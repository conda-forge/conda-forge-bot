from __future__ import annotations

import copy
import logging
import os
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Literal

import networkx as nx
from conda.models.version import VersionOrder

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.migrators.core import GraphMigrator, MiniMigrator
from conda_forge_tick.migrators.staticlib import _get_packages_by_name_and_platform_arch
from conda_forge_tick.migrators_types import (
    AttrsTypedDict,
    MigrationUidTypedDict,
    PackageName,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import get_keys_default

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _channel_versions(
    name: str,
    platform_arches: tuple[str, ...],
) -> dict[str, set[str]]:
    """Map each version of ``name`` on the channel to the set of queried
    platform architectures on which it is published.
    """
    seen: dict[str, set[str]] = {}
    for platform_arch in platform_arches:
        for rec in _get_packages_by_name_and_platform_arch(name, platform_arch):
            seen.setdefault(rec.version, set()).add(platform_arch)
    return seen


def latest_published_version(
    name: str,
    platform_arches: Sequence[str],
) -> str | None:
    """Return the newest version of ``name`` published on the channel for the
    given platforms.

    There is deliberately no requirement that every platform carries the newest
    version - a platform that never receives it is surfaced in the rebuild PR
    body instead (see ``pr_body``).

    Returns None if the package has no records on the channel at all.
    """
    versions = _channel_versions(name, tuple(sorted(platform_arches)))
    if not versions:
        return None

    return max(versions, key=lambda v: VersionOrder(v.replace("-", ".")))


def _watched_packages(attrs: AttrsTypedDict) -> list[str]:
    return (
        get_keys_default(
            attrs,
            ["conda-forge.yml", "bot", "rebuild_on_update"],
            {},
            [],
        )
        or []
    )


def _rebuild_versions(attrs: AttrsTypedDict) -> dict[str, str]:
    """Map each watched package to the newest version published on the channel
    for this feedstock's platforms.

    Watched packages with no records on the channel are omitted - each package
    triggers a rebuild independently of the others.
    """
    versions: dict[str, str] = {}
    platform_arches = attrs.get("platforms") or []
    for pkg in _watched_packages(attrs):
        version = latest_published_version(pkg, platform_arches)
        if version is not None:
            versions[pkg] = version
    return versions


class RebuildOnUpdateMigrator(GraphMigrator):
    """Open rebuild PRs for opted-in feedstocks when a package they must be built
    against (most commonly a build-only dependency such as a compiler) publishes
    a new version on the conda-forge channel.
    """

    migrator_version = 0
    rerender = True
    allowed_schema_versions = [0, 1]

    def __init__(
        self,
        graph: nx.DiGraph | None = None,
        pr_limit: int = 0,
        bump_number: int = 1,
        piggy_back_migrations: Sequence[MiniMigrator] | None = None,
        check_solvable: bool = True,
        effective_graph: nx.DiGraph | None = None,
        force_pr_after_solver_attempts=10,
        longterm=False,
        paused=False,
        total_graph: nx.DiGraph | None = None,
        top_level: set[PackageName] | None = None,
    ):
        top_level = top_level or set()

        if not hasattr(self, "_init_args"):
            self._init_args: list[Any] = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs: dict[str, Any] = {
                "graph": graph,
                "pr_limit": pr_limit,
                "bump_number": bump_number,
                "piggy_back_migrations": piggy_back_migrations,
                "check_solvable": check_solvable,
                "effective_graph": effective_graph,
                "longterm": longterm,
                "force_pr_after_solver_attempts": force_pr_after_solver_attempts,
                "paused": paused,
                "total_graph": total_graph,
                "top_level": top_level,
            }

        self.bump_number = bump_number
        self.longterm = longterm
        self.force_pr_after_solver_attempts = force_pr_after_solver_attempts
        self.paused = paused

        if total_graph is not None:
            total_graph = copy.deepcopy(total_graph)
            # each opted-in feedstock rebuilds independently against the channel;
            # there is no ordering between them
            total_graph.clear_edges()

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            obj_version=0,
            piggy_back_migrations=piggy_back_migrations,
            check_solvable=check_solvable,
            name="rebuild_on_update",
            effective_graph=effective_graph,
            total_graph=total_graph,
            top_level=top_level,
        )

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        watched = _watched_packages(attrs)
        if not watched:
            logger.debug(
                "filter %s: rebuild_on_update not configured",
                attrs.get("name") or "",
            )
            return True

        # each watched package triggers a rebuild independently; a package with
        # no triggerable channel version (yet) must not block the others
        versions = _rebuild_versions(attrs)
        if not versions:
            logger.debug(
                "filter %s: no triggerable channel version for watched packages %s",
                attrs.get("name") or "",
                watched,
            )
            return True

        return False

    def migrate(
        self, recipe_dir: str, attrs: AttrsTypedDict, **kwargs: Any
    ) -> MigrationUidTypedDict | Literal[False]:
        if not _watched_packages(attrs):
            return False

        with pushd(recipe_dir):
            if os.path.exists("recipe.yaml"):
                self.set_build_number("recipe.yaml")
            elif os.path.exists("meta.yaml"):
                self.set_build_number("meta.yaml")
            else:
                logger.warning("no recipe found in %s", recipe_dir)
                return False

        return super().migrate(recipe_dir, attrs)

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text: bool = True
    ) -> str:
        body = super().pr_body(feedstock_ctx)

        versions = _rebuild_versions(feedstock_ctx.attrs)
        platform_arches = feedstock_ctx.attrs.get("platforms") or []
        pkg_lines = []
        for pkg, version in sorted(versions.items()):
            present = _channel_versions(pkg, tuple(sorted(platform_arches))).get(
                version, set()
            )
            missing = sorted(set(platform_arches) - present)
            if missing:
                pkg_lines.append(
                    f"- {pkg} {version} (not yet available on: "
                    f"{', '.join(p.replace('_', '-') for p in missing)})"
                )
            else:
                pkg_lines.append(f"- {pkg} {version}")
        pkg_list = "\n".join(pkg_lines)
        additional_body = (
            "This PR has been triggered because a package this feedstock must be "
            "built against has a newer version published on the conda-forge "
            "channel:\n\n"
            f"{pkg_list}\n\n"
            "It bumps the build number only; there are no recipe changes. The "
            "rebuild picks up the newest version of the package at build time. "
            "If a platform is listed as not having the package version yet, the "
            "build for that platform may fail until the package shows up on the "
            "channel.\n\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed.\n"
            "2. Feel free to push to the bot's branch to update this PR if needed.\n\n"
            "**Please note that if you close this PR we presume that the feedstock "
            "has been rebuilt, so if you are going to perform the rebuild yourself "
            "don't close this PR until the rebuild has been merged.**\n\n"
        )

        return body.format(additional_body)

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        versions = _rebuild_versions(feedstock_ctx.attrs)
        if not versions:
            return "Rebuild for watched package updates"
        parts = ", ".join(f"{pkg} {ver}" for pkg, ver in sorted(versions.items()))
        return f"Rebuild for {parts}"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return self.commit_message(feedstock_ctx).splitlines()[0]

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        # auto_tick appends a random suffix, so this needs no uniqueness on its own
        return "rebuild_on_update"

    def migrator_uid(self, attrs: AttrsTypedDict) -> MigrationUidTypedDict:
        d = super().migrator_uid(attrs)
        versions = _rebuild_versions(attrs)
        if versions:
            d["rebuild_on_update"] = versions
        return d
