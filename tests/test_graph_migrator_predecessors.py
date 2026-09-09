import networkx as nx

from conda_forge_tick.migrators.arch import (
    ArchRebuild,
    LinuxRISCV64,
    _arches_are_configured,
)
from conda_forge_tick.migrators.core import GraphMigrator
from conda_forge_tick.utils import frozen_to_json_friendly


def _payload(name, conda_forge_yml=None, pred=None):
    return {
        "name": name,
        "feedstock_name": name,
        "archived": False,
        "conda-forge.yml": conda_forge_yml or {},
        "pr_info": {"PRed": pred or []},
    }


def _graph(parent_payload):
    # parent -> child, i.e. the child depends on the parent
    gx = nx.DiGraph()
    gx.add_node("lapack", payload=parent_payload)
    gx.add_node("gsl", payload=_payload("gsl"))
    gx.add_edge("lapack", "gsl")
    return gx


def test_predecessor_migrated_via_build_platform_counts_as_built():
    # mirrors conda-forge/conda-forge-bot: lapack got linux_riscv64 through a
    # rerender rather than a bot PR, so it has no PRed record at all. Its
    # children must not be blocked by that.
    parent = _payload(
        "lapack",
        conda_forge_yml={"build_platform": {"linux_riscv64": "linux_64"}},
    )
    migrator = LinuxRISCV64(graph=_graph(parent), effective_graph=_graph(parent))

    assert not migrator.predecessors_not_yet_built(_payload("gsl"))


def test_predecessor_migrated_via_provider_counts_as_built():
    parent = _payload(
        "lapack",
        conda_forge_yml={"provider": {"linux_riscv64": "default"}},
    )
    migrator = LinuxRISCV64(graph=_graph(parent), effective_graph=_graph(parent))

    assert not migrator.predecessors_not_yet_built(_payload("gsl"))


def test_unmigrated_predecessor_still_blocks():
    # the parent has neither the arch configured nor a PR record -> still blocked
    migrator = LinuxRISCV64(
        graph=_graph(_payload("lapack")),
        effective_graph=_graph(_payload("lapack")),
    )

    assert migrator.predecessors_not_yet_built(_payload("gsl"))


def test_predecessor_with_open_pr_still_blocks():
    parent = _payload("lapack")
    migrator = LinuxRISCV64(graph=_graph(parent), effective_graph=_graph(parent))
    muid = frozen_to_json_friendly(migrator.migrator_uid(parent))
    parent["pr_info"]["PRed"] = [{"data": muid["data"], "PR": {"state": "open"}}]

    assert migrator.predecessors_not_yet_built(_payload("gsl"))


def test_predecessor_with_merged_pr_counts_as_built():
    parent = _payload("lapack")
    migrator = LinuxRISCV64(graph=_graph(parent), effective_graph=_graph(parent))
    muid = frozen_to_json_friendly(migrator.migrator_uid(parent))
    parent["pr_info"]["PRed"] = [{"data": muid["data"], "PR": {"state": "closed"}}]

    assert not migrator.predecessors_not_yet_built(_payload("gsl"))


class _PlainGraphMigrator(GraphMigrator):
    """A graph migrator with no feedstock-visible notion of "already migrated"."""

    migrator_version = 0


def test_default_hook_does_not_treat_config_as_migrated():
    # non-arch migrators keep the old behaviour: only a PRed record counts, so an
    # arch key in conda-forge.yml means nothing to them
    parent = _payload(
        "lapack",
        conda_forge_yml={"build_platform": {"linux_riscv64": "linux_64"}},
    )
    migrator = _PlainGraphMigrator(
        name="test migration",
        graph=_graph(parent),
        effective_graph=_graph(parent),
    )

    assert not migrator.predecessor_already_migrated(parent)
    assert migrator.predecessors_not_yet_built(_payload("gsl"))


def test_arch_rebuild_predecessor_migrated_counts_as_built():
    # the same fix applies to the aarch64 migrator
    parent = _payload(
        "lapack",
        conda_forge_yml={"provider": {"linux_aarch64": "default"}},
    )
    migrator = ArchRebuild(graph=_graph(parent), effective_graph=_graph(parent))

    assert migrator.predecessor_already_migrated(parent)
    assert not migrator.predecessors_not_yet_built(_payload("gsl"))


def test_no_arches_is_not_configured():
    # an empty `arches` means there is nothing to detect, not that the feedstock is
    # configured for everything -- the latter would mark every predecessor as built
    parent = _payload(
        "lapack",
        conda_forge_yml={"build_platform": {"linux_riscv64": "linux_64"}},
    )

    assert not _arches_are_configured(parent, {})
