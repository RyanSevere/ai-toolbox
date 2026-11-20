#!/usr/bin/env python3
################################################################################
# File: test_prepush.py
# Path: {PROJECT_ROOT}/tests/test_prepush.py
# Created by: Claude Code (Opus 5.5), for Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-19
# Description: Tests for githooks/pre-push.sh helpers that build the gate
#              report. json_escape must turn any gate detail into a valid JSON
#              string body: coloured test output once made report.json
#              invalid, and CI then reported a parse error in place of the
#              gates' findings.
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

"""json_escape, run as the hook defines it, under sh."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "githooks" / "pre-push.sh"
ESC = "\x1b"

SH = shutil.which("sh") or next(
    (p for p in (r"C:\Program Files\Git\usr\bin\sh.exe", "/bin/sh") if Path(p).exists()),
    None,
)


def json_escape(text: str) -> str:
    """Pipe text through the hook's own json_escape function and return its output."""
    source = HOOK.read_text(encoding="utf-8")
    match = re.search(r"^json_escape\(\) \{\n.*?^\}\n", source, re.S | re.M)
    if match is None:
        raise AssertionError(f"no json_escape function in {HOOK}")
    # Run from a file, not `sh -c`: on Windows the argument quoting eats backslashes.
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "escape.sh"
        script.write_bytes((match.group(0) + "json_escape\n").encode("utf-8"))
        # The shell's own bin directory has to be on PATH, for the tools json_escape runs.
        env = dict(os.environ)
        env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
        done = subprocess.run([SH, str(script)], input=text.encode("utf-8"),
                              capture_output=True, check=True, env=env)
    return done.stdout.decode("utf-8")


@unittest.skipIf(SH is None, "no POSIX shell available; not reporting a pass")
class JsonEscape(unittest.TestCase):
    def parsed(self, text: str) -> str:
        return json.loads('"' + json_escape(text) + '"')

    def test_colour_codes_and_carriage_returns_give_valid_json(self):
        detail = f"{ESC}[0;34mRan 12 tests{ESC}[0m\r\nOK {ESC}[1;31mFAILED{ESC}[0m"
        self.assertEqual(self.parsed(detail), "Ran 12 tests OK FAILED")

    def test_any_other_control_character_is_dropped(self):
        self.assertEqual(self.parsed("a\x00b\x07c\x0bd\x0ce\x1ff"), "abcdef")

    def test_backslash_quote_tab_and_newline_are_unchanged(self):
        self.assertEqual(json_escape('a\\b "q"\tt\nn'), 'a\\\\b \\"q\\"\\tt n')
        self.assertEqual(self.parsed('a\\b "q"\tt\nn'), 'a\\b "q"\tt n')


if __name__ == "__main__":
    unittest.main()
