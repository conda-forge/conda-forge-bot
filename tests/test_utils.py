import contextlib
import tempfile
import textwrap
from io import StringIO
from unittest import mock
from unittest.mock import MagicMock, mock_open

import networkx as nx
import pytest

from conda_forge_tick.lazy_json_backends import LazyJson
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    DEFAULT_GRAPH_FILENAME,
    _munge_dict_repr,
    extract_section_from_yaml_text,
    get_keys_default,
    get_recipe_schema_version,
    load_existing_graph,
    load_graph,
    parse_munged_run_export,
    prune,
    replace_compiler_with_stub,
    run_command_hiding_token,
)

EMPTY_JSON = "{}"
DEMO_GRAPH = """
{
    "directed": true,
    "graph": {
        "outputs_lut": {
            "package1": {
                "__set__": true,
                "elements": [
                    "package1"
                ]
            },
            "package2": {
                "__set__": true,
                "elements": [
                    "package2"
                ]
            }
        }
    },
    "links": [
        {
            "source": "package1",
            "target": "package2"
        }
    ],
    "multigraph": false,
    "nodes": [
        {
            "id": "package1",
            "payload": {
                "__lazy_json__": "node_attrs/package1.json"
            }
        }
    ]
}
"""


def test_get_keys_default():
    attrs = {
        "conda-forge.yml": {
            "bot": {
                "version_updates": {
                    "sources": ["pypi"],
                },
            },
        },
    }
    assert get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "sources"],
        {},
        None,
    ) == ["pypi"]


def test_get_keys_default_none():
    attrs = {
        "conda-forge.yml": {
            "bot": None,
        },
    }
    assert (
        get_keys_default(
            attrs,
            ["conda-forge.yml", "bot", "check_solvable"],
            {},
            False,
        )
        is False
    )


@pytest.fixture
def blas_like_graph():
    """Provide a dummy graph modeled on the ``blas`` metapackage.

    Edges point from a dependency to the package requiring it (as in the real
    conda-forge graph). ``blas`` combines several BLAS implementations;
    ``zlib``/``zstd`` are shared dependencies also used by ``numpy``/``scipy``,
    while ``tbb``/``libhwloc`` are private to a single implementation.
    """
    G = nx.DiGraph()
    # blas depends on the implementations
    G.add_edges_from(
        [
            ("openblas", "blas"),
            ("mkl", "blas"),
            ("mpich", "blas"),
            ("blis", "blas"),
        ]
    )
    # example of shared low-level deps, also needed by the science stack
    G.add_edges_from(
        [
            ("zlib", "openblas"),
            ("zlib", "mkl"),
            ("zstd", "openblas"),
            ("zstd", "mpich"),
            ("zlib", "numpy"),
            ("zstd", "scipy"),
        ]
    )
    # deps private to a single implementation
    G.add_edges_from([("tbb", "mkl"), ("libhwloc", "mpich")])
    # children of blas
    G.add_edges_from([("blas", "numpy"), ("blas", "scipy"), ("numpy", "scipy")])
    return G


def test_prune_removes_exclusive_ancestors(blas_like_graph):
    G = blas_like_graph

    prune(G, "blas")

    # blas and its children survive, as do the shared deps (needed by numpy/scipy)
    assert set(G.nodes) == {"blas", "numpy", "scipy", "zlib", "zstd"}
    # the BLAS implementations and their private deps are gone, with all edges
    assert set(G.edges) == {
        ("blas", "numpy"),
        ("blas", "scipy"),
        ("numpy", "scipy"),
        ("zlib", "numpy"),
        ("zstd", "scipy"),
    }


def test_prune_keeps_ancestors_needed_elsewhere(blas_like_graph):
    G = blas_like_graph
    # mkl is now also a direct dependency of numpy -> it (and its private dep
    # tbb, transitively) must be kept even though blas no longer needs it
    G.add_edge("mkl", "numpy")

    prune(G, "blas")

    assert set(G.nodes) == {"blas", "numpy", "scipy", "zlib", "zstd", "mkl", "tbb"}
    assert ("tbb", "mkl") in G.edges
    assert ("mkl", "numpy") in G.edges
    assert ("mkl", "blas") not in G.edges
    # the other implementations are still pruned
    assert {"openblas", "mpich", "blis", "libhwloc"}.isdisjoint(G.nodes)


def test_prune_keep_retains_listed_ancestors_and_their_deps(blas_like_graph):
    G = blas_like_graph

    prune(G, "blas", keep=["mkl"])

    # mkl is kept even though it is exclusive to blas, and so is its private
    # dependency tbb
    assert {"mkl", "tbb"} <= set(G.nodes)
    assert ("tbb", "mkl") in G.edges
    # the mkl -> blas edge survives too: edges from `keep` nodes are not cut
    assert ("mkl", "blas") in G.edges
    # the other implementations are still pruned
    assert {"openblas", "mpich", "blis", "libhwloc"}.isdisjoint(G.nodes)


def test_prune_handles_cycle_through_node_id():
    G = nx.DiGraph()
    # blas and lapack feedstocks (from the POV of the bot metadata) form a cycle
    G.add_edges_from([("blas", "lapack"), ("lapack", "blas")])
    # mkl is a private, exclusive dependency of blas
    G.add_edge("mkl", "blas")
    # numpy depends on blas and lapack
    G.add_edges_from([("blas", "numpy"), ("lapack", "numpy")])

    prune(G, "blas")

    # lapack is part of the cycle but is still needed by numpy -> kept;
    # mkl was exclusive to blas -> pruned
    assert set(G.nodes) == {"blas", "lapack", "numpy"}
    assert ("lapack", "blas") not in G.edges
    assert {("blas", "lapack"), ("blas", "numpy"), ("lapack", "numpy")} <= set(G.edges)


def test_load_graph():
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        with open(LazyJson(DEFAULT_GRAPH_FILENAME).sharded_path, "w") as fp:
            fp.write(DEMO_GRAPH)

        gx = load_graph()

        assert gx is not None

        assert gx.nodes.keys() == {"package1", "package2"}


def test_load_graph_empty_graph():
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        with open(LazyJson(DEFAULT_GRAPH_FILENAME).sharded_path, "w") as fp:
            fp.write(EMPTY_JSON)

        gx = load_graph()

        assert gx is None


@mock.patch("os.path.exists")
def test_load_graph_file_does_not_exist(exists_mock: MagicMock):
    exists_mock.return_value = False

    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        load_graph()

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME, "w")])


def test_load_existing_graph():
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        with open(LazyJson(DEFAULT_GRAPH_FILENAME).sharded_path, "w") as fp:
            fp.write(DEMO_GRAPH)

        gx = load_existing_graph()

        assert gx.nodes.keys() == {"package1", "package2"}


def test_load_existing_graph_empty_graph():
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        with open(LazyJson(DEFAULT_GRAPH_FILENAME).sharded_path, "w") as fp:
            fp.write(EMPTY_JSON)

        with pytest.raises(ValueError, match="empty JSON"):
            load_existing_graph()


@mock.patch("os.path.exists")
def test_load_existing_graph_file_does_not_exist(exists_mock: MagicMock):
    exists_mock.return_value = False

    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        with pytest.raises(ValueError, match="empty JSON"):
            load_existing_graph()

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME, "w")])


def test_munge_dict_repr():
    d = {"a": 1, "b": 2, "weak": [1, 2, 3], "strong": {"a": 1, "b": 2}}
    print(_munge_dict_repr(d))
    assert parse_munged_run_export(_munge_dict_repr(d)) == d


@pytest.mark.parametrize("version", [0, 1])
def test_get_recipe_schema_version_valid(version: int):
    attrs = {
        "meta_yaml": {
            "schema_version": version,
        }
        if version is not None
        else {},
    }

    assert get_recipe_schema_version(attrs) == version


def test_get_recipe_schema_version_missing_keys_1():
    attrs = {"meta_yaml": {}}
    assert get_recipe_schema_version(attrs) == 0


def test_get_recipe_schema_version_missing_keys_2():
    attrs = {}
    assert get_recipe_schema_version(attrs) == 0


def test_get_recipe_schema_version_invalid():
    attrs = {"meta_yaml": {"schema_version": "invalid"}}
    with pytest.raises(ValueError, match="Recipe version is not an integer"):
        get_recipe_schema_version(attrs)


def test_run_command_hiding_token():
    cmd = ["python", "-c", "print('stdTOKEN.out')"]

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        run_command_hiding_token(cmd, "TOKEN")

    assert stdout.getvalue() == "std*****.out\n"
    assert stderr.getvalue() == ""


def test_run_command_hiding_token_stderr():
    cmd = ["python", "-c", "import sys; sys.stderr.write('stdTOKEN.err')"]

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        run_command_hiding_token(cmd, "TOKEN")

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "std*****.err"


@pytest.mark.parametrize(
    "meta_yaml,section_name,result,exclude_requirements",
    [
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "host",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        host:
                          - python 3.8
                          - numpy
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "  ",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
                host:
                  - python 3.8
                  - numpy
                """
            ),
            "host",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        host:
                          - python 3.8
                          - numpy
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              host:
              - python 3.8
              - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "host",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        host:
                          - python 3.8
                          - numpy
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "  ",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "build",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          number: 1
                          string: h1234_0
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              build:
                - blah
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "build",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          number: 1
                          string: h1234_0
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
            ],
            True,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              build:
                - blah
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "build",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          number: 1
                          string: h1234_0
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          - blah
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "  ",
                ),
            ],
            False,
        ),
    ],
)
def test_extract_section_from_yaml_text(
    meta_yaml, section_name, result, exclude_requirements
):
    extracted_sections = extract_section_from_yaml_text(
        meta_yaml, section_name, exclude_requirements=exclude_requirements
    )
    assert extracted_sections == result


@pytest.mark.parametrize(
    "text, expected",
    [
        ("${{ compiler('c') }}", "c_compiler_stub"),
        ('${{   compiler( "fortran" )  }}', "fortran_compiler_stub"),
        ('${{stdlib("cxx")}}', "cxx_stdlib_stub"),
        (
            '${{ variable | default(compiler("c")) }}',
            "c_compiler_stub",
        ),
        (
            '${{ compiler("fortran") | replace("x", "y") }}',
            "fortran_compiler_stub",
        ),
        ('# compiler("fortran")', '# compiler("fortran")'),
        ("${{ c_compiler }}", "c_compiler_stub"),
        ("${{ blah | x_compiler }}", "x_compiler_stub"),
        ("${{ blah | x_compiler | foo}}", "x_compiler_stub"),
        ("${{x_compiler|foo}}", "x_compiler_stub"),
        (
            "          then: cuda-version ${{ cuda_compiler_version }}",
            "          then: cuda-version ${{ cuda_compiler_version }}",
        ),
    ],
)
def test_replace_compiler_stub(text, expected):
    assert replace_compiler_with_stub(text) == expected
