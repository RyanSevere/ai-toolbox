#!/usr/bin/env python3
################################################################################
# File: test_planning_spec.py
# Path: {PROJECT_ROOT}/tests/test_planning_spec.py
# Created by: Ryan Severe
# Created: 2026-11-26
# Last Updated: 2026-11-26
# Description: The planning spec, rules/spec-planning.md. The living plan document
#              section is retired, no line names a document the source of truth for
#              status, and the review gate records on the ticket, points to the spec
#              gate and keeps only what the spec gate does not check.
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
SPEC = ROOT / "rules" / "spec-planning.md"

EXERCISES = ["rules/**"]


def read() -> str:
    return SPEC.read_text(encoding="utf-8")


def squash(text: str) -> str:
    return " ".join(text.split())


def section(text: str, word: str) -> str:
    """The body of the first `## ` section whose heading contains `word`."""
    out: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            if out is not None:
                break
            if word.casefold() in line.casefold():
                out = []
        elif out is not None:
            out.append(line)
    if out is None:
        raise AssertionError(f"no '## ' section naming {word!r}")
    return "\n".join(out)


class RetiredSection(unittest.TestCase):
    def test_there_is_no_living_plan_documents_heading(self):
        """Intent: the ticket's Done when, "`rules/spec-planning.md` has no 'Living plan
        documents' section": no heading of any level names a living plan document."""
        heads = [ln for ln in read().splitlines() if ln.startswith("#")]
        self.assertEqual([h for h in heads if "living plan" in h.casefold()], [])

    def test_the_frontmatter_description_no_longer_describes_a_living_plan_document(self):
        """Intent: the ticket's Decided, "rewrite the frontmatter description to match":
        the description does not call the structure a living plan document."""
        parts = read().split("---", 2)
        description = squash(yaml.safe_load(parts[1])["description"]).casefold()
        self.assertNotIn("living plan", description)

    def test_the_work_tracking_section_is_gone(self):
        """Intent: the ticket's Done when, "no `Work Tracking`": the words appear nowhere
        in the spec."""
        self.assertNotIn("work tracking", read().casefold())

    def test_no_line_names_a_document_the_source_of_truth_for_status(self):
        """Intent: the ticket's Done when, "no line naming a document the source of truth
        for status": the phrase "source of truth" is not used in the spec, so the rewrite
        cannot hand status to a document by that wording."""
        hits = [p for p in re.split(r"\n\s*\n", read()) if "source of truth" in squash(p).casefold()]
        self.assertEqual(hits, [])

    def test_the_plan_is_not_called_a_living_document_and_no_decision_ledger_remains(self):
        """Intent: the ticket's Decided, "delete the 'plan is a living document' lines" and
        "reword the scale-the-ceremony line to name no Decision Ledger"."""
        text = read().casefold()
        self.assertNotIn("living document", text)
        self.assertNotIn("decision ledger", text)


class ReviewGate(unittest.TestCase):
    def body(self) -> str:
        return squash(section(read(), "review")).casefold()

    def test_the_review_gate_records_its_outcome_on_the_ticket_not_in_a_change_log(self):
        """Intent: the ticket's Done when, "the review gate records on the ticket": the
        review section names the ticket and no longer records into a Change Log."""
        body = self.body()
        self.assertIn("ticket", body)
        self.assertNotIn("change log", body)

    def test_the_review_gate_points_to_the_spec_gate(self):
        """Intent: the ticket's Done when, "points to the spec gate": the review section
        names the spec gate for what the spec gate checks."""
        self.assertIn("spec gate", self.body())

    def test_the_review_gate_keeps_rollback_dependency_ordering_and_resource_and_timeline(self):
        """Intent: the ticket's Done when, "lists rollback, dependency ordering, and
        resource and timeline reality"."""
        body = self.body()
        for phrase in ("rollback", "dependency ordering", "resource and timeline"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_the_review_gate_runs_before_tickets_are_marked_agent_ready(self):
        """Intent: the ticket's Decided, "a short design review run before tickets are
        marked agent-ready"."""
        self.assertIn("agent-ready", self.body())


class Kept(unittest.TestCase):
    def test_documents_plan_tickets_track_is_kept(self):
        """Characterisation: passes before the change, because the division of labour
        is not being touched; it guards the rewrite against deleting the rule that the
        retirement rests on."""
        self.assertIn("## Documents plan; tickets track", read())

    def test_runbooks_and_scale_the_ceremony_are_kept(self):
        """Characterisation: passes before the change; the ticket's Decided keeps both
        sections, and the rewrite must not take them out with the retired one."""
        text = read()
        self.assertIn("## Runbooks", text)
        self.assertIn("## Scale the ceremony", text)


if __name__ == "__main__":
    unittest.main()
