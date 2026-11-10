#!/usr/bin/env python3
################################################################################
# File: check.py
# Path: {PROJECT_ROOT}/scripts/no-secret-defaults/check.py
# Created by: Ryan Severe
# Created: 2026-09-15
# Last Updated: 2026-11-07
# Description: Fails when a secret is given a fallback or default value. Runs
#              as a git pre-commit hook over staged changes, or in CI over the
#              whole tree. Not a Cursor hook - this must catch every commit.
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
import re
import subprocess
import sys
from pathlib import Path

SECRETISH = r"(?:secret|password|passwd|token|api[_-]?key|apikey|credential|private[_-]?key|jwt|auth)"

RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "JS/TS fallback on a secret",
        # APP_JWT_SECRET ?? "dev-secret"   |   process.env.X || 'changeme'
        re.compile(rf"""\b\w*{SECRETISH}\w*\b[^\n;]{{0,80}}(?:\?\?|\|\|)\s*['"][^'"]+['"]""", re.I),
    ),
    (
        "Python getenv default on a secret",
        # os.getenv('X_PASSWORD', '')  |  os.environ.get("API_KEY", "abc")
        re.compile(rf"""(?:getenv|environ\.get)\s*\(\s*['"][^'"]*{SECRETISH}[^'"]*['"]\s*,""", re.I),
    ),
    (
        "Typed default on a secret field",
        # secret_key: str = "change-me-in-production"
        re.compile(rf"""\b\w*{SECRETISH}\w*\s*:\s*\w+\s*=\s*['"][^'"]+['"]""", re.I),
    ),
    (
        "Shell/Compose default on a secret",
        # ${JWT_SECRET:-changeme} and ${API_KEY:-}  -  :? is the correct form and is allowed
        re.compile(rf"""\$\{{\w*{SECRETISH}\w*:?-[^}}]*\}}""", re.I),
    ),
]

# ${APP_API_KEY:-} used to pass on the grounds that the consumer validates.
# Reversed 2026-09-26: an empty default turns a missing key into a
# 401 far from its cause. Use :? so compose refuses to start instead.

ALLOW_MARKER = "no-secret-defaults: allow"

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".yml", ".yaml", ".env.example"}


def staged_files() -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, check=False,
    )
    return [Path(p) for p in out.stdout.split() if p]


def all_files(root: Path) -> list[Path]:
    return [
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix in SCAN_SUFFIXES
        and not any(part in SKIP_DIRS for part in p.parts)
    ]


def scan(path: Path) -> list[tuple[int, str, str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    findings = []
    for number, line in enumerate(lines, 1):
        if ALLOW_MARKER in line:
            continue
        for label, pattern in RULES:
            if pattern.search(line):
                findings.append((number, label, line.strip()[:120]))
                break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail on secrets given default values.")
    parser.add_argument("--all", action="store_true", help="scan the tree, not just staged changes")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    targets = all_files(args.root) if args.all else staged_files()
    targets = [p for p in targets if p.suffix in SCAN_SUFFIXES and p.exists()]

    total = 0
    for path in targets:
        for number, label, text in scan(path):
            total += 1
            print(f"{path}:{number}: {label}")
            print(f"    {text}")

    if total:
        print(f"\n[ERROR] {total} secret default(s) found.")
        print("A missing secret must abort, never continue with a placeholder.")
        print("See the core's patterns/required-secret for the correct form per language.")
        print(f"If a match is genuinely not a secret, add '{ALLOW_MARKER}' to that line.")
        return 1

    print(f"[OK] no secret defaults in {len(targets)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
