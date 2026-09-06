import collections.abc
import copy
import logging
import os
import pprint
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from grayskull.config import Configuration
from grayskull.utils import generate_recipe
from ruamel.yaml import YAML
from souschef.recipe import Recipe

# from conda_forge_tick.depfinder_api import simple_import_to_pkg_map
from conda_forge_tick.feedstock_parser import load_feedstock
from conda_forge_tick.recipe_parser import CONDA_SELECTOR, CondaMetaYAML
from conda_forge_tick.utils import get_recipe_schema_version

try:
    from grayskull.main import create_python_recipe
except ImportError:
    from grayskull.__main__ import create_python_recipe

logger = logging.getLogger(__name__)

yaml = YAML()
yaml.default_flow_style = False
yaml.block_seq_indent = True
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 4096

EnvDepComparison = dict[Literal["df_minus_cf", "cf_minus_df"], set[str]]
DepComparison = dict[Literal["host", "run"], EnvDepComparison]


SECTIONS_TO_PARSE = ["host", "run"]
SECTIONS_TO_UPDATE = ["run"]


def get_dep_updates_and_hints(
    update_deps: str | Literal[False],
    recipe_dir: str,
    attrs,
    python_nodes,
    version_key: str,
):
    """Get updated deps and hints.

    Parameters
    ----------
    update_deps : str | Literal[False]
        An update kind. See the code below for what is supported.
    recipe_dir : str
        The directory with the recipe.
    attrs : dict-like
        the bot node attrs for the feedstock.
    python_nodes : set-like
        A set of all bot python nodes.
    version_key : str
        The version key in the node attrs to use for grayskull.

    Returns
    -------
    dep_comparison : dict of dicts of sets
        A dictionary with the dep updates. See the hint generation code below
        to understand its contents.
    hint : str
        The dependency update hint.


    Raises
    ------
    ValueError
        If the update kind is not supported.
    """
    if update_deps == "disabled":
        # no dependency updates or hinting
        return {}, ""

    if update_deps in [
        "hint",
        "hint-grayskull",
        "update-grayskull",
        "hint-all",
        "update-all",
    ]:
        dep_comparison, _ = get_grayskull_comparison(
            attrs,
            version_key=version_key,
        )
        logger.info("grayskull dep. comp: %s", pprint.pformat(dep_comparison))
        kind = "grayskull"
        hint = generate_dep_hint(dep_comparison, kind)
        return dep_comparison, hint

    raise ValueError(f"update kind '{update_deps}' not supported.")


def _is_list_like(obj):
    # based on https://stackoverflow.com/a/37842328 w/ help from google's AI
    return isinstance(obj, collections.abc.Sequence) and not isinstance(
        obj, (str, bytes, bytearray, collections.abc.Buffer, memoryview)
    )


def _modify_package_name_from_github(orig_name, src):
    # if a package source comes from github, adjust the package name
    # for sending to create_python_recipe, so grayskull can find metadata
    all_urls = set()
    if isinstance(src, dict):
        src = [src]
    for s in src:
        if "url" in s:
            if _is_list_like(s):
                for _s in s:
                    all_urls.add(_s)
            else:
                all_urls.add(s["url"])

    is_pypi = False
    is_github = False
    for url in all_urls:
        if any(
            pypi_slug in url
            for pypi_slug in [
                "/pypi.io/",
                "/pypi.org/",
                "/pypi.python.org/",
                "/files.pythonhosted.org/",
            ]
        ):
            is_pypi = True
            break

    if not is_pypi:
        for url in all_urls:
            if "github.com/" in url:
                is_github = True
                github_url = url
                break

    # we don't know so assume pypi
    if not is_pypi and not is_github:
        is_pypi = True

    if is_pypi:
        for url in all_urls:
            match = re.search(r"/packages/source/[a-z0-9]/([^/]+)/", url)
            if match:
                return match.group(1)
        return orig_name
    elif is_github:
        url_parts = github_url.split("/")
        if len(url_parts) < 5:
            logger.warning(
                "github url %s for grayskull dep update is too short! assuming pypi...",
                github_url,
            )
            return orig_name
        else:
            return "/".join(url_parts[:5])


def make_grayskull_recipe(attrs, version_key="version"):
    """Make a grayskull recipe given bot node attrs.

    Parameters
    ----------
    attrs : dict or LazyJson
        The node attrs.
    version_key : str, optional
        The version key to use from the attrs. Default is "version".

    Returns
    -------
    recipe : str
        The generated grayskull recipe as a string.
    """
    if version_key not in attrs:
        pkg_version = attrs.get("version_pr_info", {}).get(version_key)
    else:
        pkg_version = attrs[version_key]

    src = attrs["meta_yaml"].get("source", {}) or {}
    pkg_name = _modify_package_name_from_github(attrs["name"], src)

    is_noarch = "noarch: python" in attrs["raw_meta_yaml"]
    logger.info(
        "making grayskull recipe for pkg %s w/ version %s",
        pkg_name,
        pkg_version,
    )
    recipe, _ = create_python_recipe(
        pkg_name=pkg_name,
        version=pkg_version,
        download=False,
        is_strict_cf=True,
        from_local_sdist=False,
        is_arch=not is_noarch,
    )

    with tempfile.TemporaryDirectory() as td:
        pth = os.path.join(td, "meta.yaml")
        recipe.save(pth)
        with open(pth) as f:
            out = f.read()

    # code around a grayskull bug
    # see https://github.com/conda-incubator/grayskull/issues/295
    if "[py>=40]" in out:
        out = out.replace("[py>=40]", "[py>=400]")

    logger.info("grayskull recipe:\n%s", out)

    return out


def _generate_grayskull_recipe_v1(recipe: Recipe, configuration: Configuration) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        generate_recipe(
            recipe=recipe,
            config=configuration,
            folder_path=temp_dir,
            use_v1_format=True,
        )
        return (Path(temp_dir) / configuration.name / "recipe.yaml").read_text()


def _validate_grayskull_recipe_v1(recipe: Recipe):
    # The new v1 recipe format allows for complex structures as requirements, not just strings.
    # For example, '{'if': 'linux', 'then': 'numpy'}'.
    # This is hard to integrate into the remainder of the dependency update process downstream,
    # so we skip recipes affected by this for now.
    for environment in ["host", "run"]:
        for requirement in recipe.yaml["requirements"][environment]:
            if not isinstance(requirement, str):
                raise ValueError(
                    f"Requirement in '{environment}' environment is not a string: '{requirement}'"
                )


def _make_grayskull_recipe_v1(
    package_name: str, package_version: str, package_is_noarch: bool
) -> str:
    recipe, config = create_python_recipe(
        pkg_name=package_name,
        version=package_version,
        download=False,
        is_strict_cf=True,
        from_local_sdist=False,
        is_arch=not package_is_noarch,
    )
    _validate_grayskull_recipe_v1(recipe=recipe)
    recipe_str = _generate_grayskull_recipe_v1(recipe=recipe, configuration=config)

    # Grayskull generates `match(python, ...)` for noarch recipes, but v1 recipes
    # use `python_min` in their variant configs (CFEP-25). Replace to make the
    # recipe renderable. See: https://github.com/conda/conda-recipe-manager/issues/479
    if package_is_noarch:
        recipe_str = recipe_str.replace("match(python,", "match(python_min,")

    return recipe_str


def get_grayskull_comparison(attrs, version_key="version"):
    """Get the dependency comparison between the recipe and grayskull.

    Parameters
    ----------
    attrs : dict or LazyJson
        The bot node attrs.
    version_key : str, optional
        The version key to use from the attrs. Default is "version".

    Returns
    -------
    d : dict
        The dependency comparison with conda-forge.

    Raises
    ------
    ValueError
        When a v1 recipe contains requirements that we are unable to process.
    """
    recipe_schema_version = get_recipe_schema_version(attrs)
    if recipe_schema_version == 0:
        grayskull_recipe = make_grayskull_recipe(attrs, version_key=version_key)
        new_attrs = load_feedstock(
            attrs.get("feedstock_name"), {}, meta_yaml=grayskull_recipe
        )
    elif recipe_schema_version == 1:
        recipe = attrs["meta_yaml"]
        src = recipe.get("source", {}) or {}
        pkg_name = _modify_package_name_from_github(recipe["package"]["name"], src)
        grayskull_recipe = _make_grayskull_recipe_v1(
            package_name=pkg_name,
            package_version=attrs["version_pr_info"][version_key],
            package_is_noarch=bool(recipe["build"].get("noarch")),
        )
        new_attrs = load_feedstock(
            attrs.get("feedstock_name"), {}, recipe_yaml=grayskull_recipe
        )
    else:
        raise ValueError(f"Unknown recipe schema version: '{recipe_schema_version}'.")

    # we put back python_min by hand since we render the recipe above before
    # computing the dep comparison
    python_min_slugs = [
        "python ${{ python_min }}.*",
        "python >=${{ python_min }}",
        "python {{ python_min }}.*",
        "python {{ python_min }}",
        "python >={{ python_min }}",
    ]
    has_python_min = any(slug in grayskull_recipe for slug in python_min_slugs) and (
        any(slug in attrs["raw_meta_yaml"] for slug in python_min_slugs)
        or any(
            line.strip().startswith("noarch: python")
            for line in attrs["raw_meta_yaml"].splitlines()
        )
    )

    def _replace_python_min(orig_set, section):
        new_set = set()
        for req in orig_set:
            if req.split()[0] == "python" and has_python_min:
                if recipe_schema_version == 1:
                    if section == "host":
                        new_set.add("python ${{ python_min }}.*")
                    elif section == "run":
                        new_set.add("python >=${{ python_min }}")
                    else:
                        new_set.add(req)
                else:
                    if section == "host":
                        new_set.add("python {{ python_min }}")
                    elif section == "run":
                        new_set.add("python >={{ python_min }}")
                    else:
                        new_set.add(req)
            else:
                new_set.add(req)

        return new_set

    d: dict[str, dict[str, set[str]]] = {}
    for section in SECTIONS_TO_PARSE:
        gs_run = _replace_python_min(
            {c for c in new_attrs.get("total_requirements").get(section, set())},
            section,
        )
        cf_minus_df = {c for c in attrs.get("total_requirements").get(section, set())}

        df_minus_cf = set()
        for req in gs_run:
            if req in cf_minus_df:
                cf_minus_df = cf_minus_df - {req}
            else:
                df_minus_cf.add(req)

        d[section] = {}
        d[section]["cf_minus_df"] = cf_minus_df
        d[section]["df_minus_cf"] = df_minus_cf

    return d, grayskull_recipe


def generate_dep_hint(dep_comparison, kind):
    """Generate a dep hint.

    Parameters
    ----------
    dep_comparison : dict
        The dependency comparison.
    kind : str
        The kind of comparison (e.g., source code, grayskull, etc.)

    Returns
    -------
    hint : str
        The dependency hint string.
    """
    hint = "\n\nDependency Analysis\n--------------------\n\n"
    hint += (
        "Please note that this analysis is **highly experimental**. "
        "The aim here is to make maintenance easier by inspecting the package's dependencies. "  # noqa: E501
        "Importantly this analysis does not support optional dependencies, "
        "please double check those before making changes. "
        "If you do not want hinting of this kind ever please add "
        "`bot: inspection: disabled` to your `conda-forge.yml`. "
        "If you encounter issues with this feature please ping the bot team `conda-forge/bot`.\n\n"  # noqa: E501
    )

    df_cf = ""
    for sec in SECTIONS_TO_PARSE:
        for k in dep_comparison.get(sec, {}).get("df_minus_cf", set()):
            df_cf += f"- {k}" + "\n"
    cf_df = ""
    for sec in SECTIONS_TO_PARSE:
        for k in dep_comparison.get(sec, {}).get("cf_minus_df", set()):
            cf_df += f"- {k}" + "\n"

    if len(df_cf) > 0 or len(cf_df) > 0:
        hint += (
            f"Analysis by {kind} shows a discrepancy between it and the"
            " the package's stated requirements in the meta.yaml."
        )
        if df_cf:
            hint += (
                f"\n\n### Packages found by {kind} but not in the meta.yaml:\n"  # noqa: E501
                f"{df_cf}"
            )
        if cf_df:
            hint += (
                f"\n\n### Packages found in the meta.yaml but not found by {kind}:\n"  # noqa: E501
                f"{cf_df}"
            )
    else:
        hint += f"Analysis by {kind} shows **no discrepancy** with the stated requirements in the meta.yaml."  # noqa: E501
    return hint


def _ok_for_dep_updates(lines):
    is_multi_output = any(ln.lstrip().startswith("outputs:") for ln in lines)
    return not is_multi_output


def _update_sec_deps(recipe, dep_comparison, sections_to_update, update_python=False):
    updated_deps = False

    rqkeys = list(_gen_key_selector(recipe.meta, "requirements"))
    if len(rqkeys) == 0:
        recipe.meta["requirements"] = {}

    for rqkey in _gen_key_selector(recipe.meta, "requirements"):
        for section in sections_to_update:
            seckeys = list(_gen_key_selector(recipe.meta[rqkey], section))
            if len(seckeys) == 0:
                recipe.meta[rqkey][section] = []

            for seckey in _gen_key_selector(recipe.meta[rqkey], section):
                deps = sorted(
                    list(dep_comparison.get(section, {}).get("df_minus_cf", set())),
                )[::-1]
                for dep in deps:
                    dep_pkg_nm = dep.split(" ", 1)[0]

                    # do not touch python itself - to finicky
                    if dep_pkg_nm == "python" and not update_python:
                        continue

                    # do not replace pin compatible keys
                    if seckey.startswith("run") and any(
                        (
                            "pin_compatible" in rq
                            and ("'%s'" % dep_pkg_nm in rq or '"%s"' % dep_pkg_nm in rq)
                        )
                        for rq in recipe.meta[rqkey][seckey]
                    ):
                        continue

                    # find location of old dep
                    # add if not found, otherwise replace
                    loc = None
                    for i, rq in enumerate(recipe.meta[rqkey][seckey]):
                        pkg_nm = rq.split(" ", 1)[0]
                        if dep_pkg_nm == pkg_nm:
                            loc = i
                            break
                    if loc is None:
                        recipe.meta[rqkey][seckey].insert(0, dep)
                    else:
                        recipe.meta[rqkey][seckey][loc] = dep
                    updated_deps = True

    return updated_deps


def _gen_key_selector(dct, key):
    for k in dct:
        if k == key or (CONDA_SELECTOR in k and k.split(CONDA_SELECTOR)[0] == key):
            yield k


@dataclass
class Patch:
    before: str | None = None
    after: str | None = None


def _env_dep_comparison_to_patches(
    env_dep_comparison: EnvDepComparison,
) -> dict[str, Patch]:
    deps_to_remove = copy.copy(env_dep_comparison["cf_minus_df"])
    deps_to_add = copy.copy(env_dep_comparison["df_minus_cf"])
    patches: dict[str, Patch] = defaultdict(Patch)
    for dep in deps_to_add:
        package = dep.split(" ")[0]
        patches[package] = Patch(after=dep)
    for dep in deps_to_remove:
        package = dep.split(" ")[0]
        patches[package].before = dep
    return patches


def is_expression_requirement(dep: str) -> bool:
    return dep.startswith(r"${{")


def _apply_env_dep_comparison(
    deps: list[str], env_dep_comparison: EnvDepComparison
) -> list[str]:
    """Apply updates to dependency list while maintaining original package order."""
    new_deps = copy.copy(deps)
    patches = _env_dep_comparison_to_patches(env_dep_comparison)
    for package, patch in patches.items():
        # Do not touch Python itself - too finicky.
        if package == "python":
            continue
        # Do not try to replace expressions.
        if patch.before is not None and is_expression_requirement(patch.before):
            continue
        # Add new package.
        if patch.before is None:
            new_deps.append(patch.after)  # type: ignore[arg-type]
        # Remove old package.
        elif patch.after is None:
            new_deps.remove(patch.before)
        # Update existing package.
        else:
            new_deps[new_deps.index(patch.before)] = patch.after
    return new_deps


def _is_multi_output_v1_recipe(recipe: dict) -> bool:
    return "outputs" in recipe


def _is_v1_recipe_okay_for_dep_updates(recipe: dict) -> bool:
    return not _is_multi_output_v1_recipe(recipe=recipe)


def _apply_dep_update_v1(recipe: dict, dep_comparison: DepComparison) -> dict:
    new_recipe = copy.deepcopy(recipe)
    if not _is_v1_recipe_okay_for_dep_updates(recipe):
        return new_recipe

    for section in SECTIONS_TO_UPDATE:
        new_recipe["requirements"][section] = _apply_env_dep_comparison(
            recipe["requirements"][section],
            dep_comparison[section],  # type: ignore[index]
        )

    return new_recipe


def _get_v1_recipe_file_if_exists(recipe_dir: Path) -> Path | None:
    if (recipe_file := Path(recipe_dir).joinpath("recipe.yaml")).is_file():
        return recipe_file
    return None


def apply_dep_update(recipe_dir, dep_comparison):
    """Update a recipe given a dependency comparison.

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe dir.
    dep_comparison : dict
        The dependency comparison.
    """
    if recipe_file := _get_v1_recipe_file_if_exists(recipe_dir):
        recipe = yaml.load(recipe_file.read_text())
        if (new_recipe := _apply_dep_update_v1(recipe, dep_comparison)) != recipe:
            with recipe_file.open("w") as f:
                yaml.dump(new_recipe, f)
        return
    recipe_pth = os.path.join(recipe_dir, "meta.yaml")
    with open(recipe_pth) as fp:
        lines = fp.readlines()

    if _ok_for_dep_updates(lines) and any(
        len(dep_comparison.get(s, {}).get("df_minus_cf", set())) > 0
        for s in SECTIONS_TO_UPDATE
    ):
        recipe = CondaMetaYAML("".join(lines))
        updated_deps = _update_sec_deps(
            recipe,
            dep_comparison,
            SECTIONS_TO_UPDATE,
        )
        # updated_deps is True if deps were updated, False otherwise.
        if updated_deps:
            with open(recipe_pth, "w") as fp:
                recipe.dump(fp)
