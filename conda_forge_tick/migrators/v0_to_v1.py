import logging
import re
import typing
from pathlib import Path
from typing import Any

from conda_recipe_manager.parser._message_table import MessageCategory, MessageTable
from conda_recipe_manager.parser.recipe_parser_convert import RecipeParserConvert
from conda_recipe_manager.parser.types import RecipeReaderFlags

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.migrators.license import _to_spdx

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)

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


def _normalize_legacy_license(raw_meta_yaml: str) -> str:
    """Rewrite a recognized legacy license string to its SPDX identifier.

    crm has its own SPDX-correction pass, but it only catches a handful of
    common mistakes and doesn't call out to a real SPDX database (see its
    ``_fix_bad_licenses``). This repo's own ``LicenseMigrator`` already has a
    broader, battle-tested mapping (e.g. ``GPL (>= 2)`` -> ``GPL-2.0-or-later``)
    that crm's matcher doesn't know about; apply it first so crm never has a
    reason to warn "Could not patch unrecognized license" for a string we
    already know how to fix.
    """

    def _repl(match: re.Match) -> str:
        value = match.group("value")
        quote = ""
        unquoted = value
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            quote = value[0]
            unquoted = value[1:-1]
        corrected = _to_spdx(unquoted)
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
        quote, before, var, after = match.groups()
        parts = []
        if before:
            parts.append(f"{quote}{before}{quote}")
        parts.append(f'env.get("{var}")')
        if after:
            parts.append(f"{quote}{after}{quote}")
        return "(" + " ~ ".join(parts) + ")"

    # A placeholder embedded inside a quoted string literal - the merged-
    # ternary case - needs the literal split into a concatenation at the
    # placeholder's position.
    content = re.sub(
        r"(['\"])([^'\"]*)" + _ENVIRON_PLACEHOLDER_RE.pattern + r"([^'\"]*)\1",
        _in_string,
        v1_content,
    )
    # A placeholder on its own (the common, non-duplicated case) is just the
    # template call.
    return _ENVIRON_PLACEHOLDER_RE.sub(
        lambda m: f'${{{{ env.get("{m.group(1)}") }}}}', content
    )


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
            if not any(ignore in msg for ignore in self.IGNORED_WARNINGS):
                blocking.append(msg)
        return blocking

    def _convert(self, raw_meta_yaml: str) -> tuple[str | None, list[str]]:
        """Attempt to convert ``raw_meta_yaml`` (schema v0) to a v1 recipe.

        Returns the converted recipe text, or ``None`` if the conversion is
        not safe to ship unattended, along with the list of messages that
        explain why (empty if the conversion is clean).
        """
        # Fix legacy license strings crm's own matcher won't recognize, and
        # hide `environ["X"]` calls before crm's duplicate-key merge can
        # mangle them - see the two functions' docstrings above.
        raw_meta_yaml = _normalize_legacy_license(raw_meta_yaml)
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
        blocking = self._actionable_messages(msg_tbl)
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
