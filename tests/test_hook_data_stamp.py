#!/usr/bin/env python3
################################################################################
# File: test_hook_data_stamp.py
# Path: {PROJECT_ROOT}/tests/test_hook_data_stamp.py
# Created by: Ryan Severe
# Created: 2026-11-23
# Last Updated: 2026-11-23
# Description: A hook's rendered data file carries the generated-from stamp
#              within the first 40 lines, so a change set made only of
#              rendered files is judged rendered-only and skips the tests gate.
#              Pins the title-prefix hook's prefixes.yaml.
################################################################################
#              given to the test-writer role.
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


from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "githooks" / "lib"))

import rendered_only  # noqa: E402
import sync  # noqa: E402
from locked_example import locked_example  # noqa: E402

SHA = "abc1234"
EXAMPLE = locked_example()
MANIFEST = sync.load_profile(EXAMPLE)
DEFAULTS = MANIFEST.get("defaults") or {}
DEFAULT_FILE = ROOT / "hooks" / "title-prefix" / "prefixes.yaml"
SUFFIX = "title-prefix/prefixes.yaml"
OWN = [{"prefix": "blocked", "rule": "ask"},
       {"label": "waiting <x>", "pattern": "waiting .+", "rule": "no-ask"}]


def plan(**extra) -> sync.Plan:
    manifest = {**MANIFEST, **extra}
    return sync.build_plan("t", {"estate": True, "hooks": True}, DEFAULTS, SHA, manifest,
                           profile_dir=EXAMPLE)


def rendered(built: sync.Plan) -> dict[str, str]:
    """Every hook root's copy of prefixes.yaml in the plan."""
    found = {k: v for k, v in built.items() if k.endswith(SUFFIX)}
    assert found, "the plan renders no prefixes.yaml at all"
    return found


class StampedDataFile(unittest.TestCase):
    """The rendered prefixes.yaml is stamped where the gate reads."""

    def assert_stamped(self, built: sync.Plan) -> None:
        for where, text in rendered(built).items():
            head = "\n".join(text.split("\n")[:rendered_only.STAMP_LINES]).encode("utf-8")
            self.assertRegex(head, rendered_only.STAMP, f"{where} has no stamp in its first 40 lines")

    def test_the_default_file_is_stamped_in_every_hook_root(self):
        """Intent: ticket 181 Done when - the core's default prefixes.yaml renders with the
        generated-from stamp inside the first 40 lines, in every hook root."""
        self.assert_stamped(plan())

    def test_a_profile_override_is_stamped_too(self):
        """Characterisation: the override path already writes its own stamp, so this passes
        before ticket 181's change; it pins that the factored stamping keeps it so."""
        built = plan(title_prefixes=OWN)
        self.assert_stamped(built)
        for text in rendered(built).values():
            self.assertEqual(yaml.safe_load(text)["prefixes"], OWN)

    def test_the_stamp_is_a_comment_so_the_data_is_unchanged(self):
        """Intent: ticket 181 Done when - the stamped file loads with yaml.safe_load to
        the same data as its unstamped source."""
        want = yaml.safe_load(DEFAULT_FILE.read_text(encoding="utf-8"))
        self.assertIsNotNone(want)
        for where, text in rendered(plan()).items():
            self.assertEqual(yaml.safe_load(text), want, where)


class RenderedOnlyVerdict(unittest.TestCase):
    """A change set of nothing but stamped rendered files is rendered-only."""

    def git(self, *args: str) -> str:
        return subprocess.run(("git",) + args, cwd=self.repo, capture_output=True, text=True,
                              check=True).stdout.strip()

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        (self.repo / "README.md").write_text("plain\n", encoding="utf-8", newline="\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")

    def verdict(self) -> int:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "render")
        local = self.git("rev-parse", "HEAD")
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        return rendered_only.main([local, self.base])

    def test_a_render_that_changes_prefixes_yaml_skips_the_tests_gate(self):
        """Intent: ticket 181 Done when - with every file stamped, prefixes.yaml included,
        the verdict is 0 (rendered-only), so the tests gate is skipped."""
        for where, text in plan().items():
            if where.startswith(".claude/hooks/title-prefix/"):
                path = self.repo / where
                path.parent.mkdir(parents=True, exist_ok=True)
                # Python files are stamped by the render already; only the data file is in doubt.
                path.write_text(text, encoding="utf-8", newline="\n")
        self.assertTrue((self.repo / ".claude/hooks/title-prefix/prefixes.yaml").exists())
        self.assertEqual(self.verdict(), 0)


if __name__ == "__main__":
    unittest.main()
