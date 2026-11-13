#!/usr/bin/env python3
################################################################################
# File: shape.py
# Path: {PROJECT_ROOT}/responses/shape.py
# Created by: Ryan Severe
# Created: 2026-10-09
# Last Updated: 2026-11-13
# Description: The tool-neutral half of the response checker.
#              Parses a reply against the response shape, grades it, and walks
#              back over finished turns to collect replies whose turn never ran
#              the check. Knows nothing about any tool's transcript format; an
#              adapter turns a transcript into a list of Turn records first.
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
from dataclasses import dataclass

# Matches an actual invocation. Matching the bare filename also counted commands that
# merely mentioned it, such as copying it to a backup - which inflated the run count.
INVOCATION = re.compile(r"python[\w.]*\s+[^\s|;]*check_response\.py")

# Session starters open their report with this line. It exempts a reply only when its
# turn began with the command.
EXEMPT_MARKER = re.compile(r"^results\s+from\s+(prime|sitrep)\b", re.IGNORECASE)
INVOKED = re.compile(r"^\s*/(prime|sitrep)\b", re.IGNORECASE)
EXIT_NOT_APPLICABLE = 4
# A skipped turn is collected by the next run. The cap stops the first run of a long
# ungraded session from grading all of it.
LOOKBACK_CAP = 5

OPERATOR = "operator"
NOTIFICATION = "notification"

MODES = {"planning", "execution", "planning + execution"}

REQUIRED = {
    "planning": ["yourpremises", "myclaims", "logicandapproach"],
    "execution": ["askeddoneresult", "premisesactedon"],
}

# The condensed shape is the default. A reply is full only if it carries a heading that
# belongs to the full shape alone; the headings both shapes use are left out on purpose.
FULL_SECTIONS = {
    "yourpremises", "myclaims", "logicandapproach", "recommendations",
    "askeddoneresult", "premisesactedon", "notdonenotchecked",
}
CONDENSED_REQUIRED = ["summary", "recommendednext", "cameupwhiledoingit"]
RECOMMENDED = re.compile(r"\(recommended\)", re.IGNORECASE)
NONE_THIS_TURN = "None this turn."
LINES = "#lines"  # suffix: a section's raw lines outside fences, blank lines kept
# The ledger file holds what the condensed reply no longer prints. Checking it is air-333;
# until it exists the line says so and never reads as a pass - unknown is not zero.
LEDGER_FILE_LINE = "Ledger file: not checked - no ledger exists yet (air-333)"

CAPS = {"cameupwhiledoingit": 3, "recommendednext": 4}  # decisions deliberately uncapped

FIELD = re.compile(
    r"^(verdict|evidence for|evidence against|would have falsified[^:]*|"
    r"looked for it|use case|autonomy|how|consistent with|in tension with)\s*:",
    re.IGNORECASE,
)
EMPTY = {"", "-", "none", "none found", "n/a", "na", "nothing"}
# A qualifier may follow after a comma or full stop: "confirmed, with a correction".
VERDICT = re.compile(r"^(confirmed|contradicted|not checked)(?![\w-])", re.IGNORECASE)

# An item starts at its ID. Bold was the old marker and the shape's own examples
# never used it, so from 2026-09-23 every reply that followed the examples parsed
# to zero items and passed on its header alone. Q is excluded: a question attaches
# to an item, it is not one.
ITEM_START = re.compile(r"^(?:P|C|LA|DC|A|ND|CU|R|OS)\d+\b")

# Re-surfaced items are answered by reference, so each needs an ID - spec rule 16.
# Entries here are top-level list lines, not items, and are collected separately.
RESURFACED = ("youmissedthis", "stillopen", "stillopenfromlastturn")
QUESTION = re.compile(r"^Q\d+\b")
ENTRIES = "#entries"  # suffix: norm() strips '#', so it can never collide with a heading

# Evidence a reader can follow without trusting the writer. Presence only - the
# script cannot tell a real pointer from an invented one, but it can tell a
# pointer from a summary, and all three false claims of 2026-09-24 were summaries.
POINTERS = (
    ("file:line", re.compile(r"[\w./\\-]+\.[A-Za-z0-9]{1,6}:\d+")),
    ("url", re.compile(r"https?://\S+")),
    ("quotation", re.compile(r"[\"\u201c][^\"\u201d]{8,}[\"\u201d]")),
    ("command or output", re.compile(r"`[^`\n]*\s[^`\n]*`")),
)


@dataclass
class Turn:
    """One turn as an adapter read it from its tool's transcript.

    text is the reply the shape applies to, which only the adapter can pick out:
    every assistant message of a Copilot turn, the last text block of a Cursor one.
    key names the turn in the run ledgers and must be stable as the transcript grows.
    """

    kind: str
    text: str
    key: str
    invoked: str | None = None
    runs: int = 0
    cut_short: bool = False
    last: str = ""


def invoked_in(message: str) -> str | None:
    """The session command an operator message opens with, if any."""
    match = INVOKED.match(message)
    return match.group(1).capitalize() if match else None


def lookback(turns: list[Turn]) -> tuple[list[tuple[int, Turn]], int, bool]:
    """The previous reply, plus any before it whose turn never ran the check.

    The last turn is the one in progress. A skipped check is invisible from the turn
    that skipped it, so the next run collects the arrears; reply j is graded during
    turn j+1, which is what stops the walk. A notification turn is graded like any
    other: its reply is one the operator reads and answers.
    """
    current = turns[-1] if turns else Turn(OPERATOR, "", "0")
    finished = turns[:-1]

    picked: list[tuple[int, Turn]] = []
    back = 0
    for turn in reversed(finished):
        if not turn.text.strip():
            # An interrupted or checkpoint-abandoned turn. Its own run of this
            # script was never seen, so it must not end the walk.
            back += 1
            continue
        picked.append((back, turn))
        if len(picked) >= LOOKBACK_CAP:
            return picked, current.runs, True
        if turn.runs:
            break  # the reply before this one was graded during this turn
        back += 1
    return picked, current.runs, False


def has_pointer(raw: str) -> bool:
    return any(pattern.search(raw) for _, pattern in POINTERS)


def norm(text: str) -> str:
    """Section and field names, reduced to letters so formatting cannot change identity."""
    return re.sub(r"[^a-z]", "", text.lower())


def strip_md(line: str) -> str:
    return re.sub(r"[*_`#>]", "", line).strip().lstrip("-").strip()


def parse(text: str) -> tuple[list[str], dict[str, list[dict]]]:
    """Split into header lines and sections of items, each item holding its fields.

    Grading starts at the header. Anything written before it - a lead-in sentence
    ahead of a tool call - is not shaped, so checking it would invent failures.
    """
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        if strip_md(raw).lower().startswith("mode:"):
            lines = lines[i:]
            break

    header: list[str] = []
    sections: dict[str, list[dict]] = {}
    section = None
    item: dict | None = None
    field = None
    fence: str | None = None

    for raw in lines:
        line = raw.rstrip().replace("&nbsp;", " ")
        # A list line inside a fence is pasted output or a diff - evidence, not an entry.
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker and (fence is None or marker.group(1).startswith(fence)):
            fence = marker.group(1)[:3] if fence is None else None
        in_fence = fence is not None or marker is not None
        heading = re.match(r"^#{2,4}\s+(.+)$", line)
        if heading:
            section = norm(heading.group(1))
            sections.setdefault(section, [])
            sections.setdefault(section + LINES, [])
            item = None
            field = None
            continue
        if section is None:
            if line.strip():
                header.append(line)
            continue

        body = strip_md(line)
        if not in_fence:
            sections[section + LINES].append(line)
        if not in_fence and re.match(r"^[-*]\s", line):
            sections.setdefault(section + ENTRIES, []).append(body)
        match = FIELD.match(body)
        if ITEM_START.match(body) and not match:
            item = {"title": body, "fields": {}, "raw": {}, "lines": [line]}
            sections[section].append(item)
            field = None
            continue
        if item is not None:
            item["lines"].append(line)
        if match and item is not None:
            field = norm(match.group(1))
            item["fields"][field] = body[match.end():].strip()
            # Unstripped, because strip_md removes the backticks a pointer is made of.
            item["raw"][field] = line.split(":", 1)[1].strip() if ":" in line else ""
            continue
        if field and item is not None and line.strip():
            item["fields"][field] += " " + body
            item["raw"][field] += " " + line.strip()

    return header, sections


def has_content(value: str) -> bool:
    cleaned = strip_md(value).lower().strip(" .")
    return cleaned not in EMPTY


def session_starter(text: str) -> str | None:
    """The command whose fixed-format report this is, or None if it is a shaped reply."""
    for line in text.splitlines():
        stripped = strip_md(line)
        if not stripped:
            continue
        match = EXEMPT_MARKER.match(stripped)
        return match.group(1).capitalize() if match else None
    return None


def shape_of(sections: dict) -> str:
    """'full' if any heading belongs to the full shape alone, else 'condensed'.

    There is no marker to forget: a half-opened block, a lone '## My claims', is graded
    as full and fails on the sections its mode requires.
    """
    return "full" if FULL_SECTIONS & set(sections) else "condensed"


def paragraphs(lines: list[str]) -> list[str]:
    """Runs of non-empty lines, split by blank lines. The lines are already outside fences."""
    found: list[str] = []
    run: list[str] = []
    for line in lines:
        if line.strip():
            run.append(line.strip())
        elif run:
            found.append(" ".join(run))
            run = []
    if run:
        found.append(" ".join(run))
    return found


def condensed_findings(sections: dict) -> list[str]:
    """Findings that apply only to the condensed shape."""
    findings: list[str] = []
    for name in CONDENSED_REQUIRED:
        if name not in sections:
            findings.append(f"condensed: section missing: {name}")

    if "summary" in sections:
        found = paragraphs(sections.get("summary" + LINES, []))
        if len(found) != 1:
            findings.append(f"summary: {len(found)} paragraphs, exactly 1 allowed")
        elif found[0] != NONE_THIS_TURN and not has_pointer(found[0]):
            kinds = ", ".join(kind for kind, _ in POINTERS)
            findings.append(f"summary: no pointer a reader could follow ({kinds})")

    for name in ("recommendednext", "cameupwhiledoingit"):
        if name not in sections:
            continue
        stated_empty = any(strip_md(line).lower() == "none." for line in sections[name + LINES])
        if not sections[name] and not stated_empty:
            findings.append(f"{name}: empty - list an item or write 'None.'")
    return findings


def check(header: list[str], sections: dict[str, list[dict]]) -> tuple[list[str], str | None]:
    """Structural findings for one parsed reply, and the mode it declared."""
    findings: list[str] = []
    blob = " ".join(header).lower()

    mode = None
    for line in header:
        if norm(line).startswith("mode"):
            mode = strip_md(line).split(":", 1)[-1].strip().lower()
    if mode not in MODES:
        findings.append(f"header: Mode missing or not one of {sorted(MODES)} (saw {mode!r})")
    if "needs from you" not in blob:
        findings.append("header: 'Needs from you' line missing")
    if "changed" not in blob:
        findings.append("header: 'Changed' line missing")

    if shape_of(sections) == "full":
        for part, names in REQUIRED.items():
            if mode and part in mode:
                for name in names:
                    if name not in sections:
                        findings.append(f"section missing for {part} mode: {name}")
    else:
        findings.extend(condensed_findings(sections))

    for name, limit in CAPS.items():
        count = len(sections.get(name, []))
        if count > limit:
            findings.append(f"{name}: {count} items, cap is {limit}")

    for name in ("yourpremises", "myclaims", "premisesactedon"):
        for item in sections.get(name, []):
            fields = item["fields"]
            label = item["title"][:60]
            # Both premise sections need the tag. Without it on the execution side, a
            # ruling there can never claim the exemption below and fails on evidence
            # it cannot have - three findings that describe the grader, not the reply.
            if name in ("yourpremises", "premisesactedon") and not re.search(
                r"\[(factual|ruling)\]", item["title"], re.I
            ):
                findings.append(f"{name}: '{label}' not tagged [factual] or [ruling]")
            if "ruling" in item["title"].lower():
                continue  # a ruling has no truth value, so no verdict or evidence is expected
            verdict = fields.get("verdict", "")
            # Which evidence side is owed follows the verdict, so an unknown verdict is
            # reported as itself. 'refuted' once drew "no evidence for it".
            if verdict and not VERDICT.match(strip_md(verdict)):
                findings.append(f"{name}: '{label}' verdict '{strip_md(verdict)[:40]}' is not "
                                "confirmed, contradicted or not checked")
                verdict = ""
            for required in ("verdict", "evidencefor", "evidenceagainst"):
                if required not in fields:
                    findings.append(f"{name}: '{label}' missing '{required}'")
            # Which side must carry evidence follows the verdict. A contradicted premise
            # is supported by evidence against it, so demanding evidence for it flagged
            # the correct shape - including this document's own worked example.
            if verdict and "not checked" not in verdict.lower():
                contradicted = "contradicted" in verdict.lower()
                side = "evidenceagainst" if contradicted else "evidencefor"
                if not has_content(fields.get(side, "")):
                    wording = "against it" if contradicted else "for it"
                    findings.append(
                        f"{name}: '{label}' claims verdict '{strip_md(verdict)}' "
                        f"with no evidence {wording}"
                    )
                elif not has_pointer(item["raw"].get(side, "")):
                    kinds = ", ".join(kind for kind, _ in POINTERS)
                    findings.append(
                        f"{name}: '{label}' evidence for verdict '{strip_md(verdict)}' "
                        f"has no pointer a reader could follow ({kinds})"
                    )
            if name == "myclaims":
                if not any(k.startswith("wouldhavefalsified") for k in fields):
                    findings.append(f"{name}: '{label}' missing falsification line")
                if "lookedforit" not in fields:
                    findings.append(f"{name}: '{label}' missing 'Looked for it'")

    for item in sections.get("decisionsandclarifications", []):
        if "usecase" not in item["fields"]:
            findings.append(f"decisions: '{item['title'][:60]}' missing 'Use case'")
        marked = len(RECOMMENDED.findall("\n".join(item["lines"])))
        if marked != 1:
            findings.append(f"decisions: '{item['title'][:60]}' marks {marked} options "
                            "recommended, exactly one is required")

    # Spec rule 9: every entity carries an ID. A top-level entry without one used to be
    # dropped, or merged into the field above it, so the reply passed.
    for key, entries in sections.items():
        if not key.endswith(ENTRIES):
            continue
        name = key[:-len(ENTRIES)]
        for entry in entries:
            if name in RESURFACED:
                if not QUESTION.match(entry):
                    findings.append(f"{name}: '{entry[:60]}' has no Q<n> ID to answer it by")
            elif not (ITEM_START.match(entry) or QUESTION.match(entry)):
                findings.append(f"{name}: '{entry[:60]}' has no item ID - every top-level "
                                "entry opens with one, and fields are indented under it")

    return findings, mode


def grade(label: str, text: str, interrupted: bool = False, invoked: str | None = None) -> int:
    """Report one reply. Returns 0 clean, 1 findings, EXIT_NOT_APPLICABLE if unshaped."""
    if interrupted:
        print(f"\n{label}: NOT APPLICABLE - cut short by a message sent mid-turn. The turn")
        print("carried on after it, so this slice is progress narration, not a reply.")
        return EXIT_NOT_APPLICABLE
    starter = session_starter(text)
    if starter and starter == invoked:
        print(f"\n{label}: NOT APPLICABLE - {starter} output, a fixed-format report that")
        print("carries no shape header by design. Nothing to grade.")
        return EXIT_NOT_APPLICABLE
    if starter:
        print(f"\n{label}: opens with the {starter} marker, but its turn was not "
              f"/{starter.lower()} - graded as a normal reply.")

    header, sections = parse(text)
    findings, mode = check(header, sections)
    count = sum(not name.endswith((ENTRIES, LINES)) for name in sections)
    print(f"\n{label}: mode={mode} | shape={shape_of(sections)} | {len(text)} chars | "
          f"{count} sections")
    if findings:
        print(f"Compliance: FAIL - {len(findings)} finding(s)")
        for f in findings:
            print(f"  - {f}")
        print(LEDGER_FILE_LINE)
        return 1
    print("Compliance: PASS")
    print(LEDGER_FILE_LINE)
    return 0
