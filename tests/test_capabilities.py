#!/usr/bin/env python3
################################################################################
# File: test_capabilities.py
# Path: {PROJECT_ROOT}/tests/test_capabilities.py
# Created by: Ryan Severe
# Created: 2026-10-13
# Last Updated: 2026-11-23
# Description: Tests for capabilities/tracker.yaml, the core's wireframe of ticket
#              management, and capabilities/asks.yaml, its wireframe of asking the
#              operator away from the session, and capabilities/sessions.yaml, its
#              wireframe of listing the managed sessions. Each holds concepts, operations, guarantees and setup
#              questions, and names no tracker, transport or estate value. A
#              wireframe that quietly names a product has to be edited to support
#              the next one. Stdlib and PyYAML only.
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

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "capabilities" / "tracker.yaml"
# Data coverage cannot see.
EXERCISES = ["capabilities/**"]

SECTIONS = ("concepts", "operations", "guarantees", "setup")
CONCEPTS = ("issue", "identifier", "summary", "description", "owner", "priority", "status",
            "resolution", "relation", "comment", "category")
OPERATIONS = ("create", "edit", "query", "comment", "close", "link", "status", "priority")
GUARANTEES = ("read-back", "refuse-incomplete", "unknown-not-empty")
QUESTIONS = ("system", "connection", "fields", "body", "summary", "status", "priority",
             "references", "owner", "relations", "operations")
QUESTION_KEYS = ("id", "ask", "why", "feeds", "example")
# Conventions an agent reads, rather than answers that only drive bindings.
RENDERS = ("fields", "body", "summary", "status", "priority", "references", "owner")

# Anything specific to one tracker, one transport, or this estate. Whole words, so
# "onboard" is not "board". "REST" is matched in capitals only, which is the protocol and
# not the English word.
FORBIDDEN = {
    "github": r"(?i)(?<![\w-])github(?![\w-])",
    "gh": r"(?i)(?<![\w-])gh(?![\w-])",
    "jira": r"(?i)(?<![\w-])jira(?![\w-])",
    "servicenow": r"(?i)(?<![\w-])servicenow(?![\w-])",
    "REST": r"(?<![\w-])REST(?![\w-])",
    "graphql": r"(?i)(?<![\w-])graphql(?![\w-])",
    "mcp": r"(?i)(?<![\w-])mcp(?![\w-])",
    "board": r"(?i)(?<![\w-])board(?![\w-])",
    "P0-P3": r"(?i)(?<![\w-])p[0-3](?![\w-])",
    "severity": r"(?i)(?<![\w-])severity(?![\w-])",
    "found note": r"(?i)(?<![\w-])found notes?(?![\w-])",
    "refined": r"(?i)(?<![\w-])refined(?![\w-])",
    "agent-ready": r"(?i)(?<![\w-])agent-ready(?![\w-])",
    "tickets.py": r"(?i)tickets\.py",
}


def load() -> dict:
    return yaml.safe_load(FILE.read_text(encoding="utf-8"))


class Wireframe(unittest.TestCase):
    """The core describes ticket management without describing a ticket system."""

    def test_the_file_exists(self):
        self.assertTrue(FILE.is_file(), f"{FILE} is missing")

    def test_the_four_sections_exist(self):
        data = load()
        for section in SECTIONS:
            with self.subTest(section=section):
                self.assertTrue(data.get(section), f"section {section!r} is missing or empty")

    def test_every_listed_concept_is_defined_with_a_description(self):
        concepts = load()["concepts"]
        self.assertEqual(set(concepts), set(CONCEPTS))
        for name, entry in concepts.items():
            with self.subTest(concept=name):
                self.assertTrue(str((entry or {}).get("description") or "").strip())

    def test_every_listed_operation_is_a_tracker_capability(self):
        """Intent: one tracker.* capability per operation, so a profile whose system
        lacks one loses only what needs it. A profile's binding maps these names."""
        operations = load()["operations"]
        self.assertEqual(set(operations), set(OPERATIONS))
        for name, entry in operations.items():
            with self.subTest(operation=name):
                self.assertEqual(entry.get("capability"), f"tracker.{name}")
                self.assertTrue(str(entry.get("description") or "").strip())

    def test_every_guarantee_an_operation_names_is_defined(self):
        data = load()
        self.assertEqual(set(data["guarantees"]), set(GUARANTEES))
        for name, entry in data["operations"].items():
            for guarantee in entry.get("guarantees") or []:
                with self.subTest(operation=name, guarantee=guarantee):
                    self.assertIn(guarantee, data["guarantees"])

    def test_every_guarantee_has_a_description(self):
        for name, entry in load()["guarantees"].items():
            with self.subTest(guarantee=name):
                self.assertTrue(str((entry or {}).get("description") or entry or "").strip())

    def test_the_create_and_query_guarantees_are_the_ones_the_design_names(self):
        """Intent: a write is done only when it reads back complete, an
        incomplete record is refused before it is written, and a failed lookup reports failure
        and never an empty result."""
        operations = load()["operations"]
        self.assertEqual(set(operations["create"]["guarantees"]), {"read-back", "refuse-incomplete"})
        self.assertIn("unknown-not-empty", operations["query"]["guarantees"])


class SetupQuestions(unittest.TestCase):
    """A Q&A section refines the wireframe to one profile's specifics. Setup asks these
    and stores the answers."""

    def test_every_listed_question_is_present_once(self):
        ids = [q.get("id") for q in load()["setup"]]
        self.assertEqual(sorted(ids), sorted(QUESTIONS))

    def test_every_question_carries_its_fields(self):
        for question in load()["setup"]:
            for key in QUESTION_KEYS:
                with self.subTest(question=question.get("id"), key=key):
                    self.assertTrue(question.get(key), f"{key!r} missing or empty")

    def test_every_question_feeds_a_concept_or_an_operation(self):
        data = load()
        known = set(data["concepts"]) | set(data["operations"])
        for question in data["setup"]:
            feeds = question["feeds"]
            for target in [feeds] if isinstance(feeds, str) else feeds:
                with self.subTest(question=question["id"], feeds=target):
                    self.assertIn(target, known)

    def test_renders_is_true_or_absent(self):
        """Intent: `renders` is allowed, and only true or absent."""
        for question in load()["setup"]:
            with self.subTest(question=question["id"]):
                self.assertIs(question.get("renders", True), True)

    def test_the_convention_questions_are_the_ones_that_render(self):
        """Intent: body, summary, status, fields,
        priority, references and owner render; system, connection, relations and operations
        stay binding-only."""
        flagged = [q["id"] for q in load()["setup"] if q.get("renders")]
        self.assertEqual(flagged, list(RENDERS))


class NamesNothingSpecific(unittest.TestCase):
    """No tracker, CLI, API or estate value appears in the file."""

    def test_the_word_list_is_not_vacuous(self):
        self.assertGreater(len(FORBIDDEN), 10)
        self.assertIsNotNone(re.search(FORBIDDEN["board"], "a board"))
        self.assertIsNone(re.search(FORBIDDEN["board"], "onboard"))
        self.assertIsNotNone(re.search(FORBIDDEN["REST"], "a REST call"))
        self.assertIsNone(re.search(FORBIDDEN["REST"], "the rest of it"))

    def test_the_file_names_no_tracker_transport_or_estate_value(self):
        text = FILE.read_text(encoding="utf-8")
        for word, pattern in FORBIDDEN.items():
            with self.subTest(word=word):
                self.assertIsNone(re.search(pattern, text), f"{word!r} appears in {FILE.name}")


ASKS_FILE = ROOT / "capabilities" / "asks.yaml"
ASKS_CONCEPTS = ("ask", "verdict", "open-ask")
ASKS_OPERATIONS = ("ask", "list")
ASKS_GUARANTEES = ("verdict-from-channel", "read-back", "unknown-not-empty")
ASKS_QUESTIONS = ("channel", "connection", "verdicts", "operations")
# Anything specific to one channel, one transport, or one profile's own tooling.
ASKS_FORBIDDEN = {
    "slack": r"(?i)(?<![\w-])slack(?![\w-])",
    "ntfy": r"(?i)(?<![\w-])ntfy(?![\w-])",
    "pushover": r"(?i)(?<![\w-])pushover(?![\w-])",
    "telegram": r"(?i)(?<![\w-])telegram(?![\w-])",
    "discord": r"(?i)(?<![\w-])discord(?![\w-])",
    "github": FORBIDDEN["github"],
    "gh": FORBIDDEN["gh"],
    "mcp": FORBIDDEN["mcp"],
    "opqueue": r"(?i)opqueue",
    "operator queue": r"(?i)operator[ -]queue",
}


def load_asks() -> dict:
    return yaml.safe_load(ASKS_FILE.read_text(encoding="utf-8"))


class AsksWireframe(unittest.TestCase):
    """The core describes asking the operator without describing a channel."""

    def test_the_file_exists(self):
        self.assertTrue(ASKS_FILE.is_file(), f"{ASKS_FILE} is missing")

    def test_the_four_sections_exist(self):
        data = load_asks()
        for section in SECTIONS:
            with self.subTest(section=section):
                self.assertTrue(data.get(section), f"section {section!r} is missing or empty")

    def test_every_listed_concept_is_defined_with_a_description(self):
        concepts = load_asks()["concepts"]
        self.assertEqual(set(concepts), set(ASKS_CONCEPTS))
        for name, entry in concepts.items():
            with self.subTest(concept=name):
                self.assertTrue(str((entry or {}).get("description") or "").strip())

    def test_the_two_operations_are_asks_capabilities(self):
        """Intent: asks.ask puts a question and returns the verdict, asks.list shows the
        open asks, and a profile whose channel lacks one loses only what needs it."""
        operations = load_asks()["operations"]
        self.assertEqual(set(operations), set(ASKS_OPERATIONS))
        for name, entry in operations.items():
            with self.subTest(operation=name):
                self.assertEqual(entry.get("capability"), f"asks.{name}")
                self.assertTrue(str(entry.get("description") or "").strip())

    def test_every_guarantee_an_operation_names_is_defined(self):
        data = load_asks()
        self.assertEqual(set(data["guarantees"]), set(ASKS_GUARANTEES))
        for name, entry in data["operations"].items():
            for guarantee in entry.get("guarantees") or []:
                with self.subTest(operation=name, guarantee=guarantee):
                    self.assertIn(guarantee, data["guarantees"])

    def test_the_verdict_comes_from_the_channel_and_a_failed_list_is_not_empty(self):
        operations = load_asks()["operations"]
        self.assertIn("verdict-from-channel", operations["ask"]["guarantees"])
        self.assertIn("unknown-not-empty", operations["list"]["guarantees"])

    def test_every_question_is_present_once_and_carries_its_fields(self):
        setup = load_asks()["setup"]
        self.assertEqual(sorted(q.get("id") for q in setup), sorted(ASKS_QUESTIONS))
        for question in setup:
            for key in QUESTION_KEYS:
                with self.subTest(question=question.get("id"), key=key):
                    self.assertTrue(question.get(key), f"{key!r} missing or empty")

    def test_every_question_feeds_a_concept_or_an_operation(self):
        data = load_asks()
        known = set(data["concepts"]) | set(data["operations"])
        for question in data["setup"]:
            feeds = question["feeds"]
            for target in [feeds] if isinstance(feeds, str) else feeds:
                with self.subTest(question=question["id"], feeds=target):
                    self.assertIn(target, known)

    def test_one_question_declares_the_channel(self):
        declaring = [q["id"] for q in load_asks()["setup"] if q.get("declares")]
        self.assertEqual(declaring, ["channel"])

    def test_the_file_names_no_channel_transport_or_estate_value(self):
        text = ASKS_FILE.read_text(encoding="utf-8")
        for word, pattern in ASKS_FORBIDDEN.items():
            with self.subTest(word=word):
                self.assertIsNone(re.search(pattern, text), f"{word!r} appears in {ASKS_FILE.name}")

    def test_sync_reads_both_wireframes(self):
        import sys
        sys.path.insert(0, str(ROOT))
        import sync
        self.assertLessEqual({"asks.ask", "asks.list"}, sync.known_capabilities())
        self.assertIn("asks", sync.setup_questions())


SESSIONS_FILE = ROOT / "capabilities" / "sessions.yaml"
SESSIONS_CONCEPTS = ("session", "digest", "rotation-flag")
SESSIONS_OPERATIONS = ("digest",)
SESSIONS_GUARANTEES = ("unknown-not-empty", "read-back")
SESSIONS_QUESTIONS = ("source", "threshold", "operations")


def load_sessions() -> dict:
    return yaml.safe_load(SESSIONS_FILE.read_text(encoding="utf-8"))


class SessionsWireframe(unittest.TestCase):
    """Intent: ticket 180. The core describes listing the managed sessions without
    describing a product."""

    def test_the_file_exists(self):
        """Intent: ticket 180, the wireframe file is part of the core."""
        self.assertTrue(SESSIONS_FILE.is_file(), f"{SESSIONS_FILE} is missing")

    def test_the_four_sections_exist(self):
        """Intent: ticket 180, it has concepts, operations, guarantees and setup."""
        data = load_sessions()
        for section in SECTIONS:
            with self.subTest(section=section):
                self.assertTrue(data.get(section), f"section {section!r} is missing or empty")

    def test_every_listed_concept_is_defined_with_a_description(self):
        """Intent: ticket 180, session, digest and rotation-flag are each described."""
        concepts = load_sessions()["concepts"]
        self.assertEqual(set(concepts), set(SESSIONS_CONCEPTS))
        for name, entry in concepts.items():
            with self.subTest(concept=name):
                self.assertTrue(str((entry or {}).get("description") or "").strip())

    def test_the_one_operation_is_the_sessions_digest_capability(self):
        """Intent: ticket 180. sessions.digest lists every managed session with its state,
        and a profile that does not bind it loses only what needs it."""
        operations = load_sessions()["operations"]
        self.assertEqual(set(operations), set(SESSIONS_OPERATIONS))
        entry = operations["digest"]
        self.assertEqual(entry.get("capability"), "sessions.digest")
        self.assertTrue(str(entry.get("description") or "").strip())

    def test_both_guarantees_are_defined_and_the_digest_gives_the_two(self):
        """Intent: ticket 180, the digest gives unknown-not-empty and read-back, both defined."""
        data = load_sessions()
        self.assertEqual(set(data["guarantees"]), set(SESSIONS_GUARANTEES))
        for name, entry in data["guarantees"].items():
            with self.subTest(guarantee=name):
                self.assertTrue(str((entry or {}).get("description") or entry or "").strip())
        guarantees = data["operations"]["digest"]["guarantees"]
        for guarantee in guarantees:
            self.assertIn(guarantee, data["guarantees"])
        self.assertEqual(set(guarantees), set(SESSIONS_GUARANTEES))

    def test_an_unreadable_session_or_list_is_not_an_empty_digest(self):
        """Intent: ticket 180. An unreadable session is listed as unknown, and a failed
        read of the list reports failure, never an empty digest."""
        self.assertIn("unknown-not-empty", load_sessions()["operations"]["digest"]["guarantees"])

    def test_every_question_is_present_once_and_carries_its_fields(self):
        """Intent: ticket 180, source, threshold and operations are asked, each with ask, why, feeds and example."""
        setup = load_sessions()["setup"]
        self.assertEqual(sorted(q.get("id") for q in setup), sorted(SESSIONS_QUESTIONS))
        for question in setup:
            for key in QUESTION_KEYS:
                with self.subTest(question=question.get("id"), key=key):
                    self.assertTrue(question.get(key), f"{key!r} missing or empty")

    def test_every_question_feeds_a_concept_or_an_operation(self):
        """Intent: ticket 180, each setup answer feeds something the wireframe defines."""
        data = load_sessions()
        known = set(data["concepts"]) | set(data["operations"])
        for question in data["setup"]:
            feeds = question["feeds"]
            for target in [feeds] if isinstance(feeds, str) else feeds:
                with self.subTest(question=question["id"], feeds=target):
                    self.assertIn(target, known)

    def test_one_question_declares_the_source(self):
        """Intent: ticket 180, only the source question declares."""
        declaring = [q["id"] for q in load_sessions()["setup"] if q.get("declares")]
        self.assertEqual(declaring, ["source"])

    def test_the_file_names_no_product_transport_or_estate_value(self):
        """Intent: ticket 180, the wireframe names no product, transport or estate value."""
        text = SESSIONS_FILE.read_text(encoding="utf-8")
        for word, pattern in ASKS_FORBIDDEN.items():
            with self.subTest(word=word):
                self.assertIsNone(re.search(pattern, text),
                                  f"{word!r} appears in {SESSIONS_FILE.name}")

    def test_sync_knows_the_sessions_digest_capability(self):
        """Intent: ticket 180, sync reads the new wireframe, so profiles can bind sessions.digest."""
        import sys
        sys.path.insert(0, str(ROOT))
        import sync
        self.assertIn("sessions.digest", sync.known_capabilities())


if __name__ == "__main__":
    unittest.main()
