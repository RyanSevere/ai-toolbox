#!/usr/bin/env python3
################################################################################
# File: expected_docs.py
# Path: {PROJECT_ROOT}/skills/product-docs/expected_docs.py
# Created by: Ryan Severe
# Created: 2026-11-23
# Last Updated: 2026-11-23
# Description: Derives, for a consuming repository, which product documents each
#              product is expected to carry, from docs/products.yaml or from a
#              docs/product/ folder, and reports which are present or missing.
#              Information only: a missing document never changes the exit code.
#              A malformed declaration is refused with exit 2, never read as
#              "no products".
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
import sys
from pathlib import Path

import yaml

NAME_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
ALWAYS = ["product-requirements.md", "architecture.md", "security.md", "testing.md",
          "DECISIONS.md"]
PER_KIND = {"deployed": "operations.md", "ui": "design-system.md",
            "datastore": "database.md", "called": "interfaces.md"}
DECLARATION = Path("docs") / "products.yaml"
SINGLE_FOLDER = Path("docs") / "product"
MULTI_FOLDER = Path("docs") / "products"


class Refused(Exception):
    """A declaration that cannot be trusted. Carries the message naming the problem."""


def expected_for(kinds: list[str]) -> list[str]:
    """The documents a product of these kinds is expected to carry, in a stable order."""
    return ALWAYS + [doc for kind, doc in PER_KIND.items() if kind in kinds]


def load_declaration(path: Path) -> list[dict]:
    """The validated product entries of a products.yaml, or Refused."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Refused(f"{path.as_posix()} is unreadable: {exc}") from exc
    except yaml.YAMLError as exc:
        raise Refused(f"{path.as_posix()} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or "products" not in data:
        raise Refused(f"{path.as_posix()} has no `products` list")
    products = data["products"]
    if not isinstance(products, list):
        raise Refused(f"`products` in {path.as_posix()} is not a list")
    if not products:
        raise Refused(f"`products` in {path.as_posix()} is an empty list")
    seen: set[str] = set()
    entries: list[dict] = []
    for index, entry in enumerate(products, start=1):
        if not isinstance(entry, dict):
            raise Refused(f"products entry {index} is not a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise Refused(f"product name {name!r} in entry {index} does not match "
                          f"[a-z0-9]+(-[a-z0-9]+)*")
        if name in seen:
            raise Refused(f"product name {name!r} is declared more than once")
        seen.add(name)
        kinds = entry.get("kinds", [])
        if not isinstance(kinds, list):
            raise Refused(f"`kinds` of product {name!r} is not a list")
        for kind in kinds:
            if not isinstance(kind, str) or kind not in PER_KIND:
                raise Refused(f"product {name!r} has unknown kind {kind!r}; "
                              f"known kinds: {', '.join(PER_KIND)}")
        entries.append({"name": name, "kinds": kinds})
    return entries


def find_products(root: Path) -> list[dict] | None:
    """Each product as {name, kinds, folder}, or None when nothing is declared.

    Raises Refused for a declaration that is present and malformed.
    """
    declaration = root / DECLARATION
    if declaration.exists():
        entries = load_declaration(declaration)
        if len(entries) == 1:
            return [{**entries[0], "folder": SINGLE_FOLDER}]
        return [{**entry, "folder": MULTI_FOLDER / entry["name"]} for entry in entries]
    if (root / SINGLE_FOLDER).is_dir():
        return [{"name": root.resolve().name, "kinds": [], "folder": SINGLE_FOLDER}]
    return None


def report_line(root: Path, product: dict) -> str:
    """One line: name, folder, expected documents, and the present and missing ones."""
    expected = expected_for(product["kinds"])
    present = [doc for doc in expected if (root / product["folder"] / doc).is_file()]
    missing = [doc for doc in expected if doc not in present]
    return (f"{product['name']} | {product['folder'].as_posix()}/ | "
            f"expected: {', '.join(expected)} | "
            f"present: {', '.join(present) or 'none'} | "
            f"missing: {', '.join(missing) or 'none'}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: expected_docs.py [repo root]", file=sys.stderr)
        return 2
    root = Path(args[0] if args else ".")
    try:
        products = find_products(root)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if products is None:
        print("no products declared")
        return 0
    for product in products:
        print(report_line(root, product))
    return 0


if __name__ == "__main__":
    sys.exit(main())
