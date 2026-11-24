#!/usr/bin/env python3
################################################################################
# File: test_select_tests.py
# Path: {PROJECT_ROOT}/tests/test_select_tests.py
# Created by: Ryan Severe
# Created: 2026-10-01
# Last Updated: 2026-11-24
# Description: Pins how the pre-push test selector decides what a push runs.
#              Unknown change sets and changes to the selection
#              machinery run everything; otherwise a class runs when its own
#              file, a measured dependency or a declared pattern changed, or
#              when the map has never seen it. Also pins the mapping of a child
#              process's temp-copy paths back to repository paths.
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

import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import select_tests  # noqa: E402

NAMES = ["test_sync.Rollout", "test_sync.Render", "test_gates.Tests"]
DEPMAP = {
    "test_sync.Rollout": ["sync.py", "tests/test_sync.py"],
    "test_sync.Render": ["sync.py", "tests/test_sync.py"],
    "test_gates.Tests": ["tests/test_gates.py"],
}
DECLARED = {
    "test_sync.Render": ["rules/**"],
    "test_gates.Tests": ["githooks/gates/tests.sh"],
}


def pick(changed: set[str] | None, names=NAMES, depmap=DEPMAP, declared=DECLARED) -> list[str]:
    return sorted(select_tests.select(names, changed, depmap, declared))


class Select(unittest.TestCase):
    def test_an_unknown_change_set_runs_everything(self):
        self.assertEqual(pick(None), sorted(NAMES))

    def test_a_change_to_the_selection_machinery_runs_everything(self):
        for path in ("tests/select_tests.py", "tests/run_shard.py", ".github/test-roots",
                     "tests/depmap.json"):
            with self.subTest(path=path):
                self.assertEqual(pick({path}), sorted(NAMES))

    def test_a_profile_suite_sees_the_core_s_selector_as_machinery(self):
        """Intent: a profile runs its tests/ with core/tests/select_tests.py, so from the
        profile's root a change to the selector is core/tests/..., and must still run all."""
        profile = select_tests.ROOT.parent / "profile-root"
        with mock.patch.object(select_tests, "ROOT", select_tests.ROOT.parent), \
                mock.patch.object(select_tests, "DEPMAP", profile / "tests" / "depmap.json"):
            machinery = select_tests.always_all()
        name = select_tests.ROOT.name
        self.assertIn(f"{name}/tests/select_tests.py", machinery)
        self.assertIn(f"{name}/tests/run_shard.py", machinery)

    def test_a_changed_test_file_runs_its_own_classes(self):
        self.assertEqual(pick({"tests/test_gates.py"}), ["test_gates.Tests"])

    def test_a_suite_outside_tests_selects_by_its_own_folder(self):
        """Intent: the folder under test is the caller's configuration - a consumer's suite
        in checks/ selects a class on a change to checks/<module>.py, not on tests/."""
        names = ["test_a.Alpha", "test_a.Beta", "test_b.Gamma"]
        depmap = {"test_a.Alpha": ["lib.py"], "test_a.Beta": ["other.py"],
                  "test_b.Gamma": ["lib.py"]}
        with mock.patch.object(select_tests, "TESTS", select_tests.ROOT / "checks"):
            chosen = sorted(select_tests.select(names, {"checks/test_b.py"}, depmap, {}))
            ignored = sorted(select_tests.select(names, {"tests/test_b.py"}, depmap, {}))
        self.assertEqual(chosen, ["test_b.Gamma"])
        self.assertEqual(ignored, [])

    def test_a_measured_dependency_selects_every_class_that_ran_it(self):
        self.assertEqual(pick({"sync.py"}), ["test_sync.Render", "test_sync.Rollout"])

    def test_a_declared_pattern_selects_only_the_class_that_declared_it(self):
        self.assertEqual(pick({"rules/prescriptions.md"}), ["test_sync.Render"])
        self.assertEqual(pick({"githooks/gates/tests.sh"}), ["test_gates.Tests"])

    def test_a_class_the_map_has_never_seen_runs(self):
        names = NAMES + ["test_new.Fresh"]
        self.assertEqual(pick({"README.md"}, names=names), ["test_new.Fresh"])

    def test_a_change_nothing_depends_on_runs_nothing(self):
        self.assertEqual(pick({"README.md"}), [])

    def test_a_deleted_dependency_still_selects(self):
        # A deletion appears in the diff by its old name; the map still holds that name.
        self.assertEqual(pick({"sync.py"}, depmap={**DEPMAP, "test_gates.Tests": ["sync.py"]}),
                         sorted(NAMES))


class RepoRelative(unittest.TestCase):
    ROOT = Path(tempfile.gettempdir()) / "checkout" / "example-profile"
    TRACKED = {"sync.py", "tests/test_sync.py", ".github/scripts/tickets/edit.py", "lib/__init__.py"}

    def rel(self, path: Path) -> str | None:
        return select_tests.repo_relative(str(path), self.ROOT, self.TRACKED)

    def test_a_path_inside_the_checkout_is_made_relative(self):
        self.assertEqual(self.rel(self.ROOT / "tests" / "test_sync.py"), "tests/test_sync.py")

    def test_a_temp_copy_maps_to_the_longest_tracked_suffix(self):
        copy = Path(tempfile.gettempdir()) / "tmp4k4b7qt3" / "source"
        self.assertEqual(self.rel(copy / "sync.py"), "sync.py")
        self.assertEqual(self.rel(copy / ".github" / "scripts" / "tickets" / "edit.py"),
                         ".github/scripts/tickets/edit.py")

    def test_the_standard_library_is_never_a_dependency(self):
        stdlib = Path(sysconfig.get_paths()["stdlib"])
        self.assertIsNone(self.rel(stdlib / "lib" / "__init__.py"))
        self.assertIsNone(self.rel(stdlib / "json" / "__init__.py"))

    def test_installed_packages_are_never_a_dependency(self):
        site = Path(sysconfig.get_paths()["purelib"])
        self.assertIsNone(self.rel(site / "lib" / "__init__.py"))

    def test_a_path_matching_nothing_tracked_is_dropped(self):
        self.assertIsNone(self.rel(Path(tempfile.gettempdir()) / "tmpx" / "scratch.py"))


class Declared(unittest.TestCase):
    def found(self, module_list, **attrs):
        module = types.ModuleType("fake_declared")
        if module_list is not None:
            module.EXERCISES = module_list
        cls = type("Case", (unittest.TestCase,), {"__module__": module.__name__,
                                                   "test_x": lambda self: None, **attrs})
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        return {"fake_declared.Case": [cls("test_x")]}

    def test_a_class_without_its_own_list_takes_the_modules(self):
        self.assertEqual(select_tests.declared(self.found(["rules/**"])),
                         {"fake_declared.Case": ["rules/**"]})

    def test_a_class_list_replaces_the_modules(self):
        """So one slow class in a file of render tests can opt out of rule content."""
        found = self.found(["rules/**"], EXERCISES=["manifest.yaml"])
        self.assertEqual(select_tests.declared(found), {"fake_declared.Case": ["manifest.yaml"]})

    def test_no_list_anywhere_declares_nothing(self):
        self.assertEqual(select_tests.declared(self.found(None)), {"fake_declared.Case": []})


class ChangedFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls._tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        cls.env = env

        def git(*args: str) -> str:
            return subprocess.run(("git", *args), cwd=cls.repo, env=env, check=True,
                                  capture_output=True, text=True, timeout=60).stdout.strip()
        git("init", "--quiet", "-b", "main")
        git("config", "user.name", "t")
        git("config", "user.email", "t@example.invalid")
        git("config", "commit.gpgsign", "false")
        (cls.repo / "a.txt").write_text("a\n", encoding="utf-8")
        (cls.repo / "gone.txt").write_text("g\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "--quiet", "-m", "one")
        cls.first = git("rev-parse", "HEAD")
        (cls.repo / "b.txt").write_text("b\n", encoding="utf-8")
        (cls.repo / "gone.txt").unlink()
        git("add", "-A")
        git("commit", "--quiet", "-m", "two")
        cls.second = git("rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def changed(self, local: str, remote: str) -> set[str] | None:
        return select_tests.changed_files(local, remote, cwd=self.repo, env=self.env)

    def test_a_real_range_lists_added_and_deleted_files(self):
        self.assertEqual(self.changed(self.second, self.first), {"b.txt", "gone.txt"})

    def test_a_new_branch_has_no_range(self):
        self.assertIsNone(self.changed(self.second, "0" * 40))

    def test_a_missing_end_has_no_range(self):
        self.assertIsNone(self.changed(self.second, ""))
        self.assertIsNone(self.changed("", self.first))

    def test_a_remote_commit_this_clone_lacks_has_no_range(self):
        self.assertIsNone(self.changed(self.second, "1" * 40))


SHARD = Path(select_tests.__file__).resolve().parent / "run_shard.py"
CASE = "import unittest\n\n\nclass {name}(unittest.TestCase):\n    def test_it(self):\n        pass\n"


class NestedRoot(unittest.TestCase):
    """A suite two levels below the repository top level: scripts/tests, whose default root
    is scripts/. Synthetic folders throughout; each commit is one scenario's push range."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls._tmp.name)
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        cls.tests = cls.repo / "scripts" / "tests"
        cls.write("scripts/lib.py", "x = 1\n")
        cls.write("scripts/tests/test_a.py", CASE.format(name="Alpha"))
        cls.write("scripts/tests/test_b.py",
                  'EXERCISES = ["stacks/app/exercised.sh"]\n\n' + CASE.format(name="Beta"))
        cls.write("stacks/app/ctl.sh", "echo ctl\n")
        cls.write("stacks/app/two.sh", "echo two\n")
        cls.write("stacks/app/exercised.sh", "echo exercised\n")
        cls.write(".github/test-roots", "scripts/tests\n")
        cls.git("init", "--quiet", "-b", "main")
        cls.git("config", "user.name", "t")
        cls.git("config", "user.email", "t@example.invalid")
        cls.git("config", "commit.gpgsign", "false")
        cls.git("add", "-A")
        cls.git("commit", "--quiet", "-m", "base")
        cls.ranges: dict[str, tuple[str, str]] = {}
        cls.commit("mixed", "stacks/app/ctl.sh", "scripts/tests/test_a.py")
        cls.commit("inside", "scripts/lib.py", "scripts/tests/test_a.py")
        cls.commit("outside", "stacks/app/ctl.sh")
        cls.commit("two_outside", "stacks/app/ctl.sh", "stacks/app/two.sh")
        cls.commit("exercised", "stacks/app/exercised.sh")
        cls.commit("roots", ".github/test-roots")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def git(cls, *args: str) -> str:
        return subprocess.run(("git", *args), cwd=cls.repo, env=cls.env, check=True,
                              capture_output=True, text=True, timeout=60).stdout.strip()

    @classmethod
    def write(cls, rel: str, text: str, append: bool = False) -> None:
        path = cls.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a" if append else "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    @classmethod
    def commit(cls, label: str, *paths: str) -> None:
        before = cls.git("rev-parse", "HEAD")
        for rel in paths:
            cls.write(rel, f"# {label}\n", append=True)
        cls.git("add", "-A")
        cls.git("commit", "--quiet", "-m", label)
        cls.ranges[label] = (before, cls.git("rev-parse", "HEAD"))

    def set_map(self, mapping: dict[str, list[str]]) -> None:
        (self.tests / "depmap.json").write_text(json.dumps(mapping), encoding="utf-8")

    def shard(self, label: str, *args: str) -> subprocess.CompletedProcess[str]:
        remote, local = self.ranges[label]
        env = {**self.env, "PUSH_LOCAL_SHA": local, "PUSH_REMOTE_SHA": remote}
        return subprocess.run((sys.executable, "-B", str(SHARD), "--tests", str(self.tests),
                               *args, "1/1"), cwd=self.repo, env=env, capture_output=True,
                              text=True, timeout=120)

    def changed(self, label: str):
        remote, local = self.ranges[label]
        return select_tests.changed_files(local, remote, cwd=self.repo / "scripts", env=self.env)

    def test_a_change_outside_a_nested_root_is_reported_not_dropped(self):
        """Intent: Done when - "`changed_files` from a nested root reports a change outside it
        instead of dropping it". The return shape is the coder's; the outside path must appear
        in it, and the inside path with it, relative to the root."""
        shown = repr(self.changed("mixed"))
        self.assertIn("stacks/app/ctl.sh", shown)
        self.assertIn("tests/test_a.py", shown)

    def test_a_change_inside_a_nested_root_is_made_relative_to_it(self):
        """Characterisation: passes before the fix. A range wholly inside the root reports
        its paths relative to the root and names nothing outside it."""
        shown = repr(self.changed("inside"))
        self.assertIn("lib.py", shown)
        self.assertNotIn("scripts/lib.py", shown)
        self.assertNotIn("stacks", shown)

    def test_a_change_outside_a_nested_root_runs_every_class(self):
        """Intent: Done when - "A push range touching a file outside a nested root runs every
        class, and the `selected:` line says so"."""
        self.set_map({"test_a.Alpha": ["lib.py"], "test_b.Beta": ["other.py"]})
        done = self.shard("outside")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("selected: 2 of 2 class(es) - 1 change(s) outside scripts, so all",
                      done.stdout)

    def test_every_outside_path_is_counted_once(self):
        """Intent: Edge cases - "several outside paths are counted once each in the
        `selected:` line"."""
        self.set_map({"test_a.Alpha": ["lib.py"], "test_b.Beta": ["other.py"]})
        done = self.shard("two_outside")
        self.assertIn("selected: 2 of 2 class(es) - 2 change(s) outside scripts, so all",
                      done.stdout)

    def test_a_change_only_inside_the_root_still_selects_by_the_map(self):
        """Characterisation: passes before the fix. Boundary values - "a change only inside
        the root selects as now"."""
        self.set_map({"test_a.Alpha": ["lib.py"], "test_b.Beta": ["other.py"]})
        done = self.shard("inside")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("selected: 1 of 2 class(es) - 2 changed file(s)", done.stdout)
        self.assertIn("test_a.Alpha", done.stdout)
        self.assertNotIn("test_b.Beta", done.stdout)

    def test_root_dot_selects_the_class_whose_map_names_an_outside_file(self):
        """Intent: Done when - "With `--root .`, a change to a file outside the tests
        folder's parent selects the class whose map or `EXERCISES` names it" (the map half)."""
        self.set_map({"test_a.Alpha": ["stacks/app/ctl.sh"], "test_b.Beta": ["other.py"]})
        done = self.shard("outside", "--root", ".")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("selected: 1 of 2 class(es)", done.stdout)
        self.assertIn("test_a.Alpha", done.stdout)
        self.assertNotIn("test_b.Beta", done.stdout)

    def test_root_dot_selects_the_class_whose_exercises_names_an_outside_file(self):
        """Intent: Done when - "With `--root .`, a change to a file outside the tests
        folder's parent selects the class whose map or `EXERCISES` names it" (the EXERCISES
        half)."""
        self.set_map({"test_a.Alpha": ["lib.py"], "test_b.Beta": ["other.py"]})
        done = self.shard("exercised", "--root", ".")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("selected: 1 of 2 class(es)", done.stdout)
        self.assertIn("test_b.Beta", done.stdout)
        self.assertNotIn("test_a.Alpha", done.stdout)

    def test_a_change_to_the_test_roots_file_runs_every_class_under_any_root(self):
        """Intent: Done when - "A change to `.github/test-roots` runs every class under any
        root"."""
        self.set_map({"test_a.Alpha": ["lib.py"], "test_b.Beta": ["other.py"]})
        for args in ((), ("--root", ".")):
            with self.subTest(args=args):
                done = self.shard("roots", *args)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertIn("selected: 2 of 2 class(es)", done.stdout)


if __name__ == "__main__":
    unittest.main()
