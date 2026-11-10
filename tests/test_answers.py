################################################################################
# File: test_answers.py
# Path: {PROJECT_ROOT}/tests/test_answers.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-08
# Description: A profile's setup answers: the questions read from
#              every capability file, the answers: key validated against them,
#              and render reporting a declared system that nothing binds.
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


import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402

# Data coverage cannot see.
EXERCISES = ["capabilities/**"]

SHA = "abc1234"
EXAMPLE = sync.ROOT / "examples" / "profile"
MANIFEST = sync.load_profile(EXAMPLE)
DEFAULTS = MANIFEST.get("defaults") or {}
WIREFRAME = (
    "operations:\n"
    "  x: {capability: a.x}\n"
    "setup:\n"
    "  - {id: kind, declares: true}\n"
    "  - {id: style}\n"
)
# The tracker's convention questions in ask order, and each one's ask, read from the file.
CONVENTIONS = ("fields", "body", "summary", "status", "priority", "references", "owner")
ASKS = {q["id"]: q["ask"] for q in yaml.safe_load(
    (sync.CAPABILITIES_DIR / "tracker.yaml").read_text(encoding="utf-8"))["setup"]}


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def wireframes(self, **files: str) -> dict:
        for stem, text in files.items():
            (self.folder / f"{stem}.yaml").write_text(text, encoding="utf-8")
        with mock.patch.object(sync, "CAPABILITIES_DIR", self.folder):
            return sync.setup_questions()


class SetupQuestions(Fixture):
    """Setup reads every capability file's questions rather than a list."""

    def test_every_wireframe_contributes_its_questions(self):
        questions = self.wireframes(a=WIREFRAME, b="operations:\n  y: {capability: b.y}\n")
        self.assertEqual(questions["a"].ids, {"kind", "style"})
        self.assertEqual(questions["a"].declares, "kind")
        self.assertEqual(questions["a"].capabilities, {"a.x"})
        self.assertEqual(questions["b"].ids, set())
        self.assertIsNone(questions["b"].declares)

    def test_the_tracker_declares_its_system_through_the_system_question(self):
        """Intent: the capability file says which answer declares
        a system, so sync.py names no question."""
        self.assertEqual(sync.setup_questions()["tracker"].declares, "system")

    def test_a_malformed_setup_section_refuses(self):
        ops = "operations:\n  x: {capability: a.x}\n"
        cases = {
            "not a list": (ops + "setup: {kind: x}\n", "must be a list"),
            "entry not a mapping": (ops + "setup:\n  - kind\n", "has no id"),
            "no id": (ops + "setup:\n  - {ask: q}\n", "has no id"),
            "empty id": (ops + "setup:\n  - {id: ''}\n", "has no id"),
            "duplicate id": (ops + "setup:\n  - {id: kind}\n  - {id: kind}\n", "asked twice"),
            "two declare": (ops + "setup:\n  - {id: k, declares: true}\n"
                                  "  - {id: j, declares: true}\n", "One question names it"),
            "declares not true": (ops + "setup:\n  - {id: k, declares: 'yes'}\n",
                                  "declares must be true"),
        }
        for name, (text, needle) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(sync.SyncError) as caught:
                    self.wireframes(a=text)
                self.assertIn(needle, str(caught.exception))

    def test_renders_must_be_true_or_absent(self):
        """Intent: setup_questions refuses any renders value but true or absent."""
        for value in ("'yes'", "false", "1"):
            with self.subTest(value=value):
                with self.assertRaises(sync.SyncError) as caught:
                    self.wireframes(a=f"setup:\n  - {{id: k, renders: {value}}}\n")
                self.assertIn("renders must be true", str(caught.exception))

    def test_flagged_questions_are_carried_in_ask_order(self):
        """Intent: Questions carries the flagged ids in ask order."""
        questions = self.wireframes(a="setup:\n  - {id: zeta, renders: true}\n  - {id: mid}\n"
                                      "  - {id: alpha, renders: true}\n")
        self.assertEqual(questions["a"].renders, ("zeta", "alpha"))

    def test_the_tracker_flags_its_seven_conventions(self):
        """Intent: which answers render is set in the capability file."""
        self.assertEqual(sync.setup_questions()["tracker"].renders, CONVENTIONS)


class ValidateAnswers(Fixture):
    """an answer under a key no capability file asks is refused."""

    def check(self, answers) -> dict:
        return sync.validate_answers({"answers": answers}, self.wireframes(a=WIREFRAME))

    def test_answers_to_asked_questions_pass(self):
        answers = {"a.kind": "ExampleTracker", "a.style": "Imperative."}
        self.assertEqual(self.check(answers), answers)

    def test_no_answers_is_valid(self):
        for value in (None, {}):
            with self.subTest(value=value):
                self.assertEqual(self.check(value), {})

    def test_a_key_no_capability_file_asks_refuses_naming_it(self):
        for key in ("b.kind", "a.knd", "kind", "a.", ".kind", "a.kind.extra"):
            with self.subTest(key=key):
                with self.assertRaises(sync.SyncError) as caught:
                    self.check({key: "x"})
                self.assertIn(repr(key), str(caught.exception))

    def test_an_answer_that_is_not_a_non_empty_string_refuses(self):
        """Intent: answers are prose; and empty is missing."""
        for value in ("", "   ", None, 3, ["a"], {"a": "b"}, True):
            with self.subTest(value=value):
                with self.assertRaises(sync.SyncError) as caught:
                    self.check({"a.kind": value})
                self.assertIn("a.kind", str(caught.exception))


class Unbuilt(unittest.TestCase):
    """declaring a system with no binding is reported unbuilt by render."""

    QUERY = {"tracker.query": {"skill": "example-tracker"}}

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.profile = Path(tmp.name)
        skill = cls.profile / "seeds" / "skills" / "example-tracker"
        skill.mkdir(parents=True)
        (skill / "procedure.md").write_text(
            "---\nname: example-tracker\ndescription: Query ExampleTracker.\n---\n\n"
            "# Example tracker\n", encoding="utf-8")

    def tearDown(self):
        sync.set_stamp_source(MANIFEST)

    def plan(self, answers: dict, capabilities: dict) -> sync.Plan:
        manifest = {**MANIFEST, "answers": answers, "capabilities": capabilities}
        return sync.build_plan("t", {}, DEFAULTS, SHA, manifest, self.profile)

    def test_a_declared_system_with_nothing_bound_is_unbuilt(self):
        plan = self.plan({"tracker.system": "ExampleTracker"}, {})
        self.assertEqual(plan.unbuilt, ["tracker.system"])

    def test_one_bound_capability_is_enough(self):
        self.assertEqual(self.plan({"tracker.system": "ExampleTracker"}, self.QUERY).unbuilt, [])

    def test_answers_that_declare_no_system_are_not_unbuilt(self):
        self.assertEqual(self.plan({"tracker.body": "Problem, then Steps."}, {}).unbuilt, [])

    def test_render_refuses_a_bad_answer_before_writing(self):
        with self.assertRaises(sync.SyncError) as caught:
            self.plan({"tracker.sytem": "ExampleTracker"}, self.QUERY)
        self.assertIn("tracker.sytem", str(caught.exception))

    def test_render_prints_each_unbuilt_system(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sync.report_drops(self.plan({"tracker.system": "ExampleTracker"}, {}))
        lines = [line for line in out.getvalue().splitlines() if "unbuilt" in line]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^\[INFO\] unbuilt: tracker\.system is answered, and no "
                                   r"capability tracker\.yaml defines is bound$")


class Conventions(unittest.TestCase):
    """A profile's prose answers reach an agent as an on-demand rule."""

    RULE = f"{sync.ON_DEMAND_DIR}/tracker-conventions.md"
    CURSOR = ".cursor/rules/tracker-conventions.mdc"
    ANSWERS = {"tracker.system": "ExampleTracker",
               **{f"tracker.{q}": f"Answer for {q}, as given." for q in CONVENTIONS}}

    def tearDown(self):
        sync.set_stamp_source(MANIFEST)

    def plan(self, answers: dict) -> sync.Plan:
        return sync.build_plan("t", {}, DEFAULTS, SHA, {**MANIFEST, "answers": answers},
                               profile_dir=EXAMPLE)

    def report(self, plan: sync.Plan) -> list[str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sync.report_drops(plan)
        return out.getvalue().splitlines()

    def test_every_flagged_answer_renders_into_both_paths_with_its_ask(self):
        """Intent: a profile with tracker.system and the seven flagged
        answers renders tracker-conventions into both paths, carrying each answer."""
        plan = self.plan(self.ANSWERS)
        for path in (self.RULE, self.CURSOR):
            with self.subTest(path=path):
                self.assertIn(path, sorted(plan))
                for question in CONVENTIONS:
                    self.assertIn(ASKS[question], plan[path])
                    self.assertIn(f"Answer for {question}, as given.", plan[path])

    def test_answers_render_in_ask_order(self):
        """Intent: the flagged ids are carried in ask order."""
        text = self.plan(self.ANSWERS)[self.RULE]
        places = [text.index(f"Answer for {q}, as given.") for q in CONVENTIONS]
        self.assertEqual(places, sorted(places))

    def test_binding_only_answers_do_not_render(self):
        """Intent: system, connection, relations and operations stay
        binding-only."""
        answers = {**self.ANSWERS, "tracker.connection": "Through a tunnel, as given."}
        self.assertNotIn("Through a tunnel, as given.", self.plan(answers)[self.RULE])

    def test_a_missing_flagged_answer_is_named_in_the_rule_and_the_report(self):
        """Intent: a missing flagged answer is named in the rendered rule
        and in render's output."""
        answers = {k: v for k, v in self.ANSWERS.items() if k != "tracker.owner"}
        plan = self.plan(answers)
        self.assertIn(ASKS["owner"], plan[self.RULE])
        self.assertIn("tracker.owner", plan[self.RULE])
        self.assertTrue([line for line in self.report(plan) if "tracker.owner" in line],
                        self.report(plan))

    def test_a_routing_row_points_at_the_rule(self):
        """Intent: a routing-table row in AGENTS.md for each rendered
        conventions rule."""
        self.assertIn(f"`{self.RULE}`", self.plan(self.ANSWERS)["AGENTS.md"])

    def test_a_rule_with_nowhere_to_route_refuses(self):
        """Characterisation: a conventions rule with no routing row is never found, so render
        refuses rather than writing it."""
        with mock.patch.object(sync, "CONVENTIONS_MARKER", "<!-- NOT THERE -->"):
            with self.assertRaises(sync.SyncError) as caught:
                self.plan(self.ANSWERS)
        self.assertIn("tracker-conventions", str(caught.exception))

    def test_no_declared_system_renders_no_rule_no_row_and_no_report(self):
        """Intent: no tracker.system answer renders no conventions rule
        and no routing row. Design: nothing is reported."""
        plan = self.plan({"tracker.body": "Answer for body, as given."})
        self.assertEqual([p for p in plan if "conventions" in p], [])
        self.assertNotIn("tracker-conventions", plan["AGENTS.md"])
        self.assertNotIn("<!-- CONVENTIONS -->", plan["AGENTS.md"])
        self.assertEqual([line for line in self.report(plan) if "conventions" in line], [])


class ProfileKey(Fixture):
    def test_answers_is_a_profile_key_and_must_be_a_mapping(self):
        path = self.folder / "profile.yaml"
        path.write_text("answers: {}\n", encoding="utf-8")
        self.assertEqual(sync.load_profile(self.folder)["answers"], {})
        path.write_text("answers: [a]\n", encoding="utf-8")
        with self.assertRaises(sync.SyncError):
            sync.load_profile(self.folder)


if __name__ == "__main__":
    unittest.main()
