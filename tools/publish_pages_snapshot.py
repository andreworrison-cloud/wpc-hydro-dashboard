#!/usr/bin/env python3
"""Publish the GitHub Pages working tree as a bounded, history-free snapshot.

The durable source branch remains main. The pages-live branch contains the
currently served site and generated products, but every publication is a root
commit with no parents. An explicit force-with-lease protects concurrent
publishers from overwriting one another.

This module intentionally does not copy .github/ into pages-live. Workflow
definitions remain on the durable source branch only.
"""
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

DEFAULT_BRANCH = "pages-live"
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_ATTEMPTS = 4

# These files are operational runtime products owned by dedicated model
# workflows. Source synchronization from main must never replace a fresher
# pages-live product with an archived/bootstrap copy from the durable branch.
MODEL_RUNTIME_PREFIXES = (
    "static/cam_",
    "static/ero_",
    "static/rap_",
    "static/hrrr_",
    "static/leg_",
)


def run(cmd, *, cwd=None, check=True, env=None):
    result = subprocess.run(
        [str(x) for x in cmd],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {cmd[0]}")
    return result


def git(repo: Path, *args, check=True):
    return run(["git", "-C", str(repo), *args], check=check)


def safe_rel(value: str) -> str:
    value = value.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe repository path: {value!r}")
    return value


def has_magic(spec: str) -> bool:
    return any(ch in spec for ch in "*?[")


def remove_item(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def copy_item(source_root: Path, target_root: Path, item: Path) -> None:
    rel = item.relative_to(source_root)
    if ".git" in rel.parts or rel.parts[:1] == (".github",):
        return
    dest = target_root / rel
    if item.is_symlink():
        raise ValueError(f"Symlinks are not allowed in Pages snapshots: {rel}")
    if item.is_dir():
        shutil.copytree(item, dest, dirs_exist_ok=True, copy_function=shutil.copy2)
    elif item.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)


def matches(root: Path, spec: str):
    spec = safe_rel(spec)
    if has_magic(spec):
        found = [Path(p) for p in glob.glob(str(root / spec), recursive=True)]
        return sorted(found, key=lambda p: (len(p.parts), str(p)), reverse=True)
    path = root / spec
    return [path] if path.exists() or path.is_symlink() else []


def overlay_specs(source: Path, target: Path, specs: list[str]) -> None:
    for raw in specs:
        spec = safe_rel(raw)
        # Synchronize each pathspec: remove old matches, then copy current source matches.
        for old in matches(target, spec):
            remove_item(old)
        for item in reversed(matches(source, spec)):
            copy_item(source, target, item)


def copy_full_source(source: Path, target: Path) -> None:
    for child in target.iterdir():
        remove_item(child)
    for item in source.iterdir():
        if item.name in {".git", ".github"}:
            continue
        copy_item(source, target, item)


def remote_head(repo: Path, branch: str) -> str | None:
    result = git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    line = result.stdout.strip()
    return line.split()[0] if line else None


def extract_remote(repo: Path, branch: str, destination: Path) -> str | None:
    expected = remote_head(repo, branch)
    if not expected:
        return None
    git(repo, "fetch", "--no-tags", "--depth=1", "origin", f"refs/heads/{branch}")
    fetched = git(repo, "rev-parse", "FETCH_HEAD").stdout.strip()
    if fetched != expected:
        # The branch moved between ls-remote and fetch. Use the exact fetched tip
        # as the lease expectation and snapshot base.
        expected = fetched
    names = git(repo, "ls-tree", "-r", "--name-only", expected).stdout.splitlines()
    if not names:
        # git archive emits zero bytes for an empty tree. That is a valid
        # bootstrap snapshot, not a corrupt archive.
        return expected
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", expected],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    with tarfile.open(fileobj=__import__("io").BytesIO(archive)) as tf:
        for member in tf.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise ValueError(f"Unsafe entry in {branch}: {member.name}")
        tf.extractall(destination, filter="data")
    return expected


def snapshot_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def build_root_commit(tree_root: Path, message: str) -> tuple[str, str]:
    gitdir = tree_root / ".git"
    if gitdir.exists():
        shutil.rmtree(gitdir)
    run(["git", "init", "-q"], cwd=tree_root)
    run(["git", "config", "user.name", "github-actions[bot]"], cwd=tree_root)
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=tree_root)
    run(["git", "add", "-A"], cwd=tree_root)
    tree = run(["git", "write-tree"], cwd=tree_root).stdout.strip()
    commit = run(["git", "commit-tree", tree, "-m", message], cwd=tree_root).stdout.strip()
    parents = run(["git", "rev-list", "--parents", "-n", "1", commit], cwd=tree_root).stdout.split()
    if len(parents) != 1:
        raise RuntimeError("Pages snapshot commit unexpectedly has a parent")
    return tree, commit


def authenticated_remote() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPOSITORY are required for publication")
    return f"https://x-access-token:{token}@github.com/{repository}.git"


def publish(repo: Path, branch: str, specs: list[str], message: str, full_source: bool) -> str:
    source = repo.resolve()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        with tempfile.TemporaryDirectory(prefix="pages-live-") as tmp:
            target = Path(tmp) / "tree"
            target.mkdir()
            expected = extract_remote(repo, branch, target)

            if full_source:
                copy_full_source(source, target)
            else:
                if not specs:
                    raise ValueError("At least one --path is required unless --full-source is used")
                overlay_specs(source, target, specs)

            size = snapshot_bytes(target)
            if size > MAX_SNAPSHOT_BYTES:
                raise ValueError(
                    f"Pages snapshot is {size / 1024 / 1024:.1f} MiB, above the 512 MiB safety budget"
                )

            tree, commit = build_root_commit(target, message)
            if expected:
                remote_tree = git(repo, "rev-parse", f"{expected}^{{tree}}").stdout.strip()
                if tree == remote_tree:
                    print(f"{branch}: no content change; preserving {expected}", flush=True)
                    return expected

            run(["git", "remote", "add", "origin", authenticated_remote()], cwd=target)
            if expected:
                push = run(
                    [
                        "git",
                        "push",
                        f"--force-with-lease=refs/heads/{branch}:{expected}",
                        "origin",
                        f"{commit}:refs/heads/{branch}",
                    ],
                    cwd=target,
                    check=False,
                )
            else:
                push = run(
                    ["git", "push", "origin", f"{commit}:refs/heads/{branch}"],
                    cwd=target,
                    check=False,
                )

            if push.returncode == 0:
                print(
                    f"{branch}: published root snapshot {commit}; "
                    f"{size / 1024 / 1024:.1f} MiB; attempt {attempt}",
                    flush=True,
                )
                return commit

            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(push.stderr.strip() or "Pages snapshot publication failed")
            print(f"{branch}: lease changed during publication; retrying from latest snapshot", flush=True)
            time.sleep(attempt * 3)
    raise AssertionError("unreachable")


def restore(repo: Path, branch: str, specs: list[str]) -> None:
    if not specs:
        raise ValueError("restore requires at least one --path")
    source = repo.resolve()
    with tempfile.TemporaryDirectory(prefix="pages-live-restore-") as tmp:
        remote = Path(tmp) / "remote"
        remote.mkdir()
        expected = extract_remote(repo, branch, remote)
        if not expected:
            raise RuntimeError(f"Required Pages snapshot branch {branch!r} does not exist")
        overlay_specs(remote, source, specs)
        print(f"{branch}: restored {len(specs)} pathspec(s) from {expected}", flush=True)


def is_model_runtime_owned(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in MODEL_RUNTIME_PREFIXES)


def changed_paths(repo: Path, before: str, after: str) -> list[str]:
    zeros = set(before) == {"0"}
    if zeros:
        return []
    result = git(repo, "diff", "--name-only", "--diff-filter=ACMRD", before, after)
    paths = []
    for line in result.stdout.splitlines():
        rel = safe_rel(line.strip())
        if rel == ".github" or rel.startswith(".github/"):
            continue
        if is_model_runtime_owned(rel):
            print(
                f"Skipping model runtime-owned path during source sync: {rel}",
                flush=True,
            )
            continue
        paths.append(rel)
    return sorted(set(paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    pub = sub.add_parser("publish")
    pub.add_argument("--branch", default=DEFAULT_BRANCH)
    pub.add_argument("--message", required=True)
    pub.add_argument("--path", action="append", default=[])
    pub.add_argument("--full-source", action="store_true")
    pub.add_argument("--repo", type=Path, default=Path.cwd())

    res = sub.add_parser("restore")
    res.add_argument("--branch", default=DEFAULT_BRANCH)
    res.add_argument("--path", action="append", required=True)
    res.add_argument("--repo", type=Path, default=Path.cwd())

    sync = sub.add_parser("sync-source")
    sync.add_argument("--branch", default=DEFAULT_BRANCH)
    sync.add_argument("--before", required=True)
    sync.add_argument("--after", required=True)
    sync.add_argument("--repo", type=Path, default=Path.cwd())

    args = parser.parse_args()
    repo = args.repo.resolve()

    if args.action == "publish":
        publish(repo, args.branch, args.path, args.message, args.full_source)
    elif args.action == "restore":
        restore(repo, args.branch, args.path)
    else:
        paths = changed_paths(repo, args.before, args.after)
        if not paths:
            print("No non-workflow source paths require Pages synchronization.", flush=True)
            return
        publish(
            repo,
            args.branch,
            paths,
            f"Sync Pages source from main {args.after[:12]}",
            False,
        )


if __name__ == "__main__":
    main()
