import typing

from conda_forge_tick.migrators.v0_to_v1 import GenericV0ToV1Migrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


def _is_r_feedstock(attrs: "AttrsTypedDict") -> bool:
    # R feedstocks are all maintained by the same conda-forge/r team, e.g.
    # https://github.com/conda-forge/r-essentials-feedstock/blob/main/recipe/meta.yaml#L69-L71
    if "conda-forge/r" in attrs.get("extra", {}).get("recipe-maintainers", []):
        return True
    return (
        attrs.get("feedstock_name", "").startswith("r-")
        or attrs.get("name", "").startswith("r-")
    ) and (
        "r-base" in attrs.get("raw_meta_yaml", "")
        or "r-base" in attrs.get("requirements", {}).get("run", set())
    )


class RV0ToV1Migrator(GenericV0ToV1Migrator):
    """R-specific v0 -> v1 recipe migrator.

    R recipes near-universally template their compiler and Windows/ucrt
    cross-compilation requirements with ``{{ compiler(...) }}`` and the
    ``native``/``posix``/``m2w64`` substitution variables. crm already
    converts these to correct v1 ``if``/``then`` selector syntax; it just
    can't upgrade the (non-existent) version constraint on a templated
    dependency, and warns about that on every single one. Ignoring that
    warning here is safe: there was no version constraint on these
    dependencies in the v0 recipe for crm to preserve in the first place,
    so the produced recipe.yaml is unaffected.
    """

    IGNORED_WARNINGS = GenericV0ToV1Migrator.IGNORED_WARNINGS + (
        "Recipe upgrades cannot currently upgrade ambiguous version "
        "constraints on dependencies that use variables:",
    )

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs, not_bad_str_start):
            return True
        return not _is_r_feedstock(attrs)
