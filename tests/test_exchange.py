#!/usr/bin/env python3
################################################################################
# File: test_exchange.py
# Path: {PROJECT_ROOT}/tests/test_exchange.py
# Created by: Cursor agent, for Ryan Severe
# Created: 2026-11-07
# Last Updated: 2026-11-09
# Description: The exchange append tool - an append under its lock can't drop
#              another chat's concurrent entry, a held lock is refused rather
#              than broken, and every refusal leaves the log untouched.
#              The watch command reports a new entry that names a chat, and
#              never reports silence for a log it couldn't read.
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
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

EXCHANGE = Path(__file__).resolve().parent.parent / "exchange"
sys.path.insert(0, str(EXCHANGE))
import exchange as ex  # noqa: E402

HEADER = "# Exchange\n\nAppend-only.\n\n"
NOW = datetime(2026, 11, 7, 16, 50)
WRITERS = 8


def todays_procedure(log: Path, chat: str, body: str) -> None:
    """The procedure the tool replaces: read the log, then write it back with the
    entry on the end. The pause stands in for the edit tool's gap between its read and write."""
    old = log.read_text(encoding="utf-8")
    time.sleep(0.05)
    log.write_text(f"{old}- **{chat}.** {body}\n", encoding="utf-8")


def through_the_tool(log: Path, chat: str, body: str) -> None:
    ex.append(log, chat, body, wait=30)


def race(appender: Callable[[Path, str, str], None], log: Path) -> list[str]:
    """Every chat appends at once. Returns the markers missing from the log afterwards."""
    markers = [f"MARKER-{n:02d}" for n in range(WRITERS)]
    start = threading.Barrier(WRITERS)

    def write(marker: str) -> None:
        start.wait()
        appender(log, f"chat {marker}", f"entry {marker}")

    threads = [threading.Thread(target=write, args=(m,)) for m in markers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    text = log.read_text(encoding="utf-8")
    return [m for m in markers if text.count(f"entry {m}") != 1]


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.log = self.dir / "exchange-test.md"
        self.log.write_text(HEADER, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class ConcurrentAppends(Case):
    def test_the_race_catches_todays_procedure(self) -> None:
        """Intent: shown by a test that fails against the procedure the tool replaces. The
        race below is only evidence if it catches the loss it exists for."""
        self.assertTrue(race(todays_procedure, self.log),
                        "the race lost nothing under today's procedure, so it proves nothing")

    def test_no_concurrent_entry_is_dropped(self) -> None:
        """Intent: an append under the skill can't drop another
        chat's concurrent entry."""
        self.assertEqual(race(through_the_tool, self.log), [])

    def test_existing_content_survives_the_race(self) -> None:
        """Intent: the log is append-only; nothing above the new entries moves."""
        race(through_the_tool, self.log)
        self.assertTrue(self.log.read_text(encoding="utf-8").startswith(HEADER))

    def test_separate_processes_do_not_drop_entries(self) -> None:
        """Intent: chats are separate processes, so the lock must hold across
        them, through the command line every chat calls."""
        procs = [subprocess.Popen([sys.executable, str(EXCHANGE / "exchange.py"), "append",
                                   str(self.log), "--chat", f"proc {n}", "--body",
                                   f"entry PROC-{n}"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for n in range(6)]
        for proc in procs:
            proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0)
        text = self.log.read_text(encoding="utf-8")
        for n in range(6):
            self.assertEqual(text.count(f"entry PROC-{n}"), 1, f"PROC-{n}")


class Entry(Case):
    def test_entry_is_stamped_and_attributed(self) -> None:
        """Intent: the tool stamps the entry itself,
        local time to the minute, replacing a hand-run Get-Date."""
        ex.append(self.log, "release-prep chat (my-repo)", "**It landed.**", now=NOW)
        self.assertEqual(self.log.read_text(encoding="utf-8"),
                         HEADER + "- **2026-11-07 16:50, release-prep chat (my-repo).** "
                                  "**It landed.**\n")

    def test_continuation_lines_follow_the_heading(self) -> None:
        """Intent: an exchange entry's shape - a bold heading line, then indented
        sub-bullets."""
        ex.append(self.log, "chat", "Heading.\n  - detail one\n  - detail two", now=NOW)
        self.assertTrue(self.log.read_text(encoding="utf-8").endswith(
            "- **2026-11-07 16:50, chat.** Heading.\n  - detail one\n  - detail two\n"))

    def test_log_without_trailing_newline_gets_one_first(self) -> None:
        """Intent: an entry never joins the previous one's last line."""
        self.log.write_text(HEADER + "- last entry", encoding="utf-8")
        ex.append(self.log, "chat", "next", now=NOW)
        self.assertIn("- last entry\n- **2026-11-07 16:50, chat.** next\n",
                      self.log.read_text(encoding="utf-8"))

    def test_entry_matches_a_crlf_log(self) -> None:
        """Intent: the first real append
        put six LF-only lines into a CRLF log. An entry takes the log's own line ending."""
        self.log.write_bytes(HEADER.replace("\n", "\r\n").encode("utf-8"))
        ex.append(self.log, "chat", "Heading.\n  - detail", now=NOW)
        data = self.log.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "LF-only line written")
        self.assertTrue(data.endswith(b"- **2026-11-07 16:50, chat.** Heading.\r\n  - detail\r\n"))

    def test_entry_stays_lf_in_an_lf_log(self) -> None:
        """Intent: matching the log's ending must not turn an LF log CRLF."""
        self.log.write_bytes(HEADER.encode("utf-8"))
        ex.append(self.log, "chat", "Heading.\n  - detail", now=NOW)
        self.assertNotIn(b"\r", self.log.read_bytes())

    def test_empty_body_is_refused(self) -> None:
        """Intent: prescriptions - an incomplete record is refused before it is written."""
        with self.assertRaises(ex.ExchangeError):
            ex.append(self.log, "chat", "  \n", now=NOW)
        self.assertEqual(self.log.read_text(encoding="utf-8"), HEADER)

    def test_empty_chat_is_refused(self) -> None:
        """Intent: entries are addressed by chat name, so an unnamed one is
        unaddressable."""
        with self.assertRaises(ex.ExchangeError):
            ex.append(self.log, " ", "body", now=NOW)
        self.assertEqual(self.log.read_text(encoding="utf-8"), HEADER)

    def test_missing_log_is_refused_not_created(self) -> None:
        """Intent: prescriptions - a failed lookup is a failure. A mistyped path must not start
        a second exchange nobody reads."""
        missing = self.dir / "exchange-typo.md"
        with self.assertRaises(ex.ExchangeError):
            ex.append(missing, "chat", "body", now=NOW)
        self.assertFalse(missing.exists())

    def test_new_creates_a_log_that_does_not_exist(self) -> None:
        """Intent: starting an exchange goes through the tool too."""
        fresh = self.dir / "exchange-new.md"
        ex.append(fresh, "chat", "first", now=NOW, new=True)
        self.assertIn("- **2026-11-07 16:50, chat.** first\n", fresh.read_text(encoding="utf-8"))

    def test_new_refuses_an_existing_log(self) -> None:
        """Intent: --new never touches a live exchange."""
        with self.assertRaises(ex.ExchangeError):
            ex.append(self.log, "chat", "first", now=NOW, new=True)
        self.assertEqual(self.log.read_text(encoding="utf-8"), HEADER)


class Lock(Case):
    def test_a_held_lock_is_refused_naming_its_holder(self) -> None:
        """Intent: a stale lock is refused with its holder
        named, never broken."""
        lock = ex.lock_path(self.log)
        lock.write_text("chat: other chat\npid: 4242\ntaken: 2026-11-07 16:00\n",
                        encoding="utf-8")
        with self.assertRaises(ex.ExchangeError) as caught:
            ex.append(self.log, "chat", "body", now=NOW, wait=0.2)
        self.assertIn("other chat", str(caught.exception))
        self.assertIn("4242", str(caught.exception))
        self.assertTrue(lock.exists(), "the tool removed another chat's lock")
        self.assertEqual(self.log.read_text(encoding="utf-8"), HEADER)

    def test_lock_is_released_after_an_append(self) -> None:
        """Intent: take the lock, append, verify, release."""
        ex.append(self.log, "chat", "body", now=NOW)
        self.assertFalse(ex.lock_path(self.log).exists())

    def test_a_refusal_before_locking_leaves_no_lock(self) -> None:
        """Intent: a refused append must not leave its own lock behind to block
        every other chat. This one is refused before the lock is taken."""
        with self.assertRaises(ex.ExchangeError):
            ex.append(self.log, "chat", "  ", now=NOW)
        self.assertFalse(ex.lock_path(self.log).exists())

    def test_lock_is_released_when_the_read_back_fails(self) -> None:
        """Intent: a failure while the lock is held must still release it, or
        every other chat's append waits on a lock nobody owns."""
        real = ex.verify
        ex.verify = lambda old, new, entry: "forced read-back failure"
        try:
            with self.assertRaises(ex.ExchangeError) as caught:
                ex.append(self.log, "chat", "body", now=NOW)
        finally:
            ex.verify = real
        self.assertIn("forced read-back failure", str(caught.exception))
        self.assertFalse(ex.lock_path(self.log).exists())

    def test_a_waiting_append_lands_once_the_lock_is_released(self) -> None:
        """Intent: a chat that finds the lock held waits for it rather than
        failing at once."""
        lock = ex.lock_path(self.log)
        lock.write_text("chat: other chat\npid: 1\ntaken: now\n", encoding="utf-8")
        threading.Timer(0.3, lock.unlink).start()
        ex.append(self.log, "chat", "after the wait", now=NOW, wait=10)
        self.assertIn("after the wait", self.log.read_text(encoding="utf-8"))


class Verify(unittest.TestCase):
    def test_a_rewritten_prefix_is_caught(self) -> None:
        """Intent: the read-back checks that everything above the entry is
        unchanged, which catches a writer that ignored the lock."""
        self.assertIsNotNone(ex.verify("old\n", "changed\nentry\n", "entry\n"))

    def test_a_missing_entry_is_caught(self) -> None:
        """Intent: prescriptions - a write is done only when it reads back complete."""
        self.assertIsNotNone(ex.verify("old\n", "old\n", "entry\n"))

    def test_a_clean_append_passes(self) -> None:
        """Intent: the read-back passes the append it exists to confirm."""
        self.assertIsNone(ex.verify("old\n", "old\nentry\n", "entry\n"))


class Since(Case):
    def test_since_returns_entries_at_or_after_the_time(self) -> None:
        """Intent: "a check, at the start of a turn, for items addressed to this
        chat" needs the entries since the last look."""
        ex.append(self.log, "a", "early", now=datetime(2026, 11, 7, 14, 0))
        ex.append(self.log, "b", "late\n  - detail", now=datetime(2026, 11, 7, 16, 50))
        since = ex.since(self.log, datetime(2026, 11, 7, 15, 0))
        self.assertEqual(since, ["- **2026-11-07 16:50, b.** late\n  - detail\n"])

    def test_since_reads_entries_written_before_the_tool(self) -> None:
        """Intent: a log written by hand before the tool existed has entries headed
        "2026-11-07 16:50 by `Get-Date`, ..." and the check must see them."""
        self.log.write_text(HEADER + "- **2026-11-07 16:50 by `Get-Date`, chat.** old style\n",
                            encoding="utf-8")
        self.assertEqual(len(ex.since(self.log, datetime(2026, 11, 7, 16, 0))), 1)


OLD = "- **2026-11-08 09:00, old chat.** Already here for everyone.\n"
NEW = "- **2026-11-08 10:00, other chat.** **Factory chat:** the gate is green.\n"
TERMS = ["factory chat", "everyone"]


class Scan(unittest.TestCase):
    def test_a_new_matching_entry_gives_one_line(self) -> None:
        """Intent: a new entry containing a --for term prints exactly
        one [NEW] line, the entry's heading."""
        count, lines = ex.scan(HEADER + OLD + NEW, 1, TERMS, "me")
        self.assertEqual(count, 2)
        self.assertEqual(lines, ["[NEW] " + NEW.rstrip("\n")])

    def test_an_entry_from_before_the_start_is_skipped(self) -> None:
        """Intent: entries already in the log when the watcher starts are never
        reported."""
        count, lines = ex.scan(HEADER + OLD + NEW, 2, TERMS, "me")
        self.assertEqual((count, lines), (2, []))

    def test_an_entry_matching_no_term_is_skipped(self) -> None:
        """Intent: an entry matching no --for term prints nothing, but still
        counts as seen."""
        other = "- **2026-11-08 10:00, other chat.** **Docs chat:** unrelated.\n"
        count, lines = ex.scan(HEADER + other, 0, TERMS, "me")
        self.assertEqual((count, lines), (1, []))

    def test_own_entry_is_skipped(self) -> None:
        """Intent: an entry whose heading names --me as author doesn't wake the
        chat that wrote it, even when it names a term."""
        own = "- **2026-11-08 10:00, Factory Chat (example-repo).** Telling everyone it landed.\n"
        count, lines = ex.scan(HEADER + own, 0, TERMS, "factory chat")
        self.assertEqual((count, lines), (1, []))

    def test_a_term_in_the_body_is_not_the_author(self) -> None:
        """Intent: only the bold heading prefix is the author; --me named in
        the body of someone else's entry still wakes the chat."""
        addressed = "- **2026-11-08 10:00, other chat.** Asking me: are you done?\n"
        _, lines = ex.scan(HEADER + addressed, 0, ["asking me"], "me")
        self.assertEqual(len(lines), 1)

    def test_matching_ignores_case(self) -> None:
        """Intent: --for terms match case-insensitively."""
        _, lines = ex.scan(HEADER + NEW, 0, ["FACTORY CHAT"], "me")
        self.assertEqual(len(lines), 1)

    def test_a_continuation_line_can_carry_the_match(self) -> None:
        """Intent: matching runs over the whole entry, not only its heading,
        and the line printed is still the heading."""
        entry = ("- **2026-11-08 10:00, other chat.** Heading.\n"
                 "  - **Factory chat:** please look.\n")
        _, lines = ex.scan(HEADER + entry, 0, TERMS, "me")
        self.assertEqual(lines, ["[NEW] - **2026-11-08 10:00, other chat.** Heading."])

    def test_a_crlf_log_prints_no_stray_return(self) -> None:
        """Intent: an exchange log can be CRLF; a [NEW] line must not end in
        a carriage return."""
        _, lines = ex.scan((HEADER + NEW).replace("\n", "\r\n"), 0, TERMS, "me")
        self.assertEqual(lines, ["[NEW] " + NEW.rstrip("\n")])


class Clock:
    """A clock the fake sleep advances, so a watch run takes no real time."""

    def __init__(self) -> None:
        self.t = 0.0

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def __call__(self) -> float:
        return self.t


class Watch(Case):
    def run_watch(self, *, limit: int, sleep: Callable[[float], None] | None = None,
                  log: Path | None = None, **kwargs: float) -> list[str]:
        clock = Clock()
        out: list[str] = []
        ex.watch(log or self.log, TERMS, "me", sleep=sleep or clock.sleep, clock=clock,
                 now=lambda: datetime(2026, 11, 8, 10, 5), out=out.append, limit=limit, **kwargs)
        return out

    def test_a_new_entry_is_reported_once(self) -> None:
        """Intent: a new entry containing a --for term prints exactly
        one [NEW] line, however many times the log is reread."""
        clock = Clock()

        def sleep(seconds: float) -> None:
            clock.sleep(seconds)
            if self.log.read_text(encoding="utf-8").count("the gate") == 0:
                self.log.write_text(self.log.read_text(encoding="utf-8") + NEW, encoding="utf-8")

        out: list[str] = []
        ex.watch(self.log, TERMS, "me", sleep=sleep, clock=clock, out=out.append, limit=3,
                 alive=10_000)
        self.assertEqual(out, ["[NEW] " + NEW.rstrip("\n")])

    def test_entries_present_at_start_are_not_reported(self) -> None:
        """Intent: nothing already in the log is reported."""
        self.log.write_text(HEADER + OLD + NEW, encoding="utf-8")
        self.assertEqual(self.run_watch(limit=2, alive=10_000), [])

    def test_a_missing_log_reports_a_gap(self) -> None:
        """Intent: a missing log prints [GAP], not silence."""
        out = self.run_watch(limit=1, log=self.dir / "exchange-gone.md", alive=10_000)
        self.assertTrue(out and all(line.startswith("[GAP] ") for line in out), out)

    def test_a_log_missing_at_start_does_not_report_its_old_entries(self) -> None:
        """Intent: with the start count unknown, the first good read is the
        baseline, or every old entry would read as new."""
        late = self.dir / "exchange-late.md"
        clock = Clock()

        def sleep(seconds: float) -> None:
            clock.sleep(seconds)
            if not late.exists():
                late.write_text(HEADER + OLD + NEW, encoding="utf-8")

        out: list[str] = []
        ex.watch(late, TERMS, "me", sleep=sleep, clock=clock, out=out.append, limit=2,
                 alive=10_000)
        self.assertTrue(out[0].startswith("[GAP] "), out)
        self.assertEqual([line for line in out if line.startswith("[NEW]")], [])

    def test_the_heartbeat_prints_at_its_interval(self) -> None:
        """Intent: the heartbeat prints at its interval, so a dead
        watcher can be told from a quiet log."""
        out = self.run_watch(limit=8, interval=30, alive=100)
        self.assertEqual(out, ["[ALIVE] 10:05 0 entries"] * 2)

    def test_ctrl_c_exits_cleanly(self) -> None:
        """Intent: stopping the watcher is not an error."""
        def interrupt(seconds: float) -> None:
            raise KeyboardInterrupt

        clock = Clock()
        self.assertEqual(ex.watch(self.log, TERMS, "me", sleep=interrupt, clock=clock,
                                  out=lambda line: None), 0)


class WholeEntries(Case):
    def test_since_keeps_an_unindented_body(self) -> None:
        """Intent: since prints each entry whole, from its heading to the next entry's
        heading, however the body is laid out. A body drafted in a file is not indented."""
        ex.append(self.log, "a", "Heading.\n\nParagraph one.\n- bullet",
                  now=datetime(2026, 11, 7, 16, 50))
        ex.append(self.log, "b", "next", now=datetime(2026, 11, 7, 17, 0))
        self.assertEqual(ex.since(self.log, datetime(2026, 11, 7, 16, 0)), [
            "- **2026-11-07 16:50, a.** Heading.\n\nParagraph one.\n- bullet\n",
            "- **2026-11-07 17:00, b.** next\n"])

    def test_since_does_not_leak_an_older_entrys_body(self) -> None:
        """Intent: an entry before the time is skipped with its whole body, so the body
        of an old entry never prints under a newer one."""
        ex.append(self.log, "a", "old\n\nold body", now=datetime(2026, 11, 7, 14, 0))
        ex.append(self.log, "b", "new", now=datetime(2026, 11, 7, 17, 0))
        self.assertEqual(ex.since(self.log, datetime(2026, 11, 7, 16, 0)),
                         ["- **2026-11-07 17:00, b.** new\n"])

    def test_a_term_in_an_unindented_body_line_matches(self) -> None:
        """Intent: matching runs over the whole entry, so a name that appears in an
        unindented body line still wakes the chat."""
        entry = "- **2026-11-08 10:00, other chat.** Heading.\n\nFactory chat: please look.\n"
        _, lines = ex.scan(HEADER + entry, 0, TERMS, "me")
        self.assertEqual(lines, ["[NEW] - **2026-11-08 10:00, other chat.** Heading."])


BEAT = datetime(2026, 11, 9, 9, 0)
INTERVAL = 600.0


def beat(log: Path, me: str = "factory chat", at: datetime = BEAT,
         terms: list[str] | None = None) -> None:
    ex.write_heartbeat(log, me, terms or TERMS, INTERVAL, at)


class Heartbeat(Case):
    def test_the_file_name_is_safe_for_any_chat_name(self) -> None:
        """Intent: one heartbeat file per watcher, keyed by the chat name, beside the log,
        whatever characters the name holds."""
        path = ex.heartbeat_path(self.log, "Factory Chat (example-repo) / one")
        self.assertEqual(path.parent, self.log.parent)
        self.assertRegex(path.name, r"^[a-z0-9._-]+$")

    def test_different_chats_have_different_files(self) -> None:
        """Intent: two watchers on one log do not overwrite each other's heartbeat."""
        self.assertNotEqual(ex.heartbeat_path(self.log, "factory chat"),
                            ex.heartbeat_path(self.log, "opus chat"))

    def test_the_heartbeat_records_time_interval_and_terms(self) -> None:
        """Intent: the file carries the ISO timestamp, the interval, and the terms the
        watcher was started with."""
        beat(self.log)
        data = json.loads(ex.heartbeat_path(self.log, "factory chat").read_text(encoding="utf-8"))
        self.assertEqual(data, {"me": "factory chat", "beat": "2026-11-09T09:00:00",
                                "interval": INTERVAL, "terms": TERMS})

    def test_writing_leaves_no_temporary_file(self) -> None:
        """Intent: the file is replaced atomically, so no half-written copy is left
        beside the log for a reader to find."""
        beat(self.log)
        beat(self.log, at=datetime(2026, 11, 9, 9, 10))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         sorted([self.log.name, ex.heartbeat_path(self.log, "factory chat").name]))

    def test_a_live_watcher_is_live(self) -> None:
        """Intent: a heartbeat younger than two intervals is live."""
        beat(self.log)
        found = ex.watcher_state(self.log, "factory chat", BEAT + timedelta(seconds=1199))
        self.assertEqual((found.state, found.beat), ("live", BEAT))

    def test_stale_at_exactly_two_missed_intervals(self) -> None:
        """Intent: two missed heartbeats is stale, and the boundary is exact."""
        beat(self.log)
        found = ex.watcher_state(self.log, "factory chat", BEAT + timedelta(seconds=1200))
        self.assertEqual((found.state, found.beat), ("stale", BEAT))

    def test_no_file_is_none_never_live(self) -> None:
        """Intent: a watcher that never started, or has stopped, reads as none."""
        self.assertEqual(ex.watcher_state(self.log, "factory chat", BEAT).state, "none")

    def test_an_unparsable_file_is_unknown(self) -> None:
        """Intent: unknown is not zero - a heartbeat that cannot be read is neither live
        nor none."""
        ex.heartbeat_path(self.log, "factory chat").write_text("not json", encoding="utf-8")
        self.assertEqual(ex.watcher_state(self.log, "factory chat", BEAT).state, "unknown")

    def test_a_file_missing_a_field_is_unknown(self) -> None:
        """Intent: a readable file that lacks a field is unknown, not live."""
        ex.heartbeat_path(self.log, "factory chat").write_text('{"me": "factory chat"}',
                                                               encoding="utf-8")
        self.assertEqual(ex.watcher_state(self.log, "factory chat", BEAT).state, "unknown")

    def test_a_zero_interval_is_unknown(self) -> None:
        """Intent: an interval of zero would make every beat stale or never stale, so it
        is refused as unreadable."""
        ex.heartbeat_path(self.log, "factory chat").write_text(
            '{"me": "factory chat", "beat": "2026-11-09T09:00:00", "interval": 0, "terms": []}',
            encoding="utf-8")
        self.assertEqual(ex.watcher_state(self.log, "factory chat", BEAT).state, "unknown")

    def test_watch_writes_a_heartbeat_at_start_and_each_tick(self) -> None:
        """Intent: the watcher is live from the moment it starts, and rewrites its file
        on each heartbeat."""
        clock = Clock()
        stamps = iter([datetime(2026, 11, 9, 9, 0), datetime(2026, 11, 9, 9, 5),
                       datetime(2026, 11, 9, 9, 10), datetime(2026, 11, 9, 9, 15)])
        ex.watch(self.log, TERMS, "me", sleep=clock.sleep, clock=clock, out=lambda line: None,
                 now=lambda: next(stamps), limit=0, alive=100)
        self.assertEqual(ex.watcher_state(self.log, "me", datetime(2026, 11, 9, 9, 0)).state,
                         "live")
        clock = Clock()
        ex.watch(self.log, TERMS, "me", sleep=clock.sleep, clock=clock, out=lambda line: None,
                 now=lambda: datetime(2026, 11, 9, 9, 30), limit=4, interval=30, alive=100)
        found = ex.watcher_state(self.log, "me", datetime(2026, 11, 9, 9, 30))
        self.assertEqual((found.state, found.beat), ("live", datetime(2026, 11, 9, 9, 30)))

    def test_an_interrupted_watch_leaves_its_heartbeat(self) -> None:
        """Intent: a stopped watcher still means nobody is listening, so its heartbeat is
        left to go stale rather than deleted - an interrupt must not hide a watcher that
        died the same way."""
        def interrupt(seconds: float) -> None:
            raise KeyboardInterrupt

        ex.watch(self.log, TERMS, "me", sleep=interrupt, clock=Clock(), out=lambda line: None,
                 now=lambda: BEAT)
        self.assertEqual(ex.watcher_state(self.log, "me", BEAT).state, "live")
        self.assertEqual(ex.watcher_state(self.log, "me", STALE_AT).state, "stale")


STALE_AT = BEAT + timedelta(seconds=1200)
ENTRY = "- **2026-11-09 09:20, other chat.** **Factory chat:** please look.\n"


class Warnings(Case):
    def test_a_stale_addressee_warns_naming_the_chat_and_its_last_beat(self) -> None:
        """Intent: the writer is told the chat an entry names has a watcher that has
        missed two heartbeats, with the chat and its last heartbeat time."""
        beat(self.log)
        found = ex.warnings_for(self.log, "other chat", ENTRY, STALE_AT)
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("[WARN]"))
        self.assertIn("factory chat", found[0])
        self.assertIn("09:00", found[0])

    def test_a_live_addressee_does_not_warn(self) -> None:
        """Intent: a watcher that is beating needs no warning."""
        beat(self.log)
        self.assertEqual(ex.warnings_for(self.log, "other chat", ENTRY,
                                         BEAT + timedelta(seconds=60)), [])

    def test_an_entry_naming_no_watcher_does_not_warn(self) -> None:
        """Intent: only the chat an entry is addressed to is warned about; the match is
        the one watch uses."""
        beat(self.log)
        other = "- **2026-11-09 09:20, other chat.** **Docs chat:** unrelated.\n"
        self.assertEqual(ex.warnings_for(self.log, "other chat", other, STALE_AT), [])

    def test_the_writers_own_stale_watcher_does_not_warn(self) -> None:
        """Intent: a chat is not warned about its own watcher by its own entry."""
        beat(self.log)
        own = "- **2026-11-09 09:20, Factory Chat (example-repo).** Telling everyone it landed.\n"
        self.assertEqual(ex.warnings_for(self.log, "Factory Chat (example-repo)", own, STALE_AT), [])

    def test_no_heartbeat_files_gives_no_warning(self) -> None:
        """Intent: with no watcher known there is no addressee to warn about."""
        self.assertEqual(ex.warnings_for(self.log, "other chat", ENTRY, STALE_AT), [])

    def test_an_unreadable_heartbeat_warns(self) -> None:
        """Intent: a heartbeat that cannot be read never passes silently, even though the
        chat it belongs to cannot be named."""
        bad = self.log.with_name(self.log.name + ".heartbeat.broken")
        bad.write_text("not json", encoding="utf-8")
        found = ex.warnings_for(self.log, "other chat", ENTRY, STALE_AT)
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("[WARN]"))
        self.assertIn("heartbeat.broken", found[0])

    def test_several_stale_addressees_each_warn(self) -> None:
        """Intent: each stale watcher an entry names gets its own warning."""
        beat(self.log, "factory chat", terms=["factory chat"])
        beat(self.log, "docs chat", terms=["factory chat"])
        self.assertEqual(len(ex.warnings_for(self.log, "other chat", ENTRY, STALE_AT)), 2)


class Describe(unittest.TestCase):
    def test_each_state_reads_distinctly(self) -> None:
        """Intent: live, stale with its last heartbeat time, none, and unknown must not
        read alike."""
        live = ex.describe(ex.Watcher("live", BEAT, INTERVAL))
        stale = ex.describe(ex.Watcher("stale", BEAT, INTERVAL))
        none = ex.describe(ex.Watcher("none", None, None))
        unknown = ex.describe(ex.Watcher("unknown", None, None))
        self.assertEqual(len({live, stale, none, unknown}), 4)
        self.assertIn("live", live)
        self.assertIn("stale", stale)
        self.assertIn("09:00", stale)
        self.assertIn("none", none)
        self.assertIn("unknown", unknown)


NOON = datetime(2026, 11, 9, 12, 0)


class When(unittest.TestCase):
    def test_a_bare_time_earlier_today_is_today(self) -> None:
        """Intent: a bare HH:MM that has already passed means that time today."""
        self.assertEqual(ex._when("08:30", now=NOON), datetime(2026, 11, 9, 8, 30))

    def test_a_bare_time_equal_to_now_is_accepted(self) -> None:
        """Intent: only a time later than now is refused; now itself is a valid look."""
        self.assertEqual(ex._when("12:00", now=NOON), NOON)

    def test_a_bare_time_later_than_now_is_refused(self) -> None:
        """Intent: a bare time later than now cannot hold an entry from today, so it is
        refused rather than answered with a silent zero, and the error names the form to use."""
        with self.assertRaises(ex.ExchangeError) as caught:
            ex._when("15:00", now=NOON)
        self.assertIn("YYYY-MM-DD HH:MM", str(caught.exception))

    def test_a_full_date_is_accepted_at_any_hour(self) -> None:
        """Intent: the full form always works, including a time later than now's hour."""
        self.assertEqual(ex._when("2026-11-08 15:00", now=NOON), datetime(2026, 11, 8, 15, 0))

    def test_garbage_is_still_refused(self) -> None:
        """Intent: text that is neither form is refused."""
        with self.assertRaises(ex.ExchangeError):
            ex._when("tomorrow", now=NOON)


class WatcherCommandLine(Case):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(EXCHANGE / "exchange.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def test_append_warns_but_still_writes(self) -> None:
        """Intent: a warning never blocks the append; the entry is written and the
        command still succeeds."""
        beat(self.log, at=datetime(2026, 1, 1, 9, 0))
        proc = self.run_cli("append", str(self.log), "--chat", "other chat", "--body",
                            "**Factory chat:** please look.")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[OK]", proc.stdout)
        self.assertIn("[WARN]", proc.stdout)
        self.assertIn("please look", self.log.read_text(encoding="utf-8"))

    def test_since_reports_the_readers_own_watcher(self) -> None:
        """Intent: the start-of-turn check says whether the reading chat's own watcher is
        live, stale, or none."""
        none = self.run_cli("since", str(self.log), "2000-01-01 00:00", "--me", "factory chat")
        self.assertIn("[WATCHER]", none.stdout)
        self.assertIn("none", none.stdout)
        beat(self.log, at=datetime(2026, 1, 1, 9, 0))
        stale = self.run_cli("since", str(self.log), "2000-01-01 00:00", "--me", "factory chat")
        self.assertIn("stale", stale.stdout)
        self.assertIn("09:00", stale.stdout)

    def test_since_without_a_chat_says_the_watcher_was_not_checked(self) -> None:
        """Intent: silence is ambiguous - a check that could not run says so rather than
        reporting no watcher."""
        proc = self.run_cli("since", str(self.log), "2000-01-01 00:00")
        self.assertIn("[WATCHER] not checked", proc.stdout)


class CommandLine(Case):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(EXCHANGE / "exchange.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def test_append_reports_ok(self) -> None:
        """Intent: prescriptions - every write reads back as [OK] or [GAP]."""
        proc = self.run_cli("append", str(self.log), "--chat", "chat", "--body", "hello")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[OK]", proc.stdout)

    def test_body_file_is_read(self) -> None:
        """Intent: multi-line entries come from a drafted file, as ticket bodies
        do."""
        body = self.dir / "entry.md"
        body.write_text("From a file.\n  - with detail\n", encoding="utf-8")
        proc = self.run_cli("append", str(self.log), "--chat", "chat", "--body-file", str(body))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("From a file.\n  - with detail\n", self.log.read_text(encoding="utf-8"))

    def test_refusal_reports_gap_and_fails(self) -> None:
        """Intent: prescriptions - a refusal is a failure, never a quiet success."""
        proc = self.run_cli("append", str(self.dir / "missing.md"), "--chat", "c", "--body", "b")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("[GAP]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
