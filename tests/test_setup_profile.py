################################################################################
# File: test_setup_profile.py
# Path: {PROJECT_ROOT}/tests/test_setup_profile.py
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-15
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
