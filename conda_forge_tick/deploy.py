import contextlib
import logging
import os
import secrets
import subprocess
import sys
import time

import tqdm

from conda_forge_tick.git_utils import (
    delete_file_via_gh_api,
    get_bot_app_token,
    push_file_via_gh_api,
    reset_and_restore_file,
)
from conda_forge_tick.lazy_json_backends import (
    CF_TICK_GRAPH_DATA_HASHMAPS,
    get_github_backend_repo_for_hashmap,
    get_lazy_json_backends,
    lazy_json_override_backends,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.settings import settings
from conda_forge_tick.utils import (
    fold_log_lines,
    get_bot_run_url,
    load_existing_graph,
    run_command_hiding_token,
)

logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()
GIT_CMD_TIMEOUT = 300


def _flush_io():
    sys.stdout.flush()
    sys.stderr.flush()


def _run_git_cmd(cmd, **kwargs):
    r = subprocess.run(["git"] + cmd, timeout=GIT_CMD_TIMEOUT, **kwargs)
    _flush_io()
    if r.returncode != 0:
        raise RuntimeError(
            "git command '{!r}' failed:\nstdout:\n{}\nstderr:\n{}".format(
                cmd, r.stdout, r.stderr
            )
        )
    return r


def _parse_gh_conflicts(output):
    files_to_commit = set()
    files_to_delete = set()
    in_section = False
    indent = None
    for line in output.splitlines():
        print(line, flush=True)
        if not line.strip():
            continue

        # CONFLICT (modify/delete): pr_json/0/9/7/a/1/3254711106.json deleted
        # in 930a956604b17c5fd7cada5c011eb77f4eeebe52 and modified in HEAD.
        # Version HEAD of pr_json/0/9/7/a/1/3254711106.json left in tree.
        if (
            line.startswith("CONFLICT (modify/delete):")
            and "modified in HEAD" in line
            and "deleted in" in line
        ):
            fname = line.split("CONFLICT (modify/delete):")[1].strip().split()[0]
            files_to_delete.add(fname)

        if line.startswith("error:"):
            in_section = True
            continue

        if in_section and indent is not None and not line.startswith(indent):
            in_section = False
            indent = None
            continue

        if in_section:
            if indent is None:
                indent = line[: len(line) - len(line.lstrip())]
            fname = line.strip()
            if os.path.exists(fname):
                files_to_commit.add(fname)
            continue

    return files_to_commit, files_to_delete


def _pull_changes(batch=None):
    r = subprocess.run(
        ["git", "pull", "-s", "recursive", "-X", "theirs"],
        text=True,
        capture_output=True,
        timeout=GIT_CMD_TIMEOUT,
    )
    n_added = 0
    if r.returncode != 0:
        files_to_commit, files_to_delete = _parse_gh_conflicts(
            r.stderr + "\n" + r.stdout
        )

        for fname in files_to_commit:
            n_added += 1
            print(f"committing for conflicts {n_added: >5d}: {fname}", flush=True)
            _run_git_cmd(["add", fname])

        for fname in files_to_delete:
            n_added += 1
            print(f"deleting for conflicts {n_added: >5d}: {fname}", flush=True)
            _run_git_cmd(["rm", "-f", fname])

        if files_to_commit or files_to_delete:
            _step_name = os.environ.get("GITHUB_WORKFLOW", "update graph")
            _run_git_cmd(
                [
                    "commit",
                    "-m",
                    f"{_step_name} - conflicts for pull - {get_bot_run_url()}"
                    if batch is None
                    else f"{_step_name} - conflicts for pull for batch {batch} - {get_bot_run_url()}",
                ],
            )

        _run_git_cmd(["pull", "-s", "recursive", "-X", "theirs"])

    _flush_io()

    return n_added


def _deploy_batch(
    *,
    files_to_add: set[str],
    batch,
    n_added,
    max_per_batch=10,
    exp_backoff_base: float = 1.1,
    exp_backoff_rfrac: float = 0.5,
    max_tries: int = 30,
):
    n_added_this_batch = 0
    while files_to_add and n_added_this_batch < max_per_batch:
        file = files_to_add.pop()
        if file and os.path.exists(file):
            try:
                print(f"committing {n_added: >5d}: {file}", flush=True)
                _run_git_cmd(["add", file])
                n_added_this_batch += 1
                n_added += 1
            except Exception as e:
                print(e, flush=True)

    if n_added_this_batch > 0:
        try:
            _step_name = os.environ.get("GITHUB_WORKFLOW", "update graph")
            _run_git_cmd(
                [
                    "commit",
                    "-m",
                    f"{_step_name} - batch {batch: >3d} - {get_bot_run_url()}",
                ],
            )
        except Exception as e:
            print(e, flush=True)

        status = 1
        num_try = 0
        while status != 0 and num_try < max_tries:
            with fold_log_lines(">>>>>>>>>>>> git pull+push try %d" % num_try):
                try:
                    # pull twice right away to reduce chance of changes between
                    # pull and push
                    for pull_itr in range(2):
                        print(">>>>>>>>>>>> git pull %d/2" % (pull_itr + 1), flush=True)
                        _n_added = _pull_changes(batch)
                        n_added += _n_added
                        n_added_this_batch += _n_added
                except Exception as e:
                    print(
                        ">>>>>>>>>>>> git pull failed: %s" % repr(e),
                        flush=True,
                    )
                    pass

                print(">>>>>>>>>>>> git push try", flush=True)
                status = run_command_hiding_token(
                    [
                        "git",
                        "push",
                        f"https://{get_bot_app_token()}@github.com/{settings().graph_github_backend_repo}.git",
                        settings().graph_repo_default_branch,
                    ],
                    token=get_bot_app_token(),
                )
                if status != 0:
                    print(">>>>>>>>>>>> git push failed", flush=True)
                    interval = exp_backoff_base**num_try
                    interval = interval * exp_backoff_rfrac * (1.0 + RNG.uniform(0, 1))
                    time.sleep(interval)
            num_try += 1

        if status != 0:
            # we did try to push to a branch but it never worked so we'll just stop
            raise RuntimeError("bot did not push its data! stopping!")

    return n_added_this_batch


def _ensure_file_has_dir(pth, dr):
    if not pth.startswith(f"{dr}/"):
        pth = os.path.join(dr, pth)
    return pth


def _get_files_to_delete(drs_to_deploy) -> set[str]:
    files_to_delete = set()
    for dr in drs_to_deploy:
        if not os.path.exists(dr):
            continue

        if os.path.isdir(dr):
            ctx = pushd(dr)
            is_dir = True
        else:
            ctx = contextlib.nullcontext()
            is_dir = False

        with ctx:
            r = subprocess.run(
                ["git", "diff", "--name-status", "--cached", "."],
                text=True,
                capture_output=True,
                check=True,
                timeout=GIT_CMD_TIMEOUT,
            )
            for line in r.stdout.splitlines():
                res = line.strip().split()
                if len(res) < 2:
                    continue
                status, fname = res[0:2]
                if status == "D":
                    if is_dir:
                        fname = _ensure_file_has_dir(fname, dr)
                    logger.debug("deleting file: %s", fname)
                    files_to_delete.add(fname)

    return files_to_delete


def _get_pth_commit_message(pth):
    """Make a nice message for stuff managed via LazyJson."""
    step_name = os.environ.get("GITHUB_WORKFLOW", "update graph")
    msg_pth = pth
    parts = pth.split("/")
    if pth.endswith(".json") and (
        len(parts) > 1 and parts[0] in CF_TICK_GRAPH_DATA_HASHMAPS
    ):
        msg_pth = f"{parts[0]}/{parts[-1]}"
    msg = f"{step_name} - {msg_pth} - {get_bot_run_url()}"
    return msg


def _get_full_repo_name_pth_and_context_from_path(pth):
    default_repo = get_github_backend_repo_for_hashmap("lazy_json")

    pth_parts = pth.split("/")
    if len(pth_parts) > 1:
        hashmap_name = pth_parts[0]
        repo = get_github_backend_repo_for_hashmap(hashmap_name)
    else:
        repo = default_repo

    pth_parts = pth.split("/")
    if repo != default_repo and len(pth_parts) > 1:
        context_dir = pth_parts[0]
        pth = "/".join(pth_parts[1:])
    else:
        context_dir = None

    return repo, pth, context_dir


def _deploy_via_api(
    files_to_add: set[str],
    files_to_delete: set[str],
) -> tuple[set[str], set[str]]:
    files_done = set()
    files_to_try_again = set()
    for pth in tqdm.tqdm(files_to_add, desc="pushing files", ncols=80, file=sys.stdout):
        full_repo_name, pth_to_push, context_dir = (
            _get_full_repo_name_pth_and_context_from_path(pth)
        )

        try:
            with tqdm.tqdm.external_write_mode(file=sys.stdout):
                print(f"[{full_repo_name}] pushing file '{pth_to_push}'", flush=True)

            # make a nice message for stuff managed via LazyJson
            # use path here for nice commit message
            msg = _get_pth_commit_message(pth)

            if context_dir is not None:
                ctx = pushd(context_dir)
            else:
                ctx = contextlib.nullcontext()

            with ctx:
                push_file_via_gh_api(pth_to_push, full_repo_name, msg)
        except Exception as e:
            logger.warning("git push via API failed", exc_info=e)
            files_to_try_again.add(pth)
        else:
            files_done.add(pth)

    for pth in tqdm.tqdm(
        files_to_delete, desc="deleting files", ncols=80, file=sys.stdout
    ):
        full_repo_name, pth_to_push, context_dir = (
            _get_full_repo_name_pth_and_context_from_path(pth)
        )

        try:
            with tqdm.tqdm.external_write_mode(file=sys.stdout):
                print(f"[{full_repo_name}] deleting file '{pth}'", flush=True)

            # make a nice message for stuff managed via LazyJson
            # use path here for nice commit message
            msg = _get_pth_commit_message(pth)

            if context_dir is not None:
                ctx = pushd(context_dir)
            else:
                ctx = contextlib.nullcontext()

            with ctx:
                delete_file_via_gh_api(pth_to_push, full_repo_name, msg)
        except Exception as e:
            logger.warning("git delete via API failed", exc_info=e)
            files_to_try_again.add(pth)
        else:
            files_done.add(pth)

    for pth in files_done:
        pth_parts = pth.split("/")
        if len(pth_parts) > 1:
            dr = pth_parts[0]
            pth_to_restore = "/".join(pth_parts[1:])
        else:
            dr = pth
            pth_to_restore = pth

        if os.path.isdir(dr):
            ctx = pushd(dr)
        else:
            ctx = contextlib.nullcontext()

        with ctx:
            reset_and_restore_file(pth_to_restore)

    return files_done, files_to_try_again


def deploy(
    dry_run: bool = False,
    dirs_to_deploy: list[str] | None = None,
    git_only: bool = False,
    dirs_to_ignore: list[str] | None = None,
):
    if dry_run:
        print("(dry run) deploying", flush=True)
        return

    # make sure the graph can load, if not it will error
    with lazy_json_override_backends(["file-read-only"], use_file_cache=False):
        gx = load_existing_graph()
        for node, attrs in gx.nodes.items():
            with attrs["payload"]:
                pass

    files_to_add: set[str] = set()
    if not dirs_to_deploy:
        drs_to_deploy = [
            "status",
            "mappings",
            "mappings/pypi",
            "ranked_hubs_authorities.json",
            "all_feedstocks.json",
            "import_to_pkg_maps",
        ]
        if "file" in get_lazy_json_backends():
            drs_to_deploy += CF_TICK_GRAPH_DATA_HASHMAPS
            drs_to_deploy += ["graph.json", "outputs_to_feedstocks.json"]
    else:
        if dirs_to_ignore:
            raise RuntimeError(
                "You cannot specify both `dirs_to_deploy` "
                "and `dirs_to_ignore` when deploying the graph!"
            )
        drs_to_deploy = dirs_to_deploy

    for dr in drs_to_deploy:
        logger.info("checking file/directory: %s", dr)
        if not os.path.exists(dr):
            continue

        if os.path.isdir(dr):
            is_dir = True
            ctx = pushd(dr)
            extra_cmd = ["."]
        else:
            is_dir = False
            ctx = contextlib.nullcontext()
            extra_cmd = [dr]

        with ctx:
            # untracked
            _files_to_add = set(
                _run_git_cmd(
                    ["ls-files", "-o", "--exclude-standard"] + extra_cmd,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines(),
            )
            # need to add the other path segment
            if is_dir:
                _files_to_add = {_ensure_file_has_dir(fn, dr) for fn in _files_to_add}
            logger.debug("adding files: %r", _files_to_add)
            files_to_add |= _files_to_add

            # changed
            _files_to_add = set(
                _run_git_cmd(
                    ["diff", "--name-only"] + extra_cmd,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines(),
            )
            if is_dir:
                _files_to_add = {_ensure_file_has_dir(fn, dr) for fn in _files_to_add}
            logger.debug("adding files: %r", _files_to_add)
            files_to_add |= _files_to_add

            # modified and staged but not deleted
            # these come out with the full path
            _files_to_add = set(
                _run_git_cmd(
                    ["diff", "--name-only", "--cached", "--diff-filter=d"] + extra_cmd,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines(),
            )
            if is_dir:
                _files_to_add = {_ensure_file_has_dir(fn, dr) for fn in _files_to_add}
            logger.debug("adding files: %r", _files_to_add)
            files_to_add |= _files_to_add

    files_to_delete = _get_files_to_delete(drs_to_deploy)

    if dirs_to_ignore:
        print("ignoring dirs:", dirs_to_ignore, flush=True)
        new_files_to_add = set()
        for fn in files_to_add:
            if any(fn.startswith(f"{dr}/") for dr in dirs_to_ignore):
                reset_and_restore_file(fn)
                print("ignoring file to add:", fn, flush=True)
            else:
                new_files_to_add.add(fn)
        files_to_add = new_files_to_add

        new_files_to_delete = set()
        for fn in files_to_delete:
            if any(fn.startswith(f"{dr}/") for dr in dirs_to_ignore):
                reset_and_restore_file(fn)
                print("ignoring file to delete:", fn, flush=True)
            else:
                new_files_to_delete.add(fn)
        files_to_delete = new_files_to_delete

    print("found %d files to add" % len(files_to_add), flush=True)
    print("found %d files to delete" % len(files_to_delete), flush=True)

    if files_to_add or files_to_delete:
        if not git_only:
            files_done, files_to_try_again = _deploy_via_api(
                files_to_add, files_to_delete
            )
            print(
                f"deployed {len(files_done)} files to graph; {len(files_to_try_again)} did not deploy!",
                flush=True,
            )
            if files_to_try_again:
                sys.exit(1)
        else:
            if (
                settings().graph_github_backend_repo
                != settings().versions_github_backend_repo
            ):
                raise RuntimeError(
                    "git-based deploys of the graph data do not work for split backends!"
                )

            batch = 0
            n_added = 0
            while files_to_add:
                batch += 1
                n_added += _deploy_batch(
                    files_to_add=files_to_add,
                    n_added=n_added,
                    batch=batch,
                )

            print(f"deployed {n_added} files to graph in {batch} batches", flush=True)
