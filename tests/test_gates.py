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

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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

    def test_vendored_core_tests_are_not_the_profiles_own(self):
        """Intent: where core/VENDORED exists, core/tests/ is the core's suite, run upstream.
        A profile with no tests of its own passes, and says so."""
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tests/test_core_thing.py")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("vendored", result.stdout)

    def test_vendored_core_tests_need_no_root_beside_a_declaration(self):
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tests/test_core_thing.py")
        self.write("tests/test_own.py")
        self.write(".github/test-roots", "tests\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("core/tests", result.stdout)

    def test_a_core_folder_with_no_vendored_marker_still_counts(self):
        self.write("core/tests/test_thing.py")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("core/tests/test_thing.py", result.stdout)

    def test_a_profiles_own_tests_still_count_beside_a_vendored_core(self):
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tests/test_core_thing.py")
        self.write("tests/test_own.py")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("tests/test_own.py", result.stdout)
        self.assertNotIn("core/tests/test_core_thing.py", result.stdout)


class SecretScan(GateCase):
    gate = "secret-scan"
    # Fixtures are assembled at run time, so no scanner of this repository's own source
    # (the push gate, gitleaks in CI) ever sees a whole credential shape.
    FAKE_HEX = "0f1e2d3c4b5a6978" + "8796a5b4c3d2e1f0"

    def pushed(self, rel: str, text: str):
        self.write("a.txt")
        base = self.commit()
        self.write(rel, text)
        return self.run_gate(self.commit("second"), base)

    def test_bare_32_hex_is_refused_and_not_printed(self):
        result = self.pushed("docs/NOTES.md", f"| Example | `{self.FAKE_HEX}` |\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/NOTES.md:1", result.stdout)
        self.assertNotIn(self.FAKE_HEX, result.stdout + result.stderr)

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
        result = self.pushed("t.py", f'VALUE = "{self.FAKE_HEX}"  # secret-scan: allow - fixture\n')
        self.assertEqual(result.returncode, 0)

    def test_only_added_lines_are_scanned(self):
        self.write("old.md", f"`{self.FAKE_HEX}`\n")
        base = self.commit()
        self.write("new.txt", "clean\n")
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0)

    ZEROS = "0" * 40

    def deploy_branch_with_old_match(self, configured: bool = True) -> str:
        """A deploy branch whose tip already carries a matching line, tracked as origin/main."""
        if configured:
            self.gate_config(deploy_branch="main")
        self.write("old.md", f"`{self.FAKE_HEX}`\n")
        tip = self.commit("deploy")
        self.git("update-ref", "refs/remotes/origin/main", tip)
        return tip

    def test_new_branch_scans_from_the_merge_base(self):
        """Intent: lines already on the deploy branch are not new on a branch cut from it."""
        self.deploy_branch_with_old_match()
        self.write("new.txt", "clean\n")
        result = self.run_gate(self.commit("branch"), self.ZEROS)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("scanning from merge-base with origin/main", result.stdout)

    def test_new_branch_adding_a_match_is_refused(self):
        self.deploy_branch_with_old_match()
        self.write("added.md", f"`{self.FAKE_HEX}`\n")
        result = self.run_gate(self.commit("branch"), self.ZEROS)
        self.assertEqual(result.returncode, 1)
        self.assertIn("added.md:1", result.stdout)
        self.assertNotIn("old.md", result.stdout)

    def test_new_branch_at_the_deploy_tip_has_an_empty_diff(self):
        tip = self.deploy_branch_with_old_match()
        result = self.run_gate(tip, self.ZEROS)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_new_branch_uses_the_remote_named_by_the_third_argument(self):
        tip = self.deploy_branch_with_old_match()
        self.git("update-ref", "refs/remotes/upstream/main", tip)
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.write("new.txt", "clean\n")
        result = self.run_gate(self.commit("branch"), self.ZEROS, "upstream")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("merge-base with upstream/main", result.stdout)

    def test_new_branch_with_no_deploy_branch_configured_scans_everything(self):
        self.deploy_branch_with_old_match(configured=False)
        self.write("new.txt", "clean\n")
        result = self.run_gate(self.commit("branch"), self.ZEROS)
        self.assertEqual(result.returncode, 1)
        self.assertIn("old.md:1", result.stdout)
        self.assertIn("scanning the whole history (new branch, no merge base)", result.stdout)

    def test_new_branch_with_no_remote_tracking_ref_scans_everything(self):
        self.deploy_branch_with_old_match()
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.write("new.txt", "clean\n")
        result = self.run_gate(self.commit("branch"), self.ZEROS)
        self.assertEqual(result.returncode, 1)
        self.assertIn("old.md:1", result.stdout)

    def test_new_branch_with_orphan_history_scans_everything(self):
        self.deploy_branch_with_old_match()
        self.git("checkout", "-q", "--orphan", "island")
        self.write("island.md", f"`{self.FAKE_HEX}`\n")
        result = self.run_gate(self.commit("island"), self.ZEROS)
        self.assertEqual(result.returncode, 1)
        self.assertIn("island.md:1", result.stdout)
        self.assertIn("scanning the whole history (new branch, no merge base)", result.stdout)

    def test_existing_branch_still_scans_only_its_own_diff(self):
        tip = self.deploy_branch_with_old_match()
        self.write("new.txt", "clean\n")
        result = self.run_gate(self.commit("branch"), tip)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("scanning", result.stdout)


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

    def test_vendored_core_tests_are_not_the_profiles_own(self):
        """Intent: where core/VENDORED exists, core/tests/ is the core's suite, run upstream.
        A profile with no tests of its own passes, and says so."""
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("core/tests/test_core_thing.py")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("vendored", result.stdout)

    def test_a_core_folder_with_no_vendored_marker_still_counts(self):
        self.write("core/tests/test_thing.py")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 1)

    def test_a_profiles_own_tests_still_need_a_declaration_beside_a_vendored_core(self):
        self.write("core/VENDORED", "source: acme/toolbox\n")
        self.write("tests/test_own.py")
        self.commit()
        self.assertEqual(self.run_gate().returncode, 1)

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


def path_without(*tools: str, python: bool = True) -> str | None:
    """A PATH holding only the shell, git and (optionally) python, or None where one of
    `tools` lives in one of those folders and so cannot be taken away."""
    dirs: list[str] = []
    for exe in (SH, shutil.which("python") if python else None, shutil.which("git")):
        if exe and str(Path(exe).parent) not in dirs:
            dirs.append(str(Path(exe).parent))
    path = os.pathsep.join(dirs)
    if any(shutil.which(tool, path=path) for tool in tools):
        return None
    if not python and shutil.which("python", path=path):
        return None
    return path


class LintCase(GateCase):
    """Shared by the gates that lint a push against a committed baseline."""

    config_dir = "cfg"

    def baseline(self, tool: str, entries: dict[str, int]) -> None:
        self.write(f"cfg/lint-baseline/{tool}.json", json.dumps(entries) + "\n")

    def run_without(self, tool: str, *args: str):
        path = path_without(tool)
        if path is None:
            self.skipTest(f"{tool} lives beside python, git or sh here; cannot hide it")
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            return self.run_gate(*args)

    def assert_nothing_to_check(self, result) -> None:
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Nothing to check", result.stdout)


class Ruff(LintCase):
    gate = "ruff"
    DIRTY = "import os\n"

    def test_no_python_in_the_push_is_a_pass(self):
        self.write("notes.txt")
        self.assert_nothing_to_check(self.run_gate(self.commit()))

    def test_a_missing_ruff_is_refused_with_how_to_install_it(self):
        self.write("a.py", self.DIRTY)
        result = self.run_without("ruff", self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("ruff is not installed", result.stdout)
        self.assertIn("pip install ruff", result.stdout)

    def test_a_missing_ruff_does_not_matter_when_no_python_changed(self):
        self.write("notes.txt")
        result = self.run_without("ruff", self.commit())
        self.assert_nothing_to_check(result)

    # The gate checks for ruff before it reads gate-config, so without ruff this refuses
    # for the missing tool instead.
    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_a_gate_config_without_a_config_dir_is_refused(self):
        self.gate_config(deploy_branch="main")
        self.write("a.py", "x = 1\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("names no config-dir", result.stdout)

    def test_an_unknown_commit_is_refused(self):
        self.write("a.py", "x = 1\n")
        self.commit()
        result = self.run_gate("not-a-commit")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("is not a commit here", result.stdout)

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_clean_python_passes(self):
        self.write("a.py", "x = 1\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("none new", result.stdout)

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_a_new_finding_is_refused_and_named(self):
        self.write("a.py", self.DIRTY)
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("1 new finding(s)", result.stdout)
        self.assertIn("a.py  F401  import os", result.stdout)

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_a_finding_the_baseline_holds_passes(self):
        self.write("a.py", self.DIRTY)
        self.baseline("ruff", {"a.py\tF401\timport os": 1})
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 known finding(s), none new", result.stdout)

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_a_second_copy_of_a_baselined_finding_is_new(self):
        self.write("a.py", self.DIRTY + self.DIRTY)
        self.baseline("ruff", {"a.py\tF401\timport os": 1})
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("1 new finding(s)", result.stdout)

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_a_range_checks_only_the_files_it_changed(self):
        self.write("old.py", self.DIRTY)
        base = self.commit()
        self.write("new.py", "x = 1\n")
        result = self.run_gate(self.commit("second"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 file(s) checked", result.stdout)

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_a_rendered_file_is_not_linted(self):
        self.write("a.py", "# generated from some-profile@abc1234\n" + self.DIRTY)
        self.assert_nothing_to_check(self.run_gate(self.commit()))

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_the_vendored_core_is_not_linted(self):
        self.write("core/VENDORED")
        self.write("core/a.py", self.DIRTY)
        self.assert_nothing_to_check(self.run_gate(self.commit()))

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_the_repos_own_ruff_config_decides_what_is_a_finding(self):
        self.write("a.py", self.DIRTY)
        self.write("ruff.toml", 'lint.ignore = ["F401"]\n')
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("none new", result.stdout)

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_a_syntax_error_is_a_finding(self):
        self.write("a.py", "def broken(:\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("invalid-syntax", result.stdout)


class Eslint(LintCase):
    gate = "eslint"
    CONFIG = "export default [];\n"
    # A stand-in for the package's own eslint: flags every `debugger` line, so the gate's
    # wiring is tested without installing the real one.
    FAKE_ESLINT = (
        "class ESLint {\n"
        "  async isPathIgnored() { return false; }\n"
        "  async calculateConfigForFile() { return {}; }\n"
        "  async lintText(text) {\n"
        "    const messages = [];\n"
        "    text.split('\\n').forEach((l, i) => {\n"
        "      if (l.includes('debugger')) messages.push({ ruleId: 'no-debugger', line: i + 1 });\n"
        "    });\n"
        "    return [{ messages }];\n"
        "  }\n"
        "}\n"
        "module.exports = { ESLint };\n"
    )

    def install_fake(self, package: str = "") -> None:
        folder = self.repo / package / "node_modules" / "eslint"
        folder.mkdir(parents=True)
        (folder / "package.json").write_text(
            '{"name":"eslint","version":"0.0.0","main":"index.js"}\n', encoding="utf-8")
        (folder / "index.js").write_text(self.FAKE_ESLINT, encoding="utf-8")

    def test_no_eslint_config_anywhere_means_nothing_to_check(self):
        self.write("a.js", "debugger;\n")
        self.assert_nothing_to_check(self.run_gate(self.commit()))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_javascript_outside_every_package_with_a_config_is_not_checked(self):
        self.write("web/eslint.config.js", self.CONFIG)
        self.write("other/b.js", "debugger;\n")
        sha = self.commit()
        self.install_fake("web")
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 file(s) checked", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_non_javascript_is_not_checked(self):
        self.write("eslint.config.js", self.CONFIG)
        self.write("notes.txt", "debugger;\n")
        sha = self.commit()
        self.install_fake()
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 file(s) checked", result.stdout)

    def test_a_gate_config_without_a_config_dir_is_refused_once_it_has_work(self):
        self.gate_config(deploy_branch="main")
        self.write("eslint.config.js", self.CONFIG)
        self.write("a.js", "x();\n")
        sha = self.commit()
        self.install_fake()
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("names no config-dir", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_missing_node_is_refused_with_a_message(self):
        self.write("eslint.config.js", self.CONFIG)
        self.write("a.js", "x();\n")
        result = self.run_without("node", self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("node is not installed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_package_without_node_modules_is_refused_never_passed(self):
        self.write("eslint.config.js", self.CONFIG)
        self.write("a.js", "x();\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("eslint is not installed in", result.stdout)
        self.assertIn("npm ci", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_clean_javascript_passes(self):
        self.write("eslint.config.js", self.CONFIG)
        self.write("a.js", "x();\n")
        sha = self.commit()
        self.install_fake()
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("none new", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_new_finding_is_refused_and_named(self):
        self.write("eslint.config.js", self.CONFIG)
        self.write("a.js", "debugger;\n")
        sha = self.commit()
        self.install_fake()
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("a.js  no-debugger  debugger;", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_finding_the_baseline_holds_passes(self):
        self.write("eslint.config.js", self.CONFIG)
        self.write("a.js", "debugger;\n")
        self.baseline("eslint", {"a.js\tno-debugger\tdebugger;": 1})
        sha = self.commit()
        self.install_fake()
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 known finding(s), none new", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_package_below_the_root_uses_its_own_node_modules(self):
        self.write("web/eslint.config.js", self.CONFIG)
        self.write("web/src/a.ts", "debugger;\n")
        sha = self.commit()
        self.install_fake("web")
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("web/src/a.ts  no-debugger", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_config_edited_since_the_commit_is_refused(self):
        self.write("eslint.config.js", self.CONFIG)
        self.write("a.js", "x();\n")
        sha = self.commit()
        self.install_fake()
        self.write("eslint.config.js", "export default [{ rules: {} }];\n")
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("differs from the commit being pushed", result.stdout)


class Shellcheck(LintCase):
    gate = "shellcheck"
    DIRTY = "#!/bin/sh\nunused=1\n"

    def test_no_shell_in_the_push_is_a_pass(self):
        self.write("a.py", "x = 1\n")
        self.assert_nothing_to_check(self.run_gate(self.commit()))

    def test_a_missing_shellcheck_is_refused_with_how_to_install_it(self):
        self.write("a.sh", self.DIRTY)
        result = self.run_without("shellcheck", self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("shellcheck is not installed", result.stdout)
        self.assertIn("apt install shellcheck", result.stdout)

    def test_a_missing_shellcheck_does_not_matter_when_no_shell_changed(self):
        self.write("a.py", "x = 1\n")
        self.assert_nothing_to_check(self.run_without("shellcheck", self.commit()))

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_a_clean_script_passes(self):
        self.write("a.sh", "#!/bin/sh\necho hi\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("none new", result.stdout)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_a_new_warning_is_refused_and_named(self):
        self.write("a.sh", self.DIRTY)
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("a.sh  SC2034  unused=1", result.stdout)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_a_warning_the_baseline_holds_passes(self):
        self.write("a.sh", self.DIRTY)
        self.baseline("shellcheck", {"a.sh\tSC2034\tunused=1": 1})
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 known finding(s), none new", result.stdout)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_an_extensionless_script_with_a_shebang_is_checked(self):
        self.write("bin/tool", "#!/usr/bin/env bash\nunused=1\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("bin/tool  SC2034", result.stdout)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_an_extensionless_file_without_a_shell_shebang_is_not_checked(self):
        self.write("bin/tool", "#!/usr/bin/env python3\nunused = 1\n")
        self.assert_nothing_to_check(self.run_gate(self.commit()))

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_a_style_note_below_warning_is_not_a_finding(self):
        self.write("a.sh", '#!/bin/sh\necho $HOME\n')
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_a_rendered_script_is_not_checked(self):
        self.write("a.sh", "#!/bin/sh\n# generated from some-profile@abc1234\nunused=1\n")
        self.assert_nothing_to_check(self.run_gate(self.commit()))

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_the_vendored_core_is_not_checked(self):
        self.write("core/VENDORED")
        self.write("core/a.sh", self.DIRTY)
        self.assert_nothing_to_check(self.run_gate(self.commit()))


class RunExpressions(GateCase):
    gate = "run-expressions"
    EXPR = "${{ github.event.head_commit.message }}"

    def workflow(self, steps: str, path: str = ".github/workflows/ci.yml") -> None:
        self.write(path, "name: ci\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
                         f"    steps:\n{steps}")

    def test_no_workflows_is_a_pass(self):
        self.write("a.py", "x = 1\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Nothing to check", result.stdout)

    def test_a_missing_commit_argument_is_refused(self):
        self.workflow("      - run: echo hi\n")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("REFUSED", result.stdout)

    def test_an_unknown_commit_is_refused(self):
        self.workflow("      - run: echo hi\n")
        self.commit()
        result = self.run_gate("not-a-commit")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("REFUSED", result.stdout)

    def test_a_workflow_without_expressions_in_scripts_passes(self):
        self.workflow("      - run: echo hi\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 workflow/action file(s)", result.stdout)

    def test_an_expression_in_a_one_line_run_is_refused_with_its_line(self):
        self.workflow(f'      - run: echo "{self.EXPR}"\n')
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(".github/workflows/ci.yml:7:", result.stdout)
        self.assertIn("env:", result.stdout)

    def test_an_expression_in_a_block_run_is_refused(self):
        self.workflow(f"      - run: |\n          echo start\n          echo {self.EXPR}\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("ci.yml:9:", result.stdout)

    def test_an_expression_in_a_folded_run_is_refused(self):
        self.workflow(f"      - run: >-\n          echo {self.EXPR}\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_an_expression_in_env_or_with_is_fine(self):
        self.workflow(f"      - uses: some/action@v1\n        with:\n          text: {self.EXPR}\n"
                      f"      - env:\n          MSG: {self.EXPR}\n        run: echo \"$MSG\"\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_defaults_run_mapping_is_not_a_script(self):
        self.write(".github/workflows/ci.yml",
                   "name: ci\non: push\ndefaults:\n  run:\n    shell: bash\n"
                   "    working-directory: ${{ github.workspace }}\n"
                   "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_composite_action_is_scanned_too(self):
        self.write(".github/actions/one/action.yml",
                   "name: one\nruns:\n  using: composite\n  steps:\n"
                   f"    - shell: bash\n      run: echo {self.EXPR}\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(".github/actions/one/action.yml", result.stdout)

    def test_a_workflow_source_without_the_github_folder_is_scanned(self):
        self.workflow(f'      - run: echo "{self.EXPR}"\n', path="workflows/ci.yml")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_the_commit_is_read_not_the_working_tree(self):
        self.workflow("      - run: echo hi\n")
        sha = self.commit()
        self.workflow(f'      - run: echo "{self.EXPR}"\n')
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 0, result.stdout)


_PYTHON = shutil.which("python")
PYTHON_HAS_YAML = bool(_PYTHON) and subprocess.run(
    [_PYTHON, "-c", "import yaml"], capture_output=True).returncode == 0


class SelfRender(GateCase):
    gate = "self-render"
    # A stand-in for the core's sync.py: it reports how it was called and where it ran.
    PASSING_SYNC = ("import os, sys\n"
                    "print('args', ' '.join(sys.argv[1:]))\n"
                    "print('profile.yaml here', os.path.exists('profile.yaml'))\n")
    FAILING_SYNC = "import sys\nprint('rendered copies are stale')\nsys.exit(1)\n"

    @staticmethod
    def has_yaml() -> bool:
        python = shutil.which("python")
        return bool(python) and subprocess.run(
            [python, "-c", "import yaml"], capture_output=True).returncode == 0

    def profile(self, sync_text: str) -> str:
        self.write("profile.yaml", "name: synthetic\n")
        self.write("core/sync.py", sync_text)
        return self.commit()

    def test_a_repo_that_is_not_a_profile_source_passes_as_not_applicable(self):
        self.write("a.py", "x = 1\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Not a profile source repository", result.stdout)

    def test_a_core_without_a_profile_manifest_is_not_applicable(self):
        self.write("core/sync.py", self.PASSING_SYNC)
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Not a profile source repository", result.stdout)

    def test_a_manifest_without_a_core_is_not_applicable(self):
        self.write("profile.yaml", "name: synthetic\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Not a profile source repository", result.stdout)

    def test_no_commit_is_refused(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no commit to check was given", result.stdout)

    def test_a_non_hex_commit_is_refused(self):
        result = self.run_gate("HEAD; rm")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no commit to check was given", result.stdout)

    def test_no_python_with_yaml_is_refused_never_passed(self):
        sha = self.profile(self.PASSING_SYNC)
        path = path_without(python=False)
        if path is None:
            self.skipTest("python lives beside git or sh here; cannot hide it")
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            result = self.run_gate(sha)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no python that can import yaml", result.stdout)

    @unittest.skipUnless(PYTHON_HAS_YAML, "python cannot import yaml")
    def test_rendered_copies_that_match_pass(self):
        result = self.run_gate(self.profile(self.PASSING_SYNC))
        self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipUnless(PYTHON_HAS_YAML, "python cannot import yaml")
    def test_rendered_copies_that_drifted_are_refused_with_the_fix(self):
        result = self.run_gate(self.profile(self.FAILING_SYNC))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("rendered copies are stale", result.stdout)
        self.assertIn("Run: python core/sync.py --profile . --self --write", result.stdout)

    @unittest.skipUnless(PYTHON_HAS_YAML, "python cannot import yaml")
    def test_the_core_is_called_to_check_offline_from_the_checked_out_commit(self):
        result = self.run_gate(self.profile(self.PASSING_SYNC))
        self.assertIn("args --profile . --self --check --no-fetch", result.stdout)
        self.assertIn("profile.yaml here True", result.stdout)

    @unittest.skipUnless(PYTHON_HAS_YAML, "python cannot import yaml")
    def test_the_commit_is_checked_not_the_working_tree(self):
        sha = self.profile(self.PASSING_SYNC)
        self.write("core/sync.py", self.FAILING_SYNC)
        result = self.run_gate(sha)
        self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipUnless(PYTHON_HAS_YAML, "python cannot import yaml")
    def test_a_hex_commit_the_repo_does_not_hold_is_not_applicable(self):
        self.profile(self.PASSING_SYNC)
        result = self.run_gate("0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Not a profile source repository", result.stdout)


class TestProvenance(GateCase):
    gate = "test-provenance"

    def test_a_missing_commit_argument_is_refused(self):
        self.write("a.py")
        self.commit()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("is not a commit here", result.stdout)

    def test_a_root_commit_has_nothing_to_compare_and_passes(self):
        self.write("tests/test_a.py", "def test_a():\n    assert 1\n")
        result = self.run_gate(self.commit())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 commit(s), 0 flagged", result.stdout)

    def test_an_edited_assertion_beside_a_source_change_is_flagged_but_never_blocks(self):
        self.write("tests/test_a.py", "def test_a():\n    assert f() == 1\n")
        self.write("src/a.py", "def f():\n    return 1\n")
        base = self.commit()
        self.write("tests/test_a.py", "def test_a():\n    assert f() == 2\n")
        self.write("src/a.py", "def f():\n    return 2\n")
        result = self.run_gate(self.commit("change both"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 flagged", result.stdout)
        self.assertIn("change both: 1 assertion line(s) edited beside src/a.py", result.stdout)
        self.assertIn("never blocks", result.stdout)

    def test_an_edited_assertion_with_no_source_change_is_not_flagged(self):
        self.write("tests/test_a.py", "def test_a():\n    assert f() == 1\n")
        base = self.commit()
        self.write("tests/test_a.py", "def test_a():\n    assert f() == 2\n")
        result = self.run_gate(self.commit("tests only"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 commit(s), 0 flagged", result.stdout)

    def test_a_source_change_with_an_untouched_assertion_is_not_flagged(self):
        self.write("tests/test_a.py", "def test_a():\n    assert f() == 1\n")
        self.write("src/a.py", "def f():\n    return 1\n")
        base = self.commit()
        self.write("src/a.py", "def f():\n    return 1  # tidy\n")
        result = self.run_gate(self.commit("source only"), base)
        self.assertIn("0 flagged", result.stdout)

    def test_added_tests_and_markers_are_counted(self):
        self.write("tests/test_a.py", "def test_a():\n    assert 1\n")
        base = self.commit()
        self.write("tests/test_a.py", "def test_a():\n    assert 1\n\n\n"
                                      "def test_b():\n    \"\"\"Intent: b holds.\"\"\"\n"
                                      "    assert 1\n\n\n"
                                      "def test_c():\n    # Characterisation: c as it is.\n"
                                      "    assert 1\n")
        result = self.run_gate(self.commit("add tests"), base)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Tests added: 2; markers: 1 Intent, 1 Characterisation", result.stdout)

    def test_every_commit_of_a_range_is_examined(self):
        self.write("a.txt")
        base = self.commit()
        self.write("a.txt", "1\n")
        self.commit("one")
        self.write("a.txt", "2\n")
        result = self.run_gate(self.commit("two"), base)
        self.assertIn("2 commit(s)", result.stdout)

    def test_a_non_test_file_with_an_assert_is_not_a_test_edit(self):
        self.write("src/a.py", "assert True\n")
        base = self.commit()
        self.write("src/a.py", "assert False\n")
        result = self.run_gate(self.commit("source"), base)
        self.assertIn("0 flagged", result.stdout)


class Identity(GateCase):
    """Every commit pushed from a profile repository carries the profile identity."""

    gate = "identity"
    ME = "me@example.invalid"
    OTHER = "someone@elsewhere.invalid"
    ZERO = "0" * 40

    def setUp(self):
        super().setUp()
        self.gate_config(deploy_branch="main", identity_email=self.ME)

    def commit_as(self, author: str, committer: str, message: str = "c") -> str:
        self.write(f"{message}.txt", message + "\n")
        self.git("add", "-A")
        self.git("-c", f"user.email={committer}", "commit", "-q", "-m", message,
                 f"--author=someone <{author}>")
        return self.git("rev-parse", "HEAD")

    def test_matching_author_and_committer_pass(self):
        """Intent: commits as the profile identity are what the gate exists to allow."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.ME, self.ME, "head")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_case_differs_only_is_the_same_address(self):
        """Intent: an address's domain is case-insensitive, and one repository's history
        carries the same address with different capitalisation."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.ME.upper(), self.ME, "head")
        self.assertEqual(self.run_gate(head, base).returncode, 0)

    def test_a_foreign_author_is_refused_and_named(self):
        """Intent: a commit authored as another address is refused."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.OTHER, self.ME, "head")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(self.OTHER, result.stdout)
        self.assertIn(head[:7], result.stdout)

    def test_a_foreign_committer_alone_is_refused(self):
        """Intent: author or committer. --author fixes only one of them."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.ME, self.OTHER, "head")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(self.OTHER, result.stdout)

    CURSOR = "Co-authored-by: Cursor <cursoragent@cursor.com>"

    def commit_message(self, name: str, *paragraphs: str) -> str:
        """A commit as the profile identity whose message is the given paragraphs."""
        self.write(f"{name}.txt", name + "\n")
        self.git("add", "-A")
        args = [arg for paragraph in (name, *paragraphs) for arg in ("-m", paragraph)]
        self.git("-c", f"user.email={self.ME}", "commit", "-q", *args,
                 f"--author=someone <{self.ME}>")
        return self.git("rev-parse", "HEAD")

    def test_a_foreign_co_author_trailer_is_refused_and_named(self):
        """Intent: a push whose range holds a commit with a Co-authored-by trailer for an
        address other than the profile identity is refused."""
        base = self.commit_message("base")
        head = self.commit_message("head", "Refs #1\n" + self.CURSOR)
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("cursoragent@cursor.com", result.stdout)
        self.assertIn(head[:7], result.stdout)

    def test_the_refusal_names_the_cursor_setting(self):
        """Intent: the refusal is where someone hits it, so it names the setting that adds
        the trailer."""
        base = self.commit_message("base")
        result = self.run_gate(self.commit_message("head", self.CURSOR), base)
        self.assertIn("Commit Attribution", result.stdout)

    def test_a_co_author_as_the_profile_identity_passes(self):
        """Intent: only a foreign address is refused, matched as the author check is."""
        base = self.commit_message("base")
        head = self.commit_message("head", f"Co-authored-by: Me <{self.ME.upper()}>")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_one_foreign_co_author_among_several_is_refused(self):
        base = self.commit_message("base")
        head = self.commit_message("head", f"Co-authored-by: Me <{self.ME}>\n"
                                           f"Co-authored-by: Other <{self.OTHER}>")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(self.OTHER, result.stdout)

    def test_a_made_with_cursor_trailer_is_refused(self):
        """Intent: Cursor's own already-modified check looks for "Made-with: Cursor", so a
        version that writes it is refused too."""
        base = self.commit_message("base")
        result = self.run_gate(self.commit_message("head", "Made-with: Cursor"), base)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Made-with", result.stdout)

    def test_a_co_author_quoted_in_the_body_is_not_a_trailer(self):
        """Intent: the gate names trailers. A commit that discusses one in prose carries
        none and must pass."""
        base = self.commit_message("base")
        head = self.commit_message("head", f"Cursor adds {self.CURSOR} to agent commits.",
                                   "Refs #166")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_co_author_already_on_the_deploy_branch_is_not_rechecked(self):
        """Intent: history that already carries the trailer is not rewritten, so it must
        not block a later push."""
        old = self.commit_message("old", self.CURSOR)
        self.on_deploy(old)
        head = self.commit_message("head")
        self.assertEqual(self.run_gate(head, old).returncode, 0)

    def test_only_the_pushed_range_is_checked(self):
        """Intent: existing history is not rewritten, so a foreign commit already on the
        remote must not block every later push. "On the remote" means on the deploy
        branch."""
        old = self.commit_as(self.OTHER, self.OTHER, "old")
        self.on_deploy(old)
        head = self.commit_as(self.ME, self.ME, "head")
        self.assertEqual(self.run_gate(head, old).returncode, 0)

    def on_deploy(self, sha: str, remote: str = "origin") -> None:
        """What a fetch of the deploy branch leaves behind."""
        self.git("update-ref", f"refs/remotes/{remote}/main", sha)

    def test_a_branch_that_merged_main_passes_for_githubs_merge_commits(self):
        """Intent: a push of a branch that merged main, with GitHub merge commits already
        on a remote, passes the identity gate."""
        base = self.commit_as(self.ME, self.ME, "base")
        trunk = self.git("branch", "--show-current")
        self.on_deploy(base)
        self.git("checkout", "-q", "-b", "feature")
        pushed = self.commit_as(self.ME, self.ME, "feature")
        self.git("checkout", "-q", trunk)
        merged = self.commit_as(self.ME, "noreply@github.com", "merge-button")
        self.on_deploy(merged)
        self.git("checkout", "-q", "feature")
        self.git("-c", f"user.email={self.ME}", "merge", "-q", "--no-edit", trunk)
        head = self.git("rev-parse", "HEAD")
        result = self.run_gate(head, pushed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_refused_commit_stays_refused_under_a_later_commit(self):
        """Intent: a feature branch's failing gate still pushes, so a refused commit is on
        the remote; the next push on top of it must refuse it again rather than pass with
        no record."""
        self.on_deploy(self.commit_as(self.ME, self.ME, "base"))
        refused = self.commit_as(self.OTHER, self.OTHER, "refused")
        head = self.commit_as(self.ME, self.ME, "on-top")
        result = self.run_gate(head, refused)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(refused[:7], result.stdout)

    GITHUB = "noreply@github.com"

    def web_merge(self, author: str, on_remote: bool, merge: bool = True) -> tuple[str, str]:
        """An integration branch with a commit GitHub's merge button would make on it; returns
        (the push's remote sha, the head pushed on top)."""
        base = self.commit_as(self.ME, self.ME, "base")
        self.on_deploy(base)
        self.git("checkout", "-q", "-b", "integration")
        if merge:
            self.git("checkout", "-q", "-b", "topic")
            self.commit_as(self.ME, self.ME, "topic")
            self.git("checkout", "-q", "integration")
            self.git("-c", f"user.email={self.GITHUB}", "merge", "-q", "--no-ff",
                     "-m", "Merge pull request", "topic")
            self.git("-c", f"user.email={self.GITHUB}", "commit", "-q", "--amend",
                     "--no-edit", f"--author=web <{author}>")
        else:
            self.commit_as(author, self.GITHUB, "web-commit")
        made = self.git("rev-parse", "HEAD")
        if on_remote:
            self.git("update-ref", "refs/remotes/origin/integration", made)
        head = self.commit_as(self.ME, self.ME, "on-top")
        return (made if on_remote else base), head

    def test_a_web_merge_already_on_the_remote_passes(self):
        """Intent: GitHub's merge of a pull request into an integration branch, authored by
        the profile identity and already on the remote, passes."""
        remote, head = self.web_merge(self.ME, on_remote=True)
        result = self.run_gate(head, remote)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_web_merge_not_yet_on_the_remote_is_refused(self):
        """Intent: a forged GitHub committer this clone made is not on the remote, so GitHub
        did not make it."""
        remote, head = self.web_merge(self.ME, on_remote=False)
        result = self.run_gate(head, remote)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(self.GITHUB, result.stdout)

    def test_a_web_merge_by_another_author_is_refused(self):
        """Intent: the author must still be the profile identity."""
        remote, head = self.web_merge(self.OTHER, on_remote=True)
        result = self.run_gate(head, remote)
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_a_non_merge_github_commit_is_refused(self):
        """Intent: only a merge commit is GitHub's merge button; a single-parent commit with
        GitHub's committer is refused even on the remote."""
        remote, head = self.web_merge(self.ME, on_remote=True, merge=False)
        result = self.run_gate(head, remote)
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_the_deploy_branch_is_read_from_the_remote_pushed_to(self):
        """Intent: the hook passes the remote's name as a third argument, and a direct call
        without it means origin."""
        self.on_deploy(self.commit_as(self.ME, self.ME, "base"))
        old = self.commit_as(self.OTHER, self.OTHER, "old")
        self.on_deploy(old, remote="upstream")
        head = self.commit_as(self.ME, self.ME, "head")
        self.assertEqual(self.run_gate(head, old, "upstream").returncode, 0)
        self.assertEqual(self.run_gate(head, old).returncode, 1)

    def test_without_a_deploy_ref_it_checks_what_no_remote_has_and_says_so(self):
        """Intent: a repository whose deploy branch was never fetched falls back to the
        new-branch rule, visibly."""
        old = self.commit_as(self.OTHER, self.OTHER, "old")
        self.git("update-ref", "refs/remotes/origin/feature", old)
        head = self.commit_as(self.ME, self.ME, "head")
        result = self.run_gate(head, old)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("refs/remotes/origin/main", result.stdout + result.stderr)

    def test_a_new_branch_checks_what_no_remote_has(self):
        """Intent: a new branch has no remote base, and skipping it as no-change-docs does
        would let a whole branch of foreign commits through."""
        self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.OTHER, self.OTHER, "head")
        result = self.run_gate(head, self.ZERO)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(self.OTHER, result.stdout)

    def test_no_configured_identity_refuses(self):
        """Intent: missing means abort. With nothing to compare against, a pass would be a
        healthy reading of a check that never ran."""
        (self.repo / ".githooks" / "gate-config").unlink()
        head = self.commit_as(self.ME, self.ME, "head")
        result = self.run_gate(head, self.ZERO)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("gate-config", result.stdout)

    def test_a_config_without_the_identity_key_refuses(self):
        """Intent: an empty value is as dangerous as a missing one."""
        self.gate_config(deploy_branch="main", identity_email="")
        head = self.commit_as(self.ME, self.ME, "head")
        self.assertEqual(self.run_gate(head, self.ZERO).returncode, 1)

    def test_git_config_cannot_change_the_expected_identity(self):
        """Intent: `git config gate.identityEmail x` leaves the identity gate refusing a
        foreign address."""
        self.git("config", "gate.identityEmail", self.OTHER)
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.OTHER, self.OTHER, "head")
        result = self.run_gate(head, base)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(self.OTHER, result.stdout)

    def test_a_crlf_checkout_of_the_config_still_matches(self):
        """Intent: every target carries the file, Windows checkouts included, where autocrlf
        leaves a carriage return that would refuse every commit."""
        (self.repo / ".githooks" / "gate-config").write_bytes(
            f"deploy-branch=main\r\nidentity-email={self.ME}\r\n".encode())
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.ME, self.ME, "head")
        self.assertEqual(self.run_gate(head, base).returncode, 0)

    def test_a_remote_sha_this_clone_has_not_fetched_names_the_pull(self):
        """Intent: on a stale clone the remote's head is not a local object. The gate still
        refuses, and says to pull rather than reporting an unlistable range."""
        head = self.commit_as(self.ME, self.ME, "head")
        unfetched = "1234567890abcdef1234567890abcdef12345678"
        result = self.run_gate(head, unfetched)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not fetched", result.stdout)
        self.assertIn("pull", result.stdout)

    def test_no_commit_given_refuses(self):
        """Intent: missing means abort; the gate cannot check a range it was not given."""
        self.commit_as(self.ME, self.ME, "head")
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_a_long_branch_starts_a_fixed_number_of_git_processes(self):
        """Intent: the gate cost a few processes per commit, so a long branch took minutes
        to push on Windows. Counted, not timed: a wall-clock bound flakes on a loaded
        runner, while the number of git processes the gate starts is the same on every
        machine. A shim ahead of git on PATH counts them."""
        base = self.commit_as(self.ME, self.ME, "base")
        self.on_deploy(base)
        stream = "".join(
            f"commit refs/heads/long\ncommitter me <{self.ME}> {1700000000 + n} +0000\n"
            f"data 2\nc\n" + (f"from {base}\n" if n == 0 else "") + "\n"
            for n in range(200))
        imported = subprocess.run(["git", "fast-import", "--quiet"], cwd=self.repo,
                                  input=stream.encode(), capture_output=True)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        head = self.git("rev-parse", "refs/heads/long")
        shim = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, shim, ignore_errors=True)
        count = shim / "count"
        count.write_text("", encoding="utf-8")
        real = Path(shutil.which("git")).as_posix()
        (shim / "git").write_text(
            f'#!/bin/sh\necho x >> "{count.as_posix()}"\nexec "{real}" "$@"\n',
            encoding="utf-8", newline="\n")
        result = self.run_gate(head, base, path_prefix=str(shim))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("200 commit(s) checked", result.stdout)
        spawned = len(count.read_text(encoding="utf-8").split())
        self.assertGreater(spawned, 0, "the shim never ran, so the count proves nothing")
        self.assertLessEqual(spawned, 10, f"{spawned} git processes for 200 commits")


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


RENDERED_ONLY_PY = ROOT / "githooks" / "lib" / "rendered_only.py"


class RenderedOnly(GateCase):
    """rendered_only() judged three ways on one range: the shell function with a python on
    PATH (the batched script), the same function with none (the per-file loop), and the
    script itself. They must agree."""

    gate = "tests"
    ZERO = "0" * 40

    def stamp_at(self, line: int) -> str:
        return "filler\n" * (line - 1) + STAMPED.splitlines()[0] + "\nmore\n"

    def base(self, **files: str) -> str:
        self.write("README.md", "plain\n")
        for rel, text in files.items():
            self.write(rel, text)
        return self.commit("base")

    def shell_verdict(self, local: str, remote: str, path: str | None = None) -> int:
        script = '. "$(dirname "$0")/../lib/rendered_only.sh"; rendered_only "$1" "$2"'
        env = {**os.environ, "LC_ALL": "C"}
        env["PATH"] = str(Path(SH).parent) + os.pathsep + (path if path is not None else env["PATH"])
        return subprocess.run([SH, "-c", script, (GATES / "tests.sh").as_posix(), local, remote],
                              cwd=self.repo, capture_output=True, text=True, env=env).returncode

    def script_verdict(self, local: str, remote: str) -> int:
        return subprocess.run([sys.executable, "-B", str(RENDERED_ONLY_PY), local, remote],
                              cwd=self.repo, capture_output=True, text=True).returncode

    def assert_verdict(self, local: str, remote: str, rendered_only: bool) -> None:
        path = path_without(python=False)
        if path is None:
            self.skipTest("python lives beside git or sh here; cannot hide it")
        want = 0 if rendered_only else 1
        self.assertEqual(self.shell_verdict(local, remote, path), want, "the per-file loop")
        self.assertEqual(self.shell_verdict(local, remote), want, "the shell function")
        self.assertEqual(self.script_verdict(local, remote), want, "the script")

    def test_every_changed_file_stamped(self):
        base = self.base()
        self.write("AGENTS.md", STAMPED)
        self.write("docs/CLAUDE.md", STAMPED)
        self.assert_verdict(self.commit(), base, True)

    def test_one_unstamped_file(self):
        base = self.base()
        self.write("AGENTS.md", STAMPED)
        self.write("app.txt", "plain\n")
        self.assert_verdict(self.commit(), base, False)

    def test_a_deleted_rendered_file_is_judged_on_the_remote_side(self):
        base = self.base(**{"AGENTS.md": STAMPED})
        (self.repo / "AGENTS.md").unlink()
        self.assert_verdict(self.commit(), base, True)

    def test_a_deleted_plain_file_is_not_rendered_only(self):
        base = self.base(**{"app.txt": "plain\n"})
        (self.repo / "app.txt").unlink()
        self.assert_verdict(self.commit(), base, False)

    def test_gitignore_alone_is_skipped(self):
        base = self.base()
        self.write(".gitignore", "build/\n")
        self.assert_verdict(self.commit(), base, True)

    def test_a_path_with_a_space(self):
        base = self.base()
        self.write("my docs/AGENTS file.md", STAMPED)
        self.assert_verdict(self.commit(), base, True)

    def test_a_stamp_on_line_forty_counts(self):
        base = self.base()
        self.write("AGENTS.md", self.stamp_at(40))
        self.assert_verdict(self.commit(), base, True)

    def test_a_stamp_on_line_forty_one_does_not(self):
        base = self.base()
        self.write("AGENTS.md", self.stamp_at(41))
        self.assert_verdict(self.commit(), base, False)

    def test_a_zero_byte_blob_is_unstamped(self):
        base = self.base()
        self.write("AGENTS.md", STAMPED)
        self.write("empty.txt", "")
        self.assert_verdict(self.commit(), base, False)

    def test_a_binary_blob_is_stamped_only_by_its_first_forty_lines(self):
        base = self.base()
        (self.repo / "a.bin").write_bytes(b"\x00\x01\x02\n" + STAMPED.encode())
        self.assert_verdict(self.commit("stamped"), base, True)
        (self.repo / "b.bin").write_bytes(b"\x00\x01\x02\n" * 3)
        self.assert_verdict(self.commit("plain"), base, False)

    def test_an_empty_diff_is_not_rendered_only(self):
        base = self.base()
        self.assert_verdict(base, base, False)

    def test_an_all_zero_remote_is_not_rendered_only(self):
        self.base()
        self.write("AGENTS.md", STAMPED)
        self.assert_verdict(self.commit(), self.ZERO, False)

    def test_a_remote_that_is_not_a_commit_is_not_rendered_only(self):
        self.base()
        self.write("AGENTS.md", STAMPED)
        self.assert_verdict(self.commit(), "1" * 40, False)

    def test_a_tab_in_a_path(self):
        if os.name == "nt":
            self.skipTest("Windows file names cannot hold a tab")
        base = self.base()
        self.write("a\tb.md", STAMPED)
        self.assert_verdict(self.commit(), base, True)

    def test_a_non_ascii_path(self):
        base = self.base()
        self.write("café/AGENTS.md", STAMPED)
        local = self.commit()
        # The per-file loop is left out on purpose: it reads `git diff --name-only` without
        # -z, so git quotes the name (core.quotepath) and the loop judges it unstamped. See
        # the ticket report; the old behaviour is not changed here.
        self.assertEqual(self.shell_verdict(local, base), 0, "the shell function")
        self.assertEqual(self.script_verdict(local, base), 0, "the script")

    def test_cat_file_dying_mid_stream_is_unknown(self):
        """Intent: exit 2 means it could not judge. cat-file is replaced by a process that
        exits at once, so the first answer never comes."""
        base = self.base()
        self.write("AGENTS.md", STAMPED)
        local = self.commit()
        sys.path.insert(0, str(RENDERED_ONLY_PY.parent))
        self.addCleanup(sys.path.remove, str(RENDERED_ONLY_PY.parent))
        import rendered_only
        real_popen = subprocess.Popen

        def popen(args, *a, **kw):
            if args[:3] == ["git", "cat-file", "--batch"]:
                args = [sys.executable, "-c", "pass"]
            return real_popen(args, *a, **kw)

        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        with unittest.mock.patch.object(subprocess, "Popen", popen), \
                unittest.mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(rendered_only.main([local, base]), 2)

    def test_exit_two_makes_the_gate_run_not_skip(self):
        """Intent: a git failure is exit 2 from the script, which the shell turns into
        "not rendered-only", so the suite runs. A local sha git cannot diff stands in."""
        self.gate_config(config_dir=".github")
        self.write(".github/test-roots", "run: echo suite-ran\n")
        base = self.commit()
        bogus = "1" * 40
        self.assertEqual(self.script_verdict(bogus, base), 2)
        self.assertEqual(self.shell_verdict(bogus, base), 1)
        result = self.run_gate(bogus, base)
        self.assertNotIn("skipped: every file", result.stdout)
        self.assertIn("suite-ran", result.stdout)


class TestsRangeByRef(GateCase):
    """The range the tests gate hands its suites depends on the ref being pushed:
    targeted on branches, everything on the deploy branch."""

    gate = "tests"
    config_dir = ".github"

    def setUp(self):
        super().setUp()
        self.gate_config(config_dir=".github", deploy_branch="main")
        self.write(".github/test-roots",
                   'run: echo "$PUSH_REMOTE_SHA..$PUSH_LOCAL_SHA" > range.out\n')

    def run_ref(self, local, remote, ref, *extra, unset_ref=False):
        script = (GATES / "tests.sh").as_posix()
        env = {**os.environ, "LC_ALL": "C"}
        env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
        env.pop("PUSH_REMOTE_REF", None)
        if not unset_ref:
            env["PUSH_REMOTE_REF"] = ref
        return subprocess.run([SH, script, local, remote, *extra], cwd=self.repo,
                              capture_output=True, text=True, env=env)

    def seen_range(self) -> str:
        return (self.repo / "range.out").read_text(encoding="utf-8").strip()

    def range_line(self, result) -> str:
        lines = [ln for ln in result.stdout.splitlines() if ln.startswith("range:")]
        self.assertEqual(len(lines), 1, result.stdout)
        return lines[0]

    def two_commits(self):
        first = self.commit()
        self.write("b.txt")
        return first, self.commit()

    def test_a_push_to_the_deploy_branch_exports_an_empty_remote_sha(self):
        """Intent: the deploy branch runs the full suite, so a selecting suite gets no range."""
        first, second = self.two_commits()
        result = self.run_ref(second, first, "refs/heads/main")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"..{second}")
        self.assertIn("deploy branch", self.range_line(result))

    def test_a_new_branch_exports_the_merge_base_with_the_deploy_branch(self):
        """Intent: a branch's first push is targeted at what the branch added."""
        first = self.commit()
        self.git("update-ref", "refs/remotes/origin/main", first)
        self.write("b.txt")
        second = self.commit()
        result = self.run_ref(second, "0" * 40, "refs/heads/feature")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"{first}..{second}")
        line = self.range_line(result)
        self.assertIn("merge-base with origin/main", line)
        self.assertIn("new branch", line)

    def test_the_merge_base_uses_the_remote_the_gate_is_given(self):
        """Intent: the third argument names the remote, as the hook passes it."""
        first = self.commit()
        self.git("update-ref", "refs/remotes/upstream/main", first)
        self.write("b.txt")
        second = self.commit()
        result = self.run_ref(second, "0" * 40, "refs/heads/feature", "upstream")
        self.assertEqual(self.seen_range(), f"{first}..{second}")
        self.assertIn("merge-base with upstream/main", self.range_line(result))

    def test_a_new_branch_with_no_deploy_branch_ref_exports_an_empty_range(self):
        """Intent: an unknown is never a narrower selection."""
        _, second = self.two_commits()
        result = self.run_ref(second, "0" * 40, "refs/heads/feature")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"..{second}")
        self.assertIn("new branch", self.range_line(result))

    def test_a_new_branch_with_no_merge_base_exports_an_empty_range(self):
        """Intent: a failing merge-base runs everything, not a guess."""
        self.git("checkout", "-q", "--orphan", "other")
        self.write("o.txt")
        orphan = self.commit()
        self.git("update-ref", "refs/remotes/origin/main", orphan)
        self.git("checkout", "-q", "--orphan", "feature")
        self.write("f.txt")
        tip = self.commit()
        result = self.run_ref(tip, "0" * 40, "refs/heads/feature")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"..{tip}")
        self.assertIn("range:", self.range_line(result))

    def test_a_branch_at_the_deploy_tip_has_a_merge_base_equal_to_itself(self):
        """Intent: the boundary is an empty range, not an error."""
        first = self.commit()
        self.git("update-ref", "refs/remotes/origin/main", first)
        result = self.run_ref(first, "0" * 40, "refs/heads/feature")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"{first}..{first}")

    def test_an_existing_branch_keeps_its_remote_sha(self):
        """Intent: a later push to a branch is targeted at what it adds, as before."""
        first, second = self.two_commits()
        result = self.run_ref(second, first, "refs/heads/feature")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"{first}..{second}")
        self.assertIn("as pushed", self.range_line(result))

    def test_a_ref_outside_heads_is_not_the_deploy_branch(self):
        """Intent: only refs/heads/<deploy-branch> triggers the full suite."""
        first, second = self.two_commits()
        result = self.run_ref(second, first, "refs/tags/main")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"{first}..{second}")

    def test_no_ref_behaves_as_before_and_prints_no_range_line(self):
        """Intent: the gate run by hand passes the arguments through untouched."""
        first, second = self.two_commits()
        result = self.run_ref(second, first, "", unset_ref=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.seen_range(), f"{first}..{second}")
        self.assertNotIn("range:", result.stdout)

    def test_a_missing_deploy_branch_in_gate_config_refuses(self):
        """Intent: with a ref named, an unreadable deploy branch refuses rather than guessing."""
        self.gate_config(config_dir=".github")
        first, second = self.two_commits()
        result = self.run_ref(second, first, "refs/heads/feature")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("deploy-branch", result.stdout)


class PrePushRemoteRef(PrePushCase):
    """The hook tells each gate which remote ref its line pushes."""

    def test_each_line_exports_its_own_remote_ref(self):
        """Intent: the gates of a line see that line's ref, set before they run."""
        self.write(".githooks/gates/ref.sh", 'echo "ref=$PUSH_REMOTE_REF"\n')
        self.enabled("ref")
        sha = self.commit()
        result = self.push(sha, "feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.reports()[0]
        self.assertIn("ref=refs/heads/feature", report["gates"]["ref"]["detail"])


# The base classes hold no test of their own and must not run as cases.
del GateCase, PrePushCase


if __name__ == "__main__":
    unittest.main(verbosity=2)
