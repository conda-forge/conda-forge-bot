import networkx as nx
import pytest

from conda_forge_tick.migrators.migration_yaml import MigrationYaml

MIGRATION_TS = 1757000000.0
YAML = f"""\
__migrator:
  build_number: 1
  kind: version
  migration_number: 2
migrator_ts: {MIGRATION_TS}
libfoo:
- 2
"""


def _payload(name, ci_support_migrations=None):
    return {
        "name": name,
        "feedstock_name": name,
        "archived": False,
        "conda-forge.yml": {},
        "pr_info": {"PRed": []},
        "ci_support_migrations": ci_support_migrations or {},
    }


def _migrator(parent_payload):
    # parent -> child, i.e. the child depends on the parent
    gx = nx.DiGraph()
    gx.graph["outputs_lut"] = {}
    gx.add_node("libfoo", payload=parent_payload)
    gx.add_node("bar", payload=_payload("bar"))
    gx.add_edge("libfoo", "bar")
    return MigrationYaml(
        YAML,
        name="libfoo2",
        migration_number=2,
        graph=gx,
        effective_graph=gx.copy(),
        check_solvable=False,
    )


def test_matching_migration_file_counts_as_built():
    # libfoo got the migration by hand or by a rerender, so it has no PRed record,
    # but it carries this exact migration file. Its children must not be blocked.
    parent = _payload(
        "libfoo",
        {"libfoo2": {"migration_number": 2, "migrator_ts": MIGRATION_TS}},
    )
    migrator = _migrator(parent)

    assert migrator.predecessor_already_migrated(parent)
    assert not migrator.predecessors_not_yet_built(_payload("bar"))


def test_no_migration_file_still_blocks():
    parent = _payload("libfoo")
    migrator = _migrator(parent)

    assert not migrator.predecessor_already_migrated(parent)
    assert migrator.predecessors_not_yet_built(_payload("bar"))


def test_other_migrations_file_does_not_count():
    parent = _payload(
        "libfoo",
        {"libbaz3": {"migration_number": 2, "migrator_ts": MIGRATION_TS}},
    )

    assert not _migrator(parent).predecessor_already_migrated(parent)


@pytest.mark.parametrize(
    "stale",
    [
        # mirrors conda-forge-pinning: flang19 is at migration_number 2 while a
        # feedstock may still hold the migration_number 1 copy
        {"migration_number": 1, "migrator_ts": MIGRATION_TS},
        # a changed timestamp is a distinct migration to conda-smithy
        {"migration_number": 2, "migrator_ts": MIGRATION_TS - 1},
        # a file the parser could not read anything out of
        {"migration_number": None, "migrator_ts": None},
    ],
)
def test_stale_migration_file_still_blocks(stale):
    parent = _payload("libfoo", {"libfoo2": stale})
    migrator = _migrator(parent)

    assert not migrator.predecessor_already_migrated(parent)
    assert migrator.predecessors_not_yet_built(_payload("bar"))


def test_missing_ci_support_migrations_is_not_migrated():
    # node_attrs scraped before the parser recorded migration files at all
    parent = _payload("libfoo")
    del parent["ci_support_migrations"]

    assert not _migrator(parent).predecessor_already_migrated(parent)
