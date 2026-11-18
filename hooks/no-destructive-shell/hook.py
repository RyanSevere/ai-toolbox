#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.cursor/hooks/no-destructive-shell/hook.py
# Created by: Ryan Severe
# Created: 2026-11-15
# Last Updated: 2026-11-17
# Description: Agent hook on shell.before. Denies the shell commands that
#              discard work - git clean, git checkout of paths, git reset
#              --hard, rm -r and Remove-Item -Recurse - and the ways round the
#              pre-push gates - git push --no-verify, setting GATE_REPORT_PUSH,
#              a push with core.hooksPath overridden, and a hand-written
#              gate-report ref - so the agent asks the operator first. Reads
#              each command's leading words, not a regex over the line, so a
#              commit message that names one is allowed. A recursive delete of
#              literal paths inside the repository's scratch/ is allowed.
#              Design in hooks/README.md.
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

import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

# The shared library renders beside the hooks, in a folder next to this one.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import hookio  # noqa: E402

NAME = "no-destructive-shell"


class Unreadable(ValueError):
    """The command cannot be split into segments, so a destructive one may hide in it."""


class Word(NamedTuple):
    text: str
    quoted: bool  # any part of it came from quotes; a quoted word is never a redirection


class Segment(NamedTuple):
    words: list[Word]
    raw: str


# A PowerShell here-string opens with @' or @" and a line end, and closes on a line that
# starts with the same quote and @. The same @' in bash is a word that starts with @.
HERE_STRING_OPEN = re.compile(r"@(['\"])[ \t]*\r?\n")
# A bash heredoc: <<WORD, <<'WORD', <<"WORD", <<-WORD. <<< is a here-string, not this.
HEREDOC_OPEN = re.compile(r"<<(?!<)(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\?([\w.-]+))")
# Characters a double-quoted word keeps escaped: POSIX's set. Backtick is PowerShell's escape.
DOUBLE_ESCAPES = ('"', "\\", "$", "`")
# Characters an unquoted backslash escapes. Any other backslash is a Windows path separator.
UNQUOTED_ESCAPES = "'\"`;&|()<>$ "


def double_quoted(command: str, start: int, chars: list[str]) -> int:
    """Append the text of the double-quoted string opening at start; return the index after it."""
    i = start + 1
    while i < len(command):
        c = command[i]
        if c == '"':
            return i + 1
        if c == "`" or (c == "\\" and command[i + 1:i + 2] in DOUBLE_ESCAPES):
            if i + 1 >= len(command):
                break
            chars.append(command[i + 1])
            i += 2
        else:
            chars.append(c)
            i += 1
    raise Unreadable("unbalanced double quote")


def skip_heredoc(command: str, i: int, delimiter: str, strip_tabs: bool) -> int:
    """The index after the heredoc body that starts at i and ends on the line `delimiter`."""
    n = len(command)
    while i < n:
        newline = command.find("\n", i)
        end = n if newline < 0 else newline
        line = command[i:end].rstrip("\r")
        if strip_tabs:
            line = line.lstrip("\t")
        i = end + 1
        if line == delimiter:
            return min(i, n)
    raise Unreadable(f"unterminated heredoc {delimiter}")


def redirect_ampersand(command: str, i: int) -> bool:
    """An & inside 2>&1, >& or &> belongs to the redirection, not to a segment boundary."""
    return command[i - 1:i] in ("<", ">") and i > 0 or command[i + 1:i + 2] == ">"


def split(command: str) -> list[Segment]:
    """The command's segments, split at ; && || | & newline ( ) and a backtick, outside quotes.

    Quoted text, a here-string body and a heredoc body are not scanned for segments. A quote,
    here-string or heredoc that never closes raises Unreadable.
    """
    segments: list[Segment] = []
    words: list[Word] = []
    chars: list[str] = []
    quoted = started = False
    pending: list[tuple[str, bool]] = []
    seg_start = 0

    def end_word() -> None:
        nonlocal chars, quoted, started
        if started:
            words.append(Word("".join(chars), quoted))
        chars, quoted, started = [], False, False

    def end_segment(at: int) -> None:
        nonlocal words
        end_word()
        if words:
            segments.append(Segment(words, command[seg_start:at].strip()))
        words = []

    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c in " \t\r":
            end_word()
            i += 1
        elif c == "\n":
            end_segment(i)
            i += 1
            for delimiter, strip_tabs in pending:
                i = skip_heredoc(command, i, delimiter, strip_tabs)
            pending = []
            seg_start = i
        elif c in ";|()" or (c == "&" and not redirect_ampersand(command, i)):
            end_segment(i)
            i += 1
            seg_start = i
        elif c == "`":
            continued = command.startswith(("`\r\n", "`\n"), i)
            if continued:  # PowerShell's line continuation joins the lines
                end_word()
                i += 3 if command.startswith("`\r\n", i) else 2
            else:  # a bash command substitution
                end_segment(i)
                i += 1
                seg_start = i
        elif c == "'":
            end = command.find("'", i + 1)
            if end < 0:
                raise Unreadable("unbalanced single quote")
            chars.append(command[i + 1:end])
            quoted = started = True
            i = end + 1
        elif c == '"':
            i = double_quoted(command, i, chars)
            quoted = started = True
        elif c == "@" and HERE_STRING_OPEN.match(command, i):
            opening = HERE_STRING_OPEN.match(command, i)
            closing = re.compile(rf"(?m)^{opening.group(1)}@").search(command, opening.end())
            if closing is None:
                raise Unreadable("unterminated here-string")
            quoted = started = True
            i = closing.end()
        elif c == "<" and HEREDOC_OPEN.match(command, i):
            opening = HEREDOC_OPEN.match(command, i)
            delimiter = opening.group(2) or opening.group(3) or opening.group(4)
            pending.append((delimiter, bool(opening.group(1))))
            end_word()
            i = opening.end()
        elif c == "\\" and command[i + 1:i + 2] and command[i + 1] in UNQUOTED_ESCAPES:
            chars.append(command[i + 1])
            started = True
            i += 2
        else:
            chars.append(c)
            started = True
            i += 1
    if pending:
        raise Unreadable(f"unterminated heredoc {pending[0][0]}")
    end_segment(n)
    return segments


# Words that open a command without being it: a keyword, or a wrapper the real command follows.
WRAPPERS = {"sudo", "env", "time", "command", "nohup", "!", "{", "if", "then", "else", "elif",
            "do", "while", "until"}
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
REDIRECT = re.compile(r"\d*(?:>>?\|?|<|&>|>&)")


def basename(word: str) -> str:
    name = re.split(r"[\\/]", word)[-1].casefold()
    return name[:-4] if name.endswith(".exe") else name


def program(words: list[Word]) -> tuple[str, list[Word]] | None:
    """The command word and the words after it, once assignments and wrappers are dropped."""
    i = 0
    while i < len(words):
        text = words[i].text
        name = basename(text)
        if ASSIGNMENT.match(text):
            i += 1
        elif name in WRAPPERS:
            i += 1
            while name in ("sudo", "env") and i < len(words) and words[i].text.startswith("-"):
                i += 1
        else:
            return name, words[i + 1:]
    return None


def without_redirects(words: list[Word]) -> list[Word]:
    """The words with each redirection, and the target it names, removed."""
    kept: list[Word] = []
    skip = False
    for word in words:
        if skip:
            skip = False
            continue
        match = None if word.quoted else REDIRECT.match(word.text)
        if match:
            skip = match.end() == len(word.text)
            continue
        kept.append(word)
    return kept


# git's own options that take their value as the next word.
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
CLEAN_DRY_RUN = re.compile(r"-[A-Za-z]*n[A-Za-z]*")


# The families that get round the pre-push gates start with this, so the deny message can tell
# them from the ones that discard work.
BYPASS = "a way round the pre-push gates"
REPORT_PREFIX = "gate-report/"
REPORT_VARIABLE = "gate_report_push"
# git tag options that only read: listing or verifying report tags is allowed.
TAG_READS = {"-l", "--list", "-v", "--verify"}
# Commands that set a variable from their arguments, as bash's export does.
EXPORTERS = {"export", "declare", "typeset", "local", "readonly"}


def git_family(args: list[Word]) -> str | None:
    """The family a git command is in, or None. Skips git's global options first."""
    i = 0
    overrides_hooks = False
    while i < len(args) and args[i].text.startswith("-"):
        option = args[i].text
        if option == "-c" and i + 1 < len(args):
            overrides_hooks = overrides_hooks or args[i + 1].text.casefold().startswith("core.hookspath")
        elif option.casefold().startswith("--config-env=core.hookspath"):
            overrides_hooks = True
        i += 2 if option in GIT_VALUE_OPTIONS else 1
    if i >= len(args):
        return None
    sub, rest = args[i].text, [word.text for word in args[i + 1:]]
    if sub == "push" and "--no-verify" in rest:
        return f"git push --no-verify, {BYPASS}"
    if sub == "push" and overrides_hooks:
        return f"a git push with core.hooksPath overridden, {BYPASS}"
    lists_tags = sub == "tag" and any(arg in TAG_READS for arg in rest)
    if (sub in ("update-ref", "tag", "push") and not lists_tags
            and any(REPORT_PREFIX in arg for arg in rest)):
        return f"a hand-written {REPORT_PREFIX} report ref, {BYPASS}"
    if sub == "clean":
        dry = "--dry-run" in rest or any(CLEAN_DRY_RUN.fullmatch(arg) for arg in rest)
        return None if dry else "git clean, which deletes untracked files"
    if sub == "checkout" and ("--" in rest or "." in rest):
        return "git checkout of paths, which overwrites their changes"
    if sub == "reset" and "--hard" in rest:
        return "git reset --hard, which discards every uncommitted change"
    return None


# rm, and Remove-Item with its aliases. PowerShell reads -r, -rec and -Recurse alike.
REMOVERS = {"rm", "ri", "del", "erase", "rd", "rmdir", "remove-item"}
POSIX_RM_FLAGS = re.compile(r"[fiIrRvdxP]+")
# Remove-Item parameters whose value is the next word, and is not a path.
VALUE_PARAMETERS = ("erroraction", "ea", "warningaction", "wa", "informationaction", "ia",
                    "errorvariable", "ev", "warningvariable", "wv", "informationvariable", "iv",
                    "outvariable", "ov", "outbuffer", "ob", "pipelinevariable", "pv",
                    "progressaction")
# Parameters that name targets by pattern, so the targets are not literal paths.
PATTERN_PARAMETERS = ("include", "exclude", "filter", "stream", "credential")
NOT_LITERAL = re.compile(r"[$*?\[\]{}`%]|^~|^@|^$")


def prefix_of(key: str, name: str, shortest: int) -> bool:
    return len(key) >= shortest and name.startswith(key)


def recursive(name: str, args: list[Word]) -> bool:
    for word in args:
        text = word.text
        if text == "--":
            break
        if text == "--recursive":
            return True
        if text.startswith("-") and not text.startswith("--"):
            flag = text[1:].partition(":")[0]
            if prefix_of(flag.lower(), "recurse", 1):
                return True
            if name == "rm" and POSIX_RM_FLAGS.fullmatch(flag) and ("r" in flag or "R" in flag):
                return True
    return False


def targets(args: list[Word]) -> list[str] | None:
    """The paths a delete names, or None when a parameter selects them by pattern."""
    found: list[str] = []
    done = False
    i = 0
    while i < len(args):
        text = args[i].text
        i += 1
        if done or not text.startswith("-") or text == "-":
            found.append(text)
        elif text == "--":
            done = True
        elif not text.startswith("--"):
            flag, colon, value = text[1:].partition(":")
            key = flag.lower()
            if any(prefix_of(key, name, 2) for name in PATTERN_PARAMETERS):
                return None
            if prefix_of(key, "path", 2) or prefix_of(key, "literalpath", 1):
                if colon:
                    found.append(value)
                elif i < len(args):
                    found.append(args[i].text)
                    i += 1
            elif key in VALUE_PARAMETERS and not colon:
                i += 1
    return found


def repository_root(cwd) -> Path | None:
    """The folder holding .git at or above cwd. None when cwd is absent, relative or in none."""
    if not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
        return None
    here = Path(os.path.realpath(cwd))
    for folder in (here, *here.parents):
        if (folder / ".git").exists():
            return folder
    return None


def inside(target: str, cwd: str, scratch: str) -> bool:
    """True when the literal target resolves strictly inside scratch."""
    if NOT_LITERAL.search(target):
        return False
    path = Path(target.replace("\\", "/"))
    if not path.is_absolute():
        path = Path(cwd) / path
    resolved = os.path.normcase(os.path.realpath(path))
    try:
        return resolved != scratch and os.path.commonpath([resolved, scratch]) == scratch
    except ValueError:  # another drive
        return False


def scratch_only(found: list[str] | None, cwd) -> bool:
    """True when there is at least one target and every one is a literal path inside the
    repository's scratch/. No cwd, no repository around it, or a target that is a variable,
    a glob or reaches out with .. is not."""
    root = repository_root(cwd)
    if not found or root is None:
        return False
    scratch = os.path.normcase(os.path.realpath(root / "scratch"))
    return all(inside(target, cwd, scratch) for target in found)


def sets_report_variable(words: list[Word], name: str, args: list[Word]) -> bool:
    """True when the segment sets GATE_REPORT_PUSH: an assignment word before the command or
    after export, `$env:GATE_REPORT_PUSH = ...`, or `Set-Item env:GATE_REPORT_PUSH ...`."""
    leading = words[:len(words) - len(args) - 1]  # the assignments and wrappers program() dropped
    assigned = leading + (args if name in EXPORTERS else [])
    for word in assigned:
        key = word.text.partition("=")[0].casefold()
        if ASSIGNMENT.match(word.text) and key == REPORT_VARIABLE:
            return True
    first = words[len(leading)].text.casefold()  # the command word itself
    if first.startswith("$env:" + REPORT_VARIABLE) and first[5 + len(REPORT_VARIABLE):][:1] in ("", "="):
        return True
    if name in ("set-item", "si", "set-content", "new-item", "ni", "set-variable"):
        return any(word.text.casefold() == "env:" + REPORT_VARIABLE for word in args)
    return False


def discards(segment: Segment, cwd) -> str | None:
    """What the segment discards or gets round, or None."""
    head = program(segment.words)
    if head is None:
        if any(ASSIGNMENT.match(word.text) and word.text.partition("=")[0].casefold()
               == REPORT_VARIABLE for word in segment.words):
            return f"setting GATE_REPORT_PUSH, {BYPASS}"
        return None
    name, words = head
    args = without_redirects(words)
    if sets_report_variable(segment.words, name, words):
        return f"setting GATE_REPORT_PUSH, {BYPASS}"
    if name == "git":
        return git_family(args)
    if name in REMOVERS and recursive(name, args):
        if scratch_only(targets(args), cwd):
            return None
        return "a recursive delete, which cannot be undone"
    return None


def shown(raw: str) -> str:
    one_line = " ".join(raw.split())
    return one_line if len(one_line) <= 120 else one_line[:117] + "..."


def decide(payload: dict) -> tuple[str, str] | None:
    command = payload["command"]
    if not isinstance(command, str):
        return (f"{NAME}: the command is not text.",
                f"The {NAME} hook could not read the command, which is not text, and denied it.")
    try:
        segments = split(command)
    except Unreadable as exc:
        return (f"{NAME}: could not read the command ({exc}).",
                f"The {NAME} hook could not read the command ({exc}), and a command it cannot "
                "split may hide one that discards work, so it denied it. Rewrite the command "
                "with its quotes balanced, or ask the operator to run it.")
    for segment in segments:
        family = discards(segment, payload.get("cwd"))
        if family:
            raw = shown(segment.raw)
            if BYPASS in family:
                return (f"{NAME}: blocked `{raw}`, {family}.",
                        f"This command was blocked by the {NAME} hook because it runs `{raw}`, "
                        f"{family}.\n\nDo not retry it or a variant of it. A failing gate is "
                        "fixed by making the gate pass. If the gate itself is wrong, ask the "
                        "operator to run the push or to say how to proceed.")
            return (f"{NAME}: blocked `{raw}`, {family}.",
                    f"This command was blocked by the {NAME} hook because it runs `{raw}`, "
                    f"{family}.\n\nDo not retry it or a variant of it. Ask the operator to run "
                    "it, or to say how to proceed. A recursive delete whose every target is a "
                    "literal path inside the repository's scratch/ folder is allowed.")
    return None


def main() -> int:
    return hookio.run_permission(NAME, "shell.before", decide)


if __name__ == "__main__":
    sys.exit(main())
