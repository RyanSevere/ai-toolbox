#!/usr/bin/env python3
################################################################################
# File: select_tests.py
# Path: {PROJECT_ROOT}/tests/select_tests.py
# Created by: Ryan Severe
# Created: 2026-10-01
# Last Updated: 2026-11-07
# Description: Chooses which test classes a push runs. A class
#              runs when its own file, a dependency coverage measured for it,
#              or a path it declares in EXERCISES changed, or when the map has
#              never seen it. An unknown change set, or a change to the
#              selection machinery itself, runs everything. Also builds the
#              map: every class under coverage, child processes included.
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

import fnmatch
import json
import os
import site
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path, PurePath

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
DEPMAP = TESTS / "depmap.json"

def always_all() -> frozenset[str]:
    """A change to any of these alters what is selected, so the old map cannot be trusted to
    judge it. Relative to ROOT, which a profile's suite moves above the core."""
    here = Path(__file__).resolve().parent
    files = (here / "select_tests.py", here / "run_shard.py", DEPMAP)
    return frozenset({PurePath(os.path.relpath(f, ROOT)).as_posix() for f in files}
                     | {".github/test-roots"})


def select(names: list[str], changed: set[str] | None, depmap: dict[str, list[str]],
           declared: dict[str, list[str]]) -> set[str]:
    """The classes this change set could affect. None means the change set is unknown."""
    if changed is None or changed & always_all():
        return set(names)
    chosen = set()
    for name in names:
        if name not in depmap:
            chosen.add(name)
            continue
        own = f"tests/{name.split('.', 1)[0]}.py"
        if changed & ({own} | set(depmap[name])):
            chosen.add(name)
        elif any(fnmatch.fnmatchcase(path, pattern)
                 for pattern in declared.get(name, ()) for path in changed):
            chosen.add(name)
    return chosen


def _outside_roots() -> list[str]:
    paths = sysconfig.get_paths()
    roots = {paths["stdlib"], paths["platstdlib"], paths["purelib"], paths["platlib"],
             sys.prefix, sys.base_prefix, site.getusersitepackages()}
    return sorted({os.path.normcase(os.path.abspath(r)) for r in roots if r})


def repo_relative(path: str, root: Path, tracked: set[str]) -> str | None:
    """A measured file as a tracked repository path, or None if it is not one.

    Tests run sync.py from temporary copies, so the longest suffix of the path
    that names a tracked file is taken. Interpreter and installed-package files
    are dropped first: `json/__init__.py` must never match a tracked `__init__.py`.
    """
    norm = os.path.normcase(os.path.abspath(path))
    if any(norm == r or norm.startswith(r + os.sep) for r in _outside_roots()):
        return None
    base = os.path.normcase(os.path.abspath(root))
    if norm.startswith(base + os.sep):
        rel = PurePath(os.path.relpath(path, root)).as_posix()
        return rel if rel in tracked else None
    parts = PurePath(path).parts
    for i in range(1, len(parts)):
        suffix = "/".join(parts[i:])
        if suffix in tracked:
            return suffix
    return None


def changed_files(local: str, remote: str, cwd: Path = ROOT,
                  env: dict[str, str] | None = None) -> set[str] | None:
    """Files the push range touches, or None when there is no range to judge."""
    if not local or not remote or not remote.strip("0"):
        return None

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(("git", *args), cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=60)

    if git("cat-file", "-e", f"{remote}^{{commit}}").returncode != 0:
        return None
    # Relative to cwd, as git ls-files and the map are: the core's tests sit in core/tests
    # inside a profile, and a repo-root path would match nothing in their map.
    diff = git("diff", "--name-only", "--relative", remote, local)
    if diff.returncode != 0:
        return None
    return {line for line in diff.stdout.splitlines() if line}


def declared(found: dict[str, list[unittest.TestCase]]) -> dict[str, list[str]]:
    """EXERCISES patterns per class. A class's own list replaces its module's, so one slow
    class in a file of render tests can depend on less than its neighbours."""
    out: dict[str, list[str]] = {}
    for name, cases in found.items():
        cls = type(cases[0])
        own = getattr(cls, "EXERCISES", None)
        module = sys.modules.get(cls.__module__)
        out[name] = list(own if own is not None else getattr(module, "EXERCISES", ()))
    return out


def load_depmap() -> dict[str, list[str]]:
    try:
        data = json.loads(DEPMAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # no map: every class is unseen, so every class runs
    return data if isinstance(data, dict) else {}


SITECUSTOMIZE = "import coverage\ncoverage.process_startup()\n"


def build_map(found: dict[str, list[unittest.TestCase]]) -> int:
    """Run every class alone under coverage, child processes included, and write the map."""
    import coverage

    listed = subprocess.run(("git", "ls-files"), cwd=ROOT, capture_output=True, text=True,
                            timeout=60, check=True)
    tracked = set(listed.stdout.splitlines())
    depmap: dict[str, list[str]] = {}
    failed = False
    saved = {k: os.environ.get(k) for k in ("PYTHONPATH", "COVERAGE_PROCESS_START")}
    with tempfile.TemporaryDirectory() as work:
        hook = Path(work) / "hook"
        hook.mkdir()
        (hook / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        try:
            for index, name in enumerate(sorted(found)):
                data = Path(work) / str(index)
                data.mkdir()
                rc = data / "coveragerc"
                rc.write_text(f"[run]\nparallel = true\ndata_file = {data.as_posix()}/.coverage\n",
                              encoding="utf-8")
                os.environ["COVERAGE_PROCESS_START"] = str(rc)
                os.environ["PYTHONPATH"] = os.pathsep.join(
                    filter(None, (str(hook), saved["PYTHONPATH"])))
                cov = coverage.Coverage(config_file=str(rc))
                cov.start()
                try:
                    result = unittest.TextTestRunner(
                        verbosity=0, stream=open(os.devnull, "w")).run(unittest.TestSuite(found[name]))
                finally:
                    cov.stop()
                    cov.save()
                failed = failed or not result.wasSuccessful()
                merged = coverage.Coverage(config_file=str(rc))
                merged.combine([str(data)])
                measured = merged.get_data().measured_files()
                depmap[name] = sorted({r for f in measured
                                       if (r := repo_relative(f, ROOT, tracked))})
                print(f"{len(depmap[name]):4d} file(s)  {name}")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    if failed:
        print("NOT WRITTEN: a class failed, so its map would describe a broken run.")
        return 1
    DEPMAP.write_text(json.dumps(depmap, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {DEPMAP.name}: {len(depmap)} classes")
    return 0
