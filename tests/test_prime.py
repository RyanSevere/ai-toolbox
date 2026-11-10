#!/usr/bin/env python3
################################################################################
# File: test_prime.py
# Path: {PROJECT_ROOT}/tests/test_prime.py
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-08
# Description: Tests for prime.py against a throwaway git repository: status
#              lines parsed, excluded root documents, nested AGENTS.md headings
#              with fenced code and ignored directories skipped, run targets
#              limited by depth, and one bad repository path failing alone
#              without losing the next repository's output.
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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prime  # noqa: E402

FILES = {
    ".gitignore": "node_modules/\nscratch/\n",
    "README.md": "**Status:** should never be reported\n",
    "ROADMAP.md": "# Roadmap\n",
    "docs/PLAN.md": "# Plan\n\n**status:** **In progress.** Phase 2 next.\n",
    "docs/NOTES.md": "no status here\n",
    "AGENTS.md": "# Root is generated and skipped\n",
    "stacks/AGENTS.md": "# Working in stacks/\n\n## Ports\n\n```sh\n# not a heading\n```\n\n### Deploy by hand\n",
    "package.json": '{"scripts": {"dev": "x", "test": "y"}}',
    "app/package.json": '{"scripts": {"build": "z"}}',
    "a/b/c/package.json": '{"scripts": {"too": "deep"}}',
    "requirements.txt": "",
}
IGNORED = {
    "node_modules/pkg/AGENTS.md": "# Must not appear\n",
    "scratch/wt/AGENTS.md": "# A worktree copy must not appear\n",
}


def make_repo(root: Path) -> Path:
    for rel, text in {**FILES, **IGNORED}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
           "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True, timeout=30)
    subprocess.run([*git, "add", "-A"], check=True, timeout=30)
    subprocess.run([*git, "commit", "-q", "-m", "fixture"], check=True, timeout=30)
    return root


# Built once for the module: each git call costs well over half a second on Windows.
TMP: tempfile.TemporaryDirectory | None = None
REPO = Path()


def setUpModule():
    global TMP, REPO
    TMP = tempfile.TemporaryDirectory()
    REPO = make_repo(Path(TMP.name) / "fixture")


def tearDownModule():
    TMP.cleanup()


class PrimeTestCase(unittest.TestCase):
    def run_prime(self, *args: str) -> tuple[int, list[str]]:
        lines: list[str] = []
        ok = [prime.prime_one(a, lines.append) for a in args]
        return (0 if all(ok) else 1), lines

    @staticmethod
    def section(lines: list[str], name: str) -> list[str]:
        start = lines.index(f"[{name}]") + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith(("[", "==="))
                    and not lines[i].startswith("[error]")), len(lines))
        return lines[start:end]


class Steps(PrimeTestCase):
    # Run from a subdirectory, so every test here also proves it resolves to the repo root.
    @classmethod
    def setUpClass(cls):
        cls.lines: list[str] = []
        cls.ok = prime.prime_one(str(REPO / "docs"), cls.lines.append)

    def test_state_carries_branch_and_log(self):
        state = self.section(self.lines, "state")
        self.assertTrue(self.ok)
        self.assertEqual(self.lines[0], f"=== REPO fixture ({REPO.resolve()})")
        self.assertTrue(state[0].startswith("## main"))
        self.assertTrue(any("fixture" in line for line in state))

    def test_status_line_is_parsed_case_insensitively_and_unbolded(self):
        docs = self.section(self.lines, "docs")
        self.assertIn("docs/PLAN.md | In progress. Phase 2 next.", docs)
        self.assertIn("docs/NOTES.md | -", docs)
        self.assertIn("ROADMAP.md | -", docs)
        self.assertFalse(any(line.startswith("README.md") for line in docs))

    def test_nested_agents_headings_verbatim_without_fences_or_ignored_dirs(self):
        traps = self.section(self.lines, "traps")
        self.assertEqual(traps, ["stacks/AGENTS.md", "  # Working in stacks/", "  ## Ports",
                                 "  ### Deploy by hand"])

    def test_run_targets_respect_depth(self):
        commands = self.section(self.lines, "commands")
        self.assertIn("target: requirements.txt", commands)
        self.assertIn("scripts: package.json: dev, test", commands)
        self.assertIn("scripts: app/package.json: build", commands)
        self.assertFalse(any("a/b/c" in line for line in commands))

    def test_an_extensionless_ctl_command_is_a_run_target(self):
        """Intent: a repo's own control command is found without naming it."""
        lines = prime.step_commands(REPO, ["toolctl", "tools/fooctl", "notctl.py", "a/b/c/deepctl"])
        self.assertIn("target: toolctl", lines)
        self.assertIn("target: tools/fooctl", lines)
        self.assertNotIn("target: notctl.py", lines)
        self.assertFalse(any("deepctl" in line for line in lines))


class Isolation(PrimeTestCase):
    def test_a_bad_path_fails_alone_and_the_next_repo_still_reports(self):
        missing = str(Path(TMP.name) / "no-such-repo")
        code, lines = self.run_prime(missing, str(REPO))
        self.assertEqual(code, 1)
        self.assertIn(f"=== REPO {missing}", lines)
        self.assertTrue(any(line.startswith("[error] not a directory") for line in lines))
        self.assertIn("docs/PLAN.md | In progress. Phase 2 next.", self.section(lines, "docs"))

    def test_a_directory_outside_git_is_an_error_not_a_crash(self):
        plain = Path(TMP.name) / "plain"
        plain.mkdir(exist_ok=True)
        code, lines = self.run_prime(str(plain))
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("[error] git rev-parse") for line in lines))

    def test_an_unreadable_package_json_is_reported_not_skipped(self):
        broken = Path(TMP.name) / "broken"
        broken.mkdir(exist_ok=True)
        (broken / "package.json").write_text("{not json", encoding="utf-8")
        lines = prime.step_commands(broken, ["package.json"])
        self.assertTrue(any("unreadable package.json" in line for line in lines))

    def test_main_exit_code_reflects_any_failure(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(prime.main([str(Path(TMP.name) / "gone")]), 1)


if __name__ == "__main__":
    unittest.main()
