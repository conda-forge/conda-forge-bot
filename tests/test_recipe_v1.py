import difflib
import io
from pathlib import Path

import networkx as nx
import pytest
from conda_forge_feedstock_ops.yaml import get_yaml_parser
from test_migrators import run_test_migration

from conda_forge_tick.migrators import (
    CombineV1ConditionsMigrator,
    Version,
)
from conda_forge_tick.migrators.recipe_v1 import (
    combine_conditions,
    get_condition,
    get_new_sub_condition,
    is_negated_condition,
    is_sub_condition,
)

YAML_PATH = Path(__file__).parent / "test_v1_yaml"

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
combine_conditions_migrator = Version(
    set(),
    piggy_back_migrations=[CombineV1ConditionsMigrator()],
    total_graph=TOTAL_GRAPH,
)


@pytest.mark.parametrize(
    "a,b",
    [
        ("unix", "not unix"),
        ('cuda_compiler_version == "None"', 'not cuda_compiler_version == "None"'),
        ('cuda_compiler_version == "None"', 'cuda_compiler_version != "None"'),
        ('not cuda_compiler_version == "None"', 'not cuda_compiler_version != "None"'),
        (
            'cuda_compiler_version != "None" and linux',
            'not (cuda_compiler_version != "None" and linux)',
        ),
        ("linux or osx", "not (linux or osx)"),
        ("a >= 14", "a < 14"),
        ("a >= 14", "not (a >= 14)"),
        ("a in [1, 2, 3]", "a not in [1, 2, 3]"),
        ("a in [1, 2, 3]", "not a in [1, 2, 3]"),
        ("a + b < 10", "a + b >= 10"),
        ("a == b == c", "not (a == b == c)"),
    ],
)
def test_is_negated_condition(a, b):
    a_cond = get_condition({"if": a})
    b_cond = get_condition({"if": b})
    assert is_negated_condition(a_cond, b_cond)
    assert is_negated_condition(b_cond, a_cond)


@pytest.mark.parametrize(
    "a,b",
    [
        ("not unix", "not unix"),
        ('cuda_compiler_version == "None"', 'not cuda_compiler_version != "None"'),
        ('cuda_compiler_version != "None"', 'not cuda_compiler_version == "None"'),
        ("a or b", "not a or b"),
        ("a and b", "not a and b"),
        ("a == b == c", "a != b != c"),
        ("a > 4", "a < 4"),
        ("a == b == c", "not (a == b) == c"),
    ],
)
def test_not_is_negated_condition(a, b):
    a_cond = get_condition({"if": a})
    b_cond = get_condition({"if": b})
    assert not is_negated_condition(a_cond, b_cond)
    assert not is_negated_condition(b_cond, a_cond)


@pytest.mark.parametrize(
    "sub_cond,super_cond,new_sub",
    [
        (
            "build_platform != target_platform and megabuild",
            "build_platform != target_platform",
            "megabuild",
        ),
        (
            "build_platform != target_platform and not megabuild",
            "build_platform != target_platform",
            "not megabuild",
        ),
        (
            'cuda_compiler_version != "None" and linux',
            'cuda_compiler_version != "None"',
            "linux",
        ),
        (
            'linux and cuda_compiler_version != "None"',
            'cuda_compiler_version != "None"',
            "linux",
        ),
        ("a and b", "a", "b"),
        ("a and b", "b", "a"),
        ("(a or b) and c", "c", "a or b"),
        ("(a or b) and c", "(a or b)", "c"),
        ("(a or b) and (c or d)", "(a or b)", "c or d"),
        ("(a or b) and (c or d)", "(c or d)", "a or b"),
        ("(a or b) and c", "a or b", "c"),
        ("(a or b) and (c or d)", "a or b", "c or d"),
        ("(a or b) and (c or d)", "c or d", "a or b"),
        ("a and b and c", "a and b", "c"),
        ("a and b and c", "c", "a and b"),
        ("a and (b and c)", "a", "b and c"),
        ("a and (b and c)", "(b and c)", "a"),
        ("a and (b and c)", "b and c", "a"),
    ],
)
def test_sub_condition(sub_cond, super_cond, new_sub):
    sub_node = get_condition({"if": sub_cond})
    super_node = get_condition({"if": super_cond})
    assert is_sub_condition(sub_node=sub_node, super_node=super_node)
    assert not is_sub_condition(sub_node=super_node, super_node=sub_node)
    assert get_new_sub_condition(sub_cond=sub_cond, super_cond=super_cond) == new_sub
    assert get_new_sub_condition(sub_cond=super_cond, super_cond=sub_cond) is None


@pytest.mark.parametrize(
    "sub_cond,super_cond",
    [
        ("a or b and c", "a"),
        ("a or b and c", "c"),
        # jinja2 interprets this as (a and b) and c, but we handle only
        # the top-most node
        ("a and b and c", "a"),
        ("a and b and c", "b and c"),
        ("a and bar", "a and b"),
        ("not (a and b)", "a and b"),
    ],
)
def test_not_sub_condition(sub_cond, super_cond):
    sub_node = get_condition({"if": sub_cond})
    super_node = get_condition({"if": super_cond})
    assert not is_sub_condition(sub_node=sub_node, super_node=super_node)
    assert not is_sub_condition(sub_node=super_node, super_node=sub_node)


def test_combine_v1_conditions(tmp_path):
    run_test_migration(
        m=combine_conditions_migrator,
        inp=YAML_PATH.joinpath("version_pytorch.yaml").read_text(),
        output=YAML_PATH.joinpath("version_pytorch_correct.yaml").read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2.6.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2.6.0",
        },
        tmp_path=tmp_path,
        recipe_version=1,
    )


def test_combine_conditions_eon():
    yaml_str = """\
context:
  version: "3.2.1"

package:
  name: eon
  version: ${{ version }}

source:
  - url: https://github.com/TheochemUI/eOn/releases/download/v${{ version }}/eon-v${{ version }}.tar.xz
    # Published asset from TheochemUI/eOn v3.2.1 (release.yml fat tarball).
    sha256: 85b5ed37659c6183cad6a15b41507217f8d5c5807d8a2b79c13fcbbfdc8c18f1
    patches:
      - 0001-win-msvc-capnp-fi-after-project.patch
    # v2.16.0 targets readcon-core 0.13 in-tree (IoStatus API); the 0.12
    # builder-API patch (use_readcon_pkgconfig.patch) is upstream and dropped.
  - url: https://github.com/OmniPotentRPC/rgpot/archive/refs/tags/v3.2.0.tar.gz
    sha256: 0bde596baad1741b79fef62e647ff7641725034d798bf346459cd274c4f451c7
    target_directory: subprojects/rgpot
    # eOn 3.2.1 wrap is rgpot v3.2.0.
  # readcon-core C-API built with cargo-c; crate deps resolve from crates.io
  # pinned by the upstream Cargo.lock (same pattern as the readcon-core
  # staged recipe).
  - url: https://github.com/lode-org/readcon-core/archive/refs/tags/v0.14.10.tar.gz
    sha256: 6b0b136e1285c3fb7832420143edd0597dadbf973f907796721b906252466e92
    target_directory: readcon-core-src

build:
  # Fortran still matters on Windows, but for the rgpot subproject rather
  # than eOn: v3.0.0 compiles no Fortran of its own, and the kernels build
  # under subprojects/rgpot. with_fortran / with_cuh2 select potentials now.
  # build.bat still forces MSVC AR=lib (not llvm-ar from flang), which is
  # what those kernels need to link (issue #15).
  number: 0
requirements:
  build:
    - ${{ compiler('c') }}
    - ${{ stdlib('c') }}
    - ${{ compiler('cxx') }}
    # win-64: flang (conda-forge) or gfortran; C++/link stay MSVC; AR=lib in build.bat
    # (issue #15 in-tree pots — see build.bat + rgoswami.me/posts/windows-compat-sci-cpp/)
    - ${{ compiler('fortran') }}
    # flang 23.1 win-64 does not ship iso_c_binding.mod; vesin cdef.f90 fails.
    - if: win
      then: flang >=21,<23
    # readcon-core C-API is built with cargo-c (lock-pinned crates.io deps);
    # headers/libs are resolved via pkg-config.
    - ${{ compiler('rust') }}
    - cargo-c
    # Required by conda-forge policy for Rust packages: bundle the licenses
    # of every transitive Rust dependency into THIRDPARTY.yml.
    - cargo-bundle-licenses
    - cmake
    - ninja
    - meson
    - pkg-config
    - sccache
    - if: (build_platform != target_platform)
      then:
        - python
        - cross-python_${{ target_platform }}
    - capnproto
    - if: osx
      then: llvm-openmp
  host:
    - python
    - pip
    - numpy
    - pyyaml
    - setuptools
    # build against CPU, CUDA at runtime
    # with linker trick
    - libtorch *cpu*
    - libtorch
    # eOn 2.16 uses ModelOutputHolder::sample_kind (per-atom API); requires
    # metatomic-torch >=0.1.15, which co-depends on metatensor-torch 0.10.x.
    - libmetatomic-torch >=0.1.15,<0.2
    - libmetatensor
    - libmetatensor-torch >=0.10,<0.11
    - xtb
    - eigen >=3.4,<3.5
    - if: win
      then:
        - libblas * *mkl
        - libcblas * *mkl
        - liblapack * *mkl
        - liblapacke * *mkl
    - if: not win
      then:
        - libblas
        - libcblas
        - liblapack
        - liblapacke
    - quill
    - capnproto
    - if: osx
      then: llvm-openmp
  run:
    - python
    - pyyaml
    - numpy
    - xtb
    - quill
    - capnproto
    - libmetatomic-torch >=0.1.15,<0.2
    - libmetatensor-torch >=0.10,<0.11
    - if: osx
      then: llvm-openmp

tests:
  - if: (build_platform == target_platform)
    then:
      script:
        - python -c "import eon"
      requirements:
        run:
          - libtorch *cpu*
  - if: (build_platform == target_platform)
    then:
      script:
        - eonclient -h
        - eonclient --version
        # Windows builds are static + no in-tree Fortran; binary must still run.
        - python -c "import eon; import sys; print('eon ok', sys.platform)"
      requirements:
        run:
          - libtorch *cpu*


about:
  homepage: https://eondocs.org/
  license: BSD-3-Clause
  license_file:
    - LICENSE
    # Bundled licenses for every Rust crate transitively pulled in by
    # readcon-core; generated by cargo-bundle-licenses in build.sh/bat.
    - readcon-THIRDPARTY.yml
  summary: "Algorithms for long time scales and potential energy surface exploration"
  description: |
    The EON software package contains algorithms used primarily to model the
    evolution of atomic scale systems over long time scales. This version is
    built with metatomic, xtb, and serve mode support.
  documentation: https://eondocs.org/index.html
  repository: https://github.com/TheochemUI/eOn

extra:
  recipe-maintainers:
    - HaoZeke
"""

    parser = get_yaml_parser(typ="rt")
    yaml = parser.load(yaml_str)
    yaml = combine_conditions(yaml)

    assert len(yaml["tests"]) == 1

    buff = io.StringIO()
    parser.dump(yaml, buff)
    new_yaml_str = buff.getvalue()

    differ = difflib.Differ()
    for line in differ.compare(yaml_str.splitlines(), new_yaml_str.splitlines()):
        print(line, flush=True)
