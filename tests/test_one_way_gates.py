#!/usr/bin/env python3
################################################################################
# File: test_one_way_gates.py
# Path: {PROJECT_ROOT}/tests/test_one_way_gates.py
# Created by: Ryan Severe
# Created: 2026-10-15
# Last Updated: 2026-11-13
# Description: Runs each one-way gate in githooks/one-way/ against a throwaway
#              repository, red on a planted violation and green on a clean
#              tree, and refusing when its pattern file is missing or empty.
#              The gates are run by nothing yet; these tests are their only
#              check until a profile wires them in. The self pre-push hook in
#              githooks/self/ is tested by real pushes from a throwaway clone
#              to a throwaway bare remote.
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

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ONE_WAY = Path(__file__).resolve().parent.parent / "githooks" / "one-way"
ZERO = "0" * 40

# Shell is invisible to coverage, so test selection is told what these run.
EXERCISES = ["githooks/one-way/**", "githooks/lib/**", "githooks/self/**"]

SH = shutil.which("sh") or next(
    (p for p in (r"C:\Program Files\Git\usr\bin\sh.exe", "/bin/sh") if Path(p).exists()),
    None,
)


@unittest.skipIf(SH is None, "no POSIX shell available; not reporting a pass")
class OneWayCase(unittest.TestCase):
    """A one-way gate run directly against a throwaway repository. Its own harness, because
    test_gates deletes GateCase so that nothing imports it."""

    one_way = ""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")

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

    def run_one_way(self, *args: str) -> subprocess.CompletedProcess:
        script = (ONE_WAY / f"{self.one_way}.sh").as_posix()
        env = {**os.environ, "LC_ALL": "C"}
        env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
        return subprocess.run([SH, script, *args], cwd=self.repo, capture_output=True,
                              text=True, env=env)

    def patterns(self, *lines: str) -> str:
        """A pattern file outside the repository, as a profile keeps it."""
        path = Path(self.repo.parent, f"{self.repo.name}-patterns.txt")
        self.addCleanup(path.unlink, missing_ok=True)
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n")
        return path.as_posix()

    def output(self, result: subprocess.CompletedProcess) -> str:
        return result.stdout + result.stderr


class PatternFileRules:
    """Mixed into each gate that reads a pattern file. `run_with(path)` runs the gate
    on a clean repository with that pattern file."""

    def test_a_missing_pattern_file_refuses(self):
        """Intent: missing means abort; a gate with nothing to compare
        against would pass everything."""
        result = self.run_with(Path(self.repo.parent, "no-such-patterns.txt").as_posix())
        self.assertEqual(result.returncode, 1, self.output(result))
        self.assertIn("pattern file", self.output(result))

    def test_an_empty_pattern_file_refuses(self):
        """Intent: "An empty denylist passing everything is the defect this
        gate exists to stop"; required-secret: test falsy, not null."""
        result = self.run_with(self.patterns())
        self.assertEqual(result.returncode, 1, self.output(result))

    def test_a_file_of_only_comments_and_blanks_refuses(self):
        """Intent: a file that exists but declares nothing is as empty as no file."""
        result = self.run_with(self.patterns("# employer strings", "", "   "))
        self.assertEqual(result.returncode, 1, self.output(result))

    def test_a_blank_line_among_patterns_does_not_match_everything(self):
        """Intent: grep -F -f treats an empty line as a pattern that matches every line, so a
        stray blank line would refuse every push and train an override."""
        result = self.run_with(self.patterns("zzz-never-present", ""))
        self.assertEqual(result.returncode, 0, self.output(result))


class LeakDenylist(PatternFileRules, OneWayCase):
    """Gate 1: added content matching a denylisted string is refused, and the string is
    never printed."""

    one_way = "leak-denylist"
    SECRET = "Acme-Internal"

    def pushed(self, rel: str, text: str, pattern_file: str) -> subprocess.CompletedProcess:
        self.write("a.txt")
        base = self.commit()
        self.write(rel, text)
        return self.run_one_way(pattern_file, self.commit("second"), base)

    def run_with(self, pattern_file: str) -> subprocess.CompletedProcess:
        return self.pushed("clean.txt", "nothing to see\n", pattern_file)

    def test_a_planted_string_is_refused_with_its_location(self):
        """Intent: red on a planted violation."""
        result = self.pushed("docs/NOTES.md", "line one\nsee acme-internal here\n",
                             self.patterns(self.SECRET))
        self.assertEqual(result.returncode, 1, self.output(result))
        self.assertIn("docs/NOTES.md:2", result.stdout)

    def test_the_pattern_and_the_line_are_never_printed(self):
        """Intent: gate 1's output never contains the matched pattern,
        because the gate report is published and the denylist is secret-held."""
        result = self.pushed("x.md", f"the {self.SECRET} host\n", self.patterns(self.SECRET))
        self.assertEqual(result.returncode, 1)
        self.assertIn("x.md:1", self.output(result))
        self.assertNotIn(self.SECRET.lower(), self.output(result).lower())
        self.assertNotIn("host", self.output(result))

    def test_a_clean_push_passes(self):
        """Intent: green on a clean tree."""
        result = self.pushed("x.md", "nothing personal\n", self.patterns(self.SECRET))
        self.assertEqual(result.returncode, 0, self.output(result))

    def test_only_added_lines_are_scanned(self):
        """Intent: a string already on the remote must not block every later push; the
        history it sits in is not this gate's to rewrite."""
        self.write("old.md", f"{self.SECRET}\n")
        base = self.commit()
        self.write("new.txt", "clean\n")
        result = self.run_one_way(self.patterns(self.SECRET), self.commit("second"), base)
        self.assertEqual(result.returncode, 0, self.output(result))

    def test_a_new_branch_scans_everything_in_it(self):
        """Intent: an all-zero remote sha is a new branch, and every line in it is new."""
        self.write("x.md", f"{self.SECRET}\n")
        result = self.run_one_way(self.patterns(self.SECRET), self.commit(), ZERO)
        self.assertEqual(result.returncode, 1, self.output(result))
        self.assertIn("x.md:1", self.output(result))

    def test_patterns_are_fixed_strings_not_expressions(self):
        """Intent: fixed strings. A dot is a dot, so `198.51.100.` does not
        match `198x51y100`, and a mistyped expression cannot silently match nothing."""
        refused = self.pushed("a.cfg", "host = 198.51.100.5\n", self.patterns("198.51.100."))
        self.assertEqual(refused.returncode, 1, self.output(refused))
        self.setUp()
        allowed = self.pushed("a.cfg", "build 198x51y100\n", self.patterns("198.51.100."))
        self.assertEqual(allowed.returncode, 0, self.output(allowed))

    def test_a_diff_that_cannot_be_computed_refuses(self):
        """Intent: unknown is not zero. A failed diff yields no added lines, and scanning no
        lines is a pass the gate did not earn."""
        self.write("a.txt")
        self.commit()
        result = self.run_one_way(self.patterns(self.SECRET), "f" * 40, ZERO)
        self.assertEqual(result.returncode, 1, self.output(result))


class NoCoreRemote(OneWayCase):
    """Gate 2: a push whose remote is the core repository is refused, whatever URL form
    names it. A backstop - a vendored profile has no such remote by construction."""

    one_way = "no-core-remote"
    CORE = "https://github.com/ExampleOwner/ai-toolbox.git"

    def test_the_core_url_itself_is_refused(self):
        """Intent: red on a planted violation."""
        result = self.run_one_way(self.CORE, self.CORE)
        self.assertEqual(result.returncode, 1, self.output(result))

    def test_every_url_form_of_the_core_is_refused(self):
        """Intent: one repository has several URLs - ssh, https without .git, an ssh host
        alias such as this estate's own `github-personal:` - and case differs."""
        for url in ("git@github.com:ExampleOwner/ai-toolbox.git",
                    "https://github.com/exampleowner/AI-TOOLBOX",
                    "github-personal:ExampleOwner/ai-toolbox.git",
                    "ssh://git@github.com/ExampleOwner/ai-toolbox"):
            with self.subTest(url=url):
                self.assertEqual(self.run_one_way(self.CORE, url).returncode, 1)

    def test_a_different_repository_passes(self):
        """Intent: green on a clean push."""
        for url in ("git@github.com:ExampleOwner/ai-toolbox-profile.git",
                    "https://github.com/OtherOwner/ai-toolbox.git"):
            with self.subTest(url=url):
                result = self.run_one_way(self.CORE, url)
                self.assertEqual(result.returncode, 0, self.output(result))

    def test_no_core_url_refuses(self):
        """Intent: missing means abort - with no core to compare against, a pass would be a
        healthy reading of a check that never ran."""
        result = self.run_one_way("", "git@github.com:ExampleOwner/anything.git")
        self.assertEqual(result.returncode, 1, self.output(result))

    def test_no_push_url_refuses(self):
        """Intent: missing means abort, for each value, not only the first."""
        result = self.run_one_way(self.CORE, "")
        self.assertEqual(result.returncode, 1, self.output(result))


class AuthorDomains(PatternFileRules, OneWayCase):
    """Gate 3: a pushed commit authored or committed under a denylisted domain is refused.
    The commit walk is the identity gate's."""

    one_way = "author-domains"
    ME = "me@example.invalid"
    WORK = "someone@corp.example"

    def commit_as(self, author: str, committer: str, message: str = "c") -> str:
        self.write(f"{message}.txt", message + "\n")
        self.git("add", "-A")
        self.git("-c", f"user.email={committer}", "commit", "-q", "-m", message,
                 f"--author=someone <{author}>")
        return self.git("rev-parse", "HEAD")

    def run_with(self, pattern_file: str) -> subprocess.CompletedProcess:
        base = self.commit_as(self.ME, self.ME, "base")
        return self.run_one_way(pattern_file, self.commit_as(self.ME, self.ME, "head"), base)

    def test_a_denylisted_author_is_refused_and_the_commit_named(self):
        """Intent: red on a planted violation."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.WORK, self.ME, "head")
        result = self.run_one_way(self.patterns("corp.example"), head, base)
        self.assertEqual(result.returncode, 1, self.output(result))
        self.assertIn(head[:7], result.stdout)

    def test_the_domain_and_address_are_never_printed(self):
        """Intent: the domain list is secret-held like the denylist, and the gate report
        is published."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.WORK, self.ME, "head")
        result = self.run_one_way(self.patterns("corp.example"), head, base)
        self.assertNotIn("corp.example", self.output(result))

    def test_a_denylisted_committer_alone_is_refused(self):
        """Intent: author or committer - --author changes only one of them."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.ME, self.WORK, "head")
        result = self.run_one_way(self.patterns("corp.example"), head, base)
        self.assertEqual(result.returncode, 1, self.output(result))

    def test_a_subdomain_is_refused_and_a_lookalike_passes(self):
        """Intent: mail.corp.example is the same employer; notcorp.example is not."""
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as("a@mail.CORP.example", self.ME, "head")
        self.assertEqual(self.run_one_way(self.patterns("corp.example"), head, base).returncode, 1)
        self.setUp()
        base = self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as("a@notcorp.example", self.ME, "head")
        result = self.run_one_way(self.patterns("corp.example"), head, base)
        self.assertEqual(result.returncode, 0, self.output(result))

    def test_a_clean_push_passes(self):
        """Intent: green on a clean push."""
        result = self.run_with(self.patterns("corp.example"))
        self.assertEqual(result.returncode, 0, self.output(result))

    def test_only_the_pushed_range_is_checked(self):
        """Intent: a denylisted commit already on the remote must not block every later push.
        "On the remote" means on the deploy
        branch, as for the identity gate it shares commit_list with."""
        self.write(".githooks/gate-config", "deploy-branch=main\n")
        old = self.commit_as(self.WORK, self.WORK, "old")
        self.git("update-ref", "refs/remotes/origin/main", old)
        head = self.commit_as(self.ME, self.ME, "head")
        result = self.run_one_way(self.patterns("corp.example"), head, old)
        self.assertEqual(result.returncode, 0, self.output(result))

    def test_a_new_branch_checks_what_no_remote_has(self):
        """Intent: an all-zero remote sha must not skip a whole branch."""
        self.commit_as(self.ME, self.ME, "base")
        head = self.commit_as(self.WORK, self.WORK, "head")
        result = self.run_one_way(self.patterns("corp.example"), head, ZERO)
        self.assertEqual(result.returncode, 1, self.output(result))


class CoreNamesNoProfile(PatternFileRules, OneWayCase):
    """Gate 4: core content naming any profile is refused. Scans a tree, because in a
    profile the core is a directory inside it."""

    one_way = "core-names-no-profile"
    PROFILE = "example-estate"

    def run_with(self, pattern_file: str) -> subprocess.CompletedProcess:
        self.write("core/README.md", "a generic toolbox\n")
        return self.run_one_way(pattern_file, (self.repo / "core").as_posix())

    def test_a_named_profile_is_refused_with_its_location(self):
        """Intent: red on a planted violation."""
        self.write("core/rules/a.md", "intro\nbuilt for Example-Estate\n")
        result = self.run_one_way(self.patterns(self.PROFILE), (self.repo / "core").as_posix())
        self.assertEqual(result.returncode, 1, self.output(result))
        self.assertIn("rules/a.md:2", result.stdout)
        self.assertNotIn(self.PROFILE, self.output(result).lower())

    def test_a_clean_core_passes(self):
        """Intent: green on a clean tree."""
        result = self.run_with(self.patterns(self.PROFILE))
        self.assertEqual(result.returncode, 0, self.output(result))

    def test_only_the_given_tree_is_scanned(self):
        """Intent: the profile around the core names itself everywhere; only core/ is held
        to this rule."""
        self.write("profile.yaml", f"name: {self.PROFILE}\n")
        result = self.run_with(self.patterns(self.PROFILE))
        self.assertEqual(result.returncode, 0, self.output(result))

    def test_a_missing_tree_refuses(self):
        """Intent: unknown is not zero - a tree that is not there has nothing scanned, which
        is not the same as nothing found."""
        result = self.run_one_way(self.patterns(self.PROFILE),
                                  (self.repo / "no-such-core").as_posix())
        self.assertEqual(result.returncode, 1, self.output(result))

    def test_a_tree_with_no_text_files_refuses(self):
        """Intent: unknown is not zero - a core with nothing readable in it had nothing
        scanned, and a typo'd path to an empty directory must not read as clean."""
        (self.repo / "core").mkdir()
        result = self.run_one_way(self.patterns(self.PROFILE), (self.repo / "core").as_posix())
        self.assertEqual(result.returncode, 1, self.output(result))
        self.assertIn("no text files", self.output(result))


class SelfPrePush(OneWayCase):
    """The self pre-push hook, exercised by a real `git push` from a throwaway clone to a
    throwaway bare remote, with core.hooksPath pointing at githooks/self."""

    HOOKS = Path(__file__).resolve().parent.parent / "githooks" / "self"
    SECRET = "Acme-Internal"
    PATTERN_PATH = ".config/ai-toolbox/leak-denylist"

    def setUp(self):
        super().setUp()
        self.bare = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.bare, ignore_errors=True)
        subprocess.run(["git", "init", "--bare", "-q", str(self.bare)], check=True,
                       capture_output=True)
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.git("remote", "add", "origin", self.bare.as_posix())
        self.git("config", "core.hooksPath", self.HOOKS.as_posix())
        self.git("checkout", "-q", "-B", "dev")
        self.write("base.txt")
        self.base = self.commit("base")
        # Seed the remote with the base commit, past the hook under test.
        self.git("push", "-q", "--no-verify", "origin", "dev")

    def home_patterns(self, *lines: str) -> None:
        """The pattern file at the fixed place the hook reads, under the temporary HOME."""
        path = self.home / self.PATTERN_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n")

    def branch(self, name: str, rel: str = "f.txt", text: str = "clean\n") -> str:
        """A branch of one commit on top of the base commit; returns its sha."""
        self.git("checkout", "-q", "-B", name, "dev")
        self.write(rel, text)
        return self.commit(name)

    def push(self, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "LC_ALL": "C", "HOME": str(self.home)}
        env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
        return subprocess.run(["git", "push", *args], cwd=self.repo, capture_output=True,
                              text=True, env=env)

    def remote_sha(self, branch: str) -> str:
        """The sha of a branch on the bare remote, or an empty string when it is not there."""
        result = subprocess.run(
            ["git", "--git-dir", str(self.bare), "rev-parse", "--verify", "-q",
             f"refs/heads/{branch}"], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ""

    def test_a_denylisted_line_on_a_feature_branch_is_refused(self):
        """Intent: the gate runs on every branch, not only dev and main - a leak is refused
        before it is public, and the output says where, never what."""
        self.home_patterns(self.SECRET)
        self.branch("feature", "docs/NOTES.md", f"line one\nthe {self.SECRET} host-marker\n")
        result = self.push("origin", "feature")
        self.assertNotEqual(result.returncode, 0, self.output(result))
        self.assertEqual(self.remote_sha("feature"), "")
        self.assertIn("docs/NOTES.md:2", self.output(result))
        self.assertNotIn(self.SECRET.lower(), self.output(result).lower())
        self.assertNotIn("host-marker", self.output(result))

    def test_a_denylisted_line_on_dev_is_refused(self):
        """Intent: the same refusal on dev, where the remote branch already exists and must
        stay where it was."""
        self.home_patterns(self.SECRET)
        self.write("docs/NOTES.md", f"line one\nthe {self.SECRET} host-marker\n")
        self.commit("leak")
        result = self.push("origin", "dev")
        self.assertNotEqual(result.returncode, 0, self.output(result))
        self.assertEqual(self.remote_sha("dev"), self.base)
        self.assertIn("docs/NOTES.md:2", self.output(result))
        self.assertNotIn(self.SECRET.lower(), self.output(result).lower())

    def test_a_missing_pattern_file_refuses_the_push(self):
        """Intent: missing means abort - a hook with nothing to compare against would pass
        every push, and it names the file so the fix is findable."""
        self.branch("feature")
        result = self.push("origin", "feature")
        self.assertNotEqual(result.returncode, 0, self.output(result))
        self.assertEqual(self.remote_sha("feature"), "")
        self.assertIn(self.PATTERN_PATH, self.output(result))

    def test_an_empty_pattern_file_refuses_the_push(self):
        """Intent: an empty denylist passing everything is the defect the gate exists to
        stop, so an empty file refuses like a missing one."""
        self.home_patterns()
        self.branch("feature")
        result = self.push("origin", "feature")
        self.assertNotEqual(result.returncode, 0, self.output(result))
        self.assertEqual(self.remote_sha("feature"), "")

    def test_a_clean_push_passes(self):
        """Intent: green on a clean push, and the branch is on the remote at the pushed sha."""
        self.home_patterns(self.SECRET)
        sha = self.branch("feature", "x.md", "nothing personal\n")
        result = self.push("origin", "feature")
        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertEqual(self.remote_sha("feature"), sha)

    def test_one_bad_ref_refuses_the_whole_push(self):
        """Intent: a push is all or nothing - one clean and one leaking ref in the same push
        and neither reaches the remote."""
        self.home_patterns(self.SECRET)
        self.branch("clean-one", "x.md", "nothing personal\n")
        self.branch("leaky", "y.md", f"the {self.SECRET} host-marker\n")
        result = self.push("origin", "clean-one", "leaky")
        self.assertNotEqual(result.returncode, 0, self.output(result))
        self.assertEqual(self.remote_sha("clean-one"), "")
        self.assertEqual(self.remote_sha("leaky"), "")
        self.assertIn("y.md:1", self.output(result))

    def test_deleting_a_remote_branch_passes_without_a_pattern_file(self):
        """Intent: a deletion adds no lines, so there is nothing to scan and no reason to
        demand the pattern file."""
        sha = self.branch("feature")
        self.git("push", "-q", "--no-verify", "origin", "feature")
        self.assertEqual(self.remote_sha("feature"), sha)
        result = self.push("origin", "--delete", "feature")
        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertEqual(self.remote_sha("feature"), "")

    def test_a_tag_push_is_not_gated(self):
        """Intent: by design, only branch refs are gated; a lightweight tag at a commit the
        remote already has adds no lines, so it passes with no pattern file."""
        self.git("tag", "v0")
        result = self.push("origin", "v0")
        self.assertEqual(result.returncode, 0, self.output(result))
        tag = subprocess.run(
            ["git", "--git-dir", str(self.bare), "rev-parse", "--verify", "-q", "refs/tags/v0"],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(tag, self.base)
