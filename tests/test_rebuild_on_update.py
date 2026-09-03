import textwrap

import networkx as nx
from test_migrators import run_test_migration

from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
from conda_forge_tick.migrators import RebuildOnUpdateMigrator
from conda_forge_tick.migrators import rebuild_on_update as rou

NAME = "golangci-lint"

CONDA_FORGE_YAML = "bot:\n  rebuild_on_update:\n    - go-nocgo\n"

RECIPE = textwrap.dedent(
    f"""\
    package:
      name: {NAME}
      version: 2.13.2

    build:
      number: 0

    requirements:
      build:
        - go-nocgo
    """
)


def test_latest_published_version(monkeypatch):
    # the newest version wins
    versions = {"1.26.2": {"linux_64"}, "1.27.1": {"linux_64", "osx_64"}}
    monkeypatch.setattr(rou, "_channel_versions", lambda name, platforms: versions)
    assert rou.latest_published_version("go-nocgo", ["linux_64"]) == "1.27.1"

    # package not on the channel at all
    monkeypatch.setattr(rou, "_channel_versions", lambda name, platforms: {})
    assert rou.latest_published_version("go-nocgo", ["linux_64"]) is None


def _make_attrs(tmp_path, cfg):
    (tmp_path / "conda-forge.yml").write_text(cfg)

    pmy = populate_feedstock_attributes(
        NAME,
        existing_node_attrs={},
        meta_yaml=RECIPE,
        conda_forge_yaml=cfg,
    )
    pmy["version"] = pmy["meta_yaml"]["package"]["version"]
    pmy["req"] = set()
    for k in ["build", "host", "run"]:
        req = pmy["meta_yaml"].get("requirements", {}) or {}
        pmy["req"] |= set(req.get(k) or set())
    pmy["raw_meta_yaml"] = RECIPE

    return pmy


def _make_graph(attrs):
    graph = nx.DiGraph()
    graph.add_node(NAME, payload=attrs)
    graph.graph["outputs_lut"] = {}
    return graph


def _make_migrator(tmp_path, monkeypatch, cfg=CONDA_FORGE_YAML, channel=None):
    if channel is None:
        channel = {"go-nocgo": {"1.27.1": {"linux_64"}}}

    monkeypatch.setattr(
        rou, "_channel_versions", lambda name, platforms: channel.get(name, {})
    )

    attrs = _make_attrs(tmp_path, cfg)
    return RebuildOnUpdateMigrator(total_graph=_make_graph(attrs))


def test_rebuild_on_update_migrator(tmp_path, monkeypatch):
    m = _make_migrator(tmp_path, monkeypatch)

    recipe_after = RECIPE.replace("number: 0", "number: 1")

    run_test_migration(
        m=m,
        inp=RECIPE,
        output=recipe_after,
        kwargs={"platforms": ["linux_64"]},
        prb="newer version published on the conda-forge",
        mr_out={
            "migrator_name": "RebuildOnUpdateMigrator",
            "migrator_version": 0,
            "name": "rebuild_on_update",
            "rebuild_on_update": {"go-nocgo": "1.27.1"},
        },
        tmp_path=tmp_path,
    )


def test_rebuild_on_update_missing_platforms_in_pr_body(tmp_path, monkeypatch):
    m = _make_migrator(
        tmp_path,
        monkeypatch,
        channel={"go-nocgo": {"1.27.1": {"linux_64"}}},
    )

    run_test_migration(
        m=m,
        inp=RECIPE,
        output=RECIPE.replace("number: 0", "number: 1"),
        kwargs={"platforms": ["linux_64", "osx_64", "win_64"]},
        prb="- go-nocgo 1.27.1 (not yet available on: osx-64, win-64)",
        mr_out={
            "migrator_name": "RebuildOnUpdateMigrator",
            "migrator_version": 0,
            "name": "rebuild_on_update",
            "rebuild_on_update": {"go-nocgo": "1.27.1"},
        },
        tmp_path=tmp_path,
    )


def test_rebuild_on_update_per_package_trigger(tmp_path, monkeypatch):
    cfg = "bot:\n  rebuild_on_update:\n    - go-nocgo\n    - not-on-channel\n"

    # go-nocgo is on the channel while the other watched package is not -
    # the rebuild for go-nocgo must not be blocked
    m = _make_migrator(
        tmp_path,
        monkeypatch,
        cfg=cfg,
        channel={"go-nocgo": {"1.27.1": {"linux_64"}}},
    )

    attrs = _make_attrs(tmp_path, cfg)
    attrs["platforms"] = ["linux_64"]

    assert m.filter(attrs) is False
    assert m.migrator_uid(attrs)["rebuild_on_update"] == {"go-nocgo": "1.27.1"}

    # if no watched package is on the channel the node is filtered out
    monkeypatch.setattr(rou, "_channel_versions", lambda name, platforms: {})
    assert m.filter(attrs) is True


def test_rebuild_on_update_not_configured(tmp_path, monkeypatch):
    m = _make_migrator(
        tmp_path,
        monkeypatch,
        cfg="bot:\n  automerge: true\n",
    )

    attrs = _make_attrs(tmp_path, "bot:\n  automerge: true\n")
    assert m.filter(attrs) is True
