import networkx as nx

from conda_forge_tick.migrators.arch import (
    _filter_stubby_and_ignored_nodes,
    _fold_noarch_node,
)


def _rich_feedstock_payload():
    # mirrors conda-forge/conda-forge-bot#6568: rich-feedstock produces two
    # noarch outputs, "rich" and "rich-with-jupyter", but only the latter
    # needs ipywidgets. The combined ("folded") node attrs look like this.
    meta_yaml = {
        "build": {"noarch": "python"},
        "outputs": [
            {"name": "rich", "requirements": {"host": ["python"], "run": ["python"]}},
            {
                "name": "rich-with-jupyter",
                "requirements": {
                    "host": ["python"],
                    "run": ["python", "rich", "ipywidgets"],
                },
            },
        ],
    }
    return {
        "meta_yaml": meta_yaml,
        "outputs_names": {"rich", "rich-with-jupyter"},
        "requirements": {
            "build": set(),
            "host": {"python"},
            "run": {"python", "ipywidgets"},
            "test": set(),
        },
    }


def _build_graph():
    gx = nx.DiGraph()
    gx.add_node("python", payload={"outputs_names": {"python"}, "requirements": {}})
    gx.add_node(
        "ipywidgets", payload={"outputs_names": {"ipywidgets"}, "requirements": {}}
    )
    gx.add_node("rich", payload=_rich_feedstock_payload())
    # only depends on the plain "rich" output
    gx.add_node(
        "anaconda-cli-base",
        payload={
            "outputs_names": {"anaconda-cli-base"},
            "requirements": {"host": set(), "run": {"rich"}},
        },
    )
    # depends on the "rich-with-jupyter" output specifically
    gx.add_node(
        "jupyter-thing",
        payload={
            "outputs_names": {"jupyter-thing"},
            "requirements": {"host": set(), "run": {"rich-with-jupyter"}},
        },
    )

    gx.add_edge("python", "rich")
    gx.add_edge("ipywidgets", "rich")
    gx.add_edge("rich", "anaconda-cli-base")
    gx.add_edge("rich", "jupyter-thing")

    outputs_lut = {
        "rich": {"rich"},
        "rich-with-jupyter": {"rich"},
    }
    return gx, outputs_lut


def test_fold_noarch_node_uses_output_specific_requirements():
    gx, outputs_lut = _build_graph()

    _fold_noarch_node(gx, outputs_lut, "rich")

    assert "rich" not in gx.nodes

    # anaconda-cli-base only ever depended on the "rich" output, which
    # doesn't need ipywidgets, so it must not gain a false edge from it
    assert not gx.has_edge("ipywidgets", "anaconda-cli-base")
    assert gx.has_edge("python", "anaconda-cli-base")

    # jupyter-thing genuinely depends on the "rich-with-jupyter" output,
    # which does need ipywidgets
    assert gx.has_edge("ipywidgets", "jupyter-thing")
    assert gx.has_edge("python", "jupyter-thing")


def test_filter_stubby_and_ignored_nodes_folds_noarch():
    gx, outputs_lut = _build_graph()

    _filter_stubby_and_ignored_nodes(gx, outputs_lut, ignored_packages=set())

    assert "rich" not in gx.nodes
    assert not gx.has_edge("ipywidgets", "anaconda-cli-base")
    assert gx.has_edge("ipywidgets", "jupyter-thing")
