#!/usr/bin/env python3
################################################################################
# File: test_select_tests.py
# Path: {PROJECT_ROOT}/tests/test_select_tests.py
# Created by: Ryan Severe
# Created: 2026-10-01
# Last Updated: 2026-11-07
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


if __name__ == "__main__":
    unittest.main()
