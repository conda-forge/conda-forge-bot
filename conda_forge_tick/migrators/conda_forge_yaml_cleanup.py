import os
from collections.abc import Callable
from typing import Any

from conda_smithy.utils import get_yaml as smithy_get_yaml
from ruamel.yaml import YAML

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.os_utils import pushd

from ..migrators_types import AttrsTypedDict


class CondaForgeYAMLCleanup(MiniMigrator):
    allowed_schema_versions = {0, 1}
    keys_to_remove = [
        "min_r_ver",
        "max_r_ver",
        "min_py_ver",
        "max_py_ver",
        "compiler_stack",
    ]
    keys_to_change = [
        "test_on_native_only",
        "abi_migration_branches",
    ]

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """Remove recipes without a conda-forge.yml file that has the keys to remove or change."""
        if super().filter(attrs):
            return True

        cfy = attrs.get("conda-forge.yml", {})
        # TODO: add a proper check
        if cfy:
            return False
        if any(key in cfy for key in (self.keys_to_remove + self.keys_to_change)):
            return False
        else:
            return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            cfg_path = os.path.join("..", "conda-forge.yml")

            # we first "round trip" the file through smithy's yaml reader
            # this takes care of duplicate line errors in that it handles them
            # just like smithy does
            smithy_yaml = smithy_get_yaml(allow_duplicate_keys=True)
            with open(cfg_path) as fp:
                cfg = smithy_yaml.load(fp.read())
            with open(cfg_path, "w") as fp:
                smithy_yaml.dump(cfg, fp)

            # now we use our own yaml parser to help with formatting
            # of spaces, indents, etc.
            yaml = YAML()
            yaml.indent(mapping=2, sequence=4, offset=2)

            with open(cfg_path) as fp:
                cfg = yaml.load(fp.read())

            for k in self.keys_to_remove:
                if k in cfg:
                    del cfg[k]

            if "test_on_native_only" in cfg:
                value = cfg["test_on_native_only"]
                del cfg["test_on_native_only"]
                if value:
                    cfg["test"] = "native_and_emulated"

            if "abi_migration_branches" in cfg:
                cfg["abi_migration_branches"] = [
                    str(v) for v in cfg["abi_migration_branches"]
                ]

            # Since we're switching workflows automatically from Azure
            # to GHA, let's also make individual settings
            # provider-independent, unless we're getting conflicting
            # values.
            azure_settings = cfg.get("azure", {})
            gha_settings = cfg.get("github_actions", {})
            azure_settings_linux = azure_settings.get("settings_linux", {})
            azure_settings_win = azure_settings.get("settings_win", {})
            azure_variables_win = azure_settings_win.get("variables", {})

            self._migrate_workflow_setting(
                azure_settings, gha_settings, cfg, "store_build_artifacts"
            )
            self._migrate_workflow_setting(
                azure_settings,
                gha_settings,
                cfg,
                "free_disk_space",
                convert=self._convert_free_disk_space,
            )

            self._migrate_pagefile_size(
                azure_settings_linux.pop("swapfile_size", None),
                azure_variables_win.pop("SET_PAGEFILE", None),
                cfg,
            )

            # Settings that are valid only for specific workflows.
            self._migrate_setting(
                gha_settings.pop("resize_win_partitions", None),
                cfg,
                "resize_partitions",
                {"provider": "github_actions", "os": "win"},
            )

            # Remove leftover empty dicts.
            if not azure_variables_win:
                azure_settings_win.pop("variables", None)
            if not azure_settings_win:
                azure_settings.pop("settings_win", None)
            if not azure_settings_linux:
                azure_settings.pop("settings_linux", None)
            if not azure_settings:
                cfg.pop("azure", None)
            if not gha_settings:
                cfg.pop("github_actions", None)

            with open(cfg_path, "w") as fp:
                yaml.dump(cfg, fp)

    @staticmethod
    def _migrate_workflow_setting(
        azure_dict: dict[str, Any],
        gha_dict: dict[str, Any],
        cfg: dict[str, Any],
        name: str,
        convert: Callable[[Any], Any] = lambda x: x,
    ) -> None:
        # Always remove old values.
        azure_val = convert(azure_dict.pop(name, None))
        gha_val = convert(gha_dict.pop(name, None))

        # Don't migrate the old value if a new one is provided already.
        if name in cfg.get("workflow_settings", {}):
            return
        if azure_val is not None:
            # If the values are different, preserve the split.
            if gha_val is not None and azure_val != gha_val:
                cfg.setdefault("workflow_settings", {})[name] = [
                    {"provider": "azure", "value": azure_val},
                    {"provider": "github_actions", "value": gha_val},
                ]
                return
            new_value = azure_val
        elif gha_val is not None:
            new_value = gha_val
        else:
            # Both values are unset, skip.
            return

        cfg.setdefault("workflow_settings", {})[name] = new_value

    @staticmethod
    def _convert_free_disk_space(value: Any) -> Any:
        # Matching the logic in conda-smithy.
        if isinstance(value, list) and "docker" in value:
            return "max"
        elif value:
            return "quick"
        elif value is not None:
            return "skip"

    @staticmethod
    def _migrate_pagefile_size(
        linux_swapfile_size: str | None,
        win_set_pagefile: bool | None,
        cfg: dict[str, Any],
    ) -> None:
        # Don't migrate the old value if a new one is provided already.
        if "pagefile_size" in cfg.get("workflow_settings", {}):
            return

        # Pagefile used to be supported on Azure only, with separate
        # keys for Linux and Windows. Extend it to GHA.
        pagefile_list = []
        # swapfile_size is "{size}GiB"
        if linux_swapfile_size is not None:
            try:
                pagefile_list.append(
                    {
                        "os": "linux",
                        "value": int(linux_swapfile_size.removesuffix("GiB")),
                    }
                )
            except ValueError:
                pass
        # SET_PAGEFILE is True for 16 GiB
        if win_set_pagefile is not None:
            pagefile_list.append({"os": "win", "value": 16 if win_set_pagefile else 0})
        if pagefile_list:
            cfg.setdefault("workflow_settings", {})["pagefile_size"] = pagefile_list

    @staticmethod
    def _migrate_setting(
        value: Any | None, cfg: dict[str, Any], name: str, params: dict[str, str]
    ) -> None:
        # Don't migrate the old value if a new one is provided already.
        if name in cfg.get("workflow_settings", {}):
            return
        if value is not None:
            cfg.setdefault("workflow_settings", {})[name] = [{**params, "value": value}]
