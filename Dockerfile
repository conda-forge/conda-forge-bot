FROM mambaorg/micromamba:2.6.2
ARG SETUPTOOLS_SCM_PRETEND_VERSION

# baseline env
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION} \
    TMPDIR=/tmp \
    AUTOTICK_BOT_DIR=/opt/conda-forge-bot

COPY --chown=$MAMBA_USER:$MAMBA_USER . $AUTOTICK_BOT_DIR
RUN micromamba install --name base --yes --file $AUTOTICK_BOT_DIR/conda-lock.yml && \
    micromamba uninstall --name base --force --yes \
        pytest \
        pytest-xprocess \
        codecov \
        requests-mock \
        pre-commit \
        pytest-xdist \
        pytest-cov \
        pytest-env \
        pytest-retry \
        pytest-split \
        python-build \
        mitmproxy \
        mypy && \
    # make symlink for conda-build locks (actual directory gets made at run time in the entrypoint)
    # see https://github.com/conda-forge/conda-forge-feedstock-ops/pull/59
    ln -s $TMPDIR/conda_user_conda_build_locks $HOME/.conda_build_locks && \
    # deal with entrypoint
    chmod +x $AUTOTICK_BOT_DIR/docker/entrypoint && \
    # this eval is needed to run activate, but won't be needed later
    eval "$(micromamba shell hook --shell bash)" && \
    micromamba activate base && \
    # remove some testing deps
    # install package
    cd $AUTOTICK_BOT_DIR && \
    pip install --no-deps --no-build-isolation -e . && \
    cd - && \
    # deal with git config
    git config --global --add safe.directory /cf_feedstock_ops_dir && \
    git config --global init.defaultBranch main && \
    git config --global user.email "mambauser@mambauser.mambauser" && \
    git config --global user.name "mambauser mambauser" && \
    micromamba deactivate && \
    # clean out data we do not need
    micromamba clean --all --yes && \
    rm -rf $AUTOTICK_BOT_DIR/.git  && \
    find ${MAMBA_ROOT_PREFIX} -follow -type f -name '*.a' -delete && \
    find ${MAMBA_ROOT_PREFIX} -follow -type f -name '*.pyc' -delete

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "/opt/conda-forge-bot/docker/entrypoint"]
