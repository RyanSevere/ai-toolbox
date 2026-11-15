#!/usr/bin/env python3
################################################################################
# File: gate_lists.py
# Path: {PROJECT_ROOT}/gate_lists.py
# Created by: Ryan Severe
# Created: 2026-11-15
# Last Updated: 2026-11-15
# Description: Builds the one-way gates' pattern files from a profile: the leak
#              denylist and the core-names list. Writes the two files named and
#              prints counts, never a pattern - the lists are secret-adjacent
#              and the person running this may be an agent whose output is logged.
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
import sys
from pathlib import Path

import sync

# The gates match each line as a fixed string, ignoring case, after trimming it and
# dropping blank lines and lines that start with #. So nothing is escaped, and an entry
# is only unsafe if it is blank, starts with #, or spans lines (githooks/lib/pattern_file.sh).
# <key>-1 to <key>-9: the issue references a leak would show.
ISSUE_NUMBERS = range(1, 10)


def _entry(value: object, where: str) -> str:
    """One pattern as the gates will read it, or a refusal that names `where`, never the value."""
    if not isinstance(value, str) or not value.strip():
        raise sync.SyncError(f"every entry under {where} must be a non-empty string")
    text = value.strip()
    if "\n" in text or "\r" in text or text.startswith("#"):
        raise sync.SyncError(f"an entry under {where} starts with # or spans lines, which the "
                             "gates would read as a comment or as two patterns")
    return text


def _entries(manifest: dict, key: str) -> list[str]:
    value = manifest.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise sync.SyncError(f"{key!r} must be a list")
    return [_entry(item, repr(key)) for item in value]


def _issue_keys(manifest: dict) -> list[str]:
    """Every key sync.issue_keys would list: the source's, each live target's, each tracked repo's."""
    keys = []
    src = manifest.get("source") or {}
    if src.get("key"):
        keys.append(src["key"])
    for cfg in (manifest.get("targets") or {}).values():
        cfg = cfg or {}
        if not cfg.get("skip") and cfg.get("key"):
            keys.append(cfg["key"])
    for cfg in (manifest.get("tracked") or {}).values():
        if (cfg or {}).get("key"):
            keys.append(cfg["key"])
    return keys


def build(manifest: dict) -> tuple[list[str], list[str]]:
    """The leak denylist and the core-names list, each sorted and without repeats."""
    src = manifest.get("source") or {}
    if not isinstance(src.get("repo"), str) or not src["repo"].strip():
        raise sync.SyncError("the profile has no source.repo, so a list built from it would "
                             "check nothing")
    source_repo = _entry(src["repo"], "'source.repo'")
    name = manifest.get("profile_name")
    profile_name = _entry(name, "'profile_name'") if name not in (None, "") else None

    leak = set(_entries(manifest, "personal"))
    for key in _issue_keys(manifest):
        base = _entry(key, "an issue key")
        leak.update(f"{base}-{n}" for n in ISSUE_NUMBERS)
    leak.add(source_repo)
    if profile_name:
        leak.add(profile_name)
    email = str((manifest.get("identity") or {}).get("email") or "").strip()
    if email:
        leak.add(_entry(email, "'identity.email'"))
    leak.update(_entries(manifest, "leak_extra"))

    core_names = {source_repo} | ({profile_name} if profile_name else set())
    return sorted(leak - {""}), sorted(core_names - {""})


def _write(path: Path, entries: list[str]) -> None:
    """One entry per line, a trailing newline, UTF-8 with no BOM."""
    path.write_bytes("".join(f"{entry}\n" for entry in entries).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gate_lists.py",
        description="Write the one-way gate pattern files from profile.yaml. Writes the two "
                    "files named; prints counts, never patterns.")
    parser.add_argument("--profile", type=Path, default=Path("."),
                        help="the profile folder (default: the current folder)")
    parser.add_argument("--leak", type=Path, required=True,
                        help="the file to write the leak denylist to")
    parser.add_argument("--core-names", type=Path, required=True,
                        help="the file to write the core-names list to")
    args = parser.parse_args(argv)
    try:
        manifest = sync.load_profile(sync.resolve_profile(args.profile))
        leak, core_names = build(manifest)
    except sync.SyncError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    _write(args.leak, leak)
    _write(args.core_names, core_names)
    print(f"[OK] wrote {len(leak)} leak pattern(s) to {args.leak} and "
          f"{len(core_names)} core name(s) to {args.core_names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
