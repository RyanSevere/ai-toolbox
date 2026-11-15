#!/usr/bin/env python3
################################################################################
# File: test_gate_lists.py
# Path: {PROJECT_ROOT}/tests/test_gate_lists.py
# Created by: Ryan Severe
# Created: 2026-11-15
# Last Updated: 2026-11-15
# Description: Tests for gate_lists.py - the generator that builds the one-way
#              gates' pattern files from a profile. Covers what each list holds,
#              sorting and de-duplication, the refusals, that main prints counts
#              and never an entry, and that a generated file is valid input to
#              the real gates.
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

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gate_lists  # noqa: E402
import sync  # noqa: E402

ONE_WAY = Path(__file__).resolve().parent.parent / "githooks" / "one-way"
ZERO = "0" * 40

# Shell is invisible to coverage, so test selection is told what these run.
EXERCISES = ["githooks/one-way/**", "githooks/lib/**"]

SH = shutil.which("sh") or next(
    (p for p in (r"C:\Program Files\Git\usr\bin\sh.exe", "/bin/sh") if Path(p).exists()),
    None,
)

PROFILE = {
    "source": {"repo": "alpha-core", "key": "alpha", "owner": "example-owner"},
    "identity": {"name": "Example", "email": "someone@example.invalid"},
    "personal": ["beta-private", "gamma-private"],
    "profile_name": "exa",
    "leak_extra": ["internal.example.invalid"],
    "targets": {
        "t-one": {"key": "tone"},
        "t-gone": {"key": "gone", "skip": True},
    },
    "tracked": {"t-pub": {"key": "pub", "reason": "r"}},
}


def profile(**changes) -> dict:
    """PROFILE with each given key replaced, or removed when its value is None."""
    merged = {**PROFILE, **changes}
    return {k: v for k, v in merged.items() if v is not None}


def keyed(*keys: str) -> set[str]:
    return {f"{key}-{n}" for key in keys for n in range(1, 10)}


class Build(unittest.TestCase):
    def test_every_source_is_in_the_leak_list(self):
        """Intent: the leak list holds the personal repositories, nine numbered references
        for each source, target and tracked key, the profile and source names, the identity
        email and the hand-kept extras, and a skipped target's key is left out."""
        leak, _ = gate_lists.build(PROFILE)
        expected = {"beta-private", "gamma-private", "exa", "alpha-core",
                    "someone@example.invalid", "internal.example.invalid"}
        expected |= keyed("alpha", "tone", "pub")
        self.assertEqual(set(leak), expected)
        self.assertFalse(set(leak) & keyed("gone"))

    def test_core_names_are_the_source_and_the_profile_name(self):
        """Intent: the core must name neither the profile nor its source, and without a
        profile name only the source is listed."""
        _, names = gate_lists.build(PROFILE)
        self.assertEqual(names, ["alpha-core", "exa"])
        _, alone = gate_lists.build(profile(profile_name=None))
        self.assertEqual(alone, ["alpha-core"])

    def test_output_is_sorted_and_each_entry_appears_once(self):
        """Intent: a name kept in two places is one pattern, and the list order does not
        depend on how the profile happens to be written."""
        leak, names = gate_lists.build(profile(
            personal=["beta-private", "zeta-private"], leak_extra=["beta-private", "exa"]))
        self.assertEqual(leak, sorted(set(leak)))
        self.assertEqual(leak.count("beta-private"), 1)
        self.assertEqual(leak.count("exa"), 1)
        self.assertEqual(names, sorted(set(names)))

    def test_a_profile_without_a_source_repo_is_refused(self):
        """Intent: an empty list would pass everything, so a profile with no source.repo is
        refused rather than written as an empty file."""
        for source in ({"key": "alpha"}, {"repo": ""}, None):
            with self.subTest(source=source), self.assertRaises(sync.SyncError) as ctx:
                gate_lists.build(profile(source=source))
            self.assertIn("source.repo", str(ctx.exception))

    def test_an_entry_that_is_not_a_non_empty_string_is_refused(self):
        """Intent: a blank or non-string entry would write an empty pattern line that
        matches every line, so it is refused with the key named and the entry unprinted."""
        for key in ("leak_extra", "personal"):
            for entry in (3, "", "  ", ["x"], None):
                with self.subTest(key=key, entry=entry), \
                        self.assertRaises(sync.SyncError) as ctx:
                    gate_lists.build(profile(**{key: ["fine-name", entry]}))
                self.assertIn(key, str(ctx.exception))

    def test_an_entry_the_gates_would_read_differently_is_refused(self):
        """Intent: the gates drop a line that starts with # and read a line break as two
        patterns, so an entry carrying either is refused rather than silently changed."""
        for entry in ("#hash", "two\nlines", "cr\rhere"):
            with self.subTest(entry=entry), self.assertRaises(sync.SyncError):
                gate_lists.build(profile(leak_extra=[entry]))

    def test_surrounding_space_is_trimmed(self):
        """Intent: the gates trim each line, so an entry with spaces round it is written
        trimmed and still means what it says."""
        leak, _ = gate_lists.build(profile(leak_extra=["  spaced  "]))
        self.assertIn("spaced", leak)


class CoreOwnName(unittest.TestCase):
    def test_the_core_repo_is_left_off_the_leak_list(self):
        """Intent: the core names itself throughout, so its own repository name is never on
        its leak list, whether the profile lists it as personal, in leak_extra, or in another
        case. Other personal names stay."""
        for changes in ({"personal": ["example-core", "alpha"]},
                        {"personal": ["EXAMPLE-Core", "alpha"]},
                        {"personal": ["alpha"], "leak_extra": ["example-core"]}):
            with self.subTest(changes=changes):
                leak, names = gate_lists.build(profile(**changes), core_repo="example-core")
                self.assertNotIn("example-core", [entry.lower() for entry in leak])
                self.assertIn("alpha", leak)
                self.assertEqual(names, ["alpha-core", "exa"])

    def test_without_a_core_repo_the_name_stays_on_the_list(self):
        """Intent: in the core's own source repository there is no vendored record, so
        nothing is left out and the list is as it was."""
        leak, _ = gate_lists.build(profile(personal=["example-core", "alpha"]))
        self.assertIn("example-core", leak)
        self.assertIn("alpha", leak)


class Main(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.leak = self.dir / "leak.txt"
        self.names = self.dir / "core-names.txt"
        self.core = self.dir / "core"
        self.core.mkdir()
        self.write_profile(PROFILE)

    def write_profile(self, data: dict) -> None:
        (self.dir / "profile.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")

    def write_vendored(self, text: str) -> None:
        (self.core / "VENDORED").write_bytes(text.encode("utf-8"))

    def run_main(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["--profile", str(self.dir), "--leak", str(self.leak),
                "--core-names", str(self.names), *extra]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate_lists.main(argv, core=self.core)
        return code, out.getvalue(), err.getvalue()

    def test_a_vendored_core_leaves_its_own_name_off_the_written_list(self):
        """Intent: run beside a VENDORED record, main reads the core's repository name from
        it, leaves that name off the leak file, and says so in words."""
        self.write_profile(profile(personal=["example-core", "alpha"]))
        self.write_vendored(
            "source=example-owner/example-core\ntag=v1.2.3\nsha=" + "0" * 40
            + "\ncontent-hash=sha256:" + "0" * 64 + "\n")
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        written = self.leak.read_text(encoding="utf-8").splitlines()
        self.assertNotIn("example-core", written)
        self.assertIn("alpha", written)
        self.assertIn("leaving out the core's own name (example-core)", out)

    def test_without_a_vendored_record_nothing_is_left_out(self):
        """Intent: in the core's own source repository there is no VENDORED, and the name
        stays on the list, with no mention of leaving anything out."""
        self.write_profile(profile(personal=["example-core", "alpha"]))
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertIn("example-core", self.leak.read_text(encoding="utf-8").splitlines())
        self.assertNotIn("leaving out", out)

    def test_a_malformed_vendored_record_is_refused_and_writes_nothing(self):
        """Intent: a VENDORED that exists but cannot be read is refused, never read as no
        record, so no list that would refuse the core's own history is written."""
        self.write_vendored("this is not a record\n")
        code, out, err = self.run_main()
        self.assertNotEqual(code, 0)
        self.assertIn("[ERROR]", err)
        self.assertFalse(self.leak.exists())
        self.assertFalse(self.names.exists())

    def test_it_writes_one_entry_per_line_and_prints_only_counts(self):
        """Intent: both files hold one entry per line with a trailing newline, as UTF-8 with
        no BOM, and nothing a pattern file holds reaches the output, which is logged."""
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        leak, names = gate_lists.build(PROFILE)
        raw = self.leak.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(raw.endswith(b"\n"))
        self.assertNotIn(b"\r", raw)
        self.assertEqual(raw.decode("utf-8").splitlines(), leak)
        self.assertEqual(self.names.read_bytes().decode("utf-8").splitlines(), names)
        shown = (out + err).replace(str(self.leak), "").replace(str(self.names), "")
        for entry in leak + names:
            self.assertNotIn(entry, shown)
        self.assertIn(str(len(leak)), shown)
        self.assertIn(str(len(names)), shown)
        self.assertIn("[OK]", shown)

    def test_a_refusal_prints_no_entry_and_writes_nothing(self):
        """Intent: a profile that cannot produce a safe list fails with an error that names
        the key, never an entry, and leaves no half-written file behind."""
        self.write_profile(profile(leak_extra=["secret-entry", 3]))
        code, out, err = self.run_main()
        self.assertNotEqual(code, 0)
        self.assertIn("leak_extra", out + err)
        self.assertNotIn("secret-entry", out + err)
        self.assertFalse(self.leak.exists())
        self.assertFalse(self.names.exists())


@unittest.skipIf(SH is None, "no POSIX shell available; not reporting a pass")
class RealGates(unittest.TestCase):
    """A generated file fed to the gates that read it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        self.leak = self.dir / "leak.txt"
        self.names = self.dir / "core-names.txt"
        leak, names = gate_lists.build(PROFILE)
        self.leak.write_text("".join(f"{e}\n" for e in leak), encoding="utf-8", newline="\n")
        self.names.write_text("".join(f"{e}\n" for e in names), encoding="utf-8", newline="\n")
        for args in (("init", "-q", "."), ("config", "user.email", "t@t"),
                     ("config", "user.name", "t")):
            self.git(*args)

    def git(self, *args: str) -> str:
        return subprocess.run(("git",) + args, cwd=self.repo, capture_output=True,
                              text=True).stdout.strip()

    def sh(self, script: str, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "LC_ALL": "C"}
        env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
        return subprocess.run([SH, (ONE_WAY / script).as_posix(), *args], cwd=self.repo,
                              capture_output=True, text=True, env=env)

    def leak_gate(self, text: str) -> subprocess.CompletedProcess:
        (self.repo / "a.txt").write_text("x\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        base = self.git("rev-parse", "HEAD")
        (self.repo / "b.txt").write_text(text, encoding="utf-8", newline="\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "second")
        return self.sh("leak-denylist.sh", self.leak.as_posix(), self.git("rev-parse", "HEAD"), base)

    def test_the_leak_gate_refuses_a_numbered_reference_and_passes_a_longer_word(self):
        """Intent: the generated leak file is valid gate input: alpha-3 is refused, and
        alphabet, which only starts like the key, is not."""
        refused = self.leak_gate("see alpha-3 for it\n")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("b.txt:1", refused.stdout)

    def test_the_leak_gate_passes_text_that_only_resembles_the_key(self):
        """Intent: matching is for the whole entry, so alphabet is not alpha-N."""
        passed = self.leak_gate("the alphabet\n")
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

    def test_the_core_names_gate_reads_the_generated_file(self):
        """Intent: the generated core-names file is valid input to the core-names gate: a
        tree naming the source is refused and a clean tree passes."""
        tree = self.dir / "tree"
        tree.mkdir()
        (tree / "f.md").write_text("generic text\n", encoding="utf-8")
        clean = self.sh("core-names-no-profile.sh", self.names.as_posix(), tree.as_posix())
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        (tree / "f.md").write_text("made at alpha-core\n", encoding="utf-8")
        dirty = self.sh("core-names-no-profile.sh", self.names.as_posix(), tree.as_posix())
        self.assertEqual(dirty.returncode, 1, dirty.stdout + dirty.stderr)


if __name__ == "__main__":
    unittest.main()
