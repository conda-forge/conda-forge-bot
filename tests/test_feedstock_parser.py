import pprint
import tempfile
from pathlib import Path

import pytest
from conftest import HAVE_CONTAINERS_AND_TEST_IMAGE

from conda_forge_tick.feedstock_parser import (
    _get_feedstock_commit_hash_and_timestamp,
    _get_requirements,
    load_feedstock_containerized,
    load_feedstock_local,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import parse_meta_yaml, parse_recipe_yaml


@pytest.mark.parametrize(
    "plat,arch,cfg,has_cudnn",
    [
        (
            "linux",
            "64",
            "linux_64_cuda_compiler_version10.2numpy1.19python3.9.____cpython.yaml",
            True,
        ),
        ("osx", "64", "osx_64_numpy1.16python3.6.____cpython.yaml", False),
    ],
)
def test_parse_cudnn(plat, arch, cfg, has_cudnn):
    recipe_dir = Path(__file__).parent.joinpath(
        "pytorch-cpu-feedstock", "meta_yaml", "recipe"
    )

    recipe_text = recipe_dir.joinpath("meta.yaml").read_text()

    meta = parse_meta_yaml(
        recipe_text,
        for_pinning=False,
        platform=plat,
        arch=arch,
        cbc_path=str(recipe_dir.joinpath("..", ".ci_support", cfg)),
        log_debug=True,
    )

    if has_cudnn:
        assert any(
            "cudnn" in out.get("requirements", {}).get("host", [])
            for out in meta["outputs"]
        ), pprint.pformat(meta)
    else:
        assert all(
            "cudnn" not in out.get("requirements", {}).get("host", [])
            for out in meta["outputs"]
        ), pprint.pformat(meta)


@pytest.mark.parametrize(
    "plat,cfg,has_cudnn",
    [
        (
            "linux-64",
            "linux_64_cuda_compiler_version10.2numpy1.19python3.9.____cpython.yaml",
            True,
        ),
        ("osx-64", "osx_64_numpy1.16python3.6.____cpython.yaml", False),
    ],
)
def test_parse_cudnn_recipe_yaml(plat, cfg, has_cudnn):
    recipe_dir = Path(__file__).parent.joinpath(
        "pytorch-cpu-feedstock", "recipe_yaml", "recipe"
    )
    recipe_text = recipe_dir.joinpath("recipe.yaml").read_text()

    parsed_recipe = parse_recipe_yaml(
        recipe_text,
        for_pinning=False,
        platform_arch=plat,
        cbc_path=str(recipe_dir.joinpath("..", ".ci_support", cfg)),
    )

    if has_cudnn:
        assert any(
            "cudnn" in out.get("requirements", {}).get("host", [])
            for out in parsed_recipe["outputs"]
        ), pprint.pformat(parsed_recipe)
    else:
        assert all(
            "cudnn" not in out.get("requirements", {}).get("host", [])
            for out in parsed_recipe["outputs"]
        ), pprint.pformat(parsed_recipe)


def test_get_requirements():
    meta_yaml = {
        "requirements": {"build": ["1", "2"], "host": ["2", "3"]},
        "outputs": [
            {"requirements": {"host": ["4"]}},
            {"requirements": {"run": ["5"]}},
            {"requirements": ["6"]},
        ],
    }
    assert _get_requirements({}) == set()
    assert _get_requirements(meta_yaml) == {"1", "2", "3", "4", "5", "6"}
    assert _get_requirements(meta_yaml, outputs=False) == {"1", "2", "3"}
    assert _get_requirements(meta_yaml, host=False) == {"1", "2", "5", "6"}


def test_feedstock_parser_load_feedstock_local_fenics_basix_version():
    attrs = load_feedstock_local(
        "fenics-basix",
        {},
    )
    assert attrs["feedstock_name"] == "fenics-basix"
    assert attrs["version"] == attrs["meta_yaml"]["outputs"][0]["version"]
    assert attrs["name"] == attrs["meta_yaml"]["outputs"][0]["name"]
    assert attrs["name"] == "fenics-basix"
    assert attrs["parsing_error"] is False
    assert isinstance(attrs["ci_support_migrations"], dict)
    assert any(fname.startswith("python") for fname in attrs["ci_support_migrations"])
    for k, v in attrs["ci_support_migrations"].items():
        assert any(kk == "migrator_ts" for kk in v)
        assert any(kk == "migration_number" for kk in v)


def test_get_feedstock_commit_hash_and_timestamp():
    sha, ts = _get_feedstock_commit_hash_and_timestamp("ngmix")
    assert sha is not None
    assert ts is not None


@pytest.mark.parametrize(
    "feedstock",
    [
        "pyobjc-framework-quartz",
        "nemo-relay",
        "clangdev",
        pytest.param(
            "scikit-image",
            marks=pytest.mark.xfail(reason="scikit-image recipe does not render"),
        ),
        "semi-ate-stdf",
    ],
)
def test_feedstock_parser_load_feedstock_local_succeeds(feedstock):
    attrs = load_feedstock_local(
        feedstock,
        {},
    )
    assert attrs["feedstock_name"] == feedstock
    assert attrs["parsing_error"] is False
    assert isinstance(attrs["ci_support_migrations"], dict)


@pytest.mark.skipif(
    not HAVE_CONTAINERS_AND_TEST_IMAGE, reason="containers not available"
)
@pytest.mark.parametrize(
    "feedstock",
    [
        "pyobjc-framework-quartz",
        "nemo-relay",
        "clangdev",
        pytest.param(
            "scikit-image",
            marks=pytest.mark.xfail(reason="scikit-image recipe does not render"),
        ),
        "semi-ate-stdf",
    ],
)
def test_feedstock_parser_load_feedstock_containerized_succeeds(
    use_containers, feedstock
):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
    ):
        attrs = load_feedstock_containerized(
            feedstock,
            {},
        )
        assert attrs["feedstock_name"] == feedstock
        assert attrs["parsing_error"] is False
        assert isinstance(attrs["ci_support_migrations"], dict)
