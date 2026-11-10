#!/usr/bin/env python3
################################################################################
# File: test_spec_gate.py
# Path: {PROJECT_ROOT}/tests/test_spec_gate.py
# Created by: Ryan Severe
# Created: 2026-11-06
# Last Updated: 2026-11-08
# Description: The spec gate skill's checker. A spec - a ticket body or a factory
#              SPEC.md - passes only in the spec format, every broken rule is
#              named, and a spec that could not be read is never reported as a pass.
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
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "skills" / "spec-gate" / "spec_gate.py"
_spec = importlib.util.spec_from_file_location("spec_gate", GATE)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

SPEC = """\
## Problem

`report.py:40` prints a zero count when the lookup fails.

## Decided

A failed lookup raises instead of returning zero.

## Touches

- `report.py`: `count`, raises on a failed lookup

## Edge cases

- Empty or missing: an empty table gives a count of zero, which is a real reading
- Boundary values: N/A: the count has no upper limit to test
- Malformed or wrong type: a non-numeric row raises naming the row
- A failed dependency or lookup: the lookup timing out raises, never prints zero
- Duplicates and ordering: N/A: the count is order-independent and duplicates are counted
- State across runs: N/A: nothing is kept between runs

## Done when

- A failed lookup exits non-zero. Checked by: `test_report.py` `test_failed_lookup`
- An empty table still prints zero.
  Checked by: `test_report.py` `test_empty_table`

## Verify

`test_failed_lookup` fails before the change and passes after it.

## Verification class

gated

## Escalate when

The lookup turns out to have callers that rely on the zero.

## Out of scope

- The report's format.

## Open questions

None.
"""

TICKET = ("**Severity:** Medium. A failed lookup reads as a healthy zero.\n\n" + SPEC
          + "\n**Found** 2026-11-06, while reading the report.\n")

CATEGORIES = ("Empty or missing", "Boundary values", "Malformed or wrong type",
              "A failed dependency or lookup", "Duplicates and ordering", "State across runs")

REQUIRED = ("Problem", "Decided", "Touches", "Edge cases", "Done when", "Verify",
            "Verification class", "Escalate when", "Out of scope", "Open questions")

VAGUE = """\
## Problem

The report is sometimes wrong.

## Decided

Make it more robust.

## Touches

TBD

## Edge cases

- Empty or missing: N/A
- Boundary values: N/A
- Malformed or wrong type: handled
- State across runs: N/A

## Done when

- It works.

## Verify

Run the tests.

## Verification class

probably gated

## Escalate when

If anything looks off.

## Out of scope

- Nothing.

## Open questions

Should failed lookups be cached?
"""


def without_section(text: str, name: str) -> str:
    """The text with one ## section, heading and body, removed."""
    lines, out, skipping = text.splitlines(keepends=True), [], False
    for line in lines:
        if line.startswith("## "):
            skipping = line[3:].strip() == name
        if not skipping:
            out.append(line)
    return "".join(out)


def rules(text: str, mode: str = "spec") -> set[str]:
    return {rule for rule, _ in gate.check(text, mode)}


def refusals(text: str, mode: str = "spec") -> list[tuple[str, str]]:
    return list(gate.check(text, mode))


class WellFormed(unittest.TestCase):
    """Intent: the format in the spec-gate procedure's "The format" section."""

    def test_a_well_formed_spec_passes_in_spec_mode(self):
        """Intent: the approved format - a spec with every section filled passes."""
        self.assertEqual(refusals(SPEC), [])

    def test_a_well_formed_ticket_passes_in_ticket_mode(self):
        """Intent: the approved format - Severity first and Found last, the rest as a spec."""
        self.assertEqual(refusals(TICKET, "ticket"), [])

    def test_spec_mode_does_not_require_severity_or_found(self):
        """Intent: Severity and Found are ticket-only."""
        self.assertNotIn("severity", rules(SPEC))
        self.assertNotIn("found", rules(SPEC))

    def test_fix_is_accepted_for_decided(self):
        """Intent: the approved format - `## Fix` is accepted as a synonym."""
        self.assertEqual(refusals(SPEC.replace("## Decided", "## Fix")), [])

    def test_a_found_line_after_open_questions_is_not_part_of_them(self):
        """Intent: the approved format - Found closes a ticket body, and Open
        questions must still read exactly "None."."""
        self.assertNotIn("open-questions", rules(TICKET, "ticket"))

    def test_a_backticked_todo_is_not_a_placeholder(self):
        """Intent: the approved format - a placeholder is the spec's own gap, not a
        TODO the change is about."""
        text = SPEC.replace("raises on a failed lookup", "removes the `TODO` it left")
        self.assertNotIn("placeholder", rules(text))


class Refusals(unittest.TestCase):
    """Intent: the refusal rules listed in the spec-gate procedure. Each test is the
    well-formed spec with one defect."""

    def test_each_missing_required_section_is_named(self):
        """Intent: the approved rules - a missing required section."""
        for name in REQUIRED:
            with self.subTest(section=name):
                found = refusals(without_section(SPEC, name))
                self.assertIn(("missing-section", name), [(r, d) for r, d in found
                                                         if r == "missing-section"])

    def test_an_empty_section_is_refused(self):
        """Intent: the approved rules - an empty required section."""
        text = SPEC.replace("The lookup turns out to have callers that rely on the zero.\n", "")
        found = refusals(text)
        self.assertIn(("empty-section", "Escalate when"), found)

    def test_a_section_given_twice_is_refused(self):
        """Intent: the rule as approved - a
        second copy of a section could hide an empty one behind a full one."""
        text = SPEC + "\n## Done when\n\n"
        self.assertIn(("duplicate-section", "Done when"), refusals(text))
        both = SPEC.replace("## Decided", "## Fix") + "\n## Decided\n\nAgain.\n"
        self.assertIn(("duplicate-section", "Decided"), refusals(both))

    def test_placeholders_are_refused(self):
        """Intent: the approved rules - a placeholder line (TBD, TODO, ?, ...)."""
        for placeholder in ("TBD", "TODO", "?", "...", "TODO: name the file"):
            with self.subTest(placeholder=placeholder):
                text = SPEC.replace("- The report's format.", f"- {placeholder}")
                self.assertIn("placeholder", rules(text))

    def test_problem_without_a_path_line_pointer_is_refused(self):
        """Intent: the approved rules - Problem with no `path:line`."""
        text = SPEC.replace("`report.py:40` prints", "The report prints")
        self.assertIn("problem-pointer", rules(text))

    def test_a_time_of_day_is_not_a_pointer(self):
        """Intent: the approved rules - `path:line` names a file, so 12:45 is not one."""
        text = SPEC.replace("`report.py:40` prints", "Since 12:45 the report prints")
        self.assertIn("problem-pointer", rules(text))

    def test_a_done_when_item_without_checked_by_is_refused(self):
        """Intent: the approved rules - a Done when item with no `Checked by:`."""
        text = SPEC.replace("  Checked by: `test_report.py` `test_empty_table`\n", "")
        found = refusals(text)
        self.assertEqual([r for r, _ in found], ["done-when-unchecked"])
        self.assertIn("An empty table still prints zero.", found[0][1])

    def test_checked_by_in_bold_counts(self):
        """Characterisation: some existing tickets write **Checked by:** in bold, and they
        should not fail on emphasis alone."""
        text = SPEC.replace("Checked by: `test_report.py` `test_failed_lookup`",
                            "**Checked by:** `test_report.py` `test_failed_lookup`")
        self.assertEqual(refusals(text), [])

    def test_each_missing_edge_case_category_is_named(self):
        """Intent: every category is covered or N/A with a reason."""
        for category in CATEGORIES:
            with self.subTest(category=category):
                lines = [line for line in SPEC.splitlines(keepends=True)
                         if not line.startswith(f"- {category}:")]
                self.assertIn(("edge-case-missing", category), refusals("".join(lines)))

    def test_an_edge_case_marked_na_without_a_reason_is_refused(self):
        """Intent: the approved rules - N/A with no reason."""
        for bare in ("N/A", "N/A:", "N/A: "):
            with self.subTest(bare=bare):
                text = SPEC.replace("- State across runs: N/A: nothing is kept between runs",
                                    f"- State across runs: {bare}")
                self.assertIn(("edge-case-no-reason", "State across runs"), refusals(text))

    def test_an_edge_case_with_no_text_is_refused(self):
        """Intent: the approved rules - a category line that names nothing is absent."""
        text = SPEC.replace("- Malformed or wrong type: a non-numeric row raises naming the row",
                            "- Malformed or wrong type:")
        self.assertIn(("edge-case-missing", "Malformed or wrong type"), refusals(text))

    def test_the_verification_class_must_be_exactly_one_of_two(self):
        """Intent: the approved rules - exactly `gated` or `needs-live-host`."""
        for value in ("needs-live-host", "`gated`"):
            with self.subTest(value=value):
                text = SPEC.replace("\ngated\n", f"\n{value}\n")
                self.assertNotIn("verification-class", rules(text))
        for value in ("probably gated", "gated or needs-live-host", "Gated", "live"):
            with self.subTest(value=value):
                text = SPEC.replace("\ngated\n", f"\n{value}\n")
                self.assertIn("verification-class", rules(text))

    def test_open_questions_must_read_none(self):
        """Intent: the approved rules - Open questions reading anything but "None."."""
        for value in ("None, but check the cache.", "- Should we cache?", "N/A"):
            with self.subTest(value=value):
                text = SPEC.replace("\nNone.\n", f"\n{value}\n")
                self.assertIn("open-questions", rules(text))

    def test_open_questions_refusal_quotes_the_text_that_is_not_none(self):
        """Intent: a body of 'None.' plus a second line must
        not read 'None.', not 'None.'; the refusal names the offending text."""
        text = SPEC.replace("\nNone.\n", "\nNone.\nShould failed lookups be cached?\n")
        details = [d for r, d in refusals(text) if r == "open-questions"]
        self.assertEqual(len(details), 1)
        self.assertIn("Should failed lookups be cached?", details[0])
        self.assertNotIn("reads 'None.', not", details[0])

    def test_ticket_mode_requires_severity(self):
        """Intent: Severity is ticket-only, so a ticket needs it."""
        self.assertIn("severity", rules(TICKET.replace("**Severity:**", "**Impact:**"), "ticket"))

    def test_ticket_mode_requires_a_dated_found_note(self):
        """Intent: Found is ticket-only, so a ticket needs it."""
        self.assertIn("found", rules(TICKET.replace("**Found** 2026-11-06, ", "**Found** "),
                                     "ticket"))
        self.assertIn("found", rules(TICKET.split("\n**Found**")[0] + "\n", "ticket"))


class FoundNote(unittest.TestCase):
    """Intent: a line is the
    closing Found note only if it leads with its date, so a line that merely starts with
    the word Found inside a section is that section's content and is checked."""

    DONE = ("- An empty table still prints zero.\n"
            "  Checked by: `test_report.py` `test_empty_table`\n")

    def repro(self) -> str:
        """The ticket with a mid-section Found line before an unchecked Done-when item and a
        second Open-questions line."""
        text = TICKET.replace(self.DONE, "Found while drafting that a second outcome is needed:\n"
                                         "- It also survives a restart.\n")
        return text.replace("\nNone.\n", "\nNone.\nFound later: whether a 429 should be "
                                         "retried is still undecided.\n")

    def test_a_found_line_inside_a_section_is_checked_as_its_content(self):
        """Intent: the reproduction is refused on both rules."""
        found = refusals(self.repro(), "ticket")
        self.assertIn(("done-when-unchecked", "It also survives a restart."), found)
        self.assertIn("open-questions", [r for r, _ in found])

    def test_a_found_line_inside_a_section_is_checked_in_spec_mode_too(self):
        """Intent: sections() applies the pattern in both modes."""
        self.assertIn("done-when-unchecked", rules(self.repro(), "spec"))
        self.assertIn("open-questions", rules(self.repro(), "spec"))

    def test_each_form_of_the_closing_note_still_satisfies_found(self):
        """Intent: `**Found:** <date>`, `**Found** <date>` and a
        `## Found` heading each close the body and satisfy the found rule."""
        body = TICKET.split("\n**Found**")[0] + "\n"
        forms = {
            "bold colon inside": "\n**Found:** 2026-11-08, a repro.\n",
            "bold no colon": "\n**Found** 2026-11-08, a repro.\n",
            "plain colon": "\nFound: 2026-11-08, a repro.\n",
            "lowercase": "\nfound 2026-11-08, a repro.\n",
            "heading": "\n## Found\n\n2026-11-08, a repro.\n",
        }
        for name, note in forms.items():
            with self.subTest(form=name):
                self.assertEqual(refusals(body + note, "ticket"), [])

    def test_a_dateless_found_line_is_not_the_closing_note(self):
        """Intent: 'Found while reading' has no date, so it is no note and
        a ticket carrying only that is refused on found."""
        text = TICKET.split("\n**Found**")[0] + "\nFound while reading the report.\n"
        self.assertIn("found", rules(text, "ticket"))

    def test_the_closing_note_still_ends_the_last_section(self):
        """Intent: the dated note after Open questions is
        not part of them (the existing test, pinned for the new pattern)."""
        self.assertNotIn("open-questions", rules(TICKET.replace("**Found**", "**Found:**"),
                                                 "ticket"))


class TouchesFormat(unittest.TestCase):
    """Intent: every top-level `## Touches` bullet starts with exactly one backticked
    path, because a factory's intake reads that path as a file the run may change."""

    LINE = "- `report.py`: `count`, raises on a failed lookup"

    def touches(self, *bullets: str) -> str:
        return SPEC.replace(self.LINE, "\n".join(bullets))

    def formats(self, text: str) -> list[tuple[str, str]]:
        return [(r, d) for r, d in refusals(text) if r == "touches-format"]

    def test_a_bullet_with_one_leading_path_passes(self):
        """Intent: the conforming bullet, with trailing prose and a second
        backticked span after the path, is accepted."""
        self.assertEqual(self.formats(self.touches(self.LINE)), [])
        self.assertEqual(self.formats(self.touches("- `a.py`", "* `b/c.py`: edits `run`")), [])

    def test_a_bullet_with_no_backticks_is_refused_naming_it(self):
        """Intent: a bullet with no path is refused, naming the bullet."""
        found = self.formats(self.touches("- report.py: count, raises on a failed lookup"))
        self.assertEqual(len(found), 1)
        self.assertIn("report.py: count", found[0][1])

    def test_a_bullet_starting_with_prose_is_refused(self):
        """Intent: the path is the start of the bullet, not somewhere in it."""
        found = self.formats(self.touches("- Edit `report.py`: `count`"))
        self.assertEqual(len(found), 1)
        self.assertIn("Edit `report.py`", found[0][1])

    def test_a_bullet_starting_with_two_paths_is_refused(self):
        """Intent: two leading paths are two files in one bullet."""
        for bullet in ("- `a.py` `b.py`: both", "- `a.py`, `b.py`: both", "- `a.py`/`b.py`"):
            with self.subTest(bullet=bullet):
                found = self.formats(self.touches(bullet))
                self.assertEqual(len(found), 1)
                self.assertIn("a.py", found[0][1])

    def test_an_empty_bullet_or_an_empty_span_is_refused(self):
        """Intent: a bullet that names no path at all."""
        for bullet in ("-", "- ``: nothing", "- ` `: nothing"):
            with self.subTest(bullet=bullet):
                self.assertEqual(len(self.formats(self.touches(bullet))), 1)

    def test_each_bad_bullet_is_named_and_good_ones_are_not(self):
        """Intent: one line per offending bullet."""
        found = self.formats(self.touches(self.LINE, "- no path here", "- `ok.py`: fine",
                                          "- two `a.py` `b.py`"))
        self.assertEqual(len(found), 2)
        self.assertIn("no path here", found[0][1])
        self.assertIn("two `a.py`", found[1][1])

    def test_an_indented_sub_bullet_is_not_a_top_level_bullet(self):
        """Intent: only top-level bullets are read; a nested line and a
        continuation line belong to the bullet above."""
        text = self.touches(self.LINE, "  - detail with no path", "  continues here")
        self.assertEqual(self.formats(text), [])

    def test_a_section_with_no_top_level_bullet_is_refused_naming_it(self):
        """Intent: prose only declares
        no file for the factory intake to read, so it is refused, naming the section."""
        prose = "Edits `report.py` so that a failed lookup raises instead of printing zero."
        found = self.formats(self.touches(prose))
        self.assertEqual(len(found), 1)
        self.assertIn("Touches", found[0][1])
        self.assertIn("no top-level bullet", found[0][1])

    def test_a_section_with_only_indented_bullets_is_refused(self):
        """Intent: an indented bullet belongs to a bullet above it, so a
        section holding only those has no top-level bullet."""
        found = self.formats(self.touches("  - `report.py`: `count`"))
        self.assertEqual(len(found), 1)
        self.assertIn("no top-level bullet", found[0][1])

    def test_a_section_of_only_tbd_is_refused_on_both_rules(self):
        """Intent: `TBD` is a placeholder and also has no bullet; both
        refusals are named, as the gate names everything wrong."""
        text = self.touches("TBD")
        self.assertEqual(len(self.formats(text)), 1)
        self.assertIn("placeholder", rules(text))

    def test_a_section_with_a_bullet_is_not_refused_for_having_none(self):
        """Intent: the new case fires only when no top-level bullet exists,
        even if prose sits beside the bullet."""
        text = self.touches("Context in prose.", self.LINE)
        self.assertEqual(self.formats(text), [])

    def test_it_applies_in_both_modes(self):
        """Intent: the rule runs in ticket and spec mode."""
        bad = "- no path here"
        self.assertEqual(len(self.formats(self.touches(bad))), 1)
        ticket = TICKET.replace(self.LINE, bad)
        named = [r for r, _ in refusals(ticket, "ticket") if r == "touches-format"]
        self.assertEqual(len(named), 1)

    def test_it_is_named_on_the_command_line(self):
        """Intent: the refusal prints as `refused: touches-format: ...`."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SPEC.md"
            path.write_bytes(self.touches("- no path here").encode())
            done = subprocess.run([sys.executable, str(GATE), "--mode", "spec", str(path)],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 1)
        self.assertIn("refused: touches-format: ", done.stdout)


class PlantedVagueSpec(unittest.TestCase):
    """Intent: a planted vague spec
    must be rejected, and the gate names everything wrong with it, not only the first."""

    def test_the_vague_spec_is_refused_on_every_rule_it_breaks(self):
        found = refusals(VAGUE)
        self.assertEqual({r for r, _ in found}, {
            "problem-pointer", "placeholder", "touches-format", "edge-case-missing",
            "edge-case-no-reason", "done-when-unchecked", "verification-class",
            "open-questions"})
        self.assertIn(("edge-case-missing", "A failed dependency or lookup"), found)
        self.assertIn(("edge-case-missing", "Duplicates and ordering"), found)

    def test_an_empty_spec_is_refused_not_unchecked(self):
        """Intent: an empty file was read; it is missing everything, which is a
        known answer, so it is a refusal rather than a failure to check."""
        self.assertEqual({d for r, d in refusals("") if r == "missing-section"}, set(REQUIRED))


class CommandLine(unittest.TestCase):
    """Intent: exit 0 passes, 1 refuses with each rule listed, 2 could not check. The
    factory harness treats both 1 and 2 as a refusal, so 2 must never be confused with 0."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = gate.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_a_passing_spec_exits_zero(self):
        code, out, _ = self.run_main("--mode", "spec", str(self.write("SPEC.md", SPEC.encode())))
        self.assertEqual(code, 0)

    def test_a_refused_spec_exits_one_and_lists_each_rule(self):
        code, out, _ = self.run_main("--mode", "spec", str(self.write("SPEC.md", VAGUE.encode())))
        self.assertEqual(code, 1)
        for rule in ("problem-pointer", "placeholder", "edge-case-missing",
                     "edge-case-no-reason", "done-when-unchecked", "verification-class",
                     "open-questions"):
            self.assertIn(rule, out)

    def test_a_missing_file_exits_two(self):
        code, out, err = self.run_main("--mode", "spec", str(self.dir / "absent.md"))
        self.assertEqual(code, 2)
        self.assertIn("absent.md", err)
        self.assertNotIn("passed", out)

    def test_a_file_that_is_not_utf8_exits_two(self):
        code, _, err = self.run_main("--mode", "spec", str(self.write("SPEC.md", b"\xff\xfe\x00")))
        self.assertEqual(code, 2)
        self.assertTrue(err)

    def test_an_unknown_mode_exits_two(self):
        code, _, _ = self.run_main("--mode", "plan", str(self.write("SPEC.md", SPEC.encode())))
        self.assertEqual(code, 2)

    def test_it_runs_as_a_standalone_script(self):
        """Intent: the rendered copy runs on its own in the factory,
        with nothing from this repository importable."""
        path = self.write("SPEC.md", SPEC.encode())
        done = subprocess.run([sys.executable, str(GATE), "--mode", "spec", str(path)],
                              capture_output=True, text=True, timeout=30, cwd=self.dir)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
