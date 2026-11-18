#!/usr/bin/env python3
################################################################################
# File: test_gate_report.py
# Path: {PROJECT_ROOT}/tests/test_gate_report.py
# Created by: Ryan Severe
# Created: 2026-11-18
# Last Updated: 2026-11-18
# Description: Covers the exit criteria of the gate report check plus the ways a
#              report can be present and still worthless. Every case asserts
#              that the answer is a refusal rather than a pass, because the
#              defect this gate exists to prevent is a green signal over an
#              unexamined push. A skipped required gate is a finding unless the
#              profile declares an exemption for that gate on that ref.
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
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / "actions" / "report-gate"
sys.path.insert(0, str(ACTION))
sys.path.insert(0, str(ROOT))

import gate_report as gr  # noqa: E402
import sync  # noqa: E402

SHA = "b9ee31428cbfa3d0e7c95af3a43a9a778e2085e3"
OTHER_SHA = "0000000000000000000000000000000000000000"
REQUIRED = ["dead-variants", "typecheck"]

# A declared exemption, written the way a profile declares one: a pattern that must match
# the whole ref, and the gates it lets a report skip.
SCHEME_PATTERN = r"(?:scheme/[^/]+/approved|(?:refs/heads/)?scheme/[^/]+/tests)"
SCHEME_SKIP = [(SCHEME_PATTERN, ["tests"])]


def report(commit: str = SHA, **gates) -> dict:
    return {"commit": commit, "gates": gates or {n: {"status": "pass"} for n in REQUIRED}}


class GateList(unittest.TestCase):
    def test_ci_reads_the_list_the_hook_runs(self):
        """Intent: CI's required list is derived from the same data, so the
        validator and the action both default to the list the core renders."""
        self.assertEqual(gr.DEFAULT_GATES_FILE, sync.ENABLED_GATES)
        action = yaml.safe_load((ACTION / "action.yml").read_text(encoding="utf-8"))
        self.assertEqual(action["inputs"]["gates"]["default"], sync.ENABLED_GATES)

    def test_ci_reads_the_gate_config_the_core_renders(self):
        """Intent: the exemptions are read from the file sync renders them into."""
        self.assertEqual(gr.DEFAULT_GATE_CONFIG_FILE, ".githooks/gate-config")
        action = yaml.safe_load((ACTION / "action.yml").read_text(encoding="utf-8"))
        self.assertEqual(action["inputs"]["gate-config"]["default"], gr.DEFAULT_GATE_CONFIG_FILE)

    def file(self, text: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", newline="\n")
        handle.write(text)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(path.unlink)
        return path

    def test_comments_and_blank_lines_are_ignored(self):
        path = self.file("# which gates must pass\n\ndead-variants\ntypecheck  # inline\n")
        self.assertEqual(gr.load_required_gates(path), REQUIRED)

    def test_missing_file_refuses(self):
        """No declared gates and zero required gates must not look alike."""
        with self.assertRaises(gr.ReportError):
            gr.load_required_gates(Path("does-not-exist"))

    def test_empty_file_refuses(self):
        with self.assertRaises(gr.ReportError):
            gr.load_required_gates(self.file("# nothing but a comment\n"))


class Parsing(unittest.TestCase):
    def test_malformed_json_refuses(self):
        with self.assertRaises(gr.ReportError):
            gr.parse_report("{not json")

    def test_a_json_list_refuses(self):
        with self.assertRaises(gr.ReportError):
            gr.parse_report("[]")


class Validation(unittest.TestCase):
    def findings(self, doc: dict, sha: str = SHA) -> list[str]:
        return gr.validate(doc, sha, REQUIRED)[0]

    def test_complete_passing_report_bound_to_the_commit_passes(self):
        self.assertEqual(self.findings(report()), [])

    def test_report_for_a_different_commit_is_refused(self):
        findings = self.findings(report(commit=OTHER_SHA))
        self.assertTrue(any(OTHER_SHA in f and SHA in f for f in findings))

    def test_report_naming_no_commit_is_refused(self):
        doc = report()
        del doc["commit"]
        self.assertTrue(any("names no commit" in f for f in self.findings(doc)))

    def test_a_required_gate_missing_from_the_report_is_refused(self):
        doc = report(**{"typecheck": {"status": "pass"}})
        self.assertTrue(any("dead-variants" in f and "absent" in f for f in self.findings(doc)))

    def test_a_failing_gate_is_refused_with_its_detail(self):
        doc = report(**{
            "dead-variants": {"status": "fail", "detail": "two dead variants"},
            "typecheck": {"status": "pass"},
        })
        self.assertTrue(any("two dead variants" in f for f in self.findings(doc)))

    def test_gates_object_missing_entirely_is_refused(self):
        self.assertTrue(any("no gates object" in f for f in self.findings({"commit": SHA})))

    def test_an_extra_gate_is_a_note_not_a_finding(self):
        doc = report(**{
            "dead-variants": {"status": "pass"},
            "typecheck": {"status": "pass"},
            "some-future-gate": {"status": "pass"},
        })
        findings, notes = gr.validate(doc, SHA, REQUIRED)
        self.assertEqual(findings, [])
        self.assertTrue(any("some-future-gate" in n for n in notes))

    def test_a_skipped_gate_is_a_note_naming_it(self):
        """Intent: a disabled gate is named, and CI shows it as skipped rather than as
        drift between the hook and the list."""
        doc = {**report(), "skipped": ["eslint"]}
        findings, notes = gr.validate(doc, SHA, REQUIRED)
        self.assertEqual(findings, [])
        self.assertIn("eslint: skipped, off in profile.lock", notes)

    def test_a_required_gate_reported_as_skipped_is_refused(self):
        """Intent: the hook skips only what the list leaves out, so a required gate in skipped
        is a report that disagrees with the list."""
        doc = {**report(), "skipped": ["typecheck"]}
        self.assertTrue(any("typecheck" in f and "skipped" in f for f in self.findings(doc)))

    def test_flag_changes_are_notes(self):
        """Intent: every flag change is printed in the pre-push report."""
        doc = {**report(), "flag_changes": ["eslint: on -> off"]}
        findings, notes = gr.validate(doc, SHA, REQUIRED)
        self.assertEqual(findings, [])
        self.assertIn("flag changed: eslint: on -> off", notes)

    def test_skipped_that_is_not_a_list_is_refused(self):
        """Intent: unknown is not zero - an unreadable skipped list is not an empty one."""
        self.assertTrue(any("skipped" in f for f in self.findings({**report(), "skipped": "x"})))

    def test_an_empty_gates_object_refuses_every_required_gate(self):
        """An empty report must not read as 'nothing to check'."""
        findings = self.findings({"commit": SHA, "gates": {}})
        self.assertEqual(len(findings), len(REQUIRED))


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, True)
        self.gates = self.work / "gates"
        self.gates.write_text("\n".join(REQUIRED) + "\n", encoding="utf-8")
        self.config = self.work / "gate-config"
        self.config.write_text("deploy-branch=main\n", encoding="utf-8")

    def run_check(self, *extra: str, config: Path | None = None):
        args = [
            sys.executable, str(Path(gr.__file__)),
            "--sha", SHA,
            "--gates", str(self.gates),
            "--gate-config", str(config or self.config),
            *extra,
        ]
        return subprocess.run(args, capture_output=True, text=True)

    def write_report(self, doc: dict) -> Path:
        path = self.work / "report.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_a_push_with_no_report_exits_non_zero(self):
        result = self.run_check("--report", str(self.work / "absent.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no report at", result.stderr)

    def test_a_complete_report_exits_zero(self):
        result = self.run_check("--report", str(self.write_report(report())))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_missing_gate_config_refuses_and_says_so(self):
        """Intent: an unreadable gate-config is never read as 'no exemption declared'."""
        result = self.run_check("--report", str(self.write_report(report())),
                                config=self.work / "absent-config")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gate-config", result.stderr)

    def test_a_declared_exemption_is_read_from_gate_config(self):
        self.gates.write_text("ruff\ntests\n", encoding="utf-8")
        self.config.write_text(
            f"deploy-branch=main\nreport-skip={SCHEME_PATTERN} tests\n", encoding="utf-8")
        doc = {**report(ruff={"status": "pass"}), "skipped": ["tests"]}
        path = self.write_report(doc)
        ok = self.run_check("--report", str(path), "--ref", "refs/heads/scheme/r1/tests")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        refused = self.run_check("--report", str(path), "--ref", "refs/heads/other")
        self.assertNotEqual(refused.returncode, 0)

    def test_a_skipped_gate_with_nothing_declared_refuses(self):
        self.gates.write_text("ruff\ntests\n", encoding="utf-8")
        doc = {**report(ruff={"status": "pass"}), "skipped": ["tests"]}
        result = self.run_check("--report", str(self.write_report(doc)),
                                "--ref", "refs/heads/scheme/r1/tests")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("skipped", result.stderr)


class GateConfigFile(unittest.TestCase):
    """The exemptions are read from the rendered gate-config, one report-skip= line each."""

    def load(self, text: str):
        path = Path(tempfile.mkdtemp()) / "gate-config"
        self.addCleanup(shutil.rmtree, path.parent, True)
        path.write_text(text, encoding="utf-8")
        return gr.load_gate_config(path)

    def test_no_report_skip_line_declares_nothing(self):
        skips, deploy = self.load("# stamp\ndeploy-branch=main\nconfig-dir=.gates\n")
        self.assertEqual((skips, deploy), ([], "main"))

    def test_a_line_names_a_pattern_and_its_gates(self):
        skips, _ = self.load(f"deploy-branch=main\nreport-skip={SCHEME_PATTERN} tests,lint\n")
        self.assertEqual(skips, [(SCHEME_PATTERN, ["tests", "lint"])])

    def test_a_missing_file_refuses(self):
        with self.assertRaises(gr.ReportError) as caught:
            gr.load_gate_config(Path("does-not-exist"))
        self.assertIn("gate-config", str(caught.exception))

    def test_a_line_that_is_not_pattern_then_gates_refuses(self):
        for line in ("report-skip=onlypattern", "report-skip=", "report-skip=a b c,"):
            with self.subTest(line=line), self.assertRaises(gr.ReportError):
                self.load(f"deploy-branch=main\n{line}\n")

    def test_an_invalid_pattern_refuses(self):
        with self.assertRaises(gr.ReportError):
            self.load("deploy-branch=main\nreport-skip=(unclosed tests\n")

    def test_an_exemption_without_a_deploy_branch_refuses(self):
        """Intent: with no deploy branch the never-exempt rule cannot be applied, so it fails
        closed rather than skipping the rule."""
        with self.assertRaises(gr.ReportError):
            self.load("report-skip=x tests\n")


class DeclaredExemptions(unittest.TestCase):
    """A skipped required gate is a finding unless the profile declared an exemption for it."""

    REQ = ["ruff", "tests"]

    def check(self, skipped: list[str], ref: str | None = None, skip_allowed=None,
              deploy_branch: str = "main", **extra):
        doc = {**report(**{n: {"status": "pass"} for n in self.REQ}), "skipped": skipped}
        doc.update(extra)
        kwargs = {}
        if skip_allowed is not None:
            kwargs["skip_allowed"] = skip_allowed
            kwargs["deploy_branch"] = deploy_branch
        if ref is None:
            return gr.validate(doc, SHA, self.REQ, **kwargs)
        return gr.validate(doc, SHA, self.REQ, ref, **kwargs)

    def refused(self, findings: list[str], gate: str = "tests") -> bool:
        return any(gate in f and "skipped" in f for f in findings)

    def test_with_nothing_declared_every_skipped_required_gate_is_a_finding(self):
        for ref in (None, "main", "scheme/r1/approved", "refs/heads/scheme/r1/tests"):
            for gate in self.REQ:
                with self.subTest(ref=ref, gate=gate):
                    findings, _ = self.check([gate], ref)
                    self.assertTrue(self.refused(findings, gate))

    def test_an_empty_declaration_is_the_same_as_none(self):
        findings, _ = self.check(["tests"], "scheme/r1/approved", skip_allowed=[])
        self.assertTrue(self.refused(findings))

    def test_a_declared_exemption_accepts_the_gate_on_a_matching_ref_as_a_note(self):
        for ref in ("scheme/r1/approved", "scheme/r1/tests", "refs/heads/scheme/r1/tests"):
            with self.subTest(ref=ref):
                findings, notes = self.check(["tests"], ref, skip_allowed=SCHEME_SKIP)
                self.assertEqual(findings, [])
                self.assertTrue(any(f"tests: skipped on ref {ref}" in n for n in notes))

    def test_a_declared_exemption_accepts_only_its_gate(self):
        findings, _ = self.check(["ruff"], "scheme/r1/approved", skip_allowed=SCHEME_SKIP)
        self.assertTrue(self.refused(findings, "ruff"))

    def test_a_ref_that_matches_only_as_a_substring_is_not_exempt(self):
        """Intent: the match is against the whole ref."""
        for ref in ("x/scheme/r1/approved", "scheme/r1/approved/x", "refs/heads/scheme/a/b/tests",
                    "main", "refs/heads/main", "scheme//tests"):
            with self.subTest(ref=ref):
                findings, _ = self.check(["tests"], ref, skip_allowed=SCHEME_SKIP)
                self.assertTrue(self.refused(findings))

    def test_with_no_ref_nothing_is_exempt(self):
        findings, _ = self.check(["tests"], skip_allowed=SCHEME_SKIP)
        self.assertTrue(self.refused(findings))

    def test_the_deploy_branch_is_never_exempt_even_when_a_pattern_matches_it(self):
        """Intent: a pull request into the deploy branch must have run every required gate."""
        greedy = [(".*", ["tests"])]
        for ref in ("main", "refs/heads/main"):
            with self.subTest(ref=ref):
                findings, _ = self.check(["tests"], ref, skip_allowed=greedy)
                self.assertTrue(self.refused(findings))
        findings, _ = self.check(["tests"], "refs/heads/other", skip_allowed=greedy)
        self.assertEqual(findings, [])

    def test_a_skipped_gate_left_out_of_gates_is_exempt_only_where_declared(self):
        """A report may list a skipped gate in `skipped` and leave it out of `gates`; where the
        exemption holds that is not also an absent gate, and elsewhere it is."""
        doc = {**report(ruff={"status": "pass"}), "skipped": ["tests"]}
        findings, notes = gr.validate(doc, SHA, self.REQ, "refs/heads/scheme/r1/tests",
                                      skip_allowed=SCHEME_SKIP, deploy_branch="main")
        self.assertEqual(findings, [])
        self.assertTrue(any("skipped on ref" in n for n in notes))
        findings, _ = gr.validate(doc, SHA, self.REQ, "refs/heads/main",
                                  skip_allowed=SCHEME_SKIP, deploy_branch="main")
        self.assertTrue(any("tests" in f and "absent" in f for f in findings))

    def test_an_absent_gate_not_listed_as_skipped_is_refused_even_on_an_exempt_ref(self):
        """Intent: the exemption is for a gate the report says it skipped, never for a report
        that simply lost the gate."""
        doc = {**report(ruff={"status": "pass"}), "skipped": []}
        findings, _ = gr.validate(doc, SHA, self.REQ, "scheme/r1/approved",
                                  skip_allowed=SCHEME_SKIP, deploy_branch="main")
        self.assertTrue(any("tests" in f and "absent" in f for f in findings))

    def test_a_failing_gate_is_not_made_a_pass_by_an_exemption(self):
        doc = report(ruff={"status": "pass"}, tests={"status": "fail"})
        doc["skipped"] = ["tests"]
        findings, _ = gr.validate(doc, SHA, self.REQ, "scheme/r1/approved",
                                  skip_allowed=SCHEME_SKIP, deploy_branch="main")
        self.assertTrue(any("status 'fail'" in f for f in findings))

    def test_order_and_duplicates_do_not_change_the_verdict(self):
        other = (r"scheme/x/.*", ["ruff"])
        first = SCHEME_SKIP[0]
        for entries in ([first, other], [other, first], [first, first, other]):
            with self.subTest(entries=entries):
                findings, _ = self.check(["tests", "ruff"], "scheme/r1/approved",
                                         skip_allowed=entries)
                self.assertTrue(self.refused(findings, "ruff"))
                self.assertFalse(self.refused(findings, "tests"))
                findings, _ = self.check(["ruff"], "scheme/x/y", skip_allowed=entries)
                self.assertEqual(findings, [])


class Graph:
    """A fake history: commit -> parents, plus which commits have reports and which trees merge."""

    def __init__(self, parents, reports=None, trees=None, merges=None, accepted=()):
        self._parents = parents
        self._reports = reports or {}
        self._trees = trees or {}
        self._merges = merges or {}
        self._accepted = set(accepted)
        self.report_lookups: list[str] = []

    def run(self, sha, required=REQUIRED):
        return gr.merge_cover(
            sha,
            required,
            self.parents,
            self.report_for,
            self.clean_merge_tree,
            self.tree_of,
            self.accepted,
        )

    def accepted(self, sha):
        return sha in self._accepted

    def parents(self, sha):
        return self._parents.get(sha, [])

    def report_for(self, sha):
        self.report_lookups.append(sha)
        return self._reports.get(sha)

    def clean_merge_tree(self, first, second):
        return self._merges.get((first, second))

    def tree_of(self, sha):
        return self._trees.get(sha, "")


def passing(sha):
    return report(commit=sha)


class MergeCover(unittest.TestCase):
    """A web-UI merge commit has no report, and is covered only when it adds nothing."""

    def simple_merge(self, **overrides):
        reports = {"a": passing("a"), "b": passing("b")}
        kwargs = dict(
            parents={"m": ["a", "b"]},
            reports=reports,
            trees={"m": "T"},
            merges={("a", "b"): "T"},
        )
        kwargs.update(overrides)
        return Graph(**kwargs)

    def test_two_covered_parents_and_a_matching_tree_pass(self):
        ok, why = self.simple_merge().run("m")
        self.assertTrue(ok, why)
        self.assertIn("a", why)
        self.assertIn("b", why)

    def test_a_parent_whose_report_fails_is_named(self):
        bad = {"commit": "b", "gates": {"typecheck": {"status": "fail"}, "dead-variants": {"status": "pass"}}}
        graph = self.simple_merge(reports={"a": passing("a"), "b": bad})
        ok, why = graph.run("m")
        self.assertFalse(ok)
        self.assertIn("b:", why)
        self.assertIn("typecheck", why)

    def test_a_first_parent_that_is_itself_an_accepted_merge_passes(self):
        graph = Graph(
            parents={"m2": ["m1", "c"], "m1": ["a", "b"]},
            reports={"a": passing("a"), "b": passing("b"), "c": passing("c")},
            trees={"m1": "T1", "m2": "T2"},
            merges={("a", "b"): "T1", ("m1", "c"): "T2"},
        )
        ok, why = graph.run("m2")
        self.assertTrue(ok, why)

    def test_a_chain_longer_than_the_cap_is_refused_naming_the_cap(self):
        depth = gr.MERGE_COVER_DEPTH_CAP + 5
        parents, trees, merges = {}, {}, {}
        for i in range(depth):
            parents[f"m{i}"] = [f"m{i + 1}", f"s{i}"]
            trees[f"m{i}"] = "T"
            merges[(f"m{i + 1}", f"s{i}")] = "T"
        reports = {f"s{i}": passing(f"s{i}") for i in range(depth)}
        reports[f"m{depth}"] = passing(f"m{depth}")
        ok, why = Graph(parents, reports, trees, merges).run("m0")
        self.assertFalse(ok)
        self.assertIn(str(gr.MERGE_COVER_DEPTH_CAP), why)
        self.assertIn("cap", why)

    def test_a_one_parent_commit_without_a_report_is_refused(self):
        ok, why = Graph(parents={"s": ["a"]}, reports={"a": passing("a")}).run("s")
        self.assertFalse(ok)
        self.assertIn("1 parent", why)

    def test_a_tree_that_differs_from_the_merge_is_refused(self):
        ok, why = self.simple_merge(trees={"m": "OTHER"}).run("m")
        self.assertFalse(ok)
        self.assertIn("differs", why)

    def test_a_conflicting_merge_is_refused(self):
        ok, why = self.simple_merge(merges={}).run("m")
        self.assertFalse(ok)
        self.assertIn("do not merge cleanly", why)

    def test_a_commit_with_its_own_report_passes_without_consulting_parents(self):
        graph = Graph(parents={"m": ["a", "b"]}, reports={"m": passing("m")})
        ok, _ = graph.run("m")
        self.assertTrue(ok)
        self.assertEqual(graph.report_lookups, ["m"])

    def test_an_accepted_first_parent_and_a_reported_second_parent_pass(self):
        graph = self.simple_merge(reports={"b": passing("b")}, accepted={"a"})
        ok, why = graph.run("m")
        self.assertTrue(ok, why)
        self.assertNotIn("a", graph.report_lookups)

    def test_an_accepted_first_parent_does_not_cover_an_unreported_second_parent(self):
        graph = self.simple_merge(reports={}, accepted={"a"})
        ok, why = graph.run("m")
        self.assertFalse(ok)
        self.assertIn("b:", why)

    def test_an_accepted_first_parent_does_not_excuse_a_tree_with_changes_of_its_own(self):
        graph = self.simple_merge(reports={"b": passing("b")}, trees={"m": "OTHER"}, accepted={"a"})
        ok, why = graph.run("m")
        self.assertFalse(ok)
        self.assertIn("differs", why)

    def test_an_accepted_commit_at_depth_one_ends_a_chain_longer_than_the_cap(self):
        depth = gr.MERGE_COVER_DEPTH_CAP + 5
        parents, trees, merges = {}, {}, {}
        for i in range(depth):
            parents[f"m{i}"] = [f"m{i + 1}", f"s{i}"]
            trees[f"m{i}"] = "T"
            merges[(f"m{i + 1}", f"s{i}")] = "T"
        reports = {f"s{i}": passing(f"s{i}") for i in range(depth)}
        ok, why = Graph(parents, reports, trees, merges, accepted={"m1"}).run("m0")
        self.assertTrue(ok, why)

    def test_an_accepted_commit_passes_on_its_own_without_a_report(self):
        ok, why = Graph(parents={}, accepted={"x"}).run("x")
        self.assertTrue(ok, why)
        self.assertIn("already on the branch", why)

    def test_a_commit_with_its_own_failing_report_is_refused_without_merge_logic(self):
        bad = {"commit": "m", "gates": {"typecheck": {"status": "fail"}, "dead-variants": {"status": "pass"}}}
        graph = self.simple_merge(reports={"m": bad, "a": passing("a"), "b": passing("b")})
        ok, why = graph.run("m")
        self.assertFalse(ok)
        self.assertIn("its report fails", why)

    def test_a_covered_commit_whose_report_skips_a_required_gate_is_refused(self):
        """Intent: merge cover grants no exemption, so a parent's skipped required gate stays
        a finding whatever a profile declares for a ref."""
        skipped = {**passing("b"), "skipped": ["typecheck"]}
        graph = self.simple_merge(reports={"a": passing("a"), "b": skipped})
        ok, why = graph.run("m")
        self.assertFalse(ok)
        self.assertIn("skipped", why)


class MergeCoverAgainstRealGit(unittest.TestCase):
    """The same rule over a real repository: real parents, real merge-tree, injected reports."""

    def git(self, *args):
        result = subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit_file(self, name):
        (self.repo / name).write_text(name, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-m", name)
        return self.git("rev-parse", "HEAD")

    def run_cover(self, sha, reports):
        return gr.merge_cover(
            sha,
            REQUIRED,
            lambda s: gr.git_parents(s, self.repo),
            lambda s: reports.get(s),
            lambda a, b: gr.git_clean_merge_tree(a, b, self.repo),
            lambda s: gr.git_tree_of(s, self.repo),
            lambda s: False,
        )

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main")
        self.base = self.commit_file("base.txt")
        self.git("checkout", "-q", "-b", "side")
        self.side = self.commit_file("side.txt")
        self.git("checkout", "-q", "main")
        self.main = self.commit_file("main.txt")
        self.reports = {s: passing(s) for s in (self.main, self.side)}

    def test_a_real_clean_merge_commit_passes_and_an_amended_one_is_refused(self):
        self.git("merge", "--no-ff", "-m", "merge", "side")
        merge = self.git("rev-parse", "HEAD")
        ok, why = self.run_cover(merge, self.reports)
        self.assertTrue(ok, why)

        (self.repo / "extra.txt").write_text("sneaked in", encoding="utf-8")
        self.git("add", "extra.txt")
        self.git("commit", "--amend", "--no-edit")
        amended = self.git("rev-parse", "HEAD")
        ok, why = self.run_cover(amended, self.reports)
        self.assertFalse(ok)
        self.assertIn("differs", why)

    def test_git_is_accepted_follows_ancestry_of_the_prior_tip(self):
        tip = self.git("rev-parse", "main")
        accepted = gr.git_is_accepted(tip, self.repo)
        self.assertTrue(accepted(self.base))
        self.assertTrue(accepted(tip))
        self.assertFalse(accepted(self.side))
        self.assertFalse(accepted("0123456789abcdef0123456789abcdef01234567"))

    def test_git_is_accepted_accepts_nothing_for_a_new_branch(self):
        for before in ("", "0" * 40):
            accepted = gr.git_is_accepted(before, self.repo)
            self.assertFalse(accepted(self.base), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
