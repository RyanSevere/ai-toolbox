#!/usr/bin/env python3
################################################################################
# File: test_push_timeout.py
# Path: {PROJECT_ROOT}/tests/test_push_timeout.py
# Created by: Ryan Severe
# Created: 2026-11-23
# Last Updated: 2026-11-23
# Description: A push that times out ends the whole process tree it started and
#              then reads the remote, so the rollout learns whether the commit
#              landed rather than guessing. Local bare repositories only, no
#              network, a short timeout passed to push_target.
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

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sync  # noqa: E402

TIMEOUT = 3
TIMEOUT_AFTER_PUSH = 8

CHILD = (
    "import os, sys, time\n"
    "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
    "time.sleep(60)\n"
)


def posix(path: Path) -> str:
    """A path the hook's shell reads the same on Windows and Linux."""
    return str(path).replace("\\", "/")


def pid_alive(pid: int) -> bool:
    """True while the process exists. The one place the platform differs."""
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=30).stdout
        return str(pid) in out.split()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=30)
    else:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def run_git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, env=env, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


class PushTimeoutBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.remote = self.tmp / "remote.git"
        self.repo = self.tmp / "work"
        self.pidfile = self.tmp / "child.pid"
        self.child = self.tmp / "child.py"
        self.child.write_text(CHILD, encoding="utf-8", newline="\n")
        run_git(self.tmp, "init", "--bare", "-b", "main", str(self.remote))
        run_git(self.tmp, "init", "-b", "main", str(self.repo))
        run_git(self.repo, "remote", "add", "origin", posix(self.remote))
        (self.repo / "a.txt").write_text("one\n", encoding="utf-8")
        run_git(self.repo, "add", "a.txt")
        run_git(self.repo, "commit", "-m", "first")
        run_git(self.repo, "push", "-u", "origin", "main")
        # Cleanups run last-in first-out: the child kill is registered after the
        # directory cleanup, so it runs before the directory is removed.
        self.addCleanup(self.kill_recorded_child)

    def kill_recorded_child(self) -> None:
        if self.pidfile.exists():
            text = self.pidfile.read_text(encoding="utf-8").strip()
            if text.isdigit() and pid_alive(int(text)):
                kill_pid(int(text))

    def new_commit(self) -> str:
        (self.repo / "a.txt").write_text("two\n", encoding="utf-8")
        run_git(self.repo, "commit", "-am", "second")
        return run_git(self.repo, "rev-parse", "HEAD")

    def install_hook(self, before: str = "") -> None:
        """A pre-push hook: optional steps, then a child that records its PID and
        sleeps, then the hook itself sleeps so git never sends anything."""
        py = posix(Path(sys.executable))
        script = (
            "#!/bin/sh\n"
            "unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX\n"
            f"{before}"
            f"\"{py}\" \"{posix(self.child)}\" \"{posix(self.pidfile)}\" &\n"
            "sleep 60\n"
        )
        hook = self.repo / ".git" / "hooks" / "pre-push"
        hook.write_text(script, encoding="utf-8", newline="\n")
        hook.chmod(0o755)

    def wait_for_child_pid(self) -> int:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.pidfile.exists():
                text = self.pidfile.read_text(encoding="utf-8").strip()
                if text.isdigit():
                    return int(text)
            time.sleep(0.1)
        self.fail("the hook's child never recorded its PID")


class PushTimeoutTests(PushTimeoutBase):
    def test_timeout_ends_the_process_tree(self) -> None:
        """Intent: ticket 182, Done when - a timed-out push leaves no process
        running. After push_target returns, the hook's child is gone."""
        self.new_commit()
        self.install_hook()
        try:
            sync.push_target(self.repo, timeout=TIMEOUT)
        except sync.SyncError:
            pass  # the outcome is covered below; this test is about the tree
        pid = self.wait_for_child_pid()
        time.sleep(0.5)
        self.assertFalse(pid_alive(pid), f"child {pid} is still running after the timeout")

    def test_timeout_with_nothing_landed_raises_not_landed(self) -> None:
        """Intent: ticket 182, Decided - when the remote is not at HEAD after a
        timeout, push_target raises SyncError naming 'not landed' and the short
        sha."""
        head = self.new_commit()
        self.install_hook()
        with self.assertRaises(sync.SyncError) as ctx:
            sync.push_target(self.repo, timeout=TIMEOUT)
        message = str(ctx.exception)
        self.assertIn("not landed", message)
        self.assertIn(head[:7], message)

    def test_timeout_with_commit_landed_returns_success_text(self) -> None:
        """Intent: ticket 182, Decided - when the remote is at HEAD after a
        timeout, push_target returns text naming the timeout and the remote's
        sha, so the rollout counts it as ok."""
        head = self.new_commit()
        remote_url = posix(self.remote)
        self.install_hook(f"git push --quiet --no-verify \"{remote_url}\" HEAD:refs/heads/main\n")
        result = sync.push_target(self.repo, timeout=TIMEOUT_AFTER_PUSH)
        self.assertIn("timed out", result)
        self.assertIn("remote is at", result)
        self.assertIn(head[:7], result)

    def test_normal_push_is_unchanged(self) -> None:
        """Intent: ticket 182, Decided - a push that exits in time behaves as
        before: 'pushed', and 'nothing to push' when nothing is ahead."""
        self.assertEqual(sync.push_target(self.repo, timeout=60), "nothing to push")
        head = self.new_commit()
        self.assertEqual(sync.push_target(self.repo, timeout=60), "pushed")
        self.assertEqual(run_git(self.remote, "rev-parse", "refs/heads/main"), head)

    def test_unreadable_remote_after_timeout_is_never_landed(self) -> None:
        """Intent: ticket 182, Decided - unknown is not landed. If the remote
        cannot be read after a timeout, push_target raises SyncError and the
        message does not claim the commit landed."""
        self.new_commit()
        gone = posix(self.tmp / "no-such-remote.git")
        self.install_hook(f"git remote set-url origin \"{gone}\"\n")
        with self.assertRaises(sync.SyncError) as ctx:
            sync.push_target(self.repo, timeout=TIMEOUT_AFTER_PUSH)
        message = str(ctx.exception)
        self.assertNotIn("remote is at", message)
        self.assertNotIn("landed", message.replace("not landed", ""))


if __name__ == "__main__":
    unittest.main()
