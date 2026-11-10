#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.cursor/hooks/no-shell-file-edits/hook.py
# Created by: Ryan Severe
# Created: 2026-09-15
# Last Updated: 2026-11-06
# Description: Cursor beforeShellExecution hook. Denies shell commands that
#              edit a file in place - POSIX and PowerShell - so edits go through
#              proper edit tooling where they are reviewable, and any command
#              naming profile.lock that is not a read. Reads hook JSON on stdin.
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
import re
import sys

# In-place editors. These rewrite a file without producing a reviewable diff.
IN_PLACE = re.compile(
    r"""(?:^|[;&|(]\s*)\s*
        (?:sudo\s+)?
        (?:
            sed\s+(?:-\S*\s+)*(?:-[A-Za-z]*i|--in-place)   # sed -i, sed -Ei, sed -i.bak
          | perl\s+(?:-\S*\s+)*-[A-Za-z]*i                # perl -pi -e: -i bundled
          | ruby\s+(?:-\S*\s+)*-[A-Za-z]*i
          | truncate\b
          | (?:ed|ex)\s+-s
        )
    """,
    re.VERBOSE,
)

# Redirection into a path. Excluded below if the target is clearly throwaway.
REDIRECT = re.compile(r"(?<![0-9<>])>>?\s*(?P<target>[^\s;&|]+)")

# tee writing to a real path rather than being used for display.
TEE = re.compile(r"\btee\s+(?:-a\s+)?(?P<target>[^\s;&|]+)")

# Targets that are not source files and are always fine to write.
THROWAWAY = re.compile(
    r"""^(
        /dev/(null|stderr|stdout|fd/\d+)
      | \$null
      | &\d
      | /tmp/.*
      | \$\{?TMPDIR.*
      | .*\.(log|tmp|out|bak|json\.tmp)
    )$""",
    re.VERBOSE,
)

# PowerShell cmdlets that write a file. Case-insensitive, as PowerShell is. Aliases
# are left out: in Windows PowerShell 5.1 `sc` is also sc.exe, the service tool.
PS_WRITER = re.compile(
    r"(?:^|[;&|(]\s*)\s*(?P<cmdlet>Set-Content|Add-Content|Out-File|New-Item)\b(?P<args>[^;&|]*)",
    re.IGNORECASE,
)
PS_PATH = re.compile(r"-(?:Path|FilePath|LiteralPath)\s+(?P<target>\S+)", re.IGNORECASE)
PS_VALUE = re.compile(r"(?:^|\s)-Value\b", re.IGNORECASE)


# The consent lock. Only `consent.py` writes it, after a typed yes; a script that computes
# the hash is the forgery route this closes. An allowlist, not a list of
# writers: any segment naming the lock must start with a reader, or with consent.py.
LOCK_NAME = "profile.lock"
LOCK = re.compile(r"(?<![\w.-])profile\.lock(?![\w.-])", re.IGNORECASE)
LOCK_READER = re.compile(
    r"""^\s*(?:
        (?:git|cat|type|get-content|rg|grep|diff|head|tail)(?:\.exe)?\b
      | (?:python3?|py)(?:\.exe)?\s+(?:\S*[/\\])?consent\.py\b
    )""",
    re.VERBOSE | re.IGNORECASE,
)
# Command separators, subshells and backticks. Splitting inside quotes as well is
# deliberate: a quoted `|` costs a false refusal, never a write let through.
SEGMENT = re.compile(r"[;&|\n()`]+")


def lock_write(command: str) -> str | None:
    """The first segment that names profile.lock without being a read, or None."""
    for segment in SEGMENT.split(command):
        if LOCK.search(segment) and not LOCK_READER.match(segment):
            return segment.strip()
    return None


def ps_target(args: str) -> str | None:
    """The file a cmdlet writes: its -Path, or else the first argument no parameter claims."""
    named = PS_PATH.search(args)
    if named:
        return named.group("target")
    previous = ""
    for token in args.split():
        if not token.startswith("-") and not previous.startswith("-"):
            return token
        previous = token
    return None


def offending(command: str) -> str | None:
    """Return a human-readable reason to block, or None to allow."""
    segment = lock_write(command)
    if segment is not None:
        return f"a command naming {LOCK_NAME} that is not a read ({segment[:80]})"
    if IN_PLACE.search(command):
        return "an in-place editor (sed -i or equivalent)"

    for pattern, label in ((REDIRECT, "shell redirection"), (TEE, "tee")):
        for match in pattern.finditer(command):
            target = match.group("target").strip("'\"")
            if not THROWAWAY.match(target):
                return f"{label} writing to {target}"

    for match in PS_WRITER.finditer(command):
        cmdlet, args = match.group("cmdlet"), match.group("args")
        # New-Item without -Value creates an empty file or a directory, not an edit.
        if cmdlet.lower() == "new-item" and not PS_VALUE.search(args):
            continue
        target = (ps_target(args) or "").strip("'\"")
        # No target found is denied: a write whose destination cannot be read is not throwaway.
        if not THROWAWAY.match(target):
            return f"{cmdlet} writing to {target or 'an unreadable target'}"
    return None


def read_payload() -> tuple[dict | None, str]:
    """The hook input as a dict, or None and a description of the bytes that would not parse.

    Read as bytes: piped stdin on Windows decodes with the locale code page, not UTF-8, and
    that denied every command live on 2026-10-09.
    """
    raw = sys.stdin.buffer.read()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        payload = json.loads(raw.decode(encoding))
    except ValueError:  # UnicodeDecodeError and JSONDecodeError are both ValueErrors
        return None, f"{len(raw)} bytes, starting {raw[:16]!r}"
    if not isinstance(payload, dict):
        return None, f"{len(raw)} bytes of JSON that is not an object"
    return payload, ""


def main() -> int:
    payload, unread = read_payload()
    if payload is None:
        # A permission hook that cannot parse its input must not wave the
        # action through. Deny and say why, with enough to diagnose it.
        print(json.dumps({
            "permission": "deny",
            "user_message": f"no-shell-file-edits: could not parse hook input ({unread}).",
            "agent_message": "The file-edit guard could not read its input and denied by default.",
        }))
        return 0

    command = payload.get("command", "") or ""
    reason = offending(command)

    if reason is None:
        print(json.dumps({"permission": "allow"}))
        return 0

    if LOCK_NAME in reason:
        print(json.dumps({
            "permission": "deny",
            "user_message": f"Blocked: {reason}.",
            "agent_message": (
                f"This command was blocked because it names {LOCK_NAME} and is not a read.\n\n"
                f"{LOCK_NAME} records the operator's consent to the gate flags. Only "
                "`python core/consent.py --profile . --set <gate>=on|off`, typed by the operator at an "
                "interactive console, may change it - not a script, and not an editor "
                "tool. Ask the operator to run the consent command."
            ),
        }))
        return 0

    print(json.dumps({
        "permission": "deny",
        "user_message": f"Blocked: {reason}. Use the editor's file tools.",
        "agent_message": (
            f"This command was blocked because it uses {reason} to modify a file.\n\n"
            "Edit files with the editing tools, not the shell. Shell edits produce no "
            "reviewable diff, bypass the backup-before-batch-edit rule, and have "
            "silently corrupted files in this estate before.\n\n"
            "If the write is genuinely not a source edit - a temp file, a log, "
            "/dev/null - adjust the target. If you need this specific command, ask "
            "the operator to run it."
        ),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
