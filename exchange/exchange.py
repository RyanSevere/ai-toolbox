#!/usr/bin/env python3
################################################################################
# File: exchange.py
# Path: {PROJECT_ROOT}/.github/scripts/exchange/exchange.py
# Created by: Cursor agent, for Ryan Severe
# Created: 2026-11-07
# Last Updated: 2026-11-13
# Description: Appends an entry to a cross-chat exchange log under a lock, so
#              no concurrent entry is lost, and lists the entries since a
#              time for the start-of-turn check. Watches a log and prints a
#              line when a new entry names a chat.
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

"""exchange - append to a cross-chat exchange log without losing anyone's entry.

    python .github/scripts/exchange/exchange.py append scratch/exchange-<name>.md \\
        --chat "release-prep chat (my-repo)" --body-file scratch/entry.md
    python .github/scripts/exchange/exchange.py since scratch/exchange-<name>.md \\
        "2026-11-09 16:11" --me "<chat name>"
    python .github/scripts/exchange/exchange.py watch scratch/exchange-<name>.md \\
        --for "<chat name>" --for everyone --me "<chat name>"

An append takes `<log>.lock` by exclusive create, appends, reads the log back, and
releases. A lock held past the wait is refused with its holder named, never broken:
an append takes milliseconds, so a lock that outlives the wait means a chat died
holding it, and removing it is a person's call.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple

POLL_SECONDS = 0.05
HEARTBEAT_MISSES = 2
HEADING = re.compile(r"^- \*\*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
AUTHOR = re.compile(r"^- \*\*(.*?)\*\*")


class ExchangeError(Exception):
    """An append or read that was refused. The log is unchanged."""


def lock_path(log: Path) -> Path:
    return log.with_name(log.name + ".lock")


def _holder(lock: Path) -> str:
    try:
        return lock.read_text(encoding="utf-8").strip().replace("\n", ", ") or "unnamed holder"
    except OSError:
        return "holder unreadable"


def _take(lock: Path, chat: str, wait: float) -> None:
    deadline = time.monotonic() + wait
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ExchangeError(f"{lock} is held ({_holder(lock)}) after {wait:g}s. Not "
                                    "breaking it: if its chat is gone, remove it by hand") from None
            time.sleep(POLL_SECONDS)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(f"chat: {chat}\npid: {os.getpid()}\n"
                      f"taken: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        return


def _read(log: Path) -> str:
    with open(log, encoding="utf-8", newline="") as src:
        return src.read()


def format_entry(chat: str, body: str, now: datetime) -> str:
    return f"- **{now.strftime('%Y-%m-%d %H:%M')}, {chat}.** {body}\n"


def verify(old: str, new: str, entry: str) -> str | None:
    """Why the read-back fails, or None when the log is exactly the old one plus the entry."""
    if not new.startswith(old):
        return "the log above the entry changed - a writer bypassed the lock"
    if new[len(old):] != entry:
        return "the entry did not read back as written"
    return None


def append(log: Path, chat: str, body: str, *, now: datetime | None = None,
           wait: float = 30.0, new: bool = False) -> str:
    """Append one entry and return it as written. Raises ExchangeError, log unchanged."""
    chat, body = chat.strip(), body.strip()
    if not chat:
        raise ExchangeError("no chat name - an entry nobody can address is not recorded")
    if not body:
        raise ExchangeError("empty entry")
    if new and log.exists():
        raise ExchangeError(f"{log} already exists - --new only starts an exchange")
    if not new and not log.is_file():
        raise ExchangeError(f"{log} not found - check the path, or start it with --new")
    lock = lock_path(log)
    _take(lock, chat, wait)
    try:
        old = _read(log) if log.exists() else ""
        # A log edited on Windows is CRLF; an LF entry in it leaves mixed line endings.
        newline = "\r\n" if "\r\n" in old else "\n"
        entry = format_entry(chat, body, now or datetime.now())
        if old and not old.endswith("\n"):
            entry = "\n" + entry
        entry = entry.replace("\r\n", "\n").replace("\n", newline)
        with open(log, "a", encoding="utf-8", newline="") as out:
            out.write(entry)
        failure = verify(old, _read(log), entry)
        if failure:
            raise ExchangeError(f"{log}: {failure}")
        return entry
    finally:
        lock.unlink()


def _split(text: str, keepends: bool) -> list[list[str]]:
    """Each entry as its lines: from its heading up to the next entry's heading, however its
    body is laid out. Lines before the first heading belong to no entry."""
    entries: list[list[str]] = []
    for line in text.splitlines(keepends=keepends):
        if HEADING.match(line):
            entries.append([line])
        elif entries:
            entries[-1].append(line)
    return entries


def since(log: Path, when: datetime) -> list[str]:
    """Entries headed at or after `when`, each whole: heading, body and all."""
    if not log.is_file():
        raise ExchangeError(f"{log} not found")
    kept: list[str] = []
    for lines in _split(log.read_text(encoding="utf-8"), keepends=True):
        stamp = HEADING.match(lines[0]).group(1)  # type: ignore[union-attr]
        if datetime.strptime(stamp, "%Y-%m-%d %H:%M") >= when:
            kept.append("".join(lines))
    return kept


def _entries(text: str) -> list[list[str]]:
    """Each entry as its heading line and the lines under it, line endings stripped."""
    return _split(text, keepends=False)


def heartbeat_path(log: Path, me: str) -> Path:
    """The watcher's heartbeat file: one per chat, beside the log."""
    slug = re.sub(r"[^a-z0-9]+", "-", me.lower()).strip("-") or "chat"
    return log.with_name(f"{log.name}.heartbeat.{slug}")


def write_heartbeat(log: Path, me: str, terms: list[str], interval: float,
                    now: datetime) -> None:
    """Record that `me` is watching: when, how often it beats, and the terms it answers to.
    Written to a temporary file and moved into place, so a reader never sees half of it."""
    path = heartbeat_path(log, me)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {"me": me, "beat": now.isoformat(timespec="seconds"), "interval": interval,
               "terms": list(terms)}
    try:
        temp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Watcher(NamedTuple):
    """One chat's watcher: live, stale, none (no heartbeat file) or unknown (unreadable)."""

    state: str
    beat: datetime | None
    interval: float | None
    me: str = ""
    terms: tuple[str, ...] = ()


def _load_heartbeat(path: Path) -> Watcher:
    """The heartbeat file's content as a Watcher with state 'recorded'. Raises ValueError for
    anything unreadable or malformed, so a damaged file is never mistaken for a live one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        me, interval = data["me"], data["interval"]
        terms = data["terms"]
        beat = datetime.fromisoformat(data["beat"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"{path.name} is unreadable: {exc}") from exc
    if (not isinstance(me, str) or isinstance(interval, bool)
            or not isinstance(interval, (int, float)) or interval <= 0
            or not isinstance(terms, list) or not all(isinstance(t, str) for t in terms)):
        raise ValueError(f"{path.name} holds a field of the wrong kind")
    return Watcher("recorded", beat, float(interval), me, tuple(terms))


def _classify(found: Watcher, now: datetime) -> Watcher:
    """Live until two heartbeat intervals have passed since the last beat, stale from then."""
    assert found.beat is not None and found.interval is not None
    age = (now - found.beat).total_seconds()
    state = "stale" if age >= HEARTBEAT_MISSES * found.interval else "live"
    return found._replace(state=state)


def watcher_state(log: Path, me: str, now: datetime) -> Watcher:
    """The state of `me`'s watcher on `log`. No file is 'none', never 'live'; a file that
    cannot be read, or belongs to a differently spelt chat, is 'unknown'."""
    path = heartbeat_path(log, me)
    if not path.exists():
        return Watcher("none", None, None)
    try:
        found = _load_heartbeat(path)
    except ValueError:
        return Watcher("unknown", None, None)
    if found.me.lower() != me.lower():
        return Watcher("unknown", None, None)
    return _classify(found, now)


def describe(watcher: Watcher) -> str:
    """A watcher's state as one line, so the four states never read alike."""
    if watcher.state in ("live", "stale") and watcher.beat is not None:
        when = watcher.beat.strftime("%Y-%m-%d %H:%M")
        if watcher.state == "live":
            return f"live (last heartbeat {when})"
        return f"stale (last heartbeat {when}; {HEARTBEAT_MISSES} heartbeats missed)"
    if watcher.state == "none":
        return "none (no watcher is running for this chat)"
    return "unknown (the heartbeat file could not be read)"


def warnings_for(log: Path, chat: str, entry: str, now: datetime) -> list[str]:
    """A `[WARN]` line for each watcher the entry names that has gone stale, or whose heartbeat
    file cannot be read. The writer's own watcher is skipped. Never raises for a bad file."""
    lowered = entry.lower()
    found: list[str] = []
    pattern = glob.escape(log.name) + ".heartbeat.*"
    for path in sorted(log.parent.glob(pattern)):
        try:
            recorded = _load_heartbeat(path)
        except ValueError as exc:
            found.append(f"[WARN] {exc}; whether the chat it belongs to is listening is unknown")
            continue
        if recorded.me.lower() in chat.lower():
            continue
        if not any(term.lower() in lowered for term in recorded.terms):
            continue
        watcher = _classify(recorded, now)
        if watcher.state == "stale" and watcher.beat is not None:
            found.append(f"[WARN] {recorded.me}'s watcher last beat "
                         f"{watcher.beat.strftime('%Y-%m-%d %H:%M')} and has missed "
                         f"{HEARTBEAT_MISSES} heartbeats; this entry may not wake it")
    return found


def scan(text: str, seen: int, terms: list[str], me: str) -> tuple[int, list[str]]:
    """The entry count now, and a `[NEW]` line for each entry past the first `seen` naming a term."""
    entries = _entries(text)
    wanted = [term.lower() for term in terms]
    lines: list[str] = []
    for entry in entries[seen:]:
        author = AUTHOR.match(entry[0])
        if author and me.lower() in author.group(1).lower():
            continue
        body = "\n".join(entry).lower()
        if any(term in body for term in wanted):
            lines.append(f"[NEW] {entry[0]}")
    return len(entries), lines


def watch(log: Path, terms: list[str], me: str, *, interval: float = 30.0, alive: float = 600.0,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
          now: Callable[[], datetime] = datetime.now, out: Callable[[str], None] = print,
          limit: int | None = None) -> int:
    """Print `[NEW]` for entries that name a term, `[ALIVE]` as a heartbeat, `[GAP]` when unread.

    `seen` is None until the log has been read once: the first good read is the baseline, so
    a log that was missing at the start never reports its old entries as new.
    """
    def say(line: str) -> None:
        out(line)
        sys.stdout.flush()

    def read() -> str | None:
        try:
            return _read(log)
        except (OSError, UnicodeDecodeError) as exc:
            say(f"[GAP] {log} unreadable: {exc}")
            return None

    def pulse() -> None:
        try:
            write_heartbeat(log, me, terms, alive, now())
        except OSError as exc:
            say(f"[GAP] heartbeat not written: {exc}")

    pulse()
    text = read()
    seen = len(_entries(text)) if text is not None else None
    beat = clock()
    iterations = 0
    try:
        while limit is None or iterations < limit:
            sleep(interval)
            iterations += 1
            text = read()
            if text is not None:
                if seen is None:
                    seen = len(_entries(text))
                else:
                    seen, lines = scan(text, seen, terms, me)
                    for line in lines:
                        say(line)
            if clock() - beat >= alive:
                beat = clock()
                pulse()
                say(f"[ALIVE] {now().strftime('%H:%M')} "
                    f"{'unknown' if seen is None else seen} entries")
    except KeyboardInterrupt:
        # The heartbeat is left to go stale: a stopped watcher still means nobody is listening.
        pass
    return 0


def _when(text: str, now: datetime | None = None) -> datetime:
    """A time as `since` takes it. A bare HH:MM means that time today, and one later than now
    is refused: nothing from today can be that late, so an answer of zero entries would be
    silence that reads as a quiet log."""
    now = now or datetime.now()
    for fmt in ("%Y-%m-%d %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            parsed = datetime.combine(now.date(), parsed.time())
            if parsed > now:
                raise ExchangeError(f"{text!r} is later than now, so it can hold nothing from "
                                    "today. Pass the full date: YYYY-MM-DD HH:MM")
        return parsed
    raise ExchangeError(f"{text!r} is not HH:MM or YYYY-MM-DD HH:MM")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exchange.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("append", help="append one entry under the lock")
    add.add_argument("log", type=Path)
    add.add_argument("--chat", required=True, help="who is writing, not who it is for; name the recipient in the body")
    body = add.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file", type=Path)
    add.add_argument("--new", action="store_true", help="start a log that does not exist yet")
    add.add_argument("--wait", type=float, default=30.0, help="seconds to wait for the lock")
    read = commands.add_parser("since", help="entries at or after a time")
    read.add_argument("log", type=Path)
    read.add_argument("when", help="HH:MM today, or YYYY-MM-DD HH:MM")
    read.add_argument("--me", help="this chat; reports the state of its own watcher")
    follow = commands.add_parser("watch", help="print a line when a new entry names a term")
    follow.add_argument("log", type=Path)
    follow.add_argument("--for", dest="terms", action="append", required=True,
                        help="a term that wakes this chat; repeatable")
    follow.add_argument("--me", required=True, help="this chat; its own entries are skipped")
    follow.add_argument("--interval", type=float, default=30.0, help="seconds between rereads")
    follow.add_argument("--alive", type=float, default=600.0, help="seconds between heartbeats")
    args = parser.parse_args(argv)
    if args.command == "watch":
        return watch(args.log, args.terms, args.me, interval=args.interval, alive=args.alive)
    try:
        if args.command == "append":
            text = (args.body if args.body is not None
                    else args.body_file.read_text(encoding="utf-8-sig"))
            entry = append(args.log, args.chat, text, wait=args.wait, new=args.new)
            print(f"[OK] appended to {args.log}: {entry.strip().splitlines()[0]}")
            try:
                for warning in warnings_for(args.log, args.chat, entry, datetime.now()):
                    print(warning)
            except OSError as exc:
                print(f"[WARN] could not check the watchers: {exc}")
        else:
            entries = since(args.log, _when(args.when))
            print("".join(entries), end="")
            print(f"[OK] {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} since "
                  f"{args.when} in {args.log}")
            if args.me:
                print(f"[WATCHER] {describe(watcher_state(args.log, args.me, datetime.now()))}")
            else:
                print("[WATCHER] not checked: pass --me <chat> to check this chat's own watcher")
    except (ExchangeError, OSError) as exc:
        print(f"[GAP] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
