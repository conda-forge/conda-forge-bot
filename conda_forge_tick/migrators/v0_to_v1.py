import logging
import typing
from pathlib import Path
from typing import Any

from conda_recipe_manager.parser._message_table import MessageCategory, MessageTable
from conda_recipe_manager.parser.exceptions import BaseParserException
from conda_recipe_manager.parser.recipe_parser_convert import RecipeParserConvert

from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


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
    )

    def _actionable_messages(self, msg_tbl: MessageTable) -> list[str]:
        blocking = list(msg_tbl.get_messages(MessageCategory.EXCEPTION))
        blocking += msg_tbl.get_messages(MessageCategory.ERROR)
        blocking += [
            msg
            for msg in msg_tbl.get_messages(MessageCategory.WARNING)
            if not any(ignore in msg for ignore in self.IGNORED_WARNINGS)
        ]
        return blocking

    def _convert(self, raw_meta_yaml: str) -> tuple[str | None, list[str]]:
        """Attempt to convert ``raw_meta_yaml`` (schema v0) to a v1 recipe.

        Returns the converted recipe text, or ``None`` if the conversion is
        not safe to ship unattended, along with the list of messages that
        explain why (empty if the conversion is clean).
        """
        # crm can *raise* on malformed recipes (ParsingException,
        # DuplicateKeyException, ...) at construction, before any msg_tbl
        # exists to record the failure.
        try:
            converter = RecipeParserConvert(raw_meta_yaml)
            v1_content, msg_tbl, _debug = converter.render_to_v1_recipe_format()
        except BaseParserException as exc:
            return None, [f"crm raised {type(exc).__name__}: {exc}"]

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
