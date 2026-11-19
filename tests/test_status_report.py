import networkx as nx
import pytest
from test_migration_yaml_predecessors import MIGRATION_TS, _migrator
from test_migration_yaml_predecessors import _payload as _yaml_payload

from conda_forge_tick.migrators.arch import LinuxRISCV64
from conda_forge_tick.status_report import graph_migrator_status


def _payload(name, conda_forge_yml=None):
    return {
        "name": name,
        "feedstock_name": name,
        "archived": False,
        "conda-forge.yml": conda_forge_yml or {},
        "pr_info": {"PRed": []},
    }


def _graph(parent_payload):
    gx = nx.DiGraph()
    gx.add_node("lapack", payload=parent_payload)
    gx.add_node("gsl", payload=_payload("gsl"))
    gx.add_edge("lapack", "gsl")
    return gx


def test_manually_migrated_node_reports_as_done():
    # lapack got linux_riscv64 through a rerender rather than a bot PR, so there is
    # no PRed record to match the migrator uid against. It should still report as
    # done rather than landing in the "awaiting-parents" catch-all.
    gx = _graph(
        _payload("lapack", {"build_platform": {"linux_riscv64": "linux_64"}}),
    )

    migrator = LinuxRISCV64(graph=gx, effective_graph=gx.copy())
    out, _, _ = graph_migrator_status(migrator, gx)

    assert "lapack" in out["done"]
    assert "lapack" not in out["awaiting-parents"]
    # ... and its child is released for a PR rather than waiting on it
    assert "gsl" in out["awaiting-pr"]


def test_unmigrated_node_does_not_report_as_done():
    gx = _graph(_payload("lapack"))

    migrator = LinuxRISCV64(graph=gx, effective_graph=gx.copy())
    out, _, _ = graph_migrator_status(migrator, gx)

    assert "lapack" not in out["done"]
    assert "lapack" in out["awaiting-pr"]
    assert "gsl" in out["awaiting-parents"]


@pytest.mark.parametrize(
    "file_migration_number, migrated",
    [
        # libfoo carries this exact migration file without a PR from the migrator,
        # e.g., it was added by hand. It should still report as done.
        (2, True),
        # the migration was reissued with a bumped migration_number, so libfoo's
        # older copy does not count and it is not done yet
        (1, False),
    ],
)
def test_migration_yaml_file_reports_as_done(file_migration_number, migrated):
    parent = _yaml_payload(
        "libfoo",
        {
            "libfoo2": {
                "migration_number": file_migration_number,
                "migrator_ts": MIGRATION_TS,
            }
        },
    )
    migrator = _migrator(parent)
    out, _, _ = graph_migrator_status(migrator, migrator.graph)

    assert ("libfoo" in out["done"]) is migrated
