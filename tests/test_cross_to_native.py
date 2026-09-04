from pathlib import Path

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import CrossToNativeMigrator, Version

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION_CF = Version(
    set(),
    piggy_back_migrations=[CrossToNativeMigrator()],
    total_graph=TOTAL_GRAPH,
)

YAML_PATHS = [
    Path(__file__).parent / "test_yaml",
    Path(__file__).parent / "test_v1_yaml",
]


@pytest.mark.parametrize("provider", [None, "default", "github_actions"])
@pytest.mark.parametrize("recipe_version", [0, 1])
def test_cross_to_native(
    tmp_path: Path, provider: str | None, recipe_version: int
) -> None:
    """Test successfully migrating cross to native."""
    in_yaml = (
        YAML_PATHS[recipe_version] / "version_cfyaml_cleanup_simple.yaml"
    ).read_text()
    out_yaml = (
        YAML_PATHS[recipe_version] / "version_cfyaml_cleanup_simple_correct.yaml"
    ).read_text()

    input_yaml = """\
build_platform:
  linux_aarch64: linux_64
  linux_ppc64le: linux_64
  osx_arm64: osx_64
  win_arm64: win_64
"""
    if provider is not None:
        input_yaml += f"""\
provider:
  linux_64: {provider}
"""

    cfyaml = tmp_path / "conda-forge.yml"
    cfyaml.write_text(input_yaml)

    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )

    expected_providers = ""
    if provider is not None:
        expected_providers += f"  linux_64: {provider}\n"

    assert (
        cfyaml.read_text()
        == f"""\
build_platform:
  linux_ppc64le: linux_64
  osx_arm64: osx_64
  win_arm64: win_64
provider:
{expected_providers}\
  linux_aarch64: default
"""
    )


@pytest.mark.parametrize("provider_platform", ["linux_64", "linux_aarch64"])
@pytest.mark.parametrize("recipe_version", [0, 1])
def test_no_cross(tmp_path: Path, provider_platform: str, recipe_version: int) -> None:
    """Test package with no aarch64 build and with native aarch64 build."""
    in_yaml = (
        YAML_PATHS[recipe_version] / "version_cfyaml_cleanup_simple.yaml"
    ).read_text()
    out_yaml = (
        YAML_PATHS[recipe_version] / "version_cfyaml_cleanup_simple_correct.yaml"
    ).read_text()

    input_yaml = f"""\
provider:
  {provider_platform}: default
"""

    cfyaml = tmp_path / "conda-forge.yml"
    cfyaml.write_text(input_yaml)

    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )

    assert cfyaml.read_text() == input_yaml


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_azure(tmp_path: Path, recipe_version: int) -> None:
    """Test package using non-GHA runner."""
    in_yaml = (
        YAML_PATHS[recipe_version] / "version_cfyaml_cleanup_simple.yaml"
    ).read_text()
    out_yaml = (
        YAML_PATHS[recipe_version] / "version_cfyaml_cleanup_simple_correct.yaml"
    ).read_text()

    input_yaml = """\
build_platform:
  linux_aarch64: linux_64
  linux_ppc64le: linux_64
  osx_arm64: osx_64
  win_arm64: win_64
provider:
  linux_64: azure
"""

    cfyaml = tmp_path / "conda-forge.yml"
    cfyaml.write_text(input_yaml)

    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )

    assert cfyaml.read_text() == input_yaml
