################################################################################
# File: cleanup.py
# Path: {PROJECT_ROOT}/cleanup.py
# Created by: Ryan Severe
# Created: 2026-11-07
# Last Updated: 2026-11-08
# Description: Lists, then removes in one call, everything a workstream owns in
#              scratch/<objective>/ - its files, its worktrees and their merged
#              branches. Refuses a dirty worktree or unmerged work rather than
#              discarding it. Runs once, when the objective is done.
################################################################################
# ===========================================================================
#
#
#            "~,
#                *m,
#                   *9m;
#                       *%pg
#                          "YRWu
#                              *9$&w
#                                  *R$&w
#   ;j]@@W;                   *w,      79&&w;
#   :|*%MT"                     7&&w,      ?78BWw
# . ,|*       -p     ~            *R$$$gw,     '*MU@m,
#            =W/?*%NMWgw             *T&$F ,@w;     "*4[%m,
#              7R$$$$$$$$g          yg$$Gg$@@Hh!j ,w     "*w|j=,
#       ..     ]K@ww[T$Fff            >*MB&&@@Hh ]hk{!!~^     "*v'
#          '|;, *M@@&&$P                 $$&@HHH\  ` ;w,,   ,~""
#            "|jj]]%@F"                  ]$@@H, ;*M%P)a$$C  c
#           . :|j[M"                     ]@@HHr TfR4&$NE*,/~<'
#             `!||j]@@@A`                ]@@Hh~ *TT"" "* ^ r  '~
#                *ojKM"                  l@Hh~  "*|"'   /        `
#                                        @HHkC ,;!"
#                                       ]HHhr/|!"'
#                                       #Hhr!||"
#                             ,@r       hkr!||'
#                                      [k{|!"
#                                     (r!!"        r
#                                     !!"        r
#                                      ";      /
#                                             '
#                                            '
# ===========================================================================


from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The workstream's objective in kebab case - never a ticket number: a workstream spans tickets.
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SCRATCH = "scratch"
GIT_TIMEOUT = 60


class CleanupError(Exception):
    pass


@dataclass
class Worktree:
    path: Path
    head: str
    branch: str | None
    problems: list[str] = field(default_factory=list)


@dataclass
class Inventory:
    root: Path
    name: str
    directory: Path
    default: str | None
    worktrees: list[Worktree]
    files: list[str]

    @property
    def problems(self) -> list[str]:
        return [p for wt in self.worktrees for p in wt.problems]


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One git call with a timeout. The caller judges the exit code."""
    try:
        return subprocess.run(("git", *args), cwd=cwd, capture_output=True, text=True,
                              timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CleanupError(f"git {' '.join(args)} did not run: {exc}") from exc


def git_out(cwd: Path, *args: str) -> str:
    """Stdout of a git call that must succeed."""
    result = git(cwd, *args)
    if result.returncode != 0:
        raise CleanupError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def key(path: Path) -> str:
    """A path as a comparable string. Windows paths compare case-insensitively."""
    return os.path.normcase(str(path.resolve()))


def within(path: Path, directory: Path) -> bool:
    """True when path is directory itself or anything below it."""
    p, d = key(path), key(directory)
    return p == d or p.startswith(d.rstrip(os.sep) + os.sep)


def repo_root(cwd: Path) -> Path:
    """The primary checkout, so a run from any worktree aims at the same scratch/."""
    common = git_out(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common).resolve().parent


def workstream_dir(root: Path, name: str) -> Path:
    """scratch/<name>, refused unless the name is kebab case and the path stays inside."""
    if not NAME.fullmatch(name):
        raise CleanupError(f"{name!r} is not a workstream name - lower-case kebab case only, "
                           "such as release-prep")
    scratch = root / SCRATCH
    directory = scratch / name
    if not directory.is_dir():
        raise CleanupError(f"no workstream directory {SCRATCH}/{name} in {root}")
    if directory.is_symlink() or key(directory.parent) != key(scratch):
        raise CleanupError(f"{SCRATCH}/{name} resolves outside {SCRATCH}/, so it is not removed")
    return directory


def default_branch(root: Path) -> str:
    """origin's default branch as a remote ref. Never assumed: a guess decides what is merged."""
    result = git(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    ref = result.stdout.strip()
    if result.returncode != 0 or not ref.startswith("refs/remotes/origin/"):
        raise CleanupError("could not tell the default branch - origin/HEAD is not set. "
                           "Run: git remote set-head origin --auto")
    return ref.removeprefix("refs/remotes/")


def worktrees_in(root: Path, directory: Path) -> list[Worktree]:
    """The registered worktrees whose path is inside the workstream directory."""
    found: list[Worktree] = []
    for block in git_out(root, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines() if line)
        if "worktree" not in fields or not within(Path(fields["worktree"]), directory):
            continue
        branch = fields.get("branch", "").removeprefix("refs/heads/") or None
        found.append(Worktree(Path(fields["worktree"]).resolve(), fields.get("HEAD", ""), branch))
    return found


def judge(root: Path, wt: Worktree, default: str) -> None:
    """Record why removing this worktree or its branch would discard work."""
    label = wt.path.relative_to(root).as_posix() if within(wt.path, root) else str(wt.path)
    if not wt.path.is_dir():
        wt.problems.append(f"{label} is registered but missing - run: git worktree prune")
        return
    status = git(wt.path, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        wt.problems.append(f"{label}: could not read its status - {status.stderr.strip()}")
    elif status.stdout.strip():
        count = len(status.stdout.strip().splitlines())
        wt.problems.append(f"{label} is dirty - {count} changed file(s)")
    merged = git(root, "merge-base", "--is-ancestor", wt.head, default)
    what = f"branch {wt.branch}" if wt.branch else f"detached commit {wt.head[:12]}"
    if merged.returncode == 1:
        wt.problems.append(f"{label}: {what} is not merged into {default}")
    elif merged.returncode != 0:
        wt.problems.append(f"{label}: could not tell whether {what} is merged - "
                           f"{merged.stderr.strip()}")


def files_in(directory: Path, worktrees: list[Worktree]) -> list[str]:
    """Every file under the directory, not descending into a worktree: git removes those."""
    skip = {key(wt.path) for wt in worktrees}
    found: list[str] = []
    for current, dirs, names in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if key(Path(current) / d) not in skip)
        for name in sorted(names):
            found.append((Path(current) / name).relative_to(directory).as_posix())
    return found


def inventory(cwd: Path, name: str) -> Inventory:
    """What --apply would remove, and every reason it would refuse. Changes nothing."""
    root = repo_root(cwd)
    directory = workstream_dir(root, name)
    worktrees = worktrees_in(root, directory)
    default = default_branch(root) if worktrees else None
    for wt in worktrees:
        judge(root, wt, default)
    return Inventory(root, name, directory, default, worktrees, files_in(directory, worktrees))


def report(inv: Inventory) -> None:
    """The listing the operator approves."""
    print(f"workstream: {inv.name}")
    print(f"directory:  {SCRATCH}/{inv.name} in {inv.root}")
    print(f"worktrees ({len(inv.worktrees)}):")
    for wt in inv.worktrees:
        what = f"branch {wt.branch}" if wt.branch else f"detached at {wt.head[:12]}"
        state = "refused" if wt.problems else f"merged into {inv.default}, clean"
        print(f"  {wt.path.relative_to(inv.directory).as_posix()}  {what}  {state}")
    print(f"files ({len(inv.files)}):")
    for rel in inv.files:
        print(f"  {rel}")


def clear_read_only(func, path, _exc) -> None:
    """Git writes objects read-only, and Windows will not delete a read-only file."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(directory: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(directory, onexc=clear_read_only)
    else:
        shutil.rmtree(directory, onerror=clear_read_only)


def apply(inv: Inventory) -> None:
    """Worktrees, then their branches, then the directory; each read back afterwards."""
    for wt in inv.worktrees:
        git_out(inv.root, "worktree", "remove", str(wt.path))
        print(f"removed worktree {wt.path.relative_to(inv.directory).as_posix()}")
    for wt in inv.worktrees:
        if wt.branch:
            # -d judges against HEAD or the upstream, either of which can trail the remote's
            # default branch; judge() has already established the branch is merged there.
            git_out(inv.root, "branch", "-D", wt.branch)
            print(f"deleted branch {wt.branch}")
    remove_tree(inv.directory)
    left = [f"{SCRATCH}/{inv.name} still exists"] if inv.directory.exists() else []
    for wt in inv.worktrees:
        if wt.branch and git(inv.root, "rev-parse", "--verify", "--quiet",
                             f"refs/heads/{wt.branch}").returncode == 0:
            left.append(f"branch {wt.branch} still exists")
    if worktrees_in(inv.root, inv.directory):
        left.append("a worktree is still registered inside it")
    if left:
        raise CleanupError("removal did not complete: " + "; ".join(left))
    print(f"removed {SCRATCH}/{inv.name}")


def main(argv: list[str] | None = None, cwd: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List, or with --apply remove, a workstream's scratch directory.")
    parser.add_argument("--ws", required=True, help="the workstream's objective, kebab case")
    parser.add_argument("--apply", action="store_true",
                        help="remove everything listed, in this one call")
    args = parser.parse_args(argv)
    here = Path(cwd or Path.cwd())
    try:
        inv = inventory(here, args.ws)
        report(inv)
        if inv.problems:
            print("--apply refuses, and removes nothing, while any of these hold:")
            for problem in inv.problems:
                print(f"  REFUSED: {problem}")
            return 1
        if not args.apply:
            print("nothing changed - run again with --apply to remove all of the above")
            return 0
        if within(here, inv.directory):
            raise CleanupError(f"the current directory is inside {SCRATCH}/{inv.name}; "
                               "run from the repository root")
        apply(inv)
    except CleanupError as exc:
        print(f"REFUSED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
