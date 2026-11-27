#!/usr/bin/env python3
################################################################################
# File: test_layer_rulings.py
# Path: {PROJECT_ROOT}/tests/test_layer_rulings.py
# Created by: Ryan Severe
# Created: 2026-11-23
# Last Updated: 2026-11-26
# Description: The layer-skill rulings. The workstream-primary and orchestrator
#              skills state that information goes on STATUS and a message is for
#              action, that no rotation starts while Remote Control is on, that
#              a rotation ordered by message ends in a card the operator starts,
#              that the already-fresh orchestrator is judged by a confirmed
#              pickup and not a clock, and that Remote Control is the operator's
#              to switch.
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

ROOT = Path(__file__).resolve().parent.parent
PRIMARY = ROOT / "skills" / "workstream-primary" / "procedure.md"
ORCHESTRATOR = ROOT / "skills" / "orchestrator" / "procedure.md"
SPEC = ROOT / "rules" / "spec-response-shape.md"
PRESCRIPTIONS = ROOT / "rules" / "prescriptions.md"


def engineering_bullets() -> list[str]:
    """The bullets of the Engineering section, each with its wrapped continuation
    lines joined. A line starting with whitespace continues the bullet above it."""
    text = PRESCRIPTIONS.read_text(encoding="utf-8")
    match = re.search(r"^## Engineering\s*$", text, re.MULTILINE)
    if match is None:
        raise AssertionError("prescriptions.md: no '## Engineering' heading")
    section = re.split(r"^## ", text[match.end():], maxsplit=1, flags=re.MULTILINE)[0]
    bullets: list[str] = []
    for line in section.splitlines():
        if line.startswith("- "):
            bullets.append(line)
        elif line[:1].isspace() and bullets and bullets[-1] != "":
            bullets[-1] += " " + line.strip()
        elif bullets and bullets[-1] != "":
            # A blank line, rule, or comment marker ends the open bullet.
            bullets.append("")
    return [squash(b) for b in bullets if b.strip()]


def squash(text: str) -> str:
    return " ".join(text.split())


def between(path: Path, start: str, end: str) -> str:
    """The squashed text from `start` up to (not including) `end`, or fail loudly."""
    text = squash(path.read_text(encoding="utf-8"))
    begin = text.find(start)
    if begin < 0:
        raise AssertionError(f"{path.name}: marker not found: {start!r}")
    stop = text.find(end, begin + len(start))
    if stop < 0:
        raise AssertionError(f"{path.name}: end marker not found after {start!r}: {end!r}")
    return text[begin:stop]


class LayerRulings(unittest.TestCase):
    def test_primary_status_section_says_status_not_a_message_for_information(self):
        """Intent: ticket 185 Done when - the STATUS section carries the rule that
        information goes on the STATUS line and a message is for action only."""
        section = between(PRIMARY, "## STATUS", "## Title prefix")
        self.assertIn("STATUS, not a message, for information", section)
        self.assertIn("the orchestrator's digest reads it", section)
        self.assertIn("Send a message only when the receiving session has to act on it",
                      section)

    def test_primary_rotation_section_says_no_rotation_while_remote_control_is_on(self):
        """Intent: ticket 185 Done when - workstream-primary's Rotation section says no
        successor starts while Remote Control is on, and the seed is still written."""
        section = between(PRIMARY, "## Rotation", "## Parking")
        self.assertIn("No rotation while Remote Control is on", section)
        self.assertIn("no successor starts until desk mode", section)
        self.assertIn("writes the seed", section)

    def test_orchestrator_who_rotates_says_no_rotation_while_remote_control_is_on(self):
        """Intent: ticket 185 Done when - the orchestrator's Who rotates says no rotation
        while Remote Control is on, carries a due rotation in the status, and applies
        the same hold to its own rotation."""
        section = between(ORCHESTRATOR, "**Who rotates.**", "**Scope.**")
        self.assertIn("No rotation while Remote Control is on", section)
        self.assertIn("carried in the status", section)
        self.assertIn("ordered when the mode returns to desk", section)
        self.assertIn("holds its own rotation the same way", section)

    def test_morning_step_four_says_message_ordered_rotation_ends_in_a_card(self):
        """Intent: ticket 185 Done when - Morning status step 4 says a rotation ordered by
        message ends in a successor card the operator starts, listed in the status."""
        step = between(ORCHESTRATOR, "4. The successor messages", "**Already fresh.**")
        self.assertIn("told by message to rotate cannot start its successor", step)
        self.assertIn("refuses a session start on a turn that a peer message opened", step)
        self.assertIn("proposes the successor as a card", step)
        self.assertIn("the operator starts it", step)
        self.assertIn("The status lists each waiting card", step)

    def test_primary_title_prefix_section_names_the_own_work_prefixes(self):
        """Intent: the ticket's Done when - the skill's Title prefix section lists
        `pending workers` and `pending ci`, and says a wait on the session's own work
        always names what it waits on."""
        section = between(PRIMARY, "## Title prefix", "## Rotation")
        self.assertIn("`pending workers`", section)
        self.assertIn("`pending ci`", section)
        self.assertIn("always names what it waits on", section)

    def test_primary_title_prefix_section_has_no_unprefixed_case(self):
        """Intent: the ticket's Done when - the skill no longer has a "leaves no prefix"
        case; a wait on the session's own work is never left bare."""
        section = between(PRIMARY, "## Title prefix", "## Rotation")
        self.assertNotIn("leaves no prefix", section)

    def test_primary_staleness_rule_excludes_the_own_work_prefixes(self):
        """Intent: the ticket's Done when - the staleness rule for `pending <name>`
        excludes the literal own-work prefixes, so they are not read as a gone session."""
        rule = between(PRIMARY, "- A `pending <name>` whose session", "- If `list_sessions`")
        self.assertIn("`pending workers`", rule)
        self.assertIn("`pending ci`", rule)

    def test_orchestrator_title_check_does_not_report_own_work_prefixes_as_missing(self):
        """Intent: the ticket's Done when - the orchestrator's title check names
        `pending workers` and `pending ci`, so it does not report them as a missing
        session."""
        check = between(ORCHESTRATOR, "- **Title prefixes:**", "- **Rotation calls:**")
        self.assertIn("`pending workers`", check)
        self.assertIn("`pending ci`", check)

    def test_already_fresh_names_no_time_window(self):
        """Intent: ticket 185's operator ruling - the already-fresh condition replaces the
        one-hour window, so the paragraph names no time window at all."""
        para = between(ORCHESTRATOR, "**Already fresh.**", "**Who rotates.**")
        self.assertIsNone(re.search(r"\blast hour\b|\bwithin the last\b|\bminutes\b", para),
                          para)

    def test_already_fresh_states_the_confirmed_pickup_condition(self):
        """Intent: ticket 185's operator ruling - already fresh means the pickup was confirmed
        from a seed saying the status is pending, with no day-opening message since."""
        para = between(ORCHESTRATOR, "**Already fresh.**", "**Who rotates.**")
        self.assertIn("whose pickup was confirmed from a seed that says the morning "
                      "status is pending", para)
        self.assertIn("no day-opening message handled since", para)
        self.assertIn("skips the self-rotation and runs steps 2 to 4 itself", para)

    def test_set_remote_control_appears_only_in_the_orchestrators_never_sentence(self):
        """Intent: ticket 185 Done when - neither skill's text contains set_remote_control
        except the orchestrator's sentence that it never calls it."""
        self.assertNotIn("set_remote_control", PRIMARY.read_text(encoding="utf-8"))
        text = squash(ORCHESTRATOR.read_text(encoding="utf-8"))
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if "set_remote_control" in s]
        self.assertEqual(len(sentences), 1, sentences)
        self.assertIn("orchestrator never calls `set_remote_control`", sentences[0])

    def test_no_orchestrator_line_tells_it_to_switch_remote_control(self):
        """Intent: ticket 185 Done when - no line tells the orchestrator to turn Remote
        Control on or off; it reads and reports the state only."""
        text = squash(ORCHESTRATOR.read_text(encoding="utf-8"))
        for phrase in ("turn it off", "turns it off", "turn it on", "sets Remote Control"):
            self.assertNotIn(phrase, text)
        section = between(ORCHESTRATOR, "**Remote Control.**", "## Duplicate checks")
        self.assertIn("The operator switches it", section)
        self.assertIn("reports it in the status", section)
        self.assertIn("listed as unknown, never as off", section)

    def test_night_step_reads_and_records_remote_control_state(self):
        """Intent: ticket 185 Done when - the night step reads each session's Remote
        Control state and records it, and points to the operator's to switch."""
        section = between(ORCHESTRATOR, "## Night", "## After a rotation")
        self.assertIn("Read each managed session's Remote Control state and record it",
                      section)
        self.assertIn("Remote Control is the operator's to switch", section)

    def test_primary_modes_say_remote_control_is_the_operators_to_switch(self):
        """Intent: ticket 185 Done when - workstream-primary says Remote Control is the
        operator's to switch, and a primary never sets it."""
        section = squash(PRIMARY.read_text(encoding="utf-8")).split("## Modes", 1)[1]
        self.assertIn("Remote Control is the operator's to switch. Never set it.", section)
        self.assertNotIn("the orchestrator sets Remote Control", section)

    def test_spec_defines_the_status_footer(self):
        """Intent: the ticket's Done when, first item - the response-shape spec has a
        STATUS footer section naming the three fields, saying it is the reply's last
        line, and saying layers 1 and 2 require it."""
        text = SPEC.read_text(encoding="utf-8")
        match = re.search(r"^## STATUS footer\s*$", text, re.MULTILINE)
        self.assertIsNotNone(match, "no '## STATUS footer' section in the spec")
        section = squash(re.split(r"^## ", text[match.end():], maxsplit=1, flags=re.MULTILINE)[0])
        for field in ("needs operator:", "workers running:", "background tasks:"):
            self.assertIn(field, section)
        self.assertIn("the reply's last line", section)
        self.assertIn("layers 1 and 2", section)

    def test_primary_status_section_says_the_reply_ends_with_the_line(self):
        """Intent: the ticket's Done when, fifth item - the workstream-primary STATUS
        section says the reply ends with the line, and the wrap-up copy matches it
        word for word."""
        section = between(PRIMARY, "## STATUS", "## Title prefix")
        self.assertIn("The reply ends with the STATUS line", section)
        self.assertIn("word for word", section)

    def test_orchestrator_says_layer_1_ends_its_replies_with_the_same_line(self):
        """Intent: the ticket's Done when, fifth item - the orchestrator procedure says
        layer 1 ends its replies with the same STATUS line."""
        text = squash(ORCHESTRATOR.read_text(encoding="utf-8"))
        self.assertIn("layer 1 ends its replies with the same STATUS line", text)

    def test_engineering_section_has_a_line_on_questions_asked_of_a_person(self):
        """Intent: the ticket's Done when, first item - the Engineering section of the
        prescriptions carries a line saying a question asked of a person states what
        happened, then what each answer does. The line sits between the Engineering
        heading and the next heading."""
        matching = [b.lower() for b in engineering_bullets()
                    if "what happened" in b.lower() and "what each answer does" in b.lower()]
        self.assertEqual(len(matching), 1,
                         "expected one Engineering line with 'what happened' and "
                         f"'what each answer does', found {len(matching)}")

    def test_the_question_line_is_a_single_bullet(self):
        """Intent: the ticket's Done when, first item - the rule is one line, in the
        prescriptions' one-line-per-rule form: a wrapped continuation is allowed, a
        second bullet is not, so neither phrase appears in any other Engineering bullet."""
        carrying = [b for b in engineering_bullets()
                    if "what happened" in b.lower() or "what each answer does" in b.lower()]
        self.assertEqual(len(carrying), 1,
                         f"expected the two phrases in one bullet, found {len(carrying)} bullets")
        self.assertIn("what happened", carrying[0].lower())
        self.assertIn("what each answer does", carrying[0].lower())


if __name__ == "__main__":
    unittest.main()
