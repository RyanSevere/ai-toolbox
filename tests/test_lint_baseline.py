#!/usr/bin/env python3
################################################################################
# File: test_lint_baseline.py
# Path: {PROJECT_ROOT}/tests/test_lint_baseline.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: Runs githooks/lib/lint_baseline.py against throwaway git repositories:
#              files the repository does not own - the vendored core, and anything
#              carrying the render stamp - are never linted, and a finding in an
#              owned file is still reported.
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

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "githooks" / "lib" / "lint_baseline.py"

# Shell and eslint paths are shared with ruff's; each runs only where its tool is on PATH.
EXERCISES = ["githooks/lib/lint_baseline.py"]

UNUSED = "import os\n"
STAMP_PY = "# generated from some-profile@abc1234 - edit the source, not this file\n"
STAMP_PY_UNPINNED = "# generated from some-profile - edit the source, not this file\n"
STAMP_SH = "# generated from some-profile@abc1234 - edit the source, not this file\n"
BAD_SH = "#!/bin/sh\necho $unquoted_thing $other\nfoo=$(ls) ; echo $foo\n"


class LintBaseline(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.write(".githooks/gate-config", "config-dir=.gates\n")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True,
                              text=True, check=False).stdout.strip()

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def lint(self, tool: str):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        return subprocess.run([sys.executable, "-B", str(LIB), "--tool", tool, "--sha", "HEAD"],
                              cwd=self.repo, capture_output=True, text=True)


@unittest.skipUnless(shutil.which("ruff"), "ruff is not installed; not reporting a pass")
class Ruff(LintBaseline):
    def test_an_owned_file_with_a_finding_is_reported(self):
        self.write("app/mod.py", UNUSED)
        result = self.lint("ruff")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("app/mod.py", result.stdout)

    def test_the_vendored_core_is_not_linted(self):
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tool.py", UNUSED)
        self.write("app/mod.py", "VALUE = 1\n")
        result = self.lint("ruff")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("core/tool.py", result.stdout)

    def test_a_core_folder_with_no_vendored_marker_is_linted(self):
        self.write("core/tool.py", UNUSED)
        result = self.lint("ruff")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("core/tool.py", result.stdout)

    def test_a_stamped_file_is_not_linted(self):
        self.write(".claude/skills/thing/run.py", STAMP_PY + UNUSED)
        self.write(".github/scripts/other.py", STAMP_PY_UNPINNED + UNUSED)
        result = self.lint("ruff")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Nothing to check", result.stdout)

    def test_a_stamp_past_the_first_forty_lines_does_not_exempt(self):
        self.write("app/mod.py", "# filler\n" * 40 + STAMP_PY + UNUSED)
        result = self.lint("ruff")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("app/mod.py", result.stdout)

    def test_a_stamp_on_line_forty_still_exempts(self):
        self.write("app/mod.py", "# filler\n" * 39 + STAMP_PY + UNUSED)
        self.assertEqual(self.lint("ruff").returncode, 0)

    def test_owned_findings_are_reported_beside_skipped_files(self):
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tool.py", UNUSED)
        self.write(".githooks/lib/x.py", STAMP_PY + UNUSED)
        self.write("app/mod.py", UNUSED)
        result = self.lint("ruff")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("app/mod.py", result.stdout)
        self.assertNotIn("core/tool.py", result.stdout)
        self.assertNotIn(".githooks/lib/x.py", result.stdout)


@unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed; not reporting a pass")
class Shellcheck(LintBaseline):
    def test_an_owned_script_with_a_finding_is_reported(self):
        self.write("bin/run.sh", BAD_SH)
        result = self.lint("shellcheck")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("bin/run.sh", result.stdout)

    def test_vendored_and_stamped_scripts_are_not_linted(self):
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tool.sh", BAD_SH)
        self.write(".githooks/gates/x.sh", BAD_SH.replace("\n", "\n" + STAMP_SH, 1))
        result = self.lint("shellcheck")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Nothing to check", result.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed; not reporting a pass")
class Eslint(LintBaseline):
    def test_vendored_and_stamped_scripts_are_not_linted(self):
        """Only the selection is checked: with nothing owned left, eslint is never started."""
        # The config is itself JavaScript, so it carries the stamp or it would be linted.
        self.write("eslint.config.js", "// generated from some-profile@abc1234 - edit the source, not this file\nexport default [];\n")
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tool.js", "var a = 1\n")
        self.write("dist/out.js", "// generated from some-profile@abc1234 - edit the source, not this file\nvar b = 1\n")
        result = self.lint("eslint")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Nothing to check", result.stdout)


class Batched(LintBaseline):
    """The candidate paths are read through one git cat-file, not one git show each."""

    def module(self):
        sys.path.insert(0, str(LIB.parent))
        self.addCleanup(sys.path.remove, str(LIB.parent))
        import lint_baseline
        return lint_baseline

    def in_repo(self):
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def test_blobs_reads_every_path_and_maps_a_missing_one_to_none(self):
        lib = self.module()
        self.write("a.txt", "alpha\n")
        self.write("my dir/b c.txt", "beta\n")
        self.write("café/ü.txt", "gamma\n")
        self.write("empty.txt", "")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        self.in_repo()
        got = lib.blobs("HEAD", ["a.txt", "my dir/b c.txt", "café/ü.txt", "empty.txt",
                                 "gone.txt", "a.txt"])
        self.assertEqual(got, {"a.txt": b"alpha\n", "my dir/b c.txt": b"beta\n",
                               "café/ü.txt": b"gamma\n", "empty.txt": b"",
                               "gone.txt": None})

    def test_blobs_of_nothing_is_empty(self):
        lib = self.module()
        self.assertEqual(lib.blobs("HEAD", []), {})

    def test_blobs_raises_when_git_cannot_read_rather_than_returning_empty(self):
        lib = self.module()
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        cwd = os.getcwd()
        os.chdir(outside)
        self.addCleanup(os.chdir, cwd)
        with unittest.mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": outside}):
            with self.assertRaises(lib.LintError):
                lib.blobs("HEAD", ["a.txt"])

    def test_main_starts_one_cat_file_for_all_its_candidate_paths(self):
        lib = self.module()
        for n in range(5):
            self.write(f"app/m{n}.py", STAMP_PY + UNUSED)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        self.in_repo()
        calls: list[list[str]] = []
        real_popen = subprocess.Popen

        def popen(args, *a, **kw):
            calls.append(list(args))
            return real_popen(args, *a, **kw)

        # subprocess.run starts every process through Popen, so this counts each one once.
        with unittest.mock.patch.object(subprocess, "Popen", popen), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = lib.main(["--tool", "ruff", "--sha", "HEAD"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("Nothing to check", out.getvalue())
        batches = [c for c in calls if "cat-file" in c and "--batch" in c]
        shows = [c for c in calls if "show" in c and any("app/" in a for a in c)]
        self.assertEqual(len(batches), 1, calls)
        self.assertEqual(shows, [], calls)


if __name__ == "__main__":
    unittest.main()
