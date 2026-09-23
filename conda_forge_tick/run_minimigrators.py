import typing
from pathlib import Path

from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
from conda_forge_tick.make_migrators import _make_mini_migrators_with_defaults
from conda_forge_tick.migrators_types import AttrsTypedDict
from conda_forge_tick.utils import (
    yaml_safe_load,
)


def run_minimigrators(
    feedstock_dir: Path,
):
    # read the conda-forge.yml
    if feedstock_dir.joinpath("conda-forge.yml").exists():
        with open(feedstock_dir / "conda-forge.yml") as fp:
            cf_yml = fp.read()
    else:
        cf_yml = "{}"

    cf_yml_parsed = yaml_safe_load(cf_yml)
    # same logic as conda-smithy
    recipe_dir = feedstock_dir / "recipe"
    recipe_filename = (
        "recipe.yaml"
        if cf_yml_parsed.get("conda_build_tool", "") == "rattler-build"
        else "meta.yaml"
    )

    # load the recipe
    with open(recipe_dir / recipe_filename) as fp:
        recipe_yml = fp.read()

    pmy = typing.cast(
        AttrsTypedDict,
        populate_feedstock_attributes(
            "",
            {},
            conda_forge_yaml=cf_yml,
            feedstock_dir=feedstock_dir,
            use_container=False,
            **{(recipe_filename.replace(".", "_")): recipe_yml},  # type: ignore[arg-type]
        ),
    )

    migrators = _make_mini_migrators_with_defaults()
    # run pre-migration minimigrators first
    for migrator in sorted(migrators, key=lambda m: m.post_migration):
        filtered = migrator.filter(pmy)
        if not filtered:
            print(f"Running {migrator.__class__.__name__} minimigrator ...")
            migrator.migrate(str(recipe_dir), pmy)
