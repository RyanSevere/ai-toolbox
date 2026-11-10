#!/usr/bin/env python3
################################################################################
# File: run_shard.py
# Path: {PROJECT_ROOT}/tests/run_shard.py
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-07
# Description: Runs one shard of the test suite: every test class under tests/,
#              assigned longest-first to the lightest shard by the times in
#              shard_weights.json, and this process runs shard K. Each class
#              lands in exactly one shard by construction, so a new class can
#              never go unrun the way a list of names would let it; stale
#              weights cost speed, never coverage. --measure rewrites the
#              weights. The tests gate runs the shards in parallel.
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

import json
import os
import re
import statistics
import sys
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
WEIGHTS = TESTS / "shard_weights.json"
SPEC = re.compile(r"(\d+)/(\d+)")


def classes(suite: unittest.TestSuite) -> dict[str, list[unittest.TestCase]]:
    """Every test, grouped by module.Class. Loader errors count as a class of their
    own, so an import failure fails a shard instead of vanishing from all of them."""
    out: dict[str, list[unittest.TestCase]] = {}
    stack = [suite]
    while stack:
        item = stack.pop()
        if isinstance(item, unittest.TestSuite):
            stack.extend(item)
        else:
            out.setdefault(item.id().rsplit(".", 1)[0], []).append(item)
    return out


def assign(names: list[str], total: int, weights: dict[str, float] | None = None) -> list[list[str]]:
    """Longest first, each into the lightest shard. Round-robin by name put the three
    heaviest classes together on 2026-09-28: one shard took 217 s, another 60 s."""
    weights = weights or {}
    known = [weights[n] for n in names if n in weights]
    default = statistics.median(known) if known else 1.0
    cost = {n: weights.get(n, default) for n in names}
    shards: list[list[str]] = [[] for _ in range(total)]
    load = [0.0] * total
    for name in sorted(names, key=lambda n: (-cost[n], n)):
        lightest = min(range(total), key=lambda i: (load[i], i))
        shards[lightest].append(name)
        load[lightest] += cost[name]
    return shards


def load_weights() -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(WEIGHTS.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, AttributeError):
        return {}  # no weights only unbalances the shards; every class still runs


def measure(found: dict[str, list[unittest.TestCase]]) -> int:
    """Time every class alone and write the weights. Derived, never hand-typed."""
    times: dict[str, float] = {}
    failed = False
    for name in sorted(found):
        start = time.perf_counter()
        result = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, "w")).run(unittest.TestSuite(found[name]))
        times[name] = round(time.perf_counter() - start, 2)
        failed = failed or not result.wasSuccessful()
        print(f"{times[name]:8.2f}s  {name}")
    WEIGHTS.write_text(json.dumps(times, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {WEIGHTS.name}: {len(times)} classes, {sum(times.values()):.1f}s total")
    return 1 if failed else 0


def use(folder: Path) -> None:
    """Point the runner and the selector at one test folder: its weights, its map, and
    paths relative to its parent. A profile runs its own tests/ with the core's runner."""
    global TESTS, WEIGHTS
    TESTS = folder.resolve()
    WEIGHTS = TESTS / "shard_weights.json"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import select_tests
    select_tests.TESTS = TESTS
    select_tests.ROOT = TESTS.parent
    select_tests.DEPMAP = TESTS / "depmap.json"


def main(argv: list[str]) -> int:
    if argv[:1] == ["--tests"] and len(argv) >= 2:
        use(Path(argv[1]))
        argv = argv[2:]
    if argv == ["--measure"]:
        sys.path.insert(0, str(TESTS))
        return measure(classes(unittest.defaultTestLoader.discover(str(TESTS))))
    if argv == ["--map"]:
        sys.path.insert(0, str(TESTS))
        import select_tests
        return select_tests.build_map(classes(unittest.defaultTestLoader.discover(str(TESTS))))
    match = SPEC.fullmatch(argv[0]) if len(argv) == 1 else None
    if not match or not 1 <= int(match[1]) <= int(match[2]):
        print("usage: run_shard.py [--tests DIR] K/N, with 1 <= K <= N  |  --measure  |  "
              "--map", file=sys.stderr)
        return 2
    index, total = int(match[1]), int(match[2])

    sys.path.insert(0, str(TESTS))
    import select_tests
    found = classes(unittest.defaultTestLoader.discover(str(TESTS)))
    # The tests gate exports the push range; anywhere else it is unset and everything runs.
    changed = select_tests.changed_files(os.environ.get("PUSH_LOCAL_SHA", ""),
                                         os.environ.get("PUSH_REMOTE_SHA", ""),
                                         cwd=select_tests.ROOT)
    depmap = select_tests.load_depmap()
    chosen = select_tests.select(list(found), changed, depmap, select_tests.declared(found))
    if index == 1:  # every shard computes the same selection; report it once
        forced = sorted(changed & select_tests.always_all()) if changed else []
        unmapped = [name for name in found if name not in depmap]
        print(selected_line(len(chosen), len(found), changed, forced, unmapped))
    mine = assign(sorted(chosen), total, load_weights())[index - 1]
    print(f"shard {index}/{total}: {len(mine)} class(es)")

    ok, times = run_classes(found, mine)
    for line in slowest(times):
        print(line)
    return 0 if ok else 1


def run_classes(found: dict[str, list[unittest.TestCase]], names: list[str]) -> tuple[bool, dict[str, float]]:
    """Each class as its own run, so its setUpClass is counted in its own time."""
    ok = True
    times: dict[str, float] = {}
    for name in names:
        start = time.perf_counter()
        result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(found[name]))
        times[name] = time.perf_counter() - start
        ok = ok and result.wasSuccessful()
    return ok, times


def slowest(times: dict[str, float]) -> list[str]:
    """A 'timing:' line for every class run, slowest first. The tests gate carries these into
    the gate report, so the report says what a push ran."""
    ranked = sorted(times.items(), key=lambda kv: -kv[1])
    return [f"timing: {seconds:7.2f} s  {name}" for name, seconds in ranked]


def selected_line(chosen: int, total: int, changed: set[str] | None,
                  forced: list[str] | None = None, unmapped: list[str] | None = None) -> str:
    """The selector's decision, for the gate report: how many ran, on what basis, and which
    classes ran only because the map has never seen them - a stale map shows here."""
    if changed is None:
        why = "no push range, so all"
    elif forced:
        why = f"selection machinery changed ({', '.join(sorted(forced))}), so all"
    else:
        why = f"{len(changed)} changed file(s)"
    line = f"selected: {chosen} of {total} class(es) - {why}"
    if unmapped:
        names = sorted(unmapped)
        shown = ", ".join(names[:10]) + (f" and {len(names) - 10} more" if len(names) > 10 else "")
        line += (f"; {len(names)} not in the map, run on every push until "
                 f"tests/run_shard.py --map: {shown}")
    return line


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
