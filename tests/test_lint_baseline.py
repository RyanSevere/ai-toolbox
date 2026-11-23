#!/usr/bin/env python3
################################################################################
# File: test_lint_baseline.py
# Path: {PROJECT_ROOT}/tests/test_lint_baseline.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-23
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


ZEROS = "0" * 40


class PushBase(LintBaseline):
    """Which base a push is linted against. Each test builds a repository with a bare remote,
    a deploy branch (main) and a feature branch, and runs main with the tool's runner patched
    to record the paths it is handed."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(LIB.parent))
        self.addCleanup(sys.path.remove, str(LIB.parent))
        import lint_baseline
        self.lib = lint_baseline
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        self.remote = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.remote, ignore_errors=True)
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("remote", "add", "origin", str(self.remote))

    def commit(self, rel: str, text: str = "VALUE = 1\n") -> str:
        self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"add {rel}")
        return self.git("rev-parse", "HEAD")

    def world(self, deploy_branch: bool = True) -> dict[str, str]:
        """main has a.py (pushed), feature branches from it with b.py (not pushed), then main
        moves on with c.py (pushed). The merge-base of feature and origin/main is a.py's commit."""
        config = "config-dir=.gates\n" + ("deploy-branch=main\n" if deploy_branch else "")
        self.write(".githooks/gate-config", config)
        first = self.commit("a.py")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "-b", "feature")
        feature = self.commit("b.py")
        self.git("checkout", "-q", "main")
        second = self.commit("c.py")
        self.git("push", "-q", "origin", "main")
        return {"first": first, "feature": feature, "second": second}

    def run_main(self, sha: str, base: str, ref: str | None, *extra: str):
        """(exit code, printed text, the lists of paths the runner was handed)."""
        seen: list[list[str]] = []

        def runner(root, files, at):
            seen.append(sorted(files))
            return []

        selector = self.lib.TOOLS["ruff"][0]
        env = {} if ref is None else {"PUSH_REMOTE_REF": ref}
        with unittest.mock.patch.dict(self.lib.TOOLS, {"ruff": (selector, runner)}), \
                unittest.mock.patch.dict(os.environ, env), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            if ref is None:
                os.environ.pop("PUSH_REMOTE_REF", None)
            code = self.lib.main(["--tool", "ruff", "--sha", sha, "--base", base,
                                  "--remote", "origin", *extra])
        return code, out.getvalue(), seen

    def test_new_branch_uses_the_merge_base(self):
        """Intent: ticket 189, Done when 1: a new branch is linted only for what changed since
        the merge-base with the remote deploy branch, and the range line says so."""
        w = self.world()
        code, out, seen = self.run_main(w["feature"], ZEROS, "refs/heads/feature")
        self.assertEqual(code, 0, out)
        self.assertEqual(seen, [["b.py"]], out)
        self.assertIn("range: merge-base with origin/main (new branch)", out)

    def test_deploy_branch_keeps_the_remote_sha(self):
        """Intent: ticket 189, Done when 2: a push to the deploy branch is linted against the
        remote sha it was given, as before."""
        w = self.world()
        code, out, seen = self.run_main(w["second"], w["first"], "refs/heads/main")
        self.assertEqual(code, 0, out)
        self.assertEqual(seen, [["c.py"]], out)

    def test_existing_branch_keeps_the_remote_sha(self):
        """Intent: ticket 189, Done when 2: a push to a branch that already exists is linted
        against its remote sha, not the merge-base (which would add b.py)."""
        w = self.world()
        self.git("checkout", "-q", "feature")
        self.git("push", "-q", "origin", "feature")
        newest = self.commit("d.py")
        code, out, seen = self.run_main(newest, w["feature"], "refs/heads/feature")
        self.assertEqual(code, 0, out)
        self.assertEqual(seen, [["d.py"]], out)
        self.assertIn("range: as pushed (existing branch)", out)

    def test_no_merge_base_lints_everything(self):
        """Intent: ticket 189, Done when 3: a new branch with no merge-base with the deploy
        branch, or a deploy branch the remote does not have, lints every tracked file and
        says so on the range line."""
        self.world()
        self.git("checkout", "-q", "--orphan", "lone")
        self.git("rm", "-rfq", "--cached", ".")
        self.write("e.py")
        self.write("f.py")
        self.git("add", "e.py", "f.py")
        self.git("commit", "-q", "-m", "unrelated history")
        lone = self.git("rev-parse", "HEAD")
        code, out, seen = self.run_main(lone, ZEROS, "refs/heads/lone")
        self.assertEqual(code, 0, out)
        self.assertEqual(seen, [["e.py", "f.py"]], out)
        self.assertIn("range: none (", out)
        # A remote with no tracking refs gives git merge-base nothing to compare with.
        self.git("checkout", "-q", "feature")
        seen_none = []
        with unittest.mock.patch.dict(os.environ, {"PUSH_REMOTE_REF": "refs/heads/feature"}), \
                contextlib.redirect_stdout(io.StringIO()) as out2:
            selector = self.lib.TOOLS["ruff"][0]
            with unittest.mock.patch.dict(self.lib.TOOLS, {"ruff": (
                    selector, lambda r, files, at: seen_none.append(sorted(files)) or [])}):
                code2 = self.lib.main(["--tool", "ruff", "--sha", "feature", "--base", ZEROS,
                                       "--remote", "nowhere"])
        self.assertEqual(code2, 0, out2.getvalue())
        self.assertEqual(seen_none, [["a.py", "b.py"]], out2.getvalue())
        self.assertIn("range: none (", out2.getvalue())

    def test_without_a_pushed_ref_the_base_is_as_given(self):
        """Intent: ticket 189, Done when 4: with PUSH_REMOTE_REF unset (the gate run by hand)
        the base is the --base given, and an all-zero base lints every file, as today."""
        w = self.world()
        code, out, seen = self.run_main(w["second"], w["first"], None)
        self.assertEqual(code, 0, out)
        self.assertEqual(seen, [["c.py"]], out)
        code, out, seen = self.run_main(w["feature"], ZEROS, None)
        self.assertEqual(code, 0, out)
        self.assertEqual(seen, [["a.py", "b.py"]], out)

    def test_missing_deploy_branch_refuses(self):
        """Intent: ticket 189, Done when 5: a gate-config with no deploy-branch refuses while
        PUSH_REMOTE_REF is set, and never guesses a branch."""
        w = self.world(deploy_branch=False)
        code, out, seen = self.run_main(w["feature"], ZEROS, "refs/heads/feature")
        self.assertEqual(code, 1, out)
        self.assertIn("REFUSED:", out)
        self.assertIn("deploy-branch", out)
        self.assertEqual(seen, [])

    def test_an_invalid_remote_refuses(self):
        """Intent: ticket 189, Done when 5: a --remote that fails ^[A-Za-z0-9._-]{1,100}$
        refuses before it reaches git, and nothing is linted."""
        w = self.world()
        for bad in ("up stream", "origin;rm", "../origin", "a" * 101, ""):
            with self.subTest(remote=bad):
                seen: list[list[str]] = []
                selector = self.lib.TOOLS["ruff"][0]
                with unittest.mock.patch.dict(self.lib.TOOLS, {"ruff": (
                        selector, lambda r, files, at: seen.append(files) or [])}), \
                        unittest.mock.patch.dict(os.environ, {"PUSH_REMOTE_REF": "refs/heads/feature"}), \
                        contextlib.redirect_stdout(io.StringIO()) as out:
                    code = self.lib.main(["--tool", "ruff", "--sha", w["feature"],
                                          "--base", ZEROS, "--remote", bad])
                self.assertEqual(code, 1, out.getvalue())
                self.assertIn("REFUSED:", out.getvalue())
                self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
