#!/usr/bin/env python3
################################################################################
# File: test_toolboxctl.py
# Path: {PROJECT_ROOT}/tests/test_toolboxctl.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-15
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
import tarfile
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

    def test_setup_passes_hooks_through(self):
        """Intent: setup --hooks off reaches setup_profile.main untouched,
        after the --profile toolboxctl adds."""
        with mock.patch("setup_profile.main", return_value=0) as delegate:
            code, _, _ = self.run_main("setup", "--hooks", "off")
        self.assertEqual(code, 0)
        delegate.assert_called_once_with(["--profile", str(self.profile), "--hooks", "off"])

    def test_gate_lists_reaches_gate_lists_with_this_profile(self):
        """Intent: gate-lists passes its arguments through to
        gate_lists.main, adding --profile <profile> when none is given."""
        with mock.patch("gate_lists.main", return_value=0) as delegate:
            code, _, _ = self.run_main("gate-lists", "--leak", "l.txt", "--core-names", "c.txt")
        self.assertEqual(code, 0)
        delegate.assert_called_once_with(
            ["--profile", str(self.profile), "--leak", "l.txt", "--core-names", "c.txt"])

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
                                     ("update", "commits core/"),
                                     ("flags", "after a typed yes"), ("setup", "profile.yaml"),
                                     ("gate-lists", "never patterns")):
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
        (self.profile / "profile.yaml").write_text(
            "identity:\n  name: Example Person\n  email: person@example.invalid\ntargets: {}\n",
            encoding="utf-8")
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
                   render_code: int = 0, vendor_report=None) -> tuple[int, str, str]:
        def preview(core: Path, root: Path | None) -> int:
            self.events.append("preview")
            return preview_code

        def render(core: Path) -> int:
            self.events.append("render")
            self.tree_at_render = git(self.profile, "status", "--porcelain", "--", "core")
            return render_code

        def confirm() -> bool:
            self.events.append("confirm")
            return answer

        out, err = io.StringIO(), io.StringIO()
        reporter = vendor_report or self.fake_vendor
        with mock.patch.object(vendor, "vendor_report", side_effect=reporter), \
                mock.patch.object(toolboxctl, "run_preview", side_effect=preview), \
                mock.patch.object(toolboxctl, "run_render", side_effect=render), \
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
        self.assertEqual(self.events[:3], [f"vendor {SOURCE}@v1.4.0", "preview", "confirm"])

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

    def test_a_yes_commits_core_alone_as_the_profile_identity_then_renders(self):
        """Intent: a yes commits core/ as one change, as the profile
        identity, with a message naming the old and new tag, then renders from the
        clean tree. Anything else staged in the profile stays out of the commit."""
        (self.profile / "other.txt").write_text("staged elsewhere\n", encoding="utf-8")
        git(self.profile, "add", "other.txt")
        with self.newer("v1.3.0"):
            code, out, err = self.run_update(answer=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.events[-2:], ["confirm", "render"])
        self.assertEqual(self.tree_at_render, "", "the render ran before core/ was committed")
        self.assertTrue((self.core / "added.py").exists())
        self.assertEqual(git(self.profile, "log", "-1", "--format=%an|%ae|%cn|%ce"),
                         "Example Person|person@example.invalid|Example Person|"
                         "person@example.invalid")
        message = git(self.profile, "log", "-1", "--format=%B")
        self.assertIn("v1.2.3", message)
        self.assertIn("v1.3.0", message)
        files = git(self.profile, "show", "--name-only", "--format=", "HEAD").split()
        self.assertTrue(files and all(f.startswith("core/") for f in files), files)
        self.assertEqual(git(self.profile, "diff", "--cached", "--name-only"), "other.txt")
        self.assertIn("committed", out)
        self.assertIn("rendered", out)

    def test_a_no_commits_and_renders_nothing(self):
        """Intent: anything but a yes restores core/, commits nothing and renders nothing."""
        head = git(self.profile, "rev-parse", "HEAD")
        with self.newer("v1.3.0"):
            self.run_update(answer=False)
        self.assertEqual(git(self.profile, "rev-parse", "HEAD"), head)
        self.assertNotIn("render", self.events)

    def test_a_failed_commit_leaves_core_swapped_and_renders_nothing(self):
        """Intent: a commit that fails (here a refusing pre-commit hook) is an
        error, leaves the swapped core/ in place, renders nothing, and is not [OK]."""
        hook = self.profile / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho refused by hook >&2\nexit 1\n", encoding="utf-8",
                        newline="\n")
        hook.chmod(0o755)
        with self.newer("v1.3.0"):
            code, out, err = self.run_update(answer=True)
        self.assertNotEqual(code, 0)
        self.assertIn("[ERROR]", err)
        self.assertNotIn("render", self.events)
        self.assertTrue((self.core / "added.py").exists())
        self.assertNotIn("[OK]", out)

    def test_a_failed_render_keeps_the_commit_and_names_the_command(self):
        """Intent: a render that fails after the commit keeps the commit, is an
        error naming the command to run by hand, and is not [OK]."""
        head = git(self.profile, "rev-parse", "HEAD")
        with self.newer("v1.3.0"):
            code, out, err = self.run_update(answer=True, render_code=1)
        self.assertNotEqual(code, 0)
        self.assertNotEqual(git(self.profile, "rev-parse", "HEAD"), head, "the commit was lost")
        self.assertIn("[ERROR]", err)
        self.assertIn("--self --write", err)
        self.assertNotIn("[OK]", out)

    def test_an_identity_that_differs_refuses_before_the_swap(self):
        """Intent: the git identity is checked with the other preconditions, so a
        mismatch with profile.yaml refuses before anything changes."""
        git(self.profile, "config", "user.email", "someone@elsewhere.invalid")
        with self.newer("v1.3.0"):
            code, _, err = self.run_update()
        self.assertEqual(code, 1)
        self.assertIn("[ERROR]", err)
        self.assertIn("someone@elsewhere.invalid", err)
        self.assertEqual(self.events, [])

    def test_a_profile_with_no_identity_refuses_before_the_swap(self):
        """Intent: a profile.yaml with no identity: key refuses before the swap."""
        (self.profile / "profile.yaml").write_text("targets: {}\n", encoding="utf-8")
        git(self.profile, "commit", "-q", "-am", "no identity")
        with self.newer("v1.3.0"):
            code, _, err = self.run_update()
        self.assertEqual(code, 1)
        self.assertIn("identity", err)
        self.assertEqual(self.events, [])

    def test_a_failed_swap_asks_nothing(self):
        """Intent: vendor_report refuses without touching core/, so update stops."""
        with self.newer("v1.3.0"):
            code, _, _ = self.run_update(vendor_report=lambda profile, source: 1)
        self.assertEqual(code, 1)
        self.assertEqual(self.events, [])


class RunRender(Fixture):
    """The profile's own render, run from the new core in a child process."""

    def run_render(self, **kwargs) -> tuple[int, str, mock.Mock]:
        err = io.StringIO()
        with mock.patch.object(subprocess, "run", **kwargs) as run, \
                contextlib.redirect_stderr(err):
            code = toolboxctl.run_render(self.core)
        return code, err.getvalue(), run

    def test_it_runs_the_new_cores_profile_self_render(self):
        """Intent: the render is the new core's sync.py on disk, as
        --profile <profile> --self --write, from the profile, with an explicit timeout."""
        code, _, run = self.run_render(return_value=subprocess.CompletedProcess([], 0))
        self.assertEqual(code, 0)
        command = run.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], str(self.core / "sync.py"))
        self.assertEqual(command[2:], ["--profile", str(self.profile), "--self", "--write"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.profile)
        self.assertEqual(run.call_args.kwargs["timeout"], toolboxctl.RENDER_TIMEOUT)

    def test_a_failed_timed_out_or_unstartable_render_is_a_failure(self):
        """Intent: a render that exits non-zero, times out or cannot start is an
        [ERROR] and returns 1, never a pass; a render at exactly the timeout is one."""
        cases = (("exit", {"return_value": subprocess.CompletedProcess([], 2)}),
                 ("timeout", {"side_effect": subprocess.TimeoutExpired("sync", 1)}),
                 ("start", {"side_effect": OSError("no interpreter")}))
        for name, kwargs in cases:
            with self.subTest(case=name):
                code, err, _ = self.run_render(**kwargs)
                self.assertEqual(code, 1)
                self.assertIn("[ERROR]", err)


def shutil_rmtree_git(profile: Path) -> None:
    """Make the fixture profile an ordinary folder by removing its repository."""
    def writable(func, path, _):
        os.chmod(path, 0o700)
        func(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(profile / ".git", onexc=writable)
    else:
        shutil.rmtree(profile / ".git", onerror=writable)


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


class InitFixture(unittest.TestCase):
    """A release archive's folder (a VERSION, no VENDORED), an empty git repository to
    bootstrap, and a fetch that stands in for GitHub."""

    SOURCE = "example-owner/example-core"
    CORE_URL = "https://github.com/example-owner/example-core.git"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(sync.set_stamp_source, MANIFEST)
        self.archive = Path(tmp.name) / "archive"
        self.archive.mkdir()
        (self.archive / "VERSION").write_text("0.9.9\n", encoding="utf-8")
        self.profile = Path(tmp.name) / "profile"
        self.profile.mkdir()
        git(self.profile, "init", "-q")
        self.answers = Path(tmp.name) / "answers.yaml"
        self.answers.write_text(
            "identity:\n  name: Example Person\n  email: person@example.invalid\n"
            "answers:\n  tracker.system: ExampleTracker, a hosted tracker.\n", encoding="utf-8")
        self.urls: list[str] = []

    def fetch(self, url: str, accept: str) -> bytes:
        self.urls.append(url)
        if "/commits/" in url:
            return SHA.encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for name, text in (("VERSION", "0.9.9\n"), ("sync.py", "print('core')\n")):
                data = text.encode()
                member = tarfile.TarInfo(f"example-core-{SHA}/{name}")
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        return buffer.getvalue()

    def run_init(self, *extra: str, profile: Path | None = None,
                 answers: bool = True) -> tuple[int, str, str]:
        argv = ["init", "--profile", str(profile or self.profile), "--source", self.SOURCE]
        if answers:
            argv += ["--answers", str(self.answers)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = toolboxctl.main([*argv, *extra], core=self.archive, fetch=self.fetch)
        return code, out.getvalue(), err.getvalue()

    def listing(self, folder: Path) -> list[tuple[str, bytes | None]]:
        return sorted((str(p.relative_to(folder)), p.read_bytes() if p.is_file() else None)
                      for p in folder.rglob("*") if ".git" not in p.relative_to(folder).parts)


class Init(InitFixture):
    def test_it_vendors_the_archives_version_and_sets_up_a_profile(self):
        """Intent: init in an empty repository writes core/ and a VENDORED recording the
        archive's own VERSION as a tag and the SHA it resolved to, then renders a profile."""
        code, out, err = self.run_init()
        self.assertEqual(code, 0, out + err)
        record = vendor.read_record(self.profile / "core")
        self.assertEqual((record.source, record.tag, record.sha),
                         (self.SOURCE, "v0.9.9", SHA))
        self.assertTrue((self.profile / "core" / "sync.py").is_file())
        self.assertTrue((self.profile / "profile.yaml").is_file())
        self.assertIn("[OK] render:", out)
        self.assertTrue(any(url.endswith("/commits/v0.9.9") for url in self.urls))

    def test_the_repository_it_made_has_no_remote(self):
        """Intent: nothing init does leaves a remote that names the core."""
        self.run_init()
        self.assertEqual(git(self.profile, "remote", "-v"), "")

    def test_it_refuses_a_profile_that_is_already_there_and_changes_nothing(self):
        """Intent: an existing core/ or profile.yaml is refused, naming it, with no file
        touched."""
        for name, make in (("core", lambda p: (p / "core").mkdir()),
                           ("profile.yaml",
                            lambda p: (p / "profile.yaml").write_text("x: 1\n", encoding="utf-8"))):
            with self.subTest(existing=name):
                self.setUp()
                make(self.profile)
                before = self.listing(self.profile)
                code, out, err = self.run_init()
                self.assertNotEqual(code, 0)
                self.assertIn(name, err)
                self.assertEqual(self.listing(self.profile), before)
                self.assertEqual(self.urls, [])

    def test_a_setup_that_raises_leaves_no_core_and_no_profile(self):
        """Intent: a setup step that fails after vendoring removes the core/ this run
        wrote, so the folder is as init found it."""
        before = self.listing(self.profile)
        with mock.patch("setup_profile.main", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_init()
        self.assertFalse((self.profile / "core").exists())
        self.assertFalse((self.profile / "profile.yaml").exists())
        self.assertEqual(self.listing(self.profile), before)

    def test_a_setup_that_returns_non_zero_leaves_no_core_and_no_profile(self):
        """Intent: a non-zero setup exit removes the core/ this run wrote."""
        with mock.patch("setup_profile.main", return_value=2):
            code, _, _ = self.run_init()
        self.assertEqual(code, 2)
        self.assertFalse((self.profile / "core").exists())
        self.assertFalse((self.profile / "profile.yaml").exists())

    def test_an_interrupted_setup_leaves_no_core_and_no_profile(self):
        """Intent: Ctrl+C at a prompt removes the core/ this run wrote."""
        with mock.patch("setup_profile.main", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_init()
        self.assertFalse((self.profile / "core").exists())
        self.assertFalse((self.profile / "profile.yaml").exists())

    def test_a_folder_with_core_and_no_profile_names_the_unfinished_init(self):
        """Intent: core/ without profile.yaml is an unfinished init: the message says so,
        says to delete core/ and run init again, and does not send the operator to update."""
        (self.profile / "core").mkdir()
        before = self.listing(self.profile)
        code, _, err = self.run_init()
        self.assertNotEqual(code, 0)
        self.assertIn("unfinished init", err)
        self.assertIn("Delete", err)
        self.assertIn("run init again", err)
        self.assertNotIn("toolboxctl update", err)
        self.assertEqual(self.listing(self.profile), before)
        self.assertEqual(self.urls, [])

    def test_it_refuses_a_folder_that_is_not_a_git_work_tree(self):
        """Intent: no repository, no bootstrap, and nothing written."""
        plain = self.profile.parent / "plain"
        plain.mkdir()
        code, _, err = self.run_init(profile=plain)
        self.assertNotEqual(code, 0)
        self.assertIn("git", err)
        self.assertEqual(list(plain.iterdir()), [])

    def test_every_other_subcommand_still_refuses_without_vendored(self):
        """Intent: only init runs from outside a vendored core."""
        for command in ("version", "check", "update"):
            with self.subTest(command=command):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    code = toolboxctl.main([command], core=self.archive)
                self.assertEqual(code, 1)
                self.assertIn("vendored core", err.getvalue())


class InitGate2(InitFixture):
    def test_a_hand_added_core_remote_is_refused_by_gate_2(self):
        """Intent: in the repository init made, the one-way gate refuses a push to a remote
        that names the core."""
        sh = shutil.which("sh") or next(
            (p for p in (r"C:\Program Files\Git\usr\bin\sh.exe", "/bin/sh") if Path(p).exists()),
            None)
        if sh is None:
            self.skipTest("no POSIX shell available; not reporting a pass")
        code, out, err = self.run_init()
        self.assertEqual(code, 0, out + err)
        git(self.profile, "remote", "add", "origin", self.CORE_URL)
        push_url = git(self.profile, "remote", "get-url", "--push", "origin")
        script = (Path(toolboxctl.__file__).resolve().parent / "githooks" / "one-way"
                  / "no-core-remote.sh").as_posix()
        env = {**os.environ, "LC_ALL": "C",
               "PATH": str(Path(sh).parent) + os.pathsep + os.environ.get("PATH", "")}
        result = subprocess.run([sh, script, self.CORE_URL, push_url], cwd=self.profile,
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
