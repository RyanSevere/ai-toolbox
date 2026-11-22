#!/usr/bin/env python3
################################################################################
# File: test_hooks.py
# Path: {PROJECT_ROOT}/tests/test_hooks.py
# Created by: Ryan Severe
# Created: 2026-09-26
# Last Updated: 2026-11-21
# Description: Tests for the editor safety hooks, hooks/no-secret-defaults,
#              hooks/no-shell-file-edits, hooks/no-destructive-shell and
#              hooks/no-generated-edits, hooks/session-start,
#              hooks/write-observer, hooks/response-check,
#              hooks/title-prefix, and the
#              shared runtime library hooks/lib/hookio.py. Per hook: a violation it must
#              catch, a near-miss it must allow, and malformed input it must
#              not crash on. A guard that silently stops matching looks the
#              same as one with nothing to catch. Stdlib and PyYAML only.
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
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

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

    def run_hook(self, kind: str, payload, argv: list[str], callback, event: str = "shell.before"):
        out, err = io.StringIO(), io.StringIO()
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        run = self.lib.run_permission if kind == "permission" else self.lib.run_observer
        with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=err), mock.patch("sys.argv", ["hook.py", *argv]), \
                mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            code = run("guard", event, callback)
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

    WRITE = "file.write.before"
    # Claude Code documents tool_input.file_path for Write and Edit, absolute. Cursor's key is
    # mapped the same way until a capture on a real host says otherwise (hooks/README.md).
    CLAUDE_WRITE = {"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": "/repo",
                    "tool_input": {"file_path": "/repo/AGENTS.md", "content": "x"}}
    CLAUDE_EDIT = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": "/repo",
                   "tool_input": {"file_path": "/repo/AGENTS.md", "old_string": "a",
                                  "new_string": "b"}}
    CURSOR_WRITE = {"hook_event_name": "preToolUse", "tool_name": "Write", "cwd": "/repo",
                    "tool_input": {"file_path": "/repo/AGENTS.md", "contents": "x"}}

    def test_a_file_write_payload_reaches_decide_with_the_path_and_cwd_filled(self):
        for tool, payload in (("claude", self.CLAUDE_WRITE), ("claude", self.CLAUDE_EDIT),
                              ("cursor", self.CURSOR_WRITE)):
            with self.subTest(tool=tool, name=payload["tool_name"]):
                seen = []
                self.run_hook("permission", payload, ["--tool", tool],
                              lambda p: seen.append(p) or None, self.WRITE)
                self.assertEqual((seen[0]["path"], seen[0]["cwd"], seen[0]["event"]),
                                 ("/repo/AGENTS.md", "/repo", self.WRITE))

    def test_a_file_write_payload_without_a_path_denies_naming_the_field(self):
        for tool, payload in (("claude", {"tool_input": {"content": "x"}, "cwd": "/repo"}),
                              ("cursor", {"tool_input": {"contents": "x"}, "cwd": "/repo"}),
                              ("claude", {"cwd": "/repo"}), ("cursor", {"cwd": "/repo"})):
            with self.subTest(tool=tool, payload=payload):
                code, out, _ = self.run_hook("permission", payload, ["--tool", tool],
                                             self.never, self.WRITE)
                said = json.loads(out)
                reason = (said["hookSpecificOutput"]["permissionDecisionReason"]
                          if tool == "claude" else said["user_message"])
                self.assertEqual(code, 0)
                self.assertIn("tool_input.file_path", reason)

    def test_a_file_write_payload_without_a_cwd_still_reaches_decide(self):
        """cwd is optional for the event: a relative path with none is the hook's to refuse."""
        seen = []
        self.run_hook("permission", {"tool_input": {"file_path": "a.md"}}, ["--tool", "claude"],
                      lambda p: seen.append(p) or None, self.WRITE)
        self.assertEqual((seen[0]["path"], seen[0]["cwd"]), ("a.md", None))

    def test_a_file_write_deny_comes_out_in_each_tools_shape(self):
        _, out, _ = self.run_hook("permission", self.CLAUDE_WRITE, ["--tool", "claude"],
                                  lambda p: ("u", "a"), self.WRITE)
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "a"}})
        _, out, _ = self.run_hook("permission", self.CURSOR_WRITE, ["--tool", "cursor"],
                                  lambda p: ("u", "a"), self.WRITE)
        self.assertEqual(json.loads(out),
                         {"permission": "deny", "user_message": "u", "agent_message": "a"})

    def test_a_file_write_observer_without_a_path_is_skipped(self):
        self.assertEqual(self.run_hook("observer", {"cwd": "/repo"}, ["--tool", "claude"],
                                       self.never, self.WRITE), (0, "", ""))


class DestructiveShell(unittest.TestCase):
    """Intent: hooks/no-destructive-shell denies the shell commands that discard work - git
    clean, git checkout of paths, git reset --hard, rm -r and Remove-Item -Recurse - read from
    the command's leading words per segment, so a commit message that names one is allowed. A
    command it cannot read denies. A recursive delete of literal paths inside the repository's
    scratch/ is allowed. Every case runs with Cursor's payload and with Claude Code's."""

    @classmethod
    def setUpClass(cls):
        cls.hook = load("no_destructive_shell", HOOKS / "no-destructive-shell" / "hook.py")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".git").mkdir()
        (self.root / "scratch" / "sub").mkdir(parents=True)

    NO_CWD = object()

    def verdict(self, tool: str, command, cwd=None, raw: bytes | None = None, env=None):
        """None when the hook allows, else (user message, agent message); Claude Code's deny
        carries one reason, which is the agent message."""
        if raw is None:
            cwd = str(self.root) if cwd is None else cwd
            body = {} if cwd is self.NO_CWD else {"cwd": cwd}
            if tool == "cursor":
                body["command"] = command
            else:
                body.update({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                             "tool_input": {"command": command}})
            raw = json.dumps(body).encode()
        out = io.StringIO()
        with mock.patch("sys.stdin", new=stdin_of(raw)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.argv", ["hook.py", "--tool", tool]), mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            os.environ.update(env or {})
            self.assertEqual(self.hook.main(), 0)
        text = out.getvalue()
        if tool == "cursor":
            said = json.loads(text)
            return None if said["permission"] == "allow" else (said["user_message"],
                                                              said["agent_message"])
        if not text:
            return None
        said = json.loads(text)["hookSpecificOutput"]
        self.assertEqual(said["permissionDecision"], "deny")
        return None, said["permissionDecisionReason"]

    def assert_denied(self, command, **kwargs):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool, command=command):
                self.assertIsNotNone(self.verdict(tool, command, **kwargs))

    def assert_allowed(self, command, **kwargs):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool, command=command):
                self.assertIsNone(self.verdict(tool, command, **kwargs))

    DENIED = (
        "git clean -fd", "git clean -xfd", "git -C sub clean -f", "git checkout -- .",
        "git checkout -- src/app.py", "git checkout .", "git reset --hard",
        "git reset --hard HEAD~1", "rm -rf build", "rm -fr build", "rm -r -f build",
        "/bin/rm -rf build", "sudo rm -rf build", "FOO=1 rm -rf build",
        "Remove-Item -Recurse -Force build", "Remove-Item build -Recurse",
        "remove-item -rec build", "REMOVE-ITEM -RECURSE build", "ri -r build",
        "del -Recurse build", "rm -r build", "git -c core.x=y clean -f",
        "git --git-dir=.git --work-tree=. reset --hard",
    )
    WRAPS = ("cd x && {}", "cd x; {}", "a | {}", "a || {}", "echo $({})", "echo hi\n{}",
             "a & {}", "if true; then {}; fi", "& {}")

    def test_the_five_families_are_denied(self):
        for command in self.DENIED:
            self.assert_denied(command)

    def test_a_destructive_segment_anywhere_in_the_line_denies(self):
        for command in self.DENIED:
            for wrap in self.WRAPS:
                self.assert_denied(wrap.format(command))

    def test_everything_else_is_allowed(self):
        for command in (
            "git status", "git checkout main", "git checkout -b feature",
            "git reset HEAD file.py", "git reset --soft HEAD~1", "git clean -n",
            "git clean --dry-run -d", "git clean -nd", "rm file.txt", "Remove-Item file.txt",
            "Remove-Item -Force file.txt", "echo rm -rf build",
            'git log --grep "reset --hard"', 'git commit -m "git reset --hard was the fix"',
            "git commit -m 'rm -rf build'", "Select-String -Pattern 'Remove-Item -Recurse'",
            "git push 2>&1", "ls > out.txt 2>&1", "", "   ",
        ):
            self.assert_allowed(command)

    def test_a_commit_message_that_names_a_destructive_command_is_allowed(self):
        """Intent: the false positive that pulled no-shell-file-edits - a message line reading
        git reset --hard sits at the start of a physical line in a here-string or heredoc."""
        for command in (
            "git commit -m @'\ngit reset --hard is gone\n'@",
            'git commit -m @"\nrm -rf build\n"@',
            "git commit -m @'\r\ngit reset --hard is gone\r\n'@",
            "git commit -F - <<'EOF'\nrm -rf build\nEOF",
            "git commit -F - <<EOF\ngit clean -fd\nEOF\n",
            "git commit -F - <<-EOF\n\trm -rf build\n\tEOF",
            "git commit -m @'\ngit reset --hard\n'@; git status",
            "cat <<'A' <<'B'\nrm -rf x\nA\ngit clean -fd\nB",
        ):
            self.assert_allowed(command)

    def test_a_command_after_a_quoted_block_is_still_read(self):
        for command in (
            "git commit -m @'\nnote\n'@; git reset --hard",
            "git commit -F - <<'EOF'\nnote\nEOF\nrm -rf build",
            "cat <<EOF | rm -rf build\nnote\nEOF",
            "echo 'a;b' && rm -rf build",
            'echo "a;b" && rm -rf build',
            "Remove-Item `\n  -Recurse build",
            "echo `rm -rf build`",
        ):
            self.assert_denied(command)

    def test_a_quote_the_scan_cannot_close_denies_naming_the_reason(self):
        for command, reason in (
            ('git commit -m "oops', "unbalanced"),
            ("git commit -m 'oops", "unbalanced"),
            ("git commit -m @'\nno closer", "here-string"),
            ("cat <<EOF\nrm -rf build", "heredoc"),
            ("cat <<EOF", "heredoc"),
        ):
            for tool in ("cursor", "claude"):
                with self.subTest(tool=tool, command=command):
                    said = self.verdict(tool, command)
                    self.assertIsNotNone(said)
                    self.assertIn("could not read", said[1])
                    self.assertIn(reason, said[1])

    def test_a_backslash_ending_a_double_quoted_path_reads_the_rest_as_quoted(self):
        """Characterisation of the gap hooks/README.md names: POSIX reads \\" as an escaped
        quote, so the closing quote is missing and the command denies as unreadable."""
        self.assert_denied('Remove-Item "C:\\dir\\"; git status')

    def test_an_unparseable_payload_denies(self):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self.verdict(tool, "", raw=b"\x00\x01 not json"))

    def test_a_payload_without_a_command_denies(self):
        for tool, raw in (("cursor", b'{"cwd": "/r"}'), ("claude", b'{"tool_input": {}}')):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self.verdict(tool, "", raw=raw))

    def test_a_command_that_is_not_text_denies(self):
        self.assert_denied(["rm", "-rf", "build"])

    def test_the_off_switch_allows(self):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool):
                self.assertIsNone(self.verdict(tool, "rm -rf build", env={"AI_TOOLBOX_HOOKS": "off"}))

    def test_a_deny_names_the_command_and_says_to_ask_the_operator(self):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool):
                said = self.verdict(tool, "cd x && git reset --hard HEAD~1")
                self.assertIn("git reset --hard HEAD~1", said[1])
                self.assertIn("ask the operator", said[1].lower())
                self.assertNotRegex(said[1] + (said[0] or ""),
                                    r"(?i)\b[a-z]{2,5}-\d+\b|github\.com|\.local\b")

    def test_a_cursor_deny_has_a_user_message_naming_the_hook(self):
        said = self.verdict("cursor", "git clean -fd")
        self.assertIn("no-destructive-shell", said[0])
        self.assertIn("git clean -fd", said[0])

    def test_a_recursive_delete_of_literal_scratch_paths_is_allowed(self):
        """Intent: the operator's ruling - agents clean their own scratch/ and a blanket deny
        on that is the fight he ruled against. Literal paths inside it only."""
        for command in (
            "rm -rf scratch/tmp", "rm -r scratch/a scratch/sub", "rm -rf ./scratch/x",
            "Remove-Item -Recurse -Force scratch/tmp", "Remove-Item -Recurse scratch\\sub",
            "Remove-Item -Recurse -Force -Path scratch/tmp -ErrorAction SilentlyContinue",
            "Remove-Item -LiteralPath scratch/tmp -Recurse", 'rm -rf "scratch/with space"',
            "rm -rf -- scratch/-odd", "ri -r scratch/x", f"rm -rf {self.root.as_posix()}/scratch/x",
            "rm -rf scratch/x 2>&1", "rm -rf scratch/x > /dev/null",
            "cd x && rm -rf scratch/x",
        ):
            self.assert_allowed(command)

    def test_a_recursive_delete_reaching_outside_scratch_is_denied(self):
        for command in (
            "rm -rf scratch", "rm -rf scratch/", "rm -rf scratch/..", "rm -rf scratch/../src",
            "rm -rf scratch/sub/../../src", "rm -rf scratch/*", "rm -rf scratch/?", "rm -rf scratch/[a]",
            "rm -rf $dir", "rm -rf scratch/$dir", 'rm -rf "scratch/$dir"', "rm -rf ~/scratch/x",
            "rm -rf scratch/a build", "rm -rf", "rm -rf --", "rm -rf scratch2/x",
            "rm -rf /scratch/x", "Remove-Item -Recurse", "Remove-Item -Recurse -Path",
            "Remove-Item -Recurse -Include *.tmp scratch", "Remove-Item -Recurse scratch\\..\\src",
            "rm -rf $(pwd)/scratch/x", "rm -rf scratch/`pwd`", "Remove-Item -Recurse (Get-Item scratch/x)",
        ):
            self.assert_denied(command)

    def test_the_exemption_is_for_deletes_only(self):
        for command in ("git clean -fd scratch", "git checkout -- scratch/x"):
            self.assert_denied(command)

    def test_the_repository_root_is_found_from_a_subdirectory(self):
        self.assert_allowed("rm -rf ../scratch/x", cwd=str(self.root / "sub"))
        self.assert_allowed("rm -rf x", cwd=str(self.root / "scratch" / "sub"))
        self.assert_denied("rm -rf ../../src", cwd=str(self.root / "scratch" / "sub"))

    def test_a_delete_without_a_usable_cwd_is_denied(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "scratch").mkdir()
        for cwd in (self.NO_CWD, "", "scratch", outside.name, 5):
            self.assert_denied("rm -rf scratch/x", cwd=cwd)


class GateBypass(unittest.TestCase):
    """Intent: hooks/no-destructive-shell also denies a way round the pre-push gates - git push
    --no-verify, GATE_REPORT_PUSH set in a segment, a push with core.hooksPath overridden, and a
    hand-written gate-report ref - read from each segment's words, so a message or an argument
    that names one is allowed. Dry runs and reads of report refs are allowed. Every case runs
    with Cursor's payload and with Claude Code's."""

    # Reuse DestructiveShell's helpers without inheriting its tests.
    NO_CWD = DestructiveShell.NO_CWD
    @classmethod
    def setUpClass(cls):
        cls.hook = load("no_destructive_shell", HOOKS / "no-destructive-shell" / "hook.py")

    setUp = DestructiveShell.setUp
    verdict = DestructiveShell.verdict
    assert_denied = DestructiveShell.assert_denied
    assert_allowed = DestructiveShell.assert_allowed

    NO_VERIFY = (
        "git push --no-verify", "git push origin main --no-verify",
        "git -C repo push --no-verify", "git push --no-verify origin main",
    )
    ENV_VARIABLE = (
        "GATE_REPORT_PUSH=1 git push", "export GATE_REPORT_PUSH=1", "env GATE_REPORT_PUSH=1 git push",
        "gate_report_push=1 git push", "GATE_REPORT_PUSH= git push",
        "$env:GATE_REPORT_PUSH = '1'", "$env:GATE_REPORT_PUSH='1'", "$ENV:gate_report_push = 1",
        "Set-Item env:GATE_REPORT_PUSH 1", "set-item -Path env:GATE_REPORT_PUSH -Value 1",
    )
    HOOKS_PATH = (
        "git -c core.hooksPath=/dev/null push", "git -c core.hookspath=elsewhere push origin main",
        "git -C repo -c CORE.HOOKSPATH=x push",
    )
    REPORT_REF = (
        "git update-ref refs/tags/gate-report/abc123 HEAD", "git tag gate-report/abc123",
        "git tag -f gate-report/abc123 HEAD", "git push origin refs/tags/gate-report/abc123",
        "git push origin HEAD:refs/tags/gate-report/abc123", "git -C repo update-ref refs/tags/gate-report/x HEAD",
    )
    WRAPS = ("cd x && {}", "cd x; {}", "a | {}", "echo hi\n{}", "if true; then {}; fi")

    def test_a_push_with_no_verify_is_denied(self):
        for command in self.NO_VERIFY:
            self.assert_denied(command)

    def test_setting_the_report_push_variable_is_denied(self):
        for command in self.ENV_VARIABLE:
            self.assert_denied(command)

    def test_a_push_with_the_hooks_path_overridden_is_denied(self):
        for command in self.HOOKS_PATH:
            self.assert_denied(command)

    def test_a_hand_written_report_ref_is_denied(self):
        for command in self.REPORT_REF:
            self.assert_denied(command)

    def test_a_bypass_segment_anywhere_in_the_line_denies(self):
        for command in self.NO_VERIFY + self.ENV_VARIABLE + self.HOOKS_PATH + self.REPORT_REF:
            for wrap in self.WRAPS:
                self.assert_denied(wrap.format(command))

    def test_the_deny_message_names_the_attempt_and_the_way_out(self):
        for tool in ("cursor", "claude"):
            for command in ("git push --no-verify", "GATE_REPORT_PUSH=1 git push",
                            "git -c core.hooksPath=x push", "git tag gate-report/x"):
                with self.subTest(tool=tool, command=command):
                    message = self.verdict(tool, command)[1]
                    self.assertIn(command, message)
                    self.assertIn("gate", message)
                    self.assertIn("operator", message)

    def test_dry_runs_and_ordinary_git_are_allowed(self):
        for command in (
            "", "git push", "git push origin main", "git push -n", "git push --dry-run",
            "git push -n origin main", "git status", "git -c core.x=y push",
            "git -c core.hooksPath=x status", "git commit --no-verify",
        ):
            self.assert_allowed(command)

    def test_a_name_inside_a_message_or_an_argument_is_allowed(self):
        for command in (
            'git commit -m "never use --no-verify"', "git commit -m 'GATE_REPORT_PUSH=1 is for the hook'",
            "echo GATE_REPORT_PUSH=1", "echo --no-verify", "echo $env:GATE_REPORT_PUSH",
            'git log --grep "gate-report/"', "git push origin --no-verify-not-a-flag",
            "git commit -F - <<'EOF'\ngit push --no-verify\nGATE_REPORT_PUSH=1 git push\nEOF",
        ):
            self.assert_allowed(command)

    def test_reading_report_refs_is_allowed(self):
        for command in (
            "git ls-remote origin 'refs/tags/gate-report/*'",
            "git fetch origin 'refs/tags/gate-report/*:refs/tags/gate-report/*'",
            "git show refs/tags/gate-report/abc123", "git for-each-ref refs/tags/gate-report/",
            "git tag -l 'gate-report/*'", "git tag --list 'gate-report/*'",
        ):
            self.assert_allowed(command)

    def test_creating_a_report_tag_by_hand_is_denied(self):
        self.assert_denied("git tag gate-report/20260101-000000/abc123 HEAD")


class GeneratedEdits(unittest.TestCase):
    """Intent: hooks/no-generated-edits denies an agent write to a file that carries the full
    generated-file stamp in its first 40 lines, naming the stamp's source to edit instead. An
    unstamped file, a new file and a file that only quotes the stamp's opening are allowed; a
    target it cannot read denies. Every case runs with Cursor's payload and Claude Code's."""

    @classmethod
    def setUpClass(cls):
        cls.hook = load("no_generated_edits", HOOKS / "no-generated-edits" / "hook.py")

    STAMP = "generated from profile-x@abc1234 - edit the source, not this file"
    UNPINNED = "generated from profile-x - edit the source, not this file"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def make(self, name: str, content: str | bytes) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def verdict(self, tool: str, path, cwd="", raw: bytes | None = None, env=None):
        """None when the hook allows, else (user message, agent message); Claude Code's deny
        carries one reason, which is the agent message. cwd="" means the temporary directory
        and None omits the field."""
        if raw is None:
            body = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
            if cwd is not None:
                body["cwd"] = str(self.dir) if cwd == "" else cwd
            raw = json.dumps(body).encode()
        out = io.StringIO()
        with mock.patch("sys.stdin", new=stdin_of(raw)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.argv", ["hook.py", "--tool", tool]), mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            os.environ.update(env or {})
            self.assertEqual(self.hook.main(), 0)
        text = out.getvalue()
        if tool == "cursor":
            said = json.loads(text)
            return None if said["permission"] == "allow" else (said["user_message"],
                                                              said["agent_message"])
        if not text:
            return None
        said = json.loads(text)["hookSpecificOutput"]
        self.assertEqual(said["permissionDecision"], "deny")
        return None, said["permissionDecisionReason"]

    def assert_denied(self, path, **kwargs):
        found = {}
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool, path=str(path)):
                found[tool] = self.verdict(tool, path, **kwargs)
                self.assertIsNotNone(found[tool])
        return found

    def assert_allowed(self, path, **kwargs):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool, path=str(path)):
                self.assertIsNone(self.verdict(tool, path, **kwargs))

    def test_a_stamped_file_is_denied_wherever_the_stamp_sits_in_its_head(self):
        filler = "".join(f"line {n}\n" for n in range(18))
        for name, content in (
            ("a.md", f"<!-- {self.STAMP} -->\n# Title\n"),
            ("unpinned.md", f"<!-- {self.UNPINNED} -->\n# Title\n"),
            ("script.py", f"#!/usr/bin/env python3\n# {self.STAMP}\nprint(1)\n"),
            ("front.md", f"---\n{filler}---\n<!-- {self.STAMP} -->\n# Title\n"),
            ("hooks.json", json.dumps({"_generated": self.STAMP, "version": 1}, indent=2)),
            ("last-line.md", "x\n" * 39 + f"<!-- {self.STAMP} -->\n" + "tail\n"),
            ("crlf.md", f"<!-- {self.STAMP} -->\r\n# Title\r\n"),
        ):
            self.assert_denied(self.make(name, content))

    def test_an_unstamped_or_new_file_is_allowed(self):
        quoting = '# the stamp reads "generated from <repo>@<sha>" in a rendered file\nkey: 1\n'
        for name, content in (
            ("plain.md", "# Title\n"),
            ("empty.md", ""),
            ("quoted.yaml", quoting),
            ("late.md", "x\n" * 40 + f"<!-- {self.STAMP} -->\n"),
            ("binary.bin", b"\xff\xfe\x00\x81 not utf-8\n"),
            ("open-only.md", "<!-- generated from profile-x@abc1234 -->\n"),
        ):
            self.assert_allowed(self.make(name, content))
        self.assert_allowed(self.dir / "new" / "file-that-does-not-exist.md")

    def test_a_relative_path_resolves_against_cwd(self):
        self.make("sub/a.md", f"<!-- {self.STAMP} -->\n")
        self.assert_denied("sub/a.md")
        self.assert_allowed("sub/not-there.md")

    @unittest.skipUnless(os.name == "nt", "a backslash separates folders only on Windows")
    def test_a_path_with_backslashes_resolves_on_windows(self):
        self.make("sub/a.md", f"<!-- {self.STAMP} -->\n")
        self.assert_denied("sub\\a.md")
        self.assert_denied(str(self.dir / "sub" / "a.md"))

    def test_a_target_it_cannot_read_is_denied_naming_the_reason(self):
        self.make("sub/keep.md", "x")
        found = {}
        for label, path, cwd in (
            ("directory", self.dir / "sub", ""),
            ("no cwd", "relative.md", None),
            ("empty path", "", ""),
        ):
            found[label] = self.assert_denied(path, cwd=cwd)
        for tool in ("cursor", "claude"):
            self.assertIn("directory", found["directory"][tool][1])
            self.assertIn("cwd", found["no cwd"][tool][1])
            self.assertIn("could not read", found["empty path"][tool][1])

    def test_a_read_that_raises_is_denied(self):
        target = self.make("a.md", "# Title\n")
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool), mock.patch("builtins.open", side_effect=OSError("boom")):
                said = self.verdict(tool, target)
                self.assertIsNotNone(said)
                self.assertIn("could not read", said[1])

    def test_a_path_that_is_not_text_is_denied(self):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool):
                raw = json.dumps({"cwd": str(self.dir), "tool_input": {"file_path": 7}}).encode()
                self.assertIsNotNone(self.verdict(tool, "", raw=raw))

    def test_an_unparseable_payload_denies(self):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self.verdict(tool, "", raw=b"\x00\x01 not json"))

    def test_a_payload_without_a_path_denies_naming_the_field(self):
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool):
                said = self.verdict(tool, "", raw=b'{"cwd": "/r", "tool_input": {}}')
                self.assertIn("tool_input.file_path", said[0] or said[1])

    def test_the_stamp_on_line_40_counts_and_on_line_41_does_not(self):
        self.assert_denied(self.make("l40.md", "x\n" * 39 + f"{self.STAMP}\n"))
        self.assert_allowed(self.make("l41.md", "x\n" * 40 + f"{self.STAMP}\n"))

    def test_two_stamps_are_denied_once_naming_the_first(self):
        target = self.make("two.md", "<!-- generated from first-src@abc1234 - edit the source, "
                                     "not this file -->\n" + f"<!-- {self.STAMP} -->\n")
        for tool, said in self.assert_denied(target).items():
            with self.subTest(tool=tool):
                self.assertIn("first-src", said[1])
                self.assertNotIn("profile-x", said[1])

    def test_the_deny_names_the_file_the_source_and_the_next_render(self):
        target = self.make("a.md", f"<!-- {self.STAMP} -->\n")
        for tool, said in self.assert_denied(target).items():
            with self.subTest(tool=tool):
                self.assertIn(str(target), said[1])
                self.assertIn("profile-x", said[1])
                self.assertIn("overwritten at the next render", said[1])
                self.assertNotRegex(said[1] + (said[0] or ""),
                                    r"(?i)\b[a-z]{2,5}-\d+\b|github\.com|\.local\b")
        self.assertIn(str(target), self.verdict("cursor", target)[0])

    def test_the_off_switch_allows_a_stamped_file(self):
        target = self.make("a.md", f"<!-- {self.STAMP} -->\n")
        for tool in ("cursor", "claude"):
            with self.subTest(tool=tool):
                self.assertIsNone(self.verdict(tool, target, env={"AI_TOOLBOX_HOOKS": "off"}))

    def test_the_pattern_wants_the_whole_stamp(self):
        self.assertEqual(self.hook.stamp_source(self.STAMP), "profile-x")
        self.assertEqual(self.hook.stamp_source(self.UNPINNED), "profile-x")
        for text in ("generated from <repo>@<sha>", "generated from profile-x@abc1234",
                     "generated from profile-x - edit the source", ""):
            with self.subTest(text=text):
                self.assertIsNone(self.hook.stamp_source(text))


class HookNotice(unittest.TestCase):
    """Intent: hooks/README.md, "The off switch". run_notice is the one entry point the off switch
    does not gate, for a hook whose job is to report the switch: it writes the text its callback
    returns as Claude Code's SessionStart context, and like an observer it fails open."""

    @classmethod
    def setUpClass(cls):
        cls.lib = load("hookio", HOOKS / "lib" / "hookio.py")

    START = {"hook_event_name": "SessionStart", "source": "startup", "cwd": "/repo"}

    def run_hook(self, payload, argv: list[str], callback, env: dict | None = None):
        out = io.StringIO()
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.argv", ["hook.py", *argv]), mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            os.environ.update(env or {})
            code = self.lib.run_notice("start", "session.start", callback)
        return code, out.getvalue()

    def never(self, seen):
        raise AssertionError(f"callback ran with {seen}")

    def test_the_text_comes_out_as_claude_codes_session_start_context(self):
        code, out = self.run_hook(self.START, ["--tool", "claude"], lambda seen: "the line")
        self.assertEqual(code, 0)
        self.assertEqual(out, json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": "the line"}}) + "\n")

    def test_the_callback_sees_the_neutral_session_start_payload(self):
        seen = []
        self.run_hook(self.START, ["--tool", "claude"], lambda p: seen.append(p))
        self.assertEqual(seen[0]["event"], "session.start")

    def test_no_text_writes_nothing(self):
        self.assertEqual(self.run_hook(self.START, ["--tool", "claude"], lambda p: None),
                         (0, ""))

    def test_the_off_switch_does_not_gate_it(self):
        code, out = self.run_hook(self.START, ["--tool", "claude"], lambda p: "the line",
                                  {"AI_TOOLBOX_HOOKS": "off"})
        self.assertEqual(code, 0)
        self.assertIn("the line", out)

    def test_input_it_cannot_read_writes_nothing_and_exits_zero(self):
        for data in (b"\x00\x01 not json", b"[]"):
            with self.subTest(data=data):
                self.assertEqual(self.run_hook(data, ["--tool", "claude"], self.never), (0, ""))

    def test_a_tool_with_no_writer_gets_nothing(self):
        for argv in (["--tool", "cursor"], ["--tool", "nope"], []):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_hook(self.START, argv, lambda p: "the line"), (0, ""))


class SessionStart(unittest.TestCase):
    """Intent: hooks/session-start orients every session: the shape line when the rule file is
    under the payload's cwd, always the role-skill line, and first the off line when
    AI_TOOLBOX_HOOKS=off. It still runs while the switch is off."""

    LINE = ("Agent hooks are OFF on this machine: AI_TOOLBOX_HOOKS=off is set, so no hook "
            "guards this session. Clear it to turn them back on.")

    @classmethod
    def setUpClass(cls):
        cls.hook = load("session_start", HOOKS / "session-start" / "hook.py")

    def start(self, data: bytes, env: dict | None = None):
        out = io.StringIO()
        with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.argv", ["hook.py", "--tool", "claude"]), \
                mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            os.environ.update(env or {})
            code = self.hook.main()
        return code, out.getvalue()

    PAYLOAD = json.dumps({"hook_event_name": "SessionStart", "source": "startup"}).encode()

    SHAPE = ("Before your first reply, read `.github/rules/response-shape.md`. At the start of "
             "every turn, run `python .github/scripts/responses/check_response.py --previous` "
             "from the repository root and fix what it reports in the reply you are writing.")
    ROLE = ("If your instructions name a role skill for this session, load it before acting and "
            "do the steps it says belong on your first tool call.")

    def context(self, out: str) -> str:
        parsed = json.loads(out)
        self.assertEqual(list(parsed), ["hookSpecificOutput"])
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertEqual(len(out.splitlines()), 1)
        return parsed["hookSpecificOutput"]["additionalContext"]

    def repo(self, with_rule: bool = True) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if with_rule:
            rules = Path(tmp.name) / ".github" / "rules"
            rules.mkdir(parents=True)
            (rules / "response-shape.md").write_text("x", encoding="utf-8")
        return tmp.name

    def payload(self, **fields) -> bytes:
        return json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                           **fields}).encode()

    def test_with_the_rule_present_it_emits_the_shape_line_then_the_role_line(self):
        code, out = self.start(self.payload(cwd=self.repo()))
        self.assertEqual(code, 0)
        self.assertEqual(self.context(out), f"{self.SHAPE}\n{self.ROLE}")

    def test_with_the_rule_absent_it_emits_only_the_role_line(self):
        code, out = self.start(self.payload(cwd=self.repo(with_rule=False)))
        self.assertEqual(code, 0)
        self.assertEqual(self.context(out), self.ROLE)

    def test_a_missing_non_string_or_non_directory_cwd_gives_only_the_role_line(self):
        file_path = Path(self.repo()) / ".github" / "rules" / "response-shape.md"
        cases = {"no cwd": {}, "not a string": {"cwd": 7}, "null": {"cwd": None},
                 "does not exist": {"cwd": str(Path(self.repo()) / "absent")},
                 "a file": {"cwd": str(file_path)}}
        for name, fields in cases.items():
            with self.subTest(case=name):
                code, out = self.start(self.payload(**fields))
                self.assertEqual(code, 0)
                self.assertEqual(self.context(out), self.ROLE)

    def test_a_filesystem_error_checking_the_rule_counts_as_absent(self):
        with mock.patch.object(Path, "is_file", side_effect=OSError("denied")):
            code, out = self.start(self.payload(cwd=self.repo()))
        self.assertEqual(code, 0)
        self.assertEqual(self.context(out), self.ROLE)

    def test_with_the_switch_off_the_off_line_comes_first_then_the_orientation(self):
        code, out = self.start(self.payload(cwd=self.repo()), {"AI_TOOLBOX_HOOKS": "off"})
        self.assertEqual(code, 0)
        self.assertEqual(self.context(out), f"{self.LINE}\n{self.SHAPE}\n{self.ROLE}")
        code, out = self.start(self.PAYLOAD, {"AI_TOOLBOX_HOOKS": "off"})
        self.assertEqual(self.context(out), f"{self.LINE}\n{self.ROLE}")

    def test_with_the_switch_unset_or_anything_but_off_there_is_no_off_line(self):
        for env in ({}, {"AI_TOOLBOX_HOOKS": ""}, {"AI_TOOLBOX_HOOKS": "0"}):
            with self.subTest(env=env):
                code, out = self.start(self.PAYLOAD, env)
                self.assertEqual(code, 0)
                self.assertEqual(self.context(out), self.ROLE)

    def test_an_unreadable_payload_writes_nothing_and_exits_zero(self):
        for env in ({}, {"AI_TOOLBOX_HOOKS": "off"}):
            with self.subTest(env=env):
                self.assertEqual(self.start(b"\x00\x01 not json", env), (0, ""))

    def test_the_manifest_names_the_event_the_kind_and_the_tool(self):
        text = (HOOKS / "session-start" / "hook.yaml").read_text(encoding="utf-8")
        for line in ("event: session.start", "kind: observer", "tools: [claude]", "timeout: 10",
                     'run: ["{python}", "{hooks}/session-start/hook.py"]'):
            self.assertIn(line, text.splitlines())


class ObserverWarning(unittest.TestCase):
    """Intent: hooks/README.md, "Tool-neutral schema". An observer may return a warning. It
    reaches the agent where the tool supports it (Claude Code PostToolUse additionalContext), is
    never a block, and is silent when the off switch is on, for a tool with no shape, or when the
    observer returns nothing."""

    @classmethod
    def setUpClass(cls):
        cls.lib = load("hookio", HOOKS / "lib" / "hookio.py")

    WRITE = {"hook_event_name": "PostToolUse", "tool_name": "Write", "cwd": "/repo",
             "tool_input": {"file_path": "/repo/a.py", "content": "x"}}

    def run_hook(self, argv: list[str], callback, env: dict | None = None, payload=None):
        out = io.StringIO()
        data = json.dumps(self.WRITE if payload is None else payload).encode()
        with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.argv", ["hook.py", *argv]), mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            os.environ.update(env or {})
            code = self.lib.run_observer("watch", "file.write.after", callback)
        return code, out.getvalue()

    def test_the_file_write_after_fields_are_mapped_for_claude_code(self):
        seen = self.lib.neutral("file.write.after", self.WRITE, "claude")
        self.assertEqual((seen["path"], seen["cwd"]), ("/repo/a.py", "/repo"))

    def test_a_write_with_no_path_is_skipped_by_an_observer(self):
        payload = {**self.WRITE, "tool_input": {}}
        self.assertEqual(self.run_hook(["--tool", "claude"], lambda p: "warn", payload=payload),
                         (0, ""))

    def test_claude_code_gets_the_text_as_post_tool_use_context(self):
        code, out = self.run_hook(["--tool", "claude"], lambda seen: "the warning")
        self.assertEqual(code, 0)
        self.assertEqual(out, json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": "the warning"}}) + "\n")

    def test_the_callback_sees_the_neutral_payload(self):
        seen = []
        self.run_hook(["--tool", "claude"], lambda p: seen.append(p))
        self.assertEqual(seen[0]["event"], "file.write.after")
        self.assertEqual(seen[0]["path"], "/repo/a.py")

    def test_no_text_writes_nothing(self):
        self.assertEqual(self.run_hook(["--tool", "claude"], lambda p: None), (0, ""))
        self.assertEqual(self.run_hook(["--tool", "claude"], lambda p: ""), (0, ""))

    def test_cursor_and_an_unknown_tool_get_nothing(self):
        for argv in (["--tool", "cursor"], ["--tool", "nope"], []):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_hook(argv, lambda p: "the warning"), (0, ""))

    def test_the_off_switch_writes_nothing_and_does_not_run_the_callback(self):
        def never(seen):
            raise AssertionError("callback ran")
        self.assertEqual(self.run_hook(["--tool", "claude"], never, {"AI_TOOLBOX_HOOKS": "off"}),
                         (0, ""))


class WriteObserver(unittest.TestCase):
    """Intent: hooks/write-observer warns the agent, at write time, when a file it just wrote holds
    a credential shape: it names the file, the line and the shape, never the text. It shares the
    push gate's shapes by loading the rendered .githooks/lib/secret_shapes.py from the repository
    root, and fails open on a missing file, a missing module or anything else."""

    @classmethod
    def setUpClass(cls):
        cls.hook = load("write_observer", HOOKS / "write-observer" / "hook.py")
        cls.module = (HOOKS.parent / "githooks" / "lib" / "secret_shapes.py").read_text(
            encoding="utf-8")

    HEX = "0123456789abcdef" * 2  # built from parts: obviously fake

    def repo(self, rendered: bool = True) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / ".git").mkdir()
        if rendered:
            lib = root / ".githooks" / "lib"
            lib.mkdir(parents=True)
            (lib / "secret_shapes.py").write_text(self.module, encoding="utf-8")
        return root

    def write(self, root: Path, name: str, text: str) -> Path:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def payload(self, root: Path, path) -> bytes:
        return json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write",
                           "cwd": str(root), "tool_input": {"file_path": str(path),
                                                            "content": "x"}}).encode()

    def observe(self, data: bytes, env: dict | None = None, argv=("--tool", "claude")):
        out = io.StringIO()
        with mock.patch("sys.stdin", new=stdin_of(data)), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.argv", ["hook.py", *argv]), mock.patch.dict(os.environ):
            os.environ.pop("AI_TOOLBOX_HOOKS", None)
            os.environ.update(env or {})
            code = self.hook.main()
        return code, out.getvalue()

    def test_a_shape_in_the_written_file_warns_naming_file_line_and_shape(self):
        root = self.repo()
        path = self.write(root, "src/app.py", f"x = 1\ntoken = '{self.HEX}'\n")
        code, out = self.observe(self.payload(root, path))
        self.assertEqual(code, 0)
        context = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "PostToolUse")
        text = context["additionalContext"]
        self.assertIn(str(path), text)
        self.assertIn(":2", text)
        self.assertIn("hex", text)
        self.assertNotIn(self.HEX, text)
        self.assertEqual(len(out.splitlines()), 1)

    def test_every_hit_is_named(self):
        root = self.repo()
        header = "-----BEGIN " + "PRIVATE KEY" + "-----"
        path = self.write(root, "a.txt", f"{header}\nfine\n{self.HEX}\n")
        text = json.loads(self.observe(self.payload(root, path))[1])[
            "hookSpecificOutput"]["additionalContext"]
        self.assertIn(":1", text)
        self.assertIn("privkey", text)
        self.assertIn(":3", text)
        self.assertIn("hex", text)

    def test_a_clean_file_writes_nothing(self):
        root = self.repo()
        path = self.write(root, "a.py", "print('hello')\n")
        self.assertEqual(self.observe(self.payload(root, path)), (0, ""))

    def test_the_opt_out_comment_writes_nothing(self):
        root = self.repo()
        path = self.write(root, "a.py", f"t = '{self.HEX}'  # secret-scan: allow\n")
        self.assertEqual(self.observe(self.payload(root, path)), (0, ""))

    def test_a_relative_path_resolves_against_the_payload_cwd(self):
        root = self.repo()
        self.write(root, "src/app.py", f"{self.HEX}\n")
        data = json.dumps({"cwd": str(root), "tool_input": {"file_path": "src/app.py"}}).encode()
        out = self.observe(data)[1]
        self.assertIn("hex", out)

    def test_the_root_is_found_from_a_subfolder_cwd(self):
        root = self.repo()
        path = self.write(root, "deep/er/a.py", f"{self.HEX}\n")
        data = json.dumps({"cwd": str(path.parent),
                           "tool_input": {"file_path": str(path)}}).encode()
        self.assertIn("hex", self.observe(data)[1])

    def test_a_missing_file_writes_nothing_and_exits_zero(self):
        root = self.repo()
        self.assertEqual(self.observe(self.payload(root, root / "gone.py")), (0, ""))

    def test_a_directory_or_a_binary_file_writes_nothing_and_exits_zero(self):
        root = self.repo()
        (root / "dir").mkdir()
        self.assertEqual(self.observe(self.payload(root, root / "dir")), (0, ""))
        binary = root / "b.bin"
        binary.write_bytes(b"\xff\xfe\x00\x81" * 10)
        self.assertEqual(self.observe(self.payload(root, binary)), (0, ""))

    def test_a_repository_without_the_rendered_module_writes_nothing_and_exits_zero(self):
        root = self.repo(rendered=False)
        path = self.write(root, "a.py", f"{self.HEX}\n")
        self.assertEqual(self.observe(self.payload(root, path)), (0, ""))

    def test_a_module_that_crashes_writes_nothing_and_exits_zero(self):
        root = self.repo()
        (root / ".githooks" / "lib" / "secret_shapes.py").write_text("raise RuntimeError('x')\n",
                                                                     encoding="utf-8")
        path = self.write(root, "a.py", f"{self.HEX}\n")
        self.assertEqual(self.observe(self.payload(root, path)), (0, ""))

    def test_a_folder_with_no_repository_writes_nothing_and_exits_zero(self):
        loose = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, loose, True)
        path = self.write(loose, "a.py", f"{self.HEX}\n")
        self.assertEqual(self.observe(self.payload(loose, path)), (0, ""))

    def test_unreadable_input_and_other_tools_write_nothing_and_exit_zero(self):
        root = self.repo()
        path = self.write(root, "a.py", f"{self.HEX}\n")
        self.assertEqual(self.observe(b"\x00\x01 not json"), (0, ""))
        self.assertEqual(self.observe(self.payload(root, path), argv=("--tool", "cursor")),
                         (0, ""))

    def test_the_off_switch_prints_nothing(self):
        root = self.repo()
        path = self.write(root, "a.py", f"{self.HEX}\n")
        self.assertEqual(self.observe(self.payload(root, path), {"AI_TOOLBOX_HOOKS": "off"}),
                         (0, ""))

    def test_the_manifest_names_the_event_the_kind_and_the_tool(self):
        text = (HOOKS / "write-observer" / "hook.yaml").read_text(encoding="utf-8")
        for line in ("event: file.write.after", "kind: observer", "tools: [claude]",
                     "timeout: 10", 'run: ["{python}", "{hooks}/write-observer/hook.py"]'):
            self.assertIn(line, text.splitlines())


RESPONSE_CHECK = HOOKS / "response-check"
RESPONSES = HOOKS.parent / "responses"


class ResponseCheck(unittest.TestCase):
    """Claude Code's Stop hook sends a malformed reply back once, through the rendered
    .github/scripts/responses/check_response.py --stop, and never blocks otherwise."""

    MALFORMED = "No marker, no header, no sections at all."

    # A well-formed reply but for one decision whose reasoning lines are missing: only a
    # `decisions:` finding sends a reply back.
    DECISION_GAP = (
        "=== REPLY STARTS HERE ===\nMode: Execution\nNeeds from you: 1 decision\n"
        "Changed: nothing\n\n## Summary\n**Topic:** done, see `tests/x.py:1`.\n\n"
        "## Decisions and clarifications\n- DC1 Pick one?\n  - Use case: decides the next step\n"
        "  - Options:\n    - a. this (recommended)\n    - b. that\n\n"
        "## Recommended next\nNone.\n\n## Came up while doing it\nNone.\n")

    @classmethod
    def setUpClass(cls):
        cls.hook = load("response_check", RESPONSE_CHECK / "hook.py")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # A machine with the hooks switched off must not skip these checks.
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("AI_TOOLBOX_HOOKS", None)

    def rendered_project(self) -> Path:
        """A project root laid out the way sync renders it: the checker under
        .github/scripts/responses/, the hook under .claude/hooks/response-check/."""
        shutil.copytree(RESPONSES, self.tmp / ".github" / "scripts" / "responses",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (self.tmp / ".claude" / "hooks" / "response-check").mkdir(parents=True)
        return self.tmp

    def run_hook(self, payload: dict | bytes, env: dict | None = None,
                 checker: Path | None = None) -> tuple[int, str]:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        err = io.StringIO()
        patches = [mock.patch.object(sys, "stdin", stdin_of(raw)),
                   mock.patch.object(sys, "stderr", err),
                   mock.patch.dict(os.environ, env or {}, clear=False)]
        if checker is not None:
            patches.append(mock.patch.object(self.hook, "find_checker", return_value=checker))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        code = self.hook.main()
        return code, err.getvalue()

    def test_the_spec_renders_for_claude_code_only(self):
        text = (RESPONSE_CHECK / "hook.yaml").read_text(encoding="utf-8")
        for line in ("event: turn.end", "kind: observer", "tools: [claude]",
                     'run: ["{python}", "{hooks}/response-check/hook.py"]'):
            self.assertIn(line, text.splitlines())

    def test_the_rendered_checker_is_found_from_the_project_root(self):
        root = self.rendered_project()
        start = root / ".claude" / "hooks" / "response-check" / "hook.py"
        self.assertEqual(self.hook.find_checker(start),
                         (root / ".github" / "scripts" / "responses"
                          / "check_response.py").resolve())

    def rendered_checker(self) -> Path:
        return self.rendered_project() / ".github" / "scripts" / "responses" / "check_response.py"

    def test_a_formatting_only_reply_is_reported_not_sent_back(self):
        code, err = self.run_hook({"last_assistant_message": self.MALFORMED,
                                   "stop_hook_active": False}, checker=self.rendered_checker())
        self.assertEqual(code, 0)
        self.assertTrue(err.strip(), "the findings still go to stderr")

    def test_a_reply_with_a_decision_finding_is_sent_back_once(self):
        code, err = self.run_hook({"last_assistant_message": self.DECISION_GAP,
                                   "stop_hook_active": False}, checker=self.rendered_checker())
        self.assertEqual(code, 2)
        self.assertIn("decisions:", err)

    def test_a_second_try_is_never_sent_back(self):
        code, _ = self.run_hook({"last_assistant_message": self.MALFORMED,
                                 "stop_hook_active": True}, checker=self.rendered_checker())
        self.assertEqual(code, 0)

    def test_the_off_switch_skips_the_check(self):
        code, err = self.run_hook({"last_assistant_message": self.MALFORMED},
                                  env={"AI_TOOLBOX_HOOKS": "off"})
        self.assertEqual((code, err), (0, ""))

    def test_no_checker_found_never_blocks(self):
        code, err = self.run_hook({"last_assistant_message": self.MALFORMED},
                                  checker=Path("/nonexistent/check_response.py"))
        self.assertEqual(code, 0)
        self.assertIn("not found", err)

    def test_a_checker_that_crashes_never_blocks(self):
        broken = self.tmp / "check_response.py"
        broken.write_text("raise SystemExit(7)\n", encoding="utf-8")
        code, _ = self.run_hook({"last_assistant_message": self.MALFORMED}, checker=broken)
        self.assertEqual(code, 0)


TITLE_PREFIX = HOOKS / "title-prefix"


class TitlePrefix(unittest.TestCase):
    """Claude Code's Stop hook grades the session title's status prefix against the reply,
    sends a stale one back once, and never blocks on its own failure."""

    MARKER = "=== REPLY STARTS HERE ==="
    NO_ASK = f"{MARKER}\n\n## Summary\n\nDone.\n\n## Recommended next\n\nNothing.\n"
    WITH_ASK = f"{MARKER}\n\n## Summary\n\nDone.\n\n## Decisions and clarifications\n\nWhich?\n"
    WITH_STEPS = f"{MARKER}\n\n## Summary\n\nDone.\n\n## Operator steps\n\n1. Run it.\n"

    @classmethod
    def setUpClass(cls):
        cls.hook = load("title_prefix", TITLE_PREFIX / "hook.py")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # A machine with the hooks switched off must not skip these checks.
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("AI_TOOLBOX_HOOKS", None)

    def transcript(self, *calls: tuple[str, str]) -> Path:
        """A JSONL transcript holding one set_session_title call per (session_id, title)."""
        lines = [json.dumps({"type": "user", "message": {"content": "hi"}})]
        for session_id, title in calls:
            block = {"type": "tool_use", "name": "mcp__ccd_session_mgmt__set_session_title",
                     "input": {"session_id": session_id, "title": title}}
            lines.append(json.dumps({"type": "assistant", "message": {"content": [block]}}))
        path = self.tmp / "t.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def run_hook(self, payload: dict, env: dict | None = None,
                 prefixes: Path | None = None) -> tuple[int, str]:
        err = io.StringIO()
        patches = [mock.patch.object(sys, "stdin", stdin_of(json.dumps(payload).encode("utf-8"))),
                   mock.patch.object(sys, "stderr", err),
                   mock.patch.dict(os.environ, env or {}, clear=False)]
        if prefixes is not None:
            patches.append(mock.patch.object(self.hook, "PREFIXES", prefixes))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return self.hook.main(), err.getvalue()

    def graded(self, title: str, reply: str, **extra) -> tuple[int, str]:
        payload = {"transcript_path": str(self.transcript(("self", title))),
                   "last_assistant_message": reply, "stop_hook_active": False, **extra}
        return self.run_hook(payload)

    def test_the_spec_renders_for_claude_code_only(self):
        spec = yaml.safe_load((TITLE_PREFIX / "hook.yaml").read_text(encoding="utf-8"))
        self.assertEqual((spec["event"], spec["tools"]), ("turn.end", ["claude"]))
        self.assertEqual(spec["run"][:2], ["{python}", "{hooks}/title-prefix/hook.py"])

    def test_the_default_vocabulary_holds_eight_entries(self):
        entries = self.hook.load_entries(TITLE_PREFIX / "prefixes.yaml")
        self.assertEqual(len(entries), 8)
        self.assertEqual({e["rule"] for e in entries}, {"ask", "no-ask", "unchecked"})

    def test_ask_rule_with_no_ask_is_sent_back_naming_the_prefix(self):
        code, err = self.graded("needs you - session", self.NO_ASK)
        self.assertEqual(code, 2)
        self.assertIn("needs you", err)

    def test_no_ask_rule_with_an_ask_is_sent_back(self):
        for reply in (self.WITH_ASK, self.WITH_STEPS):
            with self.subTest(reply=reply[:40]):
                code, err = self.graded("pending push - session", reply)
                self.assertEqual(code, 2)
                self.assertIn("pending push", err)

    def test_a_pattern_entry_with_an_ask_is_sent_back(self):
        code, _ = self.graded("pending fix-it - session", self.WITH_ASK)
        self.assertEqual(code, 2)

    def test_matching_prefixes_pass(self):
        for title, reply in (("needs you - x", self.WITH_ASK),
                             ("needs you - x", self.WITH_STEPS),
                             ("complete - x", self.NO_ASK),
                             ("overnight local test xyz - x", self.NO_ASK),
                             ("pending push - x", self.NO_ASK)):
            with self.subTest(title=title):
                self.assertEqual(self.graded(title, reply)[0], 0)

    def test_complete_and_overnight_with_an_ask_are_sent_back(self):
        for title, named in (("complete - x", "complete"),
                             ("overnight soak test - x", "overnight")):
            for reply in (self.WITH_ASK, self.WITH_STEPS):
                with self.subTest(title=title, reply=reply[:40]):
                    code, err = self.graded(title, reply)
                    self.assertEqual(code, 2)
                    self.assertIn(named, err)

    def test_overnight_needs_a_named_thing(self):
        entries = self.hook.load_entries(TITLE_PREFIX / "prefixes.yaml")
        self.assertIsNone(self.hook.match(entries, "overnight"))
        self.assertEqual(self.hook.match(entries, "overnight soak test")["rule"], "no-ask")

    def test_unchecked_rule_passes_with_or_without_an_ask(self):
        for title in ("holding pending desk - x", "parked until Friday - x", "working - x"):
            for reply in (self.NO_ASK, self.WITH_ASK):
                with self.subTest(title=title):
                    self.assertEqual(self.graded(title, reply)[0], 0)

    def test_an_unknown_prefix_passes(self):
        self.assertEqual(self.graded("something else - x", self.NO_ASK)[0], 0)

    def test_an_ask_before_the_last_marker_does_not_count(self):
        reply = f"{self.WITH_ASK}\n{self.NO_ASK}"
        self.assertEqual(self.graded("needs you - x", reply)[0], 2)

    def test_the_later_title_call_is_graded(self):
        path = self.transcript(("self", "needs you - x"), ("self", "complete - x"))
        code, _ = self.run_hook({"transcript_path": str(path), "stop_hook_active": False,
                                 "last_assistant_message": self.NO_ASK})
        self.assertEqual(code, 0)
        path = self.transcript(("self", "complete - x"), ("self", "needs you - x"))
        code, _ = self.run_hook({"transcript_path": str(path), "stop_hook_active": False,
                                 "last_assistant_message": self.NO_ASK})
        self.assertEqual(code, 2)

    def test_another_sessions_title_is_ignored(self):
        path = self.transcript(("abc-123", "needs you - x"))
        code, err = self.run_hook({"transcript_path": str(path), "stop_hook_active": False,
                                   "last_assistant_message": self.NO_ASK})
        self.assertEqual((code, err), (0, ""))

    def test_no_title_call_passes_silently(self):
        path = self.transcript()
        code, err = self.run_hook({"transcript_path": str(path), "stop_hook_active": False,
                                   "last_assistant_message": self.NO_ASK})
        self.assertEqual((code, err), (0, ""))

    def test_an_unreadable_transcript_never_blocks(self):
        code, err = self.run_hook({"transcript_path": str(self.tmp / "missing.jsonl"),
                                   "stop_hook_active": False,
                                   "last_assistant_message": self.NO_ASK})
        self.assertEqual(code, 0)
        self.assertTrue(err.strip(), "the reason goes to stderr")

    def test_missing_prefixes_never_blocks(self):
        payload = {"transcript_path": str(self.transcript(("self", "needs you - x"))),
                   "last_assistant_message": self.NO_ASK, "stop_hook_active": False}
        code, err = self.run_hook(payload, prefixes=self.tmp / "absent.yaml")
        self.assertEqual(code, 0)
        self.assertIn("prefixes", err)

    def test_unparsable_prefixes_never_blocks(self):
        bad = self.tmp / "prefixes.yaml"
        bad.write_text("prefixes: [unclosed\n", encoding="utf-8")
        payload = {"transcript_path": str(self.transcript(("self", "needs you - x"))),
                   "last_assistant_message": self.NO_ASK, "stop_hook_active": False}
        code, err = self.run_hook(payload, prefixes=bad)
        self.assertEqual(code, 0)
        self.assertIn("prefixes", err)

    def test_a_second_try_reports_and_passes(self):
        code, err = self.graded("needs you - x", self.NO_ASK, stop_hook_active=True)
        self.assertEqual(code, 0)
        self.assertIn("needs you", err)

    def test_the_off_switch_skips_the_check(self):
        payload = {"transcript_path": str(self.transcript(("self", "needs you - x"))),
                   "last_assistant_message": self.NO_ASK}
        self.assertEqual(self.run_hook(payload, env={"AI_TOOLBOX_HOOKS": "off"}), (0, ""))


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
