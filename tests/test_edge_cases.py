#!/usr/bin/env python3
################################################################################
# File: test_edge_cases.py
# Path: {PROJECT_ROOT}/tests/test_edge_cases.py
# Created by: Ryan Severe
# Created: 2026-11-06
# Last Updated: 2026-11-08
# Description: The edge-cases factory skill. One small prompt per edge-case
#              category the spec gate checks, each within the small-model word
#              ceiling, each teaching the exact line form the gate accepts, and
#              given to the test-writer role.
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

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sync  # noqa: E402

_spec = importlib.util.spec_from_file_location("spec_gate", ROOT / "skills" / "spec-gate" / "spec_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

SKILL = ROOT / "skills" / "edge-cases"
CEILING = 300


def slug(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", category.casefold()).strip("-")


def prompt(category: str) -> str:
    return (SKILL / f"{slug(category)}.md").read_text(encoding="utf-8")


class CategoryPrompts(unittest.TestCase):
    """Intent: each edge-case category gets its own small, focused prompt, so a small model
    weighs one category at a time: the gate's six categories, in a factory skill with one
    file per category."""

    def test_there_is_exactly_one_prompt_per_gate_category(self):
        """Intent: one file per category, the spec gate's own list, so
        the prompts and the gate cannot drift apart."""
        files = {p.stem for p in SKILL.glob("*.md") if p.name != "procedure.md"}
        self.assertEqual(files, {slug(c) for c in gate.CATEGORIES})

    def test_each_prompt_fits_the_small_model_ceiling(self):
        """Intent: each fits the small-model budget, counted in words, 300 per file."""
        for category in gate.CATEGORIES:
            with self.subTest(category=category):
                self.assertLessEqual(len(prompt(category).split()), CEILING)

    def test_each_prompt_names_only_its_own_category(self):
        """Intent: one category at a time; a prompt that names another
        category's label invites the model to weigh both."""
        for category in gate.CATEGORIES:
            others = [c for c in gate.CATEGORIES if c != category]
            with self.subTest(category=category):
                text = prompt(category).casefold()
                self.assertIn(category.casefold(), text)
                self.assertEqual([c for c in others if f"- {c.casefold()}:" in text], [])

    def test_each_example_line_is_one_the_gate_accepts(self):
        """Intent: the answer is a line of the spec's Edge cases section, so a
        prompt that teaches a form the gate refuses produces a spec the gate refuses."""
        for category in gate.CATEGORIES:
            with self.subTest(category=category):
                lines = [line for line in prompt(category).splitlines()
                         if line.casefold().startswith(f"- {category.casefold()}:")]
                self.assertTrue(lines, "no example line in the spec's form")
                for line in lines:
                    refused = [r for r in gate.edge_cases(line) if r[1] == category]
                    self.assertEqual(refused, [], line)

    def test_each_prompt_shows_the_na_form_with_a_reason(self):
        """Intent: a category is covered or N/A with a reason, so a
        prompt that only shows the covered form teaches a bare N/A by omission."""
        for category in gate.CATEGORIES:
            with self.subTest(category=category):
                self.assertRegex(prompt(category), r"N/A:\s*\S")


class Delivery(unittest.TestCase):
    """Intent: a factory skill, given to the test-writer role only, because QA is off the
    code night."""

    def test_the_skill_is_rendered_for_the_factory_only(self):
        meta, _ = sync.load_doc(SKILL / "procedure.md", "name", "description")
        self.assertEqual(meta["name"], "edge-cases")
        self.assertEqual(sync.seed_sessions(meta, SKILL / "procedure.md"), ("factory",))

    def test_the_test_writer_is_given_it_and_no_other_role_is(self):
        for role in ("test-writer", "coder", "qa"):
            path = ROOT / "agents" / role / "definition.md"
            meta, _ = sync.load_doc(path, "name", "description")
            with self.subTest(role=role):
                given = "edge-cases" in (meta.get("skills") or [])
                self.assertEqual(given, role == "test-writer")


if __name__ == "__main__":
    unittest.main()
