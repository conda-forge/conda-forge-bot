import os

import pytest
from pydantic import ValidationError

from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    SPLIT_GITHUB_BACKEND_REPOS,
    BotSettings,
    get_container_env_command_args,
    settings,
    use_settings,
)


class TestBotSettings:
    def test_parse(self, temporary_environment):
        os.environ["CF_TICK_CONDA_FORGE_ORG"] = "myorg"
        os.environ["CF_TICK_GRAPH_GITHUB_BACKEND_REPO"] = "graph-owner/graph-repo"
        os.environ["RUNNER_DEBUG"] = "1"
        os.environ["CF_TICK_FRAC_UPDATE_UPSTREAM_VERSIONS"] = "0.5"
        os.environ["CF_TICK_FRAC_UPDATE_NODE_ATTRS"] = "0.7"
        for dr in SPLIT_GITHUB_BACKEND_REPOS:
            os.environ[f"CF_TICK_{dr.upper()}_GITHUB_BACKEND_REPO"] = (
                f"{dr}-owner/{dr}-repo"
            )

        bot_settings = BotSettings()

        assert bot_settings.conda_forge_org == "myorg"
        for dr in ["graph"] + SPLIT_GITHUB_BACKEND_REPOS:
            assert (
                getattr(bot_settings, f"{dr}_github_backend_repo")
                == f"{dr}-owner/{dr}-repo"
            )
            assert (
                getattr(bot_settings, f"{dr}_github_backend_raw_base_url")
                == f"https://github.com/{dr}-owner/{dr}-repo/raw/main/"
            )
        assert bot_settings.github_runner_debug is True
        assert bot_settings.frac_update_upstream_versions == 0.5
        assert bot_settings.frac_update_node_attrs == 0.7

    def test_defaults(self, temporary_environment):
        os.environ.clear()

        bot_settings = BotSettings()

        assert bot_settings.conda_forge_org == "conda-forge"
        assert (
            bot_settings.graph_github_backend_repo == "conda-forge/conda-forge-bot-data"
        )
        for dr in SPLIT_GITHUB_BACKEND_REPOS:
            assert (
                getattr(bot_settings, f"{dr}_github_backend_repo")
                == f"conda-forge/conda-forge-bot-data-{dr}"
            )
            assert (
                getattr(bot_settings, f"{dr}_github_backend_raw_base_url")
                == f"https://github.com/conda-forge/conda-forge-bot-data-{dr}/raw/main/"
            )
        assert bot_settings.github_runner_debug is False
        assert 0 <= bot_settings.frac_update_upstream_versions <= 1
        assert 0 <= bot_settings.frac_update_node_attrs <= 1

    def test_env_conda_forge_org(self, temporary_environment):
        os.environ.clear()

        os.environ[ENV_CONDA_FORGE_ORG] = "myorg"

        bot_settings = BotSettings()

        assert bot_settings.conda_forge_org == "myorg"

    def test_reject_invalid_conda_forge_org(self, temporary_environment):
        os.environ.clear()

        os.environ["CF_TICK_CONDA_FORGE_ORG"] = "invalid org"

        with pytest.raises(ValidationError, match="should match pattern"):
            BotSettings()

    def test_reject_invalid_repo_pattern(self, temporary_environment):
        os.environ.clear()

        os.environ["CF_TICK_GRAPH_GITHUB_BACKEND_REPO"] = "no-owner-repo"

        with pytest.raises(ValidationError, match="should match pattern"):
            BotSettings()

    @pytest.mark.parametrize("value", [-0.1, 1.1])
    @pytest.mark.parametrize(
        "attribute", ["FRAC_UPDATE_UPSTREAM_VERSIONS", "FRAC_UPDATE_NODE_ATTRS"]
    )
    def test_reject_invalid_fraction(
        self, attribute: str, value: float, temporary_environment
    ):
        os.environ.clear()

        os.environ[f"CF_TICK_{attribute}"] = str(value)

        with pytest.raises(ValidationError, match="Input should be (greater|less)"):
            BotSettings()

    @pytest.mark.parametrize("value", [0.0, 1.0])
    @pytest.mark.parametrize(
        "attribute", ["FRAC_UPDATE_UPSTREAM_VERSIONS", "FRAC_UPDATE_NODE_ATTRS"]
    )
    def test_accept_valid_fraction(
        self, attribute: str, value: float, temporary_environment
    ):
        os.environ.clear()

        os.environ[f"CF_TICK_{attribute}"] = str(value)

        bot_settings = BotSettings()

        assert getattr(bot_settings, attribute.lower()) == value


def test_use_settings(temporary_environment):
    os.environ.clear()
    bot_settings = settings()
    bot_settings.github_runner_debug = True

    with use_settings(bot_settings):
        ret_settings = settings()
        assert ret_settings.github_runner_debug is True

        # there should be no side effects
        bot_settings.github_runner_debug = False
        ret_settings.github_runner_debug = False

        side_effect_check_settings = settings()
        assert side_effect_check_settings.github_runner_debug is True

    # the settings should be restored
    assert settings().github_runner_debug is False


def test_get_container_env_command_args():
    args = get_container_env_command_args()
    assert len(args) == 2 * (len(SPLIT_GITHUB_BACKEND_REPOS) + 1) + 2

    for i in range(0, len(args), 2):
        assert args[i] == "-e"

    assert args[1] == f"CF_TICK_CONDA_FORGE_ORG={settings().conda_forge_org}"

    for i, dr in zip(range(3, len(args), 2), ["graph"] + SPLIT_GITHUB_BACKEND_REPOS):
        repo = getattr(settings(), f"{dr}_github_backend_repo")
        assert args[i] == f"CF_TICK_{dr.upper()}_GITHUB_BACKEND_REPO={repo}"
