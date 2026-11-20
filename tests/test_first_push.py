#!/usr/bin/env python3
################################################################################
# File: test_first_push.py
# Path: {PROJECT_ROOT}/tests/test_first_push.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: A profile made by toolboxctl init from a fixture core, with its gates
#              locked and rendered into itself, makes its first push with every
#              gate passing: the vendored core's tests and lint findings are not the
#              profile's. Skips where ruff, shellcheck or a POSIX shell is missing.
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
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import consent  # noqa: E402
import sync  # noqa: E402
import toolboxctl  # noqa: E402

# The whole hook runs here, so test selection is told what it exercises.
EXERCISES = ["githooks/**", "toolboxctl.py", "consent.py", "setup_profile.py", "sync.py"]

SHA = "0123456789abcdef0123456789abcdef01234567"
SOURCE = "acme-owner/acme-core"
SH = shutil.which("sh") or next(
    (p for p in (r"C:\Program Files\Git\usr\bin\sh.exe", "/bin/sh") if Path(p).exists()), None)
ANSWERS = (
    "identity:\n  name: Example Person\n  email: person@acme.example\n"
    "source:\n  repo: acme-profile\n  key: acm\n  owner: acme-owner\n"
    "personal: [acme-private]\nprofile_name: acme-profile-name\n"
    "leak_extra: [internal.acme.example]\n"
    "not_onboarded: {acme-archived: Retired project}\n"
    "targets: [acme-app]\n"
    "answers:\n  tracker.system: ExampleTracker, a hosted tracker.\n")


def environment() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
    return env


def run(cwd: Path, *args: str, stdin: str | None = None):
    return subprocess.run(args, cwd=cwd, env=environment(), capture_output=True, text=True,
                          timeout=900, input=stdin)


@unittest.skipIf(SH is None, "no POSIX shell available; not reporting a pass")
@unittest.skipUnless(shutil.which("ruff") and shutil.which("shellcheck")
                     and shutil.which("git") and shutil.which("node"),
                     "ruff, shellcheck, git and node are needed; not reporting a pass")
class FirstPush(unittest.TestCase):
    def test_a_new_profile_pushes_with_every_gate_passing(self):
        """Intent: a profile made by init, locked and rendered into itself, owns none of the
        vendored core's tests or lint findings, so its first push to main is not refused."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.addCleanup(sync.set_stamp_source, sync.load_profile(ROOT / "examples" / "profile"))
        profile = tmp / "profile"
        profile.mkdir()
        run(profile, "git", "init", "-q", "-b", "main")
        run(profile, "git", "config", "user.email", "person@acme.example")
        run(profile, "git", "config", "user.name", "Example Person")
        answers = tmp / "answers.yaml"
        answers.write_text(ANSWERS, encoding="utf-8")

        # The fixture core is this checkout, so the vendored tests and scripts are real ones.
        listed = run(ROOT, "git", "ls-files", "-co", "--exclude-standard").stdout.split("\n")
        files = [name for name in listed if name and (ROOT / name).is_file()]

        def fetch(url: str, accept: str) -> bytes:
            if "/commits/" in url:
                return SHA.encode()
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                for name in files:
                    data = (ROOT / name).read_bytes()
                    member = tarfile.TarInfo(f"acme-core-{SHA}/{name}")
                    member.size = len(data)
                    tar.addfile(member, io.BytesIO(data))
            return buffer.getvalue()

        out, err = io.StringIO(), io.StringIO()
        # No console: targets come from the answers file, and the lock is answered through
        # the mocked console. init then commits the profile, renders it and commits the render.
        with mock.patch.object(consent, "open_console", return_value=io.StringIO("yes\n")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = toolboxctl.main(["init", "--profile", str(profile), "--source", SOURCE,
                                    "--answers", str(answers)], core=ROOT, fetch=fetch)
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        self.assertIn("-> targets goes to profile.yaml", out.getvalue())
        self.assertIn("[OK] committed: Render the profile", out.getvalue())
        self.assertTrue((profile / "core" / "tests").is_dir(), "the core's tests are vendored")
        self.assertEqual(run(profile, "git", "log", "--format=%s").stdout.splitlines(),
                         ["Render the profile", "Create the profile"])
        remote = tmp / "remote.git"
        run(tmp, "git", "init", "-q", "--bare", str(remote))
        run(profile, "git", "remote", "add", "origin", str(remote))

        sha = run(profile, "git", "rev-parse", "HEAD").stdout.strip()
        hook = profile / ".githooks" / "pre-push"
        pushed = run(profile, SH, hook.as_posix(), "origin",
                     stdin=f"refs/heads/main {sha} refs/heads/main {'0' * 40}\n")
        self.assertEqual(pushed.returncode, 0, pushed.stdout + pushed.stderr)
        enabled = [line.strip() for line in
                   (profile / ".githooks" / "gates" / "enabled").read_text(
                       encoding="utf-8").splitlines()
                   if line.strip() and not line.startswith("#")]
        self.assertGreaterEqual(len(enabled), 14, enabled)
        for gate in enabled:
            self.assertIn(f"pre-push: {gate} passed", pushed.stderr)


if __name__ == "__main__":
    unittest.main()
