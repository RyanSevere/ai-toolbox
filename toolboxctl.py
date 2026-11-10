#!/usr/bin/env python3
################################################################################
# File: toolboxctl.py
# Path: {PROJECT_ROOT}/toolboxctl.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-06
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
import subprocess
import sys
from pathlib import Path

import yaml

import consent
import setup_profile
import sync
import vendor

HERE = Path(__file__).resolve().parent
# Subcommands whose arguments belong to the script they delegate to.
PASS_THROUGH = ("flags", "setup")
GIT_TIMEOUT = 60
PREVIEW_TIMEOUT = 600
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
    """Swap in a newer core, preview its render, and keep it only on a typed yes.
    Rendering is not part of it yet."""
    profile = core.parent
    try:
        require_committed_core(profile)
        record = vendor.check_core(core)
        chosen = choose_tag(core, tag)
    except UpdateUnknown as error:
        print(f"[UNKNOWN] {error}. Nothing was changed.", file=sys.stderr)
        return 3
    except (UpdateError, vendor.VendorError) as error:
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
    print(f"[OK] core/ is now {chosen}, not yet committed and not rendered. Commit core/ "
          "as one change; rendering from it is not part of update yet.")
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


def build_parser() -> argparse.ArgumentParser:
    """The subcommands, each help line naming what running it changes."""
    parser = argparse.ArgumentParser(
        prog="toolboxctl.py",
        description="One entry point for a profile's vendored core. Run as "
                    "python core/toolboxctl.py <subcommand>.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")
    sub.add_parser("version", help="print the source, tag and SHA core/VENDORED records; "
                                   "reads only")
    sub.add_parser("check", help="verify core/ against VENDORED, then list newer releases. "
                                 "Reads core/ and the network; changes nothing")
    update_parser = sub.add_parser(
        "update", help="replace core/ with the newest or a named release and preview its "
                       "render. Keeps it only after a typed yes; restores core/ from git "
                       "otherwise. Commits and renders nothing")
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
    return parser


def main(argv: list[str] | None = None, core: Path = HERE) -> int:
    """Dispatch one subcommand and return its delegate's exit code."""
    parser = build_parser()
    args, rest = parser.parse_known_args(argv)
    if rest and args.command not in PASS_THROUGH:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
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
    return setup_profile.main(with_profile(rest, core.parent))


if __name__ == "__main__":
    sys.exit(main())
