#!/usr/bin/env python3
################################################################################
# File: test_secret_shapes.py
# Path: {PROJECT_ROOT}/tests/test_secret_shapes.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-17
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
            f"KEYBOARD={LONG}",  # the name must end in the word
            f"API_KEY_PATH={LONG}",
            f"x = API_KEY={LONG}",  # anchored to the start of the line
            "API_KEY=",
            "API_KEY=${API_KEY}",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.shapes.find([line]), [])

    def test_a_lowercase_name_is_a_keyed_hit_not_a_near_miss(self):
        self.assertEqual(self.shapes.find([f"api_key={LONG}"]), [(1, "keyed")])

    def test_a_placeholder_value_is_not_reported(self):
        for value in ("your-api-key-here-1234", "example_token_value_1",
                      "ci-validation-placeholder-value", "a1-dummy-b2-" + "c" * 12,
                      "a1.sample.b2." + "c" * 12, "fake-a1-b2-" + "c" * 14,
                      "a1_test_b2_" + "c" * 14, "a1-xxxx-b2-" + "c" * 14):
            line = f"API_KEY={value}"
            with self.subTest(value=value):
                self.assertEqual(self.shapes.find([line]), [])

    def test_a_placeholder_word_buried_in_a_random_part_is_now_reported(self):
        self.assertEqual(self.shapes.find(["API_KEY=aaaa" + "test" + "a1" * 12]), [(1, "assign")])

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


# Provider-shaped values, built from parts so no line of this file matches a shape.
GH_TOKEN = "gh" + "p_" + "A1b2" * 9  # 36 characters after the prefix
AWS_ID = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
ANT_TOKEN = "sk" + "-ant-" + "api03-" + "Zx9" * 20
URL_PASSWORD = "S3cret" + "Passw0rd"
KEYED_VALUE = "Rt5Yu8Io" * 3  # 24 characters


class NewShapes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shapes = load()

    def shapes_of(self, line: str) -> list[str]:
        return self.shapes.shapes_in(line)

    def test_the_new_names_follow_the_existing_three_in_order(self):
        self.assertEqual(self.shapes.SHAPES,
                         ("hex", "privkey", "assign", "provider", "keyed", "urlcred"))

    def test_a_lowercase_python_assignment_is_keyed_and_provider(self):
        self.assertEqual(self.shapes_of(f'api_key = "{GH_TOKEN}"'), ["provider", "keyed"])

    def test_a_json_member_is_caught(self):
        self.assertEqual(self.shapes_of(f'  "token": "{GH_TOKEN}",'), ["provider", "keyed"])

    def test_an_authorization_header_is_caught(self):
        line = f'curl -H "Authorization: token {GH_TOKEN}"'
        self.assertIn("provider", self.shapes_of(line))

    def test_an_anthropic_token_under_a_name_without_key_is_caught(self):
        self.assertEqual(self.shapes_of(f"ANTHROPIC={ANT_TOKEN}"), ["provider"])

    def test_an_aws_access_key_id_is_caught(self):
        self.assertEqual(self.shapes_of(f"aws_access_key_id = {AWS_ID}"), ["provider"])

    def test_a_url_with_a_password_is_caught(self):
        line = 'url = "https://bob:' + URL_PASSWORD + '@db.example.org"'
        self.assertEqual(self.shapes_of(line), ["urlcred"])

    def test_the_uppercase_assignment_is_still_caught(self):
        self.assertIn("assign", self.shapes_of(f"GITHUB_TOKEN={GH_TOKEN}"))

    def test_a_placeholder_word_inside_a_random_value_does_not_excuse_it(self):
        value = "ghp_" + "A1b2" * 4 + "test" + "C3d4" * 4
        self.assertEqual(self.shapes_of(f"GITHUB_TOKEN={value}"), ["assign", "provider"])

    def test_each_other_provider_prefix_is_caught(self):
        for value in (
            "github_pat_" + "A1b2C3d4" * 8,
            "sk-" + "A1b2C3d4e5" * 4,
            "xox" + "b-" + "1234567890" + "-abc",
            "AI" + "za" + "A1b2C3d4" * 4 + "xyz",
            "ey" + "J" + "hbGciOiJIUzI1" + "." + "eyJzdWIiOiIxMjM0" + "." + "SflKxwRJSMeKKF2Q",
            "xox" + "p-" + "1234567890",
            "ASIA" + "ABCDEFGHIJKLMNOP",
            "gh" + "s_" + "A1b2" * 9,
        ):
            with self.subTest(value=value[:6]):
                self.assertIn("provider", self.shapes_of(f"see {value} here"))

    def test_an_empty_line_or_an_empty_value_is_not_a_hit(self):
        for line in ("", 'api_key = ""', "api_key ="):
            with self.subTest(line=line):
                self.assertEqual(self.shapes_of(line), [])

    def test_the_length_boundaries(self):
        self.assertEqual(self.shapes_of("x gh" + "p_" + "a" * 35), [])
        self.assertEqual(self.shapes_of("x gh" + "p_" + "a" * 36), ["provider"])
        self.assertEqual(self.shapes_of("api_key = " + "A1" * 11 + "b"), [])  # 23
        self.assertEqual(self.shapes_of("api_key = " + "A1" * 12), ["keyed"])  # 24
        self.assertEqual(self.shapes_of("AK" + "IA" + "A" * 15), [])

    def test_a_git_sha_and_a_uuid_are_not_hits(self):
        for line in ("commit " + "0123456789abcdef0123456789abcdef01234567",
                     "id 123e4567-e89b-12d3-a456-426614174000"):
            with self.subTest(line=line):
                self.assertEqual(self.shapes_of(line), [])

    def test_a_url_without_a_password_or_with_an_interpolation_is_not_a_hit(self):
        for line in ("https://user@host/x",
                     "git clone https://user:${GH_TOKEN}@host/x",
                     "git clone https://user:$GH_TOKEN@host/x",
                     "git clone https://user:%GH_TOKEN%@host/x",
                     "git clone https://user:{{ token }}@host/x",
                     "https://user:@host/x"):
            with self.subTest(line=line):
                self.assertEqual(self.shapes_of(line), [])

    def test_a_short_sk_class_name_is_not_a_hit(self):
        self.assertEqual(self.shapes_of('<div class="sk-loader">'), [])

    def test_a_path_value_is_not_a_hit(self):
        line = 'EXAMPLE_KEY="/usr/share/keyrings/example-archive-keyring.gpg"'
        self.assertEqual(self.shapes_of(line), [])

    def test_a_value_with_a_whole_placeholder_part_or_no_digit_is_not_a_hit(self):
        for line in ("RUNNER_API_KEY=ci-validation-placeholder-value",
                     'TOKEN = "fake-token-1234567890abcdefghij"',
                     "API_KEY=your-api-key-goes-here-1234567",
                     "api_key = " + "a" * 24,
                     "api_key = " + "7" * 24):
            with self.subTest(line=line):
                self.assertEqual(self.shapes_of(line), [])

    def test_a_checksum_named_key_is_not_a_hit(self):
        line = 'PVE_KEY_SHA512="' + "0123456789abcdef" * 8 + '"'
        self.assertEqual(self.shapes_of(line), [])

    def test_a_line_with_several_shapes_reports_each_once_in_order(self):
        line = f"API_KEY={GH_TOKEN} {HEX} https://bob:{URL_PASSWORD}@host"
        self.assertEqual(self.shapes_of(line),
                         ["hex", "assign", "provider", "urlcred"])

    def test_keyed_is_never_reported_beside_assign(self):
        self.assertEqual(self.shapes_of(f"API_KEY={KEYED_VALUE}"), ["assign"])
        self.assertEqual(self.shapes_of("KEY=" + "a" * 24), ["assign"])

    def test_keyed_names_by_their_last_part(self):
        for line in (f"api_key={KEYED_VALUE}", f"apiKey: {KEYED_VALUE}",
                     f"db.password = {KEYED_VALUE}", f"const authToken = '{KEYED_VALUE}'"):
            with self.subTest(line=line[:12]):
                self.assertEqual(self.shapes_of(line), ["keyed"])
        for line in (f"KEYBOARD={KEYED_VALUE}", f"API_KEY_PATH={KEYED_VALUE}",
                     f"x = API_KEY={KEYED_VALUE}", f"commit_sha_key = {KEYED_VALUE}",
                     'alert_key = "arr_sonarr_pending_import"'):
            with self.subTest(line=line[:12]):
                self.assertEqual(self.shapes_of(line), [])

    def test_a_buried_placeholder_word_is_reported_and_whole_parts_are_not(self):
        buried = "A1b2" * 3 + "test" + "C3d4" * 3
        self.assertEqual(self.shapes_of(f"api_key = {buried}"), ["keyed"])
        for value in ("your-api-key-here-1234", "example_token_value_1",
                      "ci-validation-placeholder-value", "dummy" + "-value-1234567890123456"):
            with self.subTest(value=value):
                self.assertEqual(self.shapes_of(f"api_key = {value}"), [])

    def test_the_opt_out_applies_to_every_new_shape(self):
        for line in (f'api_key = "{GH_TOKEN}"  # secret-scan: allow',
                     f"ANTHROPIC={ANT_TOKEN}  # secret-scan: allow",
                     f"https://bob:{URL_PASSWORD}@host  # secret-scan: allow",
                     f"api_key = {KEYED_VALUE}  # secret-scan: allow"):
            with self.subTest(line=line[:12]):
                self.assertEqual(self.shapes_of(line), [])


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
