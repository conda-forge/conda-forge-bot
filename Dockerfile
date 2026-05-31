FROM mambaorg/micromamba:2.6.2
ARG SETUPTOOLS_SCM_PRETEND_VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}

# baseline env
ENV TMPDIR=/tmp
ENV AUTOTICK_BOT_DIR=/opt/conda-forge-bot

COPY --chown=$MAMBA_USER:$MAMBA_USER . $AUTOTICK_BOT_DIR
RUN micromamba install --name base --yes --file $AUTOTICK_BOT_DIR/conda-lock.yml && \
    # make symlink for conda-build locks (actual directory gets made at run time in the entrypoint)
    # see https://github.com/conda-forge/conda-forge-feedstock-ops/pull/59
    ln -s $TMPDIR/conda_user_conda_build_locks $HOME/.conda_build_locks && \
    micromamba activate base && \
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
    # deal with entry point
    chmod +x $AUTOTICK_BOT_DIR/docker/entrypoint && \
    mv $AUTOTICK_BOT_DIR/docker/entrypoint /opt/entrypoint && \
    # clean out data we do not need
    micromamba clean --all --yes && \
    rm -rf $AUTOTICK_BOT_DIR/.git  && \
    find ${MAMBA_ROOT_PREFIX} -follow -type f -name '*.a' -delete && \
    find ${MAMBA_ROOT_PREFIX} -follow -type f -name '*.pyc' -delete

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "/opt/entrypoint"]

# TODO: uninstall these?
# mircomamba uninstall \
#     pytest \
#     pytest-xprocess \
#     codecov \
#     requests-mock \
#     pre-commit \
#     pytest-xdist \
#     pytest-cov \
#     pytest-env \
#     pytest-retry \
#     pytest-split \
#     python-build \
#     mitmproxy \
#     mypy \
#     --force --yes && \

