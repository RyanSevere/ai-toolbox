#!/usr/bin/env python3
################################################################################
# File: lint_baseline.py
# Path: {PROJECT_ROOT}/githooks/lib/lint_baseline.py
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-23
# Description: Runs a linter - ShellCheck, ruff or eslint - on the files a push
#              changes and fails only on findings its committed baseline does
#              not already hold, so existing debt does not block every push but
#              new debt does. Lints the commit being pushed, never the working
#              tree, which on Windows carries CRLF the commit does not. A
#              finding's key is file, rule and the offending line's text, so
#              moving code does not make an old finding new. A baseline is
#              written by --write and only ever shrinks.
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
from collections import Counter
from pathlib import Path

GATE_CONFIG = ".githooks/gate-config"
SHEBANG = re.compile(rb"^#!\s*\S*(?:/|\s)(?:env\s+)?(?:ba)?sh\b")
ZERO = re.compile(r"^0+$")
TIMEOUT = 600


class LintError(Exception):
    """The check could not be carried out. Never a pass."""


def git(*args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], capture_output=True, timeout=TIMEOUT)
    if result.returncode != 0:
        raise LintError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def blob(sha: str, path: str) -> bytes | None:
    result = subprocess.run(["git", "show", f"{sha}:{path}"], capture_output=True, timeout=TIMEOUT)
    return result.stdout if result.returncode == 0 else None


def blobs(sha: str, paths: list[str]) -> dict[str, bytes | None]:
    """Every path's bytes at sha, read through one `git cat-file --batch`. A missing object
    maps to None, as blob() returns it. Raises LintError when cat-file itself fails: never an
    empty map for a failure."""
    wanted = list(dict.fromkeys(paths))
    # A newline in a name cannot be asked of --batch, which reads one name per line.
    batched = [p for p in wanted if "\n" not in p]
    found: dict[str, bytes | None] = {p: blob(sha, p) for p in wanted if "\n" in p}
    if batched:
        request = "".join(f"{sha}:{p}\n" for p in batched).encode("utf-8")
        result = subprocess.run(["git", "cat-file", "--batch"], input=request,
                                capture_output=True, timeout=TIMEOUT)
        if result.returncode != 0:
            raise LintError("git cat-file --batch failed: "
                            f"{result.stderr.decode(errors='replace').strip()}")
        out, pos = result.stdout, 0
        for path in batched:
            end = out.find(b"\n", pos)
            if end < 0:
                raise LintError("git cat-file --batch ended before every path was answered")
            header = out[pos:end]
            pos = end + 1
            if header.endswith(b" missing"):
                found[path] = None
                continue
            parts = header.split(b" ")
            if len(parts) != 3 or not parts[2].isdigit():
                raise LintError(f"git cat-file --batch answered {header!r}")
            size = int(parts[2])
            if len(out) < pos + size + 1:
                raise LintError("git cat-file --batch ended inside an object")
            found[path] = out[pos:pos + size]
            pos += size + 1
    return {p: found[p] for p in wanted}


def baseline_dir(sha: str) -> str:
    """<config-dir>/lint-baseline, read from the commit's gate-config like everything else
    here. A missing key refuses: guessing the folder would read no baseline as zero debt."""
    text = (blob(sha, GATE_CONFIG) or b"").decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("config-dir="):
            value = line[len("config-dir="):].strip()
            if value:
                return f"{value}/lint-baseline"
    raise LintError(f"{GATE_CONFIG} at {sha[:12]} names no config-dir, so there is no telling "
                    "where the baseline lives. Re-render this repo from its profile")


def deploy_branch(sha: str) -> str:
    """The deploy branch, read from the commit's gate-config as baseline_dir reads config-dir.
    A missing key refuses: guessing a branch would narrow a push against the wrong one."""
    text = (blob(sha, GATE_CONFIG) or b"").decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("deploy-branch="):
            value = line[len("deploy-branch="):].strip()
            if (re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", value) and ".." not in value
                    and not value.startswith("-")):
                return value
    raise LintError(f"{GATE_CONFIG} at {sha[:12]} names no usable deploy-branch, so there is no "
                    "telling what a new branch is compared with. Re-render this repo from its "
                    "profile")


def tracked(sha: str) -> list[str]:
    return [p for p in str(git("ls-tree", "-r", "--name-only", sha)).splitlines() if p]


# --- tools ---------------------------------------------------------------------
# Each tool has a selector, built from the commit, saying which files it owns;
# and a runner, given those files extracted under root, returning findings as
# (path, code, line number).

# The render stamp, as githooks/lib/stamp.sh reads it: within the first 40 lines, either form.
STAMP = re.compile(rb"generated from [^ @]+(@[0-9a-f]{7}| - edit the source)")
STAMP_LINES = 40
VENDORED_CORE = "core"


def is_stamped(content: bytes) -> bool:
    """True for a rendered file: the repository does not own it, its source does."""
    head = b"\n".join(content.split(b"\n", STAMP_LINES)[:STAMP_LINES])
    return bool(STAMP.search(head))


def vendored_prefix(sha: str) -> str | None:
    """'core/' where this commit carries a vendored copy of the core, else None."""
    return f"{VENDORED_CORE}/" if blob(sha, f"{VENDORED_CORE}/VENDORED") is not None else None


def owned(sha: str, selector):
    """Wraps a tool's own selection so every linter skips what the repository does not own:
    the vendored core, and any rendered file. Linting them blocks a push on code nobody
    here can change."""
    prefix = vendored_prefix(sha)
    wanted = selector(sha)

    def owns(path: str, content: bytes) -> bool:
        if prefix and path.startswith(prefix):
            return False
        return wanted(path, content) and not is_stamped(content)
    return owns


def is_shell(path: str, content: bytes) -> bool:
    return path.endswith(".sh") or bool(SHEBANG.match(content.split(b"\n", 1)[0]))


def run_shellcheck(root: Path, files: list[str], sha: str) -> list[tuple[str, str, int]]:
    exe = shutil.which("shellcheck")
    if not exe:
        raise LintError("shellcheck is not installed, so these scripts cannot be checked. "
                        "Install it (winget install koalaman.shellcheck, apt install shellcheck).")
    result = subprocess.run([exe, "-S", "warning", "-f", "json1", *files], cwd=root,
                            capture_output=True, timeout=TIMEOUT)
    # 0 clean, 1 findings; anything else means it did not run properly.
    if result.returncode not in (0, 1):
        raise LintError(f"shellcheck exited {result.returncode}: "
                        f"{result.stderr.decode(errors='replace').strip()[:300]}")
    report = json.loads(result.stdout or b'{"comments": []}')
    return [(c["file"].replace("\\", "/"), f"SC{c['code']}", int(c["line"]))
            for c in report.get("comments", [])]


RUFF_CONFIGS = ("ruff.toml", ".ruff.toml", "pyproject.toml")


def run_ruff(root: Path, files: list[str], sha: str) -> list[tuple[str, str, int]]:
    exe = shutil.which("ruff")
    if not exe:
        raise LintError("ruff is not installed, so this Python cannot be checked. "
                        "Install it (pip install ruff).")
    # ruff finds the nearest config above each file, so every committed one goes in.
    # A pyproject.toml counts only with a ruff section; ruff ignores it otherwise.
    configs = [p for p in tracked(sha) if p.rsplit("/", 1)[-1] in RUFF_CONFIGS
               and (not p.endswith("pyproject.toml")
                    or re.search(rb"(?m)^\[tool\.ruff", blob(sha, p) or b""))]
    for path in configs:
        target = root / path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob(sha, path) or b"")
    # With no project config, a user-level one would make machines disagree.
    isolated = [] if configs else ["--isolated"]
    result = subprocess.run([exe, "check", "--no-cache", "--force-exclude", "--output-format",
                             "json", *isolated, *files], cwd=root, capture_output=True,
                            timeout=TIMEOUT)
    if result.returncode not in (0, 1):
        raise LintError(f"ruff exited {result.returncode}: "
                        f"{result.stderr.decode(errors='replace').strip()[:300]}")
    base = root.resolve()
    return [(Path(c["filename"]).resolve().relative_to(base).as_posix(),
             c.get("code") or "invalid-syntax", int(c["location"]["row"]))
            for c in json.loads(result.stdout or b"[]")]


ESLINT_CONFIG = re.compile(r"(^|/)eslint\.config\.(js|mjs|cjs|ts)$")
ESLINT_SOURCE = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")

# Runs inside the package, so its config resolves the plugins in its own
# node_modules, and lints the committed text handed over on stdin.
ESLINT_RUNNER = r"""
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const { pkg, files } = JSON.parse(Buffer.concat(chunks).toString('utf8'));
let mod;
try {
  mod = await import(pathToFileURL(createRequire(pkg + '/package.json').resolve('eslint')).href);
} catch (e) {
  console.log(JSON.stringify({ error: 'eslint is not installed in ' + pkg + '. Run npm ci there.' }));
  process.exit(0);
}
const ESLint = mod.ESLint ?? mod.default?.ESLint;
const eslint = new ESLint({ cwd: pkg });
const findings = [];
for (const f of files) {
  if (await eslint.isPathIgnored(f.abs)) continue;
  if (!(await eslint.calculateConfigForFile(f.abs))) continue;
  const [r] = await eslint.lintText(f.text, { filePath: f.abs });
  for (const m of r ? r.messages : []) {
    if (!m.ruleId && !m.fatal) continue;
    findings.push([f.path, m.ruleId || 'parse-error', m.line || 0]);
  }
}
console.log(JSON.stringify({ findings }));
"""


def eslint_packages(sha: str) -> list[str]:
    """Directories holding a committed eslint config; '' is the repo root."""
    return sorted({p.rsplit("/", 1)[0] if "/" in p else "" for p in tracked(sha)
                   if ESLINT_CONFIG.search(p) and "/node_modules/" not in f"/{p}"})


def package_of(path: str, packages: list[str]) -> str | None:
    owners = [p for p in packages if p == "" or path.startswith(p + "/")]
    return max(owners, key=len) if owners else None


def select_eslint(sha: str):
    packages = eslint_packages(sha)

    def owns(path: str, content: bytes) -> bool:
        return (path.endswith(ESLINT_SOURCE) and "/node_modules/" not in f"/{path}"
                and package_of(path, packages) is not None)
    return owns


def run_eslint(root: Path, files: list[str], sha: str) -> list[tuple[str, str, int]]:
    node = shutil.which("node")
    if not node:
        raise LintError("node is not installed, so eslint cannot run.")
    top = Path(str(git("rev-parse", "--show-toplevel")).strip())
    packages = eslint_packages(sha)
    by_package: dict[str, list[str]] = {}
    for path in files:
        by_package.setdefault(package_of(path, packages) or "", []).append(path)
    findings: list[tuple[str, str, int]] = []
    for pkg, paths in sorted(by_package.items()):
        pkg_dir = top / pkg
        # The config runs from the working tree; it must be the one being pushed.
        for name in sorted(p for p in tracked(sha) if ESLINT_CONFIG.search(p)
                           and (p.rsplit("/", 1)[0] if "/" in p else "") == pkg):
            on_disk = top / name
            if not on_disk.exists() or on_disk.read_bytes().replace(b"\r\n", b"\n") \
                    != (blob(sha, name) or b"").replace(b"\r\n", b"\n"):
                raise LintError(f"{name} differs from the commit being pushed. "
                                "Commit or stash it so the config checked is the one pushed.")
        payload = {"pkg": str(pkg_dir), "files": [
            {"path": p, "abs": str(top / p),
             "text": (root / p).read_text(encoding="utf-8", errors="replace")} for p in paths]}
        result = subprocess.run([node, "--input-type=module", "-e", ESLINT_RUNNER],
                                input=json.dumps(payload).encode("utf-8"), cwd=pkg_dir,
                                capture_output=True, timeout=TIMEOUT)
        if result.returncode != 0:
            raise LintError(f"eslint in {pkg or '.'} exited {result.returncode}: "
                            f"{result.stderr.decode(errors='replace').strip()[:300]}")
        try:
            report = json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise LintError(f"eslint in {pkg or '.'} gave no readable report: {exc}") from exc
        if "error" in report:
            raise LintError(report["error"])
        findings += [(p, code, int(line)) for p, code, line in report["findings"]]
    return findings


TOOLS = {
    "eslint": (select_eslint, run_eslint),
    "ruff": (lambda sha: lambda path, content: path.endswith(".py"), run_ruff),
    "shellcheck": (lambda sha: is_shell, run_shellcheck),
}


# --- baseline ------------------------------------------------------------------

def key(path: str, code: str, text: str) -> str:
    return f"{path}\t{code}\t{text.strip()}"


def keyed(root: Path, findings: list[tuple[str, str, int]]) -> Counter:
    lines: dict[str, list[str]] = {}
    out: Counter = Counter()
    for path, code, number in findings:
        if path not in lines:
            lines[path] = (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
        text = lines[path][number - 1] if 0 < number <= len(lines[path]) else ""
        out[key(path, code, text)] += 1
    return out


def load_baseline(sha: str, tool: str) -> Counter:
    path = f"{baseline_dir(sha)}/{tool}.json"
    raw = blob(sha, path)
    if raw is None:
        return Counter()
    try:
        return Counter({k: int(v) for k, v in json.loads(raw).items()})
    except (ValueError, AttributeError, TypeError) as exc:
        raise LintError(f"{path} is not a valid baseline: {exc}") from exc


# --- main ----------------------------------------------------------------------

def candidate_paths(sha: str, base: str | None, everything: bool) -> list[str]:
    """The push's changed files; every file when there is no usable base."""
    if everything or base is None:
        return tracked(sha)
    return [p for p in git("diff", "--name-only", "--diff-filter=ACMR", base, sha).splitlines() if p]


def resolve(rev: str) -> str | None:
    """A full commit id, or None. Validated before it reaches any git command."""
    if not rev or ZERO.match(rev) or not re.fullmatch(r"[\w./^~@{}-]{1,100}", rev):
        return None
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                            capture_output=True, timeout=TIMEOUT)
    out = result.stdout.decode().strip()
    return out if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", out) else None


def choose_base(sha: str, base_arg: str, remote: str) -> tuple[str | None, str]:
    """The base a push is linted against, and the range line saying so. Chosen as the tests
    gate chooses its range: the remote sha for the deploy branch and for an existing branch,
    the merge-base with the remote's deploy branch for a new one, nothing when there is none."""
    pushed = os.environ.get("PUSH_REMOTE_REF", "")
    given = resolve(base_arg)
    if not pushed:
        if given:
            return given, "range: as pushed (no pushed ref given)"
        return None, "range: none (no pushed ref and no usable base; every file is linted)"
    deploy = deploy_branch(sha)
    if pushed == f"refs/heads/{deploy}":
        if given:
            return given, "range: as pushed (deploy branch)"
        return None, "range: none (deploy branch with no usable base; every file is linted)"
    if given:
        return given, "range: as pushed (existing branch)"
    try:
        result = subprocess.run(["git", "merge-base", sha, f"refs/remotes/{remote}/{deploy}"],
                                capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        result = None
    out = result.stdout.decode().strip() if result is not None and result.returncode == 0 else ""
    if re.fullmatch(r"[0-9a-f]{40,64}", out):
        return out, f"range: merge-base with {remote}/{deploy} (new branch)"
    return None, (f"range: none (new branch with no merge-base with {remote}/{deploy}; "
                  "every file is linted)")


def push_base(sha: str, base_arg: str, remote: str) -> str | None:
    """The commit a push is linted against, or None to lint every file."""
    return choose_base(sha, base_arg, remote)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint changed files against a committed baseline.")
    parser.add_argument("--tool", required=True, choices=sorted(TOOLS))
    parser.add_argument("--sha", required=True, help="the commit being pushed")
    parser.add_argument("--base", default="", help="the commit already on the remote")
    parser.add_argument("--remote", default="origin",
                        help="the remote being pushed to, for a new branch's merge-base")
    parser.add_argument("--write", action="store_true",
                        help="write <config-dir>/lint-baseline/<tool>.json from every file "
                             "at --sha. "
                             "Refuses to add to an existing baseline: it can only shrink.")
    args = parser.parse_args(argv)
    selector, runner = TOOLS[args.tool]

    try:
        sha = resolve(args.sha)
        if sha is None:
            raise LintError(f"--sha {args.sha!r} is not a commit here")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", args.remote):
            raise LintError(f"--remote {args.remote!r} is not a remote name")
        owns = owned(sha, selector)
        base, range_line = (None, "") if args.write else choose_base(sha, args.base, args.remote)
        if range_line:
            print(range_line)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            paths = candidate_paths(sha, base, args.write)
            contents = blobs(sha, paths)
            for path in paths:
                content = contents[path]
                if content is None or not owns(path, content):
                    continue
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                files.append(path)
            if not files:
                print(f"{args.tool}: no files of its kind in this push. Nothing to check.")
                return 0
            found = keyed(root, runner(root, files, sha))
    except LintError as exc:
        print(f"REFUSED: {exc}")
        return 1

    if args.write:
        # Written by a run, never by hand, and only shrinks.
        try:
            existing = load_baseline(sha, args.tool)
            folder = baseline_dir(sha)
        except LintError as exc:
            print(f"REFUSED: {exc}")
            return 1
        # An empty committed baseline counts: a repo at zero must stay at zero.
        committed = blob(sha, f"{folder}/{args.tool}.json") is not None
        if committed and (found - existing):
            grown = found - existing
            print(f"REFUSED: {sum(grown.values())} finding(s) are not in the committed baseline, "
                  "and a baseline only shrinks:")
            for entry in sorted(grown):
                path, code, text = entry.split("\t", 2)
                print(f"  {path}  {code}  {text}")
            print("Fix them, or suppress a deliberate one inline at the line, where a reviewer "
                  "sees it. Delete the baseline file first only to start one from scratch.")
            return 1
        target = Path(folder) / f"{args.tool}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(sorted(found.items())), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {target}: {sum(found.values())} finding(s) in {len(files)} file(s). Commit it.")
        return 0

    try:
        baseline = load_baseline(sha, args.tool)
    except LintError as exc:
        print(f"REFUSED: {exc}")
        return 1
    new = found - baseline
    known = sum(found.values()) - sum(new.values())
    if not new:
        print(f"{args.tool}: {len(files)} file(s) checked, {known} known finding(s), none new.")
        return 0
    print(f"{args.tool}: {sum(new.values())} new finding(s) in {len(files)} file(s) checked:")
    for entry in sorted(new):
        path, code, text = entry.split("\t", 2)
        print(f"  {path}  {code}  {text}")
    print("\nFix them, or if one is deliberate, suppress it inline at the line "
          "(# noqa: CODE, // eslint-disable-next-line rule, # shellcheck disable=SCnnnn) "
          "so the reviewer sees the exception where it is made. The baseline only shrinks.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
