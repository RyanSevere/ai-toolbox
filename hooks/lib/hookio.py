#!/usr/bin/env python3
################################################################################
# File: hookio.py
# Path: {PROJECT_ROOT}/.cursor/hooks/lib/hookio.py
# Created by: Ryan Severe
# Created: 2026-11-06
# Last Updated: 2026-11-08
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
# Per neutral event, the payload fields a hook reads. Only shell.before has a hook yet; the
# others are mapped when their first hook lands and its payload is seen live.
EVENT_FIELDS = {"shell.before": ("command", "cwd")}

Decide = Callable[[dict], "tuple[str, str] | None"]


def hooks_off() -> bool:
    """Read at run time, so running sync.py from a shell cannot change it - DECISIONS.md."""
    return os.environ.get(OFF_VARIABLE, "").strip().lower() == "off"


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


def neutral(event: str, raw: dict) -> dict:
    """The payload a hook sees. An absent field is None, never a default that reads as real."""
    fields = {"event": event, "raw": raw}
    for name in (*EVENT_FIELDS.get(event, ()), *MODEL_FIELDS):
        fields[name] = raw.get(name)
    return fields


def emit(verdict: dict) -> None:
    print(json.dumps(verdict))


def run_permission(name: str, event: str, decide: Decide) -> int:
    """Run a permission hook. decide returns None to allow, or (user_message, agent_message)
    to deny. Input that cannot be read denies: a guard must not wave through what it cannot see.
    """
    if hooks_off():
        emit({"permission": "allow"})
        return 0
    payload, unread = read_payload(sys.stdin.buffer)
    if payload is None:
        emit({"permission": "deny",
              "user_message": f"{name}: could not parse hook input ({unread}).",
              "agent_message": f"The {name} hook could not read its input and denied by default."})
        return 0
    verdict = decide(neutral(event, payload))
    if verdict is None:
        emit({"permission": "allow"})
    else:
        user_message, agent_message = verdict
        emit({"permission": "deny", "user_message": user_message,
              "agent_message": agent_message})
    return 0


def run_observer(name: str, event: str, observe: Callable[[dict], None]) -> int:
    """Run an observer hook. It writes nothing, and input it cannot read is skipped: an
    observer fails open by design."""
    if hooks_off():
        return 0
    payload, _ = read_payload(sys.stdin.buffer)
    if payload is not None:
        observe(neutral(event, payload))
    return 0
