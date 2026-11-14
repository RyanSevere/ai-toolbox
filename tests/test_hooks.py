#!/usr/bin/env python3
################################################################################
# File: test_hooks.py
# Path: {PROJECT_ROOT}/tests/test_hooks.py
# Created by: Ryan Severe
# Created: 2026-09-26
# Last Updated: 2026-11-13
# Description: Tests for the editor safety hooks, hooks/no-secret-defaults,
#              and hooks/no-shell-file-edits, and the shared
#              runtime library hooks/lib/hookio.py. Per hook: a violation it must
#              catch, a near-miss it must allow, and malformed input it must
#              not crash on. A guard that silently stops matching looks the
#              same as one with nothing to catch. Stdlib only.
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

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
EXERCISES = ["hooks/**"]  # the hooks' config files are data coverage cannot see


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stdin_of(data: str | bytes) -> io.TextIOWrapper:
    """Real stdin: bytes under a text layer that decodes with the Windows locale code page."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252")


secrets = load("no_secret_defaults", HOOKS / "no-secret-defaults" / "check.py")
shell = load("no_shell_file_edits", HOOKS / "no-shell-file-edits" / "hook.py")


class SecretDefaults(unittest.TestCase):
    def scan(self, suffix: str, content: str | bytes) -> list:
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        handle.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        handle.close()
        path = Path(handle.name)
        self.addCleanup(path.unlink)
        return secrets.scan(path)

    def test_violations_are_caught(self):
        for suffix, line in (
            (".ts", 'const s = process.env.JWT_SECRET ?? "dev-secret";'),
            (".js", "const k = process.env.API_KEY || 'changeme';"),
            (".py", "password = os.getenv('DB_PASSWORD', '')"),
            (".py", 'secret_key: str = "change-me-in-production"'),
            (".yml", "      - JWT_SECRET=${JWT_SECRET:-changeme}"),
            (".yml", "      - APP_API_KEY=${APP_API_KEY:-}"),
            (".yml", "      - OMBI_API_KEY=${OMBI_API_KEY-}"),
        ):
            with self.subTest(line=line):
                self.assertEqual(len(self.scan(suffix, line + "\n")), 1)

    def test_near_misses_are_allowed(self):
        for suffix, line in (
            (".yml", "      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET is required}"),
            (".py", "password = os.getenv('DB_PASSWORD')"),
            (".py", "log_level = os.getenv('LOG_LEVEL', 'INFO')"),
            (".ts", 'const s = process.env.JWT_SECRET ?? "x"; // no-secret-defaults: allow'),
        ):
            with self.subTest(line=line):
                self.assertEqual(self.scan(suffix, line + "\n"), [])

    def test_malformed_input_does_not_crash(self):
        self.assertEqual(self.scan(".py", b"\xff\xfe\x00\x81 not utf-8\n"), [])
        self.assertEqual(secrets.scan(Path(tempfile.gettempdir()) / "does-not-exist.py"), [])


class ShellFileEdits(unittest.TestCase):
    def test_violations_are_caught(self):
        for command in (
            "sed -i 's/a/b/' src/app.py",
            "sudo sed -n -i.bak 's/a/b/' /etc/hosts",
            "echo x > src/app.py",
            "cat notes | tee -a README.md",
            "ls; perl -pi -e 's/a/b/' x.pl",
            "sed -Ei 's/a/b/' src/app.py",
            "sed --in-place 's/a/b/' src/app.py",
            # PowerShell writers.
            "Set-Content src/app.py x",
            "Set-Content -Path src/app.py -Value x",
            "'x' | Add-Content README.md",
            "Get-Process | Out-File list.txt",
            "Get-Process | Out-File -FilePath list.txt",
            "New-Item f.py -Value x",
            "New-Item -Path f.py -ItemType File -Value x",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(shell.offending(command))

    def test_near_misses_are_allowed(self):
        for command in (
            "sed -n 1p src/app.py",
            "npm test 2>&1",
            "echo x > /dev/null",
            "ls > /tmp/listing",
            "pytest > run.log",
            "grep -i secret app.py",
            # PowerShell. $null is PowerShell's /dev/null.
            "git fetch > $null",
            "Get-Content f.py",
            "New-Item -ItemType Directory scratch",
            "pytest | Out-File run.log",
            "Set-Content -Path run.log -Value x",
            "Get-Process | Out-Null",
        ):
            with self.subTest(command=command):
                self.assertIsNone(shell.offending(command))

    def run_main(self, stdin: str | bytes) -> dict:
        out = io.StringIO()
        with mock.patch("sys.stdin", new=stdin_of(stdin)), mock.patch("sys.stdout", new=out):
            self.assertEqual(shell.main(), 0)
        return json.loads(out.getvalue())

    def test_malformed_input_denies_rather_than_allowing(self):
        self.assertEqual(self.run_main("not json")["permission"], "deny")

    def test_missing_command_is_allowed(self):
        self.assertEqual(self.run_main('{"command": null}')["permission"], "allow")

    def test_verdict_travels_through_main(self):
        self.assertEqual(self.run_main(json.dumps({"command": "sed -i x f.py"}))["permission"], "deny")

    def test_a_command_writing_the_consent_lock_is_denied(self):
        """Intent: the hook refuses a shell write to profile.lock, closing
        the scripted-forgery route. Writers the redirect check does not see are the point."""
        for command in (
            "cp forged.lock profile.lock",
            "mv x profile.lock",
            "python -c \"open('profile.lock','w').write(x)\"",
            "git status; python tools/forge.py --out profile.lock",
            "git add $(python -c \"open('profile.lock','w')\")",
            "Copy-Item x -Destination ./profile.lock",
            "git show HEAD:profile.lock > profile.lock",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(shell.offending(command))

    def test_reading_and_committing_the_consent_lock_is_allowed(self):
        """Characterisation: the lock is read, diffed, restored and committed as part of
        normal work, and the consent command itself must get through."""
        for command in (
            "git add profile.yaml profile.lock",
            "git diff profile.lock",
            "git checkout -- profile.lock",
            "cat profile.lock",
            "Get-Content profile.lock",
            "rg -n gate profile.lock",
            "python consent.py --check",
            "python consent.py --set eslint=off",
            "echo profile.locked",
        ):
            with self.subTest(command=command):
                self.assertIsNone(shell.offending(command))

    def test_a_denied_lock_write_says_only_the_consent_command_may_change_it(self):
        verdict = self.run_main(json.dumps({"command": "cp x profile.lock"}))
        self.assertEqual(verdict["permission"], "deny")
        self.assertIn("consent.py", verdict["agent_message"])
        self.assertNotIn("editing tools", verdict["agent_message"])


class HookLib(unittest.TestCase):
    """Intent: one library reads the payload as bytes with utf-8-sig, gives the
    hook a neutral payload with the model fields, writes the tool's output shape, and honours
    AI_TOOLBOX_HOOKS=off: a permission hook allows and an observer does nothing."""

    @classmethod
    def setUpClass(cls):
        cls.lib = load("hookio", HOOKS / "lib" / "hookio.py")

    SHELL = {"command": "git status", "cwd": "/repo", "model": "m", "model_id": "m-1",
             "model_params": {"effort": "high"}}

    def run_hook(self, kind: str, data: bytes, callback, env: dict | None = None):
        out = io.StringIO()
        run = self.lib.run_permission if kind == "permission" else self.lib.run_observer
        with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                mock.patch.dict(os.environ, env or {}):
            if env is None:
                os.environ.pop("AI_TOOLBOX_HOOKS", None)
            self.assertEqual(run("guard", "shell.before", callback), 0)
        return out.getvalue()

    def never(self, payload):
        raise AssertionError(f"callback ran with {payload}")

    def test_every_encoding_cursor_might_send_parses(self):
        text = json.dumps({"command": 'git commit -m "café"'}, ensure_ascii=False)
        for label, data in (("utf-8", text.encode("utf-8")),
                            ("utf-8 with BOM", text.encode("utf-8-sig")),
                            ("utf-16 with BOM", text.encode("utf-16"))):
            with self.subTest(encoding=label):
                payload, unread = self.lib.read_payload(io.BytesIO(data))
                self.assertEqual(payload, {"command": 'git commit -m "café"'})
                self.assertEqual(unread, "")

    def test_bytes_that_will_not_parse_are_described_not_guessed(self):
        payload, unread = self.lib.read_payload(io.BytesIO(b"\x00\x01 not json"))
        self.assertIsNone(payload)
        self.assertIn("bytes", unread)
        self.assertIn("\\x00\\x01", unread)

    def test_the_neutral_payload_carries_the_command_and_the_model_fields(self):
        """Intent: every Cursor payload carries model, model_id
        and model_params, and the neutral schema carries the model rather than drop it."""
        neutral = self.lib.neutral("shell.before", self.SHELL)
        self.assertEqual({k: neutral[k] for k in ("event", "command", "cwd", "model",
                                                  "model_id", "model_params")},
                         {"event": "shell.before", **self.SHELL})

    def test_a_missing_model_field_is_none_not_invented(self):
        """Intent: prescriptions - unknown is not zero; an absent model is not a default one."""
        neutral = self.lib.neutral("shell.before", {"command": "git status"})
        self.assertIsNone(neutral["model"])
        self.assertIsNone(neutral["model_id"])
        self.assertIsNone(neutral["model_params"])

    def test_a_permission_hook_writes_cursors_allow_and_deny_shapes(self):
        data = json.dumps(self.SHELL).encode()
        self.assertEqual(json.loads(self.run_hook("permission", data, lambda p: None)),
                         {"permission": "allow"})
        self.assertEqual(json.loads(self.run_hook("permission", data, lambda p: ("u", "a"))),
                         {"permission": "deny", "user_message": "u", "agent_message": "a"})

    def test_the_hook_sees_the_neutral_payload(self):
        seen = []
        self.run_hook("permission", json.dumps(self.SHELL).encode(),
                      lambda p: seen.append(p) or None)
        self.assertEqual(seen[0]["command"], "git status")
        self.assertEqual(seen[0]["event"], "shell.before")

    def test_unparseable_input_denies_a_permission_hook_naming_it(self):
        verdict = json.loads(self.run_hook("permission", b"\x00\x01 not json", self.never))
        self.assertEqual(verdict["permission"], "deny")
        self.assertIn("guard", verdict["user_message"])
        self.assertIn("\\x00\\x01", verdict["user_message"])

    def test_unparseable_input_leaves_an_observer_silent(self):
        """Intent: hooks/README.md - an observer fails open."""
        self.assertEqual(self.run_hook("observer", b"\x00\x01 not json", self.never), "")

    def test_an_observer_writes_nothing(self):
        seen = []
        self.assertEqual(self.run_hook("observer", json.dumps(self.SHELL).encode(),
                                       seen.append), "")
        self.assertEqual(seen[0]["command"], "git status")

    def test_the_off_switch_allows_a_permission_hook_without_running_it(self):
        """Intent: hooks/README.md, "The off switch" - AI_TOOLBOX_HOOKS=off, read at run time."""
        for value in ("off", "OFF", " off "):
            with self.subTest(value=value):
                verdict = self.run_hook("permission", b"\x00 not even json", self.never,
                                        {"AI_TOOLBOX_HOOKS": value})
                self.assertEqual(json.loads(verdict), {"permission": "allow"})

    def test_the_off_switch_silences_an_observer(self):
        self.assertEqual(self.run_hook("observer", json.dumps(self.SHELL).encode(), self.never,
                                       {"AI_TOOLBOX_HOOKS": "off"}), "")

    def test_any_other_value_leaves_hooks_on(self):
        """A misspelt switch must not turn a guard off."""
        for value in ("", "0", "false", "of"):
            with self.subTest(value=value):
                verdict = self.run_hook("permission", json.dumps(self.SHELL).encode(),
                                        lambda p: ("u", "a"), {"AI_TOOLBOX_HOOKS": value})
                self.assertEqual(json.loads(verdict)["permission"], "deny")


class HookTools(unittest.TestCase):
    """Intent: the adapter names the tool on the hook's command line (--tool), and the library
    reads that tool's payload shape and writes that tool's verdict shape. A permission hook
    that cannot see its command denies, naming the field; an observer is skipped."""

    @classmethod
    def setUpClass(cls):
        cls.lib = load("hookio", HOOKS / "lib" / "hookio.py")

    CLAUDE = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/repo",
              "tool_input": {"command": "git status", "description": "Show status"}}

    def run_hook(self, kind: str, payload, argv: list[str], callback):
        out, err = io.StringIO(), io.StringIO()
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        run = self.lib.run_permission if kind == "permission" else self.lib.run_observer
        with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=err), mock.patch("sys.argv", ["hook.py", *argv]), \
                mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            code = run("guard", "shell.before", callback)
        return code, out.getvalue(), err.getvalue()

    def never(self, payload):
        raise AssertionError(f"callback ran with {payload}")

    def test_a_claude_code_payload_reaches_decide_with_the_command_filled(self):
        seen = []
        self.run_hook("permission", self.CLAUDE, ["--tool", "claude"],
                      lambda p: seen.append(p) or None)
        self.assertEqual((seen[0]["command"], seen[0]["cwd"]), ("git status", "/repo"))
        self.assertEqual(seen[0]["event"], "shell.before")

    def test_a_claude_code_deny_comes_out_in_its_shape(self):
        code, out, _ = self.run_hook("permission", self.CLAUDE, ["--tool", "claude"],
                                     lambda p: ("u", "a"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "a"}})

    def test_a_claude_code_allow_is_silent(self):
        """Claude Code: exit 0 with no output defers to the normal permission flow."""
        self.assertEqual(self.run_hook("permission", self.CLAUDE, ["--tool", "claude"],
                                       lambda p: None), (0, "", ""))

    def test_a_claude_code_payload_without_a_command_denies_naming_the_field(self):
        for payload in ({"tool_input": {}}, {"cwd": "/repo"}):
            with self.subTest(payload=payload):
                code, out, _ = self.run_hook("permission", payload, ["--tool", "claude"],
                                             self.never)
                verdict = json.loads(out)["hookSpecificOutput"]
                self.assertEqual((code, verdict["permissionDecision"]), (0, "deny"))
                self.assertIn("tool_input.command", verdict["permissionDecisionReason"])

    def test_a_cursor_payload_without_a_command_denies_naming_the_field(self):
        code, out, _ = self.run_hook("permission", {"cwd": "/repo"}, ["--tool", "cursor"],
                                     self.never)
        verdict = json.loads(out)
        self.assertEqual((code, verdict["permission"]), (0, "deny"))
        self.assertIn("command", verdict["user_message"])

    def test_an_empty_string_command_is_a_command(self):
        seen = []
        self.run_hook("permission", {"tool_input": {"command": ""}}, ["--tool", "claude"],
                      lambda p: seen.append(p) or None)
        self.run_hook("permission", {"command": ""}, ["--tool", "cursor"],
                      lambda p: seen.append(p) or None)
        self.assertEqual([p["command"] for p in seen], ["", ""])

    def test_a_tool_input_that_is_not_an_object_denies(self):
        for value in ("git status", ["git status"], None, 3):
            with self.subTest(tool_input=value):
                _, out, _ = self.run_hook("permission", {"tool_input": value},
                                          ["--tool", "claude"], self.never)
                verdict = json.loads(out)["hookSpecificOutput"]
                self.assertEqual(verdict["permissionDecision"], "deny")
                self.assertIn("tool_input", verdict["permissionDecisionReason"])

    def test_an_unknown_tool_denies_a_permission_hook_naming_it(self):
        for argv in (["--tool", "emacs"], ["--tool"], ["--tool="]):
            with self.subTest(argv=argv):
                code, out, err = self.run_hook("permission", self.CLAUDE, argv, self.never)
                self.assertEqual((code, out), (2, ""))  # exit 2 blocks in every tool
                self.assertIn("guard", err)
                self.assertIn("tool", err)
        _, _, err = self.run_hook("permission", self.CLAUDE, ["--tool", "emacs"], self.never)
        self.assertIn("emacs", err)

    def test_an_unknown_tool_is_skipped_by_an_observer(self):
        self.assertEqual(self.run_hook("observer", self.CLAUDE, ["--tool", "emacs"],
                                       self.never), (0, "", ""))

    def test_an_observer_without_its_command_is_skipped(self):
        self.assertEqual(self.run_hook("observer", {"cwd": "/repo"}, ["--tool", "claude"],
                                       self.never), (0, "", ""))

    def test_the_equals_form_names_the_tool(self):
        seen = []
        self.run_hook("permission", self.CLAUDE, ["--owner", "x", "--tool=claude"],
                      lambda p: seen.append(p) or None)
        self.assertEqual(seen[0]["command"], "git status")

    def test_no_tool_argument_is_cursor(self):
        seen = []
        _, out, _ = self.run_hook("permission", {"command": "git status", "cwd": "/repo"},
                                  [], lambda p: seen.append(p) or ("u", "a"))
        self.assertEqual(seen[0]["command"], "git status")
        self.assertEqual(json.loads(out),
                         {"permission": "deny", "user_message": "u", "agent_message": "a"})

    def test_cursor_named_explicitly_is_byte_identical_to_no_tool(self):
        payload = {"command": "git status", "cwd": "/repo"}
        for verdict in (None, ("u", "a")):
            with self.subTest(verdict=verdict):
                self.assertEqual(
                    self.run_hook("permission", payload, ["--tool", "cursor"], lambda p: verdict),
                    self.run_hook("permission", payload, [], lambda p: verdict))


class HookInput(unittest.TestCase):
    """Cursor sends bytes. Tests that handed main() a str passed while both hooks denied every
    command live on Windows, 2026-10-09 - the stdin text layer decodes with the code page."""

    @classmethod
    def setUpClass(cls):
        cls.hooks = {"no-shell-file-edits": (shell, [])}

    def verdict(self, data: bytes) -> dict[str, dict]:
        results = {}
        for name, (module, argv) in self.hooks.items():
            out = io.StringIO()
            with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                    mock.patch("sys.argv", ["hook.py", *argv]):
                self.assertEqual(module.main(), 0)
            results[name] = json.loads(out.getvalue())
        return results

    def test_every_encoding_cursor_might_send_parses(self):
        payload = json.dumps({"command": 'git commit -m "café"'}, ensure_ascii=False)
        for label, data in (
            ("utf-8", payload.encode("utf-8")),
            ("utf-8 with BOM", payload.encode("utf-8-sig")),
            ("utf-16 with BOM", payload.encode("utf-16")),
        ):
            for name, result in self.verdict(data).items():
                with self.subTest(encoding=label, hook=name):
                    self.assertEqual(result["permission"], "allow", result)

    def test_unparseable_input_denies_and_describes_the_bytes(self):
        for name, result in self.verdict(b"\x00\x01 not json").items():
            with self.subTest(hook=name):
                self.assertEqual(result["permission"], "deny")
                self.assertIn("bytes", result["user_message"])
                self.assertIn("\\x00\\x01", result["user_message"])

    def test_a_json_value_that_is_not_an_object_denies(self):
        for name, result in self.verdict(b"[]").items():
            with self.subTest(hook=name):
                self.assertEqual(result["permission"], "deny")


if __name__ == "__main__":
    unittest.main(verbosity=2)
