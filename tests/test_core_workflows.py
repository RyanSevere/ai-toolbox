#!/usr/bin/env python3
################################################################################
# File: test_core_workflows.py
# Path: {PROJECT_ROOT}/tests/test_core_workflows.py
# Created by: Cursor agent, for Ryan Severe
# Created: 2026-11-09
# Last Updated: 2026-11-09
# Description: The shipped workflows are safe to run for a fork's pull request.
#              Every pull_request job pins a GitHub-hosted runner, so a fork
#              can't steer a job onto a machine of its own. No job that reads a
#              secret runs for a fork, and at least one job says so out loud.
#              The Dependabot config keeps the SHA-pinned actions current.
#              Stdlib and PyYAML only.
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
import re
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
GITHUB = HERE.parent / ".github"
WORKFLOWS = GITHUB / "workflows"

HOSTED = re.compile(r"^(ubuntu|windows|macos)-")
SAME_REPO = "github.event.pull_request.head.repo.full_name == github.repository"
FORK_ONLY = "!= github.repository"


def triggers(doc: dict) -> set[str]:
    """The event names a workflow runs on. PyYAML reads the key `on` as the
    boolean True, and the value may be a string, a list or a map."""
    raw = doc.get("on", doc.get(True))
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if isinstance(raw, dict):
        return {str(key) for key in raw}
    return set()


def load_workflows(directory: Path) -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.yml"))
    }


def pull_request_workflows(directory: Path) -> dict[str, dict]:
    return {
        name: doc
        for name, doc in load_workflows(directory).items()
        if "pull_request" in triggers(doc)
    }


def reads_a_secret(job: dict) -> bool:
    """Whether a job names `secrets.` anywhere but its own `if:`."""
    body = {key: value for key, value in job.items() if key != "if"}
    return "secrets." in json.dumps(body)


def runner_problems(directory: Path) -> list[str]:
    problems = []
    for name, doc in pull_request_workflows(directory).items():
        for job_name, job in (doc.get("jobs") or {}).items():
            runner = job.get("runs-on")
            if not isinstance(runner, str):
                problems.append(f"{name}: job {job_name}: runs-on is not a plain string")
            elif "${{" in runner:
                problems.append(f"{name}: job {job_name}: runs-on is an expression: {runner}")
            elif not HOSTED.match(runner):
                problems.append(f"{name}: job {job_name}: runs-on is not GitHub-hosted: {runner}")
    return problems


def secret_problems(directory: Path) -> list[str]:
    problems = []
    for name, doc in pull_request_workflows(directory).items():
        for job_name, job in (doc.get("jobs") or {}).items():
            if reads_a_secret(job) and SAME_REPO not in str(job.get("if", "")):
                problems.append(
                    f"{name}: job {job_name}: reads a secret and does not require "
                    f"a pull request from this repository"
                )
    return problems


def fork_only_jobs(directory: Path) -> list[str]:
    found = []
    for name, doc in pull_request_workflows(directory).items():
        for job_name, job in (doc.get("jobs") or {}).items():
            if FORK_ONLY in str(job.get("if", "")) and not reads_a_secret(job):
                found.append(f"{name}: {job_name}")
    return found


class TheTree(unittest.TestCase):
    def test_the_tree_has_pull_request_workflows(self):
        found = pull_request_workflows(WORKFLOWS)
        self.assertGreaterEqual(
            len(found), 2, "the checks below pass vacuously over fewer pull_request workflows"
        )

    def test_every_pull_request_job_pins_a_hosted_runner(self):
        self.assertEqual([], runner_problems(WORKFLOWS))

    def test_no_job_that_reads_a_secret_runs_for_a_fork(self):
        self.assertEqual([], secret_problems(WORKFLOWS))

    def test_a_fork_only_job_says_the_gates_do_not_run_and_reads_no_secret(self):
        self.assertTrue(fork_only_jobs(WORKFLOWS), "no job carries the fork-only condition")


class TheDependabotConfig(unittest.TestCase):
    def setUp(self):
        path = GITHUB / "dependabot.yml"
        self.assertTrue(path.is_file(), f"{path} does not exist")
        self.doc = yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_it_is_version_2(self):
        self.assertEqual(2, self.doc.get("version"))

    def test_it_keeps_github_actions_current_at_the_root_against_dev(self):
        entries = [
            entry
            for entry in self.doc.get("updates") or []
            if entry.get("package-ecosystem") == "github-actions"
        ]
        self.assertEqual(1, len(entries), "want exactly one github-actions entry")
        self.assertEqual("/", entries[0].get("directory"))
        self.assertEqual("dev", entries[0].get("target-branch"))


class MutatedCopies(unittest.TestCase):
    """The checkers must name what they catch, or the tests above prove nothing."""

    def mutated(self, name: str, old: str, new: str) -> Path:
        source = (WORKFLOWS / name).read_text(encoding="utf-8")
        self.assertIn(old, source, f"{name} no longer contains the text this test mutates")
        tmp = Path(tempfile.mkdtemp(dir=tempfile.gettempdir()))
        self.addCleanup(self._remove, tmp)
        (tmp / name).write_text(source.replace(old, new, 1), encoding="utf-8")
        return tmp

    @staticmethod
    def _remove(directory: Path) -> None:
        for path in directory.glob("*"):
            path.unlink()
        directory.rmdir()

    def test_a_runner_chosen_by_a_variable_is_named(self):
        tmp = self.mutated(
            "ci.yml",
            "runs-on: ubuntu-latest",
            "runs-on: ${{ vars.RUNNER || 'ubuntu-latest' }}",
        )
        problems = runner_problems(tmp)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("ci.yml: job tests", problems[0])
        self.assertIn("expression", problems[0])

    def test_a_self_hosted_runner_is_named(self):
        tmp = self.mutated("ci.yml", "runs-on: ubuntu-latest", "runs-on: self-hosted")
        problems = runner_problems(tmp)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("not GitHub-hosted", problems[0])

    def test_a_secret_job_with_no_same_repository_guard_is_named(self):
        tmp = self.mutated(
            "one-way-gates.yml",
            "    if: github.event_name != 'pull_request' || "
            "github.event.pull_request.head.repo.full_name == github.repository\n",
            "",
        )
        problems = secret_problems(tmp)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("one-way-gates.yml: job gates", problems[0])

    def test_a_fork_only_job_that_reads_a_secret_does_not_count(self):
        tmp = self.mutated(
            "one-way-gates.yml",
            "echo \"::warning::The one-way gates do not run on fork",
            "echo \"${{ secrets.LEAK_DENYLIST }}::The one-way gates do not run on fork",
        )
        self.assertNotIn("one-way-gates.yml: fork-notice", fork_only_jobs(tmp))


class TriggerForms(unittest.TestCase):
    def test_a_string_a_list_and_a_map_read_alike(self):
        self.assertEqual({"pull_request"}, triggers({"on": "pull_request"}))
        self.assertEqual({"pull_request", "push"}, triggers({"on": ["pull_request", "push"]}))
        self.assertEqual({"pull_request", "push"}, triggers({"on": {"pull_request": None, "push": {}}}))

    def test_the_key_pyyaml_reads_as_true_is_found(self):
        doc = yaml.safe_load("on:\n  pull_request:\n")
        self.assertIn(True, doc, "PyYAML no longer reads the key `on` as True")
        self.assertEqual({"pull_request"}, triggers(doc))

    def test_a_workflow_with_no_trigger_reads_as_none(self):
        self.assertEqual(set(), triggers({"jobs": {}}))


if __name__ == "__main__":
    unittest.main()
