import os
import re

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import StdlibMigrator, Version

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
STDLIB = StdlibMigrator()
VERSION_WITH_STDLIB = Version(
    set(),
    piggy_back_migrations=[STDLIB],
    total_graph=TOTAL_GRAPH,
)


@pytest.mark.parametrize(
    "feedstock,new_ver,expect_cbc,atr",
    [
        # package with many outputs, includes inheritance from global build env
        ("arrow", "1.10.0", False, None),
        # package without c compiler, but with selectors
        ("daal4py", "1.10.0", False, None),
        # problems with spurious selectors applied to stdlib
        ("fenics", "1.10.0", False, None),
        # package involving selectors and m2w64_c compilers, and compilers in
        # unusual places (e.g. in host & run sections)
        ("go", "1.10.0", True, None),
        # test that pure metapackages don't get stdlib added
        ("htcondor", "1.10.0", True, None),
        # package that got failed to get stdlib added
        ("mgis", "1.10.0", False, None),
        # package that reuses feedstock-name; sole global build section
        ("pagmo", "1.10.0", False, None),
        # package with rust compilers
        ("polars", "1.10.0", False, None),
        # package that intentionally reuses feedstock-name for output
        ("rdkit", "1.10.0", False, None),
        # package without compilers, but with sysroot_linux-64
        ("sinabs", "1.10.0", True, None),
        # test that we skip recipes that already contain a {{ stdlib("c") }}
        ("skip_migration", "1.10.0", False, None),
        # no-op on noatrch: python recipe
        (
            "rucio-clients",
            "34.3.0",
            False,
            [
                {
                    "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name | replace('-', '_') }}-{{ version }}.tar.gz": "https://files.pythonhosted.org/packages/91/69/9d0718180e0c88990bbda2b77e0c8cefe3dd54b13a8e2f2c969eea78a17c/rucio_clients-{{ version }}.tar.gz"
                }
            ],
        ),
        # test recipe with templated name
        ("gz-common", "5_5.6.0", False, None),
        # test recipe with quoting
        ("libhdbpp-timescale", "2.1.0", False, None),
        # test section before build
        ("unicorn", "2.0.1.post1", False, None),
        # commented compiler dep
        ("pysyntect", "0.3.0", False, None),
    ],
)
def test_stdlib(feedstock, new_ver, expect_cbc, tmp_path, atr):
    before = f"stdlib_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"stdlib_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_STDLIB,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": VERSION_WITH_STDLIB.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        should_filter=False,
        allowed_text_replacements=atr,
    )

    cbc_pth = tmp_path / "recipe/conda_build_config.yaml"
    if expect_cbc:
        with open(cbc_pth) as fp:
            lines = fp.readlines()
        assert any(re.match(r"c_stdlib_version:\s+\#\s\[linux\]", x) for x in lines)
