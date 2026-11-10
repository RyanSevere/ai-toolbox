################################################################################
# File: test_vendor.py
# Path: {PROJECT_ROOT}/tests/test_vendor.py
# Created by: Ryan Severe
# Created: 2026-10-28
# Last Updated: 2026-11-08
# Description: The vendored core: source validation, the byte-exact
#              content hash, core/VENDORED, sync.py --check-core, --vendor-core
#              against in-memory archives and --check-updates against fake tag
#              lists, both through a fake fetch, all offline.
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
import json
import os
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402
import vendor  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
FILES = {
    "sync.py": b"print('core')\n",
    "rules/a.md": b"# a\r\nwindows line\n",
    "skills/b/procedure.md": b"b\n",
}


def offline():
    """Any socket use fails the test: everything here is offline by design."""
    return mock.patch("socket.socket", side_effect=AssertionError("network used"))


def make_core(test: unittest.TestCase, files: dict[str, bytes] | None = None) -> Path:
    """A vendored core/ inside a profile folder: files, .gitattributes, a matching VENDORED."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    profile = Path(tmp.name)
    (profile / "profile.yaml").write_text("source: {}\n", encoding="utf-8")
    core = profile / vendor.CORE_DIR
    for rel, data in (FILES if files is None else files).items():
        path = core / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (core / vendor.GITATTRIBUTES).write_bytes(vendor.GITATTRIBUTES_TEXT.encode())
    record = vendor.Record("example-owner/ai-toolbox", "v1.2.3", SHA, vendor.content_hash(core))
    write_record(core, vendor.format_record(record))
    return core


def write_record(core: Path, text: str) -> None:
    (core / vendor.VENDORED).write_bytes(text.encode("utf-8"))


def record_text(**overrides: str) -> str:
    values = {"source": "example-owner/ai-toolbox", "tag": "v1.2.3", "sha": SHA,
              "content-hash": "sha256:" + "0" * 64, **overrides}
    return "".join(f"{key}={value}\n" for key, value in values.items())


class ParseSource(unittest.TestCase):
    def test_a_tag_is_accepted(self):
        """Intent: "Vendor by tag or SHA"; releases are vX.Y.Z tags."""
        source = vendor.parse_source("example-owner/ai-toolbox@v1.20.3")
        self.assertEqual((source.owner, source.repo, source.ref),
                         ("example-owner", "ai-toolbox", "v1.20.3"))
        self.assertTrue(source.is_tag)

    def test_a_full_sha_is_accepted(self):
        """Intent: "Vendor by tag or SHA"."""
        source = vendor.parse_source(f"o/r.name_x@{SHA}")
        self.assertEqual(source.ref, SHA)
        self.assertFalse(source.is_tag)

    def test_anything_else_is_refused(self):
        """Intent: validate <owner>/<repo>@<ref> before it reaches a URL: a
        vX.Y.Z tag or a hex SHA; owner and repository names from a fixed character set."""
        for text in ("", "o/r", "o/r@", "@v1.2.3", "o@v1.2.3", "a/b/c@v1.2.3", "/r@v1.2.3",
                     "o/@v1.2.3", "o/r@v1.2", "o/r@1.2.3", "o/r@v1.2.3-rc1", "o/r@v01.2.3",
                     "o/r@main", "o/r@" + SHA[:7], "o/r@" + SHA.upper(), "o/r@" + "g" * 40,
                     "o/r@" + SHA + "0", "-o/r@v1.2.3", "o-/r@v1.2.3", "o" * 40 + "/r@v1.2.3",
                     "o o/r@v1.2.3", "o/r r@v1.2.3", "o/..@v1.2.3", "o/.@v1.2.3",
                     "o/r?x=1@v1.2.3", "o/r#x@v1.2.3", "o/r@v1.2.3\n", "o/r@v1.2.3@v1.2.4",
                     "../o/r@v1.2.3", "o\\r@v1.2.3", "o/r%2F..@v1.2.3"):
            with self.subTest(text=text), self.assertRaises(vendor.VendorError):
                vendor.parse_source(text)

    def test_a_non_string_is_refused(self):
        """Intent: validate every externally supplied value - a YAML value may not be a string."""
        for value in (None, 12, ["o/r@v1.2.3"]):
            with self.subTest(value=value), self.assertRaises(vendor.VendorError):
                vendor.parse_source(value)


class ContentHash(unittest.TestCase):
    def test_identical_trees_hash_alike(self):
        self.assertEqual(vendor.content_hash(make_core(self)), vendor.content_hash(make_core(self)))

    def test_one_byte_changes_it(self):
        """Intent: a hash of core/'s contents, so any edit is visible."""
        core = make_core(self)
        before = vendor.content_hash(core)
        (core / "skills/b/procedure.md").write_bytes(b"c\n")
        self.assertNotEqual(vendor.content_hash(core), before)

    def test_a_rename_changes_it(self):
        core = make_core(self)
        before = vendor.content_hash(core)
        (core / "sync.py").rename(core / "sync2.py")
        self.assertNotEqual(vendor.content_hash(core), before)

    def test_moving_bytes_between_files_changes_it(self):
        """Characterisation: path and length are framed, so ab+c and a+bc differ."""
        one = make_core(self, {"x": b"ab", "y": b"c"})
        two = make_core(self, {"x": b"a", "y": b"bc"})
        self.assertNotEqual(vendor.content_hash(one), vendor.content_hash(two))

    def test_an_empty_file_counts(self):
        core = make_core(self)
        before = vendor.content_hash(core)
        (core / "empty").write_bytes(b"")
        self.assertNotEqual(vendor.content_hash(core), before)

    def test_line_endings_are_bytes_like_any_other(self):
        """Intent: the hash is of the archive's exact bytes; the
        rendered .gitattributes, not normalisation, is what keeps a checkout matching."""
        lf = make_core(self, {"a.md": b"x\n"})
        crlf = make_core(self, {"a.md": b"x\r\n"})
        self.assertNotEqual(vendor.content_hash(lf), vendor.content_hash(crlf))

    def test_vendored_is_not_hashed(self):
        """Intent: VENDORED records the hash, so it cannot be part of it."""
        core = make_core(self)
        before = vendor.content_hash(core)
        write_record(core, "anything\n")
        self.assertEqual(vendor.content_hash(core), before)

    def test_vendored_is_hashed_when_not_at_the_top(self):
        core = make_core(self)
        before = vendor.content_hash(core)
        (core / "rules" / vendor.VENDORED).write_bytes(b"x\n")
        self.assertNotEqual(vendor.content_hash(core), before)

    def test_pycache_is_not_hashed(self):
        """Intent: a profile runs `python core/sync.py`, which writes
        core/__pycache__. A check that its own run breaks would be ignored."""
        core = make_core(self)
        before = vendor.content_hash(core)
        (core / "__pycache__").mkdir()
        (core / "__pycache__" / "vendor.cpython-311.pyc").write_bytes(b"\0cache")
        (core / "rules" / "__pycache__").mkdir()
        (core / "rules" / "__pycache__" / "x.pyc").write_bytes(b"\0cache")
        self.assertEqual(vendor.content_hash(core), before)

    def test_a_symlink_is_refused(self):
        """Intent: a vendored archive extracts no links; following one hashes outside core/."""
        core = make_core(self)
        try:
            os.symlink(core / "sync.py", core / "link.py")
        except (OSError, NotImplementedError):
            self.skipTest("this machine cannot create symbolic links")
        with self.assertRaises(vendor.VendorError):
            vendor.content_hash(core)


class ReadRecord(unittest.TestCase):
    def setUp(self):
        self.core = make_core(self)

    def test_it_round_trips(self):
        record = vendor.Record("example-owner/ai-toolbox", "", SHA, "sha256:" + "f" * 64)
        write_record(self.core, vendor.format_record(record))
        self.assertEqual(vendor.read_record(self.core), record)

    def test_malformed_is_refused(self):
        """Intent: prescriptions - unknown is not zero. A VENDORED that cannot be read
        fully is a refusal, never a blank or a partial record."""
        cases = {
            "missing key": record_text().replace(f"sha={SHA}\n", ""),
            "unknown key": record_text() + "extra=1\n",
            "no equals": record_text() + "source\n",
            "duplicate": record_text() + "tag=v1.2.3\n",
            "short sha": record_text(sha=SHA[:12]),
            "bad source": record_text(source="o/r/x"),
            "bad tag": record_text(tag="1.2.3"),
            "bad hash": record_text(**{"content-hash": "md5:" + "0" * 32}),
            "short hash": record_text(**{"content-hash": "sha256:" + "0" * 63}),
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                write_record(self.core, text)
                with self.assertRaises(vendor.VendorError):
                    vendor.read_record(self.core)

    def test_missing_is_refused(self):
        (self.core / vendor.VENDORED).unlink()
        with self.assertRaises(vendor.VendorError) as caught:
            vendor.read_record(self.core)
        self.assertIn("missing", str(caught.exception))

    def test_not_utf8_is_refused(self):
        (self.core / vendor.VENDORED).write_bytes(b"\xff\xfe")
        with self.assertRaises(vendor.VendorError):
            vendor.read_record(self.core)


class CheckCore(unittest.TestCase):
    def setUp(self):
        self.core = make_core(self)

    def test_an_untouched_core_passes(self):
        with offline():
            record = vendor.check_core(self.core)
        self.assertEqual((record.tag, record.sha), ("v1.2.3", SHA))

    def test_any_local_change_is_refused(self):
        """Intent: core/ with a local edit is refused by --check-core."""
        edits = {
            "edited": lambda c: (c / "sync.py").write_bytes(b"print('mine')\n"),
            "added": lambda c: (c / "new.md").write_bytes(b"new\n"),
            "deleted": lambda c: (c / "rules/a.md").unlink(),
            "crlf": lambda c: (c / "sync.py").write_bytes(b"print('core')\r\n"),
        }
        for label, edit in edits.items():
            with self.subTest(edit=label):
                core = make_core(self)
                edit(core)
                with offline(), self.assertRaises(vendor.VendorError) as caught:
                    vendor.check_core(core)
                self.assertIn("never edited in place", str(caught.exception))

    def test_a_missing_or_changed_gitattributes_is_refused(self):
        """Intent: core/.gitattributes is what stops git
        rewriting line endings, so its absence is reported by name."""
        for label, change in {"missing": lambda p: p.unlink(),
                              "changed": lambda p: p.write_bytes(b"* text=auto\n")}.items():
            with self.subTest(change=label):
                core = make_core(self)
                change(core / vendor.GITATTRIBUTES)
                with self.assertRaises(vendor.VendorError) as caught:
                    vendor.check_core(core)
                self.assertIn(vendor.GITATTRIBUTES, str(caught.exception))

    def test_no_vendored_is_refused_not_passed(self):
        """Intent: non-zero on any difference; an absent record is one."""
        (self.core / vendor.VENDORED).unlink()
        with self.assertRaises(vendor.VendorError):
            vendor.check_core(self.core)

    def test_no_core_is_refused(self):
        with self.assertRaises(vendor.VendorError) as caught:
            vendor.check_core(self.core.parent / "elsewhere")
        self.assertIn("no core is vendored", str(caught.exception))

    def test_running_python_from_core_does_not_break_it(self):
        """Intent: `python core/sync.py` writes core/__pycache__."""
        (self.core / "__pycache__").mkdir()
        (self.core / "__pycache__" / "sync.cpython-311.pyc").write_bytes(b"\0")
        vendor.check_core(self.core)


class CheckCoreCommand(unittest.TestCase):
    """sync.py --check-core, through main() as a profile runs it."""

    def run_main(self, profile: Path) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["sync.py", "--check-core", "--profile", str(profile)]
        with mock.patch.object(sys, "argv", argv), offline(), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main()
        return code, out.getvalue(), err.getvalue()

    def test_a_matching_core_exits_zero(self):
        """Intent: --check-core: recompute and compare offline."""
        core = make_core(self)
        code, out, _ = self.run_main(core.parent)
        self.assertEqual(code, 0)
        self.assertIn("[OK]", out)
        self.assertIn(SHA[:12], out)

    def test_an_edited_core_exits_non_zero(self):
        """Intent: non-zero on any difference."""
        core = make_core(self)
        (core / "sync.py").write_bytes(b"edited\n")
        code, out, err = self.run_main(core.parent)
        self.assertEqual(code, 1)
        self.assertNotIn("[OK]", out)
        self.assertIn("[ERROR]", err)

    def test_a_profile_with_no_core_exits_non_zero(self):
        core = make_core(self)
        (core / vendor.VENDORED).unlink()
        code, _, err = self.run_main(core.parent)
        self.assertEqual(code, 1)
        self.assertIn("missing", err)

    def test_it_does_not_need_a_valid_profile(self):
        """Characterisation: --check-core reads only core/, so a profile.yaml the render
        would refuse does not stop the offline check from answering."""
        core = make_core(self)
        (core.parent / "profile.yaml").write_text("not_a_key: 1\n", encoding="utf-8")
        code, _, _ = self.run_main(core.parent)
        self.assertEqual(code, 0)


SHA2 = "fedcba9876543210fedcba9876543210fedcba98"
TOP = f"ai-toolbox-{SHA2}"
NEW = {
    "sync.py": b"print('new core')\n",
    "rules/c.md": b"c\r\n",
    "skills/d/procedure.md": b"d\n",
}
TAG_SOURCE = "example-owner/ai-toolbox@v2.0.0"
COMMIT_URL = "https://api.github.com/repos/example-owner/ai-toolbox/commits/v2.0.0"
ARCHIVE_URL = f"https://codeload.github.com/example-owner/ai-toolbox/tar.gz/{SHA2}"


def tar_member(name: str, data: bytes = b"", kind: bytes = tarfile.REGTYPE,
               link: str = "") -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    info.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
    return info, data


def make_archive(files: dict[str, bytes] | None = None, top: str = TOP,
                 extra: tuple | list = ()) -> bytes:
    """A gzip tar shaped like codeload's: a global pax header, one top folder, its files."""
    members = [tar_member(top, kind=tarfile.DIRTYPE)] if top else []
    for rel, data in (NEW if files is None else files).items():
        members.append(tar_member(f"{top}/{rel}" if top else rel, data))
    members.extend(extra)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers={"comment": SHA2}) as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if info.isfile() else None)
    return buffer.getvalue()


class FakeFetch:
    """Stands in for vendor.http_get: records every URL and never touches the network."""

    def __init__(self, archive: bytes | None = None, sha: bytes = SHA2.encode() + b"\n",
                 fail: bool = False):
        self.archive = make_archive() if archive is None else archive
        self.sha = sha
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, url: str, accept: str) -> bytes:
        self.calls.append(url)
        if self.fail:
            raise vendor.VendorError(f"could not fetch {url}: connection refused")
        if "/commits/" in url:
            return self.sha
        return self.archive


def snapshot(core: Path) -> dict[str, bytes]:
    return {p.relative_to(core).as_posix(): p.read_bytes()
            for p in sorted(core.rglob("*")) if p.is_file()}


class VendorCore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)
        (self.profile / "profile.yaml").write_text("source: {}\n", encoding="utf-8")
        self.core = self.profile / vendor.CORE_DIR

    def use_old_core(self) -> None:
        """Start from a clean vendored core, as a profile updating its pin would."""
        self.core = make_core(self)
        self.profile = self.core.parent

    def vendor(self, source: str = TAG_SOURCE, fetch: FakeFetch | None = None):
        fetch = FakeFetch() if fetch is None else fetch
        with offline():
            record, notes = vendor.vendor_core(self.profile, source, fetch)
        return record, notes, fetch

    def leftovers(self) -> list[str]:
        return [p.name for p in self.profile.iterdir()
                if p.name.startswith((vendor.INCOMING, vendor.OUTGOING))]

    def test_by_tag_populates_core_and_vendored(self):
        """Intent: --vendor-core populates core/ and VENDORED from a
        fixture archive, by tag."""
        record, _, _ = self.vendor()
        self.assertEqual((record.source, record.tag, record.sha),
                         ("example-owner/ai-toolbox", "v2.0.0", SHA2))
        for rel, data in NEW.items():
            self.assertEqual((self.core / rel).read_bytes(), data)
        self.assertEqual(vendor.read_record(self.core), record)
        self.assertEqual(vendor.check_core(self.core), record)

    def test_a_tag_is_resolved_then_fetched_at_its_sha(self):
        """Intent: the archive is fetched at the resolved SHA,
        never at the tag, so the archive and the recorded SHA cannot disagree."""
        _, _, fetch = self.vendor()
        self.assertEqual(fetch.calls, [COMMIT_URL, ARCHIVE_URL])

    def test_by_sha_populates_core_without_resolving(self):
        """Intent: --vendor-core populates core/ and VENDORED, by SHA."""
        record, _, fetch = self.vendor(f"example-owner/ai-toolbox@{SHA2}")
        self.assertEqual((record.tag, record.sha), ("", SHA2))
        self.assertEqual(fetch.calls, [ARCHIVE_URL])
        vendor.check_core(self.core)

    def test_an_archived_gitattributes_is_replaced_and_said_so(self):
        """Intent: the archive's own .gitattributes is replaced by
        the fixed one, and the replacement is reported."""
        archive = make_archive({**NEW, vendor.GITATTRIBUTES: b"* text=auto\n"})
        _, notes, _ = self.vendor(fetch=FakeFetch(archive))
        self.assertEqual((self.core / vendor.GITATTRIBUTES).read_bytes(),
                         vendor.GITATTRIBUTES_TEXT.encode())
        self.assertTrue(any(vendor.GITATTRIBUTES in note for note in notes), notes)

    def test_a_clean_core_is_replaced(self):
        """Intent: "if the public repo changes i would still want a way
        to update the copies"."""
        self.use_old_core()
        self.vendor()
        self.assertFalse((self.core / "rules/a.md").exists())
        self.assertEqual(snapshot(self.core).keys() - {vendor.VENDORED, vendor.GITATTRIBUTES},
                         NEW.keys())
        self.assertEqual(sorted(p.name for p in self.profile.iterdir()),
                         [vendor.CORE_DIR, "profile.yaml"])

    def test_a_locally_edited_core_is_refused_and_left_alone(self):
        """Intent: core/ with a local edit is refused by --vendor-core."""
        self.use_old_core()
        (self.core / "sync.py").write_bytes(b"print('mine')\n")
        before = snapshot(self.core)
        fetch = FakeFetch()
        with self.assertRaises(vendor.VendorError) as caught:
            self.vendor(fetch=fetch)
        self.assertIn("never edited in place", str(caught.exception))
        self.assertEqual(fetch.calls, [])
        self.assertEqual(snapshot(self.core), before)

    def test_a_core_nothing_vendored_is_refused(self):
        """Intent: refuses local edits; a core with no record is one."""
        self.use_old_core()
        (self.core / vendor.VENDORED).unlink()
        before = snapshot(self.core)
        with self.assertRaises(vendor.VendorError):
            self.vendor()
        self.assertEqual(snapshot(self.core), before)

    def test_a_malformed_source_is_refused_before_any_call(self):
        """Intent: a malformed source is refused before any network call."""
        for text in ("example-owner/ai-toolbox@main", "o/r@v1.2", "../o/r@v1.2.3", ""):
            with self.subTest(text=text):
                fetch = FakeFetch()
                with self.assertRaises(vendor.VendorError):
                    self.vendor(text, fetch)
                self.assertEqual(fetch.calls, [])
                self.assertFalse(self.core.exists())

    def test_a_failed_download_leaves_core_intact(self):
        """Intent: a failed or partial download leaves the previous
        core/ intact."""
        cases = {
            "refused": FakeFetch(fail=True),
            "truncated": FakeFetch(make_archive()[:-40]),
            "not an archive": FakeFetch(b"<html>rate limited</html>"),
        }
        for label, fetch in cases.items():
            with self.subTest(case=label):
                self.use_old_core()
                before = snapshot(self.core)
                with self.assertRaises(vendor.VendorError):
                    self.vendor(fetch=fetch)
                self.assertEqual(snapshot(self.core), before)
                vendor.check_core(self.core)
                self.assertEqual(self.leftovers(), [])

    def test_a_failure_during_the_swap_restores_the_old_core(self):
        """Intent: swap it in for core/ only after extraction succeeds; a
        swap that fails partway puts the previous core/ back."""
        self.use_old_core()
        before = snapshot(self.core)
        real = Path.rename

        def rename(path, target):
            if Path(path).name.startswith(vendor.INCOMING) and Path(target) == self.core:
                raise OSError("simulated: the new core could not be moved in")
            return real(path, target)

        with mock.patch.object(Path, "rename", rename), \
                self.assertRaises(vendor.VendorError) as caught:
            self.vendor()
        self.assertIn("restored", str(caught.exception))
        self.assertEqual(snapshot(self.core), before)
        vendor.check_core(self.core)
        self.assertEqual(self.leftovers(), [])

    def test_an_unsafe_archive_is_refused_and_writes_nothing(self):
        """Intent: refuse archive members that escape the
        target, and anything an archive of a core cannot legitimately hold."""
        cases = {
            "parent segment": [tar_member(f"{TOP}/../escape.txt", b"x")],
            "absolute": [tar_member("/escape.txt", b"x")],
            "colon": [tar_member(f"{TOP}/rules:stream", b"x")],
            "backslash": [tar_member(f"{TOP}/..\\escape.txt", b"x")],
            "symlink": [tar_member(f"{TOP}/link", kind=tarfile.SYMTYPE, link="../../escape.txt")],
            "hardlink": [tar_member(f"{TOP}/hard", kind=tarfile.LNKTYPE, link=f"{TOP}/sync.py")],
            "fifo": [tar_member(f"{TOP}/pipe", kind=tarfile.FIFOTYPE)],
            "second top folder": [tar_member("other/x.md", b"x")],
            "duplicate": [tar_member(f"{TOP}/sync.py", b"again\n")],
            "case duplicate": [tar_member(f"{TOP}/SYNC.py", b"again\n")],
            "carries VENDORED": [tar_member(f"{TOP}/{vendor.VENDORED}", b"source=x\n")],
        }
        archives = {label: make_archive(extra=extra) for label, extra in cases.items()}
        archives["file at the top"] = make_archive({"loose.md": b"x"}, top="")
        archives["no files"] = make_archive({})
        for label, archive in archives.items():
            with self.subTest(case=label):
                self.use_old_core()
                before = snapshot(self.core)
                with self.assertRaises(vendor.VendorError):
                    self.vendor(fetch=FakeFetch(archive))
                self.assertEqual(snapshot(self.core), before)
                self.assertFalse((self.profile / "escape.txt").exists())
                self.assertFalse((self.profile.parent / "escape.txt").exists())
                self.assertEqual(self.leftovers(), [])

    def test_a_resolved_sha_that_is_not_one_is_refused(self):
        """Intent: validate every externally supplied value - the API's answer reaches a URL."""
        fetch = FakeFetch(sha=b"<html>not found</html>")
        with self.assertRaises(vendor.VendorError):
            self.vendor(fetch=fetch)
        self.assertEqual(fetch.calls, [COMMIT_URL])
        self.assertFalse(self.core.exists())

    def test_an_oversize_download_is_refused(self):
        """Intent: refuse beyond 50 MB downloaded."""
        with mock.patch.object(vendor, "MAX_DOWNLOAD", 100), \
                self.assertRaises(vendor.VendorError):
            self.vendor()
        self.assertFalse(self.core.exists())
        self.assertEqual(self.leftovers(), [])

    def test_an_oversize_unpacked_archive_is_refused(self):
        """Intent: refuse beyond 200 MB unpacked."""
        with mock.patch.object(vendor, "MAX_UNPACKED", 10), \
                self.assertRaises(vendor.VendorError):
            self.vendor()
        self.assertFalse(self.core.exists())
        self.assertEqual(self.leftovers(), [])


class HttpGet(unittest.TestCase):
    @staticmethod
    def response(body: bytes) -> mock.MagicMock:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = body
        return response

    def test_every_call_carries_the_timeout(self):
        """Intent: AGENTS.md - every outbound call gets an explicit timeout."""
        with mock.patch("urllib.request.urlopen", return_value=self.response(b"body")) as urlopen:
            self.assertEqual(vendor.http_get("https://example.invalid/x", "text/plain"), b"body")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], vendor.TIMEOUT)
        self.assertEqual(urlopen.call_args.args[0].get_header("Accept"), "text/plain")

    def test_a_failed_call_is_a_refusal_never_a_body(self):
        """Intent: AGENTS.md - a failed lookup is a failure, never an empty result."""
        errors = (urllib.error.URLError("unreachable"), TimeoutError("timed out"),
                  urllib.error.HTTPError("https://x", 404, "Not Found", {}, None),
                  ConnectionResetError("reset"))
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    mock.patch("urllib.request.urlopen", side_effect=error), \
                    self.assertRaises(vendor.VendorError):
                vendor.http_get("https://example.invalid/x", "text/plain")

    def test_it_reads_at_most_one_byte_past_the_cap(self):
        """Intent: the cap bounds memory, not just the result."""
        response = self.response(b"x" * 11)
        with mock.patch.object(vendor, "MAX_DOWNLOAD", 10), \
                mock.patch("urllib.request.urlopen", return_value=response), \
                self.assertRaises(vendor.VendorError):
            vendor.http_get("https://example.invalid/x", "text/plain")
        response.__enter__.return_value.read.assert_called_once_with(11)


class VendorCoreCommand(unittest.TestCase):
    """sync.py --vendor-core, through main() as a profile runs it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)
        (self.profile / "profile.yaml").write_text("source: {}\n", encoding="utf-8")

    def run_main(self, *args: str, fetch: FakeFetch | None = None):
        fetch = FakeFetch() if fetch is None else fetch
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["sync.py", *args]), \
                mock.patch.object(vendor, "http_get", fetch), offline(), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main()
        return code, out.getvalue(), err.getvalue(), fetch

    def test_it_vendors_and_reports(self):
        """Intent: `--vendor-core <owner>/<repo>@<tag-or-sha>`."""
        code, out, _, _ = self.run_main("--vendor-core", TAG_SOURCE, "--profile", str(self.profile))
        self.assertEqual(code, 0)
        self.assertIn("[OK]", out)
        self.assertIn(SHA2[:12], out)
        vendor.check_core(self.profile / vendor.CORE_DIR)

    def test_a_failure_exits_non_zero(self):
        code, out, err, _ = self.run_main("--vendor-core", TAG_SOURCE, "--profile",
                                          str(self.profile), fetch=FakeFetch(fail=True))
        self.assertEqual(code, 1)
        self.assertNotIn("[OK]", out)
        self.assertIn("[ERROR]", err)

    def test_the_core_is_never_vendored_into_itself(self):
        """Intent: refuse when the profile is the core's own folder."""
        existed = (self.profile / vendor.CORE_DIR).exists()
        with mock.patch.object(sync, "ROOT", self.profile.resolve()):
            code, _, err, fetch = self.run_main("--vendor-core", TAG_SOURCE,
                                                "--profile", str(self.profile))
        self.assertEqual(code, 1)
        self.assertIn("into itself", err)
        self.assertEqual(fetch.calls, [])
        self.assertEqual((self.profile / vendor.CORE_DIR).exists(), existed)

    def test_it_does_not_combine_with_check_core(self):
        code, _, err, fetch = self.run_main("--vendor-core", TAG_SOURCE, "--check-core",
                                            "--profile", str(self.profile))
        self.assertEqual(code, 1)
        self.assertIn("--check-core", err)
        self.assertEqual(fetch.calls, [])


TAGS_URL = "https://api.github.com/repos/example-owner/ai-toolbox/tags?per_page=100&page="


def tag(name: str, sha: str = SHA2) -> dict:
    return {"name": name, "commit": {"sha": sha, "url": "https://example.invalid"}}


class FakeTags:
    """Stands in for vendor.http_get against the tags API, one list per page."""

    def __init__(self, *pages: list, fail: bool = False, body: bytes | None = None):
        self.pages = pages
        self.fail = fail
        self.body = body
        self.calls: list[str] = []

    def __call__(self, url: str, accept: str) -> bytes:
        self.calls.append(url)
        if self.fail:
            raise vendor.VendorError(f"could not fetch {url}: HTTP Error 403: rate limit exceeded")
        if self.body is not None:
            return self.body
        number = int(url.rsplit("page=", 1)[1])
        return json.dumps(self.pages[number - 1] if number <= len(self.pages) else []).encode()


class CheckUpdates(unittest.TestCase):
    """The vendored core is example-owner/ai-toolbox v1.2.3 at SHA."""

    def setUp(self):
        self.core = make_core(self)

    def check(self, fetch: FakeTags) -> "vendor.Updates":
        with offline():
            return vendor.check_updates(self.core, fetch)

    def report(self, fetch: FakeTags) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with offline(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vendor.updates_report(self.core, fetch)
        return code, out.getvalue(), err.getvalue()

    def test_newer_releases_are_listed_newest_first(self):
        """Intent: --check-updates lists release tags newer than VENDORED's."""
        fetch = FakeTags([tag("v1.2.3", SHA), tag("v1.3.0"), tag("v1.10.0"), tag("v2.0.0"),
                          tag("v1.2.2"), tag("latest"), tag("v1.2"), tag("v3.0.0-rc1")])
        self.assertEqual(self.check(fetch).newer, ["v2.0.0", "v1.10.0", "v1.3.0"])

    def test_newer_releases_exit_two(self):
        """Intent: 2 means newer versions are available."""
        code, out, _ = self.report(FakeTags([tag("v1.2.3", SHA), tag("v1.3.0")]))
        self.assertEqual(code, 2)
        self.assertIn("v1.3.0", out)
        self.assertNotIn("up to date", out)

    def test_up_to_date_exits_zero(self):
        """Intent: 0 means up to date."""
        code, out, _ = self.report(FakeTags([tag("v1.2.3", SHA), tag("v1.2.2")]))
        self.assertEqual(code, 0)
        self.assertIn("[OK] up to date", out)

    def test_it_asks_the_vendored_source(self):
        fetch = FakeTags([tag("v1.2.3", SHA)])
        self.check(fetch)
        self.assertEqual(fetch.calls, [TAGS_URL + "1"])

    def test_a_failed_lookup_is_unknown_never_up_to_date(self):
        """Intent: a failed update lookup reports unknown, never "up to
        date". Exit code 3 means could not check."""
        cases = {
            "refused": FakeTags(fail=True),
            "not json": FakeTags(body=b"<html>rate limited</html>"),
            "not a list": FakeTags(body=b'{"message": "Not Found"}'),
            "empty object": FakeTags(body=b"{}"),
            "nameless entry": FakeTags([{"commit": {"sha": SHA}}]),
            "entry not an object": FakeTags(["v1.2.3"]),
            "release with a bad sha": FakeTags([tag("v1.2.3", SHA), tag("v1.3.0", "nope")]),
            "release with no commit": FakeTags([tag("v1.2.3", SHA), {"name": "v1.3.0"}]),
        }
        for label, fetch in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(vendor.LookupFailed):
                    self.check(fetch)
                code, out, err = self.report(fetch)
                self.assertEqual(code, 3)
                self.assertIn("could not check", err)
                self.assertNotIn("[OK]", out)
                self.assertNotIn("up to date", out)

    def test_every_page_is_read(self):
        """Intent: unknown is not zero - a release on page two is still a release."""
        first = [tag(f"v0.0.{n}") for n in range(vendor.TAGS_PER_PAGE)]
        fetch = FakeTags(first, [tag("v1.2.3", SHA), tag("v1.4.0")])
        self.assertEqual(self.check(fetch).newer, ["v1.4.0"])
        self.assertEqual(fetch.calls, [TAGS_URL + "1", TAGS_URL + "2"])

    def test_too_many_pages_is_unknown(self):
        """Intent: unknown is not zero - a list cut off at the cap is not known complete."""
        full = [tag(f"v0.0.{n}") for n in range(vendor.TAGS_PER_PAGE)]
        fetch = FakeTags(*[full] * (vendor.MAX_TAG_PAGES + 1))
        with self.assertRaises(vendor.LookupFailed):
            self.check(fetch)
        self.assertEqual(len(fetch.calls), vendor.MAX_TAG_PAGES)

    def test_vendored_by_sha_is_unknown_with_the_newest_release(self):
        """Intent: by SHA, list the newest release and say newer
        is unknown; exit 3."""
        record = vendor.Record("example-owner/ai-toolbox", "", SHA, vendor.content_hash(self.core))
        write_record(self.core, vendor.format_record(record))
        code, out, _ = self.report(FakeTags([tag("v1.2.3", SHA), tag("v1.4.0")]))
        self.assertEqual(code, 3)
        self.assertIn("v1.4.0", out)
        self.assertIn("unknown", out)
        self.assertNotIn("up to date", out)

    def test_a_moved_or_missing_vendored_tag_warns_and_is_unknown(self):
        """Intent: warn when the vendored tag is gone or points at a
        different SHA, and exit 3."""
        cases = {
            "moved": FakeTags([tag("v1.2.3", SHA2)]),
            "missing": FakeTags([tag("v1.2.2")]),
        }
        for label, fetch in cases.items():
            with self.subTest(case=label):
                self.assertTrue(self.check(fetch).warnings)
                code, out, _ = self.report(fetch)
                self.assertEqual(code, 3)
                self.assertIn("[WARN]", out)
                self.assertNotIn("up to date", out)

    def test_a_bad_record_is_refused_before_any_call(self):
        """Intent: 1 means refused: VENDORED missing or invalid."""
        (self.core / vendor.VENDORED).unlink()
        fetch = FakeTags([tag("v1.2.3", SHA)])
        code, _, err = self.report(fetch)
        self.assertEqual(code, 1)
        self.assertIn("[ERROR]", err)
        self.assertEqual(fetch.calls, [])

    def test_it_never_changes_anything(self):
        """Intent: --check-updates never changes anything."""
        before = snapshot(self.core)
        self.report(FakeTags([tag("v1.2.3", SHA), tag("v9.0.0")]))
        self.assertEqual(snapshot(self.core), before)


class CheckUpdatesCommand(unittest.TestCase):
    """sync.py --check-updates, through main() as a profile runs it."""

    def run_main(self, *args: str, fetch: FakeTags) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["sync.py", *args]), \
                mock.patch.object(vendor, "http_get", fetch), offline(), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main()
        return code, out.getvalue(), err.getvalue()

    def test_it_reports_newer_releases(self):
        core = make_core(self)
        code, out, _ = self.run_main("--check-updates", "--profile", str(core.parent),
                                     fetch=FakeTags([tag("v1.2.3", SHA), tag("v1.3.0")]))
        self.assertEqual(code, 2)
        self.assertIn("v1.3.0", out)

    def test_a_failed_lookup_exits_three(self):
        core = make_core(self)
        code, out, _ = self.run_main("--check-updates", "--profile", str(core.parent),
                                     fetch=FakeTags(fail=True))
        self.assertEqual(code, 3)
        self.assertNotIn("up to date", out)

    def test_it_does_not_combine_with_the_other_core_commands(self):
        core = make_core(self)
        for extra in (["--check-core"], ["--vendor-core", TAG_SOURCE]):
            with self.subTest(extra=extra):
                fetch = FakeTags([tag("v1.2.3", SHA)])
                code, _, err = self.run_main("--check-updates", *extra, "--profile",
                                             str(core.parent), fetch=fetch)
                self.assertEqual(code, 1)
                self.assertIn("--check-updates", err)
                self.assertEqual(fetch.calls, [])


if __name__ == "__main__":
    unittest.main()
