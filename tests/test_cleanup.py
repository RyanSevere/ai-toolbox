################################################################################
# File: test_cleanup.py
# Path: {PROJECT_ROOT}/tests/test_cleanup.py
# Created by: Ryan Severe
# Created: 2026-11-07
# Last Updated: 2026-11-08
# Description: The workstream scratch cleanup, against a real
#              temporary repository with an origin, worktrees and branches.
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


import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cleanup  # noqa: E402

WS = "release-prep"


def clean_env() -> dict[str, str]:
    """The pre-push hook exports GIT_DIR and friends; a fixture repo must not inherit them."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(("git", *args), cwd=cwd, env=clean_env(), capture_output=True,
                            text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"fixture: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def force_remove(path: Path) -> None:
    def clear(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear)
    else:
        shutil.rmtree(path, onerror=clear)


class Repo(unittest.TestCase):
    """A clone with an origin whose HEAD names main, a shared scratch file, a second
    workstream, and one workstream with a worktree on a branch already merged."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(force_remove, self.tmp)
        origin = self.tmp / "origin.git"
        git(self.tmp, "init", "--quiet", "--bare", "-b", "main", str(origin))
        self.repo = self.tmp / "repo"
        git(self.tmp, "init", "--quiet", "-b", "main", str(self.repo))
        for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"),
                           ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
            git(self.repo, "config", key, value)
        (self.repo / ".gitignore").write_text("scratch/\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "--quiet", "-m", "initial")
        git(self.repo, "remote", "add", "origin", str(origin))
        git(self.repo, "push", "--quiet", "-u", "origin", "main")
        git(self.repo, "remote", "set-head", "origin", "main")

        self.scratch = self.repo / "scratch"
        self.ws = self.scratch / WS
        self.ws.mkdir(parents=True)
        (self.ws / "notes.md").write_text("n\n", encoding="utf-8")
        (self.ws / "sub").mkdir()
        (self.ws / "sub" / "probe.py").write_text("p\n", encoding="utf-8")
        (self.scratch / "handoff-other.md").write_text("shared\n", encoding="utf-8")
        (self.scratch / "other-ws").mkdir()
        (self.scratch / "other-ws" / "keep.md").write_text("k\n", encoding="utf-8")
        self.wt = self.ws / "wt-work-1"
        git(self.repo, "worktree", "add", "--quiet", "-b", "work-1-merged", str(self.wt), "main")

        env = mock.patch.dict(os.environ, clean_env(), clear=True)
        env.start()
        self.addCleanup(env.stop)

    def run_cleanup(self, *args: str, cwd: Path | None = None) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cleanup.main(list(args), cwd=cwd or self.repo)
        return code, out.getvalue()

    def snapshot(self) -> tuple:
        files = sorted(p.relative_to(self.repo).as_posix() for p in self.scratch.rglob("*"))
        return (files, git(self.repo, "branch", "--list"),
                git(self.repo, "worktree", "list", "--porcelain"))

    def branches(self) -> str:
        return git(self.repo, "branch", "--list")

    def commit_in_worktree(self) -> None:
        (self.wt / "work.txt").write_text("w\n", encoding="utf-8")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "--quiet", "-m", "unmerged work")


class Listing(Repo):
    def test_listing_changes_nothing(self):
        """Intent: lists what it would remove ... and changes nothing."""
        before = self.snapshot()
        code, out = self.run_cleanup("--ws", WS)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("work-1-merged", out)
        self.assertIn("notes.md", out)
        self.assertIn("sub/probe.py", out)
        self.assertIn("nothing changed", out)

    def test_listing_does_not_descend_into_a_worktree(self):
        """Characterisation: a worktree is removed by git as one unit, so its files are not
        listed one by one, and its .git file would read as a loose scratch file."""
        (self.wt / "inside.txt").write_text("i\n", encoding="utf-8")
        _, out = self.run_cleanup("--ws", WS)
        self.assertNotIn("inside.txt", out)

    def test_listing_names_what_apply_would_refuse(self):
        """Intent: the listing is the inventory the operator approves."""
        (self.wt / "dirty.txt").write_text("d\n", encoding="utf-8")
        code, out = self.run_cleanup("--ws", WS)
        self.assertNotEqual(code, 0)
        self.assertIn("dirty", out.lower())


class Refusals(Repo):
    def assert_refused_unchanged(self, *args: str, needle: str) -> str:
        before = self.snapshot()
        code, out = self.run_cleanup(*args)
        self.assertNotEqual(code, 0, out)
        self.assertIn(needle, out.lower())
        self.assertEqual(self.snapshot(), before)
        return out

    def test_a_name_that_escapes_scratch_is_refused(self):
        """Intent: --apply refuses a path outside scratch/<objective>/."""
        outside = str(self.repo / "elsewhere")
        for name in ("..", "../repo", "a/b", "a\\b", outside, "", "Upper-Case", "-lead",
                     "trail-", "a--b", "."):
            with self.subTest(name=name):
                self.assert_refused_unchanged(f"--ws={name}", "--apply", needle="refused")

    def test_a_missing_directory_is_refused_not_reported_empty(self):
        """Intent: prescriptions.md - a failed lookup is a failure, never an empty result."""
        self.assert_refused_unchanged("--ws", "no-such-workstream", needle="no workstream directory")

    def test_a_dirty_worktree_is_refused(self):
        """Intent: it refuses a dirty worktree."""
        (self.wt / "dirty.txt").write_text("d\n", encoding="utf-8")
        self.assert_refused_unchanged("--ws", WS, "--apply", needle="dirty")
        self.assertTrue((self.wt / "dirty.txt").exists())

    def test_an_unmerged_branch_is_refused(self):
        """Intent: it refuses an unmerged branch rather than discarding work."""
        self.commit_in_worktree()
        self.assert_refused_unchanged("--ws", WS, "--apply", needle="not merged")
        self.assertIn("work-1-merged", self.branches())

    def test_a_detached_worktree_off_the_default_branch_is_refused(self):
        """Intent: a detached commit is work no branch holds."""
        self.commit_in_worktree()
        git(self.wt, "checkout", "--quiet", "--detach")
        git(self.repo, "branch", "-D", "work-1-merged")
        self.assert_refused_unchanged("--ws", WS, "--apply", needle="not merged")

    def test_merged_means_merged_into_the_remote_default_branch(self):
        """Intent: prescriptions.md - unknown is not zero; local main ahead of origin is unshipped."""
        (self.repo / "local.txt").write_text("l\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "--quiet", "-m", "local only")
        git(self.wt, "reset", "--quiet", "--hard", "main")
        self.assert_refused_unchanged("--ws", WS, "--apply", needle="not merged")

    def test_an_unknown_default_branch_is_refused(self):
        """Intent: prescriptions.md - never assume a value that could not be found out."""
        git(self.repo, "remote", "set-head", "origin", "--delete")
        self.assert_refused_unchanged("--ws", WS, "--apply", needle="default branch")

    def test_running_from_inside_the_directory_is_refused(self):
        """Characterisation: Windows cannot remove a directory that is a process's cwd, so a
        run from inside it would fail half-way, after the worktrees were already gone."""
        before = self.snapshot()
        code, out = self.run_cleanup("--ws", WS, "--apply", cwd=self.ws / "sub")
        self.assertNotEqual(code, 0, out)
        self.assertIn("inside", out.lower())
        self.assertEqual(self.snapshot(), before)

    def test_one_refusal_stops_everything(self):
        """Intent: one call; a partial removal is not a cleanup."""
        second = self.ws / "wt-work-2"
        git(self.repo, "worktree", "add", "--quiet", "-b", "work-2-unmerged", str(second), "main")
        (second / "w.txt").write_text("w\n", encoding="utf-8")
        git(second, "add", "-A")
        git(second, "commit", "--quiet", "-m", "unmerged")
        self.assert_refused_unchanged("--ws", WS, "--apply", needle="not merged")
        self.assertTrue(self.wt.exists())


class Apply(Repo):
    def test_apply_removes_the_workstream_and_nothing_else(self):
        """Intent: worktrees, merged branches, then the directory, and a workstream's cleanup
        never touches the root."""
        code, out = self.run_cleanup("--ws", WS, "--apply")
        self.assertEqual(code, 0, out)
        self.assertFalse(self.ws.exists())
        self.assertNotIn("work-1-merged", self.branches())
        self.assertNotIn(str(self.wt.name), git(self.repo, "worktree", "list"))
        self.assertTrue((self.scratch / "handoff-other.md").exists())
        self.assertTrue((self.scratch / "other-ws" / "keep.md").exists())

    def test_apply_removes_read_only_files(self):
        """Characterisation: git writes its objects read-only, and Windows will not delete a
        read-only file, so a copied .git under scratch would stop the removal half-way."""
        locked = self.ws / "sub" / "locked.txt"
        locked.write_text("r\n", encoding="utf-8")
        os.chmod(locked, stat.S_IREAD)
        code, out = self.run_cleanup("--ws", WS, "--apply")
        self.assertEqual(code, 0, out)
        self.assertFalse(self.ws.exists())

    def test_apply_works_from_inside_a_worktree_of_another_workstream(self):
        """Characterisation: the root is the primary checkout, found from git's common dir,
        so a run from any worktree aims at the same scratch/."""
        other = self.scratch / "other-ws" / "wt-work-9"
        git(self.repo, "worktree", "add", "--quiet", "-b", "work-9", str(other), "main")
        code, out = self.run_cleanup("--ws", WS, "--apply", cwd=other)
        self.assertEqual(code, 0, out)
        self.assertFalse(self.ws.exists())
        self.assertTrue(other.exists())


if __name__ == "__main__":
    unittest.main()
