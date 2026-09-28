import logging
import os
import random
from pathlib import Path

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import Version
from conda_forge_tick.migrators.version import VersionMigrationError

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION = Version(set(), total_graph=TOTAL_GRAPH)

YAML_PATH = Path(__file__).parent / "test_yaml"
YAML_V1_PATH = Path(__file__).parent / "test_v1_yaml"

VARIANT_SOURCES_NOT_IMPLEMENTED = (
    "Sources that depend on conda build config variants are not supported yet."
)
VERY_FLAKY_TEST = "This test case is more flaky than usual."


@pytest.mark.parametrize(
    "case,new_ver,atr",
    [
        ("mpich", "4.1.1", None),
        ("mpichv0", "4.1.0", None),
        ("dash_extensions", "0.1.11", None),
        ("numpy", "1.24.1", None),
        ("python", "3.9.5", None),
        ("faiss-split", "1.7.3", None),
        ("docker-py", "6.0.1", None),
        ("allennlp", "2.10.1", None),
        ("dbt", "1.2.0", None),
        ("jinja2expr", "1.1.1", None),
        ("weird", "1.6.0", None),
        ("compress", "0.9", None),
        ("onesrc", "2.4.1", None),
        ("multisrc", "2.4.1", None),
        pytest.param(
            "jinja2sha", "2.4.1", None, marks=pytest.mark.xfail(reason=VERY_FLAKY_TEST)
        ),
        ("r", "1.3_2", None),
        pytest.param(
            "multisrclist",
            "2.25.0",
            None,
            marks=pytest.mark.xfail(reason=VERY_FLAKY_TEST),
        ),
        ("jinja2selsha", "4.7.2", None),
        (
            "jinja2nameshasel",
            "4.7.2",
            [
                {
                    "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz": "https://files.pythonhosted.org/packages/2f/56/ce6877fb43f6da8764e7dac961aaaeef54bd0ecbded164f1fff0c824841e/antlr4-python2-runtime-{{ version }}.tar.gz",
                    "168cdcec8fb9152e84a87ca6fd261b3d54c8f6358f42ab3b813b14a7193bb50b": "580825bdd89ed6200170710cb26cc1e64f96f145870d8c2cfdf162cb0b8b9212",
                }
            ],
        ),
        ("shaquotes", "0.6.0", None),
        ("cdiff", "0.15.0", None),
        ("selshaurl", "3.7.0", None),
        ("buildbumpmpi", "7.8.0", None),
        ("multisrclistnoup", "3.11.3", None),
        ("pypiurl", "0.7.1", None),
        ("githuburl", "1.1.0", None),
        ("ccacheerr", "3.7.7", None),
        ("cranmirror", "0.3.3", None),
        ("sha1", "5.0.1", None),
        ("icu", "68.1", None),
        ("libevent", "2.1.12", None),
        ("boost", "1.74.0", None),
        ("boostcpp", "1.74.0", None),
        ("event_stream", "1.6.3", None),
        ("21cmfast", "3.4.0", None),
        ("pyrsmq", "0.6.0", None),
        ("quart_trio", "0.11.1", None),
        ("reproc", "14.2.5", None),
        (
            "riskfolio_lib",
            "6.3.1",
            [
                {
                    "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name | replace('-', '_') | lower }}-{{ version }}.tar.gz": "https://files.pythonhosted.org/packages/12/52/acaf7a457dfb0c60aed043c6170b3f8fe4cdaefd2c85c84262819572ac7a/riskfolio_lib-{{ version }}.tar.gz"
                },
            ],
        ),
        ("algotree", "0.7.3", None),
        ("py_entitymatching", "0.4.2", None),
        ("py_entitymatching_name", "0.4.2", None),
        # these contain sources that depend on conda build config variants
        pytest.param(
            "polars_mixed_selectors",
            "1.1.0",
            None,
            marks=pytest.mark.xfail(reason=VARIANT_SOURCES_NOT_IMPLEMENTED),
        ),
        pytest.param(
            "polars_name_selectors",
            "1.1.0",
            None,
            marks=pytest.mark.xfail(reason=VARIANT_SOURCES_NOT_IMPLEMENTED),
        ),
        pytest.param(
            "polars_variant_selectors",
            "1.1.0",
            None,
            marks=pytest.mark.xfail(reason=VARIANT_SOURCES_NOT_IMPLEMENTED),
        ),
        # use conda build config variants directly to select source
        (
            "polars_by_variant",
            "1.20.0",
            [
                {
                    'https://pypi.org/packages/source/p/polars/polars-{{ version }}.tar.gz  # [polars_variant == "polars"]': 'https://files.pythonhosted.org/packages/dd/8f/1005f24c8c413d8a393973fcb45e6085a2311bb513ee0c6674d438e99c31/polars-{{ version }}.tar.gz  # [polars_variant == "polars"]',
                    'https://pypi.org/packages/source/p/polars-lts-cpu/polars_lts_cpu-{{ version }}.tar.gz  # [polars_variant == "polars-lts-cpu"]': 'https://files.pythonhosted.org/packages/7f/24/025ae4beab8e9990f439218ffce8930897dfe82c0a59a1a0f1554c9cbbb2/polars_lts_cpu-{{ version }}.tar.gz  # [polars_variant == "polars-lts-cpu"]',
                    'https://pypi.org/packages/source/p/polars-u64-idx/polars_u64_idx-{{ version }}.tar.gz  # [polars_variant == "polars-u64-idx"]': 'https://files.pythonhosted.org/packages/92/02/b1e5f138b8a9cc756ca404a9db37632d739de738ab9b41b196ecbae229c8/polars_u64_idx-{{ version }}.tar.gz  # [polars_variant == "polars-u64-idx"]',
                },
            ],
        ),
        # upstream is not available
        # ("mumps", "5.2.1", None),
        # ("cb3multi", "6.0.0", None),
    ],
)
def test_version_up(case, new_ver, tmp_path, caplog, atr):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = (YAML_PATH / f"version_{case}.yaml").read_text()
    out_yaml = (YAML_PATH / f"version_{case}_correct.yaml").read_text()

    kwargs = {"new_version": new_ver}
    if case == "sha1":
        kwargs["hash_type"] = "sha1"

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        allowed_text_replacements=atr,
    )


@pytest.mark.parametrize(
    "case,new_ver",
    [
        ("pypi_url", "0.7.1"),
        ("jolt", "5.2.0"),
        ("build_number_via_context", "0.20.1"),
        ("build_as_expr", "3.11"),
        ("conditional_sources", "3.24.11"),
        ("cranmirror", "0.3.3"),
        ("event_stream", "1.6.3"),
        pytest.param(
            "selshaurl", "3.7.0", marks=pytest.mark.xfail(reason=VERY_FLAKY_TEST)
        ),
        pytest.param(
            "libssh",
            "0.11.1",
            marks=pytest.mark.xfail(reason="libssh urls tend to error a lot"),
        ),
        ("polars", "1.20.0"),
        ("svcore", "0.2025.40"),
    ],
)
def test_version_up_v1(case, new_ver, tmp_path, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = (YAML_V1_PATH / f"version_{case}.yaml").read_text()
    out_yaml = (YAML_V1_PATH / f"version_{case}_correct.yaml").read_text()

    try:
        conda_build_config = (
            YAML_V1_PATH / f"version_{case}_variants.yaml"
        ).read_text()
    except FileNotFoundError:
        conda_build_config = None

    kwargs = {"new_version": new_ver}
    if case == "sha1":
        kwargs["hash_type"] = "sha1"

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        recipe_version=1,
        conda_build_config=conda_build_config,
    )


@pytest.mark.parametrize(
    "case,new_ver",
    [
        ("badvernoup", "10.12.0"),
        ("selshaurlnoup", "3.8.0"),
        ("missingjinja2noup", "7.8.0"),
        ("nouphasurl", "3.11.3"),
        ("giturl", "7.0"),
    ],
)
def test_version_noup(case, new_ver, tmp_path, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        out_yaml = fp.read()

    with pytest.raises(VersionMigrationError) as e:
        run_test_migration(
            m=VERSION,
            inp=in_yaml,
            output=out_yaml,
            kwargs={"new_version": new_ver},
            prb="Dependencies have been updated if changed",
            mr_out={},
            tmp_path=tmp_path,
        )

    assert "The recipe did not change in the version migration," in str(e.value), (
        e.value
    )


def test_version_cupy(tmp_path, caplog):
    case = "cupy"
    new_ver = "8.5.0"
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = Path(YAML_PATH).joinpath(f"version_{case}.yaml").read_text()
    out_yaml = Path(YAML_PATH).joinpath(f"version_{case}_correct.yaml").read_text()

    kwargs = {"new_version": new_ver}

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        allowed_text_replacements=[
            {
                "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz": "https://files.pythonhosted.org/packages/14/2a/ef289e429be9021fab32f2a480a023efacb3cc9ff5e9496d788e98537c92/cupy-{{ version }}.tar.gz"
            },
        ],
    )


def test_version_rand_frac(tmp_path, caplog):
    case = "aws_sdk_cpp"
    new_ver = "1.11.132"
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    random.seed(a=new_ver)
    urand = random.uniform(0, 1)
    assert urand < 0.1

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        out_yaml = fp.read()

    kwargs = {"new_version": new_ver}
    kwargs["conda-forge.yml"] = {
        "bot": {"version_updates": {"random_fraction_to_keep": 0.1}},
    }
    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
    )
    assert "random_fraction_to_keep: 0.1" in caplog.text
