#!/usr/bin/env python3
################################################################################
# File: sync.py
# Path: {PROJECT_ROOT}/sync.py
# Created by: Ryan Severe
# Created: 2026-09-14
# Last Updated: 2026-11-28
# Description: Renders the core and a profile's seeds into a consuming repository's
#              per-tool formats and stamps each output with the source SHA.
#              Dry-run by default; --write applies. Never writes Tier 3.
#              --rollout renders and commits every live target in one run.
#              --pull renders a profile's newest release tag into the repository
#              it runs in; --print-source-sha names the commit a release tags.
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
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

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
# What a GitHub owner or repository name may hold. A space or / breaks `owner/repo`.
GITHUB_NAME = re.compile(r"[A-Za-z0-9_.-]+")
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
    "answers": dict, "gate_config_dir": str, "tracked": dict,
    # What gate_lists.py builds the one-way gates' pattern files from: the owner's own
    # repository names, a name for the profile, and further literal strings kept by hand.
    "personal": list, "profile_name": str, "leak_extra": list,
    # Which rows of TOOLS render, for every target. Absent, every row does.
    "tools": list,
    # {skip_allowed: [{ref: <regex>, gates: [<gate>, ...]}], rerun: [<gate>, ...]}: refs on
    # which the report check accepts a skipped required gate (report-skip= lines), and the
    # core gates CI runs again from the vendored release (report-rerun= lines).
    "gate_report": dict,
    # The title-prefix hook's vocabulary, replacing the core's default whole. Each entry is
    # {prefix, rule} or {label, pattern, rule}, the shape of hooks/title-prefix/prefixes.yaml.
    "title_prefixes": list,
}
# Keys whose list elements must each be a non-empty string.
STRING_LIST_KEYS = ("personal", "leak_extra")
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
# A file-sync client watching scratch/ can hold the lock file for a moment, and the rename
# then raises PermissionError. Retry briefly: 5 attempts, 0.1 s apart, about 0.4 s in all.
LOCK_REPLACE_ATTEMPTS = 5
LOCK_REPLACE_SLEEP = 0.1
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
# --pull renders one target from a release's own sync.py; it runs no gates.
PULL_RENDER_TIMEOUT = 10 * 60
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
# Single files directly under seeds/, read by name rather than merged as a folder.
SEED_FILES = ("permissions.yaml",)


def check_seed_kinds(profile_dir: Path) -> None:
    """Refuse a folder under <profile>/seeds/ that is not a seed kind.

    Without this a typo such as seeds/skill/ renders nothing and says nothing - the same
    failure load_profile refuses for an unknown key.
    """
    base = Path(profile_dir) / "seeds"
    if not base.is_dir():
        return
    for entry in sorted(base.iterdir()):
        if entry.name in SEED_FILES and entry.is_file():
            continue
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
        if key in STRING_LIST_KEYS:
            for item in value or []:
                if not isinstance(item, str) or not item.strip():
                    # The entry is never quoted: these lists are secret-adjacent.
                    raise SyncError(f"{path}: every entry under {key!r} must be a "
                                    "non-empty string")
    check_tracked(data, path)
    check_repo_names(data, path)
    check_target_kinds(data, path)
    selected_tools(data, str(path))
    gate_report_skips(data, str(path))
    gate_report_rerun(data, str(path))
    title_prefixes(data, str(path))
    return data


def check_tracked(data: dict, path: Path) -> None:
    """Refuse a tracked entry with no reason, or one that is also a target, a repository
    deliberately left out, or the source: a repository is rendered into, or never is."""
    elsewhere = {
        "targets": set(data.get("targets") or {}),
        "not_onboarded": set(data.get("not_onboarded") or {}),
        "source.repo": {(data.get("source") or {}).get("repo")} - {None},
    }
    for name, cfg in (data.get("tracked") or {}).items():
        reason = cfg.get("reason") if isinstance(cfg, dict) else None
        if not isinstance(reason, str) or not reason.strip():
            raise SyncError(f"{path}: tracked: {name!r} needs a non-empty reason")
        for place, names in elsewhere.items():
            if name in names:
                raise SyncError(f"{path}: {name!r} is under both tracked: and {place}:. "
                                "A repository is rendered into or tracked, never both")


def check_repo_names(data: dict, path: Path) -> None:
    """Refuse a target or tracked `owner:` or `remote:` that is not one GitHub name part.

    A `/` in `remote:` would build `owner/a/b`, a repository that does not exist, and
    nothing else would notice until the first GitHub call."""
    for section in ("targets", "tracked"):
        for name, cfg in (data.get(section) or {}).items():
            if not isinstance(cfg, dict):
                continue
            for key in ("owner", "remote"):
                if key not in cfg:
                    continue
                value = cfg[key]
                if not isinstance(value, str) or not GITHUB_NAME.fullmatch(value):
                    raise SyncError(
                        f"{path}: {section}: {name!r} {key}: {value!r} is not allowed. "
                        "Use letters, digits, - _ and ., with no spaces or /. "
                        "Set owner: for a repository under another owner")


TARGET_KIND_FOLDER = "folder"


def check_target_kinds(data: dict, path: Path) -> None:
    """Refuse a target `kind:` other than `folder`. A target with no kind is a git repository."""
    for name, cfg in (data.get("targets") or {}).items():
        if isinstance(cfg, dict) and "kind" in cfg and cfg["kind"] != TARGET_KIND_FOLDER:
            raise SyncError(f"{path}: targets: {name!r} kind: {cfg['kind']!r} is not allowed. "
                            f"The only kind is {TARGET_KIND_FOLDER!r}, a plain folder that is "
                            "not a git repository; leave kind out for a repository")


def is_folder_target(cfg: dict) -> bool:
    """Whether a target's manifest entry declares a plain folder, not a git repository."""
    return (cfg or {}).get("kind") == TARGET_KIND_FOLDER


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


def refuse_dirty_source() -> None:
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


def source_sha(fetch: bool, profile_dir: Path) -> str:
    refuse_dirty_source()
    ensure_current(fetch, profile_dir)
    return source_commit(profile_dir)[:STAMP_SHA_LENGTH]


def source_commit(profile_dir: Path) -> str:
    """The full sha of the newest commit that touched anything this renders from: the
    commit a render stamps, and the one a rules release tag must point at."""
    # Derived from the source constants so a new input directory is covered on sight.
    # tests/test_sync.py checks this list against every file build_plan reads.
    # Absolute, because the core and the profile are different folders of one repository.
    sources = (RULES_DIR, CONTEXT_DIR, SKILLS_DIR, WORKFLOWS_DIR, ACTIONS_DIR, AGENTS_DIR,
               GITHOOKS_DIR, ROOT / "consent.py", RESPONSES_DIR, ROOT / "prime.py", HOOKS_DIR,
               EXCHANGE_DIR, ROOT / "cleanup.py",
               ROOT / "tests" / "run_shard.py", ROOT / "tests" / "select_tests.py",
               CAPABILITIES_DIR, ROOT / "sync.py", profile_dir / consent.LOCK_NAME,
               profile_dir / PROFILE_NAME, profile_dir / "seeds")
    inputs = [str(p) for p in sources]
    # Not %h: git lengthens it as a repo gains objects, so a self-hosted runner's clone
    # stamped 8 characters where a workstation stamped 7 and drift failed on both.
    return run("git", "log", "-1", "--format=%H", "--", *inputs)


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


# Suffixes whose stamp is a '#' comment line (YAML included, so a rendered hook data
# file is marked too). Markdown takes the HTML-comment stamp; anything else is copied
# verbatim, because a stamp injected into JSON or a template breaks the file it marks.
STAMPABLE_ASSETS = (".py", ".sh", ".ps1", ".yaml")

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
# Each tool's native event, and its tool matcher where it needs one. Cursor's and Claude
# Code's adapters render; Copilot's column is validation only until its adapter does, so a
# hook it cannot run is refused today.
HOOK_EVENTS = {
    "claude": {
        "session.start": ("SessionStart", None),
        "shell.before": ("PreToolUse", "Bash|PowerShell"),
        "file.write.before": ("PreToolUse", "Write|Edit"),
        "file.write.after": ("PostToolUse", "Write|Edit"),
        "turn.end": ("Stop", None),
    },
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
CLAUDE_SETTINGS = ".claude/settings.json"
MARKED_JSON = (".cursor/hooks.json", CLAUDE_SETTINGS)
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


CLAUDE_PROBE = "python -c pass"


def windows_git_bash() -> str | None:
    """The bash Claude Code runs a hook under on Windows: Git for Windows' bash, not the first
    `bash` on PATH, which can be WSL's stub under WindowsApps. In order: the path in
    CLAUDE_CODE_GIT_BASH_PATH, the bash beside the git installation found from `git` on PATH,
    then a `bash` on PATH that is not under WindowsApps."""
    override = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if override and Path(override).is_file():
        return override
    git = shutil.which("git")
    if git:
        # git.exe sits in <root>\cmd, <root>\bin or <root>\mingw64\bin.
        for parent in list(Path(git).parents)[:3]:
            candidate = parent / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    bash = shutil.which("bash")
    if bash and "windowsapps" not in bash.replace("\\", "/").lower().split("/"):
        return bash
    return None


def claude_launch_shell(windows: bool) -> list[str]:
    """The shell Claude Code runs a hook command under: bash on Windows, sh elsewhere."""
    if not windows:
        return ["sh", "-c"]
    bash = windows_git_bash()
    if not bash:
        raise SyncError("Git for Windows' bash was not found, and Claude Code runs a hook "
                        "command under it on Windows, so `python` cannot be checked to launch. "
                        "Install Git for Windows, or set CLAUDE_CODE_GIT_BASH_PATH to its "
                        "bash.exe (a bash under WindowsApps is WSL's stub and is not used), "
                        "then re-run --write")
    return [bash, "-c"]


def check_claude_launch(rel: str, content: str, windows: bool) -> None:
    """Refuse a settings file with hook entries when `python` does not launch the way Claude
    Code will launch it. A permission hook that cannot start blocks the action it guards."""
    if not json.loads(content).get("hooks"):
        return
    shell = claude_launch_shell(windows)
    try:
        ran = subprocess.run([*shell, CLAUDE_PROBE], capture_output=True, text=True,
                             timeout=HOOK_LAUNCH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError(f"{rel} not written: `{CLAUDE_PROBE}` could not be launched under "
                        f"{shell[0]}: {exc}") from exc
    if ran.returncode != 0:
        output = (ran.stdout + ran.stderr).strip()
        raise SyncError(f"{rel} not written: `{CLAUDE_PROBE}` does not launch under "
                        f"{shell[0]}, exit code {ran.returncode}\n{output}")


def has_generated_key(text: str) -> bool:
    """True when text is a JSON object with a top-level _generated key: sync's own file."""
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return isinstance(data, dict) and "_generated" in data


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


CURSOR_HOOKS = ".cursor/hooks"
CLAUDE_HOOKS = ".claude/hooks"
# What {hooks} in run: becomes: each adapter's own folder for the rendered scripts. Claude
# Code's goes through its project-root variable, so the committed file names no machine.
HOOKS_PLACEHOLDER = "{hooks}"
CLAUDE_PROJECT_HOOKS = "${CLAUDE_PROJECT_DIR}/" + CLAUDE_HOOKS


def render_hook_assets(plan: Plan, hook_dir: Path, sha: str, skip: Path | None = None,
                       root: str = CURSOR_HOOKS, prefixes: str | None = None) -> None:
    """Each file of a hook folder, rendered beside it. `prefixes`, when given, is the content
    of the title-prefix hook's prefixes.yaml in place of the core's default file."""
    for asset in sorted(p for p in hook_dir.rglob("*") if p.is_file()):
        rel = asset.relative_to(hook_dir)
        if asset == skip or GENERATED_DIRS.intersection(rel.parts):
            continue
        content = (prefixes if prefixes is not None
                   and f"{hook_dir.name}/{rel.as_posix()}" == TITLE_PREFIXES_FILE
                   else render_asset(asset, sha))
        plan[f"{root}/{hook_dir.name}/{rel.as_posix()}"] = content


def hook_sources(profile_dir: Path, tool: str) -> tuple[list[Path], list[tuple]]:
    """Every hooks/<name>/ directory, and the (dir, source, where, spec) of each with a
    hook.yaml that targets `tool`. A directory without hook.yaml is not an agent hook -
    no-secret-defaults is a git hook."""
    hook_dirs = [hook_dir for hook_dir in
                 merged_seeds(HOOKS_DIR, profile_dir, "hooks",
                              lambda f: [p for p in f.iterdir() if p.is_dir()])]
    found = []
    for hook_dir in hook_dirs:
        source = hook_dir / "hook.yaml"
        if not source.is_file():
            continue
        where = f"hooks/{hook_dir.name}/hook.yaml"
        spec = hook_spec(yaml.safe_load(source.read_text(encoding="utf-8")), where)
        if tool in spec["tools"]:
            found.append((hook_dir, source, where, spec))
    return hook_dirs, found


def fill_owner(run: list[str], owner: str | None, where: str) -> list[str]:
    run = [arg.replace("{owner}", owner) if owner else arg for arg in run]
    if any("{owner}" in arg for arg in run):
        raise SyncError(f"{where} uses {{owner}}, but {PROFILE_NAME} source has no owner")
    return run


def render_cursor_hooks(sha: str, owner: str | None, profile_dir: Path,
                        prefixes: str | None = None) -> dict[str, str]:
    """Every hooks/<name>/ with a hook.yaml, merged into one .cursor/hooks.json.

    The source is the tool-neutral schema (hooks/README.md); this is Cursor's adapter.
    Cursor hooks fail open by default, so failClosed is written on every entry, from kind:.
    A directory without hook.yaml is not an agent hook - no-secret-defaults is a git hook.
    `{owner}` in run: is the profile's GitHub owner, so a hook script never names one, and
    `{hooks}` is `.cursor/hooks`; a literal `.cursor/hooks/` path still works.
    hooks/lib/ is the shared runtime library, rendered beside the hooks whenever any render.
    """
    plan = Plan()
    events: dict[str, list[dict]] = {}
    hook_dirs, found = hook_sources(profile_dir, "cursor")
    for hook_dir, source, where, spec in found:
        run = fill_owner([arg.replace(HOOKS_PLACEHOLDER, CURSOR_HOOKS) for arg in spec["run"]],
                         owner, where)
        if run[0] == "{python}" and sys.prefix != sys.base_prefix:
            raise SyncError(f"sync.py is running in a virtual environment ({sys.prefix}); a hook "
                            "rendered with its interpreter stops launching when that environment "
                            "goes. Run sync.py with the base interpreter")
        native, matcher = HOOK_EVENTS["cursor"][spec["event"]]
        # The tool is named explicitly, so hooks/lib/hookio.py reads Cursor's payload and writes
        # Cursor's verdict by this entry rather than by its no-argument default.
        run = [*run, "--tool", "cursor"]
        entry = {"command": hook_command(run, where, sys.executable, os.name == "nt")}
        if matcher:
            entry["matcher"] = matcher
        if "timeout" in spec:
            entry["timeout"] = spec["timeout"]
        entry["failClosed"] = HOOK_FAILS_CLOSED[spec["kind"]]
        events.setdefault(native, []).append(entry)
        render_hook_assets(plan, hook_dir, sha, skip=source, prefixes=prefixes)
    if events:
        for hook_dir in hook_dirs:
            if hook_dir.name == HOOK_LIB:
                render_hook_assets(plan, hook_dir, sha)
        config = {"_generated": stamp(sha)[5:-4].strip(), "version": 1,
                  "hooks": events}
        plan[".cursor/hooks.json"] = json.dumps(config, indent=2) + "\n"
    return plan


def claude_hook_command(run: list[str], where: str, owner: str | None) -> str:
    """Claude Code's adapter: join run: into one command for the bash it runs hooks under.

    `{python}` is a bare `python` from PATH, since a committed file cannot name a machine's
    interpreter; the launch check at --write proves it starts. `{hooks}` is the project's
    .claude/hooks through ${CLAUDE_PROJECT_DIR}, in double quotes so the shell expands it.
    """
    for arg in run:
        if arg.startswith(".cursor/"):
            raise SyncError(f"{where}: run: names {arg!r}, a Cursor path, which Claude Code "
                            f"cannot run. Write {HOOKS_PLACEHOLDER}/<name>/... so each tool "
                            "resolves its own folder")
    if "{python}" in run[1:]:
        raise SyncError(f"{where}: {{python}} must open run:")
    words = []
    for arg in fill_owner([a.replace(HOOKS_PLACEHOLDER, CLAUDE_PROJECT_HOOKS)
                           for a in ["python" if a == "{python}" else a for a in run]],
                          owner, where):
        if "${CLAUDE_PROJECT_DIR}" in arg:
            rest = arg.replace("${CLAUDE_PROJECT_DIR}", "")
            if any(char in rest for char in '"`$\\'):
                raise SyncError(f"{where}: run: entry {arg!r} cannot be double-quoted safely")
            words.append(f'"{arg}"')
        else:
            words.append(shell_argument(arg, windows=False))
    return " ".join(words)


def render_claude_settings(sha: str, owner: str | None, profile_dir: Path,
                           hooks_on: bool, prefixes: str | None = None) -> dict[str, str]:
    """The one committed .claude/settings.json: hook entries in Claude Code's shape, and the
    permission rules from the profile's seeds/permissions.yaml. Written only when it has
    one of them. Scripts and the library go under .claude/hooks/."""
    plan = Plan()
    events: dict[str, list[dict]] = {}
    if hooks_on and HOOKS_DIR.exists():
        hook_dirs, found = hook_sources(profile_dir, "claude")
        for hook_dir, source, where, spec in found:
            run = claude_hook_command(spec["run"], where, owner)
            native, matcher = HOOK_EVENTS["claude"][spec["event"]]
            handler = {"type": "command", "command": f"{run} --tool claude"}
            if "timeout" in spec:
                handler["timeout"] = spec["timeout"]
            if HOOK_FAILS_CLOSED[spec["kind"]]:
                handler["onFailure"] = "block"
            groups = events.setdefault(native, [])
            group = next((g for g in groups if g.get("matcher") == matcher), None)
            if group is None:
                group = {"matcher": matcher, "hooks": []} if matcher else {"hooks": []}
                groups.append(group)
            group["hooks"].append(handler)
            render_hook_assets(plan, hook_dir, sha, skip=source, root=CLAUDE_HOOKS,
                               prefixes=prefixes)
        if events:
            for hook_dir in hook_dirs:
                if hook_dir.name == HOOK_LIB:
                    render_hook_assets(plan, hook_dir, sha, root=CLAUDE_HOOKS)
    rules = render_permission_rules(load_permissions(profile_dir)["entries"])
    if events or rules:
        config: dict = {"_generated": stamp(sha)[5:-4].strip()}
        if events:
            config["hooks"] = events
        if rules:
            config["permissions"] = rules
        plan[CLAUDE_SETTINGS] = json.dumps(config, indent=2, sort_keys=False) + "\n"
    return plan


PERMISSIONS_FILE = "permissions.yaml"
PERMISSION_KINDS = ("allow", "ask", "deny")
PERMISSION_ENTRY_KEYS = {"command", "kind", "job"}
PERMISSION_KEYS = {"entries", "classifier"}
CLASSIFIER_KEYS = ("allow", "block")


def load_permissions(profile_dir: Path) -> dict:
    """<profile>/seeds/permissions.yaml, checked: {"entries": [...], "classifier": {...}}.

    The core holds the schema and never a rule. Anything the schema does not name is
    refused, and each refusal names the entry. `classifier:` is validated here and rendered
    by the user-level file's render, not into a repository."""
    path = Path(profile_dir) / "seeds" / PERMISSIONS_FILE
    empty = {"entries": [], "classifier": {key: [] for key in CLASSIFIER_KEYS}}
    if not path.is_file():
        return empty
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SyncError(f"{path} must be a mapping with entries: and classifier:")
    unknown = sorted(set(data) - PERMISSION_KEYS)
    if unknown:
        raise SyncError(f"{path}: unknown key(s) {unknown}; allowed {sorted(PERMISSION_KEYS)}")
    entries = data.get("entries") or []
    if not isinstance(entries, list):
        raise SyncError(f"{path}: entries: must be a list")
    seen: dict[str, str] = {}
    for index, entry in enumerate(entries, 1):
        name = f"{path} entry {index}"
        if not isinstance(entry, dict):
            raise SyncError(f"{name} must be a mapping")
        command = entry.get("command")
        if isinstance(command, str) and command.strip():
            name = f"{name} ({command.strip()!r})"
        unknown = sorted(set(entry) - PERMISSION_ENTRY_KEYS)
        if unknown:
            raise SyncError(f"{name}: unknown key(s) {unknown}; "
                            f"allowed {sorted(PERMISSION_ENTRY_KEYS)}")
        if not isinstance(command, str) or not command.strip():
            raise SyncError(f"{name}: command: must be a non-empty string")
        if entry.get("kind") not in PERMISSION_KINDS:
            raise SyncError(f"{name}: kind: {entry.get('kind')!r} is not one of "
                            f"{list(PERMISSION_KINDS)}")
        if not isinstance(entry.get("job"), str) or not entry["job"].strip():
            raise SyncError(f"{name}: job: must be a non-empty string")
        command = command.strip()
        if seen.setdefault(command, entry["kind"]) != entry["kind"]:
            raise SyncError(f"{name}: command {command!r} is {seen[command]} in one entry "
                            f"and {entry['kind']} in another")
    classifier = data.get("classifier") or {}
    if not isinstance(classifier, dict) or set(classifier) - set(CLASSIFIER_KEYS):
        raise SyncError(f"{path}: classifier: must be a mapping with only {list(CLASSIFIER_KEYS)}")
    for key in CLASSIFIER_KEYS:
        lines = classifier.get(key) or []
        if not isinstance(lines, list) or not all(isinstance(line, str) and line.strip()
                                                  for line in lines):
            raise SyncError(f"{path}: classifier.{key}: must be a list of non-empty strings")
    return {"entries": [{**e, "command": e["command"].strip(), "job": e["job"].strip()}
                        for e in entries],
            "classifier": {key: list(classifier.get(key) or []) for key in CLASSIFIER_KEYS}}


def render_permission_rules(entries: list[dict]) -> dict[str, list[str]]:
    """Claude Code's permissions block: each command as a Bash and a PowerShell prefix rule
    under its kind, sorted and de-duplicated, with only the kinds that have a rule."""
    rules: dict[str, list[str]] = {}
    for kind in PERMISSION_KINDS:
        found = sorted({f"{tool}({e['command']} *)" for e in entries if e["kind"] == kind
                        for tool in ("Bash", "PowerShell")})
        if found:
            rules[kind] = found
    return rules


def job_table_rows(text: str) -> list[tuple[str, str]]:
    """The (first cell, line) of every row below a table header whose first cell is `Job`.

    A table is a run of lines starting with `|`; its first line is the header and the
    separator line is skipped. A table with any other first header cell is ignored."""
    rows: list[tuple[str, str]] = []
    in_job_table = False
    previous_was_table = False
    for line in text.splitlines():
        if not line.startswith("|"):
            previous_was_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not previous_was_table:
            in_job_table = cells[0] == "Job"
        elif in_job_table and not set(line.replace("|", "").strip()) <= set("-: "):
            rows.append((cells[0], line))
        previous_was_table = True
    return rows


def permission_table_problems(entries: list[dict], tables: str | dict[str, str]) -> list[str]:
    """Each entry's job must be the first cell of exactly one `Job` table row across the given
    tables, and that row must hold the entry's command, so the prose and the data cannot drift.

    `tables` maps a file name to its text, so a problem can name the file of the row; a bare
    string is one unnamed table."""
    if isinstance(tables, str):
        tables = {"the table": tables}
    rows = [(first, line, name) for name, text in tables.items()
            for first, line in job_table_rows(text)]
    problems = []
    for entry in entries:
        job, command = entry["job"], entry["command"]
        matching = [(line, name) for first, line, name in rows if first == job]
        if len(matching) != 1:
            where = f" ({', '.join(sorted(n for _, n in matching))})" if matching else ""
            problems.append(f"permission entry {command!r}: job {job!r} is the first cell of "
                            f"{len(matching)} table rows{where}, not exactly one")
        elif command not in matching[0][0]:
            problems.append(f"permission entry {command!r}: its row {job!r} in "
                            f"{matching[0][1]} does not mention that command")
    return problems


def permission_problems(profile_dir: Path) -> list[str]:
    """The table drift check on a profile's real data; the core has none, so it passes empty.

    It reads every `Job` table in the core's rules and in the profile's own seeds/rules/."""
    entries = load_permissions(profile_dir)["entries"]
    if not entries:
        return []
    folders = [("core", RULES_DIR), ("profile", profile_dir / "seeds" / "rules")]
    tables = {f"{label} rules/{path.name}": path.read_text(encoding="utf-8")
              for label, folder in folders if folder.is_dir()
              for path in sorted(folder.glob("*.md"))}
    return permission_table_problems(entries, tables)


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
    "skill": ("Skill",),
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
    # `agents:` is known and not applicable here, so it is dropped without a warning: Claude
    # Code ignores a type list in a subagent's Agent(...), and only a main-thread agent can
    # restrict which subagents it starts.
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


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0


def _frontmatter(text: str) -> str:
    """The text between a file's leading `---` lines, or '' when it has none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[1:i])
    return ""


def _resident_total(repo: Path, fixed: tuple[str, ...], glob: str, resident) -> int:
    """Lines of the fixed files, plus those of each file matching `glob` (a path
    relative to the repo) whose text `resident` accepts."""
    total = sum(_line_count(repo / name) for name in fixed)
    for path in sorted(repo.glob(glob)):
        text = path.read_text(encoding="utf-8")
        if resident(text):
            total += len(text.splitlines())
    return total


def resident_copilot(repo: Path) -> int:
    """AGENTS.md, copilot-instructions.md, and instruction files with an applyTo of '**'.

    An earlier version omitted the applyTo '**' files and under-reported by 76 lines,
    precisely the false-reading defect this estate keeps producing.
    """
    return _resident_total(repo, ("AGENTS.md", ".github/copilot-instructions.md"),
                           ".github/instructions/*.md", lambda t: "applyTo: '**'" in t)


def resident_cursor(repo: Path) -> int:
    """AGENTS.md, and the .cursor/rules files whose frontmatter has alwaysApply: true."""
    return _resident_total(repo, ("AGENTS.md",), ".cursor/rules/*.mdc",
                           lambda t: re.search(r"^alwaysApply:\s*true\s*$", _frontmatter(t), re.M)
                           is not None)


def resident_claude(repo: Path) -> int:
    """CLAUDE.md, AGENTS.md, and the .claude/rules files with no `paths:` key."""
    return _resident_total(repo, ("CLAUDE.md", "AGENTS.md"), ".claude/rules/*.md",
                           lambda t: re.search(r"^paths:", _frontmatter(t), re.M) is None)


def resident_report(repo: Path, tools: tuple) -> list[str]:
    """One resident-footprint line per tool. Counts are never summed across tools: an
    always-on rule would be counted once for every tool that loads it.

    Measures residency, not quality. Resident lines are paid for in every session
    forever, so the number should be known and should not creep.
    """
    return [f"resident footprint ({t.name}): {t.resident(repo)} lines" for t in tools]


@dataclass(frozen=True)
class Tool:
    """One interactive tool's output for rules, skills and agents. A new tool is a new row.

    `rule_path` takes {id}; `rule` returns the file, or None when the tool does not render
    that rule. `skill_root` and `agent_path` (takes {name}) are None for a tool without them,
    and `agent` takes (meta, body, sha, warn). `resident` takes the repo and returns the
    lines this tool loads at the start of a session. Hooks are not here.
    """
    name: str
    rule_path: str
    rule: object
    skill_root: str | None
    agent_path: str | None
    agent: object
    resident: object


TOOLS = (
    Tool("copilot", ".github/instructions/{id}.instructions.md", render_copilot_rule,
         ".github/skills", ".github/agents/{name}.agent.md", render_copilot_agent, resident_copilot),
    Tool("cursor", ".cursor/rules/{id}.mdc", render_cursor, ".cursor/skills", None, None, resident_cursor),
    Tool("claude", ".claude/rules/{id}.md", render_claude_rule, ".claude/skills",
         ".claude/agents/{name}.md", render_claude_agent, resident_claude),
)
# Derived, for what reads the roots without the rest of a row.
SKILL_ROOTS = tuple(t.skill_root for t in TOOLS if t.skill_root)


def selected_tools(manifest: dict, where: str = PROFILE_NAME) -> tuple[Tool, ...]:
    """The rows of TOOLS the profile renders: its top-level `tools:` list, or every row when
    there is none. One list for the whole profile; a target cannot override it. An empty
    list, a non-list, an unknown name or a duplicate is refused, naming the known rows."""
    known = [t.name for t in TOOLS]
    if "tools" not in manifest:
        return TOOLS
    names = manifest["tools"]
    if not isinstance(names, list) or not names:
        raise SyncError(f"{where}: tools: must be a non-empty list of {known}")
    unknown = sorted({str(n) for n in names if n not in known})
    if unknown:
        raise SyncError(f"{where}: tools: names {unknown}, which no row of TOOLS defines. "
                        f"Known: {known}")
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise SyncError(f"{where}: tools: lists {repeated} more than once. Known: {known}")
    return tuple(t for t in TOOLS if t.name in names)


# The rules a title-prefix entry may carry: hooks/title-prefix/hook.py grades by these.
TITLE_PREFIX_RULES = ("ask", "no-ask", "unchecked")
TITLE_PREFIX_SHAPES = ({"prefix", "rule"}, {"label", "pattern", "rule"})
TITLE_PREFIXES_FILE = "title-prefix/prefixes.yaml"


def title_prefixes(manifest: dict, where: str = PROFILE_NAME) -> list[dict] | None:
    """The profile's title_prefixes: list, validated, or None when it has none.

    Present, it replaces the core's default vocabulary whole. Each entry is exactly
    {prefix, rule} or {label, pattern, rule}, every value a non-empty string, the rule one the
    hook grades by and the pattern a regular expression. A bad entry refuses naming its
    position: the hook reads the rendered file at turn end and, on a bad one, grades nothing.
    """
    if "title_prefixes" not in manifest or manifest["title_prefixes"] is None:
        return None
    entries = manifest["title_prefixes"]
    if not isinstance(entries, list) or not entries:
        raise SyncError(f"{where}: title_prefixes: must be a non-empty list of entries")
    for index, entry in enumerate(entries):
        name = f"{where}: title_prefixes[{index}]"
        if not isinstance(entry, dict) or set(entry) not in TITLE_PREFIX_SHAPES:
            raise SyncError(f"{name} must be a mapping of exactly prefix: and rule:, or "
                            "label:, pattern: and rule:")
        for key, value in entry.items():
            if not isinstance(value, str) or not value.strip():
                raise SyncError(f"{name}: {key} must be a non-empty string")
        if entry["rule"] not in TITLE_PREFIX_RULES:
            raise SyncError(f"{name}: rule {entry['rule']!r} is not one of "
                            f"{', '.join(TITLE_PREFIX_RULES)}")
        if "pattern" in entry:
            try:
                re.compile(entry["pattern"])
            except re.error as exc:
                raise SyncError(f"{name}: pattern {entry['pattern']!r} is not a regular "
                                f"expression: {exc}") from exc
    return entries


def title_prefixes_file(manifest: dict, sha: str | None) -> str | None:
    """The prefixes.yaml a profile's title_prefixes: renders, or None when it has none and
    the core's default renders instead."""
    entries = title_prefixes(manifest)
    if entries is None:
        return None
    body = yaml.safe_dump({"prefixes": entries}, sort_keys=False, allow_unicode=True)
    return f"# {stamp(sha)[5:-4].strip()}\n{body}"


def repo_list(manifest: dict) -> dict:
    """The estate as data: owner, every repository with its GitHub name and issue key, and
    the repositories deliberately left out. Folder targets are left out too, because they
    are not repositories on the host. Rendered to REPO_LIST, and used in memory by
    runner, so the file and a source run agree by construction."""
    source = manifest.get("source") or {}
    owner = source.get("owner")
    if not owner:
        raise SyncError(f"{PROFILE_NAME} source has no owner, so no GitHub name can be built")
    repos = [{"name": source["repo"], "github": f"{owner}/{source['repo']}",
              "key": source.get("key")}]
    for name, cfg in (manifest.get("targets") or {}).items():
        cfg = cfg or {}
        if cfg.get("skip") or is_folder_target(cfg):
            continue
        repos.append({"name": name,
                      "github": f"{cfg.get('owner') or owner}/{cfg.get('remote') or name}",
                      "key": cfg.get("key")})
    for name, cfg in (manifest.get("tracked") or {}).items():
        cfg = cfg or {}
        repos.append({"name": name,
                      "github": f"{cfg.get('owner') or owner}/{cfg.get('remote') or name}",
                      "key": cfg.get("key"), "tracked": True})
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
    for name, cfg in (manifest.get("tracked") or {}).items():
        if (cfg or {}).get("key"):
            rows.append((name, cfg["key"]))
    width = max((len(r) for r, _ in rows), default=4)
    lines = [f"| {'Repo'.ljust(width)} | Issue key |", f"|{'-' * (width + 2)}|---|"]
    lines += [f"| {repo.ljust(width)} | `{key}-<n>` |" for repo, key in sorted(rows)]
    return "\n".join(lines)


BRANCH = re.compile(r"[A-Za-z0-9._/-]+")


def core_record_lines(manifest: dict, profile_dir: Path | None) -> str:
    """core-source= and core-tag= from the profile's vendored record, and one report-rerun=
    line per gate the profile lists for CI to run again.

    The record is `<profile_dir>/core/VENDORED`. A render with none (the core rendering itself)
    writes neither core line, and refuses a re-run list, since there would be nothing to fetch
    the trusted gate scripts by. A core vendored by SHA renders the full SHA as the tag.
    """
    import vendor
    rerun = gate_report_rerun(manifest)
    record_path = None if profile_dir is None else Path(profile_dir) / vendor.CORE_DIR
    if record_path is None or not (record_path / vendor.VENDORED).exists():
        if rerun:
            raise SyncError(f"{PROFILE_NAME}: gate_report: rerun: needs a vendored core to fetch "
                            "the gates from, and there is no core/VENDORED. Run --vendor-core")
        return ""
    try:
        record = vendor.read_record(record_path)
    except vendor.VendorError as error:
        raise SyncError(str(error)) from error
    return (f"core-source={record.source}\n"
            f"core-tag={record.tag or record.sha}\n"
            + "".join(f"report-rerun={gate}\n" for gate in rerun))


def release_tag_glob(manifest: dict, where: str = PROFILE_NAME) -> str | None:
    """rollout.release_tag, the glob that names a rules release in the profile. None when the
    profile sets none. The value ends up in one gate-config line and in a git command, so
    anything but a non-empty glob with no whitespace, and not starting with '-', is refused."""
    block = manifest.get("rollout") or {}
    if "release_tag" not in block:
        return None
    glob = block["release_tag"]
    if not isinstance(glob, str) or not glob or re.search(r"\s", glob) or glob.startswith("-"):
        raise SyncError(f"{where}: rollout: release_tag must be a non-empty glob with no "
                        f"whitespace, not {glob!r}")
    return glob


def release_lines(manifest: dict, profile_dir: Path | None) -> str:
    """The gate-config lines a target's freshness check reads: the profile repository's own
    origin URL at render time, and the release tag glob. Written only by a profile that sets
    rollout.release_tag, so every other render is unchanged. A profile that sets it and has
    no origin refuses: a remote nobody can name is not one to write."""
    glob = release_tag_glob(manifest)
    if glob is None:
        return ""
    try:
        url = git_at(profile_dir, "remote", "get-url", "origin").strip() if profile_dir else ""
    except SyncError:
        url = ""
    if not url:
        raise SyncError(f"{PROFILE_NAME} sets rollout.release_tag, but the profile repository "
                        f"({profile_dir}) has no origin remote to write as profile-remote")
    return f"profile-remote={url}\nrelease-tag={glob}\n"


def render_gate_config(target: str, cfg: dict, manifest: dict, sha: str,
                       profile_dir: Path | None = None) -> str:
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
    report_skip = "".join(f"report-skip={ref} {','.join(gates)}\n"
                          for ref, gates in gate_report_skips(manifest))
    return (f"{marker}\n"
            f"deploy-branch={branch}\n"
            f"identity-email={identity(manifest)['email']}\n"
            f"config-dir={gate_config_dir(manifest)}\n"
            f"{release_lines(manifest, profile_dir)}"
            f"{consent_check}"
            f"{report_skip}"
            f"{core_record_lines(manifest, profile_dir)}")


GATE_NAME = re.compile(r"[^\s,]+")
RERUN_GATE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def gate_report_rerun(manifest: dict, where: str = PROFILE_NAME) -> list[str]:
    """The core gates CI runs again, in declaration order, each once.

    Absent or empty is none. A name that is not a string, or not a gate under the core's
    githooks/gates/, is refused naming its position: the re-run fetches the core's gates,
    so a profile's own seeded gate is not there to run. Each name ends up in one gate-config
    line and in a path, so the shape is checked as well.
    """
    block = manifest.get("gate_report")
    entries = block.get("rerun") if isinstance(block, dict) else None
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise SyncError(f"{where}: gate_report: rerun: must be a list of core gate names")
    core_gates = {path.stem for path in (GITHOOKS_DIR / "gates").glob("*.sh")}
    found: list[str] = []
    for index, name in enumerate(entries):
        if not isinstance(name, str) or not RERUN_GATE_NAME.fullmatch(name):
            raise SyncError(f"{where}: gate_report: rerun[{index}] must be a gate name")
        if name not in core_gates:
            raise SyncError(f"{where}: gate_report: rerun[{index}]: {name} is not a core gate")
        if name not in found:
            found.append(name)
    return found


def gate_report_skips(manifest: dict, where: str = PROFILE_NAME) -> list[tuple[str, list[str]]]:
    """The refs on which the report check accepts a skipped required gate, as (pattern, gates)
    in declaration order, one row per pattern with its gates merged and deduplicated.

    Absent, or an empty list, is no exemption at all. An entry that is not a mapping of exactly
    `ref` and `gates`, a pattern that is not a regular expression or holds whitespace, or a
    gate name with whitespace or a comma is refused naming the entry: each value ends up in
    one line of gate-config, so a stray newline or space would forge or split it.
    """
    block = manifest.get("gate_report")
    if block is None:
        return []
    if not isinstance(block, dict) or set(block) - {"skip_allowed", "rerun"}:
        raise SyncError(f"{where}: gate_report: must be a mapping with only skip_allowed: "
                        "and rerun:")
    entries = block.get("skip_allowed")
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise SyncError(f"{where}: gate_report: skip_allowed: must be a list")
    merged: dict[str, list[str]] = {}
    for index, entry in enumerate(entries):
        name = f"{where}: gate_report: skip_allowed[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"ref", "gates"}:
            raise SyncError(f"{name} must be a mapping of ref: and gates:")
        ref, gates = entry["ref"], entry["gates"]
        if not isinstance(ref, str) or not ref or re.search(r"\s", ref):
            raise SyncError(f"{name}: ref must be a non-empty regular expression with no "
                            "whitespace")
        try:
            re.compile(ref)
        except re.error as exc:
            raise SyncError(f"{name}: ref {ref!r} is not a regular expression: {exc}") from exc
        if (not isinstance(gates, list) or not gates
                or not all(isinstance(g, str) and GATE_NAME.fullmatch(g) for g in gates)):
            raise SyncError(f"{name}: gates must be a non-empty list of gate names, none "
                            "holding whitespace or a comma")
        row = merged.setdefault(ref, [])
        row.extend(g for g in gates if g not in row)
    return list(merged.items())


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


def declared(answers: dict[str, str], key: str) -> bool:
    """Whether the answer under `key` names a system: present, and not `n/a`."""
    return key in answers and str(answers[key]).strip().lower() != "n/a"


def unbuilt_answers(answers: dict[str, str], questions: dict[str, Questions],
                    bound: dict[str, str]) -> list[str]:
    """Each answer that declares a system while nothing binds a capability its file defines."""
    return [f"{stem}.{entry.declares}" for stem, entry in sorted(questions.items())
            if entry.declares and declared(answers, f"{stem}.{entry.declares}")
            and not entry.capabilities & set(bound)]


CONVENTIONS_MARKER = "<!-- CONVENTIONS -->"


def conventions(answers: dict[str, str], questions: dict[str, Questions]
                ) -> list[tuple[str, str, list[str]]]:
    """(stem, rule body, flagged keys left unanswered) per capability file whose system is
    declared. Undeclared renders nothing and reports nothing: no system, no conventions."""
    rules = []
    for stem, entry in sorted(questions.items()):
        if not entry.renders or not declared(answers, f"{stem}.{entry.declares}"):
            continue
        lines = [f"# {stem.capitalize()} conventions", "",
                 f"This profile's answers to the setup questions in `capabilities/{stem}.yaml`.",
                 f"Read them before using the {stem}."]
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
                           f"{stem} setup questions, which say how it uses its {stem}. "
                           f"Read before any use of its {stem}."}


def conventions_rows(rules: list[tuple[str, str, list[str]]]) -> str:
    """One routing-table row per rendered conventions rule, or nothing."""
    return "".join(f"| `{ON_DEMAND_DIR}/{stem}-conventions.md` | Before any use of its {stem} - "
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


def add_rules(plan: Plan, rule_id: str, meta: dict, body: str, sha: str | None,
              tools: tuple[Tool, ...] | None = None) -> None:
    """One rule into every tool's rule path that renders it.

    A rule's optional `tools:` names the rows of TOOLS that render it; absent, every row
    does. `tools` is the profile's selection (every row when None); the two intersect, and a
    rule left rendering nowhere is skipped without a word. An on-demand rule is shared across
    tools (ON_DEMAND_DIR), so it cannot be limited to some of them, and `tools:` on one is
    refused rather than half-applied.
    """
    only = meta.get("tools")
    if only is not None:
        names = {t.name for t in TOOLS}
        if not isinstance(only, list) or not only:
            raise SyncError(f"rule {rule_id}: tools: must be a non-empty list of "
                            f"{sorted(names)}")
        unknown = sorted(str(n) for n in only if n not in names)
        if unknown:
            raise SyncError(f"rule {rule_id}: tools: names {unknown}, which no row of TOOLS "
                            f"defines. Known: {sorted(names)}")
        if meta.get("scope", "*") == "*" and not meta.get("alwaysApply", False):
            raise SyncError(f"rule {rule_id}: tools: on an on-demand rule is not supported, "
                            "because on-demand rules are shared across tools")
    for tool in TOOLS if tools is None else tools:
        if only is not None and tool.name not in only:
            continue
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
    tools = selected_tools(manifest)
    chosen = {t.name for t in tools}
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
        add_rules(plan, f"{stem}-conventions", conventions_meta(stem), rule, sha, tools)
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
        add_rules(plan, "estate", meta, body, sha, tools)
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
        add_rules(plan, rule_id, meta, body, sha, tools)

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
        for root in (t.skill_root for t in tools if t.skill_root):
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
        body = render_body(body, source, meta, known, bound, plan)
        # Copilot prompt files; nothing else reads .github/prompts/.
        if "copilot" in chosen:
            plan[f".github/prompts/{source.name}"] = render_prompt(meta, body, sha)

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
            for tool in tools:
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
        # A consumer selects its tests through these from its `run:` line.
        for name in ("run_shard.py", "select_tests.py"):
            selector = ROOT / "tests" / name
            if selector.exists():
                plan[f".githooks/lib/{name}"] = render_asset(selector, sha)
        plan[".githooks/gate-config"] = render_gate_config(target, cfg, manifest, sha, profile_dir)
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

    # Off unless a target opts in with `hooks: true`, pending the hook design review. Each
    # adapter renders only when its tool is chosen. Claude Code's file also carries the
    # profile's permission rules, which render whether or not hooks are on.
    owner = (manifest.get("source") or {}).get("owner")
    prefixes = title_prefixes_file(manifest, sha)
    if cfg.get("hooks", False) and "cursor" in chosen and HOOKS_DIR.exists():
        plan.update(render_cursor_hooks(sha, owner, profile_dir, prefixes))
    if "claude" in chosen:
        plan.update(render_claude_settings(sha, owner, profile_dir, cfg.get("hooks", False),
                                           prefixes))

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
    ".claude/hooks",
    ".claude/rules",
    ".claude/skills",
    ".claude/agents",
    ".agents/skills",
    FACTORY_DIR,
    FACTORY_SKILLS_DIR,
)
# A workflow never loads as a rule, and repositories keep their own CI beside the
# rendered workflows, so find_foreign does not report anything under these.
FOREIGN_CHECK_SKIPS = (".github/workflows",)
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


READER_LIST_LIMIT = 20


def _orphan_needles(repo: Path, orphans: list[str]) -> list[str]:
    """What a reader would write to name an orphan: its path, and each folder two or more
    levels deep that removing the orphans leaves empty (or removes with it)."""
    doomed = set(orphans)
    folders: dict[str, bool] = {}
    for rel in orphans:
        for parent in PurePosixPath(rel).parents:
            name = parent.as_posix()
            if len(parent.parts) < 2 or name in folders:
                continue
            base = repo / name
            folders[name] = base.is_dir() and all(
                path.relative_to(repo).as_posix() in doomed
                for path in base.rglob("*") if path.is_file())
    needles = set(orphans) | {name for name, empty in folders.items() if empty}
    return sorted(needles, key=lambda needle: (-len(needle), needle))


def orphan_readers(repo: Path, orphans: list[str], plan: dict[str, str]) -> list[str]:
    """Tracked files that still name a path about to be removed, as 'file:line: needle'.

    A rollout commit touches only rendered paths, so a target's pre-push gate selects no
    suite for its own code, and code reading a removed file breaks unseen. Files the render
    writes or stamps, the orphans themselves and binary files are not readers.
    """
    if not orphans:
        return []
    needles = _orphan_needles(repo, orphans)
    variants = []
    for needle in needles:
        for form in (needle, needle.replace("/", "\\")):
            variants.append((form, needle))
    skip = set(plan) | set(orphans)
    listed = git_at(repo, "ls-files", "-z").split("\0")
    readers = []
    for rel in sorted(rel for rel in listed if rel and rel not in skip):
        path = repo / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\0" in raw[:8192]:
            continue
        text = raw.decode("utf-8", errors="replace")
        if is_stamped(text):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            hit = next((needle for form, needle in variants if form in line), None)
            if hit:
                readers.append(f"{rel}:{number}: {hit}")
                break
    return readers


def orphan_readers_message(readers: list[str]) -> str:
    lines = readers[:READER_LIST_LIMIT]
    if len(readers) > READER_LIST_LIMIT:
        lines.append(f"... and {len(readers) - READER_LIST_LIMIT} more")
    return ("\n  ".join(lines))


def report_orphan_readers(readers: list[str]) -> int:
    """Print the readers a --check or dry run found, and return how many."""
    if readers:
        print(f"\n[WARN] {len(readers)} tracked file(s) still read a path about to be removed:")
        print("  " + orphan_readers_message(readers))
    return len(readers)


def refuse_orphan_readers(repo: Path, orphans: list[str], plan: dict[str, str]) -> None:
    """Refuse while a tracked file reads an orphan. A write calls it before emit, so a
    refused target is left exactly as it was rather than half rendered."""
    readers = orphan_readers(repo, orphans, plan)
    if readers:
        raise SyncError(
            f"{len(readers)} tracked file(s) still read a rendered path that this render "
            f"removes, so nothing was written or removed:\n  {orphan_readers_message(readers)}\n"
            "Fix the reader, or point it at the path the new render uses, then render again.")


def remove_orphans(repo: Path, orphans: list[str], plan: dict[str, str],
                   on_remove=None) -> None:
    """Remove the orphans, or refuse and remove nothing while a tracked file reads one."""
    refuse_orphan_readers(repo, orphans, plan)
    for rel in orphans:
        (repo / rel).unlink()
        if on_remove:
            on_remove(rel)


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
        if any(rel == skip or rel.startswith(skip + "/") for skip in FOREIGN_CHECK_SKIPS):
            continue
        if not is_stamped(path.read_text(encoding="utf-8")):
            foreign.append(rel)
    return sorted(foreign)


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


def emit(repo: Path, plan: dict[str, str], write: bool, *, ident: dict[str, str],
         git: bool = True) -> int:
    """Write or compare the plan in repo. git=False is a plain folder: no git config is read
    or set there."""
    # Checked before anything is written. A hand-owned hooks.json is that repo's own guard,
    # and overwriting it drops the guard silently.
    for rel in MARKED_JSON:
        path = repo / rel
        if rel == CLAUDE_SETTINGS:
            if (rel in plan and path.is_file()
                    and not has_generated_key(path.read_text(encoding="utf-8"))):
                raise SyncError(f"{rel} in {repo} has no _generated key, so sync did not write "
                                "it. Refusing to overwrite it: move its entries to "
                                ".claude/settings.local.json, which Claude Code merges in")
            continue
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
        if CLAUDE_SETTINGS in plan:
            check_claude_launch(CLAUDE_SETTINGS, plan[CLAUDE_SETTINGS], os.name == "nt")
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
    if git:
        activate_hooks(repo, write)
        # Local config, like core.hooksPath: a fresh CI checkout never has it, so it is
        # reported but not counted, or --check would fail every drift run.
        ensure_identity(repo, write, ident)
    return changed


def ensure_ignored(repo: Path, write: bool, probe: str, rule: str, why: str) -> int:
    """Append rule to .gitignore unless git already ignores probe. Returns 1 when a change is
    needed, so --check fails on it. A rule the repo already has in its own form counts.

    Only the committed .gitignore files decide. .git/info/exclude and the global excludes file
    are per machine, so a render that trusted them passed locally and drifted in CI. Git is
    pointed at a throwaway empty git dir over the same work tree, which leaves the target's
    .git/info/exclude out of the picture without touching it, and the global file is emptied."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    with tempfile.TemporaryDirectory() as scratch:
        git_dir = Path(scratch) / "git"
        made = subprocess.run(("git", "init", "--bare", "--quiet", str(git_dir)),
                              capture_output=True, text=True, env=env, timeout=60)
        if made.returncode != 0:
            raise SyncError(f"git init failed for the ignore check: {made.stderr.strip()}")
        check_env = {**env, "GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(repo)}
        found = subprocess.run(("git", "-c", "core.excludesFile=", "check-ignore", "-q", probe),
                               cwd=repo, capture_output=True, text=True, env=check_env,
                               timeout=60)
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


def ensure_claude_worktrees_ignored(repo: Path, write: bool) -> int:
    """Claude Code makes isolated worktrees under .claude/worktrees/. Never rendered; only
    kept out of the checkout's status, where they would block a rollout."""
    return ensure_ignored(repo, write, ".claude/worktrees/probe", ".claude/worktrees/",
                          "Claude Code's isolated worktrees; unignored, they dirty the "
                          "checkout and block rollouts")


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


TREE_KILL_TIMEOUT = 30


def _end_process_tree(proc: subprocess.Popen) -> None:
    """End proc and everything it started. Raises SyncError where the tree
    could not be ended, so a survivor is reported rather than ignored."""
    if sys.platform == "win32":
        try:
            killed = subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                                    capture_output=True, text=True, timeout=TREE_KILL_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            proc.kill()
            raise SyncError(f"the push timed out and taskkill did not finish: {exc}; "
                            "the process tree may still be running") from exc
        # taskkill reports an already-exited process as an error; that is fine.
        if killed.returncode != 0 and proc.poll() is None:
            proc.kill()
            raise SyncError(f"the push timed out and taskkill exited {killed.returncode}: "
                            f"{killed.stderr.strip()}; the process tree may still be running")
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            proc.kill()
            raise SyncError(f"the push timed out and its process group could not be ended: "
                            f"{exc}; the process tree may still be running") from exc
    proc.wait()


def push_with_timeout(repo: Path, timeout: float) -> bool:
    """git push in a target, in its own process group. True when it exited within
    the timeout; SyncError with git's stderr on a non-zero exit. On a timeout the
    whole process tree is ended, not only git, and the result is False."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
             else {"start_new_session": True})
    proc = subprocess.Popen(("git", "push", "--quiet"), cwd=repo, env=env, text=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **group)
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_process_tree(proc)
        return False
    if proc.returncode != 0:
        raise SyncError(f"git push --quiet failed: {(stderr or '').strip()}")
    return True


def _timed_out_push_verdict(repo: Path, timeout: float) -> str:
    """After a push timeout, read the remote rather than assuming the push failed."""
    head = git_at(repo, "rev-parse", "HEAD").strip()
    short = head[:7]
    prefix = f"push timed out after {timeout:.0f}s; process tree ended"
    try:
        branch = git_at(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        remote = git_at(repo, "ls-remote", "origin", f"refs/heads/{branch}").split()
    except SyncError as exc:
        raise SyncError(f"{prefix}; the remote could not be read, so the outcome is "
                        f"unknown: {exc}") from exc
    if remote and remote[0] == head:
        return f"pushed ({prefix}; remote is at {short})"
    raise SyncError(f"{prefix}; remote is not at {short} (not landed)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def write_lock(lock: dict, path: Path) -> None:
    """Write in one step, so a reader never sees half a lock."""
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock), encoding="utf-8")
    for attempt in range(1, LOCK_REPLACE_ATTEMPTS + 1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == LOCK_REPLACE_ATTEMPTS:
                raise
            time.sleep(LOCK_REPLACE_SLEEP)


def heartbeat(lock: dict, path: Path) -> None:
    """Stamp the lock as alive. A write that still fails after its retries is a warning:
    the targets are mid-rollout, and a stale heartbeat is no reason to abandon them."""
    lock["heartbeat"] = _now().isoformat(timespec="seconds")
    try:
        write_lock(lock, path)
    except PermissionError as exc:
        print(f"[WARN] rollout lock heartbeat not written ({exc}); carrying on")


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
                   manifest: dict, subject: str, profile_dir: Path,
                   ff_behind: bool = False) -> str:
    """Render and commit one target. Returns what was done; raises SyncError on a
    refusal or failure, so the caller moves on. Pushing is a separate phase.

    With ff_behind, a clean target that is only behind its upstream is fast-forwarded
    first. Without it the rollout never pulls."""
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
    fast_forwarded = None
    if behind != "0":
        if not ff_behind:
            raise SyncError(f"{behind} commit(s) behind its upstream; run 'git pull --ff-only' "
                            f"there first, or re-run with --ff-behind")
        # Only a clone that is only behind is moved; a diverged one is never merged.
        ahead = git_at(repo, "rev-list", "--count", "@{u}..HEAD").strip()
        if ahead != "0":
            raise SyncError(f"{behind} commit(s) behind and {ahead} ahead of its upstream; "
                            f"--ff-behind fast-forwards only a clone that is only behind")
        # A failed lookup raises: it must never read as zero rendered paths.
        fast_forwarded = set(git_at(repo, "diff", "--name-only", "HEAD", "@{u}").splitlines())
        try:
            git_at(repo, "merge", "--ff-only", "--quiet", "@{u}")
        except SyncError as exc:
            raise SyncError(f"fast-forward failed: {exc}") from exc
    # An earlier rollout's own unpushed commit is not foreign work: a re-run with --push pushes it.
    log = git_at(repo, "log", "--format=%s%x1f%b%x1e", "@{u}..HEAD")
    prefix = f"From {source_repo(manifest)}@"
    foreign = 0
    for record in log.split("\x1e"):
        if not record.strip("\n"):
            continue
        subject, _, body = record.strip("\n").partition("\x1f")
        if not (subject.startswith("Sync rules: ") and body.startswith(prefix)):
            foreign += 1
    if foreign:
        raise SyncError(f"{foreign} commit(s) ahead of its upstream that the rollout did not make; "
                        f"push or reset that clone first")

    plan = build_plan(name, cfg, defaults, sha, manifest, profile_dir)
    said = ""
    if fast_forwarded is not None:
        # The render below overwrites these, which is why they are counted, not refused.
        said = (f"fast-forwarded {behind} commit(s), "
                f"{len(fast_forwarded & set(plan))} rendered path(s) among them, ")
    report_drops(plan)
    refuse_orphan_readers(repo, find_orphans(repo, plan), plan)
    ident = identity(manifest)
    emit(repo, plan, True, ident=ident)
    verify_identity(repo, ident)
    ensure_scratch_ignored(repo, True)
    ensure_pycache_ignored(repo, True)
    ensure_claude_local_ignored(repo, True)
    ensure_claude_worktrees_ignored(repo, True)
    ensure_cursor_tracked(repo, True)
    ensure_hooks_local(repo, True)
    orphans = find_orphans(repo, plan)
    remove_orphans(repo, orphans, plan)

    hidden = hidden_plan_paths(repo, plan)
    if hidden:
        raise SyncError(f"its .gitignore hides {len(hidden)} rendered file(s), so they would never "
                        f"be committed; nothing committed: {', '.join(hidden)}")

    allowed = set(plan) | set(orphans) | {".gitignore"}
    changed = [entry[3:] for entry in
               git_at(repo, "status", "--porcelain=v1", "-z", "-uall").split("\0") if entry]
    if not changed:
        return f"{said}already current"
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
    return f"{said}committed {commit} ({len(changed)} file(s))"


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


def push_target(repo: Path, timeout: float = PUSH_TIMEOUT) -> str:
    if git_at(repo, "rev-list", "--count", "@{u}..HEAD").strip() == "0":
        return "nothing to push"
    if not push_with_timeout(repo, timeout):
        return _timed_out_push_verdict(repo, timeout)
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


def rollout_parallel(manifest: dict, override: int | None = None) -> int:
    """How many targets push at once. Read-only probe on first use, then git config.

    An override (--parallel) is for that run only: nothing is probed, read or stored.
    """
    if override is not None:
        if not 1 <= override <= PARALLEL_MAX:
            raise SyncError(f"--parallel is {override}; it must be a whole number from 1 "
                            f"to {PARALLEL_MAX}")
        return override
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
    if args.parallel is not None and not args.push:
        raise SyncError("--parallel only applies to --rollout --push")

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
    workers = rollout_parallel(manifest, args.parallel) if args.push else 0

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
            heartbeat(lock, lock_path)

        ready = []
        for name, cfg in (manifest.get("targets") or {}).items():
            cfg = cfg or {}
            if cfg.get("skip"):
                print(f"{name}: skipped - {cfg['skip']}")
                continue
            if is_folder_target(cfg):
                print(f"{name}: skipped - a plain folder, not a repository")
                continue
            try:
                line = rollout_target(name, cfg, args.root, defaults, sha, manifest, subject,
                                      profile_dir, ff_behind=args.ff_behind)
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
        lock_path.with_suffix(".tmp").unlink(missing_ok=True)
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


def repo_name_from_url(url: str) -> str | None:
    """The last path segment of a remote URL, without .git: the same name from an SSH,
    an HTTPS or a plain path form. None when there is no segment to name."""
    name = re.split(r"[/\\:]", url.strip().rstrip("/\\"))[-1]
    name = name[:-4] if name.endswith(".git") else name
    return name or None


def pull_profile(target: Path) -> Path:
    """The profile checkout named by git config rules.profile-path, or a refusal that says
    how to set it. Read with git config --get, so a machine sets it once with --global."""
    try:
        value = git_at(target, "config", "--get", "rules.profile-path").strip()
    except SyncError:
        value = ""
    how = "Set it once per machine: git config --global rules.profile-path <path to the profile>"
    if not value:
        raise SyncError(f"rules.profile-path is not set. {how}")
    folder = Path(value).expanduser()
    if not (folder / PROFILE_NAME).is_file():
        raise SyncError(f"rules.profile-path is {value!r}, which is not a profile directory: "
                        f"there is no {PROFILE_NAME} in it. {how}")
    return folder


def pull_target_name(target: Path, manifest: dict) -> str:
    """The one target whose remote matches the last segment of this clone's origin URL."""
    try:
        origin = git_at(target, "remote", "get-url", "origin").strip()
    except SyncError as exc:
        raise SyncError(f"{target} has no origin remote, so its target name cannot be "
                        "told") from exc
    repo = repo_name_from_url(origin)
    targets = manifest.get("targets") or {}
    matches = [name for name, cfg in targets.items() if (cfg or {}).get("remote", name) == repo]
    if not matches:
        raise SyncError(f"no target in {PROFILE_NAME} has the remote name {repo!r} "
                        f"(origin {origin})")
    if len(matches) > 1:
        raise SyncError(f"targets {', '.join(matches)} in {PROFILE_NAME} all have the remote "
                        f"name {repo!r} (origin {origin}), so which one this is cannot be told")
    if (targets[matches[0]] or {}).get("skip"):
        raise SyncError(f"'{matches[0]}' is marked skip in {PROFILE_NAME}")
    return matches[0]


def pull(args: argparse.Namespace) -> int:
    """--pull: render the profile's newest release tag into the repository this runs in.

    The release is checked out in a temporary worktree of the profile, so the profile's own
    working tree is never touched, and rendered by that release's own sync.py. The result is
    committed on the current branch. Nothing is pushed.
    """
    if (args.target or args.self_only or args.write or args.check or args.no_fetch
            or args.push or args.break_lock or args.ff_behind or args.rollout is not None
            or args.parallel is not None or args.profile or args.root):
        raise SyncError("--pull takes no target and none of --self, --write, --check, "
                        "--no-fetch, --profile, --root, --rollout, --push, --break-lock, "
                        "--ff-behind or --parallel: it is run in the repository to update")
    target = Path(git_at(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    profile_dir = pull_profile(target)
    manifest = load_profile(profile_dir)
    glob = release_tag_glob(manifest)
    if glob is None:
        raise SyncError(f"{profile_dir / PROFILE_NAME} has no rollout.release_tag, so there "
                        "is no telling which tags are releases")
    name = pull_target_name(target, manifest)
    if target.name != name:
        raise SyncError(f"this folder is {target.name!r} but its target is {name!r}: --pull "
                        f"renders into <parent folder>/{name}, so rename the folder")
    if git_at(target, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD":
        raise SyncError("HEAD is detached; check out the branch to commit on first")
    if git_at(target, "status", "--porcelain").strip():
        raise SyncError("uncommitted changes here - commit or stash them first")
    tags = git_at(profile_dir, "tag", "--list", "--sort=-creatordate", glob).split()
    if not tags:
        raise SyncError(f"no tag in {profile_dir} matches rollout.release_tag {glob!r}")
    tag = tags[0]
    release = git_at(profile_dir, "rev-list", "-n", "1", tag).strip()

    scratch = Path(tempfile.mkdtemp(prefix="rules-pull-"))
    tree = scratch / "tree"
    try:
        try:
            git_at(profile_dir, "worktree", "add", "--quiet", "--detach", str(tree), tag)
        except SyncError as exc:
            raise SyncError(f"could not check out {tag} of {profile_dir}: {exc}") from exc
        entry = next((p for p in (tree / "core" / "sync.py", tree / "sync.py") if p.is_file()),
                     None)
        if entry is None:
            raise SyncError(f"{tag} holds no core/sync.py or sync.py to render with")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        done = subprocess.run(
            (sys.executable, str(entry), "--profile", str(tree), name, "--write", "--no-fetch",
             "--root", str(target.parent)),
            cwd=tree, capture_output=True, text=True, env=env, timeout=PULL_RENDER_TIMEOUT)
        if done.returncode != 0:
            raise SyncError(f"rendering {tag} failed: "
                            f"{(done.stderr.strip() or done.stdout.strip())}")
    finally:
        try:
            git_at(profile_dir, "worktree", "remove", "--force", str(tree))
        except SyncError:
            pass
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            git_at(profile_dir, "worktree", "prune")
        except SyncError:
            pass

    changed = [entry[3:] for entry in
               git_at(target, "status", "--porcelain=v1", "-z", "-uall").split("\0") if entry]
    if not changed:
        print(f"{name}: already current ({tag})")
        return 0
    staged = [rel for rel in changed if rel not in LOCAL_RENDERED]
    if staged:
        git_at(target, "add", "-A", "--", *staged)
    git_at(target, "commit", "--quiet", "-m", f"Sync rules: {tag}", "-m",
           f"From {source_repo(manifest)}@{release[:STAMP_SHA_LENGTH]}.")
    commit = git_at(target, "rev-parse", "--short", "HEAD").strip()
    print(f"{name}: pulled {tag}, committed {commit} ({len(changed)} file(s)), not pushed")
    return 0


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
        "--ff-behind", action="store_true",
        help="with --rollout: fast-forward a clean target that is only behind its upstream, "
             "then render it",
    )
    parser.add_argument(
        "--parallel", type=int, metavar="N",
        help="with --rollout --push: push N targets at once, for this run only, instead of "
             "rollout.parallel",
    )
    parser.add_argument(
        "--pull", action="store_true",
        help="run in a target: render the profile's newest release tag (profile.yaml "
             "rollout.release_tag, the checkout named by git config rules.profile-path) "
             "into it and commit on the current branch. Never pushes",
    )
    parser.add_argument(
        "--print-source-sha", action="store_true",
        help="read-only: print the full sha of the commit a render stamps, which a rules "
             "release tag must point at",
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
        if args.pull and args.print_source_sha:
            raise SyncError("--pull and --print-source-sha are separate runs")
        if args.pull:
            return pull(args)
        if args.print_source_sha:
            if (args.target or args.self_only or args.write or args.check or args.no_fetch
                    or args.rollout is not None or args.push or args.break_lock
                    or args.ff_behind or args.parallel is not None):
                raise SyncError("--print-source-sha takes only --profile")
            refuse_dirty_source()
            print(source_commit(resolve_profile(args.profile)))
            return 0
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
        if args.push or args.break_lock or args.ff_behind or args.parallel is not None:
            raise SyncError("--push, --break-lock, --parallel and --ff-behind only apply to --rollout")

        if args.self_only:
            if args.target:
                raise SyncError("--self takes no target")
            cfg = self_config(manifest)
            name = source_repo(manifest)
            repo = resolve_profile(args.profile)
            folder = False
        else:
            if not args.target:
                raise SyncError("a target is required unless --self is given")
            targets = manifest.get("targets") or {}
            if args.target in (manifest.get("tracked") or {}):
                raise SyncError(f"{args.target} is tracked, not rendered")
            if args.target not in targets:
                raise SyncError(f"'{args.target}' is not in {PROFILE_NAME}")
            cfg = targets[args.target] or {}
            if cfg.get("skip"):
                raise SyncError(f"'{args.target}' is marked skip in {PROFILE_NAME}")
            name = args.target
            repo = args.root / args.target
            # A plain folder has no repository to refuse, and no git is run against it.
            folder = is_folder_target(cfg)
            if folder:
                if not repo.is_dir():
                    raise SyncError(f"{repo} is not a folder")
            elif not (repo / ".git").exists():
                raise SyncError(f"{repo} is not a git repository")

        profile_dir = resolve_profile(args.profile)
        sha = source_sha(not args.no_fetch, profile_dir)
        # The profile rendering itself stamps no SHA - see STAMP_UNPINNED. A target keeps it.
        plan = build_plan(name, cfg, defaults, None if args.self_only else sha, manifest,
                          profile_dir)
        report_drops(plan)
        if args.check:
            drift = permission_problems(profile_dir)
            if drift:
                raise SyncError("the permissions and the tool-methods table disagree:\n  "
                                + "\n  ".join(drift))
        if args.self_only:
            plan = {k: v for k, v in plan.items() if k not in never_write(manifest)}

        print(f"{source_repo(manifest)}@{sha} -> {name}  ({len(plan)} files)")
        # Orphan and foreign detection always use the unfiltered plan. A path
        # skipped for comparison is still a file this tool owns, and treating
        # it as an orphan would delete it on the next write.
        full_plan = plan
        if args.check:
            plan = {k: v for k, v in plan.items() if k not in LOCAL_RENDERED}
        if write and not folder:
            refuse_orphan_readers(repo, find_orphans(repo, full_plan), full_plan)
        ident = identity(manifest)
        changed = emit(repo, plan, write, ident=ident, **({"git": False} if folder else {}))
        if not folder:
            changed += ensure_scratch_ignored(repo, write)
            changed += ensure_pycache_ignored(repo, write)
            changed += ensure_claude_local_ignored(repo, write)
            changed += ensure_claude_worktrees_ignored(repo, write)
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
        readers: list[str] = []
        if write and folder:
            # No tracked files to read an orphan: a folder has no index.
            for rel in orphans:
                (repo / rel).unlink()
                print(f"  removed orphan {rel}")
        elif write:
            remove_orphans(repo, orphans, full_plan,
                           on_remove=lambda rel: print(f"  removed orphan {rel}"))
        else:
            for rel in orphans:
                print(f"  orphan (would remove): {rel}")
            if not folder:
                readers = orphan_readers(repo, orphans, full_plan)
                report_orphan_readers(readers)

        print()
        for line in resident_report(repo, selected_tools(manifest)):
            print(line)

        foreign = find_foreign(repo, full_plan)
        if foreign:
            print(f"\n[WARN] {len(foreign)} hand-written file(s) in rendered directories:")
            for rel in foreign:
                print(f"  {rel}")
            print("  Not touched - sync did not create them. They load alongside the")
            print("  rendered rules, so reconcile or remove them by hand.")

        if args.check:
            # Foreign files are deliberately not a failure: sync does not own them.
            if changed or orphans or readers:
                print(
                    f"\n[FAIL] {changed} file(s) differ and {len(orphans)} orphan(s) remain"
                    f"{f', {len(readers)} still read' if readers else ''}. "
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
