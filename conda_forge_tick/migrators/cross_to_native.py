from pathlib import Path
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.migrators_types import (
    AttrsTypedDict,
    CondaForgeYamlContents,
)
from conda_forge_tick.utils import (
    yaml_safe_dump,
    yaml_safe_load,
)


class CrossToNativeMigrator(MiniMigrator):
    allowed_schema_versions = {0, 1}

    # migrated platforms -> their default CI providers
    _platform_providers = {
        "linux_aarch64": "github_actions",
        "osx_arm64": "azure",
    }

    def _migrate_platform(self, platform: str, cfyaml: CondaForgeYamlContents) -> bool:
        build_platform = cfyaml.get("build_platform", {}).get(platform)
        if build_platform is None:
            return False
        provider = cfyaml.get("provider", {}).get(build_platform, "default")
        return platform in self._platform_providers and provider in (
            self._platform_providers[platform],
            "default",
        )

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """Remove recipes without a conda-forge.yml file that has the keys to remove or change."""
        if super().filter(attrs):
            return True

        # TODO: check if there are any relevant cross-targets
        cfyaml = attrs.get("conda-forge.yml", {})
        for platform in self._platform_providers:
            if self._migrate_platform(platform, cfyaml):
                return False
        return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        cfyaml_path = Path(recipe_dir) / "../conda-forge.yml"
        with open(cfyaml_path) as fp:
            cfyaml = yaml_safe_load(fp)

        for platform in self._platform_providers:
            if not self._migrate_platform(platform, cfyaml):
                continue

            del cfyaml["build_platform"][platform]
            cfyaml.setdefault("provider", {})[platform] = "default"

        with open(cfyaml_path, "w") as fp:
            yaml_safe_dump(cfyaml, fp)
