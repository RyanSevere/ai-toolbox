#!/usr/bin/env python3
################################################################################
# File: test_local_remote_mode.py
# Path: {PROJECT_ROOT}/tests/test_local_remote_mode.py
# Created by: Ryan Severe
# Created: 2026-11-23
# Last Updated: 2026-11-24
# Description: The local remote and away modes in the layer skills. The orchestrator
#              names five modes and describes local remote, where the operator reads
#              cards only. In local remote and away an interactive session asks by
#              card, and the async channel is a fallback only when Remote Control is
#              off or the work is non-interactive. The workstream-primary skill
#              carries the modes, their card rules and the mode-change rule, and
#              both skills' no-rotation rules name them. Pinned on the skill
#              sources, read directly.
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


def squash(text: str) -> str:
    return " ".join(text.split())


def between(text: str, start: str, end: str) -> str:
    """The squashed text from `start` up to (not including) `end`, or fail loudly."""
    begin = text.find(start)
    if begin < 0:
        raise AssertionError(f"marker not found: {start!r}")
    stop = text.find(end, begin + len(start))
    if stop < 0:
        raise AssertionError(f"end marker not found after {start!r}: {end!r}")
    return text[begin:stop]


REQUIRES_BLOCK = re.compile(r"<!-- requires: ([\w.]+) -->\n(.*?)<!-- end -->", re.DOTALL)


def ask_blocks(raw: str) -> list[tuple[int, int, str]]:
    """Each `requires: asks.ask` block of the raw source as (start, end, squashed body)."""
    return [(m.start(), m.end(), squash(m.group(2)))
            for m in REQUIRES_BLOCK.finditer(raw) if m.group(1) == "asks.ask"]


def entry_span(raw: str, start: str, end: str) -> tuple[int, int]:
    """Offsets in the raw source of a Modes entry, from its marker to the next one."""
    modes = raw.index("## Modes")
    begin = raw.index(start, modes)
    return begin, raw.index(end, begin + len(start))


class LocalRemoteMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orchestrator_raw = ORCHESTRATOR.read_text(encoding="utf-8")
        cls.primary_raw = PRIMARY.read_text(encoding="utf-8")
        cls.orchestrator = squash(cls.orchestrator_raw)
        cls.primary = squash(cls.primary_raw)

    def fallback_in(self, raw: str, start: str, end: str) -> str:
        """The body of the one `requires: asks.ask` block that sits inside the entry
        from `start` to `end`; fail if there is not exactly one."""
        begin, stop = entry_span(raw, start, end)
        inside = [body for lo, hi, body in ask_blocks(raw) if begin <= lo and hi <= stop]
        self.assertEqual(len(inside), 1, f"{start}: {inside}")
        return inside[0]

    def assert_fallback_sentence(self, body: str):
        """The fallback names the async channel through the capability and gives its two
        cases: Remote Control off while the operator is remote, and non-interactive work."""
        self.assertIn("{{asks.ask}}", body)
        self.assertIn("Remote Control is off", body)
        self.assertIn("non-interactive", body)

    def orchestrator_modes(self) -> str:
        return between(self.orchestrator, "## Modes", "**Remote Control.**")

    def primary_modes(self) -> str:
        return between(self.primary, "## Modes", "Rules:")

    def test_orchestrator_names_five_modes_in_order(self):
        """Intent: ticket 195 Done when - the orchestrator's Modes section says "Five
        modes" and lists Desk, Bio, Local remote, Away, Night in that order."""
        section = self.orchestrator_modes()
        self.assertIn("Five modes:", section)
        self.assertNotIn("Four modes", section)
        marks = [section.find(f"- **{name}:**")
                 for name in ("Desk", "Bio", "Local remote", "Away", "Night")]
        self.assertNotIn(-1, marks, marks)
        self.assertEqual(marks, sorted(marks), marks)

    def test_orchestrator_argument_hint_names_local_remote(self):
        """Intent: ticket 195 Done when - the orchestrator's argument hint offers local
        remote among the modes it can be told to set."""
        source = ORCHESTRATOR.read_text(encoding="utf-8")
        hint = [line for line in source.split("---", 2)[1].splitlines()
                if line.startswith("argument-hint:")]
        self.assertEqual(len(hint), 1, hint)
        self.assertIn("desk, bio, local remote, away or night", hint[0])

    def test_orchestrator_local_remote_entry_says_cards_with_async_fallback(self):
        """Intent: ticket 201 Decided - in local remote, primaries ask on cards, and fall
        back to the async channel only when this session's Remote Control is off or the
        work is non-interactive. Ticket 195 still holds: a card whose answer needs the
        operator at the desk says so."""
        entry = between(self.orchestrator, "- **Local remote:**", "- **Away:**")
        self.assertIn("reads the chats only through cards", entry)
        self.assertIn("Primaries ask on cards", entry)
        self.assertNotIn("never through the async channel", entry)
        self.assertIn("a card whose answer needs the operator at the desk says so", entry)
        self.assert_fallback_sentence(self.fallback_in(
            self.orchestrator_raw, "- **Local remote:**", "- **Away:**"))

    def test_both_no_rotation_rules_name_local_remote(self):
        """Intent: ticket 195 Decided - no rotation while Remote Control is on covers
        local remote, in the orchestrator's Who rotates and the primary's Rotation."""
        who = between(self.orchestrator, "**No rotation while Remote Control is on,**",
                      "A due rotation")
        self.assertIn("in bio, local remote and away", who)
        rotation = between(self.primary, "**No rotation while Remote Control is on.**",
                           "no successor starts")
        self.assertIn("in bio, local remote or away mode", rotation)

    def test_primary_modes_have_a_local_remote_entry_in_place(self):
        """Intent: ticket 195 Done when - workstream-primary's Modes list has a Local
        remote entry between Desk and bio and Away."""
        section = self.primary_modes()
        marks = [section.find(f"- **{name}:**")
                 for name in ("Desk and bio", "Local remote", "Away")]
        self.assertNotIn(-1, marks, marks)
        self.assertEqual(marks, sorted(marks), marks)

    def test_primary_local_remote_entry_carries_the_card_rules(self):
        """Intent: ticket 195 Decided - the merge card only once every check is green; for
        an important question the full reply, then ONE card to scroll back one turn; a
        simple question is a question card on its own; and a card needing the desk says
        so. Ticket 201 Decided - the async channel is no longer ruled out outright: the
        entry falls back to it only when Remote Control is off or the work is
        non-interactive."""
        entry = between(self.primary_modes(), "- **Local remote:**", "- **Away:**")
        self.assertIn("the operator reads cards only", entry)
        self.assertIn("one card to approve it, raised only once every check is green", entry)
        self.assertIn("the full reply with its DCs, then ONE card telling the operator to "
                      "scroll back one turn and answer that reply", entry)
        self.assertIn("a question card on its own", entry)
        self.assertNotIn("Never the async channel", entry)
        self.assertIn("needs the operator at the desk says so", entry)
        self.assert_fallback_sentence(self.fallback_in(
            self.primary_raw, "- **Local remote:**", "- **Away:**"))

    def test_primary_how_to_ask_has_cards_in_local_remote_bullet(self):
        """Intent: ticket 195 Decided - How to ask says every ask in local remote goes on
        a card, while the DCs themselves still go in the reply."""
        section = between(self.primary, "**Every question is a numbered DC",
                          "**Do not split a ticket")
        self.assertIn("**Cards in local remote.**", section)
        self.assertIn("every ask goes on a card: the merge card, the scroll-back card, "
                      "or a question card", section)
        self.assertIn("The DCs themselves still go in the reply", section)

    def test_primary_mode_change_rule_covers_local_remote(self):
        """Intent: ticket 195 Decided - moving to or from local remote re-raises every ask
        in flight in the new mode's form."""
        rule = self.primary.split("The mode changes while an ask is in flight.", 1)[1]
        rule = rule.split("Two mode messages cross", 1)[0]
        self.assertIn("To or from local remote: re-raise every ask in flight in the new "
                      "mode's form", rule)
        self.assertIn("a card in local remote", rule)
        self.assertIn("a DC in your own chat at desk or bio", rule)

    def test_primary_away_entry_asks_by_card_in_the_three_forms(self):
        """Intent: ticket 201 Decided - in away an interactive session asks by card, in the
        same three forms as local remote: the merge card once every check is green, the
        full reply plus ONE scroll-back card for an important question, and a question
        card on its own for a simple one."""
        entry = between(self.primary_modes(), "- **Away:**", "- **Night:**")
        self.assertIn("interactive", entry)
        self.assertIn("by card", entry)
        self.assertIn("the merge card", entry)
        self.assertIn("once every check is green", entry)
        self.assertIn("the full reply", entry)
        self.assertIn("ONE card", entry)
        self.assertIn("scroll back one turn", entry)
        self.assertIn("a question card on its own", entry)

    def test_orchestrator_away_entry_says_primaries_ask_by_card_in_the_three_forms(self):
        """Intent: ticket 201 Decided - the orchestrator's away entry says primaries ask on
        cards, in the same three forms as local remote."""
        entry = between(self.orchestrator, "- **Away:**", "- **Night:**")
        self.assertIn("interactive", entry)
        self.assertIn("Primaries ask on cards", entry)
        self.assertIn("the merge card", entry)
        self.assertIn("once every check is green", entry)
        self.assertIn("ONE card", entry)
        self.assertIn("scroll back", entry)
        self.assertIn("question card", entry)

    def test_away_entries_carry_the_same_fallback_sentence(self):
        """Intent: ticket 201 Decided - each away entry carries one fallback sentence: when
        this session's Remote Control is off while the operator is remote, or the work is
        non-interactive, ask through the async channel instead."""
        for raw in (self.primary_raw, self.orchestrator_raw):
            self.assert_fallback_sentence(
                self.fallback_in(raw, "- **Away:**", "- **Night:**"))

    def test_fallback_sentences_sit_in_ask_blocks_and_away_entries_do_not(self):
        """Intent: ticket 201 Decided - the fallback sentences sit inside their own
        `requires: asks.ask` block, and the away entries themselves do not, so a profile
        with no async channel keeps the away entries."""
        for raw in (self.primary_raw, self.orchestrator_raw):
            blocks = ask_blocks(raw)
            lo, hi = entry_span(raw, "- **Local remote:**", "- **Night:**")
            inside = [body for start, end, body in blocks if lo <= start and end <= hi]
            self.assertEqual(len(inside), 2, inside)
            self.assertTrue(all("non-interactive" in body for body in inside), inside)
            for marker in ("- **Local remote:**", "- **Away:**"):
                at = raw.index(marker, raw.index("## Modes"))
                self.assertFalse([1 for start, end, _ in blocks if start <= at < end],
                                 f"{marker} sits inside a requires block")

    def test_primary_mode_change_rule_names_cards_and_the_async_channel_in_two_cases(self):
        """Intent: ticket 201 Decided - the mode-change rule re-raises an ask in flight as a
        card in local remote or away, a DC in your own chat at desk or bio, and uses the
        async channel only when Remote Control is off or the work is non-interactive."""
        rule = self.primary.split("The mode changes while an ask is in flight.", 1)[1]
        rule = rule.split("Two mode messages cross", 1)[0]
        self.assertIn("a card in local remote or away", rule)
        self.assertIn("a DC in your own chat at desk or bio", rule)
        self.assertNotIn("the away channel in away", rule)
        self.assertNotIn("re-ask it through the away channel", rule)
        self.assertNotIn("send every held ask through the away channel", rule)
        self.assertIn("Remote Control is off", rule)
        self.assertIn("non-interactive", rule)
        # The rule sits outside any requires block, so it must name no capability.
        self.assertNotIn("{{", rule)


if __name__ == "__main__":
    unittest.main()
