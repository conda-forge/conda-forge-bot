import os
import pprint
import subprocess

import networkx as nx
from test_migrators import sample_yaml_rebuild, updated_yaml_rebuild

from conda_forge_tick.migration_runner import run_migration, run_migration_local
from conda_forge_tick.migrators import MigrationYaml, Version
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import parse_meta_yaml


class NoFilter:
    def filter(self, attrs, not_bad_str_start=""):
        return False


class _MigrationYaml(NoFilter, MigrationYaml):
    pass


TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
yaml_rebuild = _MigrationYaml(yaml_contents="{}", name="hi", total_graph=TOTAL_GRAPH)


def test_migration_runner_run_migration_local_yaml_rebuild(tmpdir):
    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as f:
        f.write(sample_yaml_rebuild)

    with pushd(tmpdir):
        subprocess.run(["git", "init", "-b", "main"])
    # Load the meta.yaml (this is done in the graph)
    try:
        pmy = parse_meta_yaml(sample_yaml_rebuild)
    except Exception:
        pmy = {}
    if pmy:
        pmy["version"] = pmy["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            pmy["req"] |= set(pmy.get("requirements", {}).get(k, set()))
        try:
            pmy["meta_yaml"] = parse_meta_yaml(sample_yaml_rebuild)
        except Exception:
            pmy["meta_yaml"] = {}
    pmy["raw_meta_yaml"] = sample_yaml_rebuild

    migration_data = run_migration_local(
        migrator=yaml_rebuild,
        feedstock_dir=tmpdir,
        feedstock_name="scipy",
        node_attrs=pmy,
        default_branch="main",
    )

    pprint.pprint(migration_data)

    assert migration_data["migrate_return_value"] == {
        "migrator_name": yaml_rebuild.__class__.__name__,
        "migrator_version": yaml_rebuild.migrator_version,
        "name": "hi",
        "bot_rerun": False,
    }
    assert migration_data["commit_message"] == "Rebuild for hi"
    assert migration_data["pr_title"] == "Rebuild for hi"
    assert migration_data["pr_body"].startswith(
        "This PR has been triggered in an effort to update "
        "[**hi**](https://conda-forge.org/status/migration/?name=hi)."
    )

    with open(os.path.join(tmpdir, "recipe/meta.yaml")) as f:
        actual_output = f.read()
    assert actual_output == updated_yaml_rebuild
    assert os.path.exists(os.path.join(tmpdir, ".ci_support/migrations/hi.yaml"))
    with open(os.path.join(tmpdir, ".ci_support/migrations/hi.yaml")) as f:
        saved_migration = f.read()
    assert saved_migration == yaml_rebuild.yaml_contents


def test_migration_runner_run_migration_version_gnureadline(tmpdir):
    recipe = """\
{% set name = "gnureadline" %}
{% set version = "8.2.13" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.org/packages/source/{{ name[0] }}/{{ name }}/gnureadline-{{ version }}.tar.gz
  sha256: c9b9e1e7ba99a80bb50c12027d6ce692574f77a65bf57bc97041cf81c0f49bd1

build:
  number: 3
  skip: true  # [not osx]
  script: {{ PYTHON }} -m pip install . -vv --no-deps --no-build-isolation

requirements:
  build:
    - {{ compiler('c') }}
    - {{ stdlib("c") }}
  host:
    - python
    - pip
    - setuptools
  run:
    - python

test:
  imports:
    - gnureadline
    - override_readline
    - readline
  commands:
    - pip check
  requires:
    - pip

about:
  home: http://github.com/ludwigschwardt/python-gnureadline
  license: GPL-3.0-only
  license_family: GPL
  license_file:
    - LICENSE
    - rl/readline-lib/COPYING
  summary: The standard Python readline extension statically linked against the GNU readline library

extra:
  recipe-maintainers:
    - ocefpaf
    - scopatz
"""
    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as f:
        f.write(recipe)

    with pushd(tmpdir):
        subprocess.run(["git", "init", "-b", "main"])
    # Load the meta.yaml (this is done in the graph)
    try:
        pmy = parse_meta_yaml(recipe)
    except Exception:
        pmy = {}
    if pmy:
        pmy["version"] = pmy["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            pmy["req"] |= set(pmy.get("requirements", {}).get(k, set()))
        try:
            pmy["meta_yaml"] = parse_meta_yaml(recipe)
        except Exception:
            pmy["meta_yaml"] = {}
    pmy["raw_meta_yaml"] = recipe
    pmy["version_pr_info"] = {"new_version": "8.3.3"}
    pmy["feedstock_name"] = "gnureadline"
    pmy["name"] = "readline"

    migration_data = run_migration(
        migrator=Version([], total_graph=nx.DiGraph()),
        feedstock_dir=tmpdir,
        feedstock_name="gnureadline",
        node_attrs=pmy,
        default_branch="main",
    )

    pprint.pprint(migration_data)

    assert migration_data["migrate_return_value"] == {
        "migrator_name": "Version",
        "migrator_version": 0,
        "bot_rerun": False,
        "version": "8.3.3",
    }
    assert migration_data["commit_message"] == "updated v8.3.3"
    assert migration_data["pr_title"] == "gnureadline v8.3.3"
    assert migration_data["pr_body"].startswith(
        "It is very likely that the current package version for this feedstock "
    )

    with open(os.path.join(tmpdir, "recipe/meta.yaml")) as f:
        actual_output = f.read()
    assert '{% set version = "8.3.3" %}' in actual_output
