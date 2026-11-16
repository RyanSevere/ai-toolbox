#!/usr/bin/env python3
################################################################################
# File: setup_profile.py
# Path: {PROJECT_ROOT}/setup_profile.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-15
# Description: The setup process. Creates a profile from the
#              example, asks each capability file's setup questions (or reads
#              them from --answers), hands features to the consent command,
#              shows a diff before a re-run writes, and finishes with a dry-run
#              render naming what is dropped and what is still to build.
#              With --hooks off|on it does only the per-machine hooks switch:
#              a user environment variable on Windows, a marked block in
#              ~/.profile elsewhere, written after a typed yes.
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
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

import consent
import sync

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "examples" / "profile" / sync.PROFILE_NAME
# Everything an answers file may carry. features: belongs to the consent command alone.
ANSWER_FILE_KEYS = {"identity", "answers", "source", "personal", "profile_name", "leak_extra",
                    "not_onboarded"}
IDENTITY_KEYS = {"name", "email"}
SOURCE_FIELDS = ("repo", "key", "owner")
# An answer that says a question does not apply to this profile.
NOT_APPLICABLE = "n/a"
# An email at this suffix is the example's, never a real address.
EXAMPLE_EMAIL_SUFFIX = "example.invalid"
# The profile.yaml keys beside source: that the leak gates read, how each is typed at the
# console, and what is asked. A list is one entry per line; not_onboarded is `name: reason`.
LEAK_KINDS = {"personal": "list", "profile_name": "text", "leak_extra": "list",
              "not_onboarded": "map"}
SOURCE_ASKS = {
    "repo": "The name of this profile repository. It is the name in every generated stamp.",
    "key": "The prefix of an issue reference, such as ex-12.",
    "owner": "The GitHub owner of every repository in this profile.",
}
LEAK_ASKS = {
    "personal": "Repository names that belong to you and that the core must never mention. "
                "One per line. Answer n/a for none.",
    "profile_name": "A name for this profile that the core must never mention. Answer n/a "
                    "for none.",
    "leak_extra": "Further literal strings the leak gate must refuse. One per line. Answer "
                  "n/a for none.",
    "not_onboarded": "Repositories deliberately left out, each with the reason, one per line "
                     "as `name: reason`. Answer n/a for none.",
}
# A dry run renders nothing to commit, so no real source commit is stamped.
DRY_RUN_SHA = "0000000"


def _hooks_variable() -> str:
    """The off switch's name, read from the hook library so it is written in one place."""
    spec = importlib.util.spec_from_file_location("hookio", ROOT / "hooks" / "lib" / "hookio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OFF_VARIABLE


HOOKS_VARIABLE = _hooks_variable()
HOOKS_START = "# >>> ai-toolbox hooks switch >>>"
HOOKS_END = "# <<< ai-toolbox hooks switch <<<"
HOOKS_BLOCK = f"{HOOKS_START}\nexport {HOOKS_VARIABLE}=off\n{HOOKS_END}\n"
# A line that sources ~/.profile: `. ~/.profile`, `source "$HOME/.profile"`, inside an `if`, ...
HOOKS_SOURCES = re.compile(r"(?:^|[\s;&|(])(?:\.|source)\s+[\"']?(?:~|\$HOME|\$\{HOME\})/\.profile\b")
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002
BROADCAST_TIMEOUT_MS = 5000

# What a new profile repository holds before setup: its git folder and a vendored core.
NEW_REPOSITORY_ENTRIES = frozenset({".git", "core"})

Ask = Callable[[str, str, "str | None"], str]
Confirm = Callable[[str], bool]
Consent = Callable[[Path], int]

# Run in order after profile.yaml is written, each given the profile folder. A post-create
# check, such as a hook launch check, is added here rather than built into setup.
POST_CREATE: tuple[Callable[[Path], None], ...] = ()


class SetupError(Exception):
    pass


def one_line(key: str) -> bool:
    """A name, an email or a repository is one line; every other answer may take several."""
    return key.startswith(("identity.", "source.")) or key == "profile_name"


def console_ask(key: str, prompt: str, current: str | None) -> str:
    """One answer at the console. A one-line field ends at its first line; any other ends at
    an empty line, so a pasted paragraph is one answer."""
    print(f"\n{key}: {prompt}")
    if current:
        print(f"  Current: {current}. Enter keeps it.")
    if not one_line(key):
        print("  Answer on as many lines as you need, then finish with an empty line. "
              "To answer from a file instead, run with --answers <file>.")
    lines: list[str] = []
    while True:
        try:
            line = input("> ")
        except EOFError as error:
            if lines:
                break
            raise SetupError("input closed before every question was answered. "
                             "Use --answers <file> to run without a console") from error
        if one_line(key):
            return line
        if not line.strip():
            break
        lines.append(line.rstrip())
    return "\n".join(lines)


def git_config(key: str, folder: Path | None = None) -> str:
    """`git config <key>` as git would read it in `folder`, or empty when it is unset or git
    cannot be run."""
    try:
        result = subprocess.run(
            ["git", "config", "--get", key], capture_output=True, text=True, timeout=10,
            cwd=folder if folder is not None and folder.is_dir() else None)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


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


def example_profile() -> dict:
    """The example profile's values: every one a placeholder that must not survive setup."""
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")) or {}


def parse_list(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [] if [line.lower() for line in lines] == [NOT_APPLICABLE] else lines


def parse_map(text: str) -> dict[str, str]:
    found = {}
    for line in parse_list(text):
        name, colon, reason = line.partition(":")
        if not colon or not name.strip() or not reason.strip():
            raise SetupError(f"not_onboarded: {line!r} is not `name: reason`")
        found[name.strip()] = reason.strip()
    return found


def parse_text(text: str) -> str:
    return "" if text.strip().lower() == NOT_APPLICABLE else text.strip()


PARSERS = {"list": parse_list, "map": parse_map, "text": parse_text}


def shown(value) -> str | None:
    """A current value as the console prints it."""
    if isinstance(value, dict):
        value = [f"{name}: {reason}" for name, reason in value.items()]
    if isinstance(value, list):
        value = ", ".join(value)
    return str(value) if value else None


def collect(current: dict, ask: Ask, folder: Path | None = None) -> tuple[dict, dict, dict]:
    """Identity, answers and the other profile blocks typed at the prompts. A blank answer
    keeps what is there, except that an identity still holding the example's is offered the
    git config's instead. The third value holds only the blocks the profile.yaml keys named
    source, personal, profile_name, leak_extra and not_onboarded that were typed."""
    example = example_profile()
    identity = dict(current.get("identity") or {})
    for field in sorted(IDENTITY_KEYS, reverse=True):
        default = identity.get(field)
        if not default or default == (example.get("identity") or {}).get(field):
            default = git_config(f"user.{field}", folder) or default
        typed = ask(f"identity.{field}", f"The commit {field} for every target.",
                    default).strip()
        if typed or default:
            identity[field] = typed or default
    blocks: dict = {}
    source = dict(current.get("source") or {})
    for field in SOURCE_FIELDS:
        typed = ask(f"source.{field}", SOURCE_ASKS[field], source.get(field)).strip()
        if typed:
            source[field] = typed
    blocks["source"] = source
    for key, kind in LEAK_KINDS.items():
        typed = ask(key, LEAK_ASKS[key], shown(current.get(key))).strip()
        if typed:
            blocks[key] = PARSERS[kind](typed)
    answers = dict(current.get("answers") or {})
    for key, question in prompts():
        prompt = (f"{question.get('ask')}\n  Why: {question.get('why')}\n"
                  f"  For example: {question.get('example')}\n"
                  f"  Does not apply to you? Answer {NOT_APPLICABLE}.")
        typed = ask(key, prompt, answers.get(key)).strip()
        if typed:
            answers[key] = typed
    return identity, answers, blocks


def check_blocks(blocks: dict, kinds: dict) -> None:
    """Refuse an answers-file block that has the wrong shape."""
    source = blocks.get("source")
    if source is not None and (not isinstance(source, dict) or not set(source) <= set(SOURCE_FIELDS)
                               or not all(isinstance(v, str) for v in source.values())):
        raise SetupError("source: must hold repo:, key: and owner: strings only")
    for key, kind in kinds.items():
        value = blocks.get(key)
        if value is None:
            continue
        good = {"list": isinstance(value, list) and all(isinstance(v, str) for v in value),
                "text": isinstance(value, str),
                "map": isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str)
                                                       for k, v in value.items())}[kind]
        if not good:
            raise SetupError(f"{key}: must be a {'string' if kind == 'text' else kind}")


def refuse_examples(identity: dict, current: dict, blocks: dict) -> None:
    """Refuse a profile that still holds an example value the operator was never asked to
    keep: an identity at the example's domain, or any source or leak-gate value equal to
    the example's."""
    email = str(identity.get("email") or "")
    if email.lower().endswith(EXAMPLE_EMAIL_SUFFIX):
        raise SetupError(f"identity.email {email!r} is an example address, which ends "
                         f"{EXAMPLE_EMAIL_SUFFIX}. Use your own email")
    example = example_profile()
    source = {**(current.get("source") or {}), **(blocks.get("source") or {})}
    for field in SOURCE_FIELDS:
        value = str(source.get(field) or "").strip()
        if not value or value.lower() == NOT_APPLICABLE:
            raise SetupError(f"source.{field} needs a value of your own, not {value!r}")
        if value == (example.get("source") or {}).get(field):
            raise SetupError(f"source.{field} still holds the example value {value!r}. "
                             "Replace it with your own")
    for key in LEAK_KINDS:
        value = blocks.get(key, current.get(key))
        if value not in (None, "", [], {}) and value == example.get(key):
            raise SetupError(f"{key} still holds the example value {value!r}. Replace it "
                             f"with your own, or answer {NOT_APPLICABLE} for none")


def from_file(path: Path, current: dict) -> tuple[dict, dict, dict]:
    """Identity, answers and the other profile blocks from an --answers file, over what the
    profile already holds."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SetupError(f"{path} must be a mapping of identity: and answers:")
    extra = sorted(str(key) for key in set(data) - ANSWER_FILE_KEYS)
    if extra:
        raise SetupError(f"{path}: {', '.join(extra)} cannot be set by setup. An answers file "
                         f"holds {', '.join(sorted(ANSWER_FILE_KEYS))} only; features are set "
                         "by consent.py")
    identity, answers = data.get("identity") or {}, data.get("answers") or {}
    if not isinstance(identity, dict) or not set(identity) <= IDENTITY_KEYS:
        raise SetupError(f"{path}: identity: must hold name: and email: only")
    if not isinstance(answers, dict):
        raise SetupError(f"{path}: answers: must be a mapping")
    blocks = {key: data[key] for key in ANSWER_FILE_KEYS - {"identity", "answers"}
              if key in data}
    check_blocks(blocks, LEAK_KINDS)
    return ({**(current.get("identity") or {}), **identity},
            {**(current.get("answers") or {}), **answers}, blocks)


class BlockDumper(yaml.SafeDumper):
    """Indents list entries under their key, so a block replaced in the text still reads as
    one block, and writes a multi-line string as a literal block."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


BlockDumper.add_representer(str, lambda dumper, value: dumper.represent_scalar(
    "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None))


def render_block(key: str, value) -> str:
    return yaml.dump({key: value}, Dumper=BlockDumper, sort_keys=False, allow_unicode=True,
                     width=1000)


def replace_source(text: str, source: dict) -> str:
    """profile.yaml text with source: set field by field, so the comment above each field
    stays."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(r"source:(\s|$)", line)), None)
    if start is None:
        return replace_block(text, "source", render_block("source", source))
    end = start + 1
    while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
        end += 1
    for field in SOURCE_FIELDS:
        if field not in source:
            continue
        entry = "  " + yaml.safe_dump({field: source[field]}, allow_unicode=True,
                                      width=1000).rstrip("\n") + "\n"
        hit = next((i for i in range(start + 1, end) if re.match(rf"  {field}:(\s|$)", lines[i])),
                   None)
        if hit is None:
            lines.insert(start + 1, entry)
            end += 1
        else:
            lines[hit] = entry
    return "".join(lines)


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
        if (not existing and folder.exists()
                and any(entry.name not in NEW_REPOSITORY_ENTRIES for entry in folder.iterdir())):
            raise SetupError(f"{folder} is not empty and holds no {sync.PROFILE_NAME}. Setup "
                             "creates a profile only in an empty or new folder")
        text = (path if existing else EXAMPLE).read_text(encoding="utf-8")
        current = yaml.safe_load(text) or {}
        if answers_file is None:
            identity, answers, blocks = collect(current, ask, folder)
        else:
            identity, answers, blocks = from_file(answers_file, current)
        refuse_examples(identity, current, blocks)
        sync.identity({"identity": identity})
        sync.validate_answers({"answers": answers}, sync.setup_questions())
        proposed = replace_block(text, "identity", render_block("identity", identity))
        proposed = replace_block(proposed, "answers", render_block("answers", answers))
        proposed = replace_source(proposed, blocks.get("source") or {})
        for key in LEAK_KINDS:
            if key in blocks:
                proposed = replace_block(proposed, key, render_block(key, blocks[key]))
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


def write_registry(name: str, value: str | None, winreg_module=None) -> None:
    """Set the user environment variable `name` to `value` as REG_SZ, or delete it when
    `value` is None. Deleting a variable that is not there is fine."""
    module = winreg_module
    if module is None:
        import winreg as module  # Windows only; a test passes a fake on any platform
    with module.OpenKey(module.HKEY_CURRENT_USER, "Environment", 0,
                        module.KEY_SET_VALUE) as key:
        if value is None:
            try:
                module.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            module.SetValueEx(key, name, 0, module.REG_SZ, value)


def broadcast_environment(user32=None) -> None:
    """Tell running programs the environment changed, so processes started from now on see it."""
    import ctypes
    user32 = user32 or ctypes.windll.user32
    result = ctypes.c_ulong()
    sent = user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                      SMTO_ABORTIFHUNG, BROADCAST_TIMEOUT_MS,
                                      ctypes.byref(result))
    if not sent:
        raise OSError("the settings-change broadcast was not delivered")


def sources_profile(text: str) -> bool:
    return any(HOOKS_SOURCES.search(line) for line in text.splitlines()
               if not line.lstrip().startswith("#"))


def posix_refusal(home: Path, shell: str, state: str) -> str | None:
    """Why the ~/.profile block would not be read, or None. Names the line to handle by hand."""
    do = "add" if state == "off" else "remove"
    line = f"export {HOOKS_VARIABLE}=off"
    for name in (".bash_profile", ".bash_login"):
        path = home / name
        if path.is_file() and not sources_profile(path.read_text(encoding="utf-8",
                                                                 errors="replace")):
            return (f"{path} exists and does not source ~/.profile, so a bash login shell "
                    f"never reads ~/.profile. Nothing was written. {do.capitalize()} this "
                    f"line {'to' if state == 'off' else 'from'} {path} by hand: {line}")
    if shell.endswith("zsh"):
        return (f"the login shell is zsh ({shell}), which does not read ~/.profile. Nothing "
                f"was written. {do.capitalize()} this line {'to' if state == 'off' else 'from'} "
                f"~/.zprofile by hand: {line}")
    return None


def edit_profile_text(text: str, state: str) -> str:
    """~/.profile text with the marked block present (off) or gone (on); the rest untouched."""
    if HOOKS_START in text and HOOKS_BLOCK not in text:
        raise SetupError(f"~/.profile holds the line {HOOKS_START!r} but not the whole block "
                         "setup writes. Fix or remove it by hand")
    if state == "on":
        return text.replace(HOOKS_BLOCK, "")
    if HOOKS_BLOCK in text:
        return text
    return text + ("" if not text or text.endswith("\n") else "\n") + HOOKS_BLOCK


def run_hooks(state: str, *, confirm: Confirm = console_confirm, platform: str | None = None,
              home: Path | None = None, shell: str | None = None,
              registry: Callable[[str, "str | None"], None] = write_registry,
              broadcast: Callable[[], None] = broadcast_environment) -> int:
    """Set (off) or clear (on) the hooks off switch for this machine, after a typed yes.
    0 done or already so, 1 refused or not confirmed. The writers are parameters so a test
    never touches the real registry or home folder."""
    platform = sys.platform if platform is None else platform
    try:
        if platform == "win32":
            verb = "set" if state == "off" else "delete"
            what = (f"This will {verb} {HOOKS_VARIABLE}{'=off' if state == 'off' else ''} "
                    r"in the user environment: HKCU\Environment, as a string value.")
            print(what)
            if not confirm(what):
                raise SetupError("not confirmed. Nothing was written")
            registry(HOOKS_VARIABLE, "off" if state == "off" else None)
            print(f"[OK] {verb} {HOOKS_VARIABLE} in HKCU\\Environment")
            try:
                broadcast()
            except Exception as error:  # a failed broadcast must not undo the write
                print(f"[WARN] the settings-change broadcast failed ({error}). The value is "
                      "written; sign out and in, or restart the tool, to pick it up")
        else:
            home = Path.home() if home is None else Path(home)
            shell = os.environ.get("SHELL", "") if shell is None else shell
            refusal = posix_refusal(home, shell, state)
            if refusal:
                raise SetupError(refusal)
            path = home / ".profile"
            text = path.read_bytes().decode("utf-8") if path.exists() else ""
            proposed = edit_profile_text(text, state)
            if proposed == text:
                print(f"[OK] nothing to change in {path}")
                return 0
            what = (f"This will {'add' if state == 'off' else 'remove'} this block "
                    f"{'to' if state == 'off' else 'from'} {path}:\n{HOOKS_BLOCK}")
            print(what)
            if not confirm(what):
                raise SetupError("not confirmed. Nothing was written")
            path.write_bytes(proposed.encode("utf-8"))
            print(f"[OK] written: {path}")
    except (SetupError, OSError, UnicodeError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    print("[OK] Restart the tool, from a new login shell on Linux, for the change to take effect")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup_profile.py",
        description="Create or update a profile: identity, setup answers, then features "
                    "through consent.py. Exit 0 done, 1 refused, 3 written but the render "
                    "could not be checked.")
    parser.add_argument("--profile", type=Path,
                        help="the profile folder: new, empty, or holding profile.yaml. "
                             "Required unless --hooks is given")
    parser.add_argument("--answers", type=Path,
                        help="answer from this YAML file instead of the console. Holds "
                             "identity:, answers:, source: and the leak-gate keys only; "
                             "features stay off")
    parser.add_argument("--hooks", choices=("off", "on"),
                        help="only set or clear the hooks off switch on this machine "
                             f"({HOOKS_VARIABLE}): no profile questions, no profile.yaml "
                             "write. Shows what it will write and asks for a typed yes")
    args = parser.parse_args(argv)
    if args.hooks:
        if args.answers:
            parser.error("--answers does not apply to --hooks, which asks no profile questions")
        return run_hooks(args.hooks)
    if args.profile is None:
        parser.error("--profile is required unless --hooks is given")
    return run_setup(args.profile.resolve(), answers_file=args.answers)


if __name__ == "__main__":
    sys.exit(main())
