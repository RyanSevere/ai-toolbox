#!/usr/bin/env python3
################################################################################
# File: test_toolboxctl.py
# Path: {PROJECT_ROOT}/tests/test_toolboxctl.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-09
# Description: Tests for toolboxctl.py - the one entry point a
#              profile's owner runs against its vendored core. Covers the
#              refusal outside a vendored core, version, check's ordering, the
#              flags and setup pass-through, argument errors, and update: its
#              preconditions, preview-then-ask order, and restore on a no.
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
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402
import toolboxctl  # noqa: E402
import vendor  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
SOURCE = "example-owner/ai-toolbox"
MANIFEST = sync.load_profile(sync.ROOT / "examples" / "profile")


def git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(("git", *args), cwd=cwd, env=env, capture_output=True, text=True,
                            timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"fixture: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


class Fixture(unittest.TestCase):
    """A profile folder holding a core/ with a VENDORED record, and a runner for main."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name) / "profile"
        self.core = self.profile / vendor.CORE_DIR
        self.core.mkdir(parents=True)
        record = vendor.Record(SOURCE, "v1.2.3", SHA, "sha256:" + "0" * 64)
        self.write_record(vendor.format_record(record))

    def write_record(self, text: str) -> None:
        (self.core / vendor.VENDORED).write_text(text, encoding="utf-8")

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = toolboxctl.main(list(argv), core=self.core)
        return code, out.getvalue(), err.getvalue()


class Refusal(Fixture):
    def test_it_refuses_where_there_is_no_vendored_core(self):
        """Intent: run from the source repo, where there
        is no core/VENDORED, it refuses and says it is meant for a profile's vendored core."""
        (self.core / vendor.VENDORED).unlink()
        with mock.patch.object(vendor, "check_report") as check_report:
            code, out, err = self.run_main("check")
        self.assertEqual(code, 1)
        self.assertIn("vendored core", err)
        self.assertEqual(out, "")
        check_report.assert_not_called()


class Version(Fixture):
    def test_it_prints_the_recorded_source_tag_and_sha(self):
        """Intent: version prints the tag and SHA in core/VENDORED."""
        code, out, err = self.run_main("version")
        self.assertEqual(code, 0, err)
        self.assertIn(SOURCE, out)
        self.assertIn("v1.2.3", out)
        self.assertIn(SHA, out)

    def test_it_fails_rather_than_printing_a_blank_on_a_malformed_record(self):
        """Intent: version fails rather than printing a blank when the
        file is unparseable."""
        self.write_record("source=example-owner/ai-toolbox\n")
        code, out, err = self.run_main("version")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("[ERROR]", err)


class Check(Fixture):
    def test_it_stops_when_the_core_does_not_match_its_record(self):
        """Intent: check runs check-core first and stops
        if it fails; an update report on a core that does not match its record misleads."""
        with mock.patch.object(vendor, "check_report", return_value=1), \
                mock.patch.object(vendor, "updates_report") as updates_report:
            code, _, _ = self.run_main("check")
        self.assertEqual(code, 1)
        updates_report.assert_not_called()

    def test_it_returns_the_update_checks_own_exit_code(self):
        """Intent: check is --check-core then --check-updates, and
        every subcommand reports failure as failure, so "could not check" stays exit 3."""
        for result in (0, 2, 3):
            with self.subTest(updates_report=result), \
                    mock.patch.object(vendor, "check_report", return_value=0), \
                    mock.patch.object(vendor, "updates_report", return_value=result) as report:
                code, _, _ = self.run_main("check")
            self.assertEqual(code, result)
            report.assert_called_once_with(self.core)


class PassThrough(Fixture):
    def test_flags_reaches_consent_with_this_profile(self):
        """Intent: flags passes its arguments through to
        consent.main, adding --profile <profile> when none is given."""
        with mock.patch("consent.main", return_value=0) as delegate:
            code, _, _ = self.run_main("flags", "--set", "tests=off")
        self.assertEqual(code, 0)
        delegate.assert_called_once_with(["--profile", str(self.profile), "--set", "tests=off"])

    def test_setup_reaches_setup_profile_with_this_profile(self):
        """Intent: setup passes its arguments through to
        setup_profile.main, adding --profile when none is given."""
        with mock.patch("setup_profile.main", return_value=3) as delegate:
            code, _, _ = self.run_main("setup", "--answers", "a.yaml")
        self.assertEqual(code, 3)
        delegate.assert_called_once_with(["--profile", str(self.profile), "--answers", "a.yaml"])

    def test_a_profile_given_by_the_caller_is_left_alone(self):
        """Intent: --profile is added only when the arguments do not
        already carry one."""
        for given in (["--profile", "elsewhere"], ["--profile=elsewhere"]):
            with self.subTest(given=given), \
                    mock.patch("consent.main", return_value=0) as delegate:
                self.run_main("flags", *given, "--check")
            delegate.assert_called_once_with([*given, "--check"])


class Arguments(Fixture):
    def test_an_unknown_subcommand_fails(self):
        """Intent: tests: an unknown subcommand fails."""
        with self.assertRaises(SystemExit) as raised, \
                contextlib.redirect_stderr(io.StringIO()):
            toolboxctl.main(["frobnicate"], core=self.core)
        self.assertEqual(raised.exception.code, 2)

    def test_an_argument_a_subcommand_does_not_take_fails(self):
        """Intent: only flags and setup pass arguments on, so a stray one
        anywhere else is an error rather than silently dropped."""
        with self.assertRaises(SystemExit) as raised, \
                contextlib.redirect_stderr(io.StringIO()):
            toolboxctl.main(["version", "--bogus"], core=self.core)
        self.assertEqual(raised.exception.code, 2)

    def test_help_names_each_subcommand_and_its_consequence(self):
        """Intent: --help text that names each subcommand's consequence."""
        out = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(out):
            toolboxctl.main(["--help"], core=self.core)
        text = " ".join(out.getvalue().split())
        for command, consequence in (("version", "reads only"), ("check", "changes nothing"),
                                     ("flags", "after a typed yes"), ("setup", "profile.yaml")):
            with self.subTest(command=command):
                self.assertIn(command, text)
                self.assertIn(consequence, text)


class UpdateFixture(unittest.TestCase):
    """A profile that is a git repository with a real, committed, matching core/."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name) / "profile"
        self.core = self.profile / vendor.CORE_DIR
        self.core.mkdir(parents=True)
        (self.profile / "profile.yaml").write_text("targets: {}\n", encoding="utf-8")
        (self.core / "sync.py").write_text("print('v1.2.3')\n", encoding="utf-8")
        (self.core / vendor.GITATTRIBUTES).write_bytes(vendor.GITATTRIBUTES_TEXT.encode())
        self.record = vendor.Record(SOURCE, "v1.2.3", SHA, vendor.content_hash(self.core))
        (self.core / vendor.VENDORED).write_text(vendor.format_record(self.record),
                                                encoding="utf-8")
        git(self.profile, "init", "-q")
        git(self.profile, "config", "user.name", "Example Person")
        git(self.profile, "config", "user.email", "person@example.invalid")
        git(self.profile, "add", "-A")
        git(self.profile, "commit", "-q", "-m", "profile")
        self.events: list[str] = []

    def newer(self, *tags: str, warnings: list[str] | None = None):
        updates = vendor.Updates(self.record, list(tags), tags[0] if tags else "v1.2.3",
                                 warnings or [])
        return mock.patch.object(vendor, "check_updates", return_value=updates)

    def fake_vendor(self, profile: Path, source: str) -> int:
        """Stands in for vendor_report: replaces a file and adds one, as a real swap would."""
        self.events.append(f"vendor {source}")
        (self.core / "sync.py").write_text("print('new')\n", encoding="utf-8")
        (self.core / "added.py").write_text("print('added')\n", encoding="utf-8")
        return 0

    def run_update(self, *argv: str, answer: bool = True, preview_code: int = 0,
                   vendor_report=None) -> tuple[int, str, str]:
        def preview(core: Path, root: Path | None) -> int:
            self.events.append("preview")
            return preview_code

        def confirm() -> bool:
            self.events.append("confirm")
            return answer

        out, err = io.StringIO(), io.StringIO()
        reporter = vendor_report or self.fake_vendor
        with mock.patch.object(vendor, "vendor_report", side_effect=reporter), \
                mock.patch.object(toolboxctl, "run_preview", side_effect=preview), \
                mock.patch.object(toolboxctl, "console_confirm", side_effect=confirm), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = toolboxctl.main(["update", *argv], core=self.core)
        return code, out.getvalue(), err.getvalue()

    def assert_core_is_committed_one(self):
        self.assertEqual(git(self.profile, "status", "--porcelain", "--", "core"), "")
        self.assertFalse((self.core / "added.py").exists())
        self.assertEqual((self.core / "sync.py").read_text(encoding="utf-8"), "print('v1.2.3')\n")


class UpdatePreconditions(UpdateFixture):
    def test_it_refuses_a_profile_that_is_not_a_git_repository(self):
        """Intent: update checks the profile is
        a git repository with core/ committed, because a no is undone from git."""
        shutil_rmtree_git(self.profile)
        with self.newer("v1.3.0"):
            code, _, err = self.run_update()
        self.assertEqual(code, 1)
        self.assertIn("git", err)
        self.assertEqual(self.events, [])

    def test_it_refuses_a_core_with_uncommitted_changes(self):
        """Intent: core/ must be committed and clean, or a
        restore from git would discard work nobody committed."""
        (self.core / "notes.txt").write_text("mine\n", encoding="utf-8")
        with self.newer("v1.3.0"):
            code, _, err = self.run_update()
        self.assertEqual(code, 1)
        self.assertIn("uncommitted", err)
        self.assertEqual(self.events, [])

    def test_nothing_newer_says_so_and_changes_nothing(self):
        """Intent: with nothing newer than the vendored tag it says
        so and changes nothing."""
        with self.newer():
            code, out, _ = self.run_update()
        self.assertEqual(code, 0)
        self.assertIn("nothing changed", out)
        self.assertEqual(self.events, [])

    def test_an_update_check_that_could_not_run_is_unknown(self):
        """Intent: every subcommand reports failure as failure: an update check
        that could not reach the network says so, never "up to date"."""
        with mock.patch.object(vendor, "check_updates",
                               side_effect=vendor.LookupFailed("network down")):
            code, _, err = self.run_update()
        self.assertEqual(code, 3)
        self.assertIn("[UNKNOWN]", err)
        self.assertEqual(self.events, [])

    def test_a_tag_that_is_not_a_release_tag_is_refused(self):
        """Intent: releases are vX.Y.Z tags; anything else reaches no URL."""
        code, _, err = self.run_update("latest")
        self.assertEqual(code, 1)
        self.assertIn("vX.Y.Z", err)
        self.assertEqual(self.events, [])


class UpdateFlow(UpdateFixture):
    def test_the_preview_is_shown_before_anything_is_asked(self):
        """Intent: toolboxctl update shows the render difference before
        anything is committed: it shows the difference, then asks."""
        with self.newer("v1.4.0", "v1.3.0"):
            self.run_update()
        self.assertEqual(self.events, [f"vendor {SOURCE}@v1.4.0", "preview", "confirm"])

    def test_a_named_tag_is_vendored_without_an_update_lookup(self):
        """Intent: update [tag]: --vendor-core at the newest or a named tag."""
        with mock.patch.object(vendor, "check_updates") as lookup:
            self.run_update("v1.4.0")
        lookup.assert_not_called()
        self.assertEqual(self.events[0], f"vendor {SOURCE}@v1.4.0")

    def test_a_no_restores_the_committed_core(self):
        """Intent: on anything but yes, the old core/ is
        restored from git."""
        with self.newer("v1.3.0"):
            code, out, _ = self.run_update(answer=False)
        self.assertEqual(code, 1)
        self.assert_core_is_committed_one()
        self.assertIn("restored", out)

    def test_a_failed_preview_restores_without_asking(self):
        """Intent: nothing is kept that was not previewed."""
        with self.newer("v1.3.0"):
            code, _, _ = self.run_update(preview_code=1)
        self.assertEqual(code, 1)
        self.assertNotIn("confirm", self.events)
        self.assert_core_is_committed_one()

    def test_a_yes_keeps_the_new_core_uncommitted(self):
        """Intent: a yes keeps the new core
        and says it is not yet committed or rendered."""
        with self.newer("v1.3.0"):
            code, out, _ = self.run_update(answer=True)
        self.assertEqual(code, 0)
        self.assertTrue((self.core / "added.py").exists())
        self.assertIn("not yet committed", out)

    def test_a_failed_swap_asks_nothing(self):
        """Intent: vendor_report refuses without touching core/, so update stops."""
        with self.newer("v1.3.0"):
            code, _, _ = self.run_update(vendor_report=lambda profile, source: 1)
        self.assertEqual(code, 1)
        self.assertEqual(self.events, [])


def shutil_rmtree_git(profile: Path) -> None:
    """Make the fixture profile an ordinary folder by removing its repository."""
    def writable(func, path, _):
        os.chmod(path, 0o700)
        func(path)
    shutil.rmtree(profile / ".git", onexc=writable)


class Preview(unittest.TestCase):
    """The new core's own preview: each target's render against its files, stamps excluded."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(sync.set_stamp_source, MANIFEST)
        self.profile = Path(tmp.name) / "profile"
        self.core = self.profile / vendor.CORE_DIR
        self.core.mkdir(parents=True)
        self.target = Path(tmp.name) / "app"
        self.target.mkdir()
        self.manifest = {"targets": {"app": {}, "gone": {"skip": True}}, "defaults": {}}

    def run_preview(self, plan: dict[str, str], root: Path | None = None,
                    manifest: dict | None = None) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(sync, "load_profile", return_value=manifest or self.manifest), \
                mock.patch.object(sync, "build_plan", return_value=plan), \
                contextlib.redirect_stdout(out):
            code = toolboxctl.preview(self.core, root)
        return code, out.getvalue()

    def test_a_stamp_only_difference_is_not_a_change(self):
        """Intent: the preview is each target's render difference;
        a stamp differs on every render, so counting it would show every file as changed."""
        (self.target / "AGENTS.md").write_text(
            "<!-- generated from example-profile@1111111 -->\nbody\n", encoding="utf-8")
        code, out = self.run_preview({"AGENTS.md": "<!-- generated from example-profile@0000000 -->\nbody\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("app: 0 file(s) would change", out)

    def test_a_stamp_with_and_without_a_sha_is_not_a_change(self):
        """Intent: a self-rendered file carries no SHA, a target's still does, and
        the preview must treat either as a stamp so neither shows as a difference."""
        (self.target / "AGENTS.md").write_text(
            "<!-- generated from example-profile - edit the source, not this file -->\nbody\n",
            encoding="utf-8")
        code, out = self.run_preview({
            "AGENTS.md": "<!-- generated from example-profile@0000000 - edit the source, "
                         "not this file -->\nbody\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("app: 0 file(s) would change", out)

    def test_a_real_difference_is_shown(self):
        """Intent: update shows the render difference."""
        (self.target / "AGENTS.md").write_text("old rule\n", encoding="utf-8")
        code, out = self.run_preview({"AGENTS.md": "new rule\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("app: 1 file(s) would change", out)
        self.assertIn("+new rule", out)
        self.assertIn("-old rule", out)

    def test_a_missing_target_is_reported_not_previewed(self):
        """Intent: a target whose repository is missing is reported
        as not previewed, never omitted."""
        self.target.rmdir()
        code, out = self.run_preview({"AGENTS.md": "x\n"})
        self.assertEqual(code, 3)
        self.assertIn("[UNKNOWN] app: not previewed", out)
        self.assertNotIn("gone", out)

    def test_targets_are_looked_for_beside_the_profile_unless_a_root_is_given(self):
        """Intent: preview defaults to the profile's parent folder,
        and --root overrides it."""
        code, _ = self.run_preview({"AGENTS.md": "x\n"})
        self.assertEqual(code, 0)
        elsewhere = self.profile.parent / "elsewhere"
        elsewhere.mkdir()
        code, out = self.run_preview({"AGENTS.md": "x\n"}, root=elsewhere)
        self.assertEqual(code, 3)
        self.assertIn(str(elsewhere / "app"), out)


if __name__ == "__main__":
    unittest.main()
