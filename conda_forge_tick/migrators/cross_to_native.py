from pathlib import Path
from typing import Any

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.migrators.core import Migrator
from conda_forge_tick.migrators_types import (
    AttrsTypedDict,
    CondaForgeYamlContents,
    MigrationUidTypedDict,
)
from conda_forge_tick.utils import (
    yaml_safe_dump,
    yaml_safe_load,
)


class CrossToNativeMigrator(Migrator):
    name = "Cross-to-native Migrator"
    rerender = True
    migrator_version = 1

    # platforms to migrate
    _platforms = {"linux_aarch64"}
    # build platforms where default = github_actions
    _gha_platforms = {"linux_64"}

    def _migrate_platform(self, platform: str, cfyaml: CondaForgeYamlContents) -> bool:
        build_platform = cfyaml.get("build_platform", {}).get(platform)
        if build_platform is None:
            return False
        provider = cfyaml.get("provider", {}).get(build_platform, "default")
        return provider == "github_actions" or (
            provider == "default" and build_platform in self._gha_platforms
        )

    def filter_not_in_migration(
        self, attrs: AttrsTypedDict, not_bad_str_start: str = ""
    ) -> bool:
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        # TODO: check if there are any relevant cross-targets
        cfyaml = attrs.get("conda-forge.yml", {})
        for platform in self._platforms:
            if self._migrate_platform(platform, cfyaml):
                return False

        return True

    def migrate(
        self, recipe_dir: str, attrs: AttrsTypedDict, **kwargs: Any
    ) -> MigrationUidTypedDict:
        # Only v0 recipes are supported, the handful of v1 recipes is not worth the complexity.
        recipe_file = next(
            filter(
                lambda x: x.exists(),
                (Path(recipe_dir) / "recipe.yaml", Path(recipe_dir) / "meta.yaml"),
            )
        )
        self.set_build_number(recipe_file)

        cfyaml_path = Path(recipe_dir) / "../conda-forge.yml"
        with open(cfyaml_path) as fp:
            cfyaml = yaml_safe_load(fp)

        for platform in self._platforms:
            if not self._migrate_platform(platform, cfyaml):
                continue

            build_platform = cfyaml["build_platform"].pop(platform)
            provider = cfyaml.setdefault("provider", {}).get(build_platform, "default")
            cfyaml["provider"][platform] = provider

        with open(cfyaml_path, "w") as fp:
            yaml_safe_dump(cfyaml, fp)
        return self.migrator_uid(attrs)

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text: bool = True
    ) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            f"""\
GitHub Actions provide native runners for {", ".join(self._platforms)} builds.
This migrator will attempt to switch from cross-compilation to native build.
"""
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "Migrate cross-compilation to native build"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Migrate cross-compilation to native build"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return f"cross-to-native-{self.migrator_version}"

    def migrator_uid(self, attrs: AttrsTypedDict) -> MigrationUidTypedDict:
        if self.name is None:
            raise ValueError("name is None")
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n
