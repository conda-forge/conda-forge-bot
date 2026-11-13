from unittest import mock

import networkx as nx
import pytest

from conda_forge_tick.migrators.arch import (
    LinuxRISCV64,
    _exclude_riscv64_from_linux_stdlib_pin,
)

STDLIB_MIGRATOR_PIN = '\nc_stdlib_version:   # [linux]\n  - "2.17"          # [linux]\n'


@pytest.mark.parametrize(
    "cbc, expected",
    [
        # the exact block written by the stdlib migrator
        (
            STDLIB_MIGRATOR_PIN,
            "\nc_stdlib_version:   # [linux and not riscv64]\n"
            '  - "2.17"          # [linux and not riscv64]\n',
        ),
        # unquoted, older pin, surrounded by other keys and an osx block
        (
            "MACOSX_DEPLOYMENT_TARGET:  # [osx]\n"
            "  - 10.13                 # [osx]\n"
            "c_stdlib_version:  # [osx]\n"
            "  - 10.13          # [osx]\n"
            "c_stdlib_version:  #[linux]\n"
            "  - 2.12           #[linux]\n"
            "\n"
            "cuda_compiler:\n"
            "  - nvcc\n",
            "MACOSX_DEPLOYMENT_TARGET:  # [osx]\n"
            "  - 10.13                 # [osx]\n"
            "c_stdlib_version:  # [osx]\n"
            "  - 10.13          # [osx]\n"
            "c_stdlib_version:  # [linux and not riscv64]\n"
            "  - 2.12           # [linux and not riscv64]\n"
            "\n"
            "cuda_compiler:\n"
            "  - nvcc\n",
        ),
    ],
)
def test_exclude_riscv64_rewrites_old_linux_pin(cbc, expected):
    assert _exclude_riscv64_from_linux_stdlib_pin(cbc) == expected


@pytest.mark.parametrize(
    "cbc",
    [
        # new enough for riscv64
        'c_stdlib_version:   # [linux]\n  - "2.39"          # [linux]\n',
        # already restricted
        "c_stdlib_version:   # [linux and not riscv64]\n"
        "  - 2.17            # [linux and not riscv64]\n",
        # platform-specific selectors that never match riscv64
        "c_stdlib_version:   # [linux64]\n  - 2.17            # [linux64]\n",
        # key not selected by linux: rewriting items only would leave an empty key
        "c_stdlib_version:   # [unix]\n"
        "  - 10.13           # [osx]\n"
        "  - 2.17            # [linux]\n",
        # item without the linux selector would be orphaned
        "c_stdlib_version:   # [linux]\n  - 2.17\n",
        # not a plain version
        "c_stdlib_version:   # [linux]\n  - {{ glibc }}     # [linux]\n",
        # no pin at all
        "cuda_compiler:\n  - nvcc\n",
    ],
)
def test_exclude_riscv64_leaves_other_pins_alone(cbc):
    assert _exclude_riscv64_from_linux_stdlib_pin(cbc) == cbc


def test_linux_riscv64_migrate_rewrites_cbc(tmp_path):
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    (recipe_dir / "meta.yaml").write_text("build:\n  number: 0\n")
    (recipe_dir / "conda_build_config.yaml").write_text(STDLIB_MIGRATOR_PIN)
    (tmp_path / "conda-forge.yml").write_text("{}\n")

    gx = nx.DiGraph()
    migrator = LinuxRISCV64(graph=gx, effective_graph=gx.copy())
    with mock.patch(
        "conda_forge_tick.migrators.core.GraphMigrator.migrate",
        return_value={"migrator_name": "LinuxRISCV64"},
    ):
        migrator.migrate(str(recipe_dir), {})

    assert (
        "[linux and not riscv64]"
        in (recipe_dir / "conda_build_config.yaml").read_text()
    )
    assert "linux_riscv64: linux_64" in (tmp_path / "conda-forge.yml").read_text()
