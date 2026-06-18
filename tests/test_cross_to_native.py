import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import CrossToNativeMigrator

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
cross_to_native_migrator = CrossToNativeMigrator(total_graph=TOTAL_GRAPH)


TEST_YAML = """\
{% set version = "1.2.3" %}
{% set build = @BUILD@ %}

package:
  name: test
  version: {{ version }}

build:
  number: {{ build }}
"""


@pytest.mark.parametrize("provider", [None, "default", "github_actions"])
def test_cross_to_native(tmp_path, provider: str | None):
    """Test successfully migrating cross to native."""
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
        m=cross_to_native_migrator,
        inp=TEST_YAML.replace("@BUILD@", "1"),
        output=TEST_YAML.replace("@BUILD@", "2"),
        prb="GitHub Actions provide native runners for linux_aarch64 builds",
        kwargs={},
        mr_out={
            "migrator_name": "CrossToNativeMigrator",
            "migrator_version": 1,
            "name": "Cross-to-native Migrator",
        },
        tmp_path=tmp_path,
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
  linux_aarch64: {provider or "default"}
"""
    )


@pytest.mark.parametrize("provider_platform", ["linux_64", "linux_aarch64"])
def test_no_cross(tmp_path, provider_platform: str):
    """Test package with no aarch64 build and with native aarch64 build."""
    input_yaml = f"""\
provider:
  {provider_platform}: default
"""

    cfyaml = tmp_path / "conda-forge.yml"
    cfyaml.write_text(input_yaml)

    run_test_migration(
        m=cross_to_native_migrator,
        inp=TEST_YAML.replace("@BUILD@", "1"),
        output="",
        prb=None,
        kwargs={},
        mr_out=None,
        tmp_path=tmp_path,
        should_filter=True,
    )


def test_azure(tmp_path):
    """Test package using non-GHA runner."""
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
        m=cross_to_native_migrator,
        inp=TEST_YAML.replace("@BUILD@", "1"),
        output="",
        prb=None,
        kwargs={},
        mr_out=None,
        tmp_path=tmp_path,
        should_filter=True,
    )
