from pathlib import Path

from conda_forge_feedstock_ops.yaml import get_yaml_parser

from conda_forge_tick.run_minimigrators import run_minimigrators

RECIPE_HEAD = """\
schema_version: 1

context:
  version: "1.0.0"

package:
  name: foo
  version: ${{ version }}

source:
  url: https://example.com/foo-${{ version }}.tar.gz
  sha256: "0000000000000000000000000000000000000000000000000000000000000000"

build:
  number: 0

"""

RECIPE_TAIL = """
about:
  license: MIT
  license_file: LICENSE
  summary: A foo
"""


CI_SUPPORT_LINUX_64 = """\
c_compiler:
- gcc
c_compiler_version:
- '13'
c_stdlib:
- sysroot
c_stdlib_version:
- '2.17'
channel_sources:
- conda-forge
channel_targets:
- conda-forge main
cdt_name:
- conda
docker_image:
- quay.io/condaforge/linux-anvil-x86_64:alma9
target_platform:
- linux-64
"""


def _run_on_recipe(tmp_path: Path, body: str):
    (tmp_path / "conda-forge.yml").write_text("conda_build_tool: rattler-build\n")
    ci_support_dir = tmp_path / ".ci_support"
    ci_support_dir.mkdir()
    (ci_support_dir / "linux_64_.yaml").write_text(CI_SUPPORT_LINUX_64)
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    recipe_path = recipe_dir / "recipe.yaml"
    recipe_path.write_text(RECIPE_HEAD + body + RECIPE_TAIL)

    run_minimigrators(tmp_path)

    with recipe_path.open() as fp:
        return get_yaml_parser(typ="rt").load(fp)


def test_run_minimigrators_v1_mapping_then_not_folded(tmp_path):
    body = """\
tests:
  - if: build_platform == target_platform
    then:
      script:
        - foo -version
  - if: build_platform == target_platform and not (win and arm64)
    then:
      script:
        - foo hello
"""
    recipe = _run_on_recipe(tmp_path, body)

    assert len(recipe["tests"]) == 2
    assert (
        recipe["tests"][1]["if"]
        == "build_platform == target_platform and not (win and arm64)"
    )


def test_run_minimigrators_v1_else_not_moved(tmp_path):
    body = """\
requirements:
  build:
    - if: not unix
      then: ${{ compiler("c") }}
    - if: not unix and c_compiler == "gcc"
      then:
        - ${{ stdlib("m2w64_c") }}
      else:
        - ${{ stdlib("c") }}
"""
    recipe = _run_on_recipe(tmp_path, body)

    build = recipe["requirements"]["build"]
    assert len(build) == 2
    assert build[1]["if"] == 'not unix and c_compiler == "gcc"'
    assert '${{ stdlib("c") }}' in build[1]["else"]
