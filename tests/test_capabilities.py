#!/usr/bin/env python3
################################################################################
# File: test_capabilities.py
# Path: {PROJECT_ROOT}/tests/test_capabilities.py
# Created by: Ryan Severe
# Created: 2026-10-13
# Last Updated: 2026-11-09
# Description: Tests for capabilities/tracker.yaml, the core's wireframe of ticket
#              management. It holds concepts, operations, guarantees and setup
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


if __name__ == "__main__":
    unittest.main()
