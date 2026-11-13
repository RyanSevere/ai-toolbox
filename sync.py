#!/usr/bin/env python3
################################################################################
# File: sync.py
# Path: {PROJECT_ROOT}/sync.py
# Created by: Ryan Severe
# Created: 2026-09-14
# Last Updated: 2026-11-13
# Description: Renders the core and a profile's seeds into a consuming repository's
#              per-tool formats and stamps each output with the source SHA.
#              Dry-run by default; --write applies. Never writes Tier 3.
#              --rollout renders and commits every live target in one run.
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
import difflib
import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
RULES_DIR = ROOT / "rules"
CONTEXT_DIR = ROOT / "context"
SKILLS_DIR = ROOT / "skills"
WORKFLOWS_DIR = ROOT / "workflows"
ACTIONS_DIR = ROOT / "actions"
AGENTS_DIR = ROOT / "agents"
# Git hooks, distinct from hooks/ which holds agent hooks for the editors.
GITHOOKS_DIR = ROOT / "githooks"
PROFILE_NAME = "profile.yaml"
# The gates that run and that CI requires, one name per line, rendered from profile.lock.
# The runner and CI both read it, so the two lists cannot drift.
ENABLED_GATES = ".githooks/gates/enabled"
# Repo-relative in the profile repo, which holds the core under core/ whether it is
# vendored or not; the pre-push hook runs it with --check.
CONSENT_SCRIPT = "core/consent.py"
# The only top-level keys a profile may carry. `features` is the consented gate flags;
# `capabilities` binds wireframe capabilities to skills; `answers` holds the setup
# answers, keyed <capability file>.<question id>.
PROFILE_KEYS = {
    "source": dict, "identity": dict, "not_onboarded": dict, "defaults": dict,
    "rollout": dict, "actions": dict, "targets": dict, "features": dict, "capabilities": dict,
    "answers": dict, "gate_config_dir": str,
}
# Repo-relative, one or more plain segments. Rendered into gate-config as config-dir.
CONFIG_DIR = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9._-]*(/[A-Za-z0-9_.][A-Za-z0-9._-]*)*")
# What each repo keeps in its gate_config_dir by hand: which paths hold tests, and
# where markdown may live. Rendering one copy into every repo would be wrong in most,
# so sync.py refuses to write them.
HAND_OWNED_GATE_CONFIG = ("test-roots", "doc-paths")
EXCHANGE_DIR = ROOT / "exchange"
RESPONSES_DIR = ROOT / "responses"
# Rendered under .github/scripts/. The core ships none here; a profile's seeds/scripts/
# is where tooling the core does not own - a ticket client - comes from.
SCRIPTS_DIR = ROOT / "scripts"
HOOKS_DIR = ROOT / "hooks"
# Wireframes. Each operation's `capability:` is a name a profile may bind.
CAPABILITIES_DIR = ROOT / "capabilities"
# A section of a seed body that needs capabilities: each marker alone on its line.
REQUIRES_OPEN = re.compile(r"<!-- requires:(.*?)-->")
REQUIRES_END = "<!-- end -->"
# A section only one kind of session receives. The render target sets the mode, not the
# profile: one profile renders interactive repos and a factory bundle.
MODE_OPEN = re.compile(r"<!-- mode:(.*?)-->")
MODES = ("interactive", "factory")
INTERACTIVE = "interactive"
FACTORY = "factory"
# A word either side of one dot, so a Go template - deploy-stack's {{.State.Status}} and
# {{json .Mounts}} - is never read as a capability.
MARKER = re.compile(r"\{\{(\w+\.\w+)\}\}")
# The profile's repositories as data, for any tool that needs the estate. The core builds
# it; a profile's tools read it.
REPO_LIST = ".github/profile/repos.json"
import consent  # noqa: E402  - the only writer of gate flags; check() is its read side

STAMP = "<!-- generated from {source}@{sha} - edit the source, not this file -->"
# The profile's own render names no SHA. A SHA there is re-stamped into every rendered file
# whenever any source input changes, so two branches that each change one conflict on the
# stamp line of every file. A consuming repository's render keeps the SHA: it is the only
# record of which source version the target holds, and a target is never rendered on a branch.
STAMP_UNPINNED = "<!-- generated from {source} - edit the source, not this file -->"
# The profile's source.repo, set by build_plan before anything renders. A module value
# rather than a parameter because every render function stamps; threading it through
# a dozen signatures and their callers was the larger risk. Empty until a profile sets it.
_stamp_source = ""
# Any source name, so a file rendered by another profile is still recognised as generated.
# Either form: the SHA form, or the one the profile's own render writes.
STAMP_RE = re.compile(r"generated from [^\s@]+(?:@\S| - edit the source)")


def stamp(sha: str | None) -> str:
    """The stamp line for the profile now rendering.

    None is the form with no SHA, which only the profile's own render asks for. An empty
    string is a lookup that found nothing, and refuses rather than reading as that form.
    """
    if not _stamp_source:
        raise SyncError("nothing set the stamp's source name - set_stamp_source runs before "
                        "anything renders")
    if sha is None:
        return STAMP_UNPINNED.format(source=_stamp_source)
    if not sha:
        raise SyncError("the source SHA is empty, so there is nothing to stamp")
    return STAMP.format(source=_stamp_source, sha=sha)


def is_stamped(text: str) -> bool:
    """True when text carries a generated-file stamp from any source."""
    return STAMP_RE.search(text) is not None


def source_repo(profile: dict) -> str:
    """The profile's source.repo: the name in every stamp, commit and report."""
    repo = str((profile.get("source") or {}).get("repo") or "").strip()
    if not repo:
        raise SyncError(f"{PROFILE_NAME} source.repo is missing or empty, so there is no "
                        "source name to stamp")
    return repo


def set_stamp_source(profile: dict) -> None:
    """Take the stamp's source name from the profile; a profile without one refuses."""
    global _stamp_source
    _stamp_source = source_repo(profile)
STAMP_SHA_LENGTH = 7

# Where a spec lands decides how it is retrieved, not whether it loads.
#
# Verified 2026-09-17 in both Copilot and Cursor. Only
# applyTo '**' / alwaysApply true injects a rule body. Every other scope value
# is advertised only: name and description enter the prompt, the body does not,
# and it is read when the agent decides the description is relevant. A glob does
# not make a spec load conditionally - it makes it not load automatically at all.
#
# A scope of '*' still must not land in .github/instructions, because
# render_copilot maps it to applyTo '**' and it would then be genuinely resident
# in every session. Park those here, where nothing advertises them, and let the
# routing table in AGENTS.md point at them instead.
ON_DEMAND_DIR = ".github/rules"

# Tier 3 is hand-owned. Mixing generated and hand-written content in one file is
# how the whole mechanism stops being trusted.
# Paths sync writes into its own tree. Changes here are its output, not source
# edits, so the dirty check must not trip on work this process just did.
SELF_RENDERED = (
    "AGENTS.md",
    ".github/instructions/",
    ".github/rules/",
    ".github/prompts/",
    ".github/workflows/",
    ".github/actions/",
    ".github/agents/",
    ".github/skills/",
    ".github/scripts/",
    ".github/gates",
    ".githooks/",
    ".cursor/",
    ".claude/rules/",
    ".claude/skills/",
    ".claude/agents/",
    ".agents/skills/",
)

# Skill roots are rows of TOOLS, below render_agent. Not .agents/skills/: OpenCode is the
# factory's tool and loads it even with project config disabled, so a skill there reaches a
# headless role. Reverted 2026-11-05. It stays in RENDER_DIRS and SELF_RENDERED so the
# copies rendered before are orphans.

# Hand-owned in every repo. never_write() adds the profile's gate config files.
NEVER_WRITE = {
    ".github/copilot-instructions.md",
    "README.md",
    "AGENTS.md.pre-tier3",
}

# --rollout. One lock per profile clone: two rollouts from the same
# clone would interleave commits in every target. Relative to the profile, never
# under core/, whose bytes a vendored profile checks.
ROLLOUT_LOCK = Path("scratch") / "rollout.lock"
# PROVISIONAL. Measured rollouts took about 34 minutes twice (2026-09-28), with
# pre-push gates. Revise both by reviewing new timing data with the operator,
# not by guessing.
LOCK_MAX_AGE = timedelta(hours=1)
# PROVISIONAL, as above. The heartbeat is rewritten after each target, and the
# slowest single target measured so far is one push of about 11 minutes.
LOCK_HEARTBEAT_TIMEOUT = timedelta(minutes=20)
# Local git calls. Pushes run the target's pre-push gates, which take minutes.
GIT_TIMEOUT = 300
PUSH_TIMEOUT = 30 * 60
FETCH_TIMEOUT = 2 * 60
# How many targets push at once: probed once per machine, kept in this clone's git
# config. PROVISIONAL per-push budget, sized 2026-09-29 against a 20-core, 32 GiB
# workstation whose profile push runs 8 test shards at once.
PARALLEL_KEY = "rollout.parallel"
PARALLEL_MAX = 16
CORES_PER_PUSH = 4
MEMORY_PER_PUSH = 8 * 1024 ** 3


class Plan(dict):
    """Repo-relative path -> rendered content, where a path is written once.

    Two seeds with different names can still land on one destination, and a plain dict
    lets the later silently replace the earlier - the secondary guard to the seed-name
    check in merged_seeds.

    `dropped` holds each seed left out for an unbound capability, with the capabilities
    that dropped it, so the render can say what it did not write.
    `dropped_sections` does the same for a `<!-- requires: -->` block, with its line.
    `unbuilt` holds each answer that declares a system no binding implements yet.
    `unanswered` holds each convention a rendered conventions rule states as missing.
    `warnings` holds what a render for one tool could not carry over, one line each.
    """

    def __init__(self) -> None:
        super().__init__()
        self.warnings: list[str] = []
        self.dropped: list[tuple[Path, list[str]]] = []
        self.dropped_sections: list[tuple[Path, int, list[str]]] = []
        self.unbuilt: list[str] = []
        self.unanswered: list[str] = []

    def __setitem__(self, path: str, content: str) -> None:
        if path in self:
            raise SyncError(f"two seeds render to {path}. Duplicates are not allowed - "
                            "give one of them a new name")
        super().__setitem__(path, content)

    def update(self, other=(), /, **kwargs) -> None:
        for path, content in dict(other, **kwargs).items():
            self[path] = content


SEED_KINDS = ("rules", "skills", "context", "agents", "hooks", "githooks",
              "scripts", "workflows", "actions")


def check_seed_kinds(profile_dir: Path) -> None:
    """Refuse a folder under <profile>/seeds/ that is not a seed kind.

    Without this a typo such as seeds/skill/ renders nothing and says nothing - the same
    failure load_profile refuses for an unknown key.
    """
    base = Path(profile_dir) / "seeds"
    if not base.is_dir():
        return
    for entry in sorted(base.iterdir()):
        if entry.name not in SEED_KINDS:
            raise SyncError(f"unknown seed folder {entry.name!r} in {base}. "
                            f"Allowed: {', '.join(SEED_KINDS)}")


def merged_seeds(core: Path, profile_dir: Path, kind: str, pick) -> list[Path]:
    """The core's seeds of one kind plus the profile's, from <profile>/seeds/<kind>.

    `pick(folder)` lists a folder's seeds. A name present on both sides refuses, naming
    both paths and asking for a new one - nothing is renamed or dropped automatically.
    """
    extra = Path(profile_dir) / "seeds" / kind
    seen: dict[str, Path] = {}
    merged: list[Path] = []
    for folder in (core, extra):
        if not folder.exists():
            continue
        for path in pick(folder):
            if path.name in seen:
                raise SyncError(
                    f"seed name {path.name!r} is used by both {seen[path.name]} and {path}. "
                    "Duplicates are not allowed - give the profile seed a new name.")
            seen[path.name] = path
            merged.append(path)
    return sorted(merged, key=lambda p: p.name)


def resolve_profile(arg: Path | None) -> Path:
    """The directory holding profile.yaml - the one place a profile path is computed.

    No argument means the core's own root, which holds a profile only in a repository
    that is both. A directory without the file refuses rather than falling back: a
    guessed profile renders the wrong estate without saying so.
    """
    folder = ROOT if arg is None else Path(arg).resolve()
    if not (folder / PROFILE_NAME).is_file():
        hint = ". Pass --profile <profile folder>" if arg is None else ""
        raise SyncError(f"no {PROFILE_NAME} in {folder}{hint}")
    return folder


def load_profile(folder: Path) -> dict:
    """Read and validate <folder>/profile.yaml against PROFILE_KEYS.

    An unknown key refuses naming the key and the file, so a typo is never ignored.
    """
    path = folder / PROFILE_NAME
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SyncError(f"{path} is empty or not a mapping")
    for key, value in data.items():
        if key not in PROFILE_KEYS:
            raise SyncError(f"{path}: unknown top-level key {key!r}. "
                            f"Allowed: {', '.join(sorted(PROFILE_KEYS))}")
        if value is not None and not isinstance(value, PROFILE_KEYS[key]):
            raise SyncError(f"{path}: {key!r} must be a {PROFILE_KEYS[key].__name__}")
    return data


class SyncError(Exception):
    pass


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SyncError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def ensure_current(fetch: bool, profile_dir: Path) -> None:
    """Render from the latest source, not from whatever this clone happens to hold.

    A stale clone renders old rules and stamps them with a SHA that genuinely
    does contain them. The stamp is honest and the output is still wrong, which
    is the hardest kind of wrong to notice.
    """
    if not fetch:
        print("[WARN] --no-fetch: rendering from local HEAD, which may be behind origin")
        return

    try:
        run("git", "fetch", "--quiet", "origin")
    except SyncError as exc:
        raise SyncError(
            f"Could not reach origin, so the source cannot be confirmed current. "
            f"Re-run with --no-fetch to render from local HEAD anyway. ({exc})"
        ) from exc

    behind = run("git", "rev-list", "--count", "HEAD..origin/main")
    if behind == "0":
        return

    ahead = run("git", "rev-list", "--count", "origin/main..HEAD")
    if ahead != "0":
        raise SyncError(
            f"Local and origin have diverged ({ahead} ahead, {behind} behind). "
            "Reconcile by hand - guessing which side wins is not this tool's job."
        )

    before = run("git", "rev-parse", "HEAD")
    run("git", "merge", "--ff-only", "origin/main")
    print(f"[INFO] pulled {behind} commit(s) from origin")

    # A pull that updates this script cannot take effect in the process already
    # running it. Stopping is the only honest option.
    top = Path(run("git", "rev-parse", "--show-toplevel"))
    touched = {(top / name).resolve()
               for name in run("git", "diff", "--name-only", before, "HEAD").splitlines()}
    if touched & {Path(__file__).resolve(), (profile_dir / PROFILE_NAME).resolve()}:
        raise SyncError(
            f"That pull updated sync.py or {PROFILE_NAME}. This process is still "
            "running the old code - re-run the command to use the new version."
        )


def source_sha(fetch: bool, profile_dir: Path) -> str:
    # Sync writes its own workflow copy into this repo, so rendering a second
    # target would otherwise refuse on a tree this process just dirtied.
    dirty = [
        line for line in run("git", "status", "--porcelain").splitlines()
        if not any(p in line for p in SELF_RENDERED)
    ]
    if dirty:
        raise SyncError(
            "Source tree is dirty. Commit before rendering - a stamp pointing at a "
            "SHA that does not contain the rendered content makes the drift check lie."
        )
    ensure_current(fetch, profile_dir)
    # Derived from the source constants so a new input directory is covered on sight.
    # tests/test_sync.py checks this list against every file build_plan reads.
    # Absolute, because the core and the profile are different folders of one repository.
    sources = (RULES_DIR, CONTEXT_DIR, SKILLS_DIR, WORKFLOWS_DIR, ACTIONS_DIR, AGENTS_DIR,
               GITHOOKS_DIR, ROOT / "consent.py", RESPONSES_DIR, ROOT / "prime.py", HOOKS_DIR,
               EXCHANGE_DIR, ROOT / "cleanup.py",
               CAPABILITIES_DIR, ROOT / "sync.py", profile_dir / consent.LOCK_NAME,
               profile_dir / PROFILE_NAME, profile_dir / "seeds")
    inputs = [str(p) for p in sources]
    # Not %h: git lengthens it as a repo gains objects, so a self-hosted runner's clone
    # stamped 8 characters where a workstation stamped 7 and drift failed on both.
    full = run("git", "log", "-1", "--format=%H", "--", *inputs)
    return full[:STAMP_SHA_LENGTH]


def load_doc(path: Path, *required: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body. Required keys are named by the caller."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SyncError(f"{path}: missing frontmatter")
    _, fm_text, body = text.split("---", 2)
    meta = yaml.safe_load(fm_text) or {}
    for key in required:
        if key not in meta:
            raise SyncError(f"{path}: frontmatter missing '{key}'")
    return meta, body.lstrip("\n")


def fm(pairs: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in pairs)
    return f"---\n{lines}\n---\n"


def quoted(text: str) -> str:
    """Emit a description as a YAML block scalar, so punctuation cannot break it."""
    indented = "\n".join(f"  {line}" for line in text.strip().splitlines())
    return f">-\n{indented}"


def render_agents(body: str, sha: str) -> str:
    """AGENTS.md carries no frontmatter - it is read verbatim by every tool."""
    return f"{stamp(sha)}\n\n{body}"


def render_copilot(meta: dict, body: str, sha: str) -> str:
    # Anything other than '**' is advertisement, not auto-attachment. See ON_DEMAND_DIR.
    scope = meta.get("scope", "*")
    apply_to = "**" if scope == "*" else scope
    head = fm([("applyTo", f"'{apply_to}'"), ("description", quoted(meta["description"]))])
    return f"{head}\n{stamp(sha)}\n\n{body}"


def render_cursor(meta: dict, body: str, sha: str) -> str:
    scope = meta.get("scope", "*")
    always = bool(meta.get("alwaysApply", False))
    pairs = [("description", quoted(meta["description"]))]
    if not always and scope != "*":
        pairs.append(("globs", scope))
    pairs.append(("alwaysApply", "true" if always else "false"))
    return f"{fm(pairs)}\n{stamp(sha)}\n\n{body}"


def render_skill(meta: dict, body: str, sha: str) -> str:
    head = fm([("name", meta["name"]), ("description", quoted(meta["description"]))])
    return f"{head}\n{stamp(sha)}\n\n{body}"


def render_ondemand(meta: dict, body: str, sha: str) -> str:
    """No frontmatter: this path must never be picked up automatically."""
    note = f"> Read on demand. Routed from `AGENTS.md`.\n>\n> {meta['description'].strip()}"
    return f"{stamp(sha)}\n\n{note}\n\n---\n\n{body}"


def render_prompt(meta: dict, body: str, sha: str) -> str:
    """Frontmatter is not delivered to the model, so the body must stand alone."""
    # No default mode: a rendered one moves the chat off its role agent, and it stays moved.
    pairs = [("mode", meta["mode"])] if meta.get("mode") else []
    head = fm(pairs + [("description", quoted(meta["description"]))])
    return f"{head}\n{stamp(sha)}\n\n{body}"


def render_workflow(body: str, sha: str) -> str:
    """No frontmatter to strip - a workflow is YAML all the way down."""
    return f"# {stamp(sha)[5:-4].strip()}\n{body}"


# Suffixes whose stamp is a '#' comment line. Markdown takes the HTML-comment stamp;
# anything else is copied verbatim, because a stamp injected into JSON or a template
# breaks the file it marks.
STAMPABLE_ASSETS = (".py", ".sh", ".ps1")

# Anything a tool writes beside a skill rather than a person. Running a skill
# script once leaves bytecode here, and without this every render in the estate
# died on it - the .pyc is gitignored, so nothing looked wrong.
GENERATED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}


def stamp_markdown(body: str, sha: str) -> str:
    """Stamp a markdown asset, under its frontmatter if it has one."""
    # The gate's stamped() reads only the first 40 lines, so the stamp goes at the top.
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end != -1:
            cut = end + len("\n---\n")
            return f"{body[:cut]}{stamp(sha)}\n{body[cut:]}"
    return f"{stamp(sha)}\n\n{body}"


def render_asset(path: Path, sha: str) -> str:
    """A bundled skill asset. Stamped where the format has line comments."""
    try:
        body = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SyncError(
            f"{path} is not UTF-8 text, so it cannot be rendered as a skill asset.\n"
            f"  {exc}\n"
            "Skill assets are copied as text. If this is a build artefact, delete it "
            "and add its directory to GENERATED_DIRS in sync.py."
        ) from exc
    if path.suffix == ".md":
        return stamp_markdown(body, sha)
    if path.suffix not in STAMPABLE_ASSETS:
        return body
    marker = f"# {stamp(sha)[5:-4].strip()}"
    lines = body.splitlines(keepends=True)
    # A shebang only works on line one, so the stamp goes under it.
    if lines and lines[0].startswith("#!"):
        return lines[0] + marker + "\n" + "".join(lines[1:])
    return marker + "\n" + body


# The tool-neutral hook schema - hooks/README.md. Refused rather than passed
# through: an unknown key would otherwise render as if it meant something.
HOOK_KEYS = {"event", "kind", "run", "timeout", "tools"}
HOOK_REQUIRED = ("event", "kind", "run")
# The fail mode comes from the kind, so it cannot be set wrong per hook.
HOOK_FAILS_CLOSED = {"permission": True, "observer": False}
# Each tool's native event, and its tool matcher where it needs one. Copilot's column is
# validation only until its adapter renders it, so a hook it cannot run is refused today.
HOOK_EVENTS = {
    "cursor": {
        "session.start": ("sessionStart", None),
        "shell.before": ("beforeShellExecution", None),
        "file.write.before": ("preToolUse", "Write"),
        "file.write.after": ("afterFileEdit", None),
        "reply.after": ("afterAgentResponse", None),
        "turn.end": ("stop", None),
    },
    "copilot": {
        "session.start": ("sessionStart", None),
        "shell.before": ("preToolUse", "bash|powershell"),
        "file.write.before": ("preToolUse", "edit|create"),
        "file.write.after": ("postToolUse", None),
        "turn.end": ("agentStop", None),
    },
}
NEUTRAL_EVENTS = sorted(set().union(*HOOK_EVENTS.values()))
HOOK_LIB = "lib"

# JSON has no comment syntax, so these carry the stamp as a key and are found by path.
MARKED_JSON = (".cursor/hooks.json",)
# Rendered per machine, so never tracked and never compared by --check.
LOCAL_RENDERED = (".cursor/hooks.json",)

# A bare name resolves through PATH on each machine; a Windows checkout's first python3 was
# once an sh shim, and every fail-closed hook then denied every shell command.
BARE_INTERPRETERS = {"python", "python3", "py"}
WINDOWS_MOUNT = re.compile(r"^/mnt/[A-Za-z](/|$)")


def hook_interpreter(python: str, windows: bool) -> str:
    """The quoted interpreter in the form the hook shell needs. Cursor runs a Windows hook
    through PowerShell, which calls a quoted path only with &; elsewhere a POSIX shell."""
    if windows:
        return f'& "{python}"'
    return "'" + python.replace("'", "'\\''") + "'"


SHELL_SAFE = re.compile(r"[\w./:=+-]+")


def shell_argument(arg: str, windows: bool) -> str:
    """One run: entry quoted for the hook shell. PowerShell single quotes take no escapes but
    a doubled quote; @ and , are left out of the bare set because PowerShell reads them."""
    if SHELL_SAFE.fullmatch(arg):
        return arg
    if windows:
        return "'" + arg.replace("'", "''") + "'"
    return shlex.quote(arg)


def hook_command(run: list[str], where: str, python: str, windows: bool) -> str:
    """Cursor's adapter: join run: for the machine's hook shell."""
    first = run[0]
    if first.lower().removesuffix(".exe") in BARE_INTERPRETERS:
        raise SyncError(f"{where} runs a bare {first!r}, which each machine resolves through "
                        "PATH to whatever comes first; name {python} instead")
    if "{python}" in run[1:]:
        raise SyncError(f"{where}: {{python}} must open run:, where PowerShell's & "
                        "is the call operator")
    rest = [shell_argument(arg, windows) for arg in run[1:]]
    if first == "{python}":
        return " ".join([hook_interpreter(python, windows), *rest])
    return " ".join([shell_argument(first, windows), *rest])


RENDERED_INTERPRETER = re.compile(r"""^(& "[^"]+"|'(?:[^']|'\\'')*')""")
HOOK_LAUNCH_TIMEOUT = 30


def launch_probe(command: str) -> str | None:
    """The rendered command with a no-op in place of its script, or None when it opens with
    no interpreter that hook_interpreter rendered."""
    found = RENDERED_INTERPRETER.match(command)
    return f"{found.group(1)} -c pass" if found else None


def hook_shells(windows: bool) -> list[list[str]]:
    """Each shell Cursor may run a hook under. Cursor does not say which PowerShell it uses on
    Windows, so pwsh is tried as well when installed."""
    if not windows:
        return [["sh", "-c"]]
    flags = ["-NoProfile", "-NonInteractive", "-Command"]
    shells = [["powershell.exe", *flags]]
    if (pwsh := shutil.which("pwsh")):
        shells.append([pwsh, *flags])
    return shells


def check_hooks_launch(rel: str, content: str, windows: bool) -> None:
    """Refuse a hooks.json whose interpreter does not start. Every hook fails closed, so one
    that cannot launch denies every agent action, and the agent cannot repair the file."""
    commands = {entry["command"] for entries in json.loads(content)["hooks"].values()
                for entry in entries}
    for command in sorted(commands):
        probe = launch_probe(command)
        if probe is None:
            print(f"  not launch-checked, no rendered interpreter: {command}")
            continue
        for shell in hook_shells(windows):
            try:
                ran = subprocess.run([*shell, probe], capture_output=True, text=True,
                                     timeout=HOOK_LAUNCH_TIMEOUT)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise SyncError(f"{rel} not written: a hook could not be launched under "
                                f"{shell[0]}: {exc}\n  {command}") from exc
            if ran.returncode != 0:
                output = (ran.stdout + ran.stderr).strip()
                raise SyncError(f"{rel} not written: a hook does not launch under {shell[0]}, "
                                f"exit code {ran.returncode}\n  {command}\n{output}")


def on_windows_mount(path: str, platform: str | None = None) -> bool:
    """A Windows folder seen from WSL, where a Linux interpreter path cannot launch."""
    return (platform or sys.platform).startswith("linux") and bool(WINDOWS_MOUNT.match(path))


def hook_spec(spec, where: str) -> dict:
    """A hook.yaml checked against the tool-neutral schema, with tools: defaulted."""
    if not isinstance(spec, dict):
        raise SyncError(f"{where} must be a mapping")
    unknown = sorted(set(spec) - HOOK_KEYS)
    if unknown:
        hint = ""
        if "failClosed" in unknown:
            hint = "; the fail mode comes from kind:, permission or observer"
        elif "command" in unknown:
            hint = "; command: is now run:, an argument list - hooks/README.md"
        raise SyncError(f"{where}: unknown key(s) {unknown}; allowed {sorted(HOOK_KEYS)}{hint}")
    missing = [key for key in HOOK_REQUIRED if key not in spec]
    if missing:
        raise SyncError(f"{where}: missing {missing}")
    run = spec["run"]
    if not isinstance(run, list):
        raise SyncError(f"{where}: run: must be a list of arguments, not {type(run).__name__}")
    if not run:
        raise SyncError(f"{where}: run: is empty")
    for index, arg in enumerate(run):
        if not isinstance(arg, str):
            raise SyncError(f"{where}: run: entry {index} is not a string ({arg!r})")
    if spec["kind"] not in HOOK_FAILS_CLOSED:
        raise SyncError(f"{where}: kind: {spec['kind']!r} is not one of "
                        f"{sorted(HOOK_FAILS_CLOSED)}")
    if spec["event"] not in NEUTRAL_EVENTS:
        raise SyncError(f"{where}: event: {spec['event']!r} is not a neutral event; "
                        f"one of {NEUTRAL_EVENTS}")
    tools = spec.get("tools", sorted(HOOK_EVENTS))
    if not isinstance(tools, list) or not tools:
        raise SyncError(f"{where}: tools: must be a non-empty list, of {sorted(HOOK_EVENTS)}")
    unknown_tools = sorted(set(tools) - set(HOOK_EVENTS))
    if unknown_tools:
        raise SyncError(f"{where}: tools: {unknown_tools} unknown; known {sorted(HOOK_EVENTS)}")
    lacking = [tool for tool in sorted(tools) if spec["event"] not in HOOK_EVENTS[tool]]
    if lacking:
        raise SyncError(f"{where}: {lacking} have no {spec['event']} event, so the hook would "
                        "render as guarded with nothing guarding. Leave them out with tools:")
    return {**spec, "tools": tools}


def render_hook_assets(plan: Plan, hook_dir: Path, sha: str, skip: Path | None = None) -> None:
    for asset in sorted(p for p in hook_dir.rglob("*") if p.is_file()):
        rel = asset.relative_to(hook_dir)
        if asset == skip or GENERATED_DIRS.intersection(rel.parts):
            continue
        plan[f".cursor/hooks/{hook_dir.name}/{rel.as_posix()}"] = render_asset(asset, sha)


def render_cursor_hooks(sha: str, owner: str | None,
                        profile_dir: Path) -> dict[str, str]:
    """Every hooks/<name>/ with a hook.yaml, merged into one .cursor/hooks.json.

    The source is the tool-neutral schema (hooks/README.md); this is Cursor's adapter.
    Cursor hooks fail open by default, so failClosed is written on every entry, from kind:.
    A directory without hook.yaml is not an agent hook - no-secret-defaults is a git hook.
    `{owner}` in run: is the profile's GitHub owner, so a hook script never names one.
    hooks/lib/ is the shared runtime library, rendered beside the hooks whenever any render.
    """
    plan = Plan()
    events: dict[str, list[dict]] = {}
    hook_dirs = [hook_dir for hook_dir in
                 merged_seeds(HOOKS_DIR, profile_dir, "hooks",
                              lambda f: [p for p in f.iterdir() if p.is_dir()])]
    for hook_dir in hook_dirs:
        source = hook_dir / "hook.yaml"
        if not source.is_file():
            continue
        where = f"hooks/{hook_dir.name}/hook.yaml"
        spec = hook_spec(yaml.safe_load(source.read_text(encoding="utf-8")), where)
        if "cursor" not in spec["tools"]:
            continue
        run = [arg.replace("{owner}", owner) if owner else arg for arg in spec["run"]]
        if any("{owner}" in arg for arg in run):
            raise SyncError(f"{where} uses {{owner}}, but {PROFILE_NAME} source has no owner")
        if run[0] == "{python}" and sys.prefix != sys.base_prefix:
            raise SyncError(f"sync.py is running in a virtual environment ({sys.prefix}); a hook "
                            "rendered with its interpreter stops launching when that environment "
                            "goes. Run sync.py with the base interpreter")
        native, matcher = HOOK_EVENTS["cursor"][spec["event"]]
        entry = {"command": hook_command(run, where, sys.executable, os.name == "nt")}
        if matcher:
            entry["matcher"] = matcher
        if "timeout" in spec:
            entry["timeout"] = spec["timeout"]
        entry["failClosed"] = HOOK_FAILS_CLOSED[spec["kind"]]
        events.setdefault(native, []).append(entry)
        render_hook_assets(plan, hook_dir, sha, skip=source)
    if events:
        for hook_dir in hook_dirs:
            if hook_dir.name == HOOK_LIB:
                render_hook_assets(plan, hook_dir, sha)
        config = {"_generated": stamp(sha)[5:-4].strip(), "version": 1,
                  "hooks": events}
        plan[".cursor/hooks.json"] = json.dumps(config, indent=2) + "\n"
    return plan


def render_agent(meta: dict, body: str, sha: str, skills: tuple[str, ...] = ()) -> str:
    """tools is an allowlist enforced before the model - verified 2026-09-18.

    `skills` is passed for a factory role only: the harness reads it to give the role
    those skills and no others.
    """
    fields = [("name", meta["name"]), ("description", quoted(meta["description"]))]
    if meta.get("tools") is not None:
        fields.append(("tools", json.dumps(meta["tools"])))
    # Omitted, VS Code lets the agent run any agent as a subagent, with that agent's tools.
    if meta.get("agents") is not None:
        fields.append(("agents", json.dumps(meta["agents"])))
    if skills:
        fields.append(("skills", json.dumps(list(skills))))
    return f"{fm(fields)}\n{stamp(sha)}\n\n{body}"


# Claude Code's tool names for each source tool name. An empty entry is a source tool the
# shell tools already cover; any name not here is dropped with a warning.
CLAUDE_TOOLS = {
    "read": ("Read",),
    "search": ("Grep", "Glob"),
    "edit": ("Edit", "Write"),
    "execute": ("Bash", "PowerShell"),
    "execute/runInTerminal": ("Bash", "PowerShell"),
    "execute/getTerminalOutput": (),
    "execute/killTerminal": (),
    "execute/testFailure": (),
    "agent": ("Agent",),
}
# What an agent seed's optional `model:` may say. Only Claude Code's agent file carries it.
AGENT_MODELS = ("sonnet", "opus", "haiku", "fable", "inherit")


def check_agent_model(meta: dict, path: Path) -> None:
    """Refuse a `model:` that Claude Code would not take, on every target."""
    if "model" in meta and meta["model"] not in AGENT_MODELS:
        raise SyncError(f"{path}: model: {meta['model']!r} is not one of "
                        f"{', '.join(AGENT_MODELS)}")


def render_claude_agent(meta: dict, body: str, sha: str, warn) -> str:
    """Claude Code's subagent file. `tools` is a comma-separated allowlist mapped from the
    source names; omitted in the source, it is omitted here and the agent inherits."""
    name = meta["name"]
    fields = [("name", name), ("description", quoted(meta["description"]))]
    if meta.get("tools") is not None:
        tools: list[str] = []
        for source in meta["tools"]:
            if source not in CLAUDE_TOOLS:
                warn(f"agent {name}: tool {source!r} has no Claude Code equivalent, so it is "
                     "dropped from the rendered tools")
                continue
            tools.extend(t for t in CLAUDE_TOOLS[source] if t not in tools)
        if not tools:
            # An omitted tools: key means every tool, so an empty result must not render as one.
            raise SyncError(f"agent {name}: none of its tools map to Claude Code, and an empty "
                            "allowlist would render as every tool")
        fields.append(("tools", ", ".join(tools)))
    if meta.get("agents") is not None:
        warn(f"agent {name}: agents: is not rendered for Claude Code, whose subagents cannot "
             "be restricted that way")
    fields.append(("model", meta.get("model") or "inherit"))
    return f"{fm(fields)}\n{stamp(sha)}\n\n{body}"


def render_claude_rule(meta: dict, body: str, sha: str) -> str | None:
    """.claude/rules/<id>.md. A file with no `paths` loads at launch, so only an always-on
    rule goes without one; an on-demand rule is not rendered at all."""
    scope = meta.get("scope", "*")
    if meta.get("alwaysApply", False):
        return f"{stamp(sha)}\n\n{body}"
    if scope == "*":
        return None
    return f"---\npaths:\n  - {json.dumps(scope)}\n---\n\n{stamp(sha)}\n\n{body}"


def render_copilot_rule(meta: dict, body: str, sha: str) -> str | None:
    """None for an on-demand rule: a scope of '*' here would be resident. See ON_DEMAND_DIR."""
    if meta.get("scope", "*") == "*" and not meta.get("alwaysApply", False):
        return None
    return render_copilot(meta, body, sha)


def render_copilot_agent(meta: dict, body: str, sha: str, warn) -> str:
    return render_agent(meta, body, sha)


@dataclass(frozen=True)
class Tool:
    """One interactive tool's output for rules, skills and agents. A new tool is a new row.

    `rule_path` takes {id}; `rule` returns the file, or None when the tool does not render
    that rule. `skill_root` and `agent_path` (takes {name}) are None for a tool without them,
    and `agent` takes (meta, body, sha, warn). Hooks are not here.
    """
    name: str
    rule_path: str
    rule: object
    skill_root: str | None
    agent_path: str | None
    agent: object


TOOLS = (
    Tool("copilot", ".github/instructions/{id}.instructions.md", render_copilot_rule,
         ".github/skills", ".github/agents/{name}.agent.md", render_copilot_agent),
    Tool("cursor", ".cursor/rules/{id}.mdc", render_cursor, ".cursor/skills", None, None),
    Tool("claude", ".claude/rules/{id}.md", render_claude_rule, ".claude/skills",
         ".claude/agents/{name}.md", render_claude_agent),
)
# Derived, for what reads the roots without the rest of a row.
SKILL_ROOTS = tuple(t.skill_root for t in TOOLS if t.skill_root)


def repo_list(manifest: dict) -> dict:
    """The estate as data: owner, every repository with its GitHub name and issue key, and
    the repositories deliberately left out. Rendered to REPO_LIST, and used in memory by
    runner, so the file and a source run agree by construction."""
    source = manifest.get("source") or {}
    owner = source.get("owner")
    if not owner:
        raise SyncError(f"{PROFILE_NAME} source has no owner, so no GitHub name can be built")
    repos = [{"name": source["repo"], "github": f"{owner}/{source['repo']}",
              "key": source.get("key")}]
    for name, cfg in (manifest.get("targets") or {}).items():
        cfg = cfg or {}
        if cfg.get("skip"):
            continue
        repos.append({"name": name, "github": f"{owner}/{cfg.get('remote') or name}",
                      "key": cfg.get("key")})
    not_onboarded = [{"name": name, "reason": reason}
                     for name, reason in (manifest.get("not_onboarded") or {}).items()]
    return {"owner": owner, "repos": repos, "not_onboarded": not_onboarded}


def render_repo_list(manifest: dict, sha: str) -> str:
    """repo_list() as the rendered file, stamped as a key because JSON has no comments. The
    stamp is what lets the rendered-only gate skip a rollout that changes it."""
    stamped = {"_generated": stamp(sha)[5:-4].strip(), **repo_list(manifest)}
    return json.dumps(stamped, indent=2) + "\n"


def issue_keys(manifest: dict) -> str:
    """Generated so the table cannot drift from the manifest that defines it."""
    rows = []
    src = manifest.get("source") or {}
    if src.get("key"):
        rows.append((src["repo"], src["key"]))
    for name, cfg in (manifest.get("targets") or {}).items():
        cfg = cfg or {}
        if not cfg.get("skip") and cfg.get("key"):
            rows.append((name, cfg["key"]))
    width = max((len(r) for r, _ in rows), default=4)
    lines = [f"| {'Repo'.ljust(width)} | Issue key |", f"|{'-' * (width + 2)}|---|"]
    lines += [f"| {repo.ljust(width)} | `{key}-<n>` |" for repo, key in sorted(rows)]
    return "\n".join(lines)


BRANCH = re.compile(r"[A-Za-z0-9._/-]+")


def render_gate_config(target: str, cfg: dict, manifest: dict, sha: str) -> str:
    """What the pre-push hook and its gates read: key=value lines, never sourced.

    Tracked and stamped rather than per-clone git config, where one `git config` line
    moved the deploy branch or the identity a gate compares against, and nothing showed
    it. A tracked file changed by hand is a diff the drift check reports.
    """
    branch = str(cfg.get("branch", "main"))
    # A newline here would write a line of its own, so the value is checked whole.
    if not BRANCH.fullmatch(branch):
        raise SyncError(f"{target}: branch {branch!r} is not a branch name")
    marker = f"# {stamp(sha)[5:-4].strip()}"
    # Only the profile repo holds a lock to check; a target trusts its rendered list.
    consent_check = f"consent-check={CONSENT_SCRIPT}\n" if cfg.get("profile_repo") else ""
    return (f"{marker}\n"
            f"deploy-branch={branch}\n"
            f"identity-email={identity(manifest)['email']}\n"
            f"config-dir={gate_config_dir(manifest)}\n"
            f"{consent_check}")


def gate_config_dir(manifest: dict) -> str:
    """The directory each repo keeps its gate configuration in, from the profile.

    No default: the core names no CI system's folder, so a profile that leaves this out
    has made no decision, and a guess would be one made for it.
    """
    value = manifest.get("gate_config_dir")
    if not isinstance(value, str) or not value.strip():
        raise SyncError(f"{PROFILE_NAME} has no gate_config_dir: - the directory each repo "
                        "keeps test-roots, doc-paths and lint-baseline/ in. Add one, for "
                        "example `gate_config_dir: .gates`")
    value = value.strip().rstrip("/")
    if not CONFIG_DIR.fullmatch(value) or {".", ".."} & set(value.split("/")):
        raise SyncError(f"{PROFILE_NAME} gate_config_dir {value!r} is not a repo-relative "
                        "directory")
    return value


def known_capabilities() -> set[str]:
    """Every name a profile may bind: each operation's `capability:` in each wireframe under
    capabilities/. Read, not listed, so a new wireframe needs no edit here."""
    names: dict[str, Path] = {}
    for path in sorted(CAPABILITIES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        operations = data.get("operations") if isinstance(data, dict) else None
        if not isinstance(operations, dict):
            raise SyncError(f"{path}: no operations: mapping")
        for operation, entry in operations.items():
            name = entry.get("capability") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name:
                raise SyncError(f"{path}: operation {operation!r} names no capability")
            if name in names:
                raise SyncError(f"capability {name!r} is defined by both {names[name]} and {path}")
            names[name] = path
    return set(names)


def capability_bindings(manifest: dict, skills: set[str], known: set[str]) -> dict[str, str]:
    """capability -> the skill bound to it, from the profile's capabilities:.

    A name no wireframe defines refuses rather than reading as unbound, which would drop
    whatever needs it without saying the binding was a typo.
    """
    bound: dict[str, str] = {}
    for name, value in (manifest.get("capabilities") or {}).items():
        if name not in known:
            raise SyncError(f"{PROFILE_NAME} capabilities: {name!r} is not a capability. "
                            f"Known: {', '.join(sorted(known)) or 'none'}")
        if not (isinstance(value, dict) and set(value) == {"skill"}
                and isinstance(value["skill"], str)):
            raise SyncError(f"{PROFILE_NAME} capabilities: {name} must be "
                            f"{{skill: <name>}}, not {value!r}")
        if value["skill"] not in skills:
            raise SyncError(f"{PROFILE_NAME} capabilities: {name} is bound to skill "
                            f"{value['skill']!r}, which no seed provides")
        bound[name] = value["skill"]
    return bound


@dataclass(frozen=True)
class Questions:
    """One capability file's setup questions, and the capabilities it defines.

    `renders` holds the conventions an agent reads, in ask order; `asks` maps each to its
    question text.
    """
    ids: frozenset[str]
    declares: str | None
    capabilities: frozenset[str]
    renders: tuple[str, ...] = ()
    asks: tuple[tuple[str, str], ...] = ()


def setup_questions() -> dict[str, Questions]:
    """Each capability file's name -> its setup questions. Read, not listed, like
    known_capabilities, so a new wireframe needs no edit here.

    `declares` is the one question whose answer names the profile's system, marked in the
    file rather than named here.
    """
    found: dict[str, Questions] = {}
    for path in sorted(CAPABILITIES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        setup = data.get("setup") or []
        if not isinstance(setup, list):
            raise SyncError(f"{path}: setup: must be a list of questions")
        ids: set[str] = set()
        declares = None
        renders: list[tuple[str, str]] = []
        for entry in setup:
            question = entry.get("id") if isinstance(entry, dict) else None
            if not isinstance(question, str) or not question:
                raise SyncError(f"{path}: a setup question has no id: {entry!r:.80}")
            if question in ids:
                raise SyncError(f"{path}: setup question {question!r} is asked twice")
            ids.add(question)
            flag = entry.get("declares", False)
            if flag is not True and flag is not False:
                raise SyncError(f"{path}: setup question {question!r}: declares must be true "
                                f"or absent, not {flag!r}")
            if flag:
                if declares:
                    raise SyncError(f"{path}: both {declares!r} and {question!r} declare the "
                                    "system. One question names it")
                declares = question
            if "renders" in entry and entry["renders"] is not True:
                raise SyncError(f"{path}: setup question {question!r}: renders must be true "
                                f"or absent, not {entry['renders']!r}")
            if "renders" in entry:
                renders.append((question, str(entry.get("ask") or question)))
        operations = data.get("operations") or {}
        names = {entry.get("capability") for entry in operations.values()
                 if isinstance(entry, dict)} if isinstance(operations, dict) else set()
        found[path.stem] = Questions(frozenset(ids), declares, frozenset(names - {None}),
                                     tuple(q for q, _ in renders), tuple(renders))
    return found


def validate_answers(manifest: dict, questions: dict[str, Questions]) -> dict[str, str]:
    """The profile's answers:, each refused unless a capability file asks it and the answer
    is prose. Empty is missing; answers are strings."""
    answers = manifest.get("answers") or {}
    for key, value in answers.items():
        stem, _, question = str(key).partition(".")
        if stem not in questions or question not in questions[stem].ids:
            asked = sorted(f"{s}.{q}" for s, entry in questions.items() for q in entry.ids)
            raise SyncError(f"{PROFILE_NAME} answers: {key!r} is not a setup question. "
                            f"Asked: {', '.join(asked) or 'none'}")
        if not isinstance(value, str) or not value.strip():
            raise SyncError(f"{PROFILE_NAME} answers: {key} must be a non-empty string, "
                            f"not {value!r:.80}")
    return answers


def unbuilt_answers(answers: dict[str, str], questions: dict[str, Questions],
                    bound: dict[str, str]) -> list[str]:
    """Each answer that declares a system while nothing binds a capability its file defines."""
    return [f"{stem}.{entry.declares}" for stem, entry in sorted(questions.items())
            if entry.declares and f"{stem}.{entry.declares}" in answers
            and not entry.capabilities & set(bound)]


CONVENTIONS_MARKER = "<!-- CONVENTIONS -->"


def conventions(answers: dict[str, str], questions: dict[str, Questions]
                ) -> list[tuple[str, str, list[str]]]:
    """(stem, rule body, flagged keys left unanswered) per capability file whose system is
    declared. Undeclared renders nothing and reports nothing: no system, no conventions."""
    rules = []
    for stem, entry in sorted(questions.items()):
        if not entry.renders or f"{stem}.{entry.declares}" not in answers:
            continue
        lines = [f"# {stem.capitalize()} conventions", "",
                 f"This profile's answers to the setup questions in `capabilities/{stem}.yaml`.",
                 f"Read them before writing to the {stem}."]
        missing = []
        for question, ask in entry.asks:
            key = f"{stem}.{question}"
            answer = answers.get(key)
            if answer is None:
                missing.append(key)
                answer = f"Not answered: `{key}` has no answer in this profile."
            lines += ["", f"## {ask}", "", answer.strip()]
        rules.append((stem, "\n".join(lines) + "\n", missing))
    return rules


def conventions_meta(stem: str) -> dict:
    """The description a conventions rule is advertised by."""
    return {"description": f"{stem.capitalize()} CONVENTIONS - this profile's answers to the "
                           f"{stem} setup questions, which say how it writes to its {stem}. "
                           f"Read before any {stem} write."}


def conventions_rows(rules: list[tuple[str, str, list[str]]]) -> str:
    """One routing-table row per rendered conventions rule, or nothing."""
    return "".join(f"| `{ON_DEMAND_DIR}/{stem}-conventions.md` | Before any {stem} write - "
                   f"this profile's answers to its {stem} setup questions |\n"
                   for stem, _, _ in rules)


def unbound_requirements(meta: dict, path: Path, known: set[str],
                         bound: dict[str, str]) -> list[str]:
    """The capabilities a seed's `requires:` names that the profile leaves unbound."""
    wanted = meta.get("requires")
    if wanted is None:
        return []
    if not isinstance(wanted, list) or not all(isinstance(n, str) for n in wanted):
        raise SyncError(f"{path}: requires: must be a list of capability names")
    unknown = [n for n in wanted if n not in known]
    if unknown:
        raise SyncError(f"{path}: requires: names {unknown}, which no wireframe under "
                        f"{CAPABILITIES_DIR.name}/ defines")
    return [n for n in wanted if n not in bound]


def refuse_requires(meta: dict, path: Path) -> None:
    """AGENTS.md and the estate map must render in every repo, so neither may be dropped."""
    if "requires" in meta:
        raise SyncError(f"{path}: requires: would drop it from every repo whose profile "
                        "leaves the capability unbound. Use a <!-- requires: --> block instead")


def body_start(path: Path) -> int:
    """The line of `path` that load_doc's body starts on, so a refusal names the source line."""
    _, fm_text, rest = path.read_text(encoding="utf-8").split("---", 2)
    return 1 + f"---{fm_text}---".count("\n") + len(rest) - len(rest.lstrip("\n"))


def render_body(body: str, path: Path, meta: dict, known: set[str], bound: dict[str, str],
                plan: Plan, mode: str = INTERACTIVE) -> str:
    """Resolve a seed body's `<!-- requires: -->` and `<!-- mode: -->` blocks and
    `{{capability}}` markers.

    A requires block whose capabilities are all bound keeps its content and loses its
    marker lines; any other is removed and recorded in plan.dropped_sections. A marker
    renders as the skill bound to it, and is allowed only where the seed's requires: or an
    enclosing block guarantees a binding - anywhere else it renders for one profile and
    breaks for the next. Fenced code is not exempt, so a marker cannot hide in an example.

    A mode block is kept only when it names `mode`, the render target's. It is not recorded
    as dropped: every render leaves out the other mode's sections, so a listing would be
    noise. Neither kind of block nests in either.
    """
    first = body_start(path)
    required = set(meta.get("requires") or [])
    out: list[str] = []
    opened_at: int | None = None
    opened_kind = ""
    block: list[str] = []
    keep = True
    for number, line in enumerate(body.splitlines(keepends=True), start=first):
        where = f"{path}:{number}"
        stripped = line.strip()
        opening = REQUIRES_OPEN.fullmatch(stripped)
        mode_opening = MODE_OPEN.fullmatch(stripped)
        if (opening or mode_opening) and opened_at is not None:
            hint = "; list both capabilities" if opening and opened_kind == "requires" else ""
            raise SyncError(f"{where}: a block inside the {opened_kind} block opened at line "
                            f"{opened_at}. Nesting is refused{hint}")
        if mode_opening:
            named = mode_opening.group(1).strip()
            if named not in MODES:
                raise SyncError(f"{where}: mode block names {named!r}. "
                                f"Modes: {', '.join(MODES)}")
            opened_at, opened_kind, block, keep = number, "mode", [], named == mode
            continue
        if opening:
            block = [n.strip() for n in opening.group(1).split(",") if n.strip()]
            if not block:
                raise SyncError(f"{where}: a requires block names no capability")
            unknown = [n for n in block if n not in known]
            if unknown:
                raise SyncError(f"{where}: requires block names {unknown}, which no "
                                f"wireframe under {CAPABILITIES_DIR.name}/ defines")
            opened_at, opened_kind = number, "requires"
            unbound = [n for n in block if n not in bound]
            if unbound:
                plan.dropped_sections.append((path, number, unbound))
            keep = not unbound
            continue
        if stripped == REQUIRES_END:
            if opened_at is None:
                raise SyncError(f"{where}: {REQUIRES_END} with no requires or mode block open")
            opened_at, opened_kind, block, keep = None, "", [], True
            continue
        if "<!-- requires:" in line or "<!-- mode:" in line or REQUIRES_END in line:
            raise SyncError(f"{where}: a block marker must be alone on its line")
        guarded = required | set(block)
        for match in MARKER.finditer(line):
            name = match.group(1)
            if name not in known:
                raise SyncError(f"{where}: {match.group(0)} names no capability a wireframe "
                                "defines")
            if name not in guarded:
                raise SyncError(f"{where}: {match.group(0)} is unguarded. Add {name} to "
                                f"requires: or put it inside <!-- requires: {name} -->")
        if keep:
            out.append(MARKER.sub(lambda m: f"the `{bound[m.group(1)]}` skill", line))
    if opened_at is not None:
        raise SyncError(f"{path}:{opened_at}: {opened_kind} block is never closed with "
                        f"{REQUIRES_END}")
    return "".join(out)


def seed_sessions(meta: dict, path: Path) -> tuple[str, ...]:
    """The kinds of session a seed is rendered for: its `sessions:`, else interactive only.

    Frontmatter `mode:` is taken - a prompt seed's Copilot mode - so this key has its own
    name. A role the factory runs says `sessions: [interactive, factory]`.
    """
    value = meta.get("sessions")
    if value is None:
        return (INTERACTIVE,)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise SyncError(f"{path}: sessions: must be a non-empty list drawn from "
                        f"{', '.join(MODES)}")
    unknown = [v for v in value if v not in MODES]
    if unknown:
        raise SyncError(f"{path}: sessions: names {unknown}. Modes: {', '.join(MODES)}")
    if len(set(value)) != len(value):
        raise SyncError(f"{path}: sessions: lists a mode twice")
    return tuple(value)


def seed_skills(meta: dict, path: Path, factory_skills: set[str]) -> tuple[str, ...]:
    """The factory skills an agent seed's role is given: its `skills:`, else none.

    Checked on every target, so a typo refuses on the first render rather than only where
    the bundle is built. A name must be a skill rendered for the factory - an interactive
    one never reaches a headless role.
    """
    value = meta.get("skills")
    if value is None:
        return ()
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise SyncError(f"{path}: skills: must be a non-empty list of skill names")
    if len(set(value)) != len(value):
        raise SyncError(f"{path}: skills: lists a skill twice")
    missing = sorted(set(value) - factory_skills)
    if missing:
        raise SyncError(f"{path}: skills: names {missing}, which no skill seed renders for "
                        f"{FACTORY}. Add {FACTORY} to that skill's sessions:, or check the name")
    return tuple(value)


def check_body(body: str, path: Path, meta: dict, known: set[str]) -> None:
    """Parse a dropped seed's body for the refusals alone.

    Otherwise a malformed block or an unguarded marker passes every profile that leaves the
    seed unbound and refuses only in the first one that binds it. Every capability counts
    as bound and the plan is thrown away, so nothing is recorded as dropped twice.
    """
    render_body(body, path, meta, known, dict.fromkeys(known, ""), Plan())


def report_drops(plan: Plan) -> None:
    def shown(path: Path) -> str:
        return (path.relative_to(ROOT) if path.is_relative_to(ROOT) else path).as_posix()

    for path, unbound in plan.dropped:
        print(f"[INFO] dropped {shown(path)}: unbound {', '.join(unbound)}")
    for path, line, unbound in plan.dropped_sections:
        print(f"[INFO] dropped section {shown(path)}:{line}: unbound {', '.join(unbound)}")
    for key in plan.unbuilt:
        stem = key.partition(".")[0]
        print(f"[INFO] unbuilt: {key} is answered, and no capability {stem}.yaml defines "
              "is bound")
    for key in plan.unanswered:
        stem = key.partition(".")[0]
        print(f"[INFO] unanswered: {key} is stated as missing in {stem}-conventions")
    for line in plan.warnings:
        print(f"[WARN] {line}")


def never_write(manifest: dict) -> set[str]:
    """Every path sync.py must not write: the fixed set, plus this profile's gate config."""
    folder = gate_config_dir(manifest)
    return NEVER_WRITE | {f"{folder}/{name}" for name in HAND_OWNED_GATE_CONFIG}


def render_enabled_gates(manifest: dict, profile_dir: Path, sha: str) -> str:
    """The enabled-gate list from the consented flags. A lock that disagrees refuses.

    Estate-wide rather than per-target: every target receives the same gates, so a
    per-repo list could only drift from them.
    """
    folder = Path(profile_dir)
    try:
        gates = consent.check(folder, manifest.get("features"), consent.known_gates(profile_dir))
    except consent.ConsentError as error:
        raise SyncError(str(error)) from error
    marker = f"# {stamp(sha)[5:-4].strip()}"
    header = ("# Gates the pre-push hook runs and CI requires, from profile.lock. Change one\n"
              "# with consent.py in the profile, never here.\n")
    return marker + "\n" + header + "".join(f"{name}\n" for name, on in sorted(gates.items())
                                            if on)


def add_rules(plan: Plan, rule_id: str, meta: dict, body: str, sha: str | None) -> None:
    """One rule into every tool's rule path that renders it."""
    for tool in TOOLS:
        text = tool.rule(meta, body, sha)
        if text is not None:
            plan[tool.rule_path.format(id=rule_id)] = text


def build_plan(target: str, cfg: dict, defaults: dict, sha: str | None, manifest: dict,
               profile_dir: Path) -> Plan:
    """Map repo-relative path -> rendered content.

    `profile_dir` holds the profile's own seeds under seeds/. The core is never a profile,
    so there is no default to fall back on. `sha` is the source commit every stamp names;
    None is the profile rendering itself, whose stamps name none.
    """
    set_stamp_source(manifest)
    check_seed_kinds(profile_dir)
    excluded = set(cfg.get("exclude") or [])
    plan = Plan()
    skill_dirs = [d for d in merged_seeds(SKILLS_DIR, profile_dir, "skills",
                                          lambda f: [p for p in f.iterdir() if p.is_dir()])
                  if (d / "procedure.md").exists()]
    known = known_capabilities()
    bound = capability_bindings(manifest, {d.name for d in skill_dirs}, known)
    questions = setup_questions()
    answers = validate_answers(manifest, questions)
    plan.unbuilt = unbuilt_answers(answers, questions, bound)
    rules = conventions(answers, questions)
    for stem, rule, missing in rules:
        plan[f"{ON_DEMAND_DIR}/{stem}-conventions.md"] = render_ondemand(
            conventions_meta(stem), rule, sha)
        add_rules(plan, f"{stem}-conventions", conventions_meta(stem), rule, sha)
        plan.unanswered += missing

    source = RULES_DIR / "prescriptions.md"
    meta, body = load_doc(source, "id", "description")
    refuse_requires(meta, source)
    body = render_body(body, source, meta, known, bound, plan)
    if rules and CONVENTIONS_MARKER not in body:
        raise SyncError(f"{source}: no {CONVENTIONS_MARKER} line, so nothing would route to "
                        f"{', '.join(f'{stem}-conventions' for stem, _, _ in rules)}")
    plan["AGENTS.md"] = render_agents(
        body.replace(CONVENTIONS_MARKER + "\n", conventions_rows(rules)), sha)

    # Opt-in, not opt-out: the map names the personal repos, so a work repo must
    # never receive it by default.
    if cfg.get("estate"):
        # The map's content is the profile's; the core only renders it.
        source = Path(profile_dir) / "seeds" / "context" / "estate.md"
        if not source.is_file():
            raise SyncError(f"target {target}: estate: true, but there is no {source}")
        meta, body = load_doc(source, "id", "description")
        refuse_requires(meta, source)
        body = render_body(body, source, meta, known, bound, plan)
        body = body.replace("<!-- KEYS -->", issue_keys(manifest))
        add_rules(plan, "estate", meta, body, sha)
        # Same opt-in: it names the personal repos too.
        plan[REPO_LIST] = render_repo_list(manifest, sha)

    wanted = list(defaults.get("tier1", [])) + list(defaults.get("tier2", []))
    skipped_ids: set[str] = set()
    rule_files = {p.name: p for p in merged_seeds(
        RULES_DIR, profile_dir, "rules", lambda f: sorted(f.glob("spec-*.md")))}
    for rule_id in wanted:
        if rule_id in excluded:
            skipped_ids.add(rule_id)
            continue
        path = rule_files.get(f"spec-{rule_id}.md")
        if path is None:
            raise SyncError(f"{target}: {PROFILE_NAME} names '{rule_id}' but "
                            f"spec-{rule_id}.md is missing")
        meta, body = load_doc(path, "id", "description")
        unbound = unbound_requirements(meta, path, known, bound)
        if unbound:
            check_body(body, path, meta, known)
            plan.dropped.append((path, unbound))
            continue
        body = render_body(body, path, meta, known, bound, plan)
        scope = meta.get("scope", "*")
        always = bool(meta.get("alwaysApply", False))

        if scope == "*" and not always:
            plan[f"{ON_DEMAND_DIR}/{rule_id}.md"] = render_ondemand(meta, body, sha)
        add_rules(plan, rule_id, meta, body, sha)

    # An exclusion that matches nothing is not a no-op, it is a silent failure to
    # drop the rule that was meant to be dropped.
    unused = excluded - skipped_ids
    if unused:
        raise SyncError(
            f"{target}: exclude names {sorted(unused)}, which matched no rule in "
            f"tier1 or tier2. Fix the spelling or remove the entry."
        )

    # Both tools read SKILL.md, from different roots. VS Code gained workspace
    # skills at .github/skills/<name>/ - verified 2026-09-21 against the shipped
    # agent-customization reference. Rendering one location left four skills
    # invisible to Copilot.
    dropped_skills: set[str] = set()
    factory_skills = []
    for skill_dir in skill_dirs:
        source = skill_dir / "procedure.md"
        meta, body = load_doc(source, "name", "description")
        sessions = seed_sessions(meta, source)
        unbound = unbound_requirements(meta, source, known, bound)
        if unbound:
            check_body(body, source, meta, known)
            plan.dropped.append((source, unbound))
            dropped_skills.add(skill_dir.name)
            continue
        # Bundled assets are what makes a skill a tool rather than a procedure.
        # Without them the SKILL.md references a script that never shipped.
        assets = {asset.relative_to(skill_dir).as_posix(): render_asset(asset, sha)
                  for asset in sorted(p for p in skill_dir.rglob("*") if p.is_file())
                  if asset != source and not GENERATED_DIRS.intersection(asset.parts)}
        if FACTORY in sessions:
            factory_skills.append((skill_dir.name, source, meta, body, assets))
        if INTERACTIVE not in sessions:
            check_body(body, source, meta, known)
            continue
        rendered = render_skill(meta, render_body(body, source, meta, known, bound, plan), sha)
        for root in (t.skill_root for t in TOOLS if t.skill_root):
            plan[f"{root}/{skill_dir.name}/SKILL.md"] = rendered
            for rel, content in assets.items():
                plan[f"{root}/{skill_dir.name}/{rel}"] = content
    # A binding to a skill that is not rendered would point at nothing.
    stranded = sorted(name for name, skill in bound.items() if skill in dropped_skills)
    if stranded:
        raise SyncError(f"{PROFILE_NAME} capabilities: {', '.join(stranded)} bound to a skill "
                        "that is itself dropped for an unbound capability")

    for source in merged_seeds(CONTEXT_DIR, profile_dir, "context",
                               lambda f: sorted(f.glob("*.prompt.md"))):
        meta, body = load_doc(source, "description")
        unbound = unbound_requirements(meta, source, known, bound)
        if unbound:
            check_body(body, source, meta, known)
            plan.dropped.append((source, unbound))
            continue
        plan[f".github/prompts/{source.name}"] = render_prompt(
            meta, render_body(body, source, meta, known, bound, plan), sha)

    for source in merged_seeds(WORKFLOWS_DIR, profile_dir, "workflows",
                               lambda f: sorted(f.glob("*.yml"))):
        plan[f".github/workflows/{source.name}"] = render_workflow(
            source.read_text(encoding="utf-8"), sha
        )

    # Composite actions exist so gate logic is written once. Copying the same
    # twenty lines into three workflows is hand-duplicated and unverified, which
    # this estate treats as a defect rather than a tradeoff.
    for action in merged_seeds(ACTIONS_DIR, profile_dir, "actions",
                               lambda f: sorted(p for p in f.iterdir()
                                                if (p / "action.yml").is_file())):
        plan[f".github/actions/{action.name}/action.yml"] = render_workflow(
            (action / "action.yml").read_text(encoding="utf-8"), sha
        )
        # Rendered beside the action, which calls each by fixed name.
        for script in sorted([*action.glob("*.sh"), *action.glob("*.py")]):
            plan[f".github/actions/{action.name}/{script.name}"] = render_asset(script, sha)

    agents = []
    dropped_agents: set[str] = set()
    for agent_dir in merged_seeds(AGENTS_DIR, profile_dir, "agents",
                                  lambda f: [p for p in f.iterdir() if p.is_dir()]):
        source = agent_dir / "definition.md"
        if not source.exists():
            continue
        meta, body = load_doc(source, "name", "description")
        check_agent_model(meta, source)
        sessions = seed_sessions(meta, source)
        unbound = unbound_requirements(meta, source, known, bound)
        if unbound:
            check_body(body, source, meta, known)
            plan.dropped.append((source, unbound))
            dropped_agents |= {agent_dir.name, meta["name"]}
            continue
        agents.append((agent_dir.name, source, meta, body, sessions,
                       seed_skills(meta, source, {skill[0] for skill in factory_skills})))
    for name, source, meta, body, sessions, _ in agents:
        # Prose naming a dropped agent cannot be checked; this list can.
        gone = sorted(set(meta.get("agents") or []) & dropped_agents)
        if gone:
            raise SyncError(f"{source}: agents: names {gone}, which is dropped for an "
                            "unbound capability")
        if INTERACTIVE in sessions:
            rendered = render_body(body, source, meta, known, bound, plan)
            for tool in TOOLS:
                if tool.agent_path and tool.agent:
                    plan[tool.agent_path.format(name=name)] = tool.agent(
                        meta, rendered, sha, plan.warnings.append)
    factory = cfg.get("factory", False)
    if not isinstance(factory, bool):
        raise SyncError(f"target {target}: factory: must be true or false, not {factory!r}")
    if factory:
        roles = [agent for agent in agents if FACTORY in agent[4]]
        if not roles:
            raise SyncError(f"target {target}: factory: true, but no agent seed lists "
                            f"{FACTORY} in sessions:, so the bundle would hold no role")
        # A requires block dropped here was already listed by the interactive render, or
        # is listed now for a factory-only role; either way once.
        scratch = Plan()
        source = RULES_DIR / "prescriptions.md"
        meta, body = load_doc(source, "id", "description")
        plan[f"{FACTORY_DIR}/prescriptions.md"] = render_agents(
            render_body(body, source, meta, known, bound, scratch, mode=FACTORY), sha)
        for name, source, meta, body, _, skills in roles:
            plan[f"{FACTORY_DIR}/{name}.agent.md"] = render_agent(
                meta, render_body(body, source, meta, known, bound, scratch, mode=FACTORY), sha,
                skills)
        for name, source, meta, body, assets in factory_skills:
            plan[f"{FACTORY_SKILLS_DIR}/{name}/SKILL.md"] = render_skill(
                meta, render_body(body, source, meta, known, bound, scratch, mode=FACTORY), sha)
            for rel, content in assets.items():
                plan[f"{FACTORY_SKILLS_DIR}/{name}/{rel}"] = content
        plan.dropped_sections.extend(d for d in scratch.dropped_sections
                                     if d not in plan.dropped_sections)

    # The destination drops the .sh, because git matches a hook by exact filename.
    # Gate scripts keep theirs - the hook runs <name>.sh for each name in ENABLED_GATES.
    if GITHOOKS_DIR.exists():
        for source in merged_seeds(GITHOOKS_DIR, profile_dir, "githooks",
                                   lambda f: sorted(f.glob("*.sh"))):
            plan[f".githooks/{source.stem}"] = render_asset(source, sha)
        for source in merged_seeds(GITHOOKS_DIR / "gates", profile_dir, "githooks/gates",
                                   lambda f: sorted(f.glob("*.sh"))):
            plan[f".githooks/gates/{source.name}"] = render_asset(source, sha)
        # Shared by gates, so outside gates/: the hook names every unlisted *.sh there as
        # a skipped gate.
        for source in merged_seeds(GITHOOKS_DIR / "lib", profile_dir, "githooks/lib",
                                   lambda f: sorted(f.glob("*.py")) + sorted(f.glob("*.sh"))):
            plan[f".githooks/lib/{source.name}"] = render_asset(source, sha)
        plan[".githooks/gate-config"] = render_gate_config(target, cfg, manifest, sha)
        plan[ENABLED_GATES] = render_enabled_gates(manifest, profile_dir, sha)

    # Ships with spec-response-shape.md. A shape that names a checker only
    # reachable when the profile repository happens to be open is conditionally correct,
    # which is the kind that fails at the wrong moment. Its tests stay in the core - a
    # test file in a repo whose runner never sees it is never run. The entry
    # point imports its shape core and adapters as siblings.
    if RESPONSES_DIR.exists():
        for module in sorted(RESPONSES_DIR.glob("*.py")):
            plan[f".github/scripts/responses/{module.name}"] = render_asset(module, sha)

    # /prime calls it by this path from any repo, so one allowlisted invocation
    # covers every workspace folder.
    primer = ROOT / "prime.py"
    if primer.exists():
        plan[".github/scripts/prime.py"] = render_asset(primer, sha)

    # The one end-of-workstream delete, named by one path in every repo.
    cleaner = ROOT / "cleanup.py"
    if cleaner.exists():
        plan[".github/scripts/cleanup.py"] = render_asset(cleaner, sha)

    # Off unless a target opts in with `hooks: true`, pending the hook design review.
    if cfg.get("hooks", False) and HOOKS_DIR.exists():
        plan.update(render_cursor_hooks(sha, (manifest.get("source") or {}).get("owner"),
                                        profile_dir))

    for entry in merged_seeds(SCRIPTS_DIR, profile_dir, "scripts",
                              lambda f: sorted(p for p in f.iterdir()
                                               if p.name not in GENERATED_DIRS)):
        files = [entry] if entry.is_file() else sorted(
            p for p in entry.rglob("*")
            if p.is_file() and not GENERATED_DIRS.intersection(p.relative_to(entry).parts))
        for asset in files:
            rel = asset.relative_to(entry.parent).as_posix()
            plan[f".github/scripts/{rel}"] = render_asset(asset, sha)
    # The one way to write an exchange log, under its own directory in every repo.
    if EXCHANGE_DIR.exists():
        for module in sorted(EXCHANGE_DIR.glob("*.py")):
            plan[f".github/scripts/exchange/{module.name}"] = render_asset(module, sha)
    hand_owned = never_write(manifest)
    for path_str in plan:
        if path_str in hand_owned:
            raise SyncError(f"Refusing to generate {path_str} - it is hand-owned")
    return plan


# The factory bundle, for a target with `factory: true`. Fixed rather than per target, so
# a bundle the target stops receiving is found as an orphan like any other.
# Never named AGENTS.md: interactive tools load a nested one, and the harness mounts
# prescriptions.md as OpenCode's global AGENTS.md instead.
FACTORY_DIR = "factory/rules"
# Factory skills, beside the bundle and never under SKILL_ROOTS. The harness copies only
# a role's own into its OpenCode config directory.
FACTORY_SKILLS_DIR = "factory/skills"

RENDER_DIRS = (
    ".github/instructions",
    ".github/rules",
    ".github/prompts",
    ".github/workflows",
    ".github/actions",
    ".github/agents",
    ".github/skills",
    ".github/scripts",
    ".github/profile",
    ".githooks",
    ".cursor/rules",
    ".cursor/skills",
    ".cursor/hooks",
    ".claude/rules",
    ".claude/skills",
    ".claude/agents",
    ".agents/skills",
    FACTORY_DIR,
    FACTORY_SKILLS_DIR,
)
# A stamp's prefix from an arbitrary source. Detection uses is_stamped, which accepts any
# source name, so this only stands in for a file some earlier render left behind.
STAMP_MARKER = "generated from some-profile@"


# Rendered files that carry no extension. rglob('*.*') cannot see these, so an
# orphaned hook would survive a rename and keep running.
# .github/gates was the gate list before .githooks/gates/enabled; kept here so a target's
# old copy is found and removed as an orphan.
EXTENSIONLESS_RENDERED = (".githooks", ".github/gates")

# Paths sync once rendered in a format that cannot carry a stamp, so the stamp
# check can never recognise them as its own. Listed exactly; removed if present.
RETIRED = (
    # labels.json moved to .github/scripts/tickets/.
    ".github/skills/file-tickets/scripts/labels.json",
    ".cursor/skills/file-tickets/scripts/labels.json",
    # The repo list moved to .github/profile/repos.json.
    ".github/scripts/tickets/estate.json",
)


def _rendered_candidates(repo: Path):
    """Every file in a directory this tool renders into, generated or not."""
    for sub in RENDER_DIRS:
        base = repo / sub
        if not base.exists():
            continue
        for path in base.rglob("*.*"):
            if path.suffix in (".md", ".mdc", ".yml") + STAMPABLE_ASSETS:
                yield path

    for sub in EXTENSIONLESS_RENDERED:
        target = repo / sub
        if target.is_file():
            yield target
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_file() and not path.suffix:
                    yield path

    for rel in MARKED_JSON:
        if (repo / rel).is_file():
            yield repo / rel


def find_orphans(repo: Path, plan: dict[str, str]) -> list[str]:
    """Previously generated files no longer in the plan.

    Without this, renaming or descoping a rule leaves the old copy in place and
    it keeps loading - the exact drift this tool exists to prevent.
    """
    orphans = []
    for path in _rendered_candidates(repo):
        rel = path.relative_to(repo).as_posix()
        if rel in plan:
            continue
        if is_stamped(path.read_text(encoding="utf-8")):
            orphans.append(rel)
    orphans.extend(rel for rel in RETIRED if rel not in plan and (repo / rel).is_file())
    return sorted(orphans)


def find_foreign(repo: Path, plan: dict[str, str]) -> list[str]:
    """Hand-written files sitting in a directory this tool renders into.

    Never removed: sync did not create them, and deleting a file it does not
    understand is how work in progress disappears. But a first render into a
    repo that already had rules leaves both copies loading at once, and
    reporting nothing is how that goes unnoticed for months.
    """
    foreign = []
    for path in _rendered_candidates(repo):
        rel = path.relative_to(repo).as_posix()
        if rel in plan:
            continue
        if not is_stamped(path.read_text(encoding="utf-8")):
            foreign.append(rel)
    return sorted(foreign)


def resident_lines(repo: Path) -> int:
    """Instruction lines loaded in every session, regardless of what is being edited.

    Counts any instruction file with an applyTo of '**' as resident - it is.
    An earlier version omitted those and under-reported by 76 lines, which is
    precisely the false-reading defect this estate keeps producing.

    Measures residency, not quality. Tracked because resident lines are paid for
    in every session forever, so the number should be known and should not creep.
    """
    total = 0
    for name in ("AGENTS.md", ".github/copilot-instructions.md"):
        path = repo / name
        if path.exists():
            total += len(path.read_text(encoding="utf-8").splitlines())
    inst = repo / ".github" / "instructions"
    if inst.exists():
        for path in inst.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            if "applyTo: '**'" in text:
                total += len(text.splitlines())
    return total


def activate_hooks(repo: Path, write: bool) -> None:
    """Point git at the rendered hooks, and make the file executable.

    Rendering a hook is not the same as git running one. core.hooksPath is local
    config and untracked, so a documented manual step here would be done in two
    repositories of seven. Sync owns it instead.
    """
    hooks = repo / ".githooks"
    if not hooks.is_dir():
        return

    key, wanted = "core.hooksPath", ".githooks"
    current = subprocess.run(
        ("git", "config", "--get", key), cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    if current != wanted:
        if not write:
            print(f"  would set {key}={wanted} (currently {current or 'unset'})")
        else:
            run("git", "config", key, wanted, cwd=repo)
            print(f"  set {key}={wanted}")
    unset_retired_config(repo, write, "gate.deployBranch")

    # A hook without the execute bit is silently ignored on Linux and macOS.
    for path in hooks.iterdir():
        if path.is_file() and not path.suffix and write:
            path.chmod(path.stat().st_mode | 0o111)


EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def identity(manifest: dict) -> dict[str, str]:
    """The commit identity every target is set to, from the profile's top-level identity key.

    Missing or empty refuses: without it, each clone falls back to the machine's global
    config, which may be another identity's address entirely.
    """
    block = manifest.get("identity") or {}
    name = str(block.get("name") or "").strip()
    email = str(block.get("email") or "").strip()
    if not name:
        raise SyncError(f"{PROFILE_NAME} identity.name is missing or empty")
    if not EMAIL.fullmatch(email):
        raise SyncError(f"{PROFILE_NAME} identity.email is not an address: {email!r}")
    return {"name": name, "email": email}


def unset_retired_config(repo: Path, write: bool, key: str) -> int:
    """Remove a gate setting that moved to .githooks/gate-config. A stale key
    reads as if it still governed the gate. Returns 1 when one was present."""
    current = subprocess.run(
        ("git", "config", "--local", "--get", key), cwd=repo, capture_output=True, text=True,
        timeout=GIT_TIMEOUT,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    ).stdout.strip()
    if not current:
        return 0
    if not write:
        print(f"  would unset {key} (currently {current}); .githooks/gate-config replaces it")
    else:
        git_at(repo, "config", "--local", "--unset-all", key)
        print(f"  unset {key}; .githooks/gate-config replaces it")
    return 1


def ensure_identity(repo: Path, write: bool, ident: dict[str, str]) -> int:
    """Set the identity in the clone's local config. Returns how many keys differed.

    The address the identity gate compares against is rendered into .githooks/gate-config,
    not set here. It is separate from user.email because the gate must not
    compare a commit against whatever user.email happens to resolve to - that is the
    value under test.
    """
    differed = unset_retired_config(repo, write, "gate.identityEmail")
    for key, wanted in (("user.name", ident["name"]), ("user.email", ident["email"])):
        current = subprocess.run(
            ("git", "config", "--local", "--get", key), cwd=repo, capture_output=True,
            text=True, timeout=GIT_TIMEOUT,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        ).stdout.strip()
        if current == wanted:
            continue
        differed += 1
        if not write:
            print(f"  would set {key}={wanted} (currently {current or 'unset'})")
        else:
            git_at(repo, "config", "--local", key, wanted)
            print(f"  set {key}={wanted}")
    return differed


def verify_identity(repo: Path, ident: dict[str, str]) -> None:
    """Refuse unless git would author and commit here as ident. Reads git's own answer, so an
    include, a conditional include or a system config overriding the local value is caught."""
    want = ident["email"].lower()
    for role in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        line = git_at(repo, "var", role).strip()
        found = line[line.find("<") + 1:line.find(">")] if "<" in line and ">" in line else line
        if found.lower() != want:
            raise SyncError(f"{role} here is {found!r}, not {ident['email']!r} - an override "
                            "outside the local config wins; nothing committed")


def emit(repo: Path, plan: dict[str, str], write: bool, *, ident: dict[str, str]) -> int:
    # Checked before anything is written. A hand-owned hooks.json is that repo's own guard,
    # and overwriting it drops the guard silently.
    for rel in MARKED_JSON:
        path = repo / rel
        if rel in plan and path.is_file() and not is_stamped(path.read_text(encoding="utf-8")):
            raise SyncError(f"{rel} in {repo} carries no generated-file stamp, so it is hand-owned. "
                            "Refusing to overwrite it: move its hooks into the profile's "
                            "seeds/hooks/ or "
                            "set hooks: false for this target")
    if any(rel in plan for rel in LOCAL_RENDERED) and on_windows_mount(repo.resolve().as_posix()):
        raise SyncError(f"{repo} is a Windows folder under /mnt/, and its hooks would name this "
                        "Linux interpreter, which Cursor on Windows cannot launch. Run sync.py "
                        "from Windows for this checkout")
    if write:
        for rel in LOCAL_RENDERED:
            if rel in plan:
                check_hooks_launch(rel, plan[rel], os.name == "nt")
    changed = 0
    for rel, content in sorted(plan.items()):
        path = repo / rel
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == content:
            continue
        changed += 1
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"  wrote {rel}")
        else:
            print(f"\n--- {rel}")
            diff = difflib.unified_diff(
                current.splitlines(), content.splitlines(), "current", "rendered", lineterm=""
            )
            for line in list(diff)[:40]:
                print(line)
    activate_hooks(repo, write)
    # Local config, like core.hooksPath: a fresh CI checkout never has it, so it is
    # reported but not counted, or --check would fail every drift run.
    ensure_identity(repo, write, ident)
    return changed


def ensure_ignored(repo: Path, write: bool, probe: str, rule: str, why: str) -> int:
    """Append rule to .gitignore unless git already ignores probe. Returns 1 when a change is
    needed, so --check fails on it. A rule the repo already has in its own form counts."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    found = subprocess.run(("git", "check-ignore", "-q", probe), cwd=repo,
                           capture_output=True, text=True, env=env, timeout=60)
    if found.returncode == 0:
        return 0
    if found.returncode != 1:
        raise SyncError(f"git check-ignore failed in {repo}: {found.stderr.strip()}")
    if not write:
        print(f"  would add {rule} to .gitignore")
        return 1
    path = repo / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = "" if not text or text.endswith("\n") else "\n"
    path.write_text(text + sep + f"\n# {why}\n{rule}\n", encoding="utf-8", newline="\n")
    print(f"  added {rule} to .gitignore")
    return 1


def ensure_scratch_ignored(repo: Path, write: bool) -> int:
    """scratch/ is where the prescriptions send working files; unignored, they get committed.

    Seven repos carried a hand-added line and one did not, with nothing to notice
    (2026-09-28).
    """
    return ensure_ignored(repo, write, "scratch/probe", "scratch/",
                          "Working files - kept out of commits.")


def ensure_pycache_ignored(repo: Path, write: bool) -> int:
    """Rendered scripts are Python and run in every target, so every target makes bytecode.

    One repo had no rule, and one run of a rendered script left a dirty tree that failed its
    next rollout (2026-09-30). Probed at the depth the scripts render to.
    """
    return ensure_ignored(repo, write, ".github/scripts/tickets/__pycache__/probe.pyc",
                          "__pycache__/", "Bytecode from rendered scripts.")


def ensure_claude_local_ignored(repo: Path, write: bool) -> int:
    """Claude Code writes its own permission grants to .claude/settings.local.json. It is
    never rendered, never an orphan and never removed here - only kept out of commits."""
    return ensure_ignored(repo, write, ".claude/settings.local.json",
                          ".claude/settings.local.json",
                          "Claude Code's per-machine settings - kept out of commits.")


CURSOR_BLANKET = {".cursor/", ".cursor", "/.cursor/", "/.cursor"}
CURSOR_RULES = (
    "# Cursor: rendered output is tracked. Anything else Cursor writes here stays local -",
    "# cli.json and mcp.json carry machine and credential state.",
    ".cursor/*",
    "!.cursor/rules/",
    "!.cursor/skills/",
    "!.cursor/hooks/",
)
# The old re-include of hooks.json, removed now the file is per machine.
CURSOR_RETIRED = {"!.cursor/hooks.json"}
CURSOR_PROBES_TRACKED = (".cursor/rules/probe.mdc", ".cursor/skills/probe/SKILL.md",
                         ".cursor/hooks/probe/hook.py")
CURSOR_PROBES_LOCAL = (".cursor/mcp.json", ".cursor/cli.json", ".cursor/hooks.json")


def _git_ignores(repo: Path, rel: str) -> bool:
    """Whether the rules ignore rel. --no-index: a tracked file always reads as not ignored,
    so hooks.json still in the index before --write untracks it looked mis-ignored."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    found = subprocess.run(("git", "check-ignore", "-q", "--no-index", rel), cwd=repo,
                           capture_output=True, text=True, env=env, timeout=60)
    if found.returncode not in (0, 1):
        raise SyncError(f"git check-ignore failed in {repo}: {found.stderr.strip()}")
    return found.returncode == 0


def _cursor_misignored(repo: Path) -> list[str]:
    return ([rel for rel in CURSOR_PROBES_TRACKED if _git_ignores(repo, rel)]
            + [rel for rel in CURSOR_PROBES_LOCAL if not _git_ignores(repo, rel)])


def ensure_cursor_tracked(repo: Path, write: bool) -> int:
    """Rendered .cursor/ output is tracked, and nothing else under .cursor/ is.

    Eight of nine targets carried a hand-added blanket ignore from 2026-09-18 (c76a8ba). A
    re-include below it cannot work - git never descends into an excluded directory - so the
    blanket line is removed. Returns 1 when a change is
    needed, so --check fails on it. Refuses if any other rule still gets it wrong.
    """
    path = repo / ".gitignore"
    original = path.read_bytes() if path.exists() else None
    lines = (original or b"").decode("utf-8").splitlines()
    kept: list[str] = []
    for line in lines:
        if line.strip() in CURSOR_BLANKET:
            continue
        if line.strip() in CURSOR_RETIRED:
            continue
        kept.append(line)
    present = {line.strip() for line in kept}
    has_rules = all(rule in present for rule in CURSOR_RULES if not rule.startswith("#"))

    if kept == lines and has_rules:
        wrong = _cursor_misignored(repo)
        if wrong:
            raise SyncError(f"a .gitignore rule sync does not manage mis-ignores {', '.join(wrong)} "
                            f"in {repo}. .cursor/rules/, skills/ and hooks must be tracked and "
                            "the rest of .cursor/ ignored; fix it by hand")
        return 0
    if not write:
        print("  would replace the .cursor/ ignore with rules that track rendered output")
        return 1
    if not has_rules:
        while kept and not kept[-1].strip():
            kept.pop()
        kept += ([""] if kept else []) + list(CURSOR_RULES)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    wrong = _cursor_misignored(repo)
    if wrong:
        if original is None:
            path.unlink()
        else:
            path.write_bytes(original)
        raise SyncError(f"a .gitignore rule sync does not manage still mis-ignores "
                        f"{', '.join(wrong)} in {repo}; .gitignore restored. .cursor/rules/, "
                        "skills/ and hooks must be tracked and the rest of .cursor/ ignored")
    print("  replaced the .cursor/ ignore with rules that track rendered output")
    return 1


def ensure_hooks_local(repo: Path, write: bool) -> int:
    """Untrack a committed hooks.json, keeping the file. Returns 1 when a change is
    needed, so --check fails on a target that still tracks it."""
    changed = 0
    for rel in LOCAL_RENDERED:
        if not git_at(repo, "ls-files", "--", rel).strip():
            continue
        changed += 1
        if write:
            git_at(repo, "rm", "--cached", "--quiet", "--", rel)
            print(f"  untracked {rel}; it is rendered per machine")
        else:
            print(f"  would untrack {rel}")
    return changed


def self_config(manifest: dict) -> dict:
    """This repo's own render config.

    Deliberately not the target's. Inheriting it meant a target's `exclude:`
    decided what applied here, so this repo's rendered output was the union of
    whichever targets had been rendered last, carrying mixed stamps. A drift
    check cannot mean anything until the expected output is one fixed thing.
    """
    cfg = dict(manifest.get("source") or {})
    cfg.setdefault("estate", True)
    cfg.pop("exclude", None)
    cfg["profile_repo"] = True
    return cfg


def git_at(repo: Path, *args: str, timeout: float = GIT_TIMEOUT) -> str:
    """git in a target. GIT_* is stripped so a caller running inside a hook
    cannot point these commands at its own repository instead."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(("git", *args), cwd=repo, capture_output=True, text=True,
                                env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SyncError(f"git {' '.join(args)} timed out after {timeout:.0f}s") from exc
    if result.returncode != 0:
        raise SyncError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _now() -> datetime:
    return datetime.now(timezone.utc)


def write_lock(lock: dict, path: Path) -> None:
    """Write in one step, so a reader never sees half a lock."""
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock), encoding="utf-8")
    os.replace(tmp, path)


def read_lock(path: Path) -> dict | None:
    """The held lock, or None if there is none. Raises SyncError naming the
    holder unless the lock is stale. An unreadable lock is never guessed at."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        lock = json.loads(text)
        started = datetime.fromisoformat(lock["started"])
        heartbeat = datetime.fromisoformat(lock["heartbeat"])
        holder = f"pid {int(lock['pid'])}, subject {lock['subject']!r}"
    except (ValueError, KeyError, TypeError) as exc:
        raise SyncError(
            f"{path} exists but cannot be read ({exc}), so it is treated as held. "
            "If no rollout is running, re-run with --break-lock."
        ) from exc
    started = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
    heartbeat = heartbeat if heartbeat.tzinfo else heartbeat.replace(tzinfo=timezone.utc)
    now = _now()
    if now - started > LOCK_MAX_AGE or now - heartbeat > LOCK_HEARTBEAT_TIMEOUT:
        print(f"[WARN] replacing a stale rollout lock ({holder}, started {lock['started']}, "
              f"last heartbeat {lock['heartbeat']})")
        return None
    raise SyncError(
        f"a rollout is already running: {holder}, started {lock['started']}, last heartbeat "
        f"{lock['heartbeat']}. If that process is dead, re-run with --break-lock."
    )


def rollout_target(name: str, cfg: dict, root: Path, defaults: dict, sha: str,
                   manifest: dict, subject: str, profile_dir: Path) -> str:
    """Render and commit one target. Returns what was done; raises SyncError on a
    refusal or failure, so the caller moves on. Pushing is a separate phase."""
    repo = root / name
    if not (repo / ".git").exists():
        raise SyncError(f"{repo} is not a git repository")
    if git_at(repo, "status", "--porcelain").strip():
        raise SyncError("working tree is dirty - commit or stash first")
    branch = cfg.get("branch", "main")
    current = git_at(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if current != branch:
        raise SyncError(f"on branch {current!r}, {PROFILE_NAME} says {branch!r}")
    # Unknown is not current: no upstream and a failed fetch refuse like being behind does.
    # The rollout never pulls - that would change another repo's working tree.
    try:
        git_at(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except SyncError as exc:
        raise SyncError(f"{branch!r} has no upstream, so whether it is current cannot be checked. "
                        f"Set one with 'git branch -u origin/{branch}' there") from exc
    try:
        git_at(repo, "fetch", "--quiet", timeout=FETCH_TIMEOUT)
    except SyncError as exc:
        raise SyncError(f"git fetch failed, so whether it is current cannot be checked: {exc}") from exc
    behind = git_at(repo, "rev-list", "--count", "HEAD..@{u}").strip()
    if behind != "0":
        raise SyncError(f"{behind} commit(s) behind its upstream; run 'git pull --ff-only' there first")

    plan = build_plan(name, cfg, defaults, sha, manifest, profile_dir)
    report_drops(plan)
    ident = identity(manifest)
    emit(repo, plan, True, ident=ident)
    verify_identity(repo, ident)
    ensure_scratch_ignored(repo, True)
    ensure_pycache_ignored(repo, True)
    ensure_claude_local_ignored(repo, True)
    ensure_cursor_tracked(repo, True)
    ensure_hooks_local(repo, True)
    orphans = find_orphans(repo, plan)
    for rel in orphans:
        (repo / rel).unlink()

    hidden = hidden_plan_paths(repo, plan)
    if hidden:
        raise SyncError(f"its .gitignore hides {len(hidden)} rendered file(s), so they would never "
                        f"be committed; nothing committed: {', '.join(hidden)}")

    allowed = set(plan) | set(orphans) | {".gitignore"}
    changed = [entry[3:] for entry in
               git_at(repo, "status", "--porcelain=v1", "-z", "-uall").split("\0") if entry]
    if not changed:
        return "already current"
    stray = sorted(rel for rel in changed if rel not in allowed)
    if stray:
        raise SyncError(f"changed outside the render plan, nothing committed: {', '.join(stray)}")

    # A local file's untracking is already staged, and git add refuses an ignored path.
    # With no paths, add -A would stage the whole tree.
    staged = [rel for rel in changed if rel not in LOCAL_RENDERED]
    if staged:
        git_at(repo, "add", "-A", "--", *staged)
    git_at(repo, "commit", "--quiet", "-m", f"Sync rules: {subject}", "-m",
           f"From {source_repo(manifest)}@{sha}.")
    commit = git_at(repo, "rev-parse", "--short", "HEAD").strip()
    return f"committed {commit} ({len(changed)} file(s))"


def hidden_plan_paths(repo: Path, plan: dict[str, str]) -> list[str]:
    """Rendered files the target's own .gitignore hides. A machine-local file is meant to be."""
    wanted = sorted(rel for rel in plan if rel not in LOCAL_RENDERED)
    if not wanted:
        return []
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # NUL-separated bytes: text mode on Windows sent 'path\r', which exact-name rules never match.
    result = subprocess.run(("git", "check-ignore", "--stdin", "-z"), cwd=repo,
                            input="\0".join(wanted).encode("utf-8") + b"\0",
                            capture_output=True, env=env, timeout=GIT_TIMEOUT)
    if result.returncode not in (0, 1):
        raise SyncError(f"git check-ignore failed: {result.stderr.decode(errors='replace').strip()}")
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def push_target(repo: Path) -> str:
    if git_at(repo, "rev-list", "--count", "@{u}..HEAD").strip() == "0":
        return "nothing to push"
    git_at(repo, "push", "--quiet", timeout=PUSH_TIMEOUT)
    # The push exit code is not the outcome; the remote holding the commit is.
    unpushed = git_at(repo, "rev-list", "--count", "@{u}..HEAD").strip()
    if unpushed != "0":
        raise SyncError(f"{unpushed} commit(s) are still not on the remote after the push")
    return "pushed"


def total_memory() -> int | None:
    """Physical memory in bytes, read only. None where it cannot be read."""
    if sys.platform == "win32":
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                (field, ctypes.c_ulonglong) for field in (
                    "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                    "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]

        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.ullTotalPhys if ok else None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def probe_capacity() -> int | None:
    cpus, memory = os.cpu_count(), total_memory()
    if not cpus or not memory:
        return None
    return max(1, min(cpus // CORES_PER_PUSH, memory // MEMORY_PER_PUSH, PARALLEL_MAX))


def probe_report(manifest: dict) -> int:
    """--probe-capacity: what a rollout would push at, and what is stored. Writes nothing."""
    cpus, memory = os.cpu_count(), total_memory()
    print(f"cores: {cpus or 'could not be read'}")
    print(f"memory: {f'{memory / 1024 ** 3:.1f} GiB' if memory else 'could not be read'}")
    probed = probe_capacity()
    default = (manifest.get("rollout") or {}).get("parallel_default")
    if probed:
        print(f"probed: {probed} at a time ({CORES_PER_PUSH} cores and "
              f"{MEMORY_PER_PUSH // 1024 ** 3} GiB per push)")
    else:
        print(f"probed: capacity could not be read, so the manifest default applies: "
              f"{default} at a time")
    stored = subprocess.run(("git", "config", "--get", PARALLEL_KEY), cwd=ROOT, capture_output=True,
                            text=True, timeout=GIT_TIMEOUT).stdout.strip()
    if stored:
        print(f"stored: {PARALLEL_KEY}={stored} - what --rollout --push uses on this machine")
    else:
        print(f"stored: nothing yet - the first --rollout --push stores {probed or default}")
    return 0


def rollout_parallel(manifest: dict) -> int:
    """How many targets push at once. Read-only probe on first use, then git config."""
    stored = subprocess.run(("git", "config", "--get", PARALLEL_KEY), cwd=ROOT, capture_output=True,
                            text=True, timeout=GIT_TIMEOUT).stdout.strip()
    if stored:
        if not stored.isdigit() or not 1 <= int(stored) <= PARALLEL_MAX:
            raise SyncError(f"git config {PARALLEL_KEY} is {stored!r}; it must be a whole number "
                            f"from 1 to {PARALLEL_MAX}. Fix it, or unset it to probe again.")
        return int(stored)
    default = (manifest.get("rollout") or {}).get("parallel_default")
    if isinstance(default, bool) or not isinstance(default, int) or not 1 <= default <= PARALLEL_MAX:
        raise SyncError(f"{PROFILE_NAME} rollout.parallel_default must be a whole number from 1 "
                        f"to {PARALLEL_MAX}, not {default!r}")
    probed = probe_capacity()
    chosen = probed or default
    run("git", "config", "--local", PARALLEL_KEY, str(chosen))
    how = (f"probed: {os.cpu_count()} cores, {total_memory() // 1024 ** 3} GiB" if probed
           else "capacity could not be read, so the manifest default")
    print(f"[INFO] set {PARALLEL_KEY}={chosen} for this machine ({how}). "
          f"`git config --unset {PARALLEL_KEY}` probes again.")
    return chosen


def rollout(args: argparse.Namespace, manifest: dict, defaults: dict) -> int:
    """Render and commit every live target in one run.

    Everything that can refuse for the whole estate does so before any target is
    touched. After that, one target's failure is reported and the next still runs.
    """
    subject = args.rollout.strip()
    if not subject or "\n" in subject or "\r" in subject:
        raise SyncError("--rollout needs a one-line subject for the commit message")
    if args.target or args.self_only or args.write or args.check or args.no_fetch:
        raise SyncError("--rollout takes no target, --self, --write, --check or --no-fetch")

    profile_dir = resolve_profile(args.profile)
    source = source_repo(manifest)
    sha = source_sha(True, profile_dir)
    ahead = run("git", "rev-list", "--count", "origin/main..HEAD")
    if ahead != "0":
        raise SyncError(
            f"{source} is {ahead} commit(s) ahead of origin/main. Push it first - a stamp "
            "must name a commit that the other clones and the drift checks can see."
        )
    self_plan = build_plan(source, self_config(manifest), defaults, None, manifest, profile_dir)
    pending = sorted(
        rel for rel, content in self_plan.items()
        if rel not in never_write(manifest) and rel not in LOCAL_RENDERED
        and (not (profile_dir / rel).is_file()
             or (profile_dir / rel).read_text(encoding="utf-8") != content)
    )
    if pending:
        raise SyncError(
            f"{source} has its own render pending, so targets would receive rules this repo "
            f"does not follow yet. Render it with --self --write, commit and push: "
            f"{', '.join(pending)}"
        )
    if args.push and not shutil.which("shellcheck"):
        raise SyncError(
            "shellcheck is not on PATH, and every target's pre-push gate needs it. If it is "
            "installed, this shell's PATH is stale - open a new terminal."
        )
    if args.push:
        profile_module("ghcli", profile_dir, "--push")
    workers = rollout_parallel(manifest) if args.push else 0

    lock_path = profile_dir / ROLLOUT_LOCK
    if args.break_lock and lock_path.exists():
        print(f"[WARN] --break-lock: removing {lock_path}: "
              f"{lock_path.read_text(encoding='utf-8', errors='replace').strip()}")
        lock_path.unlink()
    read_lock(lock_path)
    lock = {"pid": os.getpid(), "started": _now().isoformat(timespec="seconds"),
            "heartbeat": _now().isoformat(timespec="seconds"), "subject": subject}
    write_lock(lock, lock_path)

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)  # redirected to a log, it was empty until exit
        ok = failed = 0
        print(f"{source}@{sha} rollout: {subject}" + (" (with push)" if args.push else ""))

        def beat() -> None:
            lock["heartbeat"] = _now().isoformat(timespec="seconds")
            write_lock(lock, lock_path)

        ready = []
        for name, cfg in (manifest.get("targets") or {}).items():
            cfg = cfg or {}
            if cfg.get("skip"):
                print(f"{name}: skipped - {cfg['skip']}")
                continue
            try:
                line = rollout_target(name, cfg, args.root, defaults, sha, manifest, subject,
                                      profile_dir)
            except SyncError as exc:
                print(f"{name}: FAILED - {exc}")
                failed += 1
            else:
                if args.push:
                    ready.append((name, line))
                else:
                    print(f"{name}: ok, {line}, not pushed")
                    ok += 1
            beat()

        if ready:
            print(f"pushing {len(ready)} target(s), {workers} at a time")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(push_target, args.root / name): (name, line)
                           for name, line in ready}
                for future in as_completed(futures):
                    name, line = futures[future]
                    try:
                        print(f"{name}: ok, {line}, {future.result()}")
                        ok += 1
                    except SyncError as exc:
                        print(f"{name}: FAILED - {line}, then {exc}")
                        failed += 1
                    beat()
        if args.push:
            dispatch_drift(manifest, profile_dir)
        print(f"ROLLOUT COMPLETE: {ok} ok, {failed} failed")
    finally:
        lock_path.unlink(missing_ok=True)
    return 1 if failed else 0


def profile_module(name: str, profile_dir: Path, flag: str):
    """Import a module the profile ships, for the one flag that needs it.

    The core imports no profile code at load, so it runs with none. A module is looked for
    at the profile root, under seeds/scripts/, and in each folder directly under that;
    exactly one copy must exist.
    """
    base = Path(profile_dir)
    scripts = base / "seeds" / "scripts"
    places = [base, scripts]
    if scripts.is_dir():
        places += sorted(p for p in scripts.iterdir() if p.is_dir())
    found = [place for place in places if (place / f"{name}.py").is_file()]
    if not found:
        raise SyncError(f"{flag} needs {name}.py from the profile, and the profile ships none. "
                        f"Add it under {scripts}, or run without {flag}.")
    if len(found) > 1:
        raise SyncError(f"{flag}: {name}.py is in more than one place: "
                        f"{', '.join(str(p) for p in found)}. Keep one.")
    if str(found[0]) not in sys.path:
        sys.path.insert(0, str(found[0]))
    return importlib.import_module(name)


def dispatch_drift(manifest: dict, profile_dir: Path) -> None:
    """The estate check runs once the targets hold the render, never on the push before
    it. Reporting only: the rollout has finished, so a failure here warns."""
    ghcli = profile_module("ghcli", profile_dir, "--push")
    source = manifest.get("source") or {}
    repo = f"{source.get('owner')}/{source.get('repo')}"
    try:
        ghcli.run("workflow", "run", "rules-drift.yml", "--repo", repo, timeout=60)
    except (ghcli.GhError, ghcli.estate_data.EstateError) as exc:
        print(f"[WARN] drift check not triggered: {exc}")
        return
    print(f"drift check triggered: https://github.com/{repo}/actions/workflows/rules-drift.yml")


def runner(args: argparse.Namespace, manifest: dict) -> int:
    """--runner: hand the profile's runner module the action and the repos it governs."""
    rs = profile_module("runner_switch", resolve_profile(args.profile), "--runner")
    repos = [repo["github"] for repo in repo_list(manifest)["repos"]]
    try:
        return rs.run(args.runner, manifest, repos, args.root, git_at)
    except rs.SwitchError as exc:
        raise SyncError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a profile into a consuming repo.")
    parser.add_argument(
        "target", nargs="?", help="repo name as it appears in profile.yaml; omit with --self"
    )
    parser.add_argument(
        "--profile", type=Path, default=None,
        help="directory holding profile.yaml (default: this script's own directory)",
    )
    parser.add_argument("--write", action="store_true", help="apply changes (default: diff only)")
    parser.add_argument("--root", type=Path, default=None,
                        help="directory holding repos (default: the profile's parent)")
    parser.add_argument(
        "--self", dest="self_only", action="store_true", help="render this repo instead of a target"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare only and exit 1 on any difference. Never writes. For CI",
    )
    parser.add_argument(
        "--no-fetch", action="store_true", help="skip the origin freshness check (offline)"
    )
    parser.add_argument(
        "--rollout", metavar="SUBJECT",
        help="render and commit every live target as 'Sync rules: SUBJECT'. Does not push",
    )
    parser.add_argument("--push", action="store_true", help="with --rollout: push each target")
    parser.add_argument(
        "--break-lock", action="store_true",
        help="with --rollout: remove a rollout lock of any age first",
    )
    parser.add_argument(
        "--probe-capacity", action="store_true",
        help="read-only: show how many pushes --rollout --push would run at once, and why",
    )
    parser.add_argument(
        "--runner", choices=("status", "apply"),
        help="profile.yaml actions.runner: report every repo against it, or apply it",
    )
    parser.add_argument(
        "--check-core", action="store_true",
        help="offline: exit 1 unless the profile's core/ is exactly what core/VENDORED records",
    )
    parser.add_argument(
        "--vendor-core", metavar="SOURCE",
        help="replace the profile's core/ with <owner>/<repo>@<vX.Y.Z or full SHA>, "
             "fetched over HTTPS; refuses a core/ with local edits",
    )
    parser.add_argument(
        "--check-updates", action="store_true",
        help="list release tags newer than core/VENDORED's. Changes nothing. "
             "Exit 0 up to date, 1 refused, 2 newer available, 3 could not check",
    )
    args = parser.parse_args(argv)
    write = args.write and not args.check

    try:
        if sum((args.vendor_core is not None, args.check_core, args.check_updates)) > 1:
            raise SyncError("--vendor-core, --check-core and --check-updates are separate runs")
        if args.check_updates:
            import vendor
            return vendor.updates_report(resolve_profile(args.profile) / vendor.CORE_DIR)
        if args.vendor_core is not None:
            import vendor
            profile_dir = resolve_profile(args.profile)
            if profile_dir == ROOT:
                raise SyncError(f"{profile_dir} is this core's own folder; vendoring a core "
                                "into itself makes no sense. Pass --profile <profile folder>.")
            return vendor.vendor_report(profile_dir, args.vendor_core)
        if args.check_core:
            import vendor
            return vendor.check_report(resolve_profile(args.profile) / vendor.CORE_DIR)
        manifest = load_profile(resolve_profile(args.profile))
        defaults = manifest.get("defaults") or {}
        if args.root is None:
            args.root = resolve_profile(args.profile).parent

        if args.probe_capacity:
            return probe_report(manifest)
        if args.runner:
            return runner(args, manifest)
        if args.rollout is not None:
            return rollout(args, manifest, defaults)
        if args.push or args.break_lock:
            raise SyncError("--push and --break-lock only apply to --rollout")

        if args.self_only:
            if args.target:
                raise SyncError("--self takes no target")
            cfg = self_config(manifest)
            name = source_repo(manifest)
            repo = resolve_profile(args.profile)
        else:
            if not args.target:
                raise SyncError("a target is required unless --self is given")
            targets = manifest.get("targets") or {}
            if args.target not in targets:
                raise SyncError(f"'{args.target}' is not in {PROFILE_NAME}")
            cfg = targets[args.target] or {}
            if cfg.get("skip"):
                raise SyncError(f"'{args.target}' is marked skip in {PROFILE_NAME}")
            name = args.target
            repo = args.root / args.target
            if not (repo / ".git").exists():
                raise SyncError(f"{repo} is not a git repository")

        profile_dir = resolve_profile(args.profile)
        sha = source_sha(not args.no_fetch, profile_dir)
        # The profile rendering itself stamps no SHA - see STAMP_UNPINNED. A target keeps it.
        plan = build_plan(name, cfg, defaults, None if args.self_only else sha, manifest,
                          profile_dir)
        report_drops(plan)
        if args.self_only:
            plan = {k: v for k, v in plan.items() if k not in never_write(manifest)}

        print(f"{source_repo(manifest)}@{sha} -> {name}  ({len(plan)} files)")
        # Orphan and foreign detection always use the unfiltered plan. A path
        # skipped for comparison is still a file this tool owns, and treating
        # it as an orphan would delete it on the next write.
        full_plan = plan
        if args.check:
            plan = {k: v for k, v in plan.items() if k not in LOCAL_RENDERED}
        ident = identity(manifest)
        changed = emit(repo, plan, write, ident=ident)
        changed += ensure_scratch_ignored(repo, write)
        changed += ensure_pycache_ignored(repo, write)
        changed += ensure_claude_local_ignored(repo, write)
        changed += ensure_cursor_tracked(repo, write)
        changed += ensure_hooks_local(repo, write)

        # This repo is the first target, not an exception to its own rules. The
        # seed files stay inert; the rendered output applies here as anywhere
        # else, so a rule is only in force once it has survived a render.
        # Only under the profile this core sits in, as core/: another profile renders its
        # own targets and must not stamp this checkout with its source name.
        if not args.self_only and profile_dir == ROOT.parent:
            self_plan = build_plan(source_repo(manifest), self_config(manifest), defaults, None,
                                   manifest, profile_dir)
            self_plan = {k: v for k, v in self_plan.items() if k not in never_write(manifest)
                         and not (args.check and k in LOCAL_RENDERED)}
            self_changed = emit(profile_dir, self_plan, write, ident=ident)
            if self_changed:
                print(f"  {source_repo(manifest)} self: {self_changed} file(s)")

        orphans = find_orphans(repo, full_plan)
        for rel in orphans:
            if write:
                (repo / rel).unlink()
                print(f"  removed orphan {rel}")
            else:
                print(f"  orphan (would remove): {rel}")

        print(f"\nresident footprint: {resident_lines(repo)} lines")

        foreign = find_foreign(repo, full_plan)
        if foreign:
            print(f"\n[WARN] {len(foreign)} hand-written file(s) in rendered directories:")
            for rel in foreign:
                print(f"  {rel}")
            print("  Not touched - sync did not create them. They load alongside the")
            print("  rendered rules, so reconcile or remove them by hand.")

        if args.check:
            # Foreign files are deliberately not a failure: sync does not own them.
            if changed or orphans:
                print(
                    f"\n[FAIL] {changed} file(s) differ and {len(orphans)} orphan(s) remain. "
                    "The committed output is not what this source renders."
                )
                return 1
            print("\n[OK] committed output matches a render at this SHA")
            return 0

        if not changed and not orphans:
            print("[OK] up to date")
        elif write:
            print(f"[OK] {changed} written, {len(orphans)} removed - review before committing")
        else:
            print(f"[INFO] {changed} would change, {len(orphans)} would be removed")
        return 0
    except SyncError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
