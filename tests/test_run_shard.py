#!/usr/bin/env python3
################################################################################
# File: test_run_shard.py
# Path: {PROJECT_ROOT}/tests/test_run_shard.py
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-08
# Description: Proves the sharded suite runs every test class exactly once: the
#              shards partition the classes. A class no shard runs would look
#              like coverage and run nowhere. Each profile proves its own
#              test-roots declares every shard.
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

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_shard  # noqa: E402

EXERCISES = ["tests/shard_weights.json"]  # read as data


class Assignment(unittest.TestCase):
    def test_every_class_lands_in_exactly_one_shard(self):
        names = [f"mod{i % 3}.Class{i}" for i in range(23)]
        for total in (1, 2, 5, 8, 30):
            with self.subTest(total=total):
                shards = run_shard.assign(names, total)
                flat = [n for shard in shards for n in shard]
                self.assertEqual(sorted(flat), sorted(names))
                self.assertEqual(len(flat), len(set(flat)))

    def test_a_new_class_is_assigned_without_being_named(self):
        before = run_shard.assign(["a.A", "b.B"], 4)
        after = run_shard.assign(["a.A", "b.B", "c.New"], 4)
        self.assertIn("c.New", [n for shard in after for n in shard])
        self.assertEqual(sum(map(len, after)), sum(map(len, before)) + 1)

    def test_heavy_classes_are_spread_not_stacked(self):
        """2026-09-28: by name, SelfRenderGate, Tests and TestsGateParallel shared a shard."""
        weights = {"h.One": 100, "h.Two": 90, "h.Three": 80, **{f"l.L{i}": 1 for i in range(9)}}
        shards = run_shard.assign(list(weights), 3, weights)
        heavy = [sum(1 for n in shard if n.startswith("h.")) for shard in shards]
        self.assertEqual(heavy, [1, 1, 1])

    def test_unweighted_classes_are_still_assigned(self):
        weights = {"a.A": 50}
        shards = run_shard.assign(["a.A", "b.New", "c.New"], 2, weights)
        self.assertEqual(sorted(n for s in shards for n in s), ["a.A", "b.New", "c.New"])


class DeclaredShards(unittest.TestCase):
    def test_bad_spec_is_refused(self):
        for bad in ([], ["0/4"], ["5/4"], ["x"], ["1/4", "2/4"], ["--tests"]):
            with self.subTest(bad=bad):
                self.assertEqual(run_shard.main(bad), 2)


class SlowestClasses(unittest.TestCase):
    """Every push records which classes cost the time, for test selection to learn from."""

    def test_a_shard_names_its_slowest_class_first_with_its_seconds(self):
        """Intent: a shard of two classes, one sleeping, names the sleeping
        class first with its seconds."""
        import time

        def make(name: str, pause: float) -> type:
            # Built here, not at module level, so discovery never runs them as real tests.
            return type(name, (unittest.TestCase,), {"test_it": lambda self: time.sleep(pause)})

        loader = unittest.defaultTestLoader
        found = {"fix.Slow": list(loader.loadTestsFromTestCase(make("Slow", 0.3))),
                 "fix.Quick": list(loader.loadTestsFromTestCase(make("Quick", 0.0)))}

        ok, times = run_shard.run_classes(found, ["fix.Quick", "fix.Slow"])
        lines = run_shard.slowest(times)

        self.assertTrue(ok)
        self.assertRegex(lines[0], r"^timing: +0\.[3-9]\d s  fix\.Slow$")
        self.assertIn("fix.Quick", lines[1])

    def test_every_class_that_ran_is_reported_slowest_first(self):
        """Intent: the report lists every class a push
        ran, so a skipped class can be told from one that passed. Replaces an earlier
        five-slowest cap, which left a fast class absent whether it ran or not."""
        lines = run_shard.slowest({f"m.C{i}": float(i) for i in range(9)})
        self.assertEqual(len(lines), 9)
        self.assertIn("m.C8", lines[0])
        self.assertIn("m.C0", lines[-1])


class SelectedLine(unittest.TestCase):
    """Intent: the report says how many classes ran
    and why, because 'nothing changed' and 'the range was unknown' mean different things."""

    def test_a_narrowed_push_names_its_count_and_changed_files(self):
        self.assertEqual(run_shard.selected_line(12, 113, {"a", "b", "c"}),
                         "selected: 12 of 113 class(es) - 3 changed file(s)")

    def test_no_push_range_says_so(self):
        self.assertEqual(run_shard.selected_line(113, 113, None),
                         "selected: 113 of 113 class(es) - no push range, so all")

    def test_a_change_to_the_selector_itself_is_named_as_the_reason(self):
        """Intent: '71 changed file(s)' did not say the full run
        was forced by the selector changing, which is a different reason from a wide diff."""
        line = run_shard.selected_line(116, 116, {"tests/run_shard.py", "README.md"},
                                       forced=["tests/run_shard.py"])
        self.assertEqual(line, "selected: 116 of 116 class(es) - selection machinery changed "
                               "(tests/run_shard.py), so all")

    def test_classes_missing_from_the_map_are_named(self):
        """Intent: a class added after the last --map run runs on
        every push. Safe, but it erodes the saving silently, so the report names it."""
        line = run_shard.selected_line(7, 116, {"a", "b"}, unmapped=["m.New"])
        self.assertEqual(line, "selected: 7 of 116 class(es) - 2 changed file(s); 1 not in the "
                               "map, run on every push until tests/run_shard.py --map: m.New")

    def test_a_long_unmapped_list_is_capped(self):
        line = run_shard.selected_line(30, 30, None, unmapped=[f"m.C{i:02d}" for i in range(30)])
        self.assertIn("30 not in the map", line)
        self.assertIn("m.C09", line)
        self.assertNotIn("m.C10", line)
        self.assertTrue(line.endswith("and 20 more"), line)


if __name__ == "__main__":
    unittest.main()
