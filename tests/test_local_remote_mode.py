#!/usr/bin/env python3
################################################################################
# File: test_local_remote_mode.py
# Path: {PROJECT_ROOT}/tests/test_local_remote_mode.py
# Created by: Ryan Severe
# Created: 2026-11-23
# Last Updated: 2026-11-23
# Description: The local remote mode in the layer skills. The orchestrator names
#              five modes and describes local remote, where the operator reads
#              cards only and primaries never use the async channel. The
#              workstream-primary skill carries the mode, its card rules and the
#              mode-change rule, and both skills' no-rotation rules name it.
#              Pinned on the skill sources, read directly.
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


class LocalRemoteMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orchestrator = squash(ORCHESTRATOR.read_text(encoding="utf-8"))
        cls.primary = squash(PRIMARY.read_text(encoding="utf-8"))

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

    def test_orchestrator_local_remote_entry_says_cards_not_async_channel(self):
        """Intent: ticket 195 Decided - in local remote, primaries ask on cards and never
        through the async channel, and a card needing the operator at the desk says so."""
        entry = between(self.orchestrator, "- **Local remote:**", "- **Away:**")
        self.assertIn("reads the chats only through cards", entry)
        self.assertIn("Primaries ask on cards, never through the async channel", entry)
        self.assertIn("a card whose answer needs the operator at the desk says so", entry)

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
        simple question is a question card on its own; never the async channel; and a
        card needing the desk says so."""
        entry = between(self.primary_modes(), "- **Local remote:**", "- **Away:**")
        self.assertIn("the operator reads cards only", entry)
        self.assertIn("one card to approve it, raised only once every check is green", entry)
        self.assertIn("the full reply with its DCs, then ONE card telling the operator to "
                      "scroll back one turn and answer that reply", entry)
        self.assertIn("a question card on its own", entry)
        self.assertIn("Never the async channel", entry)
        self.assertIn("needs the operator at the desk says so", entry)

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
        self.assertIn("the away channel in away", rule)


if __name__ == "__main__":
    unittest.main()
