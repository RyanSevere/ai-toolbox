#!/usr/bin/env python3
################################################################################
# File: prime.py
# Path: {PROJECT_ROOT}/prime.py
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-08
# Description: Collects the durable facts /prime reports - repository state,
#              design-document status lines, nested AGENTS.md headings and run
#              targets - for one or more repositories in one command. Prints
#              raw facts only; the report format lives in prime.prompt.md.
#              Rendered into every repo as .github/scripts/prime.py so the
#              invocation is identical everywhere and falls under the existing
#              python terminal auto-approval.
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
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

DOC_DIRS = ("docs", "project-docs", "planning-docs")
ROOT_DOC_SKIP = {"README.md", "AGENTS.md", "CHANGELOG.md", "LICENSE.md"}
RUN_TARGETS = {"package.json", "Makefile", "docker-compose.yml", "pyproject.toml",
               "requirements.txt"}
# A repository's control command: an extensionless *ctl, as systemctl and kubectl are.
CONTROL_COMMAND = re.compile(r"^[A-Za-z0-9_-]+ctl$")
# Select-String, which this replaces, matched case-insensitively.
STATUS = re.compile(r"^\*\*Status:\*\*\s*(.+)$", re.IGNORECASE | re.MULTILINE)
HEADING = re.compile(r"^#{1,6}\s+\S")
FENCE = re.compile(r"^\s*(```|~~~)")
GIT_TIMEOUT = 30


class PrimeError(Exception):
    """A step could not establish its fact. Reported, never swallowed."""


def git(repo: Path, *args: str) -> str:
    """Run a read-only git command in repo and return stdout."""
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrimeError(f"git {args[0]}: {exc}") from exc
    if done.returncode != 0:
        raise PrimeError(f"git {args[0]} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def repo_root(arg: str) -> Path:
    """Resolve a command-line path to the top of its git work tree."""
    path = Path(arg).expanduser()
    if not path.is_dir():
        raise PrimeError(f"not a directory: {arg}")
    return Path(git(path, "rev-parse", "--show-toplevel").strip())


def listed_files(repo: Path) -> list[str]:
    """Tracked plus untracked-but-not-ignored files, so node_modules and scratch/ drop out."""
    out = git(repo, "ls-files", "--cached", "--others", "--exclude-standard")
    return sorted({line for line in out.splitlines() if line})


def step_state(repo: Path) -> list[str]:
    status = git(repo, "status", "-sb").splitlines()
    log = git(repo, "log", "-6", "--format=%h %ad %s", "--date=short").splitlines()
    return status + ["log:"] + [f"  {line}" for line in log]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def step_docs(repo: Path) -> list[str]:
    docs = [p for d in DOC_DIRS if (repo / d).is_dir() for p in sorted((repo / d).glob("*.md"))]
    docs += [p for p in sorted(repo.glob("*.md")) if p.name not in ROOT_DOC_SKIP]
    lines = []
    for doc in docs:
        found = STATUS.search(read_text(doc))
        status = found.group(1).replace("**", "").strip() if found else "-"
        lines.append(f"{doc.relative_to(repo).as_posix()} | {status}")
    return lines


def headings(text: str) -> list[str]:
    """Markdown headings, verbatim, skipping anything inside a fenced code block."""
    out, fenced = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and HEADING.match(line):
            out.append(line.rstrip())
    return out


def step_traps(repo: Path, files: list[str]) -> list[str]:
    lines = []
    for rel in files:
        if rel.rsplit("/", 1)[-1] != "AGENTS.md" or "/" not in rel:
            continue
        lines.append(rel)
        lines += [f"  {h}" for h in headings(read_text(repo / rel))]
    return lines


def step_commands(repo: Path, files: list[str]) -> list[str]:
    lines = [f"target: {rel}" for rel in files
             if (rel.rsplit("/", 1)[-1] in RUN_TARGETS
                 or CONTROL_COMMAND.match(rel.rsplit("/", 1)[-1]))
             and len(rel.split("/")) <= 3]
    for rel in files:
        if rel.rsplit("/", 1)[-1] != "package.json" or len(rel.split("/")) > 3:
            continue
        try:
            scripts = json.loads(read_text(repo / rel)).get("scripts") or {}
        except (ValueError, AttributeError) as exc:
            lines.append(f"[error] scripts: {rel}: unreadable package.json: {exc}")
            continue
        lines.append(f"scripts: {rel}: {', '.join(scripts)}")
    return lines


def prime_one(arg: str, emit: Callable[[str], None]) -> bool:
    """Print every step for one repository. Returns False if anything failed."""
    try:
        repo = repo_root(arg)
    except PrimeError as exc:
        emit(f"=== REPO {arg}")
        emit(f"[error] {exc}")
        return False
    emit(f"=== REPO {repo.name} ({repo})")
    ok = True
    try:
        files = listed_files(repo)
    except PrimeError as exc:
        emit(f"[error] file listing: {exc}")
        files, ok = None, False
    steps: list[tuple[str, Callable[[], list[str]]]] = [
        ("state", lambda: step_state(repo)),
        ("docs", lambda: step_docs(repo)),
        ("traps", lambda: step_traps(repo, files)),
        ("commands", lambda: step_commands(repo, files)),
    ]
    for name, run in steps:
        emit(f"[{name}]")
        if files is None and name in ("traps", "commands"):
            emit(f"[error] {name}: skipped, the file listing failed")
            continue
        try:
            lines = run()
        except (PrimeError, OSError) as exc:
            emit(f"[error] {name}: {exc}")
            ok = False
            continue
        for line in lines or ["none"]:
            emit(line)
            ok = ok and not line.startswith("[error]")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect /prime facts for one or more repositories.")
    parser.add_argument("repos", nargs="+", help="repository paths, one per workspace folder")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    results = [prime_one(arg, print) for arg in args.repos]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
