################################################################################
# File: test_setup_profile.py
# Path: {PROJECT_ROOT}/tests/test_setup_profile.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-08
# Description: The setup process: a profile created from the
#              example, answers collected interactively or from a file, features
#              left to the consent command, a diff confirmed before any re-run
#              writes, and a dry-run render at the end. Prompts and consent are
#              fakes; nothing reads the console.
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
import consent  # noqa: E402
import setup_profile  # noqa: E402
import sync  # noqa: E402

# Data coverage cannot see.
EXERCISES = ["capabilities/**", "examples/**"]

MANIFEST = sync.load_profile(sync.ROOT / "examples" / "profile")
SYSTEM = "ExampleTracker, a hosted tracker."
TYPED = {"identity.name": "Example Person", "identity.email": "person@example.invalid",
         "tracker.system": SYSTEM}


def fake_consent(calls: list):
    """Stands in for `consent.py --init`: every gate on, written the way it writes them."""
    def run(folder: Path) -> int:
        calls.append(folder)
        gates = {name: True for name in consent.known_gates(folder)}
        consent.write_atomically(folder / consent.LOCK_NAME, consent.render_lock({"gates": gates}))
        path = folder / consent.PROFILE_NAME
        consent.write_atomically(path, consent.replace_features_block(
            path.read_text(encoding="utf-8"), consent.render_features_block(gates)))
        return 0
    return run


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "profile"
        self.consented: list = []
        self.confirms: list = []
        self.addCleanup(sync.set_stamp_source, MANIFEST)

    @property
    def profile(self) -> Path:
        return self.folder / "profile.yaml"

    def run_setup(self, typed: dict | None = None, answers_file: Path | None = None,
                  confirm: bool = True) -> tuple[int, str]:
        typed = TYPED if typed is None else typed

        def ask(key: str, prompt: str, current: str | None) -> str:
            return typed.get(key, "")

        def say_yes(diff: str) -> bool:
            self.confirms.append(diff)
            return confirm

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = setup_profile.run_setup(self.folder, answers_file=answers_file, ask=ask,
                                           confirm=say_yes,
                                           consent_init=fake_consent(self.consented))
        return code, out.getvalue()

    def answers_file(self, text: str) -> Path:
        path = self.folder.parent / "answers.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def data(self) -> dict:
        return yaml.safe_load(self.profile.read_text(encoding="utf-8"))


class FromEmpty(Fixture):
    """from an empty directory, setup produces a profile that renders."""

    def test_an_interactive_run_produces_a_profile_that_renders(self):
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        data = self.data()
        self.assertEqual(data["identity"], {"name": "Example Person",
                                            "email": "person@example.invalid"})
        self.assertEqual(data["answers"], {"tracker.system": SYSTEM})
        self.assertEqual(self.consented, [])
        profile = sync.load_profile(self.folder)
        for name, cfg in profile["targets"].items():
            with self.subTest(target=name):
                plan = sync.build_plan(name, cfg or {}, profile["defaults"], "abc1234", profile,
                                       profile_dir=self.folder)
                self.assertIn("AGENTS.md", plan)
        self.assertIn("[OK] render:", out)

    def test_a_shipped_gate_is_put_to_consent(self):
        """Intent: once any gate ships, setup asks for its flags rather than rendering without
        a lock; with none, there is nothing to consent to."""
        with mock.patch.object(consent, "known_gates", return_value=["alpha"]):
            code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.consented, [self.folder])
        self.assertEqual(self.data()["features"], {"gates": {"alpha": True}})

    def test_the_examples_comments_survive(self):
        """Intent: blocks are replaced in the text, so the
        example's explanation of each key stays in the profile it made."""
        self.run_setup()
        text = self.profile.read_text(encoding="utf-8")
        example = (sync.ROOT / "examples" / "profile" / "profile.yaml").read_text(encoding="utf-8")
        comments = [line for line in example.splitlines() if line.startswith("#")]
        self.assertGreater(len(comments), 10)
        for line in comments:
            with self.subTest(line=line):
                self.assertIn(line, text)

    def test_a_folder_with_other_files_and_no_profile_refuses(self):
        self.folder.mkdir()
        (self.folder / "notes.txt").write_text("mine", encoding="utf-8")
        code, out = self.run_setup()
        self.assertEqual(code, 1)
        self.assertFalse(self.profile.exists())
        self.assertIn("not empty", out)

    def test_a_blank_answer_leaves_the_question_unanswered(self):
        self.run_setup({**TYPED, "tracker.system": "   "})
        self.assertEqual(self.data()["answers"], {})

    def test_a_bad_identity_refuses_before_writing(self):
        code, out = self.run_setup({**TYPED, "identity.email": "not-an-address"})
        self.assertEqual(code, 1)
        self.assertFalse(self.profile.exists())
        self.assertIn("identity.email", out)


class Unbuilt(Fixture):
    """a tracker system with no binding produces a build-list entry."""

    def test_a_system_nothing_binds_is_listed_with_what_to_build(self):
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        self.assertIn("[INFO] unbuilt: tracker.system is answered", out)
        self.assertRegex(out, r"build: tracker\.system - author a profile skill and bind it to "
                              r"one of: tracker\.\w+")

    def test_no_system_answered_lists_nothing_to_build(self):
        _, out = self.run_setup({k: v for k, v in TYPED.items() if k != "tracker.system"})
        self.assertNotIn("build:", out)


class AnswersFile(Fixture):
    """--answers leaves every feature off and profile.lock absent."""

    GOOD = ("identity: {name: Example Person, email: person@example.invalid}\n"
            f"answers: {{tracker.system: '{SYSTEM}'}}\n")

    def test_it_writes_everything_but_features(self):
        code, out = self.run_setup({}, self.answers_file(self.GOOD))
        self.assertEqual(self.data()["answers"], {"tracker.system": SYSTEM})
        self.assertEqual(self.data()["identity"]["name"], "Example Person")
        self.assertEqual(self.data()["features"], {})
        self.assertFalse((self.folder / "profile.lock").exists())
        self.assertEqual(self.consented, [])
        self.assertEqual(code, 0, out)
        self.assertIn("[OK] render:", out)

    def test_a_file_that_sets_features_or_anything_else_refuses(self):
        """Intent: features are set only through the consent command."""
        for text in (self.GOOD + "features: {gates: {}}\n", self.GOOD + "targets: {}\n",
                     "- not a mapping\n",
                     "identity: {name: A, email: a@b.invalid, signing: x}\n",
                     "identity: {name: A, email: a@b.invalid}\nanswers: [tracker.system]\n"):
            with self.subTest(text=text):
                self.profile.unlink(missing_ok=True)
                code, out = self.run_setup({}, self.answers_file(text))
                self.assertEqual(code, 1, out)
                self.assertFalse(self.profile.exists())

    def test_an_answer_no_capability_asks_refuses_before_writing(self):
        text = "identity: {name: A, email: a@b.invalid}\nanswers: {tracker.sytem: x}\n"
        code, out = self.run_setup({}, self.answers_file(text))
        self.assertEqual(code, 1, out)
        self.assertFalse(self.profile.exists())
        self.assertIn("tracker.sytem", out)


class ReRun(Fixture):
    """re-running on an existing profile writes nothing without
    confirmation."""

    def setUp(self):
        super().setUp()
        self.run_setup()
        self.before = self.profile.read_bytes()
        self.consented.clear()

    def test_a_change_not_confirmed_writes_nothing(self):
        code, out = self.run_setup({**TYPED, "tracker.system": "Another tracker."}, confirm=False)
        self.assertEqual(code, 1, out)
        self.assertEqual(self.profile.read_bytes(), self.before)
        self.assertEqual(len(self.confirms), 1)
        self.assertIn("+  tracker.system: Another tracker.", self.confirms[0])

    def test_a_confirmed_change_is_written(self):
        code, out = self.run_setup({**TYPED, "tracker.system": "Another tracker."})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.data()["answers"]["tracker.system"], "Another tracker.")

    def test_no_change_asks_nothing_and_writes_nothing(self):
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.confirms, [])
        self.assertEqual(self.profile.read_bytes(), self.before)

    def test_a_blank_answer_keeps_the_current_one(self):
        code, out = self.run_setup({"tracker.system": ""})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.data()["answers"], {"tracker.system": SYSTEM})
        self.assertEqual(self.profile.read_bytes(), self.before)

    def test_an_existing_lock_is_not_consented_again(self):
        self.run_setup({**TYPED, "tracker.system": "Another tracker."})
        self.assertEqual(self.consented, [])


class PostCreate(Fixture):
    """A step list after the profile is written, so a post-create check adds a step rather
    than reworking setup."""

    def test_each_step_runs_once_after_a_write(self):
        seen = []
        with mock.patch.object(setup_profile, "POST_CREATE",
                               (lambda folder: seen.append(self.profile.exists()),)):
            self.run_setup()
            self.assertEqual(seen, [True])
            self.run_setup()
        self.assertEqual(seen, [True], "a run that wrote nothing ran the steps again")


if __name__ == "__main__":
    unittest.main()
