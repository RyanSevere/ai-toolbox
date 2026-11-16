#!/usr/bin/env python3
################################################################################
# File: locked_example.py
# Path: {PROJECT_ROOT}/tests/locked_example.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: A copy of examples/profile with every gate the core ships
#              consented on, for tests that render from the example. The core
#              now ships gates, and a render refuses without a lock, so the
#              example as shipped (no lock) no longer renders. Not a test file.
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

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import consent  # noqa: E402
import sync  # noqa: E402

_PATH: Path | None = None


def locked_example() -> Path:
    """The example profile, copied once per process, with its features: and profile.lock
    consenting every known gate."""
    global _PATH
    if _PATH is None:
        tmp = Path(tempfile.mkdtemp(prefix="locked-example-"))
        atexit.register(shutil.rmtree, tmp, ignore_errors=True)
        folder = tmp / "profile"
        shutil.copytree(sync.ROOT / "examples" / "profile", folder)
        features = {"gates": {name: True for name in consent.known_gates(folder)}}
        (folder / consent.LOCK_NAME).write_text(consent.render_lock(features), encoding="utf-8",
                                                newline="\n")
        path = folder / consent.PROFILE_NAME
        path.write_text(consent.replace_features_block(
            path.read_text(encoding="utf-8"), consent.render_features_block(features["gates"])),
            encoding="utf-8", newline="\n")
        _PATH = folder
    return _PATH
