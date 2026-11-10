#!/usr/bin/env python3
################################################################################
# File: setup_profile.py
# Path: {PROJECT_ROOT}/setup_profile.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-06
# Description: The setup process. Creates a profile from the
#              example, asks each capability file's setup questions (or reads
#              them from --answers), hands features to the consent command,
#              shows a diff before a re-run writes, and finishes with a dry-run
#              render naming what is dropped and what is still to build.
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
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

import consent
import sync

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "examples" / "profile" / sync.PROFILE_NAME
# Everything an answers file may carry. features: belongs to the consent command alone.
ANSWER_FILE_KEYS = {"identity", "answers"}
IDENTITY_KEYS = {"name", "email"}
# A dry run renders nothing to commit, so no real source commit is stamped.
DRY_RUN_SHA = "0000000"

Ask = Callable[[str, str, "str | None"], str]
Confirm = Callable[[str], bool]
Consent = Callable[[Path], int]

# Run in order after profile.yaml is written, each given the profile folder. A post-create
# check, such as a hook launch check, is added here rather than built into setup.
POST_CREATE: tuple[Callable[[Path], None], ...] = ()


class SetupError(Exception):
    pass


def console_ask(key: str, prompt: str, current: str | None) -> str:
    print(f"\n{key}: {prompt}")
    if current:
        print(f"  Current: {current}. Enter keeps it.")
    try:
        return input("> ")
    except EOFError as error:
        raise SetupError("input closed before every question was answered. "
                         "Use --answers <file> to run without a console") from error


def console_confirm(diff: str) -> bool:
    try:
        return input("Type yes to write these changes: ").strip() == "yes"
    except EOFError:
        return False


def run_consent(folder: Path) -> int:
    return consent.main(["--profile", str(folder), "--init"])


def prompts() -> list[tuple[str, dict]]:
    """(answer key, question) for every setup question, in file order, then question order."""
    sync.setup_questions()
    found = []
    for path in sorted(sync.CAPABILITIES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found += [(f"{path.stem}.{q['id']}", q) for q in data.get("setup") or []]
    return found


def collect(current: dict, ask: Ask) -> tuple[dict, dict]:
    """Identity and answers typed at the prompts. A blank answer keeps what is there."""
    identity = dict(current.get("identity") or {})
    for field in sorted(IDENTITY_KEYS, reverse=True):
        typed = ask(f"identity.{field}", f"The commit {field} for every target.",
                    identity.get(field)).strip()
        if typed:
            identity[field] = typed
    answers = dict(current.get("answers") or {})
    for key, question in prompts():
        prompt = (f"{question.get('ask')}\n  Why: {question.get('why')}\n"
                  f"  For example: {question.get('example')}")
        typed = ask(key, prompt, answers.get(key)).strip()
        if typed:
            answers[key] = typed
    return identity, answers


def from_file(path: Path, current: dict) -> tuple[dict, dict]:
    """Identity and answers from an --answers file, over what the profile already holds."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SetupError(f"{path} must be a mapping of identity: and answers:")
    extra = sorted(str(key) for key in set(data) - ANSWER_FILE_KEYS)
    if extra:
        raise SetupError(f"{path}: {', '.join(extra)} cannot be set by setup. An answers file "
                         "holds identity: and answers: only; features are set by consent.py")
    identity, answers = data.get("identity") or {}, data.get("answers") or {}
    if not isinstance(identity, dict) or not set(identity) <= IDENTITY_KEYS:
        raise SetupError(f"{path}: identity: must hold name: and email: only")
    if not isinstance(answers, dict):
        raise SetupError(f"{path}: answers: must be a mapping")
    return ({**(current.get("identity") or {}), **identity},
            {**(current.get("answers") or {}), **answers})


def render_block(key: str, value: dict) -> str:
    return yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True, width=1000)


def replace_block(text: str, key: str, block: str) -> str:
    """profile.yaml text with one top-level block replaced, or appended. The text is
    edited rather than re-dumped, so its comments survive.

    The block runs from the `key:` line to the next line that is neither indented nor blank.
    """
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(rf"{key}:(\s|$)", line)), None)
    if start is None:
        return text.rstrip("\n") + "\n\n" + block
    end = scan = start + 1
    while scan < len(lines) and (lines[scan].startswith(" ") or not lines[scan].strip()):
        scan += 1
        if lines[scan - 1].startswith(" "):
            end = scan
    return "".join(lines[:start]) + block + "".join(lines[end:])


def report(folder: Path, answers: dict) -> int:
    """The dry-run render: what each target would get, what is dropped, what is unbuilt.
    0 when it rendered, 3 when it could not be checked."""
    manifest = sync.load_profile(folder)
    questions = sync.setup_questions()
    bound = dict.fromkeys(manifest.get("capabilities") or {}, "")
    for key in sync.unbuilt_answers(answers, questions, bound):
        names = ", ".join(sorted(questions[key.partition(".")[0]].capabilities))
        print(f"build: {key} - author a profile skill and bind it to one of: {names}")
    targets = manifest.get("targets") or {}
    try:
        if not targets:
            raise sync.SyncError(f"{sync.PROFILE_NAME} has no targets")
        for name, cfg in targets.items():
            plan = sync.build_plan(name, cfg or {}, manifest.get("defaults") or {}, DRY_RUN_SHA,
                                   manifest, profile_dir=folder)
            print(f"[OK] render: {name} would get {len(plan)} file(s)")
            sync.report_drops(plan)
    except sync.SyncError as error:
        print(f"[UNKNOWN] render not checked: {error}")
        return 3
    return 0


def run_setup(folder: Path, *, answers_file: Path | None = None, ask: Ask = console_ask,
              confirm: Confirm = console_confirm, consent_init: Consent = run_consent) -> int:
    """Create or update the profile in `folder`. 0 done, 1 refused, 3 written but the
    render could not be checked."""
    folder = Path(folder)
    path = folder / sync.PROFILE_NAME
    try:
        existing = path.is_file()
        if not existing and folder.exists() and any(folder.iterdir()):
            raise SetupError(f"{folder} is not empty and holds no {sync.PROFILE_NAME}. Setup "
                             "creates a profile only in an empty or new folder")
        text = (path if existing else EXAMPLE).read_text(encoding="utf-8")
        current = yaml.safe_load(text) or {}
        if answers_file is None:
            identity, answers = collect(current, ask)
        else:
            identity, answers = from_file(answers_file, current)
        sync.identity({"identity": identity})
        sync.validate_answers({"answers": answers}, sync.setup_questions())
        proposed = replace_block(text, "identity", render_block("identity", identity))
        proposed = replace_block(proposed, "answers", render_block("answers", answers))
        write = not existing
        if existing and proposed != text:
            diff = "".join(difflib.unified_diff(text.splitlines(keepends=True),
                                                proposed.splitlines(keepends=True),
                                                str(path), "proposed"))
            print(diff)
            if not confirm(diff):
                raise SetupError("not confirmed. Nothing was written")
            write = True
        if write:
            folder.mkdir(parents=True, exist_ok=True)
            consent.write_atomically(path, proposed)
            print(f"[OK] written: {path}")
            if not existing:
                # The example's targets name seeds it ships, such as the estate map.
                shutil.copytree(EXAMPLE.parent / "seeds", folder / "seeds")
            for step in POST_CREATE:
                step(folder)
        else:
            print(f"[OK] nothing to change in {path}")
        if (answers_file is None and consent.read_lock(folder) is None
                and consent.known_gates(folder)):
            if consent_init(folder) != 0:
                print("[WARN] consent did not complete, so every feature stays off. Run "
                      f"`python core/consent.py --init --profile {folder}` to set them")
    except (SetupError, sync.SyncError, consent.ConsentError, OSError, yaml.YAMLError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    return report(folder, answers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup_profile.py",
        description="Create or update a profile: identity, setup answers, then features "
                    "through consent.py. Exit 0 done, 1 refused, 3 written but the render "
                    "could not be checked.")
    parser.add_argument("--profile", type=Path, required=True,
                        help="the profile folder: new, empty, or holding profile.yaml")
    parser.add_argument("--answers", type=Path,
                        help="answer from this YAML file instead of the console. Holds "
                             "identity: and answers: only; features stay off")
    args = parser.parse_args(argv)
    return run_setup(args.profile.resolve(), answers_file=args.answers)


if __name__ == "__main__":
    sys.exit(main())
