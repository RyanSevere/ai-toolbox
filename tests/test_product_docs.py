#!/usr/bin/env python3
################################################################################
# File: test_product_docs.py
# Path: {PROJECT_ROOT}/tests/test_product_docs.py
# Created by: Ryan Severe
# Created: 2026-11-23
# Last Updated: 2026-11-23
# Description: The product-docs skill. A template per product document, a
#              procedure for a new product and for a backfill, the script that
#              derives a repository's expected documents from docs/products.yaml,
#              the design-partner's reading of those documents, and the absence
#              of any gate that reads them.
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

import contextlib
import importlib.util
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync  # noqa: E402
from locked_example import locked_example  # noqa: E402

EXERCISES = ["skills/**", "agents/**", "githooks/**"]

SKILL = ROOT / "skills" / "product-docs"
TEMPLATES = SKILL / "templates"
SCRIPT = SKILL / "expected_docs.py"
DESIGN_PARTNER = ROOT / "agents" / "design-partner" / "definition.md"

# The ticket's table: every document, and the words its "Holds" column names. A tuple is
# alternatives for one word. Each word has to appear in some `## ` heading of the template.
SECTIONS = {
    "product-requirements.md": ["purpose", "users", "features", "functional",
                                "non-functional", "out of scope"],
    "architecture.md": ["structure", "technolog", "topology", "design", "integration",
                        "data flow"],
    "security.md": ["threats", "controls", "secrets"],
    "testing.md": ["tool", "business logic"],
    "DECISIONS.md": [],
    "operations.md": ["deploy", "rollback", "monitoring", "backup", "restore"],
    "design-system.md": [("colour", "color"), "typography", "components", "layout",
                         "consistency"],
    "database.md": ["engine", "schema", "migrations", "retention"],
    "interfaces.md": ["api", "message"],
}
ALWAYS = ["product-requirements.md", "architecture.md", "security.md", "testing.md",
          "DECISIONS.md"]
PER_KIND = {"deployed": "operations.md", "ui": "design-system.md",
            "datastore": "database.md", "called": "interfaces.md"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def squash(text: str) -> str:
    return " ".join(text.split())


def headings(text: str, level: str = "## ") -> list[str]:
    return [line[len(level):].strip() for line in text.splitlines() if line.startswith(level)]


def section(text: str, word: str) -> str:
    """The body of the first `## ` section whose heading contains `word`."""
    out: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            if out is not None:
                break
            if word.casefold() in line.casefold():
                out = []
        elif out is not None:
            out.append(line)
    if out is None:
        raise AssertionError(f"no '## ' section naming {word!r}")
    return "\n".join(out)


def frontmatter(text: str) -> dict:
    parts = text.split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        raise AssertionError("no YAML frontmatter")
    return yaml.safe_load(parts[1]) or {}


def load_script():
    """Load expected_docs.py as spec_gate.py is loaded in test_edge_cases.py."""
    if not SCRIPT.is_file():
        raise AssertionError(f"{SCRIPT.relative_to(ROOT)} does not exist")
    spec = importlib.util.spec_from_file_location("expected_docs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(root: Path) -> tuple[int, str]:
    """main([root]) -> (exit code, everything it printed, path separators as slashes)."""
    module = load_script()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main([str(root)])
    return code, (out.getvalue() + err.getvalue()).replace("\\", "/")


class Repo(unittest.TestCase):
    """A synthetic consuming repository in a temp directory, named example-repo."""

    def repo(self, files: dict[str, str] | None = None, yaml_text: str | None = None) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "example-repo"
        root.mkdir()
        for name, text in (files or {}).items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if yaml_text is not None:
            (root / "docs").mkdir(exist_ok=True)
            (root / "docs" / "products.yaml").write_text(yaml_text, encoding="utf-8")
        return root

    def declared(self, *products: tuple[str, list[str]]) -> Path:
        data = {"products": [{"name": name, "kinds": kinds} for name, kinds in products]}
        return self.repo(yaml_text=yaml.safe_dump(data))

    def expected_in(self, output: str) -> set[str]:
        return {doc for doc in SECTIONS if doc in output}


class RenderedSkill(unittest.TestCase):
    def test_every_template_is_a_rendered_asset_of_the_skill(self):
        """Intent: ticket 172 Done when, "a test that renders the skill and finds every
        template": the skill renders as SKILL.md, and each template as an asset beside it,
        under every skill root."""
        manifest = sync.load_profile(locked_example())
        plan = sync.build_plan("t", {"estate": True}, manifest.get("defaults") or {}, "abc1234",
                               manifest, profile_dir=locked_example())
        for root in (".github/skills", ".claude/skills"):
            with self.subTest(root=root):
                self.assertIn(f"{root}/product-docs/SKILL.md", plan)
                for name in SECTIONS:
                    self.assertIn(f"{root}/product-docs/templates/{name}", plan)


class Templates(unittest.TestCase):
    def test_there_is_one_template_per_document_in_the_table(self):
        """Intent: ticket 172 Done when, "one template file per document": exactly the
        nine documents of the ticket's table, named as the table names them."""
        found = {p.name for p in TEMPLATES.glob("*")} if TEMPLATES.is_dir() else set()
        self.assertEqual(found, set(SECTIONS))

    def test_each_template_opens_with_a_title_and_a_last_verified_line(self):
        """Intent: ticket 172 Design constraints, "each document records when it was last
        verified": a `# ` title, then a `Last verified:` line before any section."""
        for name in SECTIONS:
            with self.subTest(template=name):
                lines = [ln for ln in read(TEMPLATES / name).splitlines() if ln.strip()]
                self.assertTrue(lines[0].startswith("# "), lines[0])
                first_section = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
                self.assertTrue(any(ln.startswith("Last verified:") for ln in lines[1:first_section]))

    def test_each_template_holds_the_sections_its_row_of_the_table_names(self):
        """Intent: ticket 172 Done when, "each listing its required sections": a `## `
        heading for each thing the table's Holds column names for that document."""
        for name, words in SECTIONS.items():
            with self.subTest(template=name):
                text = read(TEMPLATES / name)
                titles = " | ".join(headings(text)).casefold()
                self.assertTrue(headings(text), "no `## ` sections")
                for word in words:
                    alternatives = word if isinstance(word, tuple) else (word,)
                    self.assertTrue(any(w in titles for w in alternatives),
                                    f"no heading names {word!r}: {titles}")

    def test_each_section_carries_an_instruction_line(self):
        """Intent: the build brief's step 2, "under each heading goes a short instruction
        line saying what belongs there": no heading is followed directly by another."""
        for name in SECTIONS:
            with self.subTest(template=name):
                lines = [ln for ln in read(TEMPLATES / name).splitlines() if ln.strip()]
                for i, ln in enumerate(lines):
                    if ln.startswith("## "):
                        self.assertLess(i + 1, len(lines), f"{ln!r} ends the file")
                        self.assertFalse(lines[i + 1].startswith("#"), f"{ln!r} has no line")

    def test_the_decisions_template_has_the_one_repeating_entry_form(self):
        """Intent: the build brief's step 2, "DECISIONS.md has one repeating entry form:
        decision, alternatives, why each was rejected, date"."""
        text = read(TEMPLATES / "DECISIONS.md").casefold()
        for word in ("decision", "alternatives", "rejected", "date"):
            self.assertIn(word, text)

    def test_the_operations_template_points_at_runbooks_rather_than_holding_them(self):
        """Intent: the build brief's step 2, "operations.md points at runbooks": it names
        the runbook folder of the planning spec."""
        self.assertIn("docs/runbooks/", read(TEMPLATES / "operations.md"))


class Procedure(unittest.TestCase):
    def setUp(self):
        self.path = SKILL / "procedure.md"
        self.assertTrue(self.path.is_file(), "skills/product-docs/procedure.md does not exist")
        self.text = read(self.path)

    def test_frontmatter_names_the_skill_with_its_triggers_and_is_interactive(self):
        """Intent: the build brief's step 1: name product-docs, a description carrying the
        five trigger phrases, and no `sessions:` key, so it renders as an interactive skill."""
        meta = frontmatter(self.text)
        self.assertEqual(meta.get("name"), "product-docs")
        self.assertNotIn("sessions", meta)
        description = squash(meta.get("description", ""))
        for phrase in ("write the product docs", "backfill the product docs",
                       "document this product", "what documents does this product need",
                       "before designing a new product"):
            self.assertIn(phrase, description)

    def test_it_names_both_paths_the_placement_rules_and_the_declaration(self):
        """Intent: ticket 172 Done when, "both paths named in procedure.md": a new-product
        heading and a backfill heading, with the placement section, the products.yaml
        section, and the script it points at."""
        titles = " | ".join(headings(self.text)).casefold()
        for word in ("new product", "backfill", "placement", "products.yaml",
                     "not applicable", "constraints"):
            self.assertIn(word, titles)
        for path in ("docs/product/", "docs/products/<name>/", "docs/products.yaml",
                     "expected_docs.py"):
            self.assertIn(path, self.text)

    def test_each_path_has_numbered_steps(self):
        """Intent: ticket 172 Done when, "each with its steps": the new-product section and
        the backfill section each hold a numbered list, and each ends by setting
        `Last verified:`."""
        for word in ("new product", "backfill"):
            with self.subTest(path=word):
                body = section(self.text, word)
                steps = re.findall(r"^\d+\. ", body, flags=re.MULTILINE)
                self.assertGreaterEqual(len(steps), 3)
                self.assertIn("Last verified:", body)
                self.assertIn("expected_docs.py", body)

    def test_it_states_the_not_applicable_form_and_the_constraints(self):
        """Intent: ticket 172 Proposal and Design constraints: a document that does not
        apply says `Not applicable: <reason>`, and the skill is usable, not required."""
        body = squash(self.text).casefold()
        self.assertIn("not applicable: <reason>", body)
        self.assertIn("not required", body)
        self.assertIn("file header", body)


class ExpectedSet(Repo):
    def test_a_product_with_no_kinds_expects_only_the_five_always_documents(self):
        """Intent: ticket 172 table, the "Always" rows, which are five including
        DECISIONS.md (the ticket's prose says four; the table is followed)."""
        code, out = run_script(self.declared(("example-service", [])))
        self.assertEqual(code, 0)
        self.assertEqual(self.expected_in(out), set(ALWAYS))

    def test_each_kind_adds_exactly_its_own_document(self):
        """Intent: ticket 172 table, the Expected column: deployed adds operations, ui adds
        design-system, datastore adds database, called adds interfaces."""
        for kind, doc in PER_KIND.items():
            with self.subTest(kind=kind):
                code, out = run_script(self.declared(("example-service", [kind])))
                self.assertEqual(code, 0)
                self.assertEqual(self.expected_in(out), set(ALWAYS) | {doc})

    def test_a_mix_of_kinds_adds_each_of_their_documents(self):
        """Intent: ticket 172 table: kinds combine, so a deployed, called product expects
        both operations.md and interfaces.md and nothing else extra."""
        code, out = run_script(self.declared(("example-service", ["deployed", "called"])))
        self.assertEqual(code, 0)
        self.assertEqual(self.expected_in(out), set(ALWAYS) | {"operations.md", "interfaces.md"})

    def test_all_four_kinds_expect_all_nine_documents(self):
        """Intent: ticket 172 table: the full set is nine documents."""
        code, out = run_script(self.declared(("example-service", list(PER_KIND))))
        self.assertEqual(code, 0)
        self.assertEqual(self.expected_in(out), set(SECTIONS))

    def test_one_declared_product_lives_in_docs_product(self):
        """Intent: ticket 172 Placement, "a repository with one product uses docs/product/"."""
        code, out = run_script(self.declared(("example-service", [])))
        self.assertEqual(code, 0)
        self.assertIn("example-service", out)
        self.assertIn("docs/product/", out)
        self.assertNotIn("docs/products/", out)

    def test_several_declared_products_each_live_in_their_own_folder(self):
        """Intent: ticket 172 Placement, "more than one uses docs/products/<name>/", and each
        product's expected set is its own."""
        code, out = run_script(self.declared(("example-service", ["deployed"]),
                                             ("example-app", ["ui"])))
        self.assertEqual(code, 0)
        self.assertIn("docs/products/example-service/", out)
        self.assertIn("docs/products/example-app/", out)
        lines = {name: [ln for ln in out.splitlines() if name in ln]
                 for name in ("example-service", "example-app")}
        self.assertTrue(all(lines.values()), "a product has no line of its own")
        service, app = " ".join(lines["example-service"]), " ".join(lines["example-app"])
        self.assertIn("operations.md", service)
        self.assertNotIn("design-system.md", service)
        self.assertIn("design-system.md", app)
        self.assertNotIn("operations.md", app)

    def test_no_declaration_with_a_product_folder_is_one_product_named_after_the_repo(self):
        """Intent: ticket 172 Placement, "no declaration and a docs/product/ folder is one
        product", with the five always documents (build brief step 3); named after the
        repository folder."""
        root = self.repo({"docs/product/architecture.md": "x\n"})
        code, out = run_script(root)
        self.assertEqual(code, 0)
        self.assertIn("example-repo", out)
        self.assertIn("docs/product/", out)
        self.assertEqual(self.expected_in(out), set(ALWAYS))

    def test_neither_a_declaration_nor_a_folder_says_so_and_exits_zero(self):
        """Intent: build brief step 3, "no products declared", exit 0, distinct from a
        product with nothing missing (unknown is not zero)."""
        code, out = run_script(self.repo({"README.md": "x\n"}))
        self.assertEqual(code, 0)
        self.assertIn("no products declared", out)
        self.assertEqual(self.expected_in(out), set())

    def test_a_product_with_nothing_missing_is_not_reported_as_undeclared(self):
        """Intent: build brief step 3, "distinct from a product with nothing missing": a
        product whose five documents all exist exits 0 and does not say `no products
        declared`."""
        root = self.repo({f"docs/product/{doc}": "x\n" for doc in ALWAYS},
                         yaml_text="products:\n  - name: example-service\n    kinds: []\n")
        code, out = run_script(root)
        self.assertEqual(code, 0)
        self.assertNotIn("no products declared", out)
        self.assertIn("example-service", out)

    def test_missing_documents_are_information_and_the_exit_stays_zero(self):
        """Intent: ticket 172 Design constraints, "nothing refuses work for a missing
        document": a product with one document of five exits 0, and its report differs
        from that of a product with all five and says what is missing."""
        yaml_text = "products:\n  - name: example-service\n    kinds: []\n"
        partial = self.repo({"docs/product/security.md": "x\n"}, yaml_text=yaml_text)
        full = self.repo({f"docs/product/{doc}": "x\n" for doc in ALWAYS}, yaml_text=yaml_text)
        code, partial_out = run_script(partial)
        self.assertEqual(code, 0)
        _, full_out = run_script(full)
        self.assertIn("missing", partial_out.casefold())
        self.assertNotEqual(partial_out.replace(str(partial).replace("\\", "/"), ""),
                            full_out.replace(str(full).replace("\\", "/"), ""))


class Refusals(Repo):
    def refused(self, root: Path, *mention: str) -> None:
        code, out = run_script(root)
        self.assertEqual(code, 2, out)
        self.assertNotIn("no products declared", out)
        for text in mention:
            self.assertIn(text, out)

    def test_malformed_yaml_is_refused(self):
        """Intent: build brief step 3, a malformed declaration is refused with exit 2 and
        never reads as "no products"."""
        self.refused(self.repo(yaml_text="products: [unclosed\n  - : :\n"))

    def test_an_unreadable_declaration_is_refused(self):
        """Intent: build brief step 3, an unreadable yaml file is refused with exit 2."""
        root = self.repo()
        (root / "docs" / "products.yaml").mkdir(parents=True)
        self.refused(root)

    def test_a_declaration_with_no_products_list_is_refused(self):
        """Intent: build brief step 3, a missing `products` list is refused."""
        self.refused(self.repo(yaml_text="other: 1\n"), "products")

    def test_a_products_value_that_is_not_a_list_is_refused(self):
        """Intent: build brief step 3, "a missing products list": a `products` that is not a
        list is refused."""
        self.refused(self.repo(yaml_text="products: example-service\n"), "products")

    def test_an_empty_products_list_is_refused(self):
        """Intent: build brief step 3, an empty list is refused, not read as no products."""
        self.refused(self.repo(yaml_text="products: []\n"), "products")

    def test_an_unknown_kind_is_refused_and_named(self):
        """Intent: build brief step 3, an unknown kind is refused, naming it."""
        self.refused(self.declared(("example-service", ["sparkle"])), "sparkle")

    def test_a_duplicate_name_is_refused_and_named(self):
        """Intent: build brief step 3, a duplicate name is refused, naming it."""
        self.refused(self.declared(("example-service", []), ("example-service", ["ui"])),
                     "example-service")

    def test_a_name_failing_the_pattern_is_refused_before_it_reaches_a_path(self):
        """Intent: build brief step 3, "validate every name before it reaches a path": each
        name outside [a-z0-9]+(-[a-z0-9]+)* is refused with exit 2, naming it, with a second
        valid product so the refusal cannot come from the count, and nothing is created."""
        bad = ["Example-Service", "example_service", "../escape", "example--service",
               "-example", "example-", "example service", "example/service", ""]
        for name in bad:
            with self.subTest(name=name):
                root = self.declared(("example-app", []), (name, []))
                before = sorted(p.relative_to(root) for p in root.rglob("*"))
                self.refused(root, *([name] if name else []))
                self.assertEqual(sorted(p.relative_to(root) for p in root.rglob("*")), before)
                self.assertFalse((root.parent / "escape").exists())

    def test_kinds_that_is_not_a_list_is_refused(self):
        """Intent: build brief step 3, a non-list `kinds` is refused."""
        root = self.repo(yaml_text="products:\n  - name: example-service\n    kinds: ui\n")
        self.refused(root, "kinds")


class DesignPartner(unittest.TestCase):
    def test_it_declares_the_product_docs_skill(self):
        """Intent: build brief step 4, `product-docs` is in the design-partner's
        frontmatter `skills:` list."""
        meta = frontmatter(read(DESIGN_PARTNER))
        self.assertIn("product-docs", meta.get("skills") or [])

    def test_it_reads_the_product_documents_and_writes_rationale_to_decisions(self):
        """Intent: ticket 172 Done when, "design-partner names the product's documents: it
        reads them before designing and writes rationale to the product's DECISIONS.md"."""
        job = squash(section(read(DESIGN_PARTNER), "Job"))
        self.assertIn("product-docs", job)
        self.assertIn("DECISIONS.md", job)
        self.assertRegex(job, r"(?i)reads? the product'?s? documents")

    def test_the_planning_documents_line_is_replaced_not_dropped(self):
        """Intent: build brief step 4: the old "planning documents are ruled out as a
        process" wording is gone, while a plan document for the work itself is still ruled
        out and product documents are said not to be plan documents."""
        text = squash(read(DESIGN_PARTNER))
        self.assertNotIn("planning documents are ruled out as a process", text)
        job = squash(section(read(DESIGN_PARTNER), "Job")).casefold()
        self.assertIn("ruled out", job)
        self.assertIn("not plan documents", job)

    def test_the_documents_are_allowed_changed_files_beside_decisions(self):
        """Intent: build brief step 4: "What it writes" and the drift line both allow a
        product's documents alongside DECISIONS.md."""
        text = read(DESIGN_PARTNER)
        writes = squash(section(text, "What it writes")).casefold()
        self.assertIn("decisions.md", writes)
        self.assertIn("product document", writes)
        drift = next(p for p in text.split("\n\n") if "drifted into" in p)
        self.assertIn("DECISIONS.md", drift)
        self.assertIn("product document", squash(drift).casefold())


class NoGateReadsTheDocuments(unittest.TestCase):
    TERMS = ["product-docs", "products.yaml", "docs/product", *[d for d in SECTIONS
                                                                   if d != "DECISIONS.md"]]

    def files(self) -> list[Path]:
        folders = [ROOT / "githooks", ROOT / "skills" / "spec-gate"]
        return [p for folder in folders for p in folder.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts]

    def test_no_gate_or_spec_check_mentions_the_documents(self):
        """Characterisation: ticket 172 Done when, "a search of githooks/ and
        skills/spec-gate/ finding no reference": this passes before the skill exists,
        because nothing reads the documents today, and it guards the build against
        adding a reader."""
        found = [(p.relative_to(ROOT).as_posix(), term) for p in self.files()
                 for term in self.TERMS if term in p.read_text(encoding="utf-8", errors="replace")]
        self.assertEqual(found, [])

    def test_decisions_md_is_not_read_beside_the_product_folder(self):
        """Characterisation: as above, for DECISIONS.md, which a gate may name for another
        reason: it must not appear in a file together with `docs/product`."""
        found = []
        for p in self.files():
            text = p.read_text(encoding="utf-8", errors="replace")
            if "DECISIONS.md" in text and "docs/product" in text:
                found.append(p.relative_to(ROOT).as_posix())
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
