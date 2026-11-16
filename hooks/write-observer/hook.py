#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.cursor/hooks/write-observer/hook.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: Agent hook on file.write.after, Claude Code only. Warns the
#              agent when a file it just wrote holds a credential shape, naming
#              the file, the line and the shape and never the text. It loads
#              the push gate's own shapes from the rendered
#              .githooks/lib/secret_shapes.py at the repository root, so the
#              two cannot disagree. It never blocks, and it does nothing when
#              the module is not rendered or anything at all fails. Design in
#              hooks/README.md.
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

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# The shared library renders beside the hooks, in a folder next to this one.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import hookio  # noqa: E402

NAME = "write-observer"

# Where the push gate's shapes render in a target, from the repository root.
MODULE = Path(".githooks") / "lib" / "secret_shapes.py"
# Bytes read and hits named, so a huge or minified file cannot flood the session.
MAX_BYTES = 4 * 1024 * 1024
MAX_HITS = 20


def repository_root(start: Path) -> Path | None:
    """The repository holding start: what git says, else the nearest folder above it with .git."""
    try:
        done = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start,
                              capture_output=True, text=True, timeout=5, check=False)
        top = done.stdout.strip()
        if done.returncode == 0 and top:
            return Path(top)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def load_shapes(root: Path):
    """The repository's rendered secret_shapes module, loaded by path, or None."""
    path = root / MODULE
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("secret_shapes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def warning(path: str, hits: list[tuple[int, str]]) -> str:
    named = "\n".join(f"  {path}:{line}: {shape}" for line, shape in hits[:MAX_HITS])
    more = len(hits) - MAX_HITS
    if more > 0:
        named += f"\n  ... and {more} more"
    return (f"{NAME}: {path} was written with {len(hits)} credential-shaped line(s):\n{named}\n"
            "The text is not repeated here. If it is a real secret, move it to an untracked .env "
            "and rotate it if it has been shared. If it is not a secret, add "
            "'secret-scan: allow' to the line. The push gate refuses these lines unless "
            "it is added.")


def observe(seen: dict) -> str | None:
    try:
        path, cwd = seen["path"], seen.get("cwd")
        if not isinstance(path, str) or not path:
            return None
        target = Path(path)
        if not target.is_absolute():
            if not isinstance(cwd, str) or not os.path.isabs(cwd):
                return None
            target = Path(cwd) / target
        if not target.is_file():
            return None
        start = Path(cwd) if isinstance(cwd, str) and os.path.isabs(cwd) else target.parent
        root = repository_root(start)
        shapes = load_shapes(root) if root else None
        if shapes is None:
            return None
        with open(target, "rb") as handle:
            text = handle.read(MAX_BYTES).decode("utf-8", errors="replace")
        hits = shapes.find(text.splitlines())
        return warning(path, hits) if hits else None
    except Exception:  # noqa: BLE001 - an observer fails open on anything at all
        return None


def main() -> int:
    sys.dont_write_bytecode = True
    return hookio.run_observer(NAME, "file.write.after", observe)


if __name__ == "__main__":
    sys.exit(main())
