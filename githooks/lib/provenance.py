#!/usr/bin/env python3
################################################################################
# File: provenance.py
# Path: {PROJECT_ROOT}/githooks/lib/provenance.py
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-16
# Description: Makes a test's provenance visible. `report` (the pre-push gate,
#              never blocking) flags a commit that edits an existing assertion
#              and changes non-test source together - the shape of "changed the
#              test to fit the code". `classify` (on demand) runs the tests a
#              range added against the source they were written for: passing
#              there means characterisation, failing means written ahead of the
#              code. Both count Intent: and Characterisation: markers.
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
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT = 600
TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(test|spec)\.[jt]sx?$)")
SOURCE = re.compile(r"\.(py|sh|ts|tsx|js|jsx|mjs|cjs)$")
# Assertion lines, language-agnostic.
ASSERTION = re.compile(r"\bassert|\bself\.assert\w*\(|\bexpect\(")
ADDED_TEST = re.compile(r"^\+\s*(?:async\s+)?def\s+(test\w*)\s*\(|^\+\s*(?:it|test)\(\s*['\"`]")
INTENT = re.compile(r"\bIntent:")
CHARACTERISATION = re.compile(r"\bCharacterisation:")
ZERO = re.compile(r"^0+$")


class ProvenanceError(Exception):
    """The check could not be carried out. Never a pass."""


def env() -> dict[str, str]:
    # Run from a hook, GIT_DIR points at the repo being pushed.
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], capture_output=True, timeout=TIMEOUT, cwd=cwd,
                            env=env())
    if result.returncode != 0:
        raise ProvenanceError(f"git {' '.join(args)} failed: "
                              f"{result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode("utf-8", errors="replace")


def resolve(rev: str) -> str | None:
    if not rev or ZERO.match(rev) or not re.fullmatch(r"[\w./^~@{}-]{1,100}", rev):
        return None
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                            capture_output=True, timeout=TIMEOUT, env=env())
    out = result.stdout.decode().strip()
    return out if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", out) else None


def is_test(path: str) -> bool:
    return bool(TEST_FILE.search(path))


def is_source(path: str) -> bool:
    return bool(SOURCE.search(path)) and not is_test(path)


def parent_of(commit: str) -> str | None:
    parents = git("rev-list", "--parents", "-n", "1", commit).split()[1:]
    return parents[0] if parents else None


def diff_lines(a: str, b: str, paths: list[str]) -> list[str]:
    return git("diff", "-U0", a, b, "--", *paths).splitlines() if paths else []


def markers(lines: list[str]) -> tuple[int, int, int]:
    added = [line for line in lines if line.startswith("+") and not line.startswith("+++")]
    return (sum(bool(ADDED_TEST.match(line)) for line in added),
            sum(bool(INTENT.search(line)) for line in added),
            sum(bool(CHARACTERISATION.search(line)) for line in added))


# --- report: the pre-push gate -------------------------------------------------

def report(sha: str, base: str | None) -> int:
    commits = (git("rev-list", "--reverse", f"{base}..{sha}").split() if base else [sha])
    flagged = []
    tests = intent = characterisation = 0
    for commit in commits:
        parent = parent_of(commit)
        if parent is None:
            continue
        changed = [p for p in git("diff", "--name-only", parent, commit).splitlines() if p]
        test_files = [p for p in changed if is_test(p)]
        source_files = [p for p in changed if is_source(p)]
        lines = diff_lines(parent, commit, test_files)
        t, i, c = markers(lines)
        tests, intent, characterisation = tests + t, intent + i, characterisation + c
        edited = [line for line in lines if line.startswith("-") and not line.startswith("---")
                  and ASSERTION.search(line)]
        if edited and source_files:
            subject = git("log", "-1", "--format=%s", commit).strip()
            flagged.append((commit[:7], subject, len(edited), source_files))

    print(f"test-provenance (report only): {len(commits)} commit(s), {len(flagged)} flagged. "
          f"Tests added: {tests}; markers: {intent} Intent, {characterisation} Characterisation.")
    for short, subject, count, sources in flagged:
        shown = ", ".join(sources[:4]) + (" ..." if len(sources) > 4 else "")
        print(f"  {short} {subject[:70]}: {count} assertion line(s) edited beside {shown}")
    if flagged:
        print("  An edited assertion beside a code change is the shape of changing a test to fit "
              "the code. Check each is deliberate. This never blocks the push.")
    return 0


# --- classify: on demand -------------------------------------------------------

RUNNER = r"""
import json, sys, unittest
start, pattern = sys.argv[1], sys.argv[2]
outcome = {}
class R(unittest.TextTestResult):
    def addSuccess(self, t): super().addSuccess(t); outcome[t.id()] = "pass"
    def addFailure(self, t, e): super().addFailure(t, e); outcome[t.id()] = "fail"
    def addError(self, t, e): super().addError(t, e); outcome[t.id()] = "error"
    def addSkip(self, t, r): super().addSkip(t, r); outcome[t.id()] = "skip"
suite = unittest.defaultTestLoader.discover(start, pattern=pattern)
unittest.TextTestRunner(resultclass=R, stream=open(__import__("os").devnull, "w")).run(suite)
print("PROVENANCE-JSON " + json.dumps(outcome))
"""


def added_test_names(lines: list[str]) -> list[str]:
    return [m.group(1) for line in lines if (m := ADDED_TEST.match(line)) and m.group(1)]


def classify(base: str, head: str) -> int:
    changed = [p for p in git("diff", "--name-only", "--diff-filter=AM", base, head).splitlines()
               if p.endswith(".py") and is_test(p)]
    if not changed:
        print("classify: no Python test files added or changed in this range.")
        return 0
    names = {path: added_test_names(diff_lines(base, head, [path])) for path in changed}
    _, intent, characterisation = markers(diff_lines(base, head, changed))
    test_dirs = sorted({str(Path(p).parent.as_posix()) for p in changed})

    tree = Path(tempfile.mkdtemp())
    rows = []
    try:
        git("worktree", "add", "--quiet", "--detach", str(tree), base)
        # The range's tests, against the source as it was before the range.
        for d in test_dirs:
            prefix = "" if d == "." else d + "/"
            for p in git("ls-tree", "-r", "--name-only", head, "--", d if d != "." else ".").splitlines():
                if p.startswith(prefix) and (d != "." or "/" not in p):
                    target = tree / p
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(subprocess.run(["git", "show", f"{head}:{p}"],
                                                      capture_output=True, env=env(),
                                                      timeout=TIMEOUT).stdout)
        for path, tests in names.items():
            if not tests:
                continue
            start = tree / Path(path).parent
            result = subprocess.run([sys.executable, "-c", RUNNER, str(start), Path(path).name],
                                    cwd=start, capture_output=True, timeout=TIMEOUT, env=env())
            text = result.stdout.decode("utf-8", errors="replace")
            line = next((x for x in text.splitlines() if x.startswith("PROVENANCE-JSON ")), None)
            outcome = json.loads(line.split(" ", 1)[1]) if line else {}
            for name in tests:
                hits = [v for k, v in outcome.items() if k.endswith("." + name)]
                state = hits[0] if hits else "not run"
                verdict = {"pass": "characterisation", "fail": "written ahead",
                           "error": "written ahead"}.get(state, "unknown")
                rows.append((path, name, state, verdict))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], capture_output=True,
                       env=env(), timeout=TIMEOUT)
        shutil.rmtree(tree, ignore_errors=True)

    ahead = sum(r[3] == "written ahead" for r in rows)
    char = sum(r[3] == "characterisation" for r in rows)
    unknown = sum(r[3] == "unknown" for r in rows)
    print(f"classify {base[:7]}..{head[:7]}: {len(rows)} new test(s) - {ahead} written ahead, "
          f"{char} characterisation, {unknown} unknown. "
          f"Markers: {intent} Intent, {characterisation} Characterisation.")
    for path, name, state, verdict in rows:
        print(f"  {verdict:<16} {path}::{name}  (at base: {state})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test provenance: report and classify.")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="the pre-push gate; never blocks")
    rep.add_argument("--sha", required=True)
    rep.add_argument("--base", default="")
    cls = sub.add_parser("classify", help="run a range's new tests against its base")
    cls.add_argument("--range", required=True, help="BASE..HEAD")
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            sha = resolve(args.sha)
            if sha is None:
                raise ProvenanceError(f"--sha {args.sha!r} is not a commit here")
            return report(sha, resolve(args.base))
        base_rev, _, head_rev = args.range.partition("..")
        base, head = resolve(base_rev), resolve(head_rev or "HEAD")
        if base is None or head is None:
            raise ProvenanceError(f"--range {args.range!r} does not name two commits here")
        return classify(base, head)
    except (ProvenanceError, subprocess.TimeoutExpired) as exc:
        print(f"REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
