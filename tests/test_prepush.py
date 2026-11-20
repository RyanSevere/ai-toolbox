#!/usr/bin/env python3
################################################################################
# File: test_prepush.py
# Path: {PROJECT_ROOT}/tests/test_prepush.py
# Created by: Claude Code (Opus 5.5), for Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-20
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
import time
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


def _git(*args: str, cwd: Path, env: dict | None = None) -> str:
    clean = {k: v for k, v in (env or os.environ).items() if not k.startswith("GIT_")}
    done = subprocess.run(("git", *args), cwd=cwd, env=clean, capture_output=True, text=True,
                          timeout=120)
    if done.returncode != 0:
        raise AssertionError(f"fixture: git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


@unittest.skipIf(SH is None, "no POSIX shell available; not reporting a pass")
class Freshness(unittest.TestCase):
    """The hook's check that a target's rendered rules are the profile's newest release.

    Opt-in: only a gate-config with a release-tag line is checked. The newest release is read
    from a local bare repository standing in for profile-remote.
    """

    OLD, NEW = "rules-2026-11-01", "rules-2026-11-15"
    SOURCE = "acme-profile"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        work = base / "work"
        cls.profile_remote = base / "profile.git"
        _git("init", "--quiet", "--bare", "-b", "main", str(cls.profile_remote), cwd=base)
        _git("init", "--quiet", "-b", "main", str(work), cwd=base)
        for key, value in (("user.name", "fixture"), ("user.email", "fixture@example.invalid"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
            _git("config", key, value, cwd=work)
        (work / "rules.txt").write_text("one\n", encoding="utf-8")
        _git("add", "-A", cwd=work)
        _git("commit", "--quiet", "-m", "one", cwd=work)
        cls.old_sha = _git("rev-parse", "HEAD", cwd=work)
        _git("tag", cls.OLD, cwd=work)
        (work / "rules.txt").write_text("two\n", encoding="utf-8")
        _git("commit", "--quiet", "-am", "two", cwd=work)
        cls.new_sha = _git("rev-parse", "HEAD", cwd=work)
        # The newer release is annotated, so the check has to peel it to reach the commit.
        _git("tag", "-a", "-m", "release", cls.NEW, cwd=work)
        _git("remote", "add", "origin", str(cls.profile_remote), cwd=work)
        _git("push", "--quiet", "origin", "main", "--tags", cwd=work)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.remote = base / "origin.git"
        self.repo = base / "target"
        _git("init", "--quiet", "--bare", "-b", "main", str(self.remote), cwd=base)
        _git("init", "--quiet", "-b", "main", str(self.repo), cwd=base)
        for key, value in (("user.name", "fixture"), ("user.email", "fixture@example.invalid"),
                           ("commit.gpgsign", "false")):
            _git("config", key, value, cwd=self.repo)
        _git("remote", "add", "origin", str(self.remote), cwd=self.repo)
        self.write(".githooks/gates/enabled", "# generated from acme-profile@abc1234\n")
        self.env = dict(os.environ)
        self.env["PATH"] = str(Path(SH).parent) + os.pathsep + self.env.get("PATH", "")

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def config(self, stamp: str | None, *, release_tag: str | None = "rules-*",
               remote: str | None = ..., extra: str = "") -> None:
        """A rendered gate-config. `stamp` is the whole first line; the keys follow."""
        remote = str(self.profile_remote) if remote is ... else remote
        lines = [stamp if stamp is not None else "# not a stamp",
                 "deploy-branch=main", "identity-email=t@t.invalid"]
        if release_tag is not None:
            lines.append(f"release-tag={release_tag}")
        if remote is not None:
            lines.append(f"profile-remote={remote}")
        self.write(".githooks/gate-config", "\n".join(lines) + "\n" + extra)

    def pinned(self, sha: str) -> str:
        return f"# generated from {self.SOURCE}@{sha[:7]} - edit the source, not this file"

    def push(self, branch: str = "main", env: dict | None = None) -> subprocess.CompletedProcess:
        _git("add", "-A", cwd=self.repo)
        _git("commit", "--quiet", "--allow-empty", "-m", "change", cwd=self.repo)
        sha = _git("rev-parse", "HEAD", cwd=self.repo)
        return subprocess.run(
            [SH, str(HOOK), "origin"], cwd=self.repo, env={**(env or self.env)},
            text=True, capture_output=True, timeout=180,
            input=f"refs/heads/{branch} {sha} refs/heads/{branch} {'0' * 40}\n")

    def rules_lines(self, result: subprocess.CompletedProcess) -> list[str]:
        return [line for line in result.stderr.splitlines() if "rules" in line.lower()]

    def test_a_gate_config_without_a_release_tag_skips_the_check_silently(self):
        """Intent: the check is opt-in. A render from a profile that sets no release tag
        carries no release-tag line, and its pushes are not held on it."""
        self.config(self.pinned(self.old_sha), release_tag=None, remote="/nowhere/at/all")
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rules_lines(result), [], result.stderr)

    def test_a_stamp_at_the_newest_release_is_current_and_silent(self):
        self.config(self.pinned(self.new_sha))
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rules_lines(result), [], result.stderr)

    def test_behind_the_newest_release_refuses_on_the_deploy_branch(self):
        """Intent: a stamp that matches an older release is behind."""
        self.config(self.pinned(self.old_sha))
        result = self.push("main")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("--pull", result.stderr)
        self.assertIn(self.NEW, result.stderr)
        self.assertEqual(self.reports(), [], "a refused push published a report")

    def test_a_stamp_that_matches_no_release_is_behind(self):
        self.config(self.pinned("deadbeef" * 5))
        result = self.push("main")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("--pull", result.stderr)

    def test_behind_on_another_branch_warns_once_and_pushes(self):
        self.config(self.pinned(self.old_sha))
        result = self.push("feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        warned = [line for line in result.stderr.splitlines() if "--pull" in line]
        self.assertEqual(len(warned), 1, result.stderr)

    def assert_cannot_tell(self, **config) -> None:
        stamp = config.pop("stamp", self.pinned(self.new_sha))
        self.config(stamp, **config)
        refused = self.push("main")
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("cannot tell whether the rules are current", refused.stderr)
        warned = self.push("feature")
        self.assertEqual(warned.returncode, 0, warned.stderr)
        self.assertIn("cannot tell whether the rules are current", warned.stderr)

    def test_an_unreachable_profile_remote_is_never_current(self):
        self.assert_cannot_tell(remote=str(self.profile_remote) + "-missing")

    def test_a_missing_profile_remote_key_is_never_current(self):
        self.assert_cannot_tell(remote=None)

    def test_an_unreadable_stamp_is_never_current(self):
        self.assert_cannot_tell(stamp=None)
        self.assert_cannot_tell(stamp=f"# generated from {self.SOURCE}@xyz - edit the source")

    def test_no_release_tag_on_the_remote_is_never_current(self):
        self.assert_cannot_tell(release_tag="nomatch-*")

    def test_an_unpinned_stamp_skips_the_check(self):
        """Intent: the profile's own repository renders a stamp with no sha, and has no
        release to be behind."""
        self.config(f"# generated from {self.SOURCE} - edit the source, not this file",
                    remote="/nowhere/at/all")
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rules_lines(result), [], result.stderr)

    def test_a_lookup_that_hangs_is_cut_off_after_twenty_seconds(self):
        """Intent: a remote that never answers is a failed lookup, not a hung push. A git
        ahead of the real one on PATH stalls ls-remote."""
        self.assert_a_hang_is_cut_off(usable_timeout=True)

    def test_a_lookup_that_hangs_is_cut_off_where_there_is_no_usable_timeout(self):
        """Intent: the watchdog path, for a shell whose timeout is absent or is not the
        coreutils one. A timeout that fails the hook's probe stands in for that."""
        self.assert_a_hang_is_cut_off(usable_timeout=False)

    def assert_a_hang_is_cut_off(self, usable_timeout: bool) -> None:
        shim = self.repo.parent / "shim"
        shim.mkdir()
        real = shutil.which("git", path=self.env["PATH"])
        (shim / "git").write_text(
            '#!/bin/sh\ncase "$*" in *ls-remote*) exec sleep 120 ;; esac\n'
            f'exec "{Path(real).as_posix()}" "$@"\n', encoding="utf-8", newline="\n")
        (shim / "git").chmod(0o755)
        if not usable_timeout:
            (shim / "timeout").write_text("#!/bin/sh\nexit 125\n", encoding="utf-8", newline="\n")
            (shim / "timeout").chmod(0o755)
        env = {**self.env, "PATH": str(shim) + os.pathsep + self.env["PATH"]}
        self.config(self.pinned(self.new_sha))
        started = time.monotonic()
        result = self.push("main", env=env)
        took = time.monotonic() - started
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("cannot tell whether the rules are current", result.stderr)
        self.assertGreaterEqual(took, 19)
        self.assertLess(took, 100)

    def reports(self) -> list[str]:
        return _git("for-each-ref", "--format=%(refname)", "refs/tags/gate-report/",
                    cwd=self.remote).split()


if __name__ == "__main__":
    unittest.main()
