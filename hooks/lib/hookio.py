#!/usr/bin/env python3
################################################################################
# File: hookio.py
# Path: {PROJECT_ROOT}/.cursor/hooks/lib/hookio.py
# Created by: Ryan Severe
# Created: 2026-11-06
# Last Updated: 2026-11-16
# Description: Shared runtime library for agent hooks. Reads the
#              tool's payload as bytes, hands the hook a neutral payload with
#              the model fields, writes the tool's output shape, and honours
#              the AI_TOOLBOX_HOOKS=off switch. Design in
#              hooks/README.md, "Tool-neutral schema".
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

import json
import os
import sys
from typing import BinaryIO, Callable

OFF_VARIABLE = "AI_TOOLBOX_HOOKS"
MODEL_FIELDS = ("model", "model_id", "model_params")
DEFAULT_TOOL = "cursor"  # no --tool argument: hooks rendered before the argument existed
TOOL_ARGUMENT = "--tool"
# Per neutral event, the neutral fields a hook must have. An absent one denies a permission
# hook and skips an observer; a present null or empty string is a value. shell.before,
# file.write.before and file.write.after have hooks; the others are mapped when their first hook lands and its
# payload is seen live. file.write.before is mapped from documentation: Claude Code documents
# tool_input.file_path for Write and Edit; Cursor's preToolUse documents no key for a Write's
# path, so its entry is the same path, provisional until a captured payload confirms it.
REQUIRED_FIELDS = {"shell.before": ("command",), "file.write.before": ("path",),
                   "file.write.after": ("path",)}
# Per tool, per neutral event, where each neutral field sits in that tool's payload: a path of
# keys from the top. Fields not required here are None when absent.
FIELD_PATHS = {
    "cursor": {
        "shell.before": {"command": ("command",), "cwd": ("cwd",)},
        "file.write.before": {"path": ("tool_input", "file_path"), "cwd": ("cwd",)},  # unverified
    },
    "claude": {
        "shell.before": {"command": ("tool_input", "command"), "cwd": ("cwd",)},
        "file.write.before": {"path": ("tool_input", "file_path"), "cwd": ("cwd",)},
        "file.write.after": {"path": ("tool_input", "file_path"), "cwd": ("cwd",)},
        "session.start": {},
    },
}

Decide = Callable[[dict], "tuple[str, str] | None"]


class PayloadError(ValueError):
    """The payload cannot give the hook what it needs; the message names what."""


def hooks_off() -> bool:
    """Read at run time, so running sync.py from a shell cannot change it - DECISIONS.md."""
    return os.environ.get(OFF_VARIABLE, "").strip().lower() == "off"


def tool_from_argv(argv: list[str]) -> str:
    """The tool the adapter named, as --tool <name> or --tool=<name>; Cursor when it named none.
    A --tool with no value is the empty name, which no tool has."""
    for index, arg in enumerate(argv):
        if arg == TOOL_ARGUMENT:
            return argv[index + 1] if index + 1 < len(argv) else ""
        if arg.startswith(TOOL_ARGUMENT + "="):
            return arg[len(TOOL_ARGUMENT) + 1:]
    return DEFAULT_TOOL


def read_payload(stream: BinaryIO) -> tuple[dict | None, str]:
    """The hook input as a dict, or None and a description of the bytes that would not parse.

    Read as bytes: piped stdin on Windows decodes with the locale code page, and Cursor's
    payload may open with a BOM. Either denied every command live on 2026-10-09.
    """
    raw = stream.read()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        payload = json.loads(raw.decode(encoding))
    except ValueError:  # UnicodeDecodeError and JSONDecodeError are both ValueErrors
        return None, f"{len(raw)} bytes, starting {raw[:16]!r}"
    if not isinstance(payload, dict):
        return None, f"{len(raw)} bytes of JSON that is not an object"
    return payload, ""


def lookup(raw: dict, path: tuple[str, ...]):
    """The value at path in raw. PayloadError names the whole path when a key is absent, or the
    parent when it is not an object."""
    value = raw
    for depth, key in enumerate(path):
        if not isinstance(value, dict):
            raise PayloadError(f"{'.'.join(path[:depth])} is not an object")
        if key not in value:
            raise PayloadError(f"missing field {'.'.join(path)}")
        value = value[key]
    return value


def neutral(event: str, raw: dict, tool: str = DEFAULT_TOOL) -> dict:
    """The payload a hook sees. An absent optional field is None, never a default that reads
    as real. PayloadError when the tool is unknown or a required field is absent."""
    if tool not in FIELD_PATHS:
        raise PayloadError(f"unknown tool {tool!r}")
    paths = FIELD_PATHS[tool].get(event, {})
    fields = {"event": event, "raw": raw}
    for name, path in paths.items():
        try:
            fields[name] = lookup(raw, path)
        except PayloadError:
            if name in REQUIRED_FIELDS.get(event, ()):
                raise
            fields[name] = None
    for name in MODEL_FIELDS:
        fields[name] = raw.get(name)
    return fields


def cursor_verdict(verdict: "tuple[str, str] | None") -> str:
    if verdict is None:
        return json.dumps({"permission": "allow"})
    user_message, agent_message = verdict
    return json.dumps({"permission": "deny", "user_message": user_message,
                       "agent_message": agent_message})


def claude_verdict(verdict: "tuple[str, str] | None") -> str:
    """Allow is no output: exit 0 with none defers to Claude Code's normal permission flow,
    where an explicit "allow" would skip it. A deny carries the reason Claude is shown."""
    if verdict is None:
        return ""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": verdict[1]}})


# Per tool, the writer from a verdict (None to allow, or (user_message, agent_message)) to the
# text printed on stdout.
VERDICT_WRITERS = {"cursor": cursor_verdict, "claude": claude_verdict}


def claude_notice(text: str) -> str:
    """Claude Code adds additionalContext to the session before its first prompt."""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": text}})


# Per tool, the writer from a notice's text to the text printed on stdout. A tool with no entry
# gets no notice.
NOTICE_WRITERS = {"claude": claude_notice}


def emit(text: str) -> None:
    if text:
        print(text)


def run_permission(name: str, event: str, decide: Decide) -> int:
    """Run a permission hook. decide returns None to allow, or (user_message, agent_message)
    to deny. Input that cannot be read denies: a guard must not wave through what it cannot see.
    A tool the library does not know has no verdict shape, so it is denied by exit code 2 and
    stderr, which blocks in every tool.
    """
    tool = tool_from_argv(sys.argv[1:])
    if hooks_off():
        emit(VERDICT_WRITERS.get(tool, cursor_verdict)(None))
        return 0
    if tool not in VERDICT_WRITERS:
        print(f"{name}: unknown tool {tool!r} (known: {', '.join(sorted(VERDICT_WRITERS))}); "
              "denied by default.", file=sys.stderr)
        return 2
    write = VERDICT_WRITERS[tool]
    payload, unread = read_payload(sys.stdin.buffer)
    if payload is None:
        emit(write((f"{name}: could not parse hook input ({unread}).",
                    f"The {name} hook could not read its input and denied by default.")))
        return 0
    try:
        seen = neutral(event, payload, tool)
    except PayloadError as exc:
        emit(write((f"{name}: {exc} in the {tool} {event} payload.",
                    f"The {name} hook could not read its input ({exc}) and denied by default.")))
        return 0
    emit(write(decide(seen)))
    return 0


def claude_warning(event: str, text: str) -> str:
    """Claude Code adds additionalContext to the session after the tool call it names. An event
    with no Claude Code name has no warning shape, so it writes nothing."""
    if event not in CLAUDE_EVENT_NAMES:
        return ""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": CLAUDE_EVENT_NAMES[event], "additionalContext": text}})


# Claude Code's name for each neutral event an observer's warning can follow.
CLAUDE_EVENT_NAMES = {"file.write.after": "PostToolUse"}

# Per tool, the writer from an event and an observer's warning text to the text printed on
# stdout. A tool with no entry, or an event with no name, gets no warning. A warning informs the
# agent and never blocks.
OBSERVER_WRITERS = {"claude": claude_warning}


def run_observer(name: str, event: str, observe: Callable[[dict], "str | None"]) -> int:
    """Run an observer hook. It never blocks: observe returns None to say nothing, or a warning
    that is written for the agent where the tool supports it (OBSERVER_WRITERS). Input it cannot
    read, a tool it does not know or a field it cannot find is skipped: an observer fails open by
    design. The off switch stops it before it reads anything."""
    if hooks_off():
        return 0
    payload, _ = read_payload(sys.stdin.buffer)
    if payload is None:
        return 0
    try:
        seen = neutral(event, payload, tool_from_argv(sys.argv[1:]))
    except PayloadError:
        return 0
    text = observe(seen)
    tool = tool_from_argv(sys.argv[1:])
    if text and tool in OBSERVER_WRITERS:
        emit(OBSERVER_WRITERS[tool](event, text))
    return 0


def run_notice(name: str, event: str, notice: Callable[[dict], "str | None"]) -> int:
    """Run a hook that tells the session something. notice returns the text, or None to say
    nothing, and the text is written as the tool's context output.

    The off switch does not gate it. Use it only for a hook whose job is to report the switch:
    every other hook goes quiet when the switch is off, and this one is how a session finds out.
    It fails open, like run_observer: input it cannot read, a tool with no notice shape or a
    field it cannot find writes nothing.
    """
    tool = tool_from_argv(sys.argv[1:])
    if tool not in NOTICE_WRITERS:
        return 0
    payload, _ = read_payload(sys.stdin.buffer)
    if payload is None:
        return 0
    try:
        seen = neutral(event, payload, tool)
    except PayloadError:
        return 0
    text = notice(seen)
    if text:
        emit(NOTICE_WRITERS[tool](text))
    return 0
