"""abi3 packages are exempt from python migrations, except free-threading ones.

An abi3 package is built once and works on every later python, so rebuilding it
for python 3.15 is pointless. A free-threaded python is different: the abi3
package pulls in ``python-gil`` through ``_python_abi3_support``, so it cannot be
installed next to a free-threaded interpreter and needs a ``cp3XXt`` build of
its own. Exempting it there both skips the build and -- because filtered nodes
are plucked out of the migration graph -- stops it gating its dependents, which
then get PRs that cannot solve.
"""

import networkx as nx
import pytest
from conftest import FakeLazyJson

from conda_forge_tick.migrators.migration_yaml import MigrationYaml

FREETHREADING_YAML = """\
migrator_ts: 1755739493
__migrator:
  commit_message: Rebuild for python 3.14 freethreading
  migration_number: 1
  operation: key_add
  primary_key: python
  exclude:
  - python
  exclude_pinned_pkgs: false
  additional_zip_keys:
  - is_freethreading
  - is_abi3
python:
- 3.14.* *_cp314t
is_freethreading:
- true
is_python_min:
- false
is_abi3:
- false
"""

GIL_YAML = """\
migrator_ts: 1755739490
__migrator:
  commit_message: Rebuild for python 3.15
  migration_number: 1
  operation: key_add
  primary_key: python
  exclude:
  - python
  exclude_pinned_pkgs: false
python:
- 3.15.* *_cp315
is_python_min:
- false
"""


def _payload(name, build, host=("python",)):
    return FakeLazyJson(
        {
            "name": name,
            "feedstock_name": name,
            "archived": False,
            "conda-forge.yml": {},
            "pr_info": {"PRed": []},
            "outputs_names": {name},
            "platforms": {"linux_64"},
            "requirements": {
                "build": set(),
                "host": set(host),
                "run": {"python"},
                "test": set(),
            },
            "meta_yaml": {
                "schema_version": 1,
                "build": build,
                "requirements": {"host": list(host), "run": ["python"]},
            },
        }
    )


ABI3 = _payload("abi3pkg", {"number": 0, "python": {"version_independent": True}})
NOARCH = _payload("noarchpkg", {"number": 0, "noarch": "python"})
COMPILED = _payload("compiledpkg", {"number": 0})
DOWNSTREAM = _payload("downstreampkg", {"number": 0}, host=("python", "abi3pkg"))

# the migrator reads package_names off the graph: the yaml keys that name a
# package built somewhere in it. conda-forge-pinning is a node in every
# migration graph.
PYTHON = _payload("python", {"number": 0}, host=())
PINNING = _payload("conda-forge-pinning", {"number": 0}, host=())


def _migrator(yaml_contents, graph):
    return MigrationYaml(
        yaml_contents,
        name="python_migration",
        migration_number=1,
        package_names={"python"},
        graph=graph,
        effective_graph=graph.copy(),
        check_solvable=False,
    )


@pytest.fixture
def graph():
    gx = nx.DiGraph()
    gx.graph["outputs_lut"] = {}
    for payload in (ABI3, NOARCH, COMPILED):
        gx.add_node(payload["feedstock_name"], payload=payload)
    return gx


@pytest.mark.parametrize(
    "attrs,filtered_out",
    [
        # needs a cp3XXt build even though it is abi3
        (ABI3, False),
        # genuinely runs on any interpreter
        (NOARCH, True),
        (COMPILED, False),
    ],
)
def test_freethreading_migration_includes_abi3(graph, attrs, filtered_out):
    migrator = _migrator(FREETHREADING_YAML, graph)
    assert migrator.filter_not_in_migration(attrs) is bool(filtered_out)


@pytest.mark.parametrize(
    "attrs,filtered_out",
    [
        # one abi3 build already covers python 3.15
        (ABI3, True),
        (NOARCH, True),
        (COMPILED, False),
    ],
)
def test_gil_migration_still_exempts_abi3(graph, attrs, filtered_out):
    migrator = _migrator(GIL_YAML, graph)
    assert migrator.filter_not_in_migration(attrs) is bool(filtered_out)


def test_abi3_node_gates_its_dependents_under_freethreading():
    # abi3pkg -> downstreampkg, i.e. downstreampkg depends on abi3pkg. Nodes
    # filtered out of the migration are plucked from migrator.graph, so an
    # exempted abi3pkg would let downstreampkg get a PR that cannot solve.
    gx = nx.DiGraph()
    gx.graph["outputs_lut"] = {}
    for payload in (ABI3, DOWNSTREAM, PYTHON, PINNING):
        gx.add_node(payload["feedstock_name"], payload=payload)
    gx.add_edge("abi3pkg", "downstreampkg")

    migrator = MigrationYaml(
        FREETHREADING_YAML,
        name="python_migration",
        migration_number=1,
        total_graph=gx,
        check_solvable=False,
    )

    assert migrator.package_names == {"python"}
    assert "abi3pkg" in migrator.graph
    assert migrator.predecessors_not_yet_built(DOWNSTREAM)
