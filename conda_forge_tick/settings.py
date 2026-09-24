import contextlib
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SPLIT_GITHUB_BACKEND_REPOS = [
    "versions",
    "node_attrs",
    "pr_info",
    "version_pr_info",
    "pr_json",
    "migrators",
]

ENVIRONMENT_PREFIX = "CF_TICK_"
"""
All environment variables are expected to be prefixed with this.
"""

# NOTE: all of the ENV_{setting_name} variables below must match the field name
# in the settings class.
# These variables hold the name of the env var used to set the setting.
ENV_CONDA_FORGE_ORG = ENVIRONMENT_PREFIX + "CONDA_FORGE_ORG"
ENV_GRAPH_GITHUB_BACKEND_REPO = ENVIRONMENT_PREFIX + "GRAPH_GITHUB_BACKEND_REPO"
ENV_VERSIONS_GITHUB_BACKEND_REPO = ENVIRONMENT_PREFIX + "VERSIONS_GITHUB_BACKEND_REPO"
ENV_NODE_ATTRS_GITHUB_BACKEND_REPO = (
    ENVIRONMENT_PREFIX + "NODE_ATTRS_GITHUB_BACKEND_REPO"
)
ENV_PR_INFO_GITHUB_BACKEND_REPO = ENVIRONMENT_PREFIX + "PR_INFO_GITHUB_BACKEND_REPO"
ENV_VERSION_PR_INFO_GITHUB_BACKEND_REPO = (
    ENVIRONMENT_PREFIX + "VERSION_PR_INFO_GITHUB_BACKEND_REPO"
)
ENV_PR_JSON_GITHUB_BACKEND_REPO = ENVIRONMENT_PREFIX + "PR_JSON_GITHUB_BACKEND_REPO"
ENV_MIGRATORS_GITHUB_BACKEND_REPO = ENVIRONMENT_PREFIX + "MIGRATORS_GITHUB_BACKEND_REPO"

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]


class BotSettings(BaseSettings):
    """
    The global settings for the bot.

    To configure a settings value, set the corresponding environment variable with the prefix `CF_TICK_`.
    For example, to set the `graph_github_backend_repo` setting, set the environment variable
    `CF_TICK_GRAPH_GITHUB_BACKEND_REPO`.

    To access the current settings object, please use the `settings()` function.

    Note: There still exists a significant amount of settings that are not yet exposed here.
    All new settings should go here, and the other ones should eventually be migrated.
    """

    model_config = SettingsConfigDict(env_prefix=ENVIRONMENT_PREFIX)

    conda_forge_org: str = Field("conda-forge", pattern=r"^[\w\.-]+$")
    """
    The GitHub organization containing all feedstocks. Default: "conda-forge".
    If you change the field name, you must also update the `ENV_CONDA_FORGE_ORG` constant.
    """

    graph_github_backend_repo: str = Field(
        "conda-forge/conda-forge-bot-data", pattern=r"^[\w\.-]+/[\w\.-]+$"
    )
    """
    The GitHub repository to deploy to. Default: "conda-forge/conda-forge-bot-data".
    If you change the field name, you must also update the `ENV_GRAPH_GITHUB_BACKEND_REPO` constant.
    """

    @property
    def graph_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the graph_github_backend_repo repository.
        Example: https://github.com/conda-forge/conda-forge-bot-data/raw/main.
        """
        return f"https://github.com/{self.graph_github_backend_repo}/raw/main/"

    versions_github_backend_repo: str = Field(
        "conda-forge/conda-forge-bot-data-versions", pattern=r"^[\w\.-]+/[\w\.-]+$"
    )
    """
    The GitHub repository to deploy version data to. Default: "conda-forge/conda-forge-bot-data-versions".
    If you change the field name, you must also update the `ENV_GRAPH_VERSIONS_BACKEND_REPO` constant.
    """

    @property
    def versions_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the versions_github_backend_repo repository.
        Example: https://github.com/conda-forge/conda-forge-bot-data/raw/main.
        """
        return f"https://github.com/{self.versions_github_backend_repo}/raw/main/"

    node_attrs_github_backend_repo: str = Field(
        "conda-forge/conda-forge-bot-data-node_attrs", pattern=r"^[\w\.-]+/[\w\.-]+$"
    )
    """
    The GitHub repository to deploy node attrs to. Default: "conda-forge/conda-forge-bot-data-node_attrs".
    If you change the field name, you must also update the `ENV_GRAPH_NODE_ATTRS_BACKEND_REPO` constant.
    """

    @property
    def node_attrs_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the node_attrs_github_backend_repo repository.
        Example: https://github.com/conda-forge/conda-forge-bot-data/raw/main.
        """
        return f"https://github.com/{self.node_attrs_github_backend_repo}/raw/main/"

    pr_info_github_backend_repo: str = Field(
        "conda-forge/conda-forge-bot-data-pr_info", pattern=r"^[\w\.-]+/[\w\.-]+$"
    )
    """
    The GitHub repository to deploy PR info to. Default: "conda-forge/conda-forge-bot-data".
    If you change the field name, you must also update the `ENV_GRAPH_PR_INFO_BACKEND_REPO` constant.
    """

    @property
    def pr_info_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the pr_info_github_backend_repo repository.
        Example: https://github.com/conda-forge/conda-forge-bot-data/raw/main.
        """
        return f"https://github.com/{self.pr_info_github_backend_repo}/raw/main/"

    version_pr_info_github_backend_repo: str = Field(
        "conda-forge/conda-forge-bot-data-version_pr_info",
        pattern=r"^[\w\.-]+/[\w\.-]+$",
    )
    """
    The GitHub repository to deploy version PR info to. Default: "conda-forge/conda-forge-bot-data-version_pr_info".
    If you change the field name, you must also update the `ENV_GRAPH_VERSION_PR_INFO_BACKEND_REPO` constant.
    """

    @property
    def version_pr_info_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the version_pr_info_github_backend_repo repository.
        Example: https://github.com/conda-forge/conda-forge-bot-data/raw/main.
        """
        return (
            f"https://github.com/{self.version_pr_info_github_backend_repo}/raw/main/"
        )

    pr_json_github_backend_repo: str = Field(
        "conda-forge/conda-forge-bot-data-pr_json", pattern=r"^[\w\.-]+/[\w\.-]+$"
    )
    """
    The GitHub repository to deploy PR json to. Default: "conda-forge/conda-forge-bot-data-pr_json".
    If you change the field name, you must also update the `ENV_GRAPH_PR_JSON_BACKEND_REPO` constant.
    """

    @property
    def pr_json_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the pr_json_github_backend_repo repository.
        Example: https://github.com/conda-forge/conda-forge-bot-data/raw/main.
        """
        return f"https://github.com/{self.pr_json_github_backend_repo}/raw/main/"

    migrators_github_backend_repo: str = Field(
        "conda-forge/conda-forge-bot-data-migrators", pattern=r"^[\w\.-]+/[\w\.-]+$"
    )
    """
    The GitHub repository to deploy migrators to. Default: "conda-forge/conda-forge-bot-data-migrators".
    If you change the field name, you must also update the `ENV_GRAPH_MIGRATORS_BACKEND_REPO` constant.
    """

    @property
    def migrators_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the migrators_github_backend_repo repository.
        Example: https://github.com/conda-forge/conda-forge-bot-data/raw/main.
        """
        return f"https://github.com/{self.migrators_github_backend_repo}/raw/main/"

    github_runner_debug: bool = Field(False, alias="RUNNER_DEBUG")
    """
    Whether we are executing within a GitHub Actions run with debug logging enabled. Default: False.
    This is set automatically by GitHub Actions.
    https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
    """

    frac_update_upstream_versions: Fraction = 0.1
    """
    The fraction of feedstocks (randomly selected) to update in the update-upstream-versions job.
    This is currently only respected when running concurrently (via process pool), not in sequential mode.
    Therefore, you don't need to set this when debugging locally.
    """

    frac_update_node_attrs: Fraction = 0.1
    """
    The fraction of feedstocks (randomly selected) to update the node attrs in the update nodes job.
    In tests or when debugging, you probably need to set this to 1.0 to update all feedstocks.
    """

    # FIXME: put this back to 0.1
    frac_update_pr_json: Fraction = 0.01
    """
    The fraction of feedstocks (randomly selected) to update in the prs job.
    In tests or when debugging, you probably need to set this to 1.0 to update all feedstocks.
    """

    pull_request_reopen_window: float = 15 * 60.0
    """
    A pull request that is closed can be reopened if it is done so within this amount of time.
    Specified in seconds.
    """

    pr_refresh_age_days: float = 7.0
    """
    Number of days after which to refresh PR cache for 'clean' PRs to detect potential conflicts.
    Works around GitHub API bug #5150 where Last-Modified caching can hide merge conflicts.
    Set to 0 to always refresh.
    """

    max_attempts_for_share: float = 3.0
    """The maximum number of attempts for a PR for it to count as a PR a migrator has to do. PRs
    with more than this number are not specifically allocated time in the bot run, though every
    migrator with any PRs to make is given a minimal amount of time.
    """


_use_settings_override: BotSettings | None = None
"""
If not None, the application should use this settings object instead of generating a new one.
"""


def settings() -> BotSettings:
    """Get the current settings object."""
    if _use_settings_override:
        return _use_settings_override.model_copy()  # prevent side-effects
    return BotSettings()


@contextlib.contextmanager
def use_settings(s: BotSettings | None):
    """
    Context manager that overrides the application settings with the values set in the provided settings object.
    The new settings are used within the context of the `with` statement.
    After exiting the context, the original settings are restored.

    DO NOT call this function within multithreading contexts, as it will override the settings for all threads,
    and lead to unpredictable behavior.

    Parameters
    ----------
    s
        The settings object to use. None stands for the default settings behavior. The default settings
        behavior reads the environment variables every time the settings are accessed.
    """
    global _use_settings_override

    old_settings = (
        _use_settings_override.model_copy() if _use_settings_override else None
    )
    _use_settings_override = s.model_copy() if s else None

    yield

    _use_settings_override = old_settings


def get_container_env_command_args() -> list[str]:
    """Get the arguments to pass settings env vars into a container."""
    return [
        "-e",
        f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
        "-e",
        f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
        "-e",
        f"{ENV_VERSIONS_GITHUB_BACKEND_REPO}={settings().versions_github_backend_repo}",
        "-e",
        f"{ENV_NODE_ATTRS_GITHUB_BACKEND_REPO}={settings().node_attrs_github_backend_repo}",
        "-e",
        f"{ENV_PR_INFO_GITHUB_BACKEND_REPO}={settings().pr_info_github_backend_repo}",
        "-e",
        f"{ENV_VERSION_PR_INFO_GITHUB_BACKEND_REPO}={settings().version_pr_info_github_backend_repo}",
        "-e",
        f"{ENV_PR_JSON_GITHUB_BACKEND_REPO}={settings().pr_json_github_backend_repo}",
        "-e",
        f"{ENV_MIGRATORS_GITHUB_BACKEND_REPO}={settings().migrators_github_backend_repo}",
    ]
