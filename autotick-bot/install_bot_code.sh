#!/bin/bash

# Environment Variables:
# - CF_FEEDSTOCK_OPS_CONTAINER_NAME: The name of the container image to use for the bot (optional, not used but left intact)
# - CF_FEEDSTOCK_OPS_CONTAINER_TAG: The tag of the container image to use for the bot (optional).
# - CF_TICK_GRAPH_GITHUB_BACKEND_REPO: The GitHub repository to clone cf-graph from. Default: conda-forge/conda-forge-bot-data
# - CF_TICK_VERSIONS_GITHUB_BACKEND_REPO: The GitHub repository to clone the versions data from. If this
#   value differs from CF_TICK_GRAPH_GITHUB_BACKEND_REPO, then the repo is cloned to versions under the
#   CF_TICK_GRAPH_GITHUB_BACKEND_REPO repo. Default: conda-forge/conda-forge-bot-data

# Sets the following environment variables via GITHUB_ENV:
# - CF_FEEDSTOCK_OPS_CONTAINER_NAME (see above)
# - CF_FEEDSTOCK_OPS_CONTAINER_TAG (see above)

set -euo pipefail

export PYTHONUNBUFFERED=1

git config --global user.name regro-cf-autotick-bot
git config --global user.email 36490558+regro-cf-autotick-bot@users.noreply.github.com
git config --global pull.rebase false

# we pin everything now so no need to update this
# conda update conda-forge-pinning --yes

cd conda-forge-bot

pip install --no-deps --no-build-isolation -e .

cd ..

clone_graph="true"
for arg in "$@"; do
  if [[ "$arg" == "--no-clone-graph" ]]; then
    clone_graph="false"
  fi
done
if [[ "${clone_graph}" == "true" ]]; then
  cf_graph_repo=${CF_TICK_GRAPH_GITHUB_BACKEND_REPO:-"conda-forge/conda-forge-bot-data"}
  cf_graph_remote="https://github.com/${cf_graph_repo}.git"

  failed="true"
  for itr in {1..5}; do
    echo "clone iteration ${itr}"

    set +e
    # please make sure the cloning depth is always identical to the one used in the integration tests (test_integration.py)
    git clone --depth=5 "${cf_graph_remote}" cf-graph || false
    set -e

    if [[ "$?" == "0" ]]; then
      failed="false"
      break
    else
      rm -rf cf-graph
    fi
  done

  if [[ "${failed}" == "true" ]]; then
    echo "graph clone failed!"
    exit 1
  fi

  versions_repo=${CF_TICK_VERSIONS_GITHUB_BACKEND_REPO:-"conda-forge/conda-forge-bot-data"}
  versions_remote="https://github.com/${versions_repo}.git"
  if [[ "${versions_repo}" != "${cf_graph_repo}"]]; then
    failed="true"
    for itr in {1..5}; do
      echo "clone iteration ${itr}"

      pushd cf-graph
      set +e
      # please make sure the cloning depth is always identical to the one used in the integration tests (test_integration.py)
      git clone --depth=5 "${versions_remote}" versions || false
      set -e
      popd

      if [[ "$?" == "0" ]]; then
        failed="false"
        break
      else
        rm -rf cf-graph/versions
      fi
    done

    if [[ "${failed}" == "true" ]]; then
      echo "versions clone failed!"
      exit 1
    else
      # do not allow git deploys in this case
      rm -rf cf-graph/versions/.git
      rm -rf cf-graph/.git
    fi
  fi
else
  echo "Skipping cloning of cf-graph"
fi

docker_name=${CF_FEEDSTOCK_OPS_CONTAINER_NAME:-"quay.io/condaforge/conda-forge-tick"}
bot_tag=$(python -c "import conda_forge_tick; print(conda_forge_tick.__version__)")
docker_tag=${CF_FEEDSTOCK_OPS_CONTAINER_TAG:-${bot_tag}}

pull_cont="true"
for arg in "$@"; do
  if [[ "$arg" == "--no-pull-container" ]]; then
    pull_cont="false"
  fi
done
if [[ "${pull_cont}" == "true" ]]; then
  failed="true"
  for itr in {1..5}; do
    echo "docker pull iteration ${itr}"

    set +e
    docker pull "${docker_name}:${docker_tag}" || false
    set -e

    if [[ "$?" == "0" ]]; then
      failed="false"
      break
    fi
  done

  if [[ "${failed}" == "true" ]]; then
    echo "docker pull failed!"
    exit 1
  fi
fi

# left intact if already set
export CF_FEEDSTOCK_OPS_CONTAINER_TAG="${docker_tag}"
export CF_FEEDSTOCK_OPS_CONTAINER_NAME="${docker_name}"

echo "CF_FEEDSTOCK_OPS_CONTAINER_TAG=${CF_FEEDSTOCK_OPS_CONTAINER_TAG}" >> "$GITHUB_ENV"
echo "CF_FEEDSTOCK_OPS_CONTAINER_NAME=${CF_FEEDSTOCK_OPS_CONTAINER_NAME}" >> "$GITHUB_ENV"

echo -e "\n\n============================================\n============================================"
conda info
conda config --show-sources
conda list --show-channel-urls
echo -e "\n\n============================================\n============================================"
