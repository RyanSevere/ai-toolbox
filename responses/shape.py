#!/usr/bin/env python3
################################################################################
# File: shape.py
# Path: {PROJECT_ROOT}/responses/shape.py
# Created by: Ryan Severe
# Created: 2026-10-09
# Last Updated: 2026-11-26
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
from dataclasses import dataclass, field

# Matches an actual invocation. Matching the bare filename also counted commands that
# merely mentioned it, such as copying it to a backup - which inflated the run count.
# A path may be quoted, single or double, which is the only way to run one that holds spaces.
INVOCATION = re.compile(
    r"""python[\w.]*\s+(?:"[^"|;]*check_response\.py"|'[^'|;]*check_response\.py'"""
    r"""|[^\s|;]*check_response\.py)"""
)

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

# Layout limits of the condensed Summary. They are named here so that a profile's fork
# changes the shape in one place: the toolbox does not resist a different response shape.
# A topic runs from one bold lead-in to the next, and the first block opens with one.
# True: several topics are allowed. False: exactly one topic.
SUMMARY_MULTI_PARAGRAPH_WITH_BOLD = True
# True: a list marker (-, * or 1.) at the start of a Summary line is a finding. The
# default is False: lists are allowed inside a topic.
SUMMARY_LIST_MARKERS_FORBIDDEN = False
BOLD_LEAD_IN = "**"
LIST_MARKER = re.compile(r"^\s*(?:[-*]\s|\d+\.\s)")

# A reply with no operator message before it opens with this line, right after the
# header, and continues the previous reply's ID counters. The spec quotes it and a test
# keeps the two in step.
CONTINUATION_LINE = "Continues the previous reply - no operator message in between."
ID_PREFIXES = ("LA", "DC", "ND", "CU", "OS", "P", "C", "A", "R", "Q")
ID_AT_START = re.compile(r"^(" + "|".join(ID_PREFIXES) + r")(\d+)\b")
# A bold lead-in that starts with an ID and is followed by a prose word on the same line:
# a reference in a paragraph, not an item. A bold item ends its line or is followed by a tag.
BOLD_REFERENCE = re.compile(
    r"^\s*(?:[-*]\s+)?\*\*(?:" + "|".join(ID_PREFIXES) + r")\d+\b[^*]*\*\*\s+\w")

# The reply's footer for layers 1 and 2: its last line, three fields, each non-empty.
STATUS_PREFIX = "STATUS:"
STATUS_SHAPE = ("STATUS: needs operator: <text>; workers running: <text>; "
                "background tasks: <text>")
STATUS_FORM = re.compile(
    r"STATUS:\s*needs operator:\s*[^;\s][^;]*;\s*workers running:\s*[^;\s][^;]*;\s*"
    r"background tasks:\s*\S.*")

MODES = {"planning", "execution", "planning + execution"}

REQUIRED = {
    "planning": ["yourpremises", "myclaims", "logicandapproach"],
    "execution": ["askeddoneresult", "premisesactedon"],
}

# The condensed shape is the default. A reply is full only if it carries a heading that
# belongs to the full shape alone; the headings both shapes use are left out on purpose.
# Logic and approach is one of them: design replies keep it in the condensed shape
# (operator, 2026-11-13). It is optional there, and the full shape still requires it.
FULL_SECTIONS = {
    "yourpremises", "myclaims", "recommendations",
    "askeddoneresult", "premisesactedon", "notdonenotchecked",
}
CONDENSED_REQUIRED = ["summary", "recommendednext", "cameupwhiledoingit"]
RECOMMENDED = re.compile(r"\(recommended\)", re.IGNORECASE)
# The nested line naming the check behind a DC's premise. Matched on strip_md(...).lower().
PREMISE_KEY = "premise checked:"
UNCHECKED = re.compile(r"unchecked\b")
UNCHECKED_REASON = re.compile(r"unchecked[\s\-–—:]*\w")
NONE_THIS_TURN = "None this turn."
LINES = "#lines"  # suffix: a section's raw lines outside fences, blank lines kept
# The ledger file holds what the condensed reply no longer prints. Checking it is a
# separate piece of work; until it exists the line says so and never reads as a pass -
# unknown is not zero.
LEDGER_FILE_LINE = "Ledger file: not checked - no ledger exists yet"

CAPS = {"cameupwhiledoingit": 3, "recommendednext": 4}  # decisions deliberately uncapped

# The Stop hook sends a reply back only for a finding that starts with one of these: it can
# change what the operator is asked or decides. Every other finding is report-only. A
# profile changes the split by editing this tuple.
SEND_BACK_PREFIXES = ("decisions:", "continuation:")


def sends_back(finding: str) -> bool:
    """True when the finding starts with an entry of SEND_BACK_PREFIXES."""
    return finding.startswith(SEND_BACK_PREFIXES)

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
    ("markdown link", re.compile(r"\[[^\]\n]+\]\([^)\s]+\)")),
    ("commit hash", re.compile(r"`[0-9a-fA-F]{7,}`")),
)


@dataclass
class Turn:
    """One turn as an adapter read it from its tool's transcript.

    text is the reply the shape applies to, which only the adapter can pick out:
    every assistant message of a Copilot turn, the last text block of a Cursor one.
    key names the turn in the run ledgers and must be stable as the transcript grows.
    findings are extra findings the adapter raised about how the reply was found, such as
    a missing reply marker; grade reports them with the structural ones.
    """

    kind: str
    text: str
    key: str
    invoked: str | None = None
    runs: int = 0
    cut_short: bool = False
    last: str = ""
    findings: list[str] = field(default_factory=list)
    operator_input: bool = False  # the operator gave input inside this turn
    layer: bool = False  # the transcript shows a layer 1 or 2 skill loaded: STATUS required


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


def summary_topics(lines: list[str]) -> list[str]:
    """The Summary's topics: each runs from a line opening with a bold lead-in, up to the
    next such line. A list item that opens with bold text belongs to the topic it is in."""
    topics: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(BOLD_LEAD_IN) and not LIST_MARKER.match(line):
            topics.append([stripped])
        elif topics and stripped:
            topics[-1].append(stripped)
    return [" ".join(topic) for topic in topics]


def condensed_findings(sections: dict, mode: str | None = None) -> list[str]:
    """Findings that apply only to the condensed shape."""
    findings: list[str] = []
    for name in CONDENSED_REQUIRED:
        if name not in sections:
            findings.append(f"condensed: section missing: {name}")
    # A planning reply owes its reasoning. Whether the section was needed is the agent's
    # to judge when this fires, but an unchecked requirement would simply be dropped
    # (operator, 2026-11-13).
    if mode and "planning" in mode and "logicandapproach" not in sections:
        findings.append("condensed: section missing for planning mode: logicandapproach")

    if "summary" in sections:
        lines = sections.get("summary" + LINES, [])
        found = paragraphs(lines)
        topics = summary_topics(lines)
        if not found:
            findings.append("summary: 0 paragraphs, at least 1 required")
        else:
            if len(topics) > 1 and not SUMMARY_MULTI_PARAGRAPH_WITH_BOLD:
                findings.append(f"summary: {len(topics)} topics, exactly 1 allowed")
            # A Summary with no bold lead-in at all is one unlabelled paragraph and stays
            # valid. Once a topic opens with one, the first block must too, and a list
            # belongs inside a topic, so a Summary never opens with one.
            opens_with_list = bool(LIST_MARKER.match(next(row for row in lines if row.strip())))
            if (topics or opens_with_list) and not found[0].startswith(BOLD_LEAD_IN):
                findings.append(f"summary: first block ('{found[0][:40]}') has no bold "
                                "lead-in - a topic opens with one")
        if SUMMARY_LIST_MARKERS_FORBIDDEN:
            marked = [line.strip() for line in lines if LIST_MARKER.match(line)]
            if marked:
                findings.append(f"summary: list marker on '{marked[0][:40]}' - one topic at a "
                                "time as paragraphs, no list")
        joined = " ".join(found)
        if found and joined != NONE_THIS_TURN and not has_pointer(joined):
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
        findings.extend(condensed_findings(sections, mode))

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
        title = item["title"][:60]
        condensed = shape_of(sections) == "condensed"
        nested = [strip_md(line).lower() for line in item["lines"][1:]]
        premises = [line[len(PREMISE_KEY):].strip() for line in nested
                    if line.startswith(PREMISE_KEY)]
        # A premise line reading 'unchecked' is the one case where a DC may recommend
        # nothing: it asks the fact instead. It relaxes 'exactly one' to 'at most one'.
        unchecked = condensed and any(UNCHECKED.match(p) for p in premises)
        if marked != 1 and not (unchecked and marked == 0):
            findings.append(f"decisions: '{title}' marks {marked} options "
                            "recommended, exactly one is required")
        # Condensed only: the full shape carries its reasoning in its own blocks and its
        # checks are unchanged. The reasoning is owed so a false premise can be caught.
        if condensed:
            for key, label in (("recommendation:", "recommendation"),
                               ("would change my answer:", "would change my answer")):
                if not any(line.startswith(key) for line in nested):
                    findings.append(f"decisions: '{title}' missing '{label}'")
            if marked and not premises:
                findings.append(f"decisions: '{title}' missing 'premise checked'")
            if unchecked and marked:
                findings.append(f"decisions: '{title}' has 'premise checked: unchecked' "
                                "beside a recommended option - recommend only a checked premise")
            elif unchecked and not any(
                    UNCHECKED.match(p) and UNCHECKED_REASON.match(p) for p in premises):
                findings.append(f"decisions: '{title}' 'premise checked: unchecked' "
                                "has no reason after it")

    # Spec rule 9: every entity carries an ID. A top-level entry without one used to be
    # dropped, or merged into the field above it, so the reply passed.
    for key, entries in sections.items():
        if not key.endswith(ENTRIES):
            continue
        name = key[:-len(ENTRIES)]
        if name == "summary":
            continue  # a Summary topic is prose and lists, not an ID'd item
        for entry in entries:
            if name in RESURFACED:
                if not QUESTION.match(entry):
                    findings.append(f"{name}: '{entry[:60]}' has no Q<n> ID to answer it by")
            elif not (ITEM_START.match(entry) or QUESTION.match(entry)):
                findings.append(f"{name}: '{entry[:60]}' has no item ID - every top-level "
                                "entry opens with one, and fields are indented under it")

    return findings, mode


def item_numbers(text: str) -> list[tuple[str, int]]:
    """Every item ID a reply opens a line with, outside fences, as (prefix, number).

    A bold reference opening a prose line, such as '**DC1 (a) is waiting** on you', names
    an item and is not one, so it is not counted."""
    found: list[tuple[str, int]] = []
    fence: str | None = None
    for raw in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", raw)
        if marker and (fence is None or marker.group(1).startswith(fence)):
            fence = marker.group(1)[:3] if fence is None else None
            continue
        if fence is not None:
            continue
        if BOLD_REFERENCE.match(raw):
            continue
        match = ID_AT_START.match(strip_md(raw))
        if match:
            found.append((match.group(1), int(match.group(2))))
    return found


def continuation_findings(turns: list[Turn], index: int) -> list[str]:
    """Findings for a reply opened by a background event right after a finished reply.

    Only a NOTIFICATION turn whose immediately preceding turn has a reply is checked: no
    operator message came between them, so the reply continues the previous one. It
    must say so, and its IDs must carry on from the previous reply's counters. Any other
    turn, or a preceding turn with no reply text, has nothing to continue. A turn that
    holds operator input, a typed message or a question-card answer, is not checked
    either: the operator spoke in between, so the reply restarts its counters.
    """
    if index < 1 or index >= len(turns) or turns[index].kind != NOTIFICATION:
        return []
    if turns[index].operator_input:
        return []
    before = turns[index - 1]
    if not before.text.strip():
        return []
    findings: list[str] = []
    header, _ = parse(turns[index].text)
    if CONTINUATION_LINE not in (strip_md(line) for line in header):
        findings.append(f"continuation: header lacks the line '{CONTINUATION_LINE}'")
    highest: dict[str, int] = {}
    for prefix, number in item_numbers(before.text):
        highest[prefix] = max(highest.get(prefix, 0), number)
    reused: list[str] = []
    for prefix, number in item_numbers(turns[index].text):
        if number <= highest.get(prefix, 0) and f"{prefix}{number}" not in reused:
            reused.append(f"{prefix}{number}")
    for name in reused:
        prefix = name.rstrip("0123456789")
        findings.append(f"continuation: {name} reuses an ID - the previous reply already "
                        f"reached {prefix}{highest[prefix]}")
    return findings


def status_findings(text: str, layer: bool = False) -> list[str]:
    """Findings about the STATUS footer of one reply.

    Any line starting 'STATUS:' outside a fence must be well formed and be the reply's
    last non-empty line, in any session. A reply with no such last line is a finding
    only when the adapter marked the turn as layer 1 or 2. A reply whose last non-empty
    content is a code fence ending in a STATUS line gets a finding that names the fence:
    the footer is plain text, never in a fence."""
    lines: list[str] = []
    fence: str | None = None
    inner: str | None = None
    closed_inner: str | None = None
    for raw in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", raw)
        if marker and (fence is None or marker.group(1).startswith(fence)):
            if fence is None:
                fence, inner, closed_inner = marker.group(1)[:3], None, None
            else:
                fence, closed_inner = None, inner
            continue
        if raw.strip():
            if fence is None:
                lines.append(raw.strip())
                closed_inner = None
            else:
                inner = raw.strip()
    findings: list[str] = []
    if closed_inner is not None and closed_inner.startswith(STATUS_PREFIX):
        findings.append(f"status: '{closed_inner[:60]}' is inside a code fence - the footer is "
                        f"plain text, never in a fence")
    last = len(lines) - 1
    for index, line in enumerate(lines):
        if not line.startswith(STATUS_PREFIX):
            continue
        if not STATUS_FORM.fullmatch(line):
            findings.append(f"status: '{line[:60]}' lacks a non-empty field - the line reads "
                            f"'{STATUS_SHAPE}'")
        if index != last:
            findings.append(f"status: '{line[:60]}' is not the reply's last line")
    if layer and not (lines and lines[-1].startswith(STATUS_PREFIX)):
        findings.append(f"status: no STATUS last line - a layer 1 or 2 reply ends with "
                        f"'{STATUS_SHAPE}'")
    return findings


def grade(label: str, text: str, interrupted: bool = False, invoked: str | None = None,
          extra: list[str] | None = None, layer: bool = False) -> int:
    """Report one reply. Returns 0 clean, 1 findings, EXIT_NOT_APPLICABLE if unshaped.

    extra is a Turn's own findings, reported after the structural ones. layer is whether
    the adapter marked the turn as layer 1 or 2, which makes the STATUS footer required."""
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
    findings.extend(status_findings(text, layer))
    findings.extend(extra or [])
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
