################################################################################
# File: test_setup_profile.py
# Path: {PROJECT_ROOT}/tests/test_setup_profile.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-16
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
import importlib.util
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
TYPED = {"identity.name": "Example Person", "identity.email": "person@acme.example",
         "source.repo": "acme-profile", "source.key": "acm", "source.owner": "acme-owner",
         "personal": "acme-private\nacme-notes", "profile_name": "acme-profile-name",
         "leak_extra": "internal.acme.example",
         "not_onboarded": "acme-archived: Retired project.",
         "tracker.system": SYSTEM}
# The same values as an --answers file.
LEAK_FILE = ("source: {repo: acme-profile, key: acm, owner: acme-owner}\n"
             "personal: [acme-private, acme-notes]\nprofile_name: acme-profile-name\n"
             "leak_extra: [internal.acme.example]\n"
             "not_onboarded: {acme-archived: Retired project.}\n")


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
        self.asked: dict = {}
        self.printed_before: dict = {}
        self.addCleanup(sync.set_stamp_source, MANIFEST)
        # The machine's own git identity must not decide a test.
        patcher = mock.patch.object(setup_profile, "git_config", return_value="", create=True)
        self.git_config = patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def profile(self) -> Path:
        return self.folder / "profile.yaml"

    def run_setup(self, typed: dict | None = None, answers_file: Path | None = None,
                  confirm: bool = True) -> tuple[int, str]:
        typed = TYPED if typed is None else typed

        def say_yes(diff: str) -> bool:
            self.confirms.append(diff)
            return confirm

        out = io.StringIO()

        def ask(key: str, prompt: str, current: str | None) -> str:
            self.asked[key] = (prompt, current)
            self.printed_before.setdefault(key, out.getvalue())
            value = typed.get(key, "")
            # A list is one answer per time the question is asked, the last one repeating.
            if isinstance(value, list):
                value = value.pop(0) if len(value) > 1 else value[0]
            return value

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
                                            "email": "person@acme.example"})
        self.assertEqual(data["answers"], {"tracker.system": SYSTEM})
        profile = sync.load_profile(self.folder)
        for name, cfg in profile["targets"].items():
            with self.subTest(target=name):
                plan = sync.build_plan(name, cfg or {}, profile["defaults"], "abc1234", profile,
                                       profile_dir=self.folder)
                self.assertIn("AGENTS.md", plan)
        self.assertIn("[OK] render:", out)

    def test_a_fresh_profile_reaches_consent_with_the_core_gates(self):
        """Intent: the core ships gates, so a profile made from it alone is put to consent
        and ends with the lock written."""
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.consented, [self.folder])
        self.assertTrue((self.folder / consent.LOCK_NAME).is_file())
        self.assertNotIn("consent was skipped", out)

    def test_no_known_gates_prints_a_skip_line_and_carries_on(self):
        """Intent: skipping consent is never silent."""
        with mock.patch.object(consent, "known_gates", return_value=[]):
            code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.consented, [])
        self.assertIn("[WARN] no push gates are known, so consent was skipped: "
                      "add gates under seeds/githooks/gates/", out)
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

    def test_a_folder_holding_only_git_and_core_is_accepted(self):
        """Intent: a new repository with a vendored core is still a new profile folder."""
        (self.folder / ".git").mkdir(parents=True)
        (self.folder / "core").mkdir()
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        self.assertTrue(self.profile.is_file())

    def test_a_folder_holding_git_and_another_file_still_refuses(self):
        """Intent: only .git and core are ignored; any other entry is the operator's."""
        (self.folder / ".git").mkdir(parents=True)
        (self.folder / "README.md").write_text("mine", encoding="utf-8")
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


class ConsoleAsk(unittest.TestCase):
    """The console prompt: a free-text answer ends at an empty line, a one-line field at
    its first line."""

    def ask(self, key: str, lines: list, current: str | None = None) -> str:
        with mock.patch("builtins.input", side_effect=lines), \
                contextlib.redirect_stdout(io.StringIO()):
            return setup_profile.console_ask(key, "A question.", current)

    def test_a_multi_line_answer_ends_at_an_empty_line(self):
        self.assertEqual(self.ask("tracker.body", ["Impact first.", "Then Problem.", "", "x"]),
                         "Impact first.\nThen Problem.")

    def test_a_single_line_answer_still_works(self):
        self.assertEqual(self.ask("tracker.system", ["One line.", ""]), "One line.")

    def test_an_empty_first_line_is_a_blank_answer(self):
        self.assertEqual(self.ask("tracker.system", [""]), "")

    def test_a_one_line_field_takes_its_first_line_only(self):
        """Intent: a name or an email is one line, so it needs no empty line after it."""
        self.assertEqual(self.ask("identity.name", ["Dev Example"]), "Dev Example")
        self.assertEqual(self.ask("source.repo", ["acme-profile"]), "acme-profile")

    def test_closed_input_after_some_lines_ends_the_answer_and_before_any_refuses(self):
        self.assertEqual(self.ask("tracker.body", ["Only this.", EOFError()]), "Only this.")
        with self.assertRaises(setup_profile.SetupError):
            self.ask("tracker.body", [EOFError()])

    def test_a_multi_line_prompt_says_to_press_enter_again_once_the_first_line_is_in(self):
        """Intent: `n/a` shows an empty `>` that waits for a second Enter. After the first
        line, and not before it, the prompt says so."""
        out, hinted = io.StringIO(), []

        def typed(_prompt):
            hinted.append("Press Enter again to finish" in out.getvalue())
            return ["n/a", ""][len(hinted) - 1]

        with mock.patch("builtins.input", side_effect=typed), contextlib.redirect_stdout(out):
            self.assertEqual(setup_profile.console_ask("personal", "A question.", None), "n/a")
        self.assertEqual(hinted, [False, True])

    def test_a_blank_first_line_and_a_one_line_field_get_no_hint(self):
        for key, lines in (("personal", [""]), ("source.repo", ["acme-profile"])):
            with self.subTest(key=key):
                out = io.StringIO()
                with mock.patch("builtins.input", side_effect=lines), \
                        contextlib.redirect_stdout(out):
                    setup_profile.console_ask(key, "A question.", None)
                self.assertNotIn("Press Enter again", out.getvalue())

    def test_a_current_value_that_ends_in_a_full_stop_is_not_given_a_second(self):
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=[""]), contextlib.redirect_stdout(out):
            setup_profile.console_ask("not_onboarded", "A question.", "old: Retired project.")
        self.assertIn("Current: old: Retired project. Enter keeps it.", out.getvalue())
        self.assertNotIn("..", out.getvalue())

    def test_the_prompt_says_how_a_multi_line_answer_ends(self):
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=[""]), contextlib.redirect_stdout(out):
            setup_profile.console_ask("tracker.body", "A question.", None)
        self.assertIn("empty line", out.getvalue())


class Questions(Fixture):
    """The question text, and the n/a answer."""

    def prompt(self, key: str) -> str:
        self.run_setup()
        return self.asked[key][0]

    def test_operations_lists_the_operations(self):
        operations = yaml.safe_load(
            (sync.ROOT / "capabilities" / "tracker.yaml").read_text(encoding="utf-8"))["operations"]
        prompt = self.prompt("tracker.operations")
        for name in operations:
            with self.subTest(operation=name):
                self.assertIn(name, prompt)

    def test_system_says_any_system_works_and_what_the_answer_feeds(self):
        prompt = self.prompt("tracker.system").lower()
        self.assertIn("any system works", prompt)
        self.assertIn("nothing is built", prompt)
        self.assertIn("until a skill is bound", prompt)

    def test_every_answer_prompt_offers_n_a(self):
        self.run_setup()
        for key, (prompt, _) in self.asked.items():
            if key.startswith("tracker."):
                with self.subTest(key=key):
                    self.assertIn("n/a", prompt)

    def test_n_a_is_accepted_and_stored_as_n_a(self):
        code, out = self.run_setup({**TYPED, "tracker.system": "n/a", "tracker.relations": "n/a"})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.data()["answers"], {"tracker.system": "n/a",
                                                  "tracker.relations": "n/a"})

    def test_n_a_for_the_system_declares_no_system(self):
        """Intent: no system is nothing to build, so nothing is listed as unbuilt."""
        _, out = self.run_setup({**TYPED, "tracker.system": "n/a"})
        self.assertNotIn("unbuilt", out)
        self.assertNotIn("build:", out)


class Identity(Fixture):
    GIT = {"user.name": "Git Person", "user.email": "git.person@acme.example"}

    def test_the_git_identity_is_the_default(self):
        self.git_config.side_effect = lambda key, folder=None: self.GIT.get(key, "")
        typed = {k: v for k, v in TYPED.items() if not k.startswith("identity.")}
        code, out = self.run_setup(typed)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.asked["identity.name"][1], "Git Person")
        self.assertEqual(self.asked["identity.email"][1], "git.person@acme.example")
        self.assertEqual(self.data()["identity"], {"name": "Git Person",
                                                   "email": "git.person@acme.example"})

    def test_what_is_typed_wins_over_the_git_identity(self):
        self.git_config.side_effect = lambda key, folder=None: self.GIT.get(key, "")
        self.run_setup()
        self.assertEqual(self.data()["identity"]["name"], "Example Person")

    def test_with_no_git_identity_the_example_is_not_kept(self):
        """Intent: a blank answer with nothing to default to keeps the example email, which is
        then refused rather than written."""
        typed = {k: v for k, v in TYPED.items() if not k.startswith("identity.")}
        code, out = self.run_setup(typed)
        self.assertEqual(code, 1, out)
        self.assertFalse(self.profile.exists())

    def test_an_example_invalid_email_is_refused(self):
        for source in ("typed", "file"):
            with self.subTest(source=source):
                self.profile.unlink(missing_ok=True)
                if source == "typed":
                    code, out = self.run_setup({**TYPED, "identity.email": "me@acme.example.invalid"})
                else:
                    text = "identity: {name: A, email: me@example.invalid}\n" + LEAK_FILE
                    code, out = self.run_setup({}, self.answers_file(text))
                self.assertEqual(code, 1, out)
                self.assertFalse(self.profile.exists())
                self.assertIn("example.invalid", out)


class IdentityAtThePrompt(Fixture):
    """With no git identity, setup says so first, and an example email is refused where it
    is typed, not after every other answer is thrown away."""

    def test_no_git_email_is_said_before_the_identity_questions(self):
        typed = {**TYPED}
        self.run_setup(typed)
        before = self.printed_before["identity.name"]
        self.assertIn("git config user.email", before)
        self.assertIn("not set", before)

    def test_a_git_email_means_nothing_is_said(self):
        self.git_config.side_effect = lambda key, folder=None: {
            "user.name": "Git Person", "user.email": "git.person@acme.example"}.get(key, "")
        self.run_setup()
        self.assertNotIn("git config user.email", self.printed_before["identity.name"])

    def test_an_example_email_is_asked_again_at_the_prompt(self):
        code, out = self.run_setup({**TYPED, "identity.email": ["me@example.invalid",
                                                                "me@acme.example"]})
        self.assertEqual(code, 0, out)
        self.assertIn("example.invalid", out)
        self.assertEqual(self.data()["identity"]["email"], "me@acme.example")

    def test_a_blank_answer_that_would_keep_the_example_email_is_asked_again(self):
        code, out = self.run_setup({**TYPED, "identity.email": ["", "me@acme.example"]})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.data()["identity"]["email"], "me@acme.example")

    def test_setup_stops_after_three_refused_emails(self):
        code, out = self.run_setup({**TYPED, "identity.email": "me@example.invalid"})
        self.assertEqual(code, 1, out)
        self.assertFalse(self.profile.exists())


class SourceValidation(Fixture):
    """source.owner and source.repo are letters, digits, - _ and .; source.key is 1 to 12
    lowercase letters and digits. A value with a space breaks owner/repo."""

    BAD = {"source.owner": ["Tester McFacyTest", "a/b", "own?er"],
           "source.repo": ["acme profile", "acme/profile"],
           "source.key": ["Acm", "has space", "abcdefghijklm", "a-b"]}

    def test_a_bad_value_is_asked_again_at_the_prompt(self):
        for field, values in self.BAD.items():
            for bad in values:
                with self.subTest(field=field, bad=bad):
                    self.setUp()
                    code, out = self.run_setup({**TYPED, field: [bad, TYPED[field]]})
                    self.assertEqual(code, 0, out)
                    self.assertIn(field, out)
                    self.assertEqual(self.data()["source"][field.split(".")[1]], TYPED[field])

    def test_the_edges_of_what_is_accepted(self):
        typed = {**TYPED, "source.owner": "Acme_Owner-1.x", "source.repo": "A.b_c-9",
                 "source.key": "abcdefghijkl"}
        code, out = self.run_setup(typed)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.data()["source"], {"repo": "A.b_c-9", "key": "abcdefghijkl",
                                                 "owner": "Acme_Owner-1.x"})

    def test_a_value_still_wrong_after_three_asks_refuses_and_writes_nothing(self):
        code, out = self.run_setup({**TYPED, "source.owner": "Tester McFacyTest"})
        self.assertEqual(code, 1, out)
        self.assertFalse(self.profile.exists())

    def test_an_answers_file_with_a_bad_value_refuses_at_once(self):
        for field, bad in (("owner", "Tester McFacyTest"), ("repo", "acme profile"),
                           ("key", "ACM")):
            with self.subTest(field=field):
                source = {"repo": "acme-profile", "key": "acm", "owner": "acme-owner"}
                source[field] = bad
                text = ("identity: {name: A, email: a@acme.example}\n"
                        f"source: {{repo: '{source['repo']}', key: '{source['key']}', "
                        f"owner: '{source['owner']}'}}\n"
                        + LEAK_FILE.split("\n", 1)[1])
                code, out = self.run_setup({}, self.answers_file(text))
                self.assertEqual(code, 1, out)
                self.assertFalse(self.profile.exists())
                self.assertIn(f"source.{field}", out)


class ExampleWarning(Fixture):
    """A shipped example value that will be refused is not offered as one Enter keeps."""

    def test_an_example_source_or_leak_value_is_flagged_and_not_kept_by_enter(self):
        for key in ("source.repo", "source.key", "source.owner", "personal", "profile_name",
                    "leak_extra", "not_onboarded"):
            with self.subTest(key=key):
                self.run_setup({k: v for k, v in TYPED.items() if k != key})
                prompt, current = self.asked[key]
                self.assertIn("shipped example", prompt)
                self.assertIn("refused", prompt)
                self.assertIsNone(current)

    def test_the_example_email_default_is_flagged(self):
        self.run_setup({k: v for k, v in TYPED.items() if k != "identity.email"})
        prompt, current = self.asked["identity.email"]
        self.assertIn("shipped example", prompt)
        self.assertIsNone(current)

    def test_a_value_of_your_own_is_offered_as_one_enter_keeps(self):
        self.run_setup()
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        prompt, current = self.asked["source.repo"]
        self.assertEqual(current, "acme-profile")
        self.assertNotIn("shipped example", prompt)


class ExampleValues(Fixture):
    """Source and leak-gate values are asked, and an example value never survives."""

    ASKED = ("source.repo", "source.key", "source.owner", "personal", "profile_name",
             "leak_extra", "not_onboarded")

    def test_they_are_asked_after_identity_and_written(self):
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        keys = list(self.asked)
        for key in self.ASKED:
            self.assertIn(key, keys)
        self.assertLess(keys.index("identity.email"), keys.index("source.repo"))
        data = self.data()
        self.assertEqual(data["source"], {"repo": "acme-profile", "key": "acm",
                                          "owner": "acme-owner"})
        self.assertEqual(data["personal"], ["acme-private", "acme-notes"])
        self.assertEqual(data["profile_name"], "acme-profile-name")
        self.assertEqual(data["leak_extra"], ["internal.acme.example"])
        self.assertEqual(data["not_onboarded"], {"acme-archived": "Retired project."})

    def test_a_blank_answer_that_keeps_an_example_value_is_refused(self):
        for key in self.ASKED:
            with self.subTest(key=key):
                self.profile.unlink(missing_ok=True)
                code, out = self.run_setup({k: v for k, v in TYPED.items() if k != key})
                self.assertEqual(code, 1, out)
                self.assertFalse(self.profile.exists())
                self.assertIn(key, out)
                self.assertIn("example", out)

    def test_an_answers_file_that_leaves_an_example_value_is_refused(self):
        text = ("identity: {name: A, email: a@acme.example}\n"
                "source: {repo: acme-profile, key: acm}\n")
        code, out = self.run_setup({}, self.answers_file(text))
        self.assertEqual(code, 1, out)
        self.assertFalse(self.profile.exists())
        self.assertIn("source.owner", out)

    def test_n_a_means_none_for_the_leak_inputs(self):
        typed = {**TYPED, "personal": "n/a", "profile_name": "n/a", "leak_extra": "n/a",
                 "not_onboarded": "n/a"}
        code, out = self.run_setup(typed)
        self.assertEqual(code, 0, out)
        data = self.data()
        self.assertEqual((data["personal"], data["profile_name"], data["leak_extra"],
                          data["not_onboarded"]), ([], "", [], {}))

    def test_n_a_is_no_value_for_the_source(self):
        code, out = self.run_setup({**TYPED, "source.repo": "n/a"})
        self.assertEqual(code, 1, out)
        self.assertFalse(self.profile.exists())

    def test_a_rerun_with_the_same_values_changes_nothing(self):
        self.run_setup()
        before = self.profile.read_bytes()
        code, out = self.run_setup()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.confirms, [])
        self.assertEqual(self.profile.read_bytes(), before)

    def test_the_explaining_comments_of_the_source_block_survive(self):
        self.run_setup()
        self.assertIn("# The GitHub owner of every repository",
                      self.profile.read_text(encoding="utf-8"))


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

    GOOD = ("identity: {name: Example Person, email: person@acme.example}\n"
            f"answers: {{tracker.system: '{SYSTEM}'}}\n" + LEAK_FILE)

    def test_it_writes_everything_but_features(self):
        code, out = self.run_setup({}, self.answers_file(self.GOOD))
        self.assertEqual(self.data()["answers"], {"tracker.system": SYSTEM})
        self.assertEqual(self.data()["identity"]["name"], "Example Person")
        self.assertEqual(self.data()["features"], {})
        self.assertFalse((self.folder / "profile.lock").exists())
        self.assertEqual(self.consented, [])
        # The core ships gates, so the render cannot be checked until consent is given. 3
        # is "written, render not checked", and the message names the consent command.
        self.assertEqual(code, 3, out)
        self.assertIn("no profile.lock", out)
        self.assertIn("consent.py --profile . --init", out)

    def test_a_file_that_sets_features_or_anything_else_refuses(self):
        """Intent: features are set only through the consent command."""
        for text in (self.GOOD + "features: {gates: {}}\n", self.GOOD + "targets: {}\n",
                     "- not a mapping\n",
                     "identity: {name: A, email: a@acme.example, signing: x}\n",
                     "identity: {name: A, email: a@acme.example}\nanswers: [tracker.system]\n"):
            with self.subTest(text=text):
                self.profile.unlink(missing_ok=True)
                code, out = self.run_setup({}, self.answers_file(text))
                self.assertEqual(code, 1, out)
                self.assertFalse(self.profile.exists())

    def test_an_answer_no_capability_asks_refuses_before_writing(self):
        text = "identity: {name: A, email: a@acme.example}\nanswers: {tracker.sytem: x}\n" + LEAK_FILE
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


BLOCK = ("# >>> ai-toolbox hooks switch >>>\n"
         "export AI_TOOLBOX_HOOKS=off\n"
         "# <<< ai-toolbox hooks switch <<<\n")


class HooksFixture(unittest.TestCase):
    """Intent: the per-machine hooks switch. Every writer is a fake or points into
    a temporary folder; the real registry and home folder are never touched."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.profile_file = self.home / ".profile"
        self.registry: list = []
        self.broadcasts: list = []
        self.asked: list = []

    def run_hooks(self, state: str, *, platform: str = "linux", shell: str = "/bin/bash",
                  answer: bool = True, broadcast=None) -> tuple[int, str]:
        def confirm(text: str) -> bool:
            self.asked.append(text)
            return answer

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = setup_profile.run_hooks(
                state, confirm=confirm, platform=platform, home=self.home, shell=shell,
                registry=lambda name, value: self.registry.append((name, value)),
                broadcast=broadcast or (lambda: self.broadcasts.append("Environment")))
        return code, out.getvalue()

    def profile_bytes(self) -> bytes | None:
        return self.profile_file.read_bytes() if self.profile_file.exists() else None


class HooksWindows(HooksFixture):
    def test_off_writes_the_variable_and_broadcasts_after_a_yes(self):
        code, out = self.run_hooks("off", platform="win32")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.registry, [(setup_profile.HOOKS_VARIABLE, "off")])
        self.assertEqual(self.broadcasts, ["Environment"])

    def test_on_deletes_the_variable(self):
        code, out = self.run_hooks("on", platform="win32")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.registry, [(setup_profile.HOOKS_VARIABLE, None)])

    def test_nothing_is_written_without_a_yes(self):
        for state in ("off", "on"):
            with self.subTest(state=state):
                code, _ = self.run_hooks(state, platform="win32", answer=False)
                self.assertEqual(code, 1)
        self.assertEqual(self.registry, [])
        self.assertEqual(self.broadcasts, [])

    def test_the_question_names_the_variable_and_the_place(self):
        self.run_hooks("off", platform="win32")
        self.assertIn("AI_TOOLBOX_HOOKS", self.asked[0])
        self.assertIn(r"HKCU\Environment", self.asked[0])

    def test_a_failed_broadcast_warns_and_the_write_stands(self):
        def broken():
            raise OSError("no window")

        code, out = self.run_hooks("off", platform="win32", broadcast=broken)
        self.assertEqual(code, 0)
        self.assertIn("[WARN]", out)
        self.assertEqual(self.registry, [(setup_profile.HOOKS_VARIABLE, "off")])

    def test_the_variable_name_is_the_library_constant(self):
        spec = importlib.util.spec_from_file_location(
            "hookio", sync.ROOT / "hooks" / "lib" / "hookio.py")
        hookio = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hookio)
        self.assertEqual(setup_profile.HOOKS_VARIABLE, hookio.OFF_VARIABLE)


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, present: bool = True):
        self.calls: list = []
        self.present = present

    def OpenKey(self, hive, path, reserved, access):  # noqa: N802 - the winreg name
        self.calls.append(("open", hive, path, access))
        return contextlib.nullcontext("key")

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.calls.append(("set", name, kind, value))

    def DeleteValue(self, key, name):  # noqa: N802
        self.calls.append(("delete", name))
        if not self.present:
            raise FileNotFoundError(name)


class HooksRegistryWriter(unittest.TestCase):
    def test_off_sets_a_string_value_under_hkcu_environment(self):
        fake = FakeWinreg()
        setup_profile.write_registry("AI_TOOLBOX_HOOKS", "off", winreg_module=fake)
        self.assertEqual(fake.calls, [("open", "HKCU", "Environment", 2),
                                      ("set", "AI_TOOLBOX_HOOKS", 1, "off")])

    def test_on_deletes_the_value_and_a_missing_value_is_fine(self):
        for present in (True, False):
            with self.subTest(present=present):
                fake = FakeWinreg(present=present)
                setup_profile.write_registry("AI_TOOLBOX_HOOKS", None, winreg_module=fake)
                self.assertEqual(fake.calls[-1], ("delete", "AI_TOOLBOX_HOOKS"))

    def test_the_broadcast_sends_setting_change_with_environment(self):
        calls: list = []

        class User32:
            def SendMessageTimeoutW(self, *args):  # noqa: N802
                calls.append(args)
                return 1

        setup_profile.broadcast_environment(user32=User32())
        hwnd, message, wparam, lparam, flags, timeout, _result = calls[0]
        self.assertEqual((hwnd, message, wparam, lparam, timeout),
                         (0xFFFF, 0x001A, 0, "Environment", 5000))


class HooksPosix(HooksFixture):
    def test_off_creates_the_profile_with_the_block_after_a_yes(self):
        code, out = self.run_hooks("off")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.profile_bytes(), BLOCK.encode())
        self.assertEqual(self.registry, [])

    def test_off_appends_to_an_existing_profile(self):
        self.profile_file.write_bytes(b"export A=1\n")
        self.run_hooks("off")
        self.assertEqual(self.profile_bytes(), b"export A=1\n" + BLOCK.encode())

    def test_off_twice_leaves_one_block(self):
        self.run_hooks("off")
        once = self.profile_bytes()
        code, _ = self.run_hooks("off")
        self.assertEqual(code, 0)
        self.assertEqual(self.profile_bytes(), once)
        self.assertEqual(len(self.asked), 1, "a run with nothing to change asked anyway")

    def test_on_removes_the_block_and_the_rest_is_byte_identical(self):
        original = b"# mine\r\nexport A=1\n\n  alias x='y'\n"
        self.profile_file.write_bytes(original)
        self.run_hooks("off")
        self.assertNotEqual(self.profile_bytes(), original)
        code, _ = self.run_hooks("on")
        self.assertEqual(code, 0)
        self.assertEqual(self.profile_bytes(), original)

    def test_on_with_no_block_changes_nothing(self):
        self.profile_file.write_bytes(b"export A=1\n")
        code, _ = self.run_hooks("on")
        self.assertEqual(code, 0)
        self.assertEqual(self.profile_bytes(), b"export A=1\n")
        self.assertEqual(self.asked, [])

    def test_nothing_is_written_without_a_yes(self):
        code, _ = self.run_hooks("off", answer=False)
        self.assertEqual(code, 1)
        self.assertIsNone(self.profile_bytes())
        self.profile_file.write_bytes(BLOCK.encode())
        code, _ = self.run_hooks("on", answer=False)
        self.assertEqual(code, 1)
        self.assertEqual(self.profile_bytes(), BLOCK.encode())

    def test_the_question_names_the_variable_and_the_file(self):
        self.run_hooks("off")
        self.assertIn("AI_TOOLBOX_HOOKS", self.asked[0])
        self.assertIn(str(self.profile_file), self.asked[0])


class HooksRefusals(HooksFixture):
    def assert_refused(self, state: str, expect: str, **kwargs) -> None:
        before = self.profile_bytes()
        code, out = self.run_hooks(state, **kwargs)
        self.assertEqual(code, 1, out)
        self.assertIn(expect, out)
        self.assertEqual(self.asked, [], "it asked before refusing")
        self.assertEqual(self.profile_bytes(), before)

    def test_a_bash_profile_that_does_not_source_profile_refuses(self):
        for name in (".bash_profile", ".bash_login"):
            for state in ("off", "on"):
                with self.subTest(file=name, state=state):
                    (self.home / name).write_text("export B=1\n", encoding="utf-8")
                    self.assert_refused(state, name)
                    self.assertIn("export AI_TOOLBOX_HOOKS=off", self.run_hooks(state)[1])
                    (self.home / name).unlink()

    def test_a_bash_profile_that_sources_profile_does_not_refuse(self):
        for line in (". ~/.profile", '. "$HOME/.profile"', "source ~/.profile",
                     'source "${HOME}/.profile"', "if [ -f ~/.profile ]; then . ~/.profile; fi",
                     "  . $HOME/.profile"):
            with self.subTest(line=line):
                (self.home / ".bash_profile").write_text(f"export B=1\n{line}\n",
                                                         encoding="utf-8")
                code, out = self.run_hooks("off")
                self.assertEqual(code, 0, out)
                self.profile_file.unlink()

    def test_a_commented_out_source_line_does_not_count(self):
        (self.home / ".bash_login").write_text("# . ~/.profile\n", encoding="utf-8")
        self.assert_refused("off", ".bash_login")

    def test_a_zsh_login_shell_refuses(self):
        self.assert_refused("off", "zsh", shell="/usr/bin/zsh")
        self.assert_refused("on", "zsh", shell="/bin/zsh")

    def test_the_refusal_names_the_line_to_add_by_hand(self):
        _, out = self.run_hooks("off", shell="/bin/zsh")
        self.assertIn("export AI_TOOLBOX_HOOKS=off", out)


class HooksMain(unittest.TestCase):
    def test_hooks_does_only_the_machine_switch_and_needs_no_profile(self):
        with mock.patch.object(setup_profile, "run_hooks", return_value=0) as hooks, \
                mock.patch.object(setup_profile, "run_setup") as setup:
            code = setup_profile.main(["--hooks", "off"])
        self.assertEqual(code, 0)
        self.assertEqual(hooks.call_args.args, ("off",))
        setup.assert_not_called()

    def test_a_profile_alongside_hooks_is_ignored(self):
        with mock.patch.object(setup_profile, "run_hooks", return_value=0), \
                mock.patch.object(setup_profile, "run_setup") as setup:
            setup_profile.main(["--profile", "somewhere", "--hooks", "on"])
        setup.assert_not_called()

    def test_without_hooks_a_profile_is_still_required(self):
        with self.assertRaises(SystemExit) as raised, \
                contextlib.redirect_stderr(io.StringIO()):
            setup_profile.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_answers_with_hooks_is_an_error(self):
        with self.assertRaises(SystemExit) as raised, \
                contextlib.redirect_stderr(io.StringIO()):
            setup_profile.main(["--hooks", "off", "--answers", "a.yaml"])
        self.assertEqual(raised.exception.code, 2)

    def test_hooks_takes_off_or_on_only(self):
        with self.assertRaises(SystemExit) as raised, \
                contextlib.redirect_stderr(io.StringIO()):
            setup_profile.main(["--hooks", "maybe"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
