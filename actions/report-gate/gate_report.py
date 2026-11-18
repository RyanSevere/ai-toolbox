#!/usr/bin/env python3
################################################################################
# File: gate_report.py
# Path: {PROJECT_ROOT}/actions/report-gate/gate_report.py
# Created by: Ryan Severe
# Created: 2026-11-18
# Last Updated: 2026-11-18
# Description: Validates a pre-push gate report against the commit that was
#              actually pushed. This is the checking half of the gate report
#              and knows nothing about where the report came from - fetching it
#              is a separate concern so the transport can change without this
#              changing. Absence and malformity are failures, never passes. A
#              skipped required gate is a finding unless the profile declared an
#              exemption for it, as a report-skip= line in gate-config, on a ref
#              that fully matches the line's pattern.
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

PASS = "pass"
# Rendered from the profile's lock, and the same list the pre-push hook runs.
DEFAULT_GATES_FILE = ".githooks/gates/enabled"
# Rendered from the profile: the deploy branch, and one report-skip= line per exempt ref.
DEFAULT_GATE_CONFIG_FILE = ".githooks/gate-config"

# An exemption: a pattern that must match the whole ref, and the gates it lets a report skip.
SkipRule = tuple[str, list[str]]


class ReportError(Exception):
    """A report that cannot be read at all. Distinct from one that fails validation."""


def load_required_gates(path: Path) -> list[str]:
    """The gates that must appear and pass, read from the repository, never from the report.

    Taking this list from the report would let a report pass by declaring fewer gates
    than exist, which is the report grading its own completeness.
    """
    if not path.exists():
        raise ReportError(f"{path} does not exist, so no gate list is declared")

    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)

    if not names:
        raise ReportError(f"{path} declares no gates")
    return names


def load_gate_config(path: Path) -> tuple[list[SkipRule], str]:
    """The exemptions and the deploy branch the profile rendered into gate-config.

    A missing or unreadable file refuses: reading it as 'nothing declared' would be a
    safe-looking guess, but a gate-config that failed to arrive is not the same as one
    that declares no exemption. A malformed line refuses too, never widening what passes.
    An exemption with no deploy branch refuses, because the rule that the deploy branch is
    never exempt could not then be applied.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"gate-config {path} cannot be read ({exc.strerror or exc}), "
                          "so the declared exemptions are unknown") from exc

    skips: list[SkipRule] = []
    deploy = ""
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "deploy-branch":
            deploy = value.strip()
        elif key == "report-skip":
            where = f"gate-config {path} line {number}"
            pattern, _, listed = value.strip().rpartition(" ")
            gates = listed.split(",")
            if not pattern or not listed or not all(gates):
                raise ReportError(f"{where}: report-skip= wants '<pattern> <gate>[,<gate>...]'")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ReportError(f"{where}: pattern {pattern!r} is not a regular expression: "
                                  f"{exc}") from exc
            skips.append((pattern, gates))
    if skips and not deploy:
        raise ReportError(f"gate-config {path} declares exemptions but no deploy-branch")
    return skips, deploy


RERUN_GATE = re.compile(r"[a-z0-9][a-z0-9-]*")


def load_rerun_gates(path: Path) -> list[str]:
    """The gates the profile lists for CI to run again: one report-rerun= line each, in order,
    a repeat counting once. A malformed name refuses, since it names a file the re-run runs."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"gate-config {path} cannot be read ({exc.strerror or exc}), "
                          "so the gates to re-run are unknown") from exc
    gates: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        key, sep, value = raw.strip().partition("=")
        if not sep or key != "report-rerun":
            continue
        if not RERUN_GATE.fullmatch(value.strip()):
            raise ReportError(f"gate-config {path} line {number}: report-rerun= wants one gate name")
        if value.strip() not in gates:
            gates.append(value.strip())
    return gates


def load_rerun_verdicts(path: Path | None, listed: list[str]) -> dict[str, str]:
    """What the CI re-run found for each listed gate: 'pass', 'fail', or 'missing' when the
    verdict file has no line for it, does not exist, or was not given. Missing is never a pass."""
    verdicts = {gate: "missing" for gate in listed}
    if path is None:
        return verdicts
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return verdicts
    for raw in text.splitlines():
        name, _, status = raw.strip().partition(" ")
        if name in verdicts and status in (PASS, "fail"):
            verdicts[name] = status
    return verdicts


def parse_report(text: str) -> dict:
    try:
        report = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportError(f"report is not valid JSON: {exc}") from exc
    if not isinstance(report, dict):
        raise ReportError(f"report is a {type(report).__name__}, expected an object")
    return report


def exempt_gates(ref: str, skip_allowed: list[SkipRule], deploy_branch: str) -> set[str]:
    """The gates a report may skip on `ref`: those of every rule whose pattern matches all of
    it. None on the deploy branch, whatever a pattern says, and none without a ref. Entry
    order and repeats cannot change the answer, since it is a union."""
    if not ref or (deploy_branch and ref in (deploy_branch, f"refs/heads/{deploy_branch}")):
        return set()
    allowed: set[str] = set()
    for pattern, gates in skip_allowed:
        if re.fullmatch(pattern, ref):
            allowed.update(gates)
    return allowed


def validate(
    report: dict,
    expected_sha: str,
    required: list[str],
    ref: str = "",
    skip_allowed: list[SkipRule] | None = None,
    deploy_branch: str = "",
    rerun: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Returns findings that fail the gate, and notes that do not.

    `rerun` maps each gate CI ran again to 'pass', 'fail' or 'missing'. A fail is a finding
    whatever the report says, and a pass changes nothing: it never stands in for a report
    entry. With none, the check is exactly what it is without a re-run.

    `ref` is the pull request's base ref, or the pushed ref. A required gate the report
    skipped passes as a note only when `skip_allowed` has a rule for that gate whose pattern
    fully matches `ref`. With nothing declared, or no ref, or on `deploy_branch`, every
    skipped required gate is a finding.
    """
    findings: list[str] = []
    notes: list[str] = []

    commit = report.get("commit")
    if not commit:
        findings.append("report names no commit, so it cannot be bound to what was pushed")
    elif commit != expected_sha:
        findings.append(f"report is for commit {commit}, but {expected_sha} was pushed")

    gates = report.get("gates")
    if not isinstance(gates, dict):
        findings.append(f"report has no gates object (found {type(gates).__name__})")
        return findings, notes

    lists: dict[str, list[str]] = {}
    for key in ("skipped", "flag_changes"):
        value = report.get(key, [])
        if isinstance(value, list):
            lists[key] = [str(item) for item in value]
        else:
            findings.append(f"report {key} is a {type(value).__name__}, expected a list")
            lists[key] = []
    allowed = exempt_gates(ref, skip_allowed or [], deploy_branch)
    # A report lists a skipped gate in `skipped` and may leave it out of `gates`, so an
    # exempt gate is not also an absent one.
    exempt = allowed & set(lists["skipped"])

    for name in required:
        entry = gates.get(name)
        if entry is None:
            if name not in exempt:
                findings.append(
                    f"{name}: required by {DEFAULT_GATES_FILE}, absent from the report")
            continue
        status = entry.get("status") if isinstance(entry, dict) else entry
        if status != PASS:
            detail = entry.get("detail", "") if isinstance(entry, dict) else ""
            findings.append(f"{name}: status {status!r}{' - ' + detail if detail else ''}")

    # Not a failure. An undeclared gate is drift between the hook and the gate list,
    # which is worth seeing without blocking a push that ran more checks than required.
    for name in sorted(set(gates) - set(required)):
        notes.append(f"{name}: in the report, not required by {DEFAULT_GATES_FILE}")

    # The hook skips only gates the list leaves out, so a required gate named here is a
    # report that disagrees with the list it was run against.
    for name in sorted(set(lists["skipped"]) & set(required)):
        if name in exempt:
            notes.append(f"{name}: skipped on ref {ref}, which the profile declares exempt for it")
            continue
        findings.append(f"{name}: required by {DEFAULT_GATES_FILE}, but the report skipped it")
    for name in sorted(set(lists["skipped"]) - set(required)):
        notes.append(f"{name}: skipped, off in profile.lock")
    notes.extend(f"flag changed: {change}" for change in lists["flag_changes"])

    for name, verdict in sorted((rerun or {}).items()):
        entry = gates.get(name)
        reported = entry.get("status") if isinstance(entry, dict) else entry
        if verdict == "fail" and reported == PASS:
            findings.append(f"{name}: the report and the commit disagree - the report says it "
                            "passed, but CI ran the gate again from the vendored core and it failed")
        elif verdict == "fail":
            findings.append(f"{name}: failed when CI ran it again from the vendored core")
        elif verdict != PASS:
            findings.append(f"{name}: no CI re-run verdict, so the report's word is not confirmed")

    return findings, notes


# A web-UI merge commit is created on the server, so no hook ever ran on it and it has no
# report. It is accepted only when it adds nothing of its own.
MERGE_COVER_DEPTH_CAP = 20
GIT_TIMEOUT = 120
REPORT_REF_PATTERN = "refs/tags/gate-report/*/{sha}"


def merge_cover(
    sha: str,
    required: list[str],
    parents,
    report_for,
    clean_merge_tree,
    tree_of,
    accepted,
) -> tuple[bool, str]:
    """Decide whether a commit is covered, from injected lookups.

    A commit the branch already held before this push is covered outright, whatever its
    report: that history was judged when it landed, and walking it again is what ran the
    chain of web-UI merges into the depth cap. A commit with its own report is judged by
    that report alone. One without passes only if it has exactly two parents, each
    covered (by a passing report or, recursively, by this same rule), and its tree equals
    the clean merge of those parents. No exemption applies here: a report is judged with
    no ref, so a skipped required gate in a covered parent stays a finding.
    Returns (covered, reason or what covered it).
    """
    memo: dict[str, tuple[bool, str]] = {}

    def check(commit: str, depth: int) -> tuple[bool, str]:
        if commit in memo:
            return memo[commit]
        if depth > MERGE_COVER_DEPTH_CAP:
            # Not memoised: the same commit reached nearer the top could still pass.
            return False, f"{commit}: parent chain exceeds the depth cap of {MERGE_COVER_DEPTH_CAP}"

        if accepted(commit):
            result = (True, f"{commit}: already on the branch before this push")
            memo[commit] = result
            return result

        report = report_for(commit)
        if report is not None:
            findings, _ = validate(report, commit, required)
            if findings:
                result = (False, f"{commit}: its report fails: " + "; ".join(findings))
            else:
                result = (True, f"{commit}: has a passing report")
            memo[commit] = result
            return result

        found = list(parents(commit))
        if len(found) != 2:
            result = (
                False,
                f"{commit}: no report, and {len(found)} parent(s) - only a two-parent merge can be covered",
            )
            memo[commit] = result
            return result

        verdicts = [check(parent, depth + 1) for parent in found]
        uncovered = [why for ok, why in verdicts if not ok]
        if uncovered:
            result = (False, f"{commit}: a parent is not covered ({'; '.join(uncovered)})")
            if not any("depth cap" in why for why in uncovered):
                memo[commit] = result
            return result

        merged = clean_merge_tree(found[0], found[1])
        if merged is None:
            result = (False, f"{commit}: its parents {found[0]} and {found[1]} do not merge cleanly")
        elif merged != tree_of(commit):
            result = (
                False,
                f"{commit}: tree {tree_of(commit)} differs from the merge of its parents ({merged}), "
                "so it carries changes of its own",
            )
        else:
            result = (
                True,
                f"{commit}: clean merge of {found[0]} and {found[1]}, tree {merged} matches",
            )
        memo[commit] = result
        return result

    return check(sha, 0)


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        check=False,
    )


def git_parents(sha: str, cwd: Path | None = None) -> list[str]:
    out = _git(["rev-list", "--parents", "-n", "1", sha], cwd)
    if out.returncode != 0:
        return []
    return out.stdout.split()[1:]


def git_tree_of(sha: str, cwd: Path | None = None) -> str:
    out = _git(["rev-parse", f"{sha}^{{tree}}"], cwd)
    return out.stdout.strip() if out.returncode == 0 else ""


def git_clean_merge_tree(first: str, second: str, cwd: Path | None = None) -> str | None:
    """The tree of a conflict-free merge, or None. Needs git 2.38 for --write-tree."""
    out = _git(["merge-tree", "--write-tree", first, second], cwd)
    if out.returncode != 0:
        return None
    lines = out.stdout.splitlines()
    return lines[0].strip() if lines else None


def git_is_accepted(before: str, cwd: Path | None = None):
    """A lookup for commits the branch already held at `before`, its tip before this push.

    Nothing is accepted for a new branch (empty or all-zero `before`). Any git outcome
    other than a clean ancestor answer is False, so an error never widens what passes.
    """
    if not before or set(before) == {"0"}:
        return lambda commit: False

    def accepted(commit: str) -> bool:
        return _git(["merge-base", "--is-ancestor", commit, before], cwd).returncode == 0

    return accepted


def git_report_for(sha: str, cwd: Path | None = None) -> dict | None:
    """The report published for a commit: None if there is none, {} if it is unreadable.

    {} fails validation, so a malformed report is a refusal and does not fall through to
    the merge rule. A commit that has a report is judged by it alone.
    """
    listed = _git(["ls-remote", "origin", REPORT_REF_PATTERN.format(sha=sha)], cwd)
    refs = [line.split()[1] for line in listed.stdout.splitlines() if len(line.split()) == 2]
    if listed.returncode != 0 or not refs:
        return None
    local = f"refs/gate-report-check-cover/{sha}"
    if _git(["fetch", "--quiet", "origin", f"+{refs[-1]}:{local}"], cwd).returncode != 0:
        return {}
    shown = _git(["show", f"{local}:report.json"], cwd)
    if shown.returncode != 0:
        return {}
    try:
        return parse_report(shown.stdout)
    except ReportError:
        return {}


def run_merge_cover(sha: str, gates: Path, before: str = "") -> int:
    try:
        required = load_required_gates(gates)
    except ReportError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    # The checkout is shallow, so the commits being walked are not there until fetched.
    fetched = _git(["fetch", "--quiet", f"--depth={MERGE_COVER_DEPTH_CAP + 2}", "origin", sha])
    if fetched.returncode != 0:
        print(f"Merge cover: could not fetch {sha}: {fetched.stderr.strip()}", file=sys.stderr)
        return 1

    accepted = git_is_accepted("")
    if before and set(before) != {"0"}:
        prior = _git(["fetch", "--quiet", f"--depth={MERGE_COVER_DEPTH_CAP + 2}", "origin", before])
        if prior.returncode == 0:
            accepted = git_is_accepted(before)
        else:
            print(f"Merge cover: could not fetch {before}: {prior.stderr.strip()}", file=sys.stderr)

    covered, why = merge_cover(
        sha, required, git_parents, git_report_for, git_clean_merge_tree, git_tree_of, accepted
    )
    if not covered:
        print(f"Merge cover refused: {why}", file=sys.stderr)
        return 1
    print(f"Covered without a report of its own: {why}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a pre-push gate report.")
    parser.add_argument("--report", type=Path, help="path to the fetched report")
    parser.add_argument("--sha", required=True, help="the commit that was pushed")
    parser.add_argument("--gates", type=Path, default=Path(DEFAULT_GATES_FILE))
    parser.add_argument(
        "--gate-config",
        type=Path,
        default=Path(DEFAULT_GATE_CONFIG_FILE),
        help="the rendered gate-config, which declares the refs a gate may be skipped on",
    )
    parser.add_argument(
        "--merge-cover",
        action="store_true",
        help="no report exists for --sha: accept it only as a clean merge of covered parents",
    )
    parser.add_argument(
        "--before",
        default="",
        help="the branch tip before this push; history it contains counts as covered",
    )
    parser.add_argument(
        "--ref",
        default="",
        help="the pull request base ref, or the pushed ref; a declared exemption may skip a gate",
    )
    parser.add_argument(
        "--rerun",
        type=Path,
        help="the verdicts rerun.sh wrote, one '<gate> pass|fail' line each; read only for "
             "the gates gate-config lists as report-rerun=",
    )
    args = parser.parse_args()

    if args.merge_cover:
        return run_merge_cover(args.sha, args.gates, args.before)
    if args.report is None:
        parser.error("--report is required unless --merge-cover is given")

    try:
        required = load_required_gates(args.gates)
        skip_allowed, deploy_branch = load_gate_config(args.gate_config)
        listed = load_rerun_gates(args.gate_config)
        verdicts = load_rerun_verdicts(args.rerun, listed) if listed else None
        if not args.report.exists():
            raise ReportError(
                f"no report at {args.report}. A skipped hook writes no report, "
                "so this is indistinguishable from a failure and is treated as one."
            )
        report = parse_report(args.report.read_text(encoding="utf-8"))
    except ReportError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    findings, notes = validate(report, args.sha, required, args.ref, skip_allowed, deploy_branch,
                               verdicts)

    print(f"{len(required)} gate(s) required for {args.sha}")
    for note in notes:
        print(f"  note  {note}")

    if findings:
        print(f"REFUSED: {len(findings)} finding(s)", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1

    print("Every required gate is present, passing, and bound to this commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
