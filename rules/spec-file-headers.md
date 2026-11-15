---
id: file-headers
tier: 2
scope: "*"
alwaysApply: false
description: >-
  File header SPECIFICATION - the metadata field definitions, and how a
  profile's header art is applied. Load ONLY when creating a new file that needs a header, or when
  explicitly asked to verify a header. Do not load when merely editing an
  existing file: the art is write-once and prescriptions.md already carries the
  rule to skip past it and update Last Updated. No repo is exempt.
---

# File headers

Every file begins with a metadata block, followed by the profile's header art
if it defines one.

No repo is exempt.

---

## Order

1. Shebang, where applicable
2. Metadata block
3. Header art, if the profile defines it
4. One or two blank lines before the first import or statement

## Fields

| Field | Content |
|---|---|
| `File` | Filename only |
| `Path` | Absolute deploy path, or `{PROJECT_ROOT}/<path>` where the root varies |
| `Created by` | Author |
| `Created` | `YYYY-MM-DD` |
| `Last Updated` | `YYYY-MM-DD` - **must** change on any modification |
| `Description` | One to three sentences on purpose and key responsibilities |

## Applying it

- **New files:** always include the full header.
- **Existing files:** check on first edit. If absent, add it at the very top.
- **Comment style:** adapt to the language - `#` for shell and Python, `//` for
  JS and TS, `/* */` for CSS.
- Headers are comments only. They never affect compilation or execution.
- **Exempt: a ticket or comment body drafted in `scratch/`.** It is posted to
  the tracker and deleted, so a header would only land in the issue text.
- **Exempt: `LICENSE` and `VERSION` at the repository root.** A header stops
  GitHub recognising the licence and breaks a plain read of the version string.

---

## Header art

A profile may define header art in its own rule, `header-art`, which renders as
`.github/rules/header-art.md`. Open that file when creating a file. If it
exists, its art follows the metadata block in every new file, with the comment
character adapted to the language. If it does not exist, the profile defines no
art and the header is the metadata block alone. The core ships no `header-art`
rule, so the name never collides.

---

## Keeping headers true

- **Update `Last Updated` on any change.** A header claiming a stale date is
  worse than no header.
- **Preserve existing comments** unless the code they describe is also removed.
- **Update comments with the code.** A comment describing behaviour the
  function no longer has is a false signal, same class as any other.

---

## Note on cost

**The art, where there is one, is write-once.** After creating a file, an
assistant never needs to read, parse, reason about, or reproduce the art again.
Treat the block between the `===` delimiters as opaque:

- **On create:** emit it in full.
- **On edit:** skip past it to the metadata block, update `Last Updated`, and
  otherwise leave it untouched.
- **On read:** ignore it. It carries no instruction and never changes.
- **On explicit request to verify:** confirm the delimiters and the metadata
  fields are present. Confirming the art is byte-correct is not required.

Storing it once, in the profile's rule, rather than in every repository removes
the maintenance cost. The above removes most of the per-file reading cost.
