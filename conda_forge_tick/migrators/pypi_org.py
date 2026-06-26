import os
import re

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema
from conda_forge_tick.migrators.libboost import _replacer

# detect "url: https://pypi.io/packages/..."
raw_pat_legacy_pypi = (
    r"^(?P<before>[\s\-]*url: )(?:https?://pypi\.(?:io|org)/packages/)(?P<after>.*)"
)
pat_legacy_pypi = re.compile(raw_pat_legacy_pypi)


class PyPIOrgMigrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        lines = attrs["raw_meta_yaml"].splitlines()
        has_legacy_pypi = any(pat_legacy_pypi.search(line) for line in lines)
        # filter() returns True if we _don't_ want to migrate
        return (not has_legacy_pypi) or skip_migrator_due_to_schema(
            attrs, self.allowed_schema_versions
        )

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            with open(fname) as fp:
                lines = fp.readlines()

            lines = _replacer(
                lines,
                raw_pat_legacy_pypi,
                r"\g<before>https://files.pythonhosted.org/packages/\g<after>",
            )

            with open(fname, "w") as fp:
                fp.write("".join(lines))
