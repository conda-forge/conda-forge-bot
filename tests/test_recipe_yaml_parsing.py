import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from conda_forge_tick.feedstock_parser import (
    populate_feedstock_attributes,
)
from conda_forge_tick.migrators.migration_yaml import all_noarch
from conda_forge_tick.utils import (
    _parse_recipe_yaml_requirements,
    _process_recipe_for_pinning,
    _render_recipe_yaml,
    parse_meta_yaml,
    parse_munged_run_export,
    parse_recipe_yaml,
)

TEST_RECIPE_YAML_PATH = Path(__file__).parent / "test_recipe_yaml"
TEST_META_YAML_PATH = Path(__file__).parent / "test_yaml"


def test_render_recipe_yaml():
    text = TEST_RECIPE_YAML_PATH.joinpath("ipywidgets.yaml").read_text()
    data = _render_recipe_yaml(text)
    package_data = data[0]["package"]

    assert package_data["name"] == "ipywidgets"
    assert package_data["version"] == "8.1.2"


def test_parse_validated_recipes():
    text = TEST_RECIPE_YAML_PATH.joinpath("mplb.yaml").read_text()
    recipe_yaml_dict = parse_recipe_yaml(text)

    text = TEST_META_YAML_PATH.joinpath("mplb.yaml").read_text()
    meta_yaml_dict = parse_meta_yaml(text)

    for key in ["about", "build", "package", "requirements", "source", "extra"]:
        assert recipe_yaml_dict[key] == meta_yaml_dict[key]


def test_parse_recipe_yaml_keeps_python_version_independent():
    """``build.python.version_independent`` marks an abi3 build.

    ``all_noarch(only_python=True)`` reads it to decide that a feedstock does not
    need rebuilding for every python version, which keeps it out of the python
    migrations. Dropping the key at parse time made that check unreachable.
    """
    text = TEST_RECIPE_YAML_PATH.joinpath("abi3_pkg.yaml").read_text()
    recipe_yaml_dict = parse_recipe_yaml(text)

    assert recipe_yaml_dict["build"]["python"]["version_independent"] is True
    assert all_noarch({"meta_yaml": recipe_yaml_dict}, only_python=True)


def test_parse_recipe_yaml_keeps_per_output_build_section():
    """Each output's `build` section must survive parsing.

    It used to be replaced by the output's run exports, so `noarch` and
    `build.python` were unreachable for multi-output v1 recipes and
    `_extract_requirements` could not find run exports under `build` either.
    """
    text = TEST_RECIPE_YAML_PATH.joinpath("multi_output_build.yaml").read_text()
    recipe_yaml_dict = parse_recipe_yaml(text)

    builds = {output["name"]: output["build"] for output in recipe_yaml_dict["outputs"]}

    assert builds["multi_output_build"]["noarch"] == "python"
    assert builds["libmulti"]["run_exports"] == {"weak": ["libmulti"]}

    # _remove_none_values does not recurse into lists, so unset keys must be
    # omitted rather than stored as None; `"noarch" in build` is a consumer.
    assert all(
        value is not None for build in builds.values() for value in build.values()
    )

    # the only python-dependent output is noarch, so the feedstock does not
    # need rebuilding for each python version
    assert all_noarch({"meta_yaml": recipe_yaml_dict}, only_python=True)


@pytest.mark.parametrize(
    "is_abi3_per_variant,version_independent",
    [
        (["true", "true"], True),
        (["true", "false"], False),
        (["false", "false"], False),
    ],
)
def test_populate_feedstock_attributes_version_independent_needs_every_variant(
    is_abi3_per_variant, version_independent
):
    """A recipe is only version independent if every variant is.

    abi3 recipes commonly build one wheel covering python >=3.12 and version
    specific ones for the rest, e.g. an older python or a free threaded build.
    Reporting the feedstock as version independent overall would take it out of
    the python migrations it still needs.
    """
    recipe_yaml = TEST_RECIPE_YAML_PATH / "conditional_abi3_pkg.yaml"

    with TemporaryDirectory() as tmpdir:
        os.makedirs(Path(tmpdir) / "recipe", exist_ok=True)
        os.makedirs(Path(tmpdir) / ".ci_support", exist_ok=True)
        shutil.copy2(recipe_yaml, Path(tmpdir) / "recipe" / "recipe.yaml")
        for i, is_abi3 in enumerate(is_abi3_per_variant):
            (Path(tmpdir) / ".ci_support" / f"linux_64_v{i}.yaml").write_text(
                f"target_platform:\n - 'linux-64'\nis_abi3:\n - {is_abi3}\n"
            )
        node_attrs = populate_feedstock_attributes(
            "conditional_abi3_pkg",
            {},
            recipe_yaml=recipe_yaml.read_text(),
            feedstock_dir=tmpdir,
        )

    build_python = (node_attrs["meta_yaml"].get("build") or {}).get("python") or {}
    assert build_python.get("version_independent", False) is version_independent
    assert all_noarch(node_attrs, only_python=True) is version_independent


def test_process_recipe_for_pinning():
    input_recipes = [
        {
            "some_key": {
                "pin_subpackage": {"name": "example_package", "upper_bound": "x.x"}
            }
        },
        {
            "another_key": [
                {
                    "pin_compatible": {
                        "name": "another_package",
                        "lower_bound": "x.x.x.x",
                    }
                }
            ]
        },
    ]
    expected_result = [
        {
            "some_key": {
                "pin_subpackage": {
                    "name": "__quote_plus__%7B%27package_name%27%3A+%27example_package%27%2C+%27upper_bound%27%3A+%27x.x%27%7D__quote_plus__"
                },
            }
        },
        {
            "another_key": [
                {
                    "pin_compatible": {
                        "name": "__quote_plus__%7B%27package_name%27%3A+%27another_package%27%2C+%27lower_bound%27%3A+%27x.x.x.x%27%7D__quote_plus__"
                    },
                }
            ]
        },
    ]

    assert _process_recipe_for_pinning(input_recipes) == expected_result


def test_parse_recipe_yaml_requirements_pin_subpackage():
    requirements = {
        "run_exports": {
            "weak": [
                {
                    "pin_subpackage": {
                        "name": "slepc",
                        "lower_bound": "x.x.x.x.x.x",
                        "upper_bound": "x.x",
                    }
                }
            ]
        }
    }

    _parse_recipe_yaml_requirements(requirements)
    assert requirements["run_exports"]["weak"] == ["slepc"]


def test_parse_recipe_yaml_requirements_pin_compatible():
    requirements = {
        "run_exports": {
            "strong": [
                {
                    "pin_compatible": {
                        "name": "slepc",
                        "lower_bound": "x.x.x.x.x.x",
                        "upper_bound": "x.x",
                    }
                }
            ]
        }
    }

    _parse_recipe_yaml_requirements(requirements)
    assert requirements["run_exports"]["strong"] == ["slepc"]


def test_parse_recipe_yaml_requirements_str():
    requirements = {"run_exports": {"weak": ["slepc"]}}

    _parse_recipe_yaml_requirements(requirements)
    assert requirements["run_exports"]["weak"] == ["slepc"]


def test_parse_munged_run_export_slepc():
    recipe = TEST_RECIPE_YAML_PATH.joinpath("slepc.yaml").read_text()
    recipe_yaml = parse_recipe_yaml(
        recipe,
        for_pinning=True,
    )
    assert recipe_yaml["build"]["run_exports"]["weak"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27slepc%27%2C+%27lower_bound%27%3A+%27x.x.x.x.x.x%27%2C+%27upper_bound%27%3A+%27x.x%27%7D__quote_plus__"
    ]

    assert parse_munged_run_export(recipe_yaml["build"]["run_exports"]["weak"][0]) == {
        "package_name": "slepc",
        "lower_bound": "x.x.x.x.x.x",
        "upper_bound": "x.x",
    }


def test_parse_munged_run_export_slepc_weak_strong():
    recipe = TEST_RECIPE_YAML_PATH.joinpath("slepc_weak_strong.yaml").read_text()
    recipe_yaml = parse_recipe_yaml(
        recipe,
        for_pinning=True,
    )
    assert recipe_yaml["build"]["run_exports"]["weak"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27slepc%27%2C+%27lower_bound%27%3A+%27x.x.x.x.x.x%27%2C+%27upper_bound%27%3A+%27x.x%27%7D__quote_plus__"
    ]

    assert recipe_yaml["build"]["run_exports"]["strong"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27slepc%27%2C+%27lower_bound%27%3A+%27x.x.x.x.x.x%27%2C+%27upper_bound%27%3A+%27x%27%7D__quote_plus__"
    ]

    assert parse_munged_run_export(recipe_yaml["build"]["run_exports"]["weak"][0]) == {
        "package_name": "slepc",
        "lower_bound": "x.x.x.x.x.x",
        "upper_bound": "x.x",
    }

    assert parse_munged_run_export(
        recipe_yaml["build"]["run_exports"]["strong"][0]
    ) == {
        "package_name": "slepc",
        "lower_bound": "x.x.x.x.x.x",
        "upper_bound": "x",
    }


@pytest.mark.parametrize("recipe_name", ["libssh", "torchvision-reduced"])
def test_populate_feedstock_attributes(recipe_name):
    """Test parsing different recipe files."""
    recipe_yaml = TEST_RECIPE_YAML_PATH / f"{recipe_name}.yaml"

    with TemporaryDirectory() as tmpdir:
        os.makedirs(Path(tmpdir) / "recipe", exist_ok=True)
        os.makedirs(Path(tmpdir) / ".ci_support", exist_ok=True)
        shutil.copy2(
            TEST_RECIPE_YAML_PATH / f"{recipe_name}.yaml",
            Path(tmpdir) / "recipe" / "recipe.yaml",
        )
        (Path(tmpdir) / ".ci_support" / "linux_64_.yaml").write_text(
            "target_platform:\n - 'linux-64'\ncuda_compiler_version:\n  - 'None'\n"
        )
        existing_attrs = {}
        node_attrs = populate_feedstock_attributes(
            recipe_name,
            existing_attrs,
            recipe_yaml=recipe_yaml.read_text(),
            feedstock_dir=tmpdir,
        )

    assert node_attrs["feedstock_name"] == recipe_name
    for key, value in node_attrs["total_requirements"].items():
        assert isinstance(value, set)
        for el in value:
            assert isinstance(el, str)


def test_populate_feedstock_attributes_staging_outputs():
    """Build/host deps declared in a staging output must appear in the
    parsed feedstock attributes, otherwise pinning migrations won't
    know that this feedstock needs to be rebuilt.
    """
    recipe_text = """\
outputs:
  - staging:
      name: shared-build
    source:
      url: https://example.com/foo-1.0.tar.gz
      sha256: "0000000000000000000000000000000000000000000000000000000000000000"
    requirements:
      build:
        - cxx_compiler_stub
      host:
        - cudnn 9.*
        - python
  - package:
      name: foo
      version: "1.0"
    inherit: shared-build
    requirements:
      host:
        - numpy
      run:
        - python
        - numpy
about:
  license: MIT
  summary: test
"""

    with TemporaryDirectory() as tmpdir:
        os.makedirs(Path(tmpdir) / "recipe", exist_ok=True)
        os.makedirs(Path(tmpdir) / ".ci_support", exist_ok=True)
        (Path(tmpdir) / "recipe" / "recipe.yaml").write_text(recipe_text)
        (Path(tmpdir) / ".ci_support" / "linux_64_.yaml").write_text("""\
target_platform:
  - linux-64
""")
        node_attrs = populate_feedstock_attributes(
            "foo",
            {},
            recipe_yaml=recipe_text,
            feedstock_dir=tmpdir,
        )

    build_reqs = node_attrs["total_requirements"]["build"]
    assert "cxx_compiler_stub" in build_reqs

    host_reqs = node_attrs["total_requirements"]["host"]
    # from staging
    assert "cudnn 9.*" in host_reqs
    assert "python" in host_reqs
    # from the package output itself
    assert "numpy" in host_reqs

    run_reqs = node_attrs["total_requirements"]["run"]
    assert "python" in run_reqs
    assert "numpy" in run_reqs
