"""A feedstock that fails to parse keeps the attrs of its last good parse.

If those attrs put it in a migration, it must stay in the migration graph as a bot
error: plucking it would let the migration close without ever rebuilding it.
"""

import networkx as nx
from conftest import FakeLazyJson

from conda_forge_tick.migrators.migration_yaml import MigrationYaml

YAML = """\
migrator_ts: 1755739493
__migrator:
  commit_message: Rebuild for libfoo 2
  migration_number: 1
  kind: version
libfoo:
- '2'
"""


def _payload(name, host=(), parsing_error=False):
    return FakeLazyJson(
        {
            "name": name,
            "feedstock_name": name,
            "archived": False,
            "parsing_error": parsing_error,
            "conda-forge.yml": {},
            "pr_info": {"PRed": []},
            "outputs_names": {name},
            "platforms": {"linux_64"},
            "requirements": {
                "build": set(),
                "host": set(host),
                "run": set(),
                "test": set(),
            },
            "meta_yaml": {
                "schema_version": 1,
                "build": {"number": 0},
                "requirements": {"host": list(host)},
            },
        }
    )


LIBFOO = _payload("libfoo")
# its last parse found libfoo in host, the latest one failed
LIBBROKEN = _payload(
    "libbroken", host=("libfoo",), parsing_error="feedstock parsing error"
)


def test_parsing_error_node_stays_in_migration_without_a_pr():
    gx = nx.DiGraph()
    gx.graph["outputs_lut"] = {}
    for payload in (LIBFOO, LIBBROKEN):
        gx.add_node(payload["feedstock_name"], payload=payload)
    gx.add_edge("libfoo", "libbroken")
    migrator = MigrationYaml(
        YAML,
        name="libfoo2",
        migration_number=1,
        total_graph=gx,
        check_solvable=False,
    )

    assert not migrator.filter_not_in_migration(LIBBROKEN)
    assert migrator.filter_node_not_ready_to_be_migrated(LIBBROKEN)
    assert "libbroken" in migrator.graph
