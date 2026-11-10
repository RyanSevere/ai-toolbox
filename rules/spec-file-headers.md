---
id: file-headers
tier: 2
scope: "*"
alwaysApply: false
description: >-
  File header SPECIFICATION - the metadata field definitions and the ASCII art
  block itself. Load ONLY when creating a new file that needs a header, or when
  explicitly asked to verify a header. Do not load when merely editing an
  existing file: the art is write-once and prescriptions.md already carries the
  rule to skip past it and update Last Updated. No repo is exempt.
---

# File headers

Every file begins with a metadata block and the ShadowAgent ASCII art.

**No repo is exempt, shell included.** A per-repository opt-out was reversed
after four tests showed the art does not break shell.

---

## Order

1. Shebang, where applicable
2. Metadata block
3. ASCII art
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

## The art

Stored once here rather than four times per repo. Adapt the leading comment
character to the target language; the art itself is unchanged.

```
===========================================================================


           "~,
               *m,
                  *9m;
                      *%pg
                         "YRWu
                             *9$&w
                                 *R$&w
  ;j]@@W;                   *w,      79&&w;
  :|*%MT"                     7&&w,      ?78BWw
. ,|*       -p     ~            *R$$$gw,     '*MU@m,
           =W/?*%NMWgw             *T&$F ,@w;     "*4[%m,
             7R$$$$$$$$g          yg$$Gg$@@Hh!j ,w     "*w|j=,
      ..     ]K@ww[T$Fff            >*MB&&@@Hh ]hk{!!~^     "*v'
         '|;, *M@@&&$P                 $$&@HHH\  ` ;w,,   ,~""
           "|jj]]%@F"                  ]$@@H, ;*M%P)a$$C  c
          . :|j[M"                     ]@@HHr TfR4&$NE*,/~<'
            `!||j]@@@A`                ]@@Hh~ *TT"" "* ^ r  '~
               *ojKM"                  l@Hh~  "*|"'   /        `
                                       @HHkC ,;!"
                                      ]HHhr/|!"'
                                      #Hhr!||"
                            ,@r       hkr!||'
                                     [k{|!"
                                    (r!!"        r
                                    !!"        r
                                     ";      /
                                            '
                                           '
===========================================================================
```

---

## Keeping headers true

- **Update `Last Updated` on any change.** A header claiming a stale date is
  worse than no header.
- **Preserve existing comments** unless the code they describe is also removed.
- **Update comments with the code.** A comment describing behaviour the
  function no longer has is a false signal, same class as any other.

---

## Note on cost

The art is a signature, not decoration. It is the author's mark on code he
wrote - anyone can put a name in a comment block; the art is unique to him.
It stays.

**But it is write-once.** After creating a file, an assistant never needs to
read, parse, reason about, or reproduce the art again. Treat the block between
the `===` delimiters as opaque:

- **On create:** emit it in full.
- **On edit:** skip past it to the metadata block, update `Last Updated`, and
  otherwise leave it untouched.
- **On read:** ignore it. It carries no instruction and never changes.
- **On explicit request to verify:** confirm the delimiters and the metadata
  fields are present. Confirming the art is byte-correct is not required.

Storing it once here rather than sixteen times across the estate removes the
maintenance cost. The above removes most of the per-file reading cost.
