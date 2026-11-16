#!/usr/bin/env python3
################################################################################
# File: test_gates.py
# Path: {PROJECT_ROOT}/tests/test_gates.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: Runs each generic pre-push gate in githooks/gates/ against a
#              throwaway repository, both ways, and the pre-push hook itself
#              against a local bare remote. Skips where no POSIX shell is
#              available rather than reporting a pass it did not earn.
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
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import consent  # noqa: E402
import sync  # noqa: E402

GATES = ROOT / "githooks" / "gates"
STAMPED = "<!-- generated from some-profile@abc1234 - edit the source, not this file -->\n# rules\n"

# Shell is invisible to coverage, so test selection is told what these run.
# A class naming its gate narrows this to that gate; see GateCase.__init_subclass__.
EXERCISES = ["githooks/**"]

SH = shutil.which("sh") or next(
    (p for p in (r"C:\Program Files\Git\usr\bin\sh.exe", "/bin/sh") if Path(p).exists()),
    None,
)


@unittest.skipIf(SH is None, "no POSIX shell available; not reporting a pass")
class GateCase(unittest.TestCase):
    gate = ""
    # The gate-config config-dir a gate reading hand-owned declarations is given.
    config_dir = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("gate"):
            cls.EXERCISES = [f"githooks/gates/{cls.gate}.sh", "githooks/lib/**"]

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        if self.config_dir:
            self.gate_config(config_dir=self.config_dir)

    def assert_refuses_without_a_config_dir(self, *args: str) -> None:
        """Intent: the gate reads its declaration from config-dir, and refuses
        rather than guessing a folder when gate-config names none."""
        self.gate_config(deploy_branch="main")
        result = self.run_gate(*args)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("names no config-dir", result.stdout)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ("git",) + args, cwd=self.repo, capture_output=True, text=True, check=False
        ).stdout.strip()

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def commit(self, message: str = "c") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def gate_config(self, **values: str) -> None:
        """The rendered .githooks/gate-config, keys spelled with dashes as sync.py writes them."""
        self.write(".githooks/gate-config", "# generated from some-profile@abc1234\n" + "".join(
            f"{key.replace('_', '-')}={value}\n" for key, value in values.items()))

    def run_gate(self, *args: str, path_prefix: str = ""):
        script = (GATES / f"{self.gate}.sh").as_posix()
        # The shell's own bin directory has to be on PATH. Invoking Git for
        # Windows' sh.exe directly leaves grep and sed unfound, and the gates
        # then fail for a reason that has nothing to do with what they check.
        env = {**os.environ, "LC_ALL": "C"}
        env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
        if path_prefix:
            env["PATH"] = path_prefix + os.pathsep + env["PATH"]
        return subprocess.run(
            [SH, script, *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )


class DeadVariants(GateCase):
    gate = "dead-variants"

    def test_passes_on_names_that_only_look_like_variants(self):
        """The two shapes that produced 21 false positives."""
        self.write("backup_to_remote.sh")
        self.write("tsconfig.node.json")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_refuses_a_trailing_variant_suffix(self):
        self.write("deploy.sh.backup")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("deploy.sh.backup", result.stdout)


class NoChangeDocs(GateCase):
    gate = "no-change-docs"
    config_dir = ".github"

    def test_no_config_dir_refuses(self):
        self.write("a.txt")
        base = self.commit()
        self.write("notes/NEW.md", "# new\n")
        self.assert_refuses_without_a_config_dir(self.commit("second"), base)

    def test_doc_paths_are_read_from_the_config_dir(self):
        """Intent: the gate reads the profile's folder, not a fixed one."""
        self.gate_config(config_dir=".gates")
        self.write(".gates/doc-paths", "notes\n")
        self.write("a.txt")
        base = self.commit()
        self.write("notes/NEW.md", "# new\n")
        self.assertEqual(self.run_gate(self.commit("second"), base).returncode, 0)

    def test_no_base_is_not_a_failure(self):
        self.write("a.txt")
        sha = self.commit()
        result = self.run_gate(sha, "0000000000000000000000000000000000000000")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No comparable base", result.stdout)

    def test_markdown_in_an_allowed_home_passes(self):
        self.write("a.txt")
        base = self.commit()
        self.write("docs/DESIGN.md", "# design\n")
        head = self.commit("second")
        self.assertEqual(self.run_gate(head, base).returncode, 0)

    def test_markdown_at_the_root_is_refused(self):
        self.write("a.txt")
        base = self.commit()
        self.write("WHAT_I_CHANGED.md", "# notes\n")
        head = self.commit("second")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 1)
        self.assertIn("WHAT_I_CHANGED.md", result.stdout)

    def test_generated_markdown_is_exempt_anywhere(self):
        self.write("a.txt")
        base = self.commit()
        self.write("ANYWHERE.md", "<!-- generated from some-profile@abc1234 -->\n")
        head = self.commit("second")
        self.assertEqual(self.run_gate(head, base).returncode, 0)

    def test_markdown_generated_by_another_profile_is_exempt_anywhere(self):
        """Intent: the stamp names the profile that rendered the file, so the gate
        recognises any source name."""
        self.write("a.txt")
        base = self.commit()
        self.write("ANYWHERE.md", "<!-- generated from other-profile@abc1234 -->\n")
        head = self.commit("second")
        self.assertEqual(self.run_gate(head, base).returncode, 0)

    def test_generated_markdown_with_no_sha_in_its_stamp_is_exempt_anywhere(self):
        """Intent: the profile's own render stamps no SHA, and the gate must still
        recognise it as generated."""
        self.write("a.txt")
        base = self.commit()
        self.write("ANYWHERE.md",
                   "<!-- generated from some-profile - edit the source, not this file -->\n")
        head = self.commit("second")
        self.assertEqual(self.run_gate(head, base).returncode, 0)

    def test_generated_markdown_stamped_after_frontmatter_is_exempt(self):
        """Intent: a rendered agent carries its stamp after the frontmatter, and the
        factory bundle renders agents outside .github/, so the stamp alone has to exempt them."""
        self.write("a.txt")
        base = self.commit()
        self.write("factory/rules/qa.agent.md",
                   "---\nname: qa\ndescription: >-\n  QA.\n  More.\ntools: [\"read\"]\n"
                   "---\n\n" + STAMPED)
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ok (generated)", result.stdout)

    def add_after(self, declaration: str, *files: str):
        """Commit a declaration, then the given markdown; return the gate's result."""
        self.write(".github/doc-paths", declaration)
        base = self.commit()
        for rel in files:
            self.write(rel, "# x\n")
        head = self.commit("second")
        return self.run_gate(head, base)

    def test_a_declared_directory_passes(self):
        """A profile source repository keeps its definitions in agents/, not docs/."""
        result = self.add_after("agents\n", "agents/design-partner/definition.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ok (declared)", result.stdout)

    def test_an_undeclared_directory_is_still_refused(self):
        result = self.add_after("agents\n", "skills/new/procedure.md")
        self.assertEqual(result.returncode, 1)
        self.assertIn("REFUSED             skills/new/procedure.md", result.stdout)

    def test_comments_blanks_and_a_trailing_slash_are_honoured(self):
        result = self.add_after("# profile source\n\nskills/  # procedures\n", "skills/a/procedure.md")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_declaration_matches_on_the_directory_boundary(self):
        result = self.add_after("agents\n", "agents-notes.md")
        self.assertEqual(result.returncode, 1)
        self.assertIn("agents-notes.md", result.stdout)

    def test_a_whole_line_comment_declares_nothing(self):
        """Intent: '#' starts a comment. A comment kept and
        split on spaces would declare each of its words; the QA trial found this
        mutation survived ."""
        result = self.add_after("# notes\n", "notes/a.md")
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_an_entry_with_a_space_is_one_directory(self):
        """Intent: one directory per line, so a line is never
        split into several declarations."""
        result = self.add_after("my notes\n", "notes/a.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("REFUSED             notes/a.md", result.stdout)

    def test_a_declared_path_with_a_space_passes(self):
        """Intent: a markdown file inside a declared directory passes whatever its
        name. A path split on its space is two refusals the report never shows."""
        result = self.add_after("my notes\n", "my notes/b.md")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ok (declared)       my notes/b.md", result.stdout)

    def test_a_wildcard_entry_is_literal(self):
        """Intent: an entry names a directory; it is not a glob
        expanded against whatever the working tree holds."""
        result = self.add_after("*\n", "notes/a.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("REFUSED             notes/a.md", result.stdout)


class TestOrphans(GateCase):
    gate = "test-orphans"
    config_dir = ".github"

    def test_no_config_dir_refuses(self):
        self.write("tests/test_thing.py")
        self.commit()
        self.assert_refuses_without_a_config_dir()

    def test_roots_are_read_from_the_config_dir(self):
        self.gate_config(config_dir=".gates")
        self.write("tests/test_thing.py")
        self.write(".gates/test-roots", "tests\n")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_no_tests_and_no_declaration_is_nothing_to_check(self):
        self.write("a.txt")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_tests_with_no_declaration_are_refused(self):
        self.write("tests/test_thing.py")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("no .github/test-roots", result.stdout)

    def test_a_declared_root_covering_the_tests_passes(self):
        self.write("tests/test_thing.py")
        self.write(".github/test-roots", "tests\n")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_a_test_outside_every_root_is_an_orphan(self):
        self.write("tests/test_thing.py")
        self.write("stray/test_loose.py")
        self.write(".github/test-roots", "tests\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ORPHAN", result.stdout)

    def test_a_root_matching_nothing_is_stale(self):
        self.write("tests/test_thing.py")
        self.write(".github/test-roots", "tests\nelsewhere\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("contains no test file", result.stdout)

    def test_declared_none_with_tests_present_is_refused(self):
        self.write("tests/test_thing.py")
        self.write(".github/test-roots", "# none: nothing to test here\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("declares 'none'", result.stdout)

    def test_run_line_is_not_read_as_a_root(self):
        """A run: line holds a command. Read as a root, each is stale."""
        self.write("tests/test_thing.py")
        self.write(".github/test-roots", "tests\nrun: python -m unittest discover -s tests\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_parallel_line_is_not_read_as_a_root(self):
        """A 'parallel: yes' line is a directive. Read as roots, 'parallel:' and 'yes'
        were each stale, and a push adding it was refused."""
        self.write("tests/test_thing.py")
        self.write(".github/test-roots", "tests\nparallel: yes\nrun: python -m unittest\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)


class SecretScan(GateCase):
    gate = "secret-scan"
    # Fixtures are assembled at run time, so no scanner of this repository's own source
    # (the push gate, gitleaks in CI) ever sees a whole credential shape.
    KEY = "0f1e2d3c4b5a6978" + "8796a5b4c3d2e1f0"

    def pushed(self, rel: str, text: str):
        self.write("a.txt")
        base = self.commit()
        self.write(rel, text)
        return self.run_gate(self.commit("second"), base)

    def test_bare_32_hex_is_refused_and_not_printed(self):
        result = self.pushed("docs/NOTES.md", f"| Example | `{self.KEY}` |\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/NOTES.md:1", result.stdout)
        self.assertNotIn(self.KEY, result.stdout + result.stderr)

    def test_env_style_assignment_is_refused(self):
        line = "EXAMPLE_API_" + "KEY=" + "Zq9vXb4Lm2Tp" + "8Rk1Wn6Yc3Hd\n"
        result = self.pushed(".env.sample", line)
        self.assertEqual(result.returncode, 1)

    def test_private_key_header_is_refused(self):
        result = self.pushed("id_ed25519", "-----BEGIN OPENSSH " + "PRIVATE KEY-----\n")
        self.assertEqual(result.returncode, 1)

    def test_near_misses_pass(self):
        """Every shape a tree-wide scan produced on 2026-09-26 that was not a key."""
        text = (
            "commit 2908d1d8368d6e3f452f4849618875171f212cee\n"
            "Preparing: C:\\67c9e3a1b2c4d5e6f708192a3b4c5d6e\\netfx.msi\n"
            "https://example.com/pr/7afca223-55d2-470a-8edc-6a1739ae3252/abd1\n"
            'EXAMPLE_KEY="/usr/share/keyrings/example-archive-keyring.gpg"\n'
            "EXAMPLEHOST_JWT_SECRET=your-long-random-secret-here-please\n"
            "RUNNER_API_KEY=ci-validation-placeholder-value\n"
        )
        result = self.pushed("notes.txt", text)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_allow_marker_exempts_a_line(self):
        result = self.pushed("t.py", f'KEY = "{self.KEY}"  # secret-scan: allow - fixture\n')
        self.assertEqual(result.returncode, 0)

    def test_only_added_lines_are_scanned(self):
        self.write("old.md", f"`{self.KEY}`\n")
        base = self.commit()
        self.write("new.txt", "clean\n")
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0)


class SecretDefaults(GateCase):
    gate = "secret-defaults"
    # The editor hook and this gate must agree line for line - the gate cannot
    # import the hook, because hooks/ is not rendered into target repos.
    CASES = (
        ("      - EXAMPLE_API_KEY=${EXAMPLE_API_KEY:-}", True),
        ("      - JWT_SECRET=${JWT_SECRET:-changeme}", True),
        ("      - OTHER_API_KEY=${OTHER_API_KEY-}", True),
        ("      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET must be set}", False),
        ("      - LOG_LEVEL=${LOG_LEVEL:-info}", False),
        ("      - PORT=3001", False),
    )

    def test_each_case_matches_the_editor_hook(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check", ROOT / "hooks" / "no-secret-defaults" / "check.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        rule = dict(hook.RULES)["Shell/Compose default on a secret"]
        for line, refused in self.CASES:
            with self.subTest(line=line):
                self.assertEqual(bool(rule.search(line)), refused, "hook")
                self.write("compose.yml", f"services:\n  a:\n    environment:\n{line}\n")
                self.commit(line)
                self.assertEqual(self.run_gate().returncode, 1 if refused else 0, "gate")

    def test_refusal_names_file_and_line(self):
        self.write("stack/compose.yaml", "x: 1\n      - API_TOKEN=${API_TOKEN:-}\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("stack/compose.yaml:2", result.stdout)

    def test_allow_marker_exempts_a_line(self):
        self.write("compose.yml", "      - AUTH_MODE=${AUTH_MODE:-cookie}  # no-secret-defaults: allow\n")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)


@unittest.skipIf(shutil.which("npm") is None, "npm not on PATH; not reporting a pass")
class Lockfile(GateCase):
    gate = "lockfile"

    def lock(self, dep_range: str, locked: str) -> None:
        self.write("app/package.json",
                   '{"name": "a", "version": "1.0.0", "dependencies": {"left-pad": "%s"}}\n' % dep_range)
        self.write("app/package-lock.json", (
            '{"name": "a", "version": "1.0.0", "lockfileVersion": 3, "requires": true, "packages": {'
            '"": {"name": "a", "version": "1.0.0", "dependencies": {"left-pad": "%s"}},'
            '"node_modules/left-pad": {"version": "%s"}}}\n') % (dep_range, locked))

    def test_no_lockfile_is_nothing_to_check(self):
        self.write("a.txt")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_valid_tree_passes(self):
        self.lock("^1.3.0", "1.3.0")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("every tree valid", result.stdout)

    def test_locked_version_outside_the_manifest_range_is_refused(self):
        """The shape a broken lockfile has: npm ci passed, npm ls did not."""
        self.lock("^2.0.0", "1.3.0")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid tree in app", result.stdout)


class Tests(GateCase):
    gate = "tests"
    config_dir = ".github"

    def test_no_config_dir_refuses(self):
        self.write("run.txt")
        self.commit()
        self.assert_refuses_without_a_config_dir()

    def test_run_lines_are_read_from_the_config_dir(self):
        self.gate_config(config_dir=".gates")
        self.write(".gates/test-roots", "run: echo from-gates-dir\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("from-gates-dir", result.stdout)

    def test_no_tests_and_no_declaration_is_nothing_to_run(self):
        self.write("a.txt")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_roots_without_a_run_line_are_refused(self):
        self.write("tests/test_thing.py")
        self.write(".github/test-roots", "tests\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not how to run them", result.stdout)

    def test_declared_none_passes(self):
        self.write(".github/test-roots", "# none: provisioning scripts only\n")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 0)

    def test_commented_run_line_is_not_a_command(self):
        self.write("tests/test_thing.py")
        self.write(".github/test-roots", "tests\n# run: true\n")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 1)

    def test_passing_command_passes_and_is_named(self):
        self.write(".github/test-roots", "run: echo suite-ok\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0)
        self.assertIn("run: echo suite-ok", result.stdout)

    def test_each_command_sees_the_push_range(self):
        """Intent: a suite can choose its own tests from what the push changed,
        without the gate knowing anything about how it chooses."""
        self.write(".github/test-roots",
                   'run: echo "$PUSH_REMOTE_SHA..$PUSH_LOCAL_SHA" > range.out\n')
        first = self.commit()
        self.write("b.txt")
        second = self.commit()
        result = self.run_gate(second, first)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.repo / "range.out").read_text(encoding="utf-8").strip(),
                         f"{first}..{second}")

    def test_each_command_reports_its_seconds_and_timing_lines(self):
        """Intent: the gate report says how long each suite took and which
        classes were slowest, so  can choose from real pushes."""
        self.write(".github/test-roots", "run: echo 'timing:    0.42 s  mod.Slow'; echo noise\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, r"pass \(\d+ s\)")
        self.assertIn("timing:    0.42 s  mod.Slow", result.stdout)
        carried = [ln for ln in result.stdout.splitlines() if not ln.startswith("run:")]
        self.assertFalse([ln for ln in carried if "noise" in ln],
                         "only timing lines are carried, not the suite's other output")

    def test_a_suites_selected_line_is_carried(self):
        """Intent: the report says what a push chose
        to run and why, beside the timing of each class it ran."""
        self.write(".github/test-roots",
                   "run: echo 'selected: 12 of 113 class(es) - 3 changed file(s)'; echo noise\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        # The gate echoes each command line, which contains the text too; only carried lines count.
        carried = [ln.strip() for ln in result.stdout.splitlines() if not ln.startswith("run:")]
        self.assertIn("selected: 12 of 113 class(es) - 3 changed file(s)", carried)
        self.assertFalse([ln for ln in carried if "noise" in ln])

    def test_failing_command_is_refused_with_its_output(self):
        """The case the typecheck gate gets wrong: output that would be piped."""
        self.write(".github/test-roots", "run: echo boom-output; exit 3\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("exit 3", result.stdout)
        self.assertIn("boom-output", result.stdout)

    def test_every_command_runs_even_after_one_fails(self):
        self.write(".github/test-roots", "run: exit 1\nrun: echo second-ran\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("run: echo second-ran", result.stdout)

    def test_a_command_reading_stdin_does_not_swallow_the_rest(self):
        self.write(".github/test-roots", "run: cat\nrun: echo still-here\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0)
        self.assertIn("run: echo still-here", result.stdout)

    def rendered_push(self, *plain: str):
        """A failing suite, then a range adding a stamped file plus any plain files named."""
        self.write(".github/test-roots", "run: exit 1\n")
        base = self.commit()
        self.write("AGENTS.md", STAMPED)
        for rel in plain:
            self.write(rel, "plain\n")
        return self.run_gate(self.commit("second"), base)

    def test_a_rendered_only_range_skips_the_suite(self):
        """Intent: rendered output alone cannot change this repo's tests."""
        result = self.rendered_push()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skipped: every file in", result.stdout)

    def test_output_stamped_by_another_profile_skips_the_suite(self):
        """Intent: the rendered-only skip keys off the stamp, which names the profile
        that rendered it. Any profile must skip exactly as any other does."""
        self.write(".github/test-roots", "run: exit 1\n")
        base = self.commit()
        self.write("AGENTS.md", STAMPED.replace("some-profile@", "other-profile@"))
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skipped: every file in", result.stdout)

    def test_output_with_no_sha_in_its_stamp_skips_the_suite(self):
        """Intent: the profile's own render stamps no SHA, so the rendered-only skip
        has to recognise that form too, or every self-render would run this repo's tests."""
        self.write(".github/test-roots", "run: exit 1\n")
        base = self.commit()
        self.write("AGENTS.md", STAMPED.replace("@abc1234", ""))
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skipped: every file in", result.stdout)

    def test_one_unstamped_file_in_the_range_runs_the_suite(self):
        """Intent: the skip needs every file in the range to be rendered output."""
        self.assertEqual(self.rendered_push("src/app.py").returncode, 1)

    def test_the_rendered_repo_list_alone_skips_the_suite(self):
        """Intent: the repo list is rendered output like any other rendered file, so a
        rollout that changes only it must not run this repo's tests."""
        manifest = {"source": {"owner": "SomeOwner", "repo": "profile-source"}}
        sync.set_stamp_source(manifest)
        self.write(".github/test-roots", "run: exit 1\n")
        base = self.commit()
        self.write(sync.REPO_LIST, sync.render_repo_list(manifest, "abc1234"))
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skipped: every file in", result.stdout)

    def test_gitignore_beside_rendered_files_still_skips(self):
        """Intent: sync adds scratch/ to .gitignore in the same commit."""
        self.assertEqual(self.rendered_push(".gitignore").returncode, 0)

    def test_a_new_branch_runs_the_suite(self):
        """Intent: an all-zero remote sha has no range to judge."""
        self.write(".github/test-roots", "run: exit 1\n")
        self.write("AGENTS.md", STAMPED)
        self.assertEqual(self.run_gate(self.commit(), "0" * 40).returncode, 1)

    def test_a_stamp_below_long_frontmatter_counts(self):
        """Intent: rendered agents carry the stamp after multi-line frontmatter."""
        self.write(".github/test-roots", "run: exit 1\n")
        base = self.commit()
        front = "---\n" + "".join(f"key{i}: value\n" for i in range(12)) + "---\n"
        self.write(".github/agents/x.agent.md", front + STAMPED)
        self.assertEqual(self.run_gate(self.commit("second"), base).returncode, 0)

    def test_deleting_a_rendered_file_counts_as_rendered(self):
        """Intent: a rollout removes orphans, which are stamped on the old side."""
        self.write(".github/test-roots", "run: exit 1\n")
        self.write("old.md", STAMPED)
        base = self.commit()
        (self.repo / "old.md").unlink()
        self.assertEqual(self.run_gate(self.commit("second"), base).returncode, 0)

    def test_a_stamp_deep_in_a_file_does_not_count(self):
        """Intent: the stamp is a header; a document quoting it is not output."""
        self.write(".github/test-roots", "run: exit 1\n")
        base = self.commit()
        self.write("docs/notes.md", "line\n" * 50 + STAMPED)
        self.assertEqual(self.run_gate(self.commit("second"), base).returncode, 1)

    # --- the 'parallel:' line caps how many commands run at once ---

    # Each command drops a marker, records how many markers exist, holds for a second,
    # then removes its marker. The largest recorded count is the most that ran together.
    MARKED = "touch m/$$ ; echo $(ls m | wc -l) >> counts.txt ; sleep 1 ; rm m/$$"

    def marked_suite(self, parallel_lines: str, commands: int = 4) -> None:
        """Writes test-roots with the given 'parallel:' text and N marker-recording commands."""
        (self.repo / "m").mkdir(exist_ok=True)
        self.write(".github/test-roots",
                   parallel_lines + "".join(f"run: {self.MARKED}\n" for _ in range(commands)))
        self.commit()

    def largest_count(self) -> int:
        """The most commands that were running at once, from the counts the markers left."""
        counts = (self.repo / "counts.txt").read_text(encoding="utf-8").split()
        return max(int(c) for c in counts)

    def stub(self, name: str, output: str) -> str:
        """A directory holding an executable 'name' that prints output; returned for PATH."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = Path(folder) / name
        path.write_text(f"#!/bin/sh\n{'echo ' + output if output else 'exit 0'}\n",
                        encoding="utf-8", newline="\n")
        path.chmod(0o755)
        return folder

    def test_parallel_n_runs_no_more_than_n_at_once(self):
        """Intent: the gate used to start every command together, and 38 at once
        starved three suites into their own time limits."""
        self.marked_suite("parallel: 2\n")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertLessEqual(self.largest_count(), 2, result.stdout)
        # A cap that quietly became serial would pass the line above.
        self.assertGreaterEqual(self.largest_count(), 2, result.stdout)

    def test_the_summary_names_the_cap(self):
        """Intent: the report says how many ran at once, in place of 'concurrently'."""
        self.marked_suite("parallel: 2\n")
        result = self.run_gate()
        self.assertIn("ran 4 command(s), at most 2 at once", result.stdout)

    def test_parallel_yes_caps_at_the_cpu_count(self):
        """Intent: 'yes' no longer means unlimited."""
        self.marked_suite("parallel: yes\n")
        result = self.run_gate(path_prefix=self.stub("nproc", "2"))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertLessEqual(self.largest_count(), 2, result.stdout)
        # A build that ignored the stub and ran serially would pass the line above.
        self.assertGreaterEqual(self.largest_count(), 2, "the CPU count was read, not skipped")

    def test_parallel_yes_never_exceeds_16(self):
        """Intent: ruled 'yes' is one per CPU and no more than 16.
        Measured on a 39-command suite, 36 at once saved 4 percent over 16 and
        more than doubled the load. The summary is asserted, not a count of running
        commands: starting 17 overlapping ones under Git Bash is not reliable."""
        self.marked_suite("parallel: yes\n", commands=2)
        result = self.run_gate(path_prefix=self.stub("nproc", "40"))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ran 2 command(s), at most 16 at once", result.stdout)

    def test_parallel_yes_at_16_cpus_uses_all_16(self):
        """Characterisation: the ceiling must not trim a machine at it. Passes at the base,
        so it guards  rather than proves it."""
        self.marked_suite("parallel: yes\n", commands=2)
        result = self.run_gate(path_prefix=self.stub("nproc", "16"))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ran 2 command(s), at most 16 at once", result.stdout)

    def test_parallel_no_and_one_run_serially(self):
        """Characterisation: the new parser must keep 'no' and '1' serial. Both pass at the
        base, so they guard  rather than prove it."""
        for line in ("parallel: no\n", "parallel: 1\n"):
            with self.subTest(line=line):
                (self.repo / "counts.txt").unlink(missing_ok=True)
                self.marked_suite(line, commands=2)
                result = self.run_gate()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.largest_count(), 1, result.stdout)

    def test_the_parallel_key_and_value_ignore_case_and_padding(self):
        """Intent: 'Parallel:   2   ' is the same line as 'parallel: 2'."""
        self.marked_suite("  Parallel:   2   \n")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertLessEqual(self.largest_count(), 2, result.stdout)
        self.assertGreaterEqual(self.largest_count(), 2, "the line was read, not skipped")

    def test_a_malformed_or_repeated_parallel_line_is_refused_before_anything_runs(self):
        """Intent: a line the gate cannot read must never decide how the suite
        runs. Each of these used to run serially and say nothing."""
        cases = {
            "zero": "parallel: 0\n",
            "negative": "parallel: -2\n",
            "word": "parallel: lots\n",
            "trailing text": "parallel: 8 please\n",
            "empty": "parallel:\n",
            "repeated and agreeing": "parallel: 2\nparallel: 2\n",
            "repeated and disagreeing": "parallel: 2\nparallel: yes\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.repo / "m", ignore_errors=True)
                (self.repo / "counts.txt").unlink(missing_ok=True)
                self.marked_suite(text, commands=2)
                result = self.run_gate()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("REFUSED:", result.stdout)
                self.assertIn(text.splitlines()[0].strip(), result.stdout,
                              "the refusal quotes the line")
                self.assertFalse((self.repo / "counts.txt").exists(),
                                 "no command may have run before the refusal")

    def test_an_unreadable_cpu_count_runs_serially_and_says_so(self):
        """Intent: serial is always safe; uncapped never is."""
        self.marked_suite("parallel: yes\n")
        silent = os.pathsep.join((self.stub("nproc", ""), self.stub("getconf", "")))
        result = self.run_gate(path_prefix=silent)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("parallel: yes, but the CPU count could not be read - running serially",
                      result.stdout)
        self.assertEqual(self.largest_count(), 1, result.stdout)


class Typecheck(GateCase):
    gate = "typecheck"

    def test_no_typescript_is_a_pass(self):
        self.write("a.py")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0)
        self.assertIn("No TypeScript files", result.stdout)

    def test_typescript_with_no_tsconfig_anywhere_is_refused(self):
        self.write("src/main.ts", "export const x = 1;\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("no tsconfig anywhere", result.stdout)

    def test_a_rendered_only_range_skips_typecheck(self):
        """Intent: the refusal above does not fire on a range of rendered output."""
        self.write("src/main.ts", "export const x = 1;\n")
        base = self.commit()
        self.write("AGENTS.md", STAMPED)
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skipped: every file in", result.stdout)

    def test_typescript_outside_every_tsconfig_is_refused(self):
        self.write("app/tsconfig.json", "{}\n")
        self.write("app/main.ts", "export const x = 1;\n")
        self.write("loose/other.ts", "export const y = 2;\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("loose/other.ts", result.stdout)

    def test_covered_typescript_without_a_package_json_is_not_checked_and_says_so(self):
        self.write("app/tsconfig.json", "{}\n")
        self.write("app/main.ts", "export const x = 1;\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0)
        self.assertIn("No project has a package.json", result.stdout)

    def test_missing_dependencies_fail_rather_than_pass_silently(self):
        self.write("app/tsconfig.json", "{}\n")
        self.write("app/package.json", '{"name":"a","version":"1.0.0"}\n')
        self.write("app/main.ts", "export const x = 1;\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Dependencies are not installed", result.stdout)

    # A fake npx on PATH stands in for tsc: it records the -p config it was given
    # and exits as tsc would. The real one proved the bug on 2026-09-26 - a planted
    # error printed TS2322 and the gate still said clean. .
    FAKE_NPX = (
        "#!/bin/sh\n"
        'while [ $# -gt 0 ]; do [ "$1" = -p ] && echo "$2" >> "$NPX_LOG"; shift; done\n'
        'printf "%s" "$NPX_OUTPUT"\n'
        'exit "$NPX_EXIT"\n'
    )

    def project(self, tsconfig: str = "{}\n") -> None:
        self.write("app/tsconfig.json", tsconfig)
        self.write("app/package.json", '{"name":"a","version":"1.0.0"}\n')
        self.write("app/main.ts", "export const x = 1;\n")
        (self.repo / "app" / "node_modules").mkdir()
        self.commit()

    def run_tsc(self, exit_code: int, output: str = ""):
        bin_dir = self.repo / ".fakebin"
        bin_dir.mkdir(exist_ok=True)
        npx = bin_dir / "npx"
        npx.write_text(self.FAKE_NPX, encoding="utf-8", newline="\n")
        npx.chmod(0o755)
        self.npx_log = self.repo / ".npx.log"
        os.environ.update(NPX_LOG=self.npx_log.as_posix(), NPX_OUTPUT=output,
                          NPX_EXIT=str(exit_code))
        self.addCleanup(lambda: [os.environ.pop(k, None)
                                 for k in ("NPX_LOG", "NPX_OUTPUT", "NPX_EXIT")])
        return self.run_gate(path_prefix=str(bin_dir))

    def checked(self) -> list[str]:
        return self.npx_log.read_text(encoding="utf-8").split() if self.npx_log.exists() else []

    def test_a_type_error_fails_the_gate(self):
        self.project()
        result = self.run_tsc(2, "main.ts(1,7): error TS2322: Type 'string' is not assignable\n")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Type errors in:", result.stdout)
        self.assertIn("error TS2322", result.stdout)

    def test_tsc_that_cannot_run_is_its_own_failure(self):
        self.project()
        result = self.run_tsc(1, "Could not determine Node.js install directory\n")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("tsc could not run in:", result.stdout)
        self.assertNotIn("type-check clean", result.stdout)

    def test_a_clean_check_passes(self):
        self.project()
        result = self.run_tsc(0)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.checked(), ["tsconfig.json"])

    def test_each_reference_of_a_solution_tsconfig_is_checked(self):
        """A solution-style root tsconfig is "files": [] with references, so tsc -p on it
        checks nothing. The gate has to check each referenced config."""
        self.project('{"files": [], "references": [{"path": "./tsconfig.app.json"},'
                     ' {"path": "./tsconfig.node.json"}]}\n')
        ts = self.repo / "app" / "node_modules" / "typescript"
        ts.mkdir(parents=True)
        (ts / "index.js").write_text(
            'const fs = require("fs");\n'
            "module.exports = { sys: { readFile: p => fs.readFileSync(p, 'utf8') },\n"
            "  readConfigFile: (p, read) => ({ config: JSON.parse(read(p)) }) };\n",
            encoding="utf-8")
        result = self.run_tsc(0)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.checked(), ["./tsconfig.app.json", "./tsconfig.node.json"])


class PrePushCase(GateCase):
    """The hook itself, end to end against a local bare remote."""

    def setUp(self):
        super().setUp()
        self.remote = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.remote, ignore_errors=True)
        subprocess.run(("git", "init", "-q", "--bare", str(self.remote)), check=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.gate_config(deploy_branch="main", identity_email="t@t")

    def push(self, sha: str, branch: str = "main", remote_sha: str = "0" * 40):
        hook = (GATES.parent / "pre-push.sh").as_posix()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
        return subprocess.run([SH, hook, "origin"], cwd=self.repo, env=env, text=True,
                              capture_output=True, timeout=120,
                              input=f"refs/heads/{branch} {sha} refs/heads/{branch} {remote_sha}\n")

    def enabled(self, *names: str) -> None:
        """The rendered .githooks/gates/enabled, as sync.py writes it from the lock."""
        self.write(".githooks/gates/enabled",
                   "# generated from some-profile@abc1234\n" + "".join(f"{n}\n" for n in names))

    def reports(self) -> list[dict]:
        tags = subprocess.run(("git", "--git-dir", str(self.remote), "for-each-ref",
                               "--format=%(refname)", "refs/tags/gate-report/"),
                              capture_output=True, text=True).stdout.split()
        return [json.loads(subprocess.run(("git", "--git-dir", str(self.remote), "show",
                                           f"{tag}:report.json"),
                                          capture_output=True, text=True).stdout)
                for tag in tags]


class PrePushReport(PrePushCase):
    """What the hook publishes, and which branch a failing gate blocks."""

    def test_git_config_cannot_move_the_deploy_branch(self):
        """Intent: `git config gate.deployBranch x` leaves a failing gate
        blocking main."""
        self.write(".githooks/gates/red.sh", "echo red\nexit 1\n")
        self.enabled("red")
        sha = self.commit()
        self.git("config", "gate.deployBranch", "nothing")
        result = self.push(sha)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("main is the deploy branch", result.stderr)

    def test_a_failing_gate_on_another_branch_still_pushes(self):
        """Characterisation: pre-push.sh blocks only the deploy branch, and reading the branch
        from the rendered file must not make every branch the deploy branch."""
        self.write(".githooks/gates/red.sh", "echo red\nexit 1\n")
        self.enabled("red")
        sha = self.commit()
        self.assertEqual(self.push(sha, "feature").returncode, 0)

    def test_no_gate_config_refuses_the_push(self):
        """Intent: fail closed when the rendered file is missing. Defaulting to
        main would make deleting the file a way to move the deploy branch."""
        self.write(".githooks/gates/green.sh", "echo green\n")
        self.enabled("green")
        (self.repo / ".githooks" / "gate-config").unlink()
        sha = self.commit()
        result = self.push(sha, "feature")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("gate-config", result.stderr)

    def test_report_records_each_gates_seconds_and_the_total(self):
        """Intent: a stub gate that sleeps 1 s is recorded with
        seconds >= 1, and the report carries the hook's total."""
        self.write(".githooks/gates/slow.sh", "sleep 1\necho slept\n")
        self.write(".githooks/gates/quick.sh", "echo quick\n")
        self.enabled("quick", "slow")
        sha = self.commit()

        result = self.push(sha)

        self.assertEqual(result.returncode, 0, result.stderr)
        reports = self.reports()
        self.assertEqual(len(reports), 1, reports)
        report = reports[0]
        self.assertGreaterEqual(report["gates"]["slow"]["seconds"], 1)
        self.assertIn("seconds", report["gates"]["quick"])
        self.assertGreaterEqual(report["seconds"], report["gates"]["slow"]["seconds"])


class PrePushFlags(PrePushCase):
    """The hook runs only the gates the pushed commit's enabled list names, and in
    the profile repo refuses a lock that disagrees with features:."""

    EXERCISES = ["githooks/**", "consent.py"]

    def setUp(self):
        super().setUp()
        self.write(".githooks/gates/green.sh", "echo green\n")
        self.write(".githooks/gates/off.sh", "echo ran > ran-off\n")

    def test_an_unlisted_gate_is_not_run_and_is_named(self):
        """Intent: the runner runs only enabled gates and names each
        skipped one, on the terminal and in the report CI reads."""
        self.enabled("green")
        result = self.push(self.commit(), "feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo / "ran-off").exists(), "a disabled gate ran")
        self.assertIn("skipped off (off in profile.lock)", result.stderr)
        report = self.reports()[0]
        self.assertEqual(report["skipped"], ["off"])
        self.assertEqual(set(report["gates"]), {"green"})

    def test_the_pushed_list_is_used_not_the_working_tree(self):
        """Intent: CI reads the pushed commit's list, so the hook must too - an uncommitted
        edit to the list must not decide what runs."""
        self.enabled("green")
        sha = self.commit()
        self.enabled("green", "off")
        self.push(sha, "feature")
        self.assertFalse((self.repo / "ran-off").exists(), "the working-tree list was used")

    def test_a_listed_gate_with_no_script_fails(self):
        """Intent: unknown is not zero - a gate the list requires and nothing runs is a
        failure, not a gate that passed by being absent."""
        self.enabled("green", "missing")
        result = self.push(self.commit())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("missing FAILED", result.stderr)

    def test_a_listed_name_that_is_not_a_gate_name_fails_without_running_anything(self):
        """Intent: validate every externally supplied value before it reaches a path - a
        forged '*' must not glob, and '../x' must not leave the gates directory."""
        self.enabled("green", "*", "../off")
        result = self.push(self.commit())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse((self.repo / "ran-off").exists())
        self.assertIn("not a gate name", result.stderr)

    def test_no_enabled_list_refuses_the_push(self):
        """Intent: fail closed. Running every script or none would both be a
        guess at what was consented to."""
        result = self.push(self.commit(), "feature")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(".githooks/gates/enabled", result.stderr)
        self.assertFalse((self.repo / "ran-off").exists())

    def test_a_flag_change_since_the_remote_commit_is_printed_and_reported(self):
        """Intent: every flag change is printed in the pre-push report."""
        self.enabled("green", "off")
        before = self.commit()
        self.enabled("green")
        result = self.push(self.commit(), "feature", remote_sha=before)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("flag changed: off: on -> off", result.stderr)
        self.assertEqual(self.reports()[0]["flag_changes"], ["off: on -> off"])

    def test_an_empty_enabled_list_says_no_gates_enabled(self):
        """Intent: a push that runs nothing says so, so a repo is never believed gated when
        its list is empty."""
        self.enabled()
        result = self.push(self.commit(), "feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pre-push: no gates enabled - this push is not checked", result.stderr)
        self.assertFalse((self.repo / "ran-off").exists())

    def test_a_non_empty_list_does_not_say_no_gates_enabled(self):
        self.enabled("green")
        result = self.push(self.commit(), "feature")
        self.assertNotIn("no gates enabled", result.stderr)

    def test_each_gate_run_gets_one_line(self):
        """Intent: the terminal names every gate that ran and how it ended."""
        self.write(".githooks/gates/red.sh", "echo red\nexit 1\n")
        self.enabled("green", "red")
        result = self.push(self.commit(), "feature")
        self.assertRegex(result.stderr, r"pre-push: green passed \(\d+s\)")
        self.assertIn("pre-push: red FAILED", result.stderr)

    def test_a_new_branch_with_nothing_to_compare_says_so(self):
        """Intent: silence would read as 'no flag changed'."""
        self.enabled("green")
        result = self.push(self.commit(), "feature")
        self.assertIn("no earlier pushed list to compare", result.stderr)
        self.assertEqual(self.reports()[0]["flag_changes"], [])

    def profile_repo(self, consented: dict, declared: dict) -> str:
        """A profile repo: the real consent.py, a lock of `consented` and features: of
        `declared`, and gate-config naming the check as the self-render writes it."""
        shutil.copy(ROOT / "consent.py", self.repo / "consent.py")
        for name in consented:
            self.write(f"githooks/gates/{name}.sh", "exit 0\n")
        self.write("profile.yaml", consent.render_features_block(declared))
        self.write(consent.LOCK_NAME, consent.render_lock({"gates": consented}))
        self.gate_config(deploy_branch="main", identity_email="t@t", consent_check="consent.py")
        self.enabled(*sorted(n for n, on in consented.items() if on))
        return self.commit()

    def test_the_profile_repo_refuses_a_hand_edited_flag_naming_it(self):
        """Intent: a features: edit without the consent command fails the
        next push, naming the flag, on any branch."""
        sha = self.profile_repo({"green": True, "off": True}, {"green": True, "off": False})
        result = self.push(sha, "feature")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("disagree", result.stderr)
        self.assertIn("off", result.stderr)
        self.assertEqual(self.reports(), [])

    def test_the_profile_repo_passes_a_consented_lock(self):
        sha = self.profile_repo({"green": True, "off": False}, {"green": True, "off": False})
        result = self.push(sha, "feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.reports()[0]["skipped"], ["off"])

    def test_a_target_trusts_its_list_without_a_consent_check(self):
        """Intent: a target has no lock and no consent.py; the rendered list is
        what it runs."""
        self.write("profile.yaml", "not: checked\n")
        self.enabled("green")
        result = self.push(self.commit(), "feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("disagree", result.stderr)


# The base classes hold no test of their own and must not run as cases.
del GateCase, PrePushCase


if __name__ == "__main__":
    unittest.main(verbosity=2)
