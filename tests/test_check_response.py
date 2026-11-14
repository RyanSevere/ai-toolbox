#!/usr/bin/env python3
################################################################################
# File: test_check_response.py
# Path: {PROJECT_ROOT}/tests/test_check_response.py
# Created by: Ryan Severe
# Created: 2026-09-23
# Last Updated: 2026-11-13
# Description: Transcript fixtures for responses/check_response.py, its shared
#              shape core and its per-tool adapters. Every case here was
#              found by using the script and verified by hand first; the tests
#              exist so the next transcript-format surprise fails loudly
#              instead of silently grading the wrong text. Stdlib only.
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

import argparse
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# One entry point, a tool-neutral shape core, one adapter per tool. The
# core and adapters are imported first so a missing module fails here, not later.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "responses"))

import shape  # noqa: E402
import claude  # noqa: E402
import copilot  # noqa: E402
import cursor  # noqa: E402
import check_response as cr  # noqa: E402

EXERCISES = ["responses/**"]  # the checker under test, whatever depmap.json last measured

SHAPED_CLEAN = """Mode: Execution
Needs from you: nothing
Changed: nothing

## Asked, done, result

**A1 Did a thing**
  - Done: yes

## Premises acted on

**P1 "you asked for a thing"** [factual]
  - Verdict: confirmed
  - Evidence for: the request said "please do the thing today"
  - Evidence against: none
"""

SHAPED_NO_CHANGED_LINE = SHAPED_CLEAN.replace("Changed: nothing\n", "")

# The defect this file was written for: a ruling in the execution block, untagged.
SHAPED_UNTAGGED_RULING = """Mode: Execution
Needs from you: nothing
Changed: nothing

## Asked, done, result

**A1 Did a thing**
  - Done: yes

## Premises acted on

**P1 "refinement needs no ticket"**
  - Verdict: acted on as a ruling
"""

SHAPED_TAGGED_RULING = SHAPED_UNTAGGED_RULING.replace(
    '**P1 "refinement needs no ticket"**',
    '**P1 "refinement needs no ticket"** [ruling]',
)

CONDENSED_CLEAN = """Mode: Planning
Needs from you: 1 decision, 1 operator step
Changed: nothing

## Summary

The live state matches the seed: `git status -sb` printed "## main...origin/main", and the gate passed the draft.

## Logic and approach

- LA1 Rank by what unblocks the most work
  - Verdict: holds, because example-2 waits on example-1

## Decisions and clarifications

- DC1 Pick the next ticket
  - Use case: decides what the next session builds
  - Options:
    - a. example-1 first (recommended)
    - b. example-2 first
  - Recommendation: (a), because it unblocks example-2

## Operator steps

- OS1 Run `python tools/probe.py --host example` and paste the output back

## Recommended next

- R1 Once OS1's output is back, decide whether example-1 can run on that host
  - Reasoning: the probe is the only unknown

## Came up while doing it

None.
"""


def user(content: str) -> str:
    return json.dumps({"type": "user.message", "data": {"content": content}})


def reply(message_id: str, content: str) -> str:
    return json.dumps(
        {"type": "assistant.message", "data": {"messageId": message_id, "content": content}}
    )


def invocation(command: str = "python check_response.py --previous") -> str:
    return json.dumps(
        {
            "type": "tool.execution_start",
            "data": {
                "toolName": "run_in_terminal",
                "arguments": {"command": command},
            },
        }
    )


class TranscriptCase(unittest.TestCase):
    def transcript(self, *lines: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8", newline="\n"
        )
        handle.write("\n".join(lines) + "\n")
        handle.close()
        path = Path(handle.name)
        self.addCleanup(path.unlink)
        return path

    def lookback(self, *lines: str):
        picked, runs, truncated = shape.lookback(copilot.turns(self.transcript(*lines)))
        return [(back, turn.text) for back, turn in picked], runs, truncated


class SessionStarters(TranscriptCase):
    def test_sitrep_marker_is_detected(self):
        self.assertEqual(shape.session_starter("Results from Sitrep\n\nIN FLIGHT\n"), "Sitrep")

    def test_prime_marker_survives_bold(self):
        self.assertEqual(shape.session_starter("**Results from Prime**\n\nREPO x\n"), "Prime")

    def test_marker_is_case_insensitive(self):
        self.assertEqual(shape.session_starter("results from prime"), "Prime")

    def test_shaped_reply_is_not_a_starter(self):
        self.assertIsNone(shape.session_starter(SHAPED_CLEAN))

    def test_marker_must_be_the_first_line(self):
        """Otherwise any reply quoting the marker could exempt itself."""
        self.assertIsNone(shape.session_starter("Mode: Execution\n\nResults from Prime\n"))


class Arrears(TranscriptCase):
    def test_skipped_turn_is_collected(self):
        picked, _, truncated = self.lookback(
            user("one"),
            reply("m1", SHAPED_NO_CHANGED_LINE),
            user("two"),
            reply("m2", SHAPED_CLEAN),
            user("three - in progress"),
        )
        self.assertEqual([back for back, _ in picked], [0, 1])
        self.assertFalse(truncated)

    def test_walk_stops_at_a_graded_turn(self):
        picked, _, truncated = self.lookback(
            user("one"),
            reply("m1", SHAPED_NO_CHANGED_LINE),
            user("two"),
            invocation(),
            reply("m2", SHAPED_CLEAN),
            user("three - in progress"),
        )
        self.assertEqual([back for back, _ in picked], [0])
        self.assertFalse(truncated)

    def test_cap_reports_itself(self):
        lines = [user("start")]
        for i in range(shape.LOOKBACK_CAP + 2):
            lines += [reply(f"m{i}", SHAPED_CLEAN), user(f"turn {i}")]
        _, _, truncated = self.lookback(*lines)
        self.assertTrue(truncated)

    def test_rendered_path_still_counts_as_a_run(self):
        """The script ships to .github/scripts/ in every repo. If the detector
        stopped recognising that form, a skip would become undetectable and the
        arrears walk would silently re-grade turns that were already graded."""
        for command in (
            "python .github/scripts/check_response.py --previous",
            r"python .github\scripts\check_response.py --previous",
            "python3 .github/scripts/check_response.py --previous",
            "python .github/scripts/responses/check_response.py --previous",
            r"python .github\scripts\responses\check_response.py --previous",
        ):
            with self.subTest(command=command):
                picked, _, _ = self.lookback(
                    user("one"),
                    reply("m1", SHAPED_NO_CHANGED_LINE),
                    user("two"),
                    invocation(command),
                    reply("m2", SHAPED_CLEAN),
                    user("three - in progress"),
                )
                self.assertEqual([back for back, _ in picked], [0])

    def test_reply_spanning_several_message_ids_is_joined(self):
        picked, _, _ = self.lookback(
            user("one"),
            reply("m1", "Mode: Execution\nNeeds from you: nothing\nChanged: nothing\n"),
            reply("m2", "\n## Asked, done, result\n\n**A1 Did a thing**\n- Done: yes\n"),
            user("two - in progress"),
        )
        self.assertIn("Asked, done, result", picked[0][1])


class Grading(TranscriptCase):
    def findings(self, text: str) -> list[str]:
        return shape.check(*shape.parse(text))[0]

    def test_clean_reply_passes(self):
        self.assertEqual(self.findings(SHAPED_CLEAN), [])

    def test_missing_header_line_is_caught(self):
        self.assertTrue(any("Changed" in f for f in self.findings(SHAPED_NO_CHANGED_LINE)))

    def test_untagged_execution_premise_is_reported_as_untagged(self):
        """It used to fail on missing evidence instead, which described the grader."""
        findings = self.findings(SHAPED_UNTAGGED_RULING)
        self.assertTrue(any("not tagged" in f for f in findings))

    def test_tagged_ruling_needs_no_evidence(self):
        self.assertEqual(self.findings(SHAPED_TAGGED_RULING), [])

    def test_confirmed_verdict_with_no_evidence_is_a_contradiction(self):
        text = SHAPED_CLEAN.replace('- Evidence for: the request said "please do the thing today"',
                                    "- Evidence for: none")
        self.assertTrue(any("no evidence for it" in f for f in self.findings(text)))

    def test_contradicted_verdict_needs_evidence_against_not_for(self):
        """The evidence for a false premise sits on the against side."""
        text = SHAPED_CLEAN.replace("- Verdict: confirmed", "- Verdict: contradicted").replace(
            '- Evidence for: the request said "please do the thing today"\n  - Evidence against: none\n',
            "- Evidence for: none\n  - Evidence against: `board_collector.py:201` says otherwise\n",
        )
        self.assertEqual(self.findings(text), [])

    def test_contradicted_verdict_with_no_evidence_against_is_caught(self):
        text = SHAPED_CLEAN.replace("- Verdict: confirmed", "- Verdict: contradicted").replace(
            '- Evidence for: the request said "please do the thing today"\n', "- Evidence for: none\n"
        )
        self.assertTrue(any("no evidence against it" in f for f in self.findings(text)))


class Pointers(TranscriptCase):
    """Evidence has to be followable. Every false claim on 2026-09-24 had an
    Evidence for line, and every one was a summary with nothing to follow."""

    def findings(self, evidence: str) -> list[str]:
        text = SHAPED_CLEAN.replace(
            '- Evidence for: the request said "please do the thing today"', f"- Evidence for: {evidence}"
        )
        return [f for f in shape.check(*shape.parse(text))[0] if "no pointer" in f]

    def test_summary_alone_is_caught(self):
        self.assertTrue(self.findings("the collector derives Priority from the Severity line"))

    def test_bare_identifier_is_not_a_pointer(self):
        self.assertTrue(self.findings("see `board_collector.py`"))

    def test_each_pointer_kind_is_accepted(self):
        for evidence in (
            "`board_collector.py:201` only fills an empty Priority",
            "context/sitrep.prompt.md:125-126",
            "fetched https://docs.github.com/en/issues",
            'operator, 2026-09-24: "severity sets initial priority but they are different"',
            "`gh issue view 3 --repo owner/repo` returned the body",
        ):
            with self.subTest(evidence=evidence):
                self.assertEqual(self.findings(evidence), [])

    def test_pointer_on_a_continuation_line_counts(self):
        text = SHAPED_CLEAN.replace(
            '- Evidence for: the request said "please do the thing today"',
            "- Evidence for: read directly\n  `open issues checked: 99   mismatched: 8`",
        )
        self.assertEqual([f for f in shape.check(*shape.parse(text))[0] if "no pointer" in f], [])


class ExampleFormat(TranscriptCase):
    """The shape's own examples: an ID with no bold, fields indented with &nbsp;.
    Until 2026-09-24 this parsed to zero items and passed on the header alone."""

    REPLY = (
        "Mode: Planning\nNeeds from you: nothing\nChanged: nothing\n\n"
        "## Your premises\n\n"
        'P1  "the ticket is proj-35"  [factual]\n'
        "&nbsp;&nbsp;&nbsp;&nbsp;Verdict: confirmed\n"
        "&nbsp;&nbsp;&nbsp;&nbsp;Evidence for: I checked\n"
        "&nbsp;&nbsp;&nbsp;&nbsp;Evidence against: none found\n"
        "&nbsp;&nbsp;&nbsp;&nbsp;Q1 Is that the right ticket?\n\n"
        "## My claims\n\n## Logic and approach\n"
    )

    def test_unbolded_item_is_parsed(self):
        _, sections = shape.parse(self.REPLY)
        self.assertEqual(len(sections["yourpremises"]), 1)

    def test_question_line_does_not_start_an_item(self):
        _, sections = shape.parse(self.REPLY)
        self.assertEqual([i["title"][:2] for i in sections["yourpremises"]], ["P1"])

    def test_its_fields_are_graded(self):
        findings = shape.check(*shape.parse(self.REPLY))[0]
        self.assertTrue(any("no pointer" in f for f in findings), findings)


class NothingToGrade(TranscriptCase):
    """Two states used to print the same UNKNOWN. A first reply has nothing before
    it by design; an interrupted turn produced nothing by accident. The operator
    needs to tell them apart without reading the transcript."""

    def run_main(self, *lines: str) -> int:
        path = self.transcript(*lines)
        argv = ["check_response.py", "--previous", "--tool", "copilot", "--transcript", str(path)]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch("sys.stdout", new=io.StringIO()), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return cr.main()

    def test_first_reply_of_a_session_is_not_applicable(self):
        self.assertEqual(self.run_main(user("first message - in progress")),
                         shape.EXIT_NOT_APPLICABLE)

    def test_earlier_turn_with_no_reply_is_unknown(self):
        self.assertEqual(self.run_main(user("one - interrupted"), user("two - in progress")), 3)


class VerdictlessRunsAreFree(TranscriptCase):
    """An UNKNOWN run used to spend the turn's one run, so fixing the
    cause and re-running got REFUSED and the turn ended with no grade at all."""

    def setUp(self):
        ledger = tempfile.TemporaryDirectory()
        self.addCleanup(ledger.cleanup)
        patcher = mock.patch.object(cr.tempfile, "gettempdir", return_value=ledger.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_on(self, path: Path) -> int:
        argv = ["check_response.py", "--previous", "--tool", "copilot", "--transcript", str(path)]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch("sys.stdout", new=io.StringIO()), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return cr.main()

    def test_rerun_after_unknown_is_not_refused(self):
        path = self.transcript(user("one - interrupted"), user("two - in progress"))
        self.assertEqual(self.run_on(path), 3)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(invocation() + "\n")
        self.assertEqual(self.run_on(path), 3, "second run was refused, not re-attempted")

    def test_a_graded_run_still_spends_the_budget(self):
        path = self.transcript(user("one"), reply("m1", SHAPED_CLEAN), user("two"),
                               invocation(), invocation(), invocation())
        self.assertEqual(self.run_on(path), 2)


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class OnlyASeenVerdictSpendsTheRun(TranscriptCase):
    """One successful run per turn. A --previous run whose
    verdict never reached a terminal - it crashed, was cancelled, or its output was
    piped and cut short - must not stop the re-run that completes it."""

    def setUp(self):
        ledger = tempfile.TemporaryDirectory()
        self.addCleanup(ledger.cleanup)
        self.ledger_dir = Path(ledger.name)
        patcher = mock.patch.object(cr.tempfile, "gettempdir", return_value=ledger.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.transcript(user("one"), reply("m1", SHAPED_CLEAN), user("two"))

    def run_on(self, stdout: io.StringIO) -> int:
        argv = ["check_response.py", "--previous", "--tool", "copilot", "--transcript", str(self.path)]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=stdout), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return cr.main()

    def ran_once(self) -> None:
        """The transcript records the invocation, as the real one does after a run."""
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(invocation() + "\n")

    def test_a_verdict_seen_on_a_terminal_spends_the_run(self):
        """Intent: "3 successful runs per turn" (operator 2026-11-13)."""
        for _ in range(3):
            self.assertEqual(self.run_on(Terminal()), 0)
            self.ran_once()
        self.assertEqual(self.run_on(Terminal()), 2, "a fourth successful run was allowed")

    def test_piped_output_does_not_spend_the_run(self):
        """Intent: a run cut off before its verdict was read can be re-run."""
        self.assertEqual(self.run_on(io.StringIO()), 0)
        self.ran_once()
        self.assertEqual(self.run_on(Terminal()), 0, "the re-run after a piped run was refused")

    def test_a_crashed_run_does_not_spend_the_run(self):
        """Intent: "if its errors or is cancelled ... re-run to complete that should be allowed"."""
        with mock.patch.object(shape, "grade", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_on(Terminal())
        self.ran_once()
        self.assertEqual(self.run_on(Terminal()), 0, "the re-run after a crash was refused")

    def test_an_unreadable_ledger_falls_back_to_counting_every_run(self):
        """Intent: a broken ledger must never widen the budget."""
        for _ in range(3):
            self.ran_once()
        folder = self.ledger_dir / "check_response"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{self.path.stem}.runs.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_on(Terminal()), 2)


class AbandonedTurn(TranscriptCase):
    """A checkpoint restore leaves a turn that ran the check, produced
    no reply, and had its output thrown away. It must not end the arrears walk."""

    def test_abandoned_turn_does_not_hide_the_real_previous_reply(self):
        picked, _, _ = self.lookback(
            user("one"),
            invocation(),
            reply("m1", SHAPED_CLEAN),
            user("two - later abandoned by a checkpoint restore"),
            invocation(),
            user("two, resent - in progress"),
        )
        self.assertEqual(len(picked), 1)
        self.assertIn("Asked, done, result", picked[0][1])


def linked(kind: str, rid: str, parent: str | None, **data) -> str:
    """A record carrying id and parentId, the real transcript's linkage."""
    return json.dumps({"type": kind, "id": rid, "parentId": parent, "data": data})


class SplitTurns(TranscriptCase):
    """Shapes taken from real transcripts on 2026-09-27: a subagent's
    prompt is a user.message parented on the runSubagent call, and a mid-turn message
    is parented on whatever record came last rather than on assistant.turn_end."""

    def run_main(self, *lines: str) -> tuple[int, str]:
        path = self.transcript(*lines)
        out = io.StringIO()
        argv = ["check_response.py", "--previous", "--tool", "copilot", "--transcript", str(path)]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return cr.main(), out.getvalue()

    def subagent_turn(self, complete: bool = True) -> list[str]:
        lines = [
            linked("user.message", "u1", None, content="one"),
            linked("assistant.turn_start", "t1", "u1"),
            linked("assistant.message", "a1", "t1", messageId="m1",
                   content=SHAPED_CLEAN.split("## Premises")[0]),
            linked("tool.execution_start", "s1", "a1", toolName="runSubagent",
                   toolCallId="call1"),
            linked("user.message", "p1", "s1", content="You are an auditor. Read..."),
            linked("assistant.turn_start", "t2", "p1"),
            linked("assistant.message", "a2", "t2", messageId="sub",
                   content="Subagent findings, unshaped."),
            linked("assistant.turn_end", "e2", "a2"),
        ]
        if complete:
            lines.append(linked("tool.execution_complete", "c1", "e2", toolCallId="call1",
                                success=True))
        lines += [
            linked("assistant.message", "a3", "c1", messageId="m1",
                   content="## Premises" + SHAPED_CLEAN.split("## Premises")[1]),
            linked("assistant.turn_end", "e1", "a3"),
            linked("user.message", "u2", "e1", content="two - in progress"),
        ]
        return lines

    def test_subagent_prompt_does_not_split_the_turn(self):
        picked, _, _ = self.lookback(*self.subagent_turn())
        self.assertEqual(len(picked), 1)
        self.assertIn("Asked, done, result", picked[0][1])

    def test_subagent_answer_is_not_part_of_the_reply(self):
        picked, _, _ = self.lookback(*self.subagent_turn())
        self.assertNotIn("Subagent findings", picked[0][1])
        self.assertEqual(self.run_main(*self.subagent_turn())[0], 0)

    def test_unclosed_subagent_call_is_left_alone(self):
        """Hiding records on a guess could grade the wrong reply. A false FAIL cannot."""
        records = copilot.read_records(self.transcript(*self.subagent_turn(complete=False)))
        self.assertEqual(len(copilot.turn_bounds(records)), 3)

    def steered(self, steer_parent: str | None) -> list[str]:
        return [
            linked("user.message", "u1", None, content="one"),
            linked("assistant.turn_start", "t1", "u1"),
            invocation(),
            linked("assistant.message", "a1", "t1", messageId="m1",
                   content="Reading the file next:"),
            linked("tool.execution_complete", "c1", "a1", toolCallId="x", success=True),
            linked("user.message", "u2", steer_parent, content="oh and also check Y"),
            linked("assistant.turn_start", "t2", "u2"),
            linked("assistant.message", "a2", "t2", messageId="m2", content=SHAPED_CLEAN),
            linked("assistant.turn_end", "e2", "a2"),
            linked("user.message", "u3", "e2", content="three - in progress"),
        ]

    def test_slice_cut_short_by_a_steer_is_not_applicable(self):
        code, out = self.run_main(*self.steered("c1"))
        self.assertEqual(code, 0, out)
        self.assertIn("1 turn(s) back, UNGRADED: NOT APPLICABLE - cut short", out)

    def test_message_after_a_finished_turn_is_not_a_steer(self):
        records = copilot.read_records(self.transcript(*self.steered("c1")))
        self.assertFalse(copilot.cut_short(records, len(records) - 1))

    def test_steer_with_no_resolvable_parent_keeps_the_old_reading(self):
        code, out = self.run_main(*self.steered("not-in-this-transcript"))
        self.assertEqual(code, 1, out)
        self.assertEqual(copilot.cut_short_backs(copilot.read_records(
            self.transcript(*self.steered(None)))), set())


class RestartedSession(TranscriptCase):
    """Shape copied from the real transcript of 2026-09-30, lines 3981-4000:
    after VS Code restarted, the operator's message was never written, and the next
    record is an unparented assistant.message whose turn counter is back at 0."""

    def setUp(self):
        ledger = tempfile.TemporaryDirectory()
        self.addCleanup(ledger.cleanup)
        patcher = mock.patch.object(cr.tempfile, "gettempdir", return_value=ledger.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *lines: str) -> tuple[int, str]:
        path = self.transcript(*lines)
        out = Terminal()
        argv = ["check_response.py", "--previous", "--tool", "copilot", "--transcript", str(path)]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return cr.main(), out.getvalue()

    def evening(self) -> list[str]:
        return [
            linked("user.message", "u1", "e0", content="one"),
            linked("assistant.turn_start", "t0", "u1", turnId="0"),
            linked("assistant.turn_end", "e1", "t0", turnId="0"),
            linked("assistant.turn_start", "t1", "e1", turnId="1"),
            invocation(),
            linked("assistant.message", "a1", "t1", messageId="m1", content=SHAPED_CLEAN),
            linked("assistant.turn_end", "e2", "a1", turnId="1"),
            linked("assistant.turn_start", "t2", "e2", turnId="2"),
        ]

    def restarted(self) -> list[str]:
        return self.evening() + [
            linked("assistant.message", "a2", None, messageId="m2", content="Checking first:"),
            linked("assistant.turn_end", "e3", "a2", turnId="0"),
            linked("assistant.turn_start", "t3", "e3", turnId="1"),
        ]

    def test_turn_after_a_restart_is_a_new_turn(self):
        """Intent: the first run after a restart grades the reply before it
        rather than being refused as a second run of that reply's turn."""
        code, out = self.run_main(*self.restarted())
        self.assertNotIn("REFUSED", out)
        self.assertEqual(code, 0, out)
        self.assertIn("Compliance: PASS", out)

    def test_a_counter_reset_after_an_operator_message_is_not_an_extra_turn(self):
        """Intent: the control: every ordinary turn resets the counter, and
        must still count once."""
        records = copilot.read_records(self.transcript(
            *self.evening(),
            linked("user.message", "u2", "t2", content="two"),
            linked("assistant.turn_start", "t4", "u2", turnId="0"),
        ))
        self.assertEqual(len(copilot.turn_bounds(records)), 2)


class ExemptionNeedsTheCommand(TranscriptCase):
    """A reply exempted itself by opening with the Prime marker, whatever
    the operator had asked. A mid-session /prime writes its message - '/prime ' on
    2026-09-30, this session's transcript line 4922 - so the turn can vouch for it."""

    PRIME_REPORT = "Results from Prime\n\n| Repo | Branch |\n|---|---|\n| example-repo | main |\n"

    def run_main(self, *lines: str) -> tuple[int, str]:
        path = self.transcript(*lines)
        out = io.StringIO()
        argv = ["check_response.py", "--previous", "--tool", "copilot", "--transcript", str(path)]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return cr.main(), out.getvalue()

    def test_marker_in_an_ordinary_turn_is_graded(self):
        """Intent: a reply opening "Results from Prime" in a turn
        where /prime did not run is graded, and fails when it has no shape."""
        code, out = self.run_main(user("fix the bug please"), reply("m1", self.PRIME_REPORT),
                                  user("next - in progress"))
        self.assertNotIn("NOT APPLICABLE", out)
        self.assertEqual(code, 1, out)

    def test_real_prime_turn_is_not_applicable(self):
        """Intent: a genuine /prime report is still exempt."""
        code, out = self.run_main(user("/prime "), reply("m1", self.PRIME_REPORT),
                                  user("next - in progress"))
        self.assertEqual(code, shape.EXIT_NOT_APPLICABLE, out)

    def test_real_sitrep_turn_is_not_applicable(self):
        """Intent: the same for /sitrep, with an argument."""
        code, out = self.run_main(user("/sitrep -details"),
                                  reply("m1", "Results from Sitrep\n\nIN FLIGHT\n"),
                                  user("next - in progress"))
        self.assertEqual(code, shape.EXIT_NOT_APPLICABLE, out)


class ResurfacedItems(unittest.TestCase):
    """Spec rule 16: a re-surfaced item is answered by reference, so it needs an ID.
    One sat unanswered for six turns on 2026-09-28 under an entry with none."""

    def findings(self, section: str) -> list[str]:
        head, body = SHAPED_CLEAN.split("\n\n", 1)
        return shape.check(*shape.parse(f"{head}\n\n{section}\n{body}"))[0]

    def test_entry_with_a_question_id_passes(self):
        self.assertEqual(self.findings("## You missed this\n\n- Q1 File the ticket? Needs a yes.\n"), [])

    def test_entry_without_an_id_is_caught(self):
        found = self.findings("## You missed this\n\n- **File the ticket.** Needs a yes.\n")
        self.assertTrue(any("has no Q<n> ID" in f for f in found), found)

    def test_still_open_is_held_to_the_same_rule(self):
        found = self.findings("## Still open from last turn\n\n- DC1: the two-stage ticket.\n")
        self.assertTrue(any("stillopenfromlastturn" in f for f in found), found)

    def test_indented_detail_under_an_entry_is_not_an_entry(self):
        section = "## You missed this\n\n- Q1 File the ticket?\n  - It is the same bug class.\n"
        self.assertEqual(self.findings(section), [])


class EntryIds(unittest.TestCase):
    """Spec rule 9: every entity carries an ID. Items were found only by ID, so an
    entry without one was dropped, or merged into its neighbour, and the reply passed."""

    def findings(self, text: str) -> list[str]:
        return shape.check(*shape.parse(text))[0]

    def naming(self, found: list[str], entry: str) -> list[str]:
        return [f for f in found if entry in f and "no item ID" in f]

    def test_section_of_unided_entries_fails_naming_each(self):
        """Intent: any top-level entry without an ID fails, naming the line."""
        for bullet in ("-", "*"):
            with self.subTest(bullet=bullet):
                text = SHAPED_CLEAN + (f"\n## Not done, not checked\n\n{bullet} The push\n"
                                       f"{bullet} The rollout\n")
                found = self.findings(text)
                self.assertTrue(self.naming(found, "The push"), found)
                self.assertTrue(self.naming(found, "The rollout"), found)

    def test_unided_entry_after_an_item_fails_rather_than_merging(self):
        """Intent: the mixed list, where the entry vanished into its neighbour."""
        text = SHAPED_CLEAN + "\n## Not done, not checked\n\n- ND1 The push\n- The rollout\n"
        found = self.findings(text)
        self.assertTrue(self.naming(found, "The rollout"), found)

    def test_field_at_column_zero_fails(self):
        """Intent: fields must be indented; one at column 0 is an unIDed entry."""
        found = self.findings(SHAPED_CLEAN.replace("  - Done: yes", "- Done: yes"))
        self.assertTrue(self.naming(found, "Done: yes"), found)

    def test_question_entry_passes_in_any_section(self):
        """Intent: Q<n> is accepted as an entry ID in any section."""
        text = SHAPED_CLEAN + "\n## Not done, not checked\n\n- ND1 The push\n- Q1 Push it now?\n"
        self.assertEqual(self.findings(text), [])

    def test_indented_field_under_an_item_passes(self):
        """Intent: an indented line is a field, not an entry."""
        text = SHAPED_CLEAN + "\n## Not done, not checked\n\n- ND1 The push\n  - Why: review\n"
        self.assertEqual(self.findings(text), [])

    def test_list_lines_inside_a_fence_are_not_entries(self):
        """Intent: pasted output and diffs in a fence
        are evidence, not shape."""
        for fence in ("```", "~~~"):
            with self.subTest(fence=fence):
                text = SHAPED_CLEAN + (f"\n## Not done, not checked\n\n- ND1 The diff\n\n{fence}diff\n"
                                       f"- old line\n* pasted\n{fence}\n")
                self.assertEqual(self.findings(text), [])

    def test_an_entry_after_a_closed_fence_is_still_checked(self):
        """Intent: the rule resumes once the fence closes."""
        text = SHAPED_CLEAN + ("\n## Not done, not checked\n\n- ND1 The diff\n\n```\n- old line\n"
                               "```\n- The rollout\n")
        self.assertTrue(self.naming(self.findings(text), "The rollout"))

    def test_verdict_outside_the_three_words_fails_naming_it(self):
        """Intent: a premise written 'refuted' drew a finding for the wrong fix."""
        found = self.findings(SHAPED_CLEAN.replace("Verdict: confirmed", "Verdict: refuted"))
        self.assertTrue([f for f in found if "verdict" in f.lower() and "refuted" in f], found)

    def test_verdict_with_a_qualifier_passes(self):
        """Intent: a qualifier after a comma or full stop is allowed."""
        for verdict in ("confirmed, with a correction", "confirmed. Checked twice"):
            with self.subTest(verdict=verdict):
                text = SHAPED_CLEAN.replace("Verdict: confirmed", f"Verdict: {verdict}")
                self.assertEqual(self.findings(text), [])

    def test_logic_and_approach_verdicts_are_not_checked(self):
        """Intent: out of scope - Logic and approach verdict wording."""
        text = SHAPED_CLEAN + "\n## Logic and approach\n\n- LA1 One pass\n  - Verdict: holds\n"
        self.assertEqual(self.findings(text), [])


class WhichTranscript(unittest.TestCase):
    """The newest transcript across all workspaces is whichever session
    wrote last. The script must be told which one is its own, or refuse."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        patcher = mock.patch.object(copilot, "transcripts_base", return_value=self.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, workspace: str, session: str, *lines: str) -> Path:
        folder = self.base / workspace / "GitHub.copilot-chat" / "transcripts"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{session}.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_session_picks_its_own_transcript_not_the_newest(self):
        mine = self.write("ws1", "aaaaaaaa-1111", user("mine"))
        self.write("ws1", "bbbbbbbb-2222", user("parallel session, written later"))
        self.assertEqual(copilot.session_transcript("aaaaaaaa-1111"), mine)

    def test_nonce_finds_the_one_transcript_that_ran_it(self):
        mine = self.write("ws1", "aaaaaaaa-1111", user("x"),
                          invocation("python check_response.py --previous --nonce tok123abc"))
        self.write("ws2", "bbbbbbbb-2222", user("y"), invocation())
        self.assertEqual(copilot.nonce_transcript("tok123abc"), mine)

    def test_reused_nonce_identifies_nothing(self):
        cmd = "python check_response.py --previous --nonce tok123abc"
        self.write("ws1", "aaaaaaaa-1111", invocation(cmd))
        self.write("ws2", "bbbbbbbb-2222", invocation(cmd))
        self.assertIsNone(copilot.nonce_transcript("tok123abc"))

    def test_unsafe_identifiers_are_refused(self):
        self.assertIsNone(copilot.session_transcript("../../etc/passwd"))
        self.assertIsNone(copilot.session_transcript("*"))
        self.assertIsNone(copilot.nonce_transcript("a b"))

    def test_no_identifier_refuses_rather_than_guessing(self):
        self.write("ws1", "aaaaaaaa-1111", user("one"), reply("m1", SHAPED_CLEAN), user("two"))
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["check_response.py", "--previous", "--tool", "copilot"]), \
                mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=err):
            code = cr.main()
        self.assertEqual(code, 3)
        self.assertIn("no --session or --nonce", err.getvalue())

    def test_output_names_the_transcript_it_graded(self):
        self.write("ws1", "aaaaaaaa-1111", user("one"), reply("m1", SHAPED_CLEAN), user("two"))
        out = io.StringIO()
        argv = ["check_response.py", "--previous", "--tool", "copilot", "--session", "aaaaaaaa-1111"]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=io.StringIO()):
            cr.main()
        self.assertIn("transcript: ws1/aaaaaaaa-1111.jsonl", out.getvalue())


# Cursor records, shapes copied from the transcript of chat 33ff4d66 on 2026-10-09: an
# operator message wraps its text in <timestamp> and <user_query>; injected context is a
# user record with no <user_query>; a background-task notification is a user turn with
# fixed text; a turn ends with a turn_ended record.
NOTIFICATION = ("Briefly inform the user about the task result and perform any follow-up "
                "actions (if needed).")


def c_user(query: str) -> str:
    text = (f"<timestamp>Friday, Oct 9, 2026, 12:00 PM (UTC-7)</timestamp>\n\n"
            f"<user_query>\n{query}\n</user_query>")
    return json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": text}]}})


def c_notification() -> str:
    text = (f"<timestamp>Friday, Oct 9, 2026, 12:01 PM (UTC-7)</timestamp>\n\n"
            f"<user_query>{NOTIFICATION}</user_query>")
    return json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": text}]}})


def c_context() -> str:
    text = "<available_subagent_types>\n- explore: fast agent\n</available_subagent_types>"
    return json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": text}]}})


def c_shell(command: str) -> dict:
    return {"type": "tool_use", "name": "Shell", "input": {"command": command}}


def c_assistant(*blocks) -> str:
    content = [{"type": "text", "text": b} if isinstance(b, str) else b for b in blocks]
    return json.dumps({"role": "assistant", "message": {"content": content}})


C_ENDED = json.dumps({"type": "turn_ended", "status": "success"})
C_ABORTED = json.dumps({"type": "turn_ended", "status": "error", "error": "User aborted request"})
C_CHECK = "python .github/scripts/responses/check_response.py --previous"


class CursorTurns(TranscriptCase):
    """Cursor writes one long stream - progress notes between tool calls,
    then the reply - and a background task can add a turn that continues the last one."""

    def lookback(self, *lines: str):
        picked, runs, truncated = shape.lookback(cursor.turns(self.transcript(*lines)))
        return [(back, turn.text) for back, turn in picked], runs, truncated

    def test_the_reply_is_the_last_text_block(self):
        """Intent: grade the turn's last text block; earlier
        blocks are progress notes between tool calls."""
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant("Reading the file first.", c_shell("rg pattern")),
            c_assistant(SHAPED_CLEAN),
            C_ENDED,
            c_user("two - in progress"),
        )
        self.assertEqual(picked, [(0, SHAPED_CLEAN)])

    def test_injected_context_is_not_a_turn(self):
        """Line 94 of the source transcript: 12,054 characters of tool catalog, no query."""
        path = self.transcript(c_user("one"), c_context(), c_assistant(SHAPED_CLEAN), C_ENDED,
                               c_user("two - in progress"))
        self.assertEqual(len(cursor.turns(path)), 2)
        self.assertEqual(shape.lookback(cursor.turns(path))[0][0][1].text, SHAPED_CLEAN)

    def test_a_notification_turn_is_graded_and_the_walk_continues_past_it(self):
        """Intent: grade every turn that has text.
        Supersedes the earlier exemption on grading; that ruling's point stands on
        content - a background task "can trigger more response without it being treated
        as needing to recap what was posted before"."""
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant(SHAPED_NO_CHANGED_LINE),
            C_ENDED,
            c_notification(),
            c_assistant("That run passed."),
            C_ENDED,
            c_user("two - in progress"),
        )
        self.assertEqual(picked, [(0, "That run passed."), (1, SHAPED_NO_CHANGED_LINE)])

    def test_a_turn_that_ran_the_check_ends_the_walk(self):
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant(SHAPED_NO_CHANGED_LINE),
            C_ENDED,
            c_user("two"),
            c_assistant("Checking first.", c_shell(C_CHECK)),
            c_assistant(SHAPED_CLEAN),
            C_ENDED,
            c_user("three - in progress"),
        )
        self.assertEqual(picked, [(0, SHAPED_CLEAN)])

    def test_a_reply_written_in_a_notification_turn_that_ran_the_check_is_graded(self):
        """Intent: grade every turn that has
        text. Mirrors chat c6d9b720 at 10:59: the notification turn ran the check and wrote
        a shaped reply, and the walk stopped on it and graded nothing."""
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant(SHAPED_NO_CHANGED_LINE),
            C_ENDED,
            c_notification(),
            c_assistant("Checking first.", c_shell(C_CHECK)),
            c_assistant(SHAPED_CLEAN),
            C_ENDED,
            c_user("two - in progress"),
        )
        self.assertEqual(picked, [(0, SHAPED_CLEAN)])

    def test_the_reply_the_operator_answered_is_graded_past_later_notes(self):
        """Intent: grade every turn that has
        text. Mirrors chat c6d9b720 at 12:44: a shaped reply in a notification turn, then
        short notes, and the walk skipped all of them to grade an older operator reply."""
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant("Checking first.", c_shell(C_CHECK)),
            c_assistant(SHAPED_NO_CHANGED_LINE),
            C_ENDED,
            c_notification(),
            c_assistant(SHAPED_CLEAN),
            C_ENDED,
            c_notification(),
            c_assistant("That run passed."),
            C_ENDED,
            c_user("two - in progress"),
        )
        self.assertEqual(picked, [(0, "That run passed."), (1, SHAPED_CLEAN),
                                  (2, SHAPED_NO_CHANGED_LINE)])

    def test_an_aborted_turn_is_skipped_and_the_reply_before_it_is_graded(self):
        """Intent: an interrupted turn is skipped, not graded. Mirrors chat
        03dd7d4e records 177-179: the error record is followed by one orphan assistant
        record before the resend, and that orphan's text is narration, not a reply."""
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant(SHAPED_CLEAN),
            C_ENDED,
            c_user("two"),
            c_assistant("Reading the file first.", c_shell("rg pattern")),
            C_ABORTED,
            c_assistant("Since that was cut off, checking state.", c_shell("git status")),
            c_user("two, resent - in progress"),
        )
        self.assertEqual(picked, [(1, SHAPED_CLEAN)])

    def test_a_stray_abort_after_a_finished_turn_does_not_skip_it(self):
        """Intent: the turn's first end record decides.
        Mirrors chat c6d9b720 records 195-197: a shaped reply, success, then aborted."""
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant(SHAPED_CLEAN),
            C_ENDED,
            json.dumps({"type": "turn_ended", "status": "aborted",
                        "error": "User aborted/interrupted manually."}),
            c_user("two - in progress"),
        )
        self.assertEqual(picked, [(0, SHAPED_CLEAN)])

    def test_an_aborted_turn_that_ran_the_check_does_not_end_the_walk(self):
        """Intent: a skipped turn does not stop the arrears walk, even when
        its own run of the check happened before the abort."""
        picked, _, _ = self.lookback(
            c_user("one"),
            c_assistant(SHAPED_NO_CHANGED_LINE),
            C_ENDED,
            c_user("two"),
            c_assistant("Checking first.", c_shell(C_CHECK)),
            c_assistant("Now reading the file.", c_shell("rg pattern")),
            C_ABORTED,
            c_user("two, resent - in progress"),
        )
        self.assertEqual(picked, [(1, SHAPED_NO_CHANGED_LINE)])

    def test_a_turn_keeps_its_key_when_a_summary_drops_earlier_end_records(self):
        """Intent: key a turn by its position. Mirrors
        chat 7c843a66: summarizing rewrote the transcript without the turn_ended records
        of the turns before it, and every later record index moved back."""
        turns = [c_user("one"), c_assistant(SHAPED_CLEAN), C_ENDED,
                 c_notification(), c_assistant("ok"), C_ENDED,
                 c_user("two"), c_assistant(SHAPED_CLEAN), C_ENDED,
                 c_user("three - in progress")]
        before = [t.key for t in cursor.turns(self.transcript(*turns))]
        after = [t.key for t in cursor.turns(self.transcript(*[r for r in turns if r != C_ENDED]))]
        self.assertEqual(before, ["t0", "t1", "t2", "t3"])
        self.assertEqual(after, before)

    def test_the_query_is_read_from_inside_its_tags(self):
        """The wrapper puts a timestamp first, so a bare startswith('/sitrep') never matches."""
        turns = cursor.turns(self.transcript(c_user("/sitrep -details"),
                                             c_assistant("Results from Sitrep\n"), C_ENDED,
                                             c_user("next - in progress")))
        self.assertEqual(turns[0].invoked, "Sitrep")
        self.assertEqual([t.kind for t in turns], ["operator", "operator"])

    def test_a_notification_is_tagged_as_one(self):
        turns = cursor.turns(self.transcript(c_user("one"), c_assistant(SHAPED_CLEAN), C_ENDED,
                                             c_notification(), c_assistant("ok"), C_ENDED))
        self.assertEqual([t.kind for t in turns], ["operator", "notification"])


class CursorRealTranscript(unittest.TestCase):
    """Intent: "a actual record copided from real responses".

    tests/fixtures/cursor-transcript-2026-10-09.jsonl holds ten records of chat 33ff4d66,
    identical to its transcript lines 187, 190-192, 196-201, except that the ticket keys
    and the repository name are replaced with example identifiers: an operator turn with
    progress notes and a shaped reply, a background-task notification turn, then the next
    operator message. Five records of that span were left out because their tool inputs
    carry absolute machine paths, and this core is a public repository. The injected-context
    record has no real counterpart here for the same reason.
    """

    PATH = Path(__file__).resolve().parent / "fixtures" / "cursor-transcript-2026-10-09.jsonl"

    def test_turn_kinds(self):
        self.assertEqual([t.kind for t in cursor.turns(self.PATH)],
                         ["operator", "notification", "operator"])

    def test_the_notification_reply_is_graded_then_the_shaped_reply_not_the_notes(self):
        """Intent: grade every turn that has text,
        so the notification turn's reply comes first and the operator turn's reply, its
        progress notes excluded, follows as arrears."""
        picked, _, _ = shape.lookback(cursor.turns(self.PATH))
        self.assertEqual([back for back, _ in picked], [0, 1])
        self.assertTrue(picked[0][1].text.startswith("That notification is for"),
                        picked[0][1].text[:80])
        self.assertTrue(picked[1][1].text.startswith("Mode: Planning\nNeeds from you: 3 decisions"),
                        picked[1][1].text[:80])

    def test_the_entry_point_returns_a_verdict(self):
        """Done when - "returns a verdict for the previous reply": PASS or FAIL,
        never UNKNOWN or NOT APPLICABLE."""
        ledger = tempfile.TemporaryDirectory()
        self.addCleanup(ledger.cleanup)
        out = io.StringIO()
        argv = ["check_response.py", "--previous", "--tool", "cursor", "--transcript", str(self.PATH)]
        with mock.patch.object(cr.tempfile, "gettempdir", return_value=ledger.name), \
                mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=io.StringIO()):
            code = cr.main()
        self.assertIn(code, (0, 1), out.getvalue())
        self.assertRegex(out.getvalue(), r"Compliance: (PASS|FAIL)")


class CursorLocate(unittest.TestCase):
    """The same rule in Cursor: CURSOR_CONVERSATION_ID names the chat exactly, so
    nothing is guessed. Verified 2026-10-09: it equals the transcript's uuid."""

    UUID = "33ff4d66-7889-49d3-abca-3aae47ade31b"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        patcher = mock.patch.object(cursor, "projects_base", return_value=self.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, project: str, uuid: str) -> Path:
        folder = self.base / project / "agent-transcripts" / uuid
        folder.mkdir(parents=True)
        path = folder / f"{uuid}.jsonl"
        path.write_text(c_user("x") + "\n", encoding="utf-8")
        return path

    def args(self, session: str | None = None):
        return argparse.Namespace(session=session, nonce=None)

    def test_the_conversation_id_finds_its_transcript(self):
        mine = self.write("c-ws-one", self.UUID)
        self.write("c-ws-two", "aaaaaaaa-0000-0000-0000-000000000000")
        self.assertEqual(cursor.locate(self.args(), {"CURSOR_CONVERSATION_ID": self.UUID}), mine)

    def test_an_explicit_session_overrides_the_environment(self):
        mine = self.write("c-ws", "bbbbbbbb-0000-0000-0000-000000000000")
        self.write("c-ws", self.UUID)
        found = cursor.locate(self.args("bbbbbbbb-0000-0000-0000-000000000000"),
                              {"CURSOR_CONVERSATION_ID": self.UUID})
        self.assertEqual(found, mine)

    def test_no_id_identifies_nothing(self):
        self.write("c-ws", self.UUID)
        self.assertIsNone(cursor.locate(self.args(), {}))

    def test_unsafe_identifiers_are_refused(self):
        for bad in ("../../etc/passwd", "*", ""):
            with self.subTest(session=bad):
                self.assertIsNone(cursor.locate(self.args(), {"CURSOR_CONVERSATION_ID": bad}))

    def test_an_unknown_id_identifies_nothing(self):
        self.assertIsNone(cursor.locate(self.args(), {"CURSOR_CONVERSATION_ID": self.UUID}))

    def first_reply(self, *extra: str) -> tuple[int, str, str]:
        """A first turn: this chat has no transcript yet. The workspace folder is found from
        the working directory, which C:/ws/one maps to as c-ws-one."""
        out, err = io.StringIO(), io.StringIO()
        env = {"CURSOR_AGENT": "1", "CURSOR_CONVERSATION_ID": self.UUID}
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(cursor, "cwd", return_value=Path("C:/ws/one")), \
                mock.patch.object(sys, "argv", ["check_response.py", "--previous", *extra]), \
                mock.patch("sys.stdout", new=out), mock.patch("sys.stderr", new=err):
            return cr.main(), out.getvalue(), err.getvalue()

    def test_a_first_reply_with_no_transcript_yet_is_not_applicable(self):
        """Intent: NOT APPLICABLE when the id came
        from CURSOR_CONVERSATION_ID, is well-formed, and other transcripts exist in the same
        workspace's transcript directory. Seen live 2026-10-22 on chat 7c843a66's first reply."""
        self.write("c-ws-one", "aaaaaaaa-0000-0000-0000-000000000000")
        code, out, err = self.first_reply()
        self.assertEqual(code, 4, out + err)
        self.assertIn("NOT APPLICABLE", out)

    def test_a_workspace_with_no_other_transcripts_stays_unknown(self):
        """Intent: "otherwise UNKNOWN as now". Another workspace's
        transcripts say nothing about whether this one is being written."""
        self.write("c-ws-two", "aaaaaaaa-0000-0000-0000-000000000000")
        code, _, err = self.first_reply()
        self.assertEqual(code, 3)
        self.assertIn("UNKNOWN", err)

    def test_an_explicit_session_with_no_transcript_stays_unknown(self):
        """Intent: only an id from CURSOR_CONVERSATION_ID qualifies; a
        typed --session that matches nothing is more likely wrong than new."""
        self.write("c-ws-one", "aaaaaaaa-0000-0000-0000-000000000000")
        code, _, err = self.first_reply("--session", self.UUID)
        self.assertEqual(code, 3)
        self.assertIn("UNKNOWN", err)


class ToolDetection(unittest.TestCase):
    """The entry point picks its adapter, and refuses rather than guesses.
    Cursor also sets VSCODE_* variables, so those alone must not mean Copilot."""

    def test_cursor(self):
        self.assertEqual(cr.detect({"CURSOR_AGENT": "1", "VSCODE_PID": "1"}), "cursor")

    def test_copilot(self):
        self.assertEqual(cr.detect({"VSCODE_TARGET_SESSION_LOG": r"C:\x\aaaaaaaa-1111"}), "copilot")

    def test_neither_is_none(self):
        self.assertIsNone(cr.detect({"VSCODE_PID": "1"}))

    def test_both_is_none(self):
        self.assertIsNone(cr.detect({"CURSOR_AGENT": "1",
                                     "VSCODE_TARGET_SESSION_LOG": r"C:\x\aaaaaaaa-1111"}))

    def test_no_tool_refuses_rather_than_guessing(self):
        err = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(sys, "argv", ["check_response.py", "--previous"]), \
                mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=err):
            code = cr.main()
        self.assertEqual(code, 3)
        self.assertIn("--tool", err.getvalue())


class CursorMain(TranscriptCase):
    """The entry point end to end on a Cursor transcript."""

    def setUp(self):
        ledger = tempfile.TemporaryDirectory()
        self.addCleanup(ledger.cleanup)
        patcher = mock.patch.object(cr.tempfile, "gettempdir", return_value=ledger.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, path: Path, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["check_response.py", "--tool", "cursor", "--transcript", str(path), *extra]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=err):
            return cr.main(), out.getvalue(), err.getvalue()

    def clean(self) -> Path:
        return self.transcript(c_user("one"), c_assistant("Looking.", c_shell("rg x")),
                               c_assistant(SHAPED_CLEAN), C_ENDED, c_user("two - in progress"))

    def test_the_previous_reply_is_graded(self):
        code, out, _ = self.run_main(self.clean(), "--previous")
        self.assertEqual(code, 0, out)
        self.assertIn("Compliance: PASS", out)

    def test_a_failing_previous_reply_fails(self):
        path = self.transcript(c_user("one"), c_assistant(SHAPED_NO_CHANGED_LINE), C_ENDED,
                               c_user("two - in progress"))
        self.assertEqual(self.run_main(path, "--previous")[0], 1)

    def test_in_flight_grading_refuses(self):
        """The current turn is not in the transcript until it ends (2026-10-09: the file
        stayed at 176 lines across three tool calls), so there is nothing to grade."""
        code, _, err = self.run_main(self.clean())
        self.assertEqual(code, 3)
        self.assertIn("--previous", err)

    def test_three_graded_runs_per_turn_without_a_terminal(self):
        """Intent: "3 successful runs per turn" (operator 2026-11-13). Cursor's shell
        is never a TTY, and the current turn's runs are not in the transcript, so the
        ledger counts."""
        path = self.clean()
        for _ in range(3):
            self.assertEqual(self.run_main(path, "--previous")[0], 0)
        code, out, _ = self.run_main(path, "--previous")
        self.assertEqual(code, 2, out)
        self.assertIn("REFUSED", out)

    def test_an_index_key_left_in_the_ledger_is_not_this_turns_run(self):
        """Intent: ledgers written before turns were keyed by position hold
        record-index keys, and index 1 here is the previous turn's start, not this turn."""
        path = self.clean()
        cr.record_run(path, "1", "started")
        cr.record_run(path, "1", "delivered")
        code, out, _ = self.run_main(path, "--previous")
        self.assertEqual(code, 0, out)
        self.assertNotIn("REFUSED", out)

    def denied(self) -> Path:
        """Turn 0 ran the check and delivered; turn 1 matched the command, but nothing ran."""
        path = self.transcript(c_user("one"), c_assistant("Checking.", c_shell(C_CHECK)),
                               c_assistant(SHAPED_NO_CHANGED_LINE), C_ENDED,
                               c_user("two"), c_assistant("Checking.", c_shell(C_CHECK)),
                               c_assistant(SHAPED_CLEAN), C_ENDED,
                               c_user("three - in progress"))
        return path

    def test_a_matched_but_undelivered_run_does_not_end_the_walk(self):
        """Intent: a past turn counts as checked
        only if the ledger shows a delivery. Turn 1's command was denied, so the reply
        before it was never graded and is collected as arrears."""
        path = self.denied()
        cr.record_run(path, "t0", "started")
        cr.record_run(path, "t0", "delivered")
        code, out, _ = self.run_main(path, "--previous")
        self.assertIn("1 in arrears", out)
        self.assertIn("1 turn(s) back, UNGRADED", out)
        self.assertEqual(code, 1, out)

    def test_a_turn_whose_only_run_was_unknown_does_not_end_the_walk(self):
        """Intent: a run that produced no verdict does not count, in the walk
        as in the run limit. Turn 1's run started and returned UNKNOWN, so it recorded
        no delivery, and the reply before it was never graded."""
        path = self.denied()
        cr.record_run(path, "t0", "started")
        cr.record_run(path, "t0", "delivered")
        cr.record_run(path, "t1", "started")
        code, out, _ = self.run_main(path, "--previous")
        self.assertIn("1 in arrears", out)
        self.assertEqual(code, 1, out)

    def test_turns_older_than_the_ledger_fall_back_to_the_command_match(self):
        """Characterisation: with no position key
        in the ledger - wiped, or written before position keys - nothing is known from it,
        and the walk stops at the command match as it always has."""
        code, out, _ = self.run_main(self.denied(), "--previous")
        self.assertNotIn("arrears", out)
        self.assertEqual(code, 0, out)

    def behind(self) -> Path:
        """The previous turn ran the check and ended; the current turn is not on disk."""
        path = self.transcript(c_user("one"), c_assistant(SHAPED_NO_CHANGED_LINE), C_ENDED,
                               c_user("two"), c_assistant("Checking.", c_shell(C_CHECK)),
                               c_assistant(SHAPED_CLEAN), C_ENDED)
        cr.record_run(path, "t1", "started")
        cr.record_run(path, "t1", "delivered")
        return path

    def test_a_transcript_behind_the_current_turn_is_reported_not_refused(self):
        """Intent: re-read for up to 5 seconds,
        then a distinct result that does not spend the turn's run. Mirrors chat c6d9b720
        at 12:53: the previous turn's delivered run was counted as this turn's."""
        path = self.behind()
        with mock.patch("time.sleep"):
            code, out, err = self.run_main(path, "--previous")
        self.assertEqual(code, 3, out + err)
        self.assertIn("BEHIND", err)
        self.assertNotIn("REFUSED", out)
        self.assertEqual(cr.read_run_ledger(path), {"t1": {"started": 1, "delivered": 1}})

    def test_a_transcript_ending_at_an_aborted_turns_orphan_record_is_behind(self):
        """Intent: mirrors chat 7c843a66 records 176-178 on 2026-10-26: the
        previous turn ran the check and was aborted, Cursor wrote one assistant record
        after the error, and the resend's message was not on disk. The check took the
        aborted turn as current and refused on its delivered run."""
        path = self.transcript(c_user("one"), c_assistant(SHAPED_NO_CHANGED_LINE), C_ENDED,
                               c_user("two"), c_assistant("Checking.", c_shell(C_CHECK)),
                               c_assistant("Editing the ticket.", c_shell("rg x")), C_ABORTED,
                               c_assistant(c_shell("rg y")))
        cr.record_run(path, "t1", "started")
        cr.record_run(path, "t1", "delivered")
        with mock.patch("time.sleep"):
            code, out, err = self.run_main(path, "--previous")
        self.assertEqual(code, 3, out + err)
        self.assertIn("BEHIND", err)
        self.assertNotIn("REFUSED", out)

    def test_a_transcript_that_catches_up_within_the_wait_is_graded(self):
        """Intent: the bounded re-read grades the
        reply when the current turn's message lands during the wait."""
        path = self.behind()

        def lands(_seconds):
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(c_user("three - in progress") + "\n")

        with mock.patch("time.sleep", side_effect=lands):
            code, out, err = self.run_main(path, "--previous")
        self.assertEqual(code, 0, out + err)
        self.assertIn("Compliance: PASS", out)

    def test_a_missing_conversation_id_refuses(self):
        err = io.StringIO()
        with mock.patch.dict("os.environ", {"CURSOR_AGENT": "1"}, clear=True), \
                mock.patch.object(sys, "argv", ["check_response.py", "--previous"]), \
                mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=err):
            code = cr.main()
        self.assertEqual(code, 3)
        self.assertIn("CURSOR_CONVERSATION_ID", err.getvalue())


class CondensedShape(TranscriptCase):
    """The condensed shape is the default; the full shape is inferred from its headings."""

    def setUp(self):
        ledger = tempfile.TemporaryDirectory()
        self.addCleanup(ledger.cleanup)
        patcher = mock.patch.object(cr.tempfile, "gettempdir", return_value=ledger.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_previous(self, path: Path) -> tuple[int, str]:
        out = io.StringIO()
        argv = ["check_response.py", "--tool", "cursor", "--transcript", str(path), "--previous"]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return cr.main(), out.getvalue()

    def previous_clean(self) -> Path:
        return self.transcript(c_user("one"), c_assistant(SHAPED_CLEAN), C_ENDED,
                               c_user("two - in progress"))

    PARAGRAPH = (
        'The live state matches the seed: `git status -sb` printed "## main...origin/main", '
        "and the gate passed the draft."
    )
    RECOMMENDED_NEXT = (
        "## Recommended next\n\n"
        "- R1 Once OS1's output is back, decide whether example-1 can run on that host\n"
        "  - Reasoning: the probe is the only unknown\n\n"
    )

    def findings(self, text: str) -> list[str]:
        return shape.check(*shape.parse(text))[0]

    def test_condensed_reply_passes(self):
        self.assertEqual(self.findings(CONDENSED_CLEAN), [])

    def test_missing_summary_fails(self):
        text = CONDENSED_CLEAN.replace(f"## Summary\n\n{self.PARAGRAPH}\n\n", "")
        self.assertIn("condensed: section missing: summary", self.findings(text))

    def test_missing_recommended_next_fails(self):
        text = CONDENSED_CLEAN.replace(self.RECOMMENDED_NEXT, "")
        self.assertIn("condensed: section missing: recommendednext", self.findings(text))

    def test_missing_came_up_fails(self):
        text = CONDENSED_CLEAN.replace("## Came up while doing it\n\nNone.\n", "")
        self.assertIn("condensed: section missing: cameupwhiledoingit", self.findings(text))

    def test_empty_came_up_fails(self):
        text = CONDENSED_CLEAN.replace("\nNone.\n", "\n")
        self.assertIn(
            "cameupwhiledoingit: empty - list an item or write 'None.'", self.findings(text)
        )

    def test_summary_without_a_pointer_fails(self):
        text = CONDENSED_CLEAN.replace(self.PARAGRAPH, "The live state matches the seed.")
        found = self.findings(text)
        self.assertTrue(
            any(f.startswith("summary: no pointer a reader could follow") for f in found), found
        )

    def test_summary_of_two_paragraphs_fails(self):
        text = CONDENSED_CLEAN.replace(
            self.PARAGRAPH,
            self.PARAGRAPH + '\n\nA second paragraph quotes "the gate passed the draft".',
        )
        self.assertIn("summary: 2 paragraphs, exactly 1 allowed", self.findings(text))

    def test_summary_wrapped_over_two_lines_passes(self):
        text = CONDENSED_CLEAN.replace(
            self.PARAGRAPH, self.PARAGRAPH.replace(", and the gate", ",\nand the gate")
        )
        self.assertEqual(self.findings(text), [])

    def test_summary_none_this_turn_passes(self):
        text = CONDENSED_CLEAN.replace(self.PARAGRAPH, "None this turn.")
        self.assertEqual(self.findings(text), [])

    def test_operator_step_is_an_item(self):
        steps = shape.parse(CONDENSED_CLEAN)[1]["operatorsteps"]
        self.assertEqual(len(steps), 1)
        self.assertTrue(steps[0]["title"].startswith("OS1"), steps)

    def test_decision_with_no_recommended_option_fails(self):
        text = CONDENSED_CLEAN.replace(" (recommended)", "")
        self.assertIn(
            "decisions: 'DC1 Pick the next ticket' marks 0 options recommended, "
            "exactly one is required",
            self.findings(text),
        )

    def test_decision_with_two_recommended_options_fails(self):
        text = CONDENSED_CLEAN.replace("b. example-2 first", "b. example-2 first (recommended)")
        self.assertIn(
            "decisions: 'DC1 Pick the next ticket' marks 2 options recommended, "
            "exactly one is required",
            self.findings(text),
        )

    def test_half_opened_block_is_graded_full(self):
        claim = (
            "\n## My claims\n\n"
            "- C1 The probe exists\n"
            "  - Verdict: confirmed\n"
            "  - Evidence for: `ls tools/probe.py` printed the file\n"
            "  - Evidence against: none\n"
            "  - Would have falsified it: the file missing\n"
            "  - Looked for it: yes\n"
        )
        found = self.findings(CONDENSED_CLEAN + claim)
        self.assertIn("section missing for planning mode: yourpremises", found)

    def test_full_reply_decision_needs_one_recommended(self):
        decision = (
            "\n## Decisions and clarifications\n\n"
            "- DC1 Pick the next ticket\n"
            "  - Use case: decides what the next session builds\n"
            "  - Options:\n"
            "    - a. example-1 first\n"
            "    - b. example-2 first\n"
        )
        found = self.findings(SHAPED_CLEAN + decision)
        self.assertIn(
            "decisions: 'DC1 Pick the next ticket' marks 0 options recommended, "
            "exactly one is required",
            found,
        )

    def test_grade_line_names_the_shape(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", new=out):
            shape.grade("previous reply", CONDENSED_CLEAN)
        self.assertIn("shape=condensed", out.getvalue())
        self.assertIn("Compliance: PASS", out.getvalue())

    WITHOUT_LOGIC = CONDENSED_CLEAN.replace(
        "## Logic and approach\n\n- LA1 Rank by what unblocks the most work\n"
        "  - Verdict: holds, because example-2 waits on example-1\n\n", "")

    def test_logic_and_approach_does_not_make_a_reply_full(self):
        """Design replies keep this section (operator 2026-11-13); it must not flip the shape."""
        header, sections = shape.parse(CONDENSED_CLEAN)
        self.assertIn("logicandapproach", sections)
        self.assertEqual(shape.shape_of(sections), "condensed")
        self.assertEqual(shape.check(header, sections)[0], [])

    def test_the_fixture_without_logic_really_lacks_it(self):
        self.assertNotIn("logicandapproach", shape.parse(self.WITHOUT_LOGIC)[1])

    def test_planning_mode_requires_logic_and_approach(self):
        """Operator 2026-11-13: a visible FAIL the agent can judge is better than no check."""
        self.assertIn("condensed: section missing for planning mode: logicandapproach",
                      self.findings(self.WITHOUT_LOGIC))

    def test_planning_plus_execution_requires_logic_and_approach(self):
        text = self.WITHOUT_LOGIC.replace("Mode: Planning", "Mode: Planning + Execution")
        self.assertIn("condensed: section missing for planning mode: logicandapproach",
                      self.findings(text))

    def test_execution_mode_does_not_require_logic_and_approach(self):
        text = self.WITHOUT_LOGIC.replace("Mode: Planning", "Mode: Execution")
        self.assertEqual(self.findings(text), [])

    def test_logic_and_approach_entry_still_needs_an_id(self):
        text = CONDENSED_CLEAN.replace("- LA1 Rank", "- Rank")
        found = self.findings(text)
        self.assertTrue(any("no item ID" in f for f in found), found)

    def test_grade_prints_the_ledger_file_line(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", new=out):
            shape.grade("previous reply", CONDENSED_CLEAN)
        self.assertIn("Ledger file: not checked", out.getvalue())
        self.assertNotIn("Ledger file: PASS", out.getvalue())

    def test_a_failing_reply_still_prints_the_ledger_file_line(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", new=out):
            shape.grade("previous reply", CONDENSED_CLEAN.replace("## Summary\n", ""))
        self.assertIn("Compliance: FAIL", out.getvalue())
        self.assertIn("Ledger file: not checked", out.getvalue())

    def test_previous_allows_three_runs(self):
        path = self.previous_clean()
        self.assertEqual(self.run_previous(path)[0], 0)
        self.assertEqual(self.run_previous(path)[0], 0)
        code, out = self.run_previous(path)
        self.assertEqual(code, 0, out)
        self.assertNotIn("REFUSED", out)
        self.assertIn("run 3 of 3", out)

    def test_previous_refuses_the_fourth(self):
        path = self.previous_clean()
        for _ in range(3):
            self.assertEqual(self.run_previous(path)[0], 0)
        code, out = self.run_previous(path)
        self.assertEqual(code, 2, out)
        self.assertIn("REFUSED", out)
        self.assertIn("limit is 3", out)


# A Claude Code transcript is one JSONL line per content block. These builders write the
# observed record format with made-up text: an operator prompt is a user record with a
# string and origin.kind "human", a tool result is a user record with a tool_result list,
# and injected context is an attachment or an isMeta user record.
K_MARKER = "=== REPLY STARTS HERE ==="
K_CHECK = "python .github/scripts/responses/check_response.py --previous"
K_SESSION = "11111111-2222-3333-4444-555555555555"
K_OTHER = "66666666-7777-8888-9999-000000000000"


def k_user(text: str, kind: str = "human") -> str:
    return json.dumps({"type": "user", "uuid": "u-" + text[:8], "isSidechain": False,
                       "origin": {"kind": kind}, "promptId": "p-1", "turnPosition": 1,
                       "message": {"role": "user", "content": text}})


def k_result(text: str = "ok") -> str:
    return json.dumps({"type": "user", "uuid": "r-1", "isSidechain": False,
                       "toolUseResult": {"stdout": text},
                       "message": {"role": "user", "content": [
                           {"type": "tool_result", "tool_use_id": "t-1", "content": text}]}})


def k_attachment(kind: str = "queued_command") -> str:
    return json.dumps({"type": "attachment", "uuid": "a-1", "isSidechain": False,
                       "attachment": {"type": kind, "prompt": "a message sent mid-turn"}})


def k_meta() -> str:
    return json.dumps({"type": "user", "uuid": "m-1", "isMeta": True, "isSidechain": False,
                       "message": {"role": "user", "content": "injected context"}})


def k_block(block: dict, stop: str | None = None, sidechain: bool = False) -> str:
    return json.dumps({"type": "assistant", "uuid": "b-1", "isSidechain": sidechain,
                       "requestId": "req-1", "apiBlockIndex": 0,
                       "message": {"id": "msg-1", "role": "assistant", "content": [block],
                                   "stop_reason": stop}})


def k_text(text: str, stop: str | None = None, sidechain: bool = False) -> str:
    return k_block({"type": "text", "text": text}, stop, sidechain)


def k_final(text: str) -> str:
    return k_text(text, "end_turn")


def k_tool(command: str = "rg x", name: str = "Bash") -> str:
    return k_block({"type": "tool_use", "id": "t-1", "name": name, "input": {"command": command}},
                   "tool_use")


K_METADATA = json.dumps({"type": "last-prompt", "lastPrompt": "made-up"})


class ClaudeCodeAdapter(TranscriptCase):
    def kturns(self, *lines: str) -> list[shape.Turn]:
        return claude.turns(self.transcript(*lines))

    def test_the_interface_matches_the_other_adapters(self):
        self.assertEqual(claude.NAME, "claude")
        self.assertIs(claude.IN_FLIGHT, True)
        self.assertIs(claude.LEDGER_COUNTS, False)
        self.assertIs(cr.ADAPTERS["claude"], claude)
        path = self.transcript(k_user("one"))
        self.assertFalse(claude.behind(path))
        self.assertFalse(claude.first_turn(argparse.Namespace(session=None), {}))

    def test_detection_is_claudecode_equal_to_one(self):
        self.assertEqual(cr.detect({"CLAUDECODE": "1"}), "claude")
        self.assertIsNone(cr.detect({"CLAUDECODE": "0"}))
        self.assertIsNone(cr.detect({"CLAUDECODE": ""}))
        self.assertIsNone(cr.detect({}))

    def test_a_second_tools_marker_makes_detection_refuse(self):
        self.assertIsNone(cr.detect({"CLAUDECODE": "1", "CURSOR_AGENT": "1"}))

    def test_identity_comes_from_the_variable(self):
        args = argparse.Namespace(session=None)
        self.assertEqual(claude.identity(args, {"CLAUDE_CODE_SESSION_ID": K_SESSION}), K_SESSION)

    def test_a_session_argument_overrides_the_variable(self):
        args = argparse.Namespace(session=K_OTHER)
        self.assertEqual(claude.identity(args, {"CLAUDE_CODE_SESSION_ID": K_SESSION}), K_OTHER)

    def test_no_identity_is_none_and_never_the_newest_transcript(self):
        self.assertIsNone(claude.identity(argparse.Namespace(session=None), {}))

    def test_the_entry_point_refuses_without_an_identity(self):
        err = io.StringIO()
        with mock.patch.dict("os.environ", {"CLAUDECODE": "1"}, clear=True), \
                mock.patch.object(sys, "argv", ["check_response.py", "--previous"]), \
                mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=err):
            code = cr.main()
        self.assertEqual(code, 3)
        self.assertIn("CLAUDE_CODE_SESSION_ID", err.getvalue())


class ClaudeCodeLocate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        patcher = mock.patch.object(claude, "projects_base", return_value=self.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, project: str, session: str, *parts: str) -> Path:
        folder = self.base.joinpath(project, *parts)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{session}.jsonl"
        path.write_text(k_user("x") + "\n", encoding="utf-8")
        return path

    def args(self, session: str | None = None):
        return argparse.Namespace(session=session, nonce=None)

    def test_exactly_one_match_across_project_folders_is_found(self):
        mine = self.write("proj-one", K_SESSION)
        self.write("proj-two", K_OTHER)
        found = claude.locate(self.args(), {"CLAUDE_CODE_SESSION_ID": K_SESSION})
        self.assertEqual(found, mine)

    def test_two_matches_are_refused_naming_both(self):
        first = self.write("proj-one", K_SESSION)
        second = self.write("proj-two", K_SESSION)
        err = io.StringIO()
        with mock.patch("sys.stderr", new=err):
            found = claude.locate(self.args(), {"CLAUDE_CODE_SESSION_ID": K_SESSION})
        self.assertIsNone(found)
        self.assertIn(str(first), err.getvalue())
        self.assertIn(str(second), err.getvalue())

    def test_no_match_is_none(self):
        self.write("proj-one", K_OTHER)
        self.assertIsNone(claude.locate(self.args(), {"CLAUDE_CODE_SESSION_ID": K_SESSION}))

    def test_a_session_argument_overrides_the_variable(self):
        self.write("proj-one", K_SESSION)
        mine = self.write("proj-two", K_OTHER)
        self.assertEqual(claude.locate(self.args(K_OTHER), {"CLAUDE_CODE_SESSION_ID": K_SESSION}),
                         mine)

    def test_a_subagent_transcript_is_never_a_match(self):
        mine = self.write("proj-one", K_SESSION)
        self.write("proj-one", "agent-abc123", K_SESSION, "subagents")
        self.write("proj-two", K_SESSION, "nested")
        self.assertEqual(claude.locate(self.args(), {"CLAUDE_CODE_SESSION_ID": K_SESSION}), mine)

    def test_unsafe_identifiers_are_refused(self):
        self.write("proj-one", K_SESSION)
        for bad in ("../../etc/passwd", "*", ""):
            with self.subTest(session=bad):
                self.assertIsNone(claude.locate(self.args(), {"CLAUDE_CODE_SESSION_ID": bad}))


class ClaudeCodeTurns(TranscriptCase):
    def kturns(self, *lines: str) -> list[shape.Turn]:
        return claude.turns(self.transcript(*lines))

    def test_tool_results_and_attachments_do_not_start_a_turn(self):
        turns = self.kturns(
            K_METADATA, k_user("one"), k_attachment("environment"),
            k_text("Looking."), k_tool(), k_result(),
            k_attachment("queued_command"), k_meta(), k_text("Still looking."), k_tool(), k_result(),
            k_final("done one"),
            k_user("two"), k_final("done two"))
        self.assertEqual([t.kind for t in turns], [shape.OPERATOR, shape.OPERATOR])
        self.assertEqual([t.key for t in turns], ["t0", "t1"])

    def test_a_tool_result_alone_never_opens_a_turn(self):
        turns = self.kturns(k_user("one"), k_tool(), k_result(), k_final("done"))
        self.assertEqual(len(turns), 1)

    def test_a_mid_turn_queued_command_does_not_start_a_turn(self):
        turns = self.kturns(k_user("one"), k_text("Working."), k_tool(), k_result(),
                            k_attachment("queued_command"), k_tool(), k_result(), k_final("done"))
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].last, "done")

    def test_a_background_task_opens_a_notification_turn(self):
        turns = self.kturns(k_user("one"), k_final("done one"),
                            k_user("<task-notification>finished</task-notification>",
                                   kind="task-notification"),
                            k_final("the task finished"),
                            k_user("two"))
        self.assertEqual([t.kind for t in turns],
                         [shape.OPERATOR, shape.NOTIFICATION, shape.OPERATOR])
        self.assertEqual(turns[1].last, "the task finished")

    def test_a_peer_message_is_not_a_turn(self):
        self.assertEqual(len(self.kturns(k_user("one"), k_user("hello", kind="peer"),
                                         k_final("done"))), 1)

    def test_a_turn_without_an_end_turn_text_is_cut_short_and_skipped(self):
        turns = self.kturns(k_user("one"), k_text("Starting."), k_tool(),
                            k_user("two"), k_final(CONDENSED_CLEAN),
                            k_user("three - in progress"))
        self.assertTrue(turns[0].cut_short)
        self.assertEqual(turns[0].text, "")
        self.assertFalse(turns[1].cut_short)
        picked, _, _ = shape.lookback(turns)
        self.assertEqual([(back, t.key) for back, t in picked], [(0, "t1")])

    def test_a_cut_short_previous_turn_is_walked_past_to_the_reply_before(self):
        turns = self.kturns(k_user("one"), k_final(CONDENSED_CLEAN),
                            k_user("two"), k_text("Starting."), k_tool(),
                            k_user("three - in progress"))
        picked, _, _ = shape.lookback(turns)
        self.assertEqual([(back, t.key) for back, t in picked], [(1, "t0")])

    def test_a_bash_or_powershell_invocation_counts_as_a_run(self):
        turns = self.kturns(k_user("one"), k_tool(K_CHECK), k_result(),
                            k_tool(K_CHECK, name="PowerShell"), k_result(),
                            k_tool("rg check_response"), k_result(), k_final("done"))
        self.assertEqual(turns[0].runs, 2)

    def test_a_subagent_record_in_the_file_is_ignored(self):
        turns = self.kturns(k_user("one"), k_text("side", "end_turn", sidechain=True),
                            k_tool(K_CHECK), k_final("done"))
        self.assertEqual(turns[0].last, "done")

    def test_a_session_command_is_recorded_as_invoked(self):
        self.assertEqual(self.kturns(k_user("/sitrep"), k_final("x"))[0].invoked, "Sitrep")

    def test_an_empty_transcript_still_has_a_current_turn(self):
        self.assertEqual(len(self.kturns(K_METADATA)), 1)


class ClaudeCodeReply(TranscriptCase):
    def kturns(self, *lines: str) -> list[shape.Turn]:
        return claude.turns(self.transcript(*lines))

    def test_the_reply_starts_at_the_marker_and_runs_to_the_end(self):
        turns = self.kturns(
            k_user("one"), k_text("Checking the file."), k_tool(), k_result(),
            k_text("Found it.\n" + K_MARKER + "\nMode: Execution"),
            k_text("Needs from you: nothing"),
            k_final("Changed: nothing"))
        text = turns[0].last
        self.assertTrue(text.startswith(K_MARKER))
        self.assertNotIn("Found it.", text)
        self.assertNotIn("Checking the file.", text)
        self.assertIn("Mode: Execution\nNeeds from you: nothing\nChanged: nothing", text)
        self.assertEqual(turns[0].text, text)
        self.assertEqual(turns[0].findings, [])

    def test_a_marker_before_a_later_tool_call_still_opens_the_reply(self):
        turns = self.kturns(k_user("one"), k_text(K_MARKER + "\nMode: Execution"), k_tool(),
                            k_result(), k_final("Changed: nothing"))
        self.assertEqual(turns[0].last, K_MARKER + "\nMode: Execution\nChanged: nothing")
        self.assertEqual(turns[0].findings, [])

    def test_without_a_marker_the_text_after_the_last_tool_call_is_the_reply(self):
        turns = self.kturns(
            k_user("one"), k_text("Before any tool."), k_tool(), k_result(),
            k_text("Between tools."), k_tool(), k_result(),
            k_text("Mode: Execution"), k_final("Changed: nothing"))
        self.assertEqual(turns[0].last, "Mode: Execution\nChanged: nothing")
        self.assertEqual(turns[0].findings, ["reply marker missing"])

    def test_a_turn_with_no_tool_call_and_no_marker_is_all_its_text(self):
        turns = self.kturns(k_user("one"), k_text("Mode: Execution"), k_final("Changed: nothing"))
        self.assertEqual(turns[0].last, "Mode: Execution\nChanged: nothing")
        self.assertEqual(turns[0].findings, ["reply marker missing"])

    def test_the_marker_is_one_constant(self):
        self.assertEqual(claude.REPLY_MARKER, K_MARKER)

    def test_a_marker_mentioned_inside_a_sentence_is_not_the_marker(self):
        turns = self.kturns(k_user("one"), k_text(f"I will write {K_MARKER} soon."), k_tool(),
                            k_result(), k_final("Mode: Execution"))
        self.assertEqual(turns[0].last, "Mode: Execution")
        self.assertEqual(turns[0].findings, ["reply marker missing"])


class ClaudeCodeMain(TranscriptCase):
    """The entry point end to end on a Claude Code transcript."""

    def setUp(self):
        ledger = tempfile.TemporaryDirectory()
        self.addCleanup(ledger.cleanup)
        patcher = mock.patch.object(cr.tempfile, "gettempdir", return_value=ledger.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, path: Path, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["check_response.py", "--tool", "claude", "--transcript", str(path), *extra]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new=out), \
                mock.patch("sys.stderr", new=err):
            return cr.main(), out.getvalue(), err.getvalue()

    def test_a_marked_clean_reply_passes(self):
        path = self.transcript(k_user("one"), k_text("Working."), k_tool(), k_result(),
                               k_text(K_MARKER), k_final(CONDENSED_CLEAN),
                               k_user("two - in progress"), k_tool(K_CHECK))
        code, out, _ = self.run_main(path, "--previous")
        self.assertEqual(code, 0, out)
        self.assertIn("Compliance: PASS", out)

    def test_a_malformed_reply_fails(self):
        path = self.transcript(k_user("one"), k_text(K_MARKER), k_final("Looks fine to me."),
                               k_user("two - in progress"))
        code, out, _ = self.run_main(path, "--previous")
        self.assertEqual(code, 1, out)
        self.assertIn("Compliance: FAIL", out)

    def test_a_forgotten_marker_fails_with_its_finding_even_when_the_shape_is_clean(self):
        path = self.transcript(k_user("one"), k_text("Working."), k_tool(), k_result(),
                               k_final(CONDENSED_CLEAN), k_user("two - in progress"))
        code, out, _ = self.run_main(path, "--previous")
        self.assertEqual(code, 1, out)
        self.assertIn("  - reply marker missing", out)

    def test_the_reply_being_written_is_graded_in_flight(self):
        path = self.transcript(k_user("one"), k_text(K_MARKER), k_text(CONDENSED_CLEAN))
        code, out, _ = self.run_main(path)
        self.assertEqual(code, 0, out)
        self.assertIn("in-flight", out)

    def test_other_adapters_carry_no_findings(self):
        self.assertEqual(shape.Turn(shape.OPERATOR, "x", "t0").findings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
