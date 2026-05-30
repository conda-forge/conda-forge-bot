FROM quay.io/condaforge/linux-anvil-x86_64:alma10
ARG SETUPTOOLS_SCM_PRETEND_VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}

# baseline env
ENV TMPDIR=/tmp
ENV AUTOTICK_BOT_DIR=/opt/conda-forge-bot
ENV CONDA_DIR=/opt/conda

# use bash for a while to make conda manipulations easier
SHELL ["/bin/bash", "-l", "-c"]

# build the conda env first
COPY conda-lock.yml $AUTOTICK_BOT_DIR/conda-lock.yml
RUN conda activate base && \
    conda create --name conda-forge-bot --file $AUTOTICK_BOT_DIR/conda-lock.yml --yes --quiet && \
    conda activate conda-forge-bot && \
    conda uninstall \
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
        mypy \
        --force --yes && \
    conda list && \
    # Lucky group gets permission to write in the conda dir
    chown -R root /opt/conda && \
    chgrp -R lucky /opt/conda && chmod -R g=u /opt/conda && \
    conda clean --all --yes && \
    conda deactivate && \
    conda deactivate && \
    find ${CONDA_DIR} -follow -type f -name '*.a' -delete && \
    find ${CONDA_DIR} -follow -type f -name '*.pyc' -delete

# deal with entrypoint
COPY docker/entrypoint /opt/docker/bin/
RUN chmod +x /opt/docker/bin/entrypoint

# now install the bot code
COPY . $AUTOTICK_BOT_DIR
RUN conda activate base && \
    conda activate conda-forge-bot && \
    cd $AUTOTICK_BOT_DIR && \
    pip install --no-deps --no-build-isolation -e . && \
    cd - && \
    conda clean --all --yes && \
    conda deactivate && \
    conda deactivate && \
    # remove .git dir once installed and version is set
    rm -rf $AUTOTICK_BOT_DIR/.git  && \
    find ${CONDA_DIR} -follow -type f -name '*.a' -delete && \
    find ${CONDA_DIR} -follow -type f -name '*.pyc' -delete

# now make the conda user for running tasks and set the user
RUN useradd --shell /bin/bash -c "" -m conda
ENV HOME=/home/conda
ENV USER=conda
ENV LOGNAME=conda
ENV MAIL=/var/spool/mail/conda
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/conda/bin
# make symlink for conda-build locks (actual directory gets made at run time in the entrypoint)
# see https://github.com/conda-forge/conda-forge-feedstock-ops/pull/59
RUN ln -s $TMPDIR/conda_user_conda_build_locks $HOME/.conda_build_locks
RUN chown conda:conda $HOME && \
    chown -R conda:conda /opt/conda-forge-bot && \
    cp -R /etc/skel $HOME && \
    chown -R conda:conda $HOME/skel && \
    (ls -A1 $HOME/skel | xargs -I {} mv -n $HOME/skel/{} $HOME) && \
    rm -Rf $HOME/skel && \
    cd $HOME
USER conda

# deal with git config for user and mounted directory
RUN conda activate conda-forge-bot && \
    git config --global --add safe.directory /cf_feedstock_ops_dir && \
    git config --global init.defaultBranch main && \
    git config --global user.email "conda@conda.conda" && \
    git config --global user.name "conda conda" && \
    conda deactivate && \
    conda init --all --user && \
    find ${CONDA_DIR} -follow -type f -name '*.a' -delete && \
    find ${CONDA_DIR} -follow -type f -name '*.pyc' -delete

# put the shell back
SHELL ["/bin/sh", "-c"]
