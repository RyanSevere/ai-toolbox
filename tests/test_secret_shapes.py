#!/usr/bin/env python3
################################################################################
# File: test_secret_shapes.py
# Path: {PROJECT_ROOT}/tests/test_secret_shapes.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: Tests for githooks/lib/secret_shapes.py, the one source of the
#              credential shapes. find() reports each shape and skips
#              placeholders, the opt-out and clean lines; the command line
#              reads path:line: text on stdin, reports where and never what,
#              and exits 1 on any hit. Fixture values are built at run time
#              from obviously fake parts. Stdlib only.
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

import importlib.util
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE = Path(__file__).resolve().parent.parent / "githooks" / "lib" / "secret_shapes.py"
EXERCISES = ["githooks/lib/**"]


def load():
    spec = importlib.util.spec_from_file_location("secret_shapes", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Built from parts so no line of this file is itself a credential shape.
HEX = "0123456789abcdef" * 2
LONG = "Kq7Lm2Vx" * 3
KEY_HEADER = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"


class Find(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shapes = load()

    def test_each_shape_is_reported_with_its_line_number(self):
        lines = [
            "clean line",
            f"token {HEX} here",
            KEY_HEADER,
            f"API_TOKEN={LONG}",
        ]
        self.assertEqual(self.shapes.find(lines),
                         [(2, "hex"), (3, "privkey"), (4, "assign")])

    def test_a_bare_hex_token_is_found_at_either_end_of_a_line(self):
        for line in (HEX, f"x={HEX}", f'"{HEX}"', f"{HEX} trailing"):
            with self.subTest(line=line):
                self.assertEqual(self.shapes.find([line]), [(1, "hex")])

    def test_hex_inside_a_path_url_or_longer_hash_is_not_a_token(self):
        for line in (
            f"/var/cache/{HEX}/data",
            f"https://host.invalid/{HEX}",
            f"C:\\logs\\{HEX}\\run",
            f"{HEX}0123456789abcdef",  # 48 hex: a longer hash
            f"commit {'0123456789abcdef0123456789abcdef01234567'}",  # 40-hex commit id
            f"file.{HEX}.js",
            "0123456789abcdef0123456789abcde",  # 31 hex
        ):
            with self.subTest(line=line):
                self.assertEqual(self.shapes.find([line]), [])

    def test_private_key_headers_with_and_without_a_type(self):
        for line in (KEY_HEADER, "-----BEGIN " + "PRIVATE KEY" + "-----",
                     "-----BEGIN " + "OPENSSH PRIVATE KEY" + "-----"):
            with self.subTest(line=line):
                self.assertEqual(self.shapes.find([line]), [(1, "privkey")])

    def test_assignment_forms_that_name_a_secret(self):
        for line in (
            f"API_KEY={LONG}",
            f"export DB_PASSWORD={LONG}",
            f'  SESSION_SECRET: "{LONG}"',
            f"- AUTH_TOKEN: '{LONG}'",
            f"SERVICE_PASSWD = {LONG}",
            f"export  KEY={LONG}",
            f"KEY={'a' * 24}",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.shapes.find([line]), [(1, "assign")])

    def test_assignment_near_misses_are_not_reported(self):
        for line in (
            f"API_KEY={LONG[:23]}",  # one short of the length
            f"api_key={LONG}",  # the name is upper case
            f"KEYBOARD={LONG}",  # the name must end in the word
            f"API_KEY_PATH={LONG}",
            f"x = API_KEY={LONG}",  # anchored to the start of the line
            "API_KEY=",
            "API_KEY=${API_KEY}",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.shapes.find([line]), [])

    def test_a_placeholder_value_is_not_reported(self):
        for word in ("your", "change", "example", "placeholder", "dummy", "sample", "xxxx",
                     "<", "ci-", "test", "fake", "YOUR", "Example"):
            line = f"API_KEY=aaaa{word}aaaaaaaaaaaaaaaaaaaaaaaa"
            with self.subTest(word=word):
                self.assertEqual(self.shapes.find([line]), [])

    def test_a_placeholder_does_not_excuse_a_hex_token_or_a_key_header(self):
        self.assertEqual(self.shapes.find([f"fake {HEX} test"]), [(1, "hex")])
        self.assertEqual(self.shapes.find([f"example {KEY_HEADER}"]), [(1, "privkey")])

    def test_the_opt_out_skips_its_line_only(self):
        lines = [f"token {HEX}  # secret-scan: allow", f"token {HEX}"]
        self.assertEqual(self.shapes.find(lines), [(2, "hex")])

    def test_line_numbers_count_every_line_and_clean_input_is_empty(self):
        self.assertEqual(self.shapes.find([]), [])
        self.assertEqual(self.shapes.find(["a", "b", "c"]), [])
        self.assertEqual(self.shapes.find(["", "", f"{HEX}"]), [(3, "hex")])

    def test_a_line_with_two_shapes_reports_both(self):
        found = self.shapes.find([f"API_KEY={LONG} {HEX}"])
        self.assertEqual(sorted(found), [(1, "assign"), (1, "hex")])


class CommandLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shapes = load()

    def run_main(self, text: str) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch("sys.stdin", new=io.StringIO(text)), mock.patch("sys.stdout", new=out):
            code = self.shapes.main()
        return code, out.getvalue()

    def test_a_hit_prints_where_and_which_shape_and_exits_one(self):
        code, out = self.run_main(f"src/app.py:12: token {HEX}\nREADME.md:3: fine\n")
        self.assertEqual((code, out), (1, "src/app.py:12: hex\n"))

    def test_the_matched_text_is_never_printed(self):
        code, out = self.run_main(f"a.env:1: API_KEY={LONG}\nb.pem:2: {KEY_HEADER}\n"
                                  f"c.txt:3: {HEX}\n")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["a.env:1: assign", "b.pem:2: privkey", "c.txt:3: hex"])
        for secret in (LONG, HEX, "PRIVATE KEY"):
            self.assertNotIn(secret, out)

    def test_no_hit_prints_nothing_and_exits_zero(self):
        self.assertEqual(self.run_main("a.py:1: print('hi')\nb.py:2: x = 1\n"), (0, ""))
        self.assertEqual(self.run_main(""), (0, ""))

    def test_the_opt_out_and_placeholders_exit_zero(self):
        text = (f"a.py:1: {HEX}  # secret-scan: allow\n"
                "b.env:2: API_KEY=your-key-goes-here-aaaaaaaaaaaa\n")
        self.assertEqual(self.run_main(text), (0, ""))

    def test_a_path_with_a_colon_and_lines_that_are_not_hits_input(self):
        text = f"C:\\work\\a.py:7: {HEX}\nnot a located line {HEX}\n"
        self.assertEqual(self.run_main(text), (1, "C:\\work\\a.py:7: hex\n"))

    def test_run_as_a_script_reads_stdin_and_sets_the_exit_code(self):
        for text, code in ((f"a.py:1: {HEX}\n", 1), ("a.py:1: clean\n", 0)):
            with self.subTest(code=code):
                done = subprocess.run([sys.executable, "-B", str(MODULE)], input=text,
                                      capture_output=True, text=True, check=False)
                self.assertEqual(done.returncode, code)
                self.assertNotIn(HEX, done.stdout)


if __name__ == "__main__":
    unittest.main()
