---
name: product-docs
description: >-
  Write or backfill a product's standing documents - requirements, architecture,
  security, testing, decisions and the ones its kind adds - each from a template
  with fixed sections. Use when the user says any of: "write the product docs",
  "backfill the product docs", "document this product", "what documents does this
  product need", "before designing a new product", or otherwise wants a product's
  purpose, architecture or security model written down where an agent will read it.
argument-hint: the product, and whether it is new or already built
---

# Product documents

A **product** is a deployable thing in a consuming repository with its own purpose:
a service, an app, a library, a provisioning profile. Each product carries a
standard set of documents, written from templates in `templates/` beside this file.

| Document | Holds | Expected |
|---|---|---|
| `product-requirements.md` | Purpose, users, features, needs, functional and non-functional requirements, what is out of scope | Always |
| `architecture.md` | Structure, technologies, topology, high-level design, integration points, data flow | Always |
| `security.md` | What must be kept secure, the threats, the controls and where they are enforced, how secrets are handled | Always |
| `testing.md` | How the product is tested, the tools, the business logic the tests must encode, what runs where | Always |
| `DECISIONS.md` | Each significant decision, its alternatives and why they were rejected | Always |
| `operations.md` | Deploy, rollback, monitoring, backup and restore, pointing at the runbooks | Anything deployed |
| `design-system.md` | Colours, typography, components, layout and consistency rules | Products with a UI |
| `database.md` | Engine, schema and data models, migrations, retention | Products with a datastore |
| `interfaces.md` | API and message contracts at the product's boundaries | Products others call |

## Placement

- A repository with one product uses `docs/product/`.
- A repository with more than one uses `docs/products/<name>/`, one folder per product.
- An optional `docs/products.yaml` lists the products and their kinds, so the expected
  set is derived, not guessed.
- With no declaration and a `docs/product/` folder, the repository is one product,
  named after the repository folder, with the five always-expected documents.

## `docs/products.yaml`

```yaml
products:
  - name: example-service      # kebab case, [a-z0-9]+(-[a-z0-9]+)*
    kinds: [deployed, called]  # any of: ui, datastore, deployed, called; may be empty
```

The expected set is the five always-expected documents, plus one per kind: `deployed`
adds `operations.md`, `ui` adds `design-system.md`, `datastore` adds `database.md`,
`called` adds `interfaces.md`.

Run `python <skill dir>/expected_docs.py <repo root>` to see, for each product, its
folder, its expected documents, and which are present or missing. With neither a
declaration nor a `docs/product/` folder it prints `no products declared`. A malformed
declaration is refused with exit code 2 and a message naming the problem; it never reads
as "no products". Missing documents are information only and the exit code stays 0.

## Writing a new product's documents

Done before anything is built.

1. Run `python <skill dir>/expected_docs.py <repo root>` and note the expected documents.
2. For each expected document, copy its template from `templates/` into the product's folder.
3. Interview the operator one section at a time, starting with `product-requirements.md`.
   Ask for intent, requirements and decisions, and record what is said, quoted where it
   matters.
4. Write each section. Where a document or section does not apply, write the one line
   described under Not applicable.
5. Set `Last verified:` to the date, in each document written.

## Backfilling an existing product

1. Run `python <skill dir>/expected_docs.py <repo root>` and note which documents are missing.
2. Derive what the code shows. For a derivable fact, such as a schema from migrations or a
   topology from compose files, point at the source or generate it; never hand-copy it.
3. Ask the operator only for what the code cannot show: purpose, users, requirements,
   the reasons behind decisions.
4. Copy each missing template into the product's folder and write it.
5. Set `Last verified:` to the date, in each document written.

## Not applicable

A document or section that does not apply says so on one line, `Not applicable: <reason>`,
and is never deleted, so "not applicable" and "missing" do not look alike.

## Constraints

- **Facts versus rules.** These documents hold intent, requirements and decisions, which do
  not go stale. Anything derivable is pointed to or generated. Each records when it was
  last verified.
- **Documents plan; tickets track.** No status, next steps or blockers in these documents.
- **Security documents are safe to publish.** They describe controls, never secret values,
  hostnames or account names that would help an attacker.
- **Usable, not required.** Nothing refuses work for a missing document.

The written documents carry the consuming repository's file header, as its own header rule
requires.
