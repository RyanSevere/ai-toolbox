# Patterns

Canonical implementations of code that gets copied between repos.

Rules cannot prevent the defect this directory addresses, because nobody
decides to introduce it.

---

## The evidence

Three of the issues filed in one audit were the same event: a working pattern
copied from a sibling repo with the safety-critical line dropped.

- **A webhook entrypoint.** The jq substitution came across. The
  `webhook.real` shim came across. The resolved-file indirection came across.
  What did not come across was `exit 1` - and the comment explaining it, which
  read:

  > An empty secret templates an empty match value, which any request satisfies.

  The comment describing the exact defect was deleted along with the guard
  that prevented it. The result accepts unauthenticated deploy requests.
- **A placeholder signing secret.** `secret_key = "change-me-in-production"`,
  signing OAuth state tokens - near-identical to one a sibling repo had removed
  weeks earlier. The fix propagated to two repos and not the third.
- **Four backup scripts, copy-pasted.** One later gained validation of the
  transferred archive. The other three never did, and report success without
  checking that anything arrived.

A profile records which repositories these were in its own `patterns/` notes.

---

## Why a prescription does not fix this

The prescriptions are read when reasoning about what to do. Copying working
code from a sibling repo does not feel like a decision that needs a rule
consulted - it feels like reuse, which is normally correct.

The failure is that **the guard and its reason are the easiest lines to lose**.
They look incidental. They read like defensive clutter around the part that
does the work.

---

## What lives here

One directory per pattern, containing `pattern.md`:

- the canonical implementation
- **every load-bearing line marked, with what breaks without it**
- known-wrong variants seen in practice, and what they cost
- where a correct copy currently lives - in the profile's notes, since it names a repository

## How to use it

When implementing something that exists here, copy from here - not from
whichever sibling repo happens to be open. When reviewing a copied pattern,
diff it against here rather than reading it on its own merits.

## What does not belong here

Anything copied once. This is for code that spreads, which in practice means
security guards, deploy machinery, and backup or notification paths.
