import logging
import re
import typing
from pathlib import Path
from typing import Any, Final

from conda_recipe_manager.licenses.spdx_utils import SpdxUtils
from conda_recipe_manager.parser._message_table import MessageCategory, MessageTable
from conda_recipe_manager.parser.recipe_parser_convert import RecipeParserConvert
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.types import RecipeReaderFlags

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.migrators.license import _to_spdx as _to_spdx_generic

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)

# Cached like crm's own `RecipeParserConvert._SPDX_UTILS` - parses the ~700
# entry SPDX database once rather than per lookup.
_SPDX_UTILS: Final = SpdxUtils()

# Matches a top-level `license:` field's raw value (not `license_family:`/
# `license_file:` - the colon must follow "license" immediately).
_LICENSE_LINE_RE = re.compile(
    r"(?m)^(?P<prefix>[ \t]*license:[ \t]*)(?P<value>.+?)[ \t]*$"
)

# `{{ environ["FOO"] }}` (common in R/Bioconda `license_file` fields) and a
# placeholder standing in for it while crm runs - see _hide_environ_calls.
_ENVIRON_RE = re.compile(r"""\{\{\s*environ\[['"](\w+)['"]\]\s*\}\}""")
_ENVIRON_PLACEHOLDER_FMT = "__CFTICK_ENVIRON_{}__"
_ENVIRON_PLACEHOLDER_RE = re.compile(r"__CFTICK_ENVIRON_(\w+)__")
# A single-or-double-quoted string literal, captured whole so a literal
# containing more than one placeholder (see _restore_environ_calls) can be
# split at every occurrence, not just the first.
_QUOTED_STRING_RE = re.compile(r"(['\"])((?:(?!\1).)*)\1")

# Tokens used by _malformed_output_reasons to sanity-check crm's (or our
# own text-level fixes) v1 output structurally, since crm's message table
# can report nothing at all for malformed text - see that function.
_JINJA_TOKEN_RE = re.compile(r"\$\{\{|\}\}")
_V0_SELECTOR_RE = re.compile(r"#\s*\[")

# A block-mapping `key: "..."` (or `key: '...'`) whose value opens a quote -
# see _join_folded_quoted_scalars.
_SCALAR_KEY_RE = re.compile(r"^([ \t]*[\w.-]+:[ \t]*)([\"'])")

# crm's "Could not patch unrecognized license: `X`" warning, so the license
# string can be pulled back out for GenericV0ToV1Migrator._is_safe_compound_spdx_expression.
_UNRECOGNIZED_LICENSE_RE = re.compile(
    r"^Could not patch unrecognized license: `(?P<license>.+)`$"
)


def _find_scalar_close(text: str, quote: str) -> int:
    r"""Given a quote character, find where it closes in
    ``text`` (-1 if it doesn't), respecting ``\"``
    and ``''`` escapes.
    """
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote == '"' and ch == "\\":
            i += 2
            continue
        if ch == quote:
            if quote == "'" and i + 1 < n and text[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return -1


def _join_folded_quoted_scalars(raw_meta_yaml: str) -> str:
    """Join a quoted scalar value that YAML folds across multiple physical
    lines back onto a single line.

    YAML folds a line break inside a quoted scalar into a single space, so
    this is a semantic no-op - but crm's recipe reader parses selectors line
    by line, and a continuation line shaped like ``'word' more: words``
    (quote-led, with a colon later in the line) gets misread as its own
    key/value pair instead of plain scalar content, crashing with a raw
    ``ParsingException`` instead of a clean warning (real example:
    r-stringi's ``about/summary``, a long description wrapped across two
    lines). Physically joining the fold before crm ever sees it removes the
    ambiguous line shape entirely.
    """
    lines = raw_meta_yaml.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _SCALAR_KEY_RE.match(line)
        if not match:
            out.append(line)
            i += 1
            continue
        quote = match.group(2)
        if _find_scalar_close(line[match.end() :], quote) != -1:
            out.append(line)
            i += 1
            continue

        chunk = [line]
        j = i + 1
        closed = False
        while j < len(lines):
            chunk.append(lines[j])
            closed = _find_scalar_close(lines[j].strip(), quote) != -1
            j += 1
            if closed:
                break
        if not closed:
            # Genuinely unclosed/malformed - leave as-is and let crm raise
            # its own error rather than silently swallowing lines.
            out.append(line)
            i += 1
            continue
        out.append(chunk[0] + "".join(" " + c.strip() for c in chunk[1:]))
        i = j
    return "\n".join(out)


def _normalize_legacy_license(raw_meta_yaml: str, to_spdx) -> str:
    """Rewrite a recognized legacy license string to its SPDX identifier.

    crm has its own SPDX-correction pass, but it only catches a handful of
    common mistakes and doesn't call out to a real SPDX database. ``to_spdx``
    is a callable mapping a legacy string to its SPDX identifier (a no-op if
    it doesn't recognize the string) - normally ``GenericV0ToV1Migrator._to_spdx``
    or a subclass's override of it - applied here so crm never has a reason
    to warn "Could not patch unrecognized license" for a string we already know
    how to fix.
    """

    def _repl(match: re.Match) -> str:
        value = match.group("value")
        quote = ""
        unquoted = value
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            quote = value[0]
            unquoted = value[1:-1]
        corrected = to_spdx(unquoted)
        if corrected == unquoted:
            return match.group(0)
        return f"{match.group('prefix')}{quote}{corrected}{quote}"

    return _LICENSE_LINE_RE.sub(_repl, raw_meta_yaml)


def _hide_environ_calls(raw_meta_yaml: str) -> str:
    """Replace ``{{ environ["X"] }}`` with an inert placeholder before crm
    sees it.

    crm's own conversion of ``environ["X"]`` -> ``env.get("X")`` is correct
    for a single occurrence, but when a key is duplicated per-selector (e.g.
    ``license_file: ...  # [unix]`` / ``# [win]``) and both values contain
    their own templated expression, crm's duplicate-key ternary merge
    produces malformed, unparsable output (mismatched ``${{``/``}}``) with
    no warning at all - the base class's safe-to-auto-convert check has no
    way to catch it. Hiding the call behind a plain-text placeholder makes
    crm treat it as an ordinary string for the merge, which it already
    handles correctly; ``_restore_environ_calls`` puts the real call back
    afterward.
    """
    return _ENVIRON_RE.sub(
        lambda m: _ENVIRON_PLACEHOLDER_FMT.format(m.group(1)), raw_meta_yaml
    )


def _restore_environ_calls(v1_content: str) -> str:
    """Undo ``_hide_environ_calls`` in crm's v1 output."""

    def _in_string(match: re.Match) -> str:
        quote, body = match.group(1), match.group(2)
        if not _ENVIRON_PLACEHOLDER_RE.search(body):
            return match.group(0)

        # A value can have more than one `environ[...]` call in it.
        # Split at every placeholder, not just the first - otherwise
        # the second one is left behind as plain text, and the fallback
        # pass further down wraps it in its own `${{ ... }}`.
        parts = []
        pos = 0
        for m in _ENVIRON_PLACEHOLDER_RE.finditer(body):
            if m.start() > pos:
                parts.append(f"{quote}{body[pos : m.start()]}{quote}")
            parts.append(f'env.get("{m.group(1)}")')
            pos = m.end()
        if pos < len(body):
            parts.append(f"{quote}{body[pos:]}{quote}")
        return "(" + " ~ ".join(parts) + ")"

    # A placeholder embedded inside a quoted string literal - the merged-
    # ternary case - needs the literal split into a concatenation at the
    # placeholder's position(s).
    content = _QUOTED_STRING_RE.sub(_in_string, v1_content)
    # A placeholder on its own (the common, non-duplicated case) is just the
    # template call.
    return _ENVIRON_PLACEHOLDER_RE.sub(
        lambda m: f'${{{{ env.get("{m.group(1)}") }}}}', content
    )


def _malformed_output_reasons(v1_content: str) -> list[str]:
    """Find structural problems in crm's v1 output that its message table
    can miss entirely.

    crm or our own text-level fixes above can produce malformed v1 text
    with an empty message table: mismatched ``${{``/``}}``, or a duplicate
    key left over from a failed selector merge. That output may still be
    valid YAML in every such case seen so far, so a plain YAML parse isn't a
    useful check; these are.
    """
    reasons: list[str] = []

    # A v1 recipe should never have duplicate keys - that's a v0 selector
    # idiom, resolved into `if`/`then` blocks during conversion. Note the
    # deliberate absence of ALLOW_DUPLICATE_KEYS here, unlike the v0 read in
    # _convert().
    # Therefore a duplicate key surviving into v1 output would mean a merge
    # failed.
    try:
        RecipeReader(v1_content)
    except Exception as exc:
        reasons.append(
            f"generated recipe.yaml does not re-parse: {type(exc).__name__}: {exc}"
        )

    for lineno, line in enumerate(v1_content.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if _V0_SELECTOR_RE.search(line):
            reasons.append(f"line {lineno}: leftover v0 selector: {stripped}")

        depth = 0
        for token in _JINJA_TOKEN_RE.findall(line):
            if token == "${{":
                if depth:
                    reasons.append(f"line {lineno}: nested `${{{{`")
                depth += 1
            else:
                depth -= 1
                if depth < 0:
                    reasons.append(f"line {lineno}: unmatched `}}}}`")
                    break
        if depth > 0:
            reasons.append(f"line {lineno}: unclosed `${{{{`")

    return reasons


class GenericV0ToV1Migrator(MiniMigrator):
    """Convert a schema v0 ``meta.yaml`` recipe to a schema v1 ``recipe.yaml``.

    This only knows about the ``conda-recipe-manager`` (``crm``) conversion
    mechanics: it converts the recipe and skips (with a warning, leaving the
    recipe untouched) any conversion that comes back with actionable
    messages rather than shipping something broken. Subclasses layer
    package-specific pre/post-processing - and extend ``IGNORED_WARNINGS`` -
    on top of this class; nothing package-specific lives here.
    """

    allowed_schema_versions = [0]

    # Warnings that are safe to ignore: crm emits them but the produced
    # recipe.yaml is already correct. Extend in subclasses, don't rewrite the
    # safe-to-auto-convert check itself.
    IGNORED_WARNINGS: tuple[str, ...] = (
        # crm already removes the deprecated field, the warning is just noise.
        "Field at `/about/license_family` is no longer supported.",
        # crm already patched `license` to a corrected SPDX identifier (e.g.
        # `GPL-2` -> `GPL-2.0-only`, matching this repo's own LicenseMigrator
        # mapping in migrators/license.py) before emitting this - it's just
        # noting the change, not something that needs manual review.
        "license from `",
    )

    def _actionable_messages(self, msg_tbl: MessageTable) -> list[str]:
        blocking = [
            *msg_tbl.get_messages(MessageCategory.EXCEPTION),
            *msg_tbl.get_messages(MessageCategory.ERROR),
        ]
        for msg in msg_tbl.get_messages(MessageCategory.WARNING):
            if any(ignore in msg for ignore in self.IGNORED_WARNINGS):
                continue
            unrecognized_license = _UNRECOGNIZED_LICENSE_RE.match(msg)
            if unrecognized_license and self._is_safe_compound_spdx_expression(
                unrecognized_license.group("license")
            ):
                continue
            blocking.append(msg)
        return blocking

    def _is_safe_compound_spdx_expression(self, lic: str) -> bool:
        """Check whether ``lic`` is a two-part ``A OR B`` SPDX expression
        whose sides are both already exact, valid SPDX identifiers.

        crm's own SPDX matcher deliberately declines to touch *any* license
        string containing ``AND``/``OR``/``WITH``, even a perfectly valid
        one, to avoid mangling a compound expression it wasn't designed to
        parse - so it warns "Could not patch unrecognized license" on an
        already-correct expression just as readily as a genuinely bad one
        (real example: r-icenreg's ``LGPL-2.0-only OR LGPL-2.1-only``).
        Confirming both sides independently resolve to themselves lets us
        treat that specific warning as safe to ignore - the field is left
        untouched either way, so there's nothing to rewrite.
        """
        parts = lic.split(" OR ")
        if len(parts) != 2:
            return False
        return all(
            _SPDX_UTILS.find_closest_license_match(part) == part for part in parts
        )

    def _to_spdx(self, lic: str) -> str:
        """Map a legacy license string to its SPDX identifier, if recognized.

        Delegates verbatim to this repo's shared ``LicenseMigrator`` mapping
        (``migrators/license.py``) - nothing package-specific lives here.
        Subclasses override this method (not ``IGNORED_WARNINGS``) to layer
        their own mappings on top without touching the shared table; see
        ``RV0ToV1Migrator._to_spdx`` for the R-specific "Unlimited" case.
        """
        return _to_spdx_generic(lic)

    def _convert(self, raw_meta_yaml: str) -> tuple[str | None, list[str]]:
        """Attempt to convert ``raw_meta_yaml`` (schema v0) to a v1 recipe.

        Returns the converted recipe text, or ``None`` if the conversion is
        not safe to ship unattended, along with the list of messages that
        explain why (empty if the conversion is clean).
        """
        # Join folded multi-line quoted scalars before crm's line-based reader can misparse a continuation line.
        raw_meta_yaml = _join_folded_quoted_scalars(raw_meta_yaml)
        # Fix legacy license strings crm's own matcher won't recognize.
        raw_meta_yaml = _normalize_legacy_license(raw_meta_yaml, self._to_spdx)
        # Hide `environ["X"]` calls before crm's duplicate-key merge can mangle them.
        raw_meta_yaml = _hide_environ_calls(raw_meta_yaml)

        # Mirrors what the `crm convert` CLI always does otherwise (e.g.
        # normalizing multiline strings, `min_pin`/`max_pin` renames) and
        # allows the ordinary `key: val  # [selector]` duplicate-key pattern
        # that's otherwise extremely common in conda-forge recipes.
        content = RecipeParserConvert.pre_process_recipe_text(raw_meta_yaml)

        # crm can raise - or, on some malformed/unusual recipes (e.g.
        # multi-output), crash with an unrelated exception - at construction
        # or during conversion, before any msg_tbl exists to record why. Any
        # of that means this recipe isn't safe to auto-convert.
        try:
            converter = RecipeParserConvert(
                content, flags=RecipeReaderFlags.ALLOW_DUPLICATE_KEYS
            )
            v1_content, msg_tbl, _debug = converter.render_to_v1_recipe_format()
        except Exception as exc:
            logger.debug("CRM failed to convert", exc_info=exc)
            return None, [f"crm raised {type(exc).__name__}: {exc}"]

        v1_content = _restore_environ_calls(v1_content)

        # crm's message table is not a fully trustworthy signal: it has
        # produced malformed output (mismatched `${{`/`}}`, a duplicate key
        # left over from a failed merge) while reporting no warnings or
        # errors at all. Structurally sanity-check the text itself too,
        # rather than shipping something broken just because nothing in
        # msg_tbl complained.
        blocking = self._actionable_messages(msg_tbl)
        blocking += _malformed_output_reasons(v1_content)
        if blocking:
            return None, blocking
        return v1_content, []

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        meta_yaml_path = Path(recipe_dir) / "meta.yaml"
        if not meta_yaml_path.exists():
            return

        v1_content, blocking = self._convert(meta_yaml_path.read_text())
        if blocking:
            logger.warning(
                "Skipping v0 -> v1 conversion for %s: not safe to auto-convert:\n%s",
                attrs.get("name", recipe_dir),
                "\n".join(blocking),
            )
            return

        assert v1_content is not None
        (Path(recipe_dir) / "recipe.yaml").write_text(v1_content)
        meta_yaml_path.unlink()
