#!/usr/bin/env python3
################################################################################
# File: toolboxctl.py
# Path: {PROJECT_ROOT}/toolboxctl.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-15
# Description: One entry point for a profile's vendored core.
#              Run as python core/toolboxctl.py <subcommand>. Owns no logic:
#              each subcommand delegates to the function its own ticket built.
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
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

import consent
import gate_lists
import setup_profile
import sync
import vendor

HERE = Path(__file__).resolve().parent
# Subcommands whose arguments belong to the script they delegate to.
PASS_THROUGH = ("flags", "setup", "gate-lists")
GIT_TIMEOUT = 60
# The two commit messages init makes, and the commands it runs or prints as steps.
CREATE_MESSAGE = "Create the profile"
RENDER_MESSAGE = "Render the profile"
RENDER_COMMAND = "python core/sync.py --profile . --self --write"
# A new profile has nothing upstream to be behind, and its remote may be empty, so init's own
# render does not fetch.
FIRST_RENDER_COMMAND = RENDER_COMMAND + " --no-fetch"
LOCK_COMMAND = "python core/consent.py --profile . --init"
TARGETS_STEP = ("In profile.yaml, replace the example targets (example-app, example-scratch)"
                " with your own repositories, in any editor.")
PUSH_COMMAND = "git push -u origin main"
PREVIEW_TIMEOUT = 600
RENDER_TIMEOUT = 600
# A preview renders nothing to commit, so no real source commit is stamped.
PREVIEW_SHA = "0000000"
DIFF_LINES = 40


class UpdateError(Exception):
    """A refusal before anything was changed. The message names what was wrong."""


class UpdateUnknown(Exception):
    """Whether a newer release exists could not be established."""


def with_profile(rest: list[str], profile: Path) -> list[str]:
    """`rest` led by --profile <profile>, unless it already names one."""
    if any(arg == "--profile" or arg.startswith("--profile=") for arg in rest):
        return rest
    return ["--profile", str(profile), *rest]


def version(core: Path) -> int:
    """Print the vendored source, tag and SHA. A record that cannot be read is an error."""
    try:
        record = vendor.read_record(core)
    except vendor.VendorError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print(f"{record.source} {record.tag or 'by SHA'} {record.sha}")
    return 0


def check(core: Path) -> int:
    """--check-core, then --check-updates only if the core matches its record."""
    if vendor.check_report(core) != 0:
        print("[ERROR] core/ does not match VENDORED, so no update check was run",
              file=sys.stderr)
        return 1
    return vendor.updates_report(core)


def git(profile: Path, *args: str) -> subprocess.CompletedProcess:
    """git in the profile, with no inherited GIT_ variables steering it elsewhere."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(("git", *args), cwd=profile, env=env, capture_output=True,
                          text=True, timeout=GIT_TIMEOUT)


def require_committed_core(profile: Path) -> None:
    """Refuse unless git can restore core/ exactly: the profile is a repository's top
    level, and core/ is tracked with nothing uncommitted."""
    top = git(profile, "rev-parse", "--show-toplevel")
    try:
        is_top = top.returncode == 0 and Path(top.stdout.strip()).samefile(profile)
    except OSError:
        is_top = False
    if not is_top:
        raise UpdateError(f"{profile} is not the top level of a git repository, so a "
                          "replaced core/ could not be restored from git")
    vendored = f"{vendor.CORE_DIR}/{vendor.VENDORED}"
    if git(profile, "ls-files", "--error-unmatch", "--", vendored).returncode != 0:
        raise UpdateError(f"{vendored} is not committed, so there is no core/ to restore to")
    status = git(profile, "status", "--porcelain", "--", vendor.CORE_DIR)
    if status.returncode != 0:
        raise UpdateError(f"git status failed in {profile}: {status.stderr.strip()}")
    if status.stdout.strip():
        raise UpdateError(f"{vendor.CORE_DIR}/ has uncommitted changes. Commit or discard "
                          "them first: a no restores core/ from git and would lose them")


def choose_tag(core: Path, tag: str | None) -> str | None:
    """The tag to vendor: the one named, else the newest release. None means up to date."""
    if tag is not None:
        if not vendor.TAG.fullmatch(tag):
            raise UpdateError(f"{tag!r} is not a release tag; releases are vX.Y.Z")
        return tag
    try:
        result = vendor.check_updates(core, vendor.http_get)
    except vendor.LookupFailed as error:
        raise UpdateUnknown(f"could not check for updates: {error}") from None
    if result.warnings:
        raise UpdateUnknown("; ".join(result.warnings))
    if not result.record.tag:
        raise UpdateUnknown(f"vendored by SHA {result.record.sha[:12]}, so which release is "
                            "newer is unknown. Name the tag: update vX.Y.Z")
    return result.newer[0] if result.newer else None


def console_confirm() -> bool:
    """A typed yes at the console within consent's timeout. No console or silence is a no."""
    try:
        return consent.ask(consent.open_console(), consent.TIMEOUT_SECONDS)
    except consent.ConsentError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return False


def run_preview(core: Path, root: Path | None) -> int:
    """The new core's own preview, in a child process, so the code on disk is what runs.
    The old core is already imported in this one."""
    command = [sys.executable, str(core / "toolboxctl.py"), "preview"]
    if root is not None:
        command += ["--root", str(root)]
    try:
        return subprocess.run(command, cwd=core.parent, timeout=PREVIEW_TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        print(f"[ERROR] the preview did not finish within {PREVIEW_TIMEOUT} seconds",
              file=sys.stderr)
    except OSError as error:
        print(f"[ERROR] the preview could not start: {error}", file=sys.stderr)
    return 1


def render_command(core: Path, no_fetch: bool = False) -> list[str]:
    """The profile's own render, from the core on disk. The same line a person runs by hand."""
    return [sys.executable, str(core / "sync.py"), "--profile", str(core.parent),
            "--self", "--write", *(["--no-fetch"] if no_fetch else [])]


def run_render(core: Path, no_fetch: bool = False) -> int:
    """Render the profile from the new core, in a child process, so the code on disk is
    what runs. A failure, a timeout or a start failure is 1; the output is left for review."""
    try:
        code = subprocess.run(render_command(core, no_fetch), cwd=core.parent,
                              timeout=RENDER_TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        print(f"[ERROR] the render did not finish within {RENDER_TIMEOUT} seconds",
              file=sys.stderr)
        return 1
    except OSError as error:
        print(f"[ERROR] the render could not start: {error}", file=sys.stderr)
        return 1
    if code != 0:
        print(f"[ERROR] the render exited with {code}", file=sys.stderr)
        return 1
    return 0


def commit_core(profile: Path, old: str | None, new: str) -> int:
    """Commit core/ and nothing else, as one change. The profile's git identity is the
    profile's identity, which update checked before the swap."""
    message = f"Update core from {old or 'an untagged release'} to {new}"
    for step in (("add", "-A", "--", vendor.CORE_DIR),
                 ("commit", "-m", message, "--", vendor.CORE_DIR)):
        result = git(profile, *step)
        if result.returncode != 0:
            print(f"[ERROR] git {step[0]} failed, so core/ is swapped but not committed "
                  f"and nothing was rendered: {(result.stderr or result.stdout).strip()}",
                  file=sys.stderr)
            return 1
    return 0


def restore_core(profile: Path, core: Path) -> int:
    """Put core/ back to what the profile's HEAD holds, then prove it matches VENDORED."""
    for step in (("restore", "--source=HEAD", "--staged", "--worktree", "--", vendor.CORE_DIR),
                 ("clean", "-fdq", "--", vendor.CORE_DIR)):
        result = git(profile, *step)
        if result.returncode != 0:
            print(f"[ERROR] git {step[0]} failed, so core/ may be part-replaced: "
                  f"{result.stderr.strip()}", file=sys.stderr)
            return 1
    try:
        record = vendor.check_core(core)
    except vendor.VendorError as error:
        print(f"[ERROR] core/ was restored from git but does not match VENDORED: {error}",
              file=sys.stderr)
        return 1
    print(f"[OK] core/ restored to {record.tag or record.sha[:12]}. Nothing was kept.")
    return 1


def update(core: Path, tag: str | None, root: Path | None) -> int:
    """Swap in a newer core, preview its render, and keep it only on a typed yes. A yes
    commits core/ as one change, as the profile identity, then renders the profile from it."""
    profile = core.parent
    try:
        require_committed_core(profile)
        sync.verify_identity(profile, sync.identity(sync.load_profile(profile)))
        record = vendor.check_core(core)
        chosen = choose_tag(core, tag)
    except UpdateUnknown as error:
        print(f"[UNKNOWN] {error}. Nothing was changed.", file=sys.stderr)
        return 3
    except (UpdateError, vendor.VendorError, sync.SyncError, OSError, yaml.YAMLError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    if chosen is None:
        print(f"[OK] {record.tag} is the newest release on {record.source}; nothing changed")
        return 0
    if vendor.vendor_report(profile, f"{record.source}@{chosen}") != 0:
        return 1
    if run_preview(core, root) not in (0, 3):
        print("[ERROR] the preview failed, so the new core is not kept", file=sys.stderr)
        return restore_core(profile, core)
    print(f"Type yes to keep {chosen} in core/. Anything else, or "
          f"{consent.TIMEOUT_SECONDS:g} seconds of silence, restores {record.tag}.")
    sys.stdout.flush()
    if not console_confirm():
        return restore_core(profile, core)
    if commit_core(profile, record.tag, chosen) != 0:
        return 1
    if run_render(core) != 0:
        print(f"[ERROR] core/ is committed at {chosen} but the profile was not rendered. "
              f"Run by hand from {profile}: {' '.join(render_command(core))}", file=sys.stderr)
        return 1
    print(f"[OK] core/ is now {chosen}, committed as one change, and the profile is rendered "
          "from it. The rendered output is left uncommitted for review.")
    return 0


def unstamped(text: str) -> list[str]:
    """text's lines without its stamp, which differs on every render."""
    return [line for line in text.splitlines() if not sync.STAMP_RE.search(line)]


def preview(core: Path, root: Path | None) -> int:
    """Each target's render difference, stamps excluded. 0 all previewed, 1 refused, 3 some
    target not previewed. Targets sit beside the profile unless root says otherwise."""
    profile = core.parent
    root = profile.parent if root is None else root
    try:
        manifest = sync.load_profile(profile)
    except (sync.SyncError, OSError, yaml.YAMLError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    targets = manifest.get("targets") or {}
    if not targets:
        print(f"[ERROR] {sync.PROFILE_NAME} has no targets to preview", file=sys.stderr)
        return 1
    unknown = False
    for name, cfg in targets.items():
        cfg = cfg or {}
        if cfg.get("skip"):
            continue
        repo = root / name
        if not repo.is_dir():
            print(f"[UNKNOWN] {name}: not previewed, {repo} is missing")
            unknown = True
            continue
        try:
            plan = sync.build_plan(name, cfg, manifest.get("defaults") or {}, PREVIEW_SHA,
                                   manifest, profile_dir=profile)
            changed = 0
            for rel, content in sorted(plan.items()):
                path = repo / rel
                before = unstamped(path.read_text(encoding="utf-8") if path.is_file() else "")
                after = unstamped(content)
                if before == after:
                    continue
                changed += 1
                print(f"\n--- {name}/{rel}")
                diff = difflib.unified_diff(before, after, "current", "rendered", lineterm="")
                for line in list(diff)[:DIFF_LINES]:
                    print(line)
        except (sync.SyncError, OSError, UnicodeDecodeError) as error:
            print(f"[UNKNOWN] {name}: not previewed, {error}")
            unknown = True
            continue
        print(f"[OK] {name}: {changed} file(s) would change")
    return 3 if unknown else 0


class StepFailed(Exception):
    """A step after setup did not complete; carries the one step to run next."""

    def __init__(self, message: str, next_step: str):
        super().__init__(message)
        self.next_step = next_step


def parse_targets(text: str, profile: Path) -> list[str]:
    """Folder names beside the profile, one per line. Refuses an empty list, a path, a name
    holding anything but letters, digits, - _ and ., and a repeat."""
    names = [line.strip() for line in text.splitlines() if line.strip()]
    if not names:
        raise setup_profile.SetupError("name at least one target repository folder")
    for name in names:
        if name in (".", "..") or not setup_profile.OWNER_REPO_PATTERN.fullmatch(name):
            raise setup_profile.SetupError(
                f"{name!r} is not a folder name beside the profile. Use letters, digits, "
                "- _ and ., with no path and no spaces")
        if name == profile.name:
            raise setup_profile.SetupError(f"{name!r} is this profile's own folder")
    if len(set(names)) != len(names):
        raise setup_profile.SetupError("a target is named twice")
    return names


def ask_targets(profile: Path) -> list[str]:
    """The target folders, asked at the console until one answer is accepted."""
    prompt = (f"The folders of this profile's target repositories, beside {profile.name} in "
              f"{profile.parent}. One folder name per line. They replace the example targets "
              "in profile.yaml.")
    for _ in range(setup_profile.MAX_ASKS):
        typed = setup_profile.console_ask("targets", prompt, None)
        try:
            names = parse_targets(typed, profile)
        except setup_profile.SetupError as error:
            print(f"REFUSED: {error}")
            continue
        for name in names:
            if not (profile.parent / name).is_dir():
                print(f"[NOTE] {profile.parent / name} does not exist yet. It is needed "
                      "for that target's first sync, not for this step.")
        print("  -> targets goes to profile.yaml, in place of the example targets.")
        return names
    raise setup_profile.SetupError(
        f"targets was refused {setup_profile.MAX_ASKS} times")


def write_targets(profile: Path, names: list[str]) -> None:
    """Replace profile.yaml's targets: block with `names`, by the writer setup uses."""
    path = profile / sync.PROFILE_NAME
    text = path.read_text(encoding="utf-8")
    block = setup_profile.render_block("targets", {name: {} for name in names})
    consent.write_atomically(path, setup_profile.replace_block(text, "targets", block))
    print(f"[OK] targets written to {path}: {', '.join(names)}")


def commit_all(profile: Path, message: str) -> None:
    """Stage everything and commit it with `message`, as the printed steps do."""
    for args in (("add", "-A"), ("commit", "-q", "-m", message)):
        result = git(profile, *args)
        if result.returncode != 0:
            raise StepFailed(f"git {' '.join(args[:1])} failed: "
                             f"{(result.stderr or result.stdout).strip()}",
                             commit_step(message))
    print(f"[OK] committed: {message}")


def commit_step(message: str) -> str:
    return f"Commit it:\n       git add -A\n       git commit -m \"{message}\""


def after_setup(profile: Path) -> int:
    """Everything init does once setup has finished: targets, the profile commit, the
    render, the render commit. Nothing is ever removed here. A failure or Ctrl+C prints the
    one step to run next and exits non-zero."""
    step = TARGETS_STEP
    try:
        write_targets(profile, ask_targets(profile))
        step = commit_step(CREATE_MESSAGE)
        commit_all(profile, CREATE_MESSAGE)
        step = (f"Render the profile into itself, then commit that too:\n"
                f"       {FIRST_RENDER_COMMAND}\n"
                f"       git add -A\n       git commit -m \"{RENDER_MESSAGE}\"")
        if consent.read_lock(profile) is None:
            raise StepFailed("the push gates are not locked, and a render needs the lock. "
                             "Setup did not lock them, because its answers came from a file",
                             f"Lock the push gates, then render. In {profile}, run:\n"
                             f"       {LOCK_COMMAND}\n       {FIRST_RENDER_COMMAND}\n"
                             f"       git add -A\n       git commit -m \"{RENDER_MESSAGE}\"")
        if run_render(profile / vendor.CORE_DIR, no_fetch=True) != 0:
            raise StepFailed("the render did not finish", step)
        commit_all(profile, RENDER_MESSAGE)
    except KeyboardInterrupt:
        print(f"\n[NOTE] stopped. The profile is written and was not removed.\nNext step\n"
              f"  {step}", file=sys.stderr)
        return 130
    except StepFailed as error:
        print(f"[ERROR] {error}. The profile is written and was not removed.\nNext step\n"
              f"  {error.next_step}", file=sys.stderr)
        return 1
    except (setup_profile.SetupError, sync.SyncError, consent.ConsentError, OSError,
            subprocess.SubprocessError, yaml.YAMLError) as error:
        print(f"[ERROR] {error}. The profile is written and was not removed.\nNext step\n"
              f"  {step}", file=sys.stderr)
        return 1
    print(f"\n{consent.TOOLS_NOTE}\nNext step\n  Push it:\n       {PUSH_COMMAND}")
    return 0


def init(core: Path, profile: Path, source: str, answers: Path | None,
         fetch: vendor.Fetch | None = None, setup_only: bool = False) -> int:
    """Bootstrap a new profile from a release archive: vendor the tag this archive carries
    into <profile>/core/, then run setup. Refuses, changing nothing, where a profile is
    already there. Run from the archive, not from a vendored core."""
    profile = profile.resolve()
    core_dir, manifest = profile / vendor.CORE_DIR, profile / sync.PROFILE_NAME
    if ((core_dir.exists() or core_dir.is_symlink())
            and not (manifest.exists() or manifest.is_symlink())):
        print(f"[ERROR] {core_dir} exists but {manifest} does not: this is an unfinished "
              f"init. Delete {core_dir}, then run init again. Nothing was changed.",
              file=sys.stderr)
        return 1
    for name in (vendor.CORE_DIR, sync.PROFILE_NAME):
        if (profile / name).exists() or (profile / name).is_symlink():
            print(f"[ERROR] {profile / name} already exists, so this is not a new profile. "
                  "Nothing was changed. Update an existing profile with toolboxctl update.",
                  file=sys.stderr)
            return 1
    inside = git(profile, "rev-parse", "--is-inside-work-tree") if profile.is_dir() else None
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        print(f"[ERROR] {profile} is not a git work tree. Create the repository first. "
              "Nothing was changed.", file=sys.stderr)
        return 1
    try:
        tag = "v" + (core / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as error:
        print(f"[ERROR] could not read this archive's VERSION: {error}", file=sys.stderr)
        return 1
    before = {entry.name for entry in profile.iterdir()}
    try:
        record, notes = vendor.vendor_core(profile, f"{source}@{tag}", fetch or vendor.http_get)
    except vendor.VendorError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    for note in notes:
        print(f"[NOTE] {note}")
    print(f"[OK] vendored {record.source} {record.tag} {record.sha[:12]} into "
          f"{profile / vendor.CORE_DIR}")
    try:
        code = setup_profile.main(["--profile", str(profile),
                                   *(["--answers", str(answers)] if answers else [])])
    except KeyboardInterrupt:
        # Ctrl+C is the operator stopping, not a crash: take back what was written, say so,
        # and give the shell's 130 with no traceback.
        remove_unfinished(profile, before)
        return 130
    except BaseException:
        remove_unfinished(profile, before)
        raise
    # 1 is a refusal. 3 means the profile was written and only its render was not checked,
    # so it is a finished profile and stays.
    if code == 1:
        remove_unfinished(profile, before)
    if code in (0, 3):
        if setup_only:
            print(next_steps(profile))
        else:
            return after_setup(profile)
    return code


def remove_unfinished(profile: Path, before: set[str]) -> None:
    """Take back what a failed or cancelled init wrote: every top-level entry that was not
    in the folder when init started (core/, profile.yaml, the seeds/ setup copies in), so a
    retry starts from the same folder. Nothing that was there before is touched."""
    def writable(func, path, _error):
        os.chmod(path, 0o700)
        func(path)
    removed = []
    for entry in sorted(profile.iterdir()):
        if entry.name in before:
            continue
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        else:
            shutil.rmtree(entry, onerror=writable)
        removed.append(entry.name)
    print(f"[NOTE] init did not finish; removed {', '.join(removed) or 'nothing'} from "
          f"{profile}. Run init again.", file=sys.stderr)


def next_steps(profile: Path) -> str:
    """What to do after init wrote the profile, and where the answers went."""
    return ("\nNext steps\n"
            f"  Your answers are in {profile / sync.PROFILE_NAME}, under identity:, source:, "
            "answers: and the leak-gate keys. Edit that file in any editor to change one.\n"
            "  The build: lines above list what is still to author. They are not errors.\n"
            f"  {consent.TOOLS_NOTE}\n"
            + ("" if consent.read_lock(profile) is not None else
               "  0. Lock the push gates. Setup did not, because its answers came from a file."
               f" In {profile}, run:\n"
               "       python core/consent.py --profile . --init\n")
            + f"  1. Review the render. In {profile}, run:\n"
            "       git status\n"
            f"  2. {TARGETS_STEP}\n"
            f"  3. {commit_step(CREATE_MESSAGE)}\n"
            "  4. Render the profile into itself, then commit that too:\n"
            f"       {RENDER_COMMAND}\n"
            "       git add -A\n"
            f"       git commit -m \"{RENDER_MESSAGE}\"\n"
            "  5. Push it:\n"
            f"       {PUSH_COMMAND}\n"
            "  6. Confirm the core from inside the profile:\n"
            "       python core/toolboxctl.py version")


def build_parser() -> argparse.ArgumentParser:
    """The subcommands, each help line naming what running it changes."""
    parser = argparse.ArgumentParser(
        prog="toolboxctl.py",
        description="One entry point for a profile's vendored core. Run as "
                    "python core/toolboxctl.py <subcommand>.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")
    init_parser = sub.add_parser(
        "init", help="bootstrap a new profile: vendor the release this archive is into "
                     "<profile>/core/ and run setup. The one subcommand run from a release "
                     "archive, not core/. Writes core/ and profile.yaml in a new git "
                     "repository; refuses where either exists")
    init_parser.add_argument("--profile", type=Path, required=True,
                             help="the new, empty git repository")
    init_parser.add_argument("--source", required=True, metavar="OWNER/REPO",
                             help="the GitHub repository this archive was released from")
    init_parser.add_argument("--answers", type=Path, default=None,
                             help="answer setup from this YAML file instead of the console. "
                                  "A file with no identity: asks identity at the console")
    init_parser.add_argument("--setup-only", action="store_true",
                             help="stop after setup and print the remaining steps, instead of "
                                  "asking for the targets, committing and rendering")
    sub.add_parser("version", help="print the source, tag and SHA core/VENDORED records; "
                                   "reads only")
    sub.add_parser("check", help="verify core/ against VENDORED, then list newer releases. "
                                 "Reads core/ and the network; changes nothing")
    update_parser = sub.add_parser(
        "update", help="replace core/ with the newest or a named release and preview its "
                       "render. After a typed yes it commits core/ as one change and renders "
                       "the profile, leaving the rendered output uncommitted; otherwise it "
                       "restores core/ from git and commits and renders nothing")
    update_parser.add_argument("tag", nargs="?", help="a vX.Y.Z release (default: the newest)")
    update_parser.add_argument("--root", type=Path, default=None,
                               help="folder holding the target repositories "
                                    "(default: the profile's parent)")
    # Run by update, from the new core, in a child process. Not listed in --help.
    preview_parser = sub.add_parser("preview")
    preview_parser.add_argument("--root", type=Path, default=None)
    sub.add_parser("flags", add_help=False,
                   help="change gate flags through consent.py. Writes profile.yaml and "
                        "profile.lock, after a typed yes")
    sub.add_parser("setup", add_help=False,
                   help="create or update the profile through setup_profile.py. Writes "
                        "profile.yaml, after confirming any change to an existing one")
    sub.add_parser("gate-lists", add_help=False,
                   help="write the one-way gate pattern files from profile.yaml. Writes the "
                        "two files named; prints counts, never patterns")
    return parser


def main(argv: list[str] | None = None, core: Path = HERE,
         fetch: vendor.Fetch | None = None) -> int:
    """Dispatch one subcommand and return its delegate's exit code."""
    parser = build_parser()
    args, rest = parser.parse_known_args(argv)
    if rest and args.command not in PASS_THROUGH:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
    if args.command == "init":
        return init(core, args.profile, args.source, args.answers, fetch, args.setup_only)
    if not (core / vendor.VENDORED).is_file():
        print(f"[ERROR] {core / vendor.VENDORED} does not exist. toolboxctl is meant for a "
              "profile's vendored core, run as python core/toolboxctl.py; in the source "
              "repository use sync.py directly.", file=sys.stderr)
        return 1
    if args.command == "version":
        return version(core)
    if args.command == "check":
        return check(core)
    if args.command == "update":
        return update(core, args.tag, args.root)
    if args.command == "preview":
        return preview(core, args.root)
    if args.command == "flags":
        return consent.main(with_profile(rest, core.parent))
    if args.command == "gate-lists":
        return gate_lists.main(with_profile(rest, core.parent))
    return setup_profile.main(with_profile(rest, core.parent))


if __name__ == "__main__":
    sys.exit(main())
