#!/usr/bin/env python3
"""Is every file a pushed range changes rendered output?

    python rendered_only.py <local sha> <remote sha>

Exit 0: every changed file is rendered output (stamped within its first 40 lines) or
.gitignore. Exit 1: not. Exit 2: it could not judge. The shell treats 2 as "not", so an
unknown is never a skip.

The same rules as the per-file loop in rendered_only.sh, but with two git processes in
all, not two or three per file: one `git diff --name-only -z`, one `git cat-file --batch`.
The stamp expression is the one in stamp.sh, and lint_baseline.py's STAMP.
"""
from __future__ import annotations

import re
import subprocess
import sys

TIMEOUT = 600
STAMP_LINES = 40
STAMP = re.compile(rb"generated from [^ @\n]+(@[0-9a-f]{7}| - edit the source)")
ZERO = re.compile(r"^0+$")


class Unknown(Exception):
    """The verdict could not be reached."""


def stamped(content: bytes) -> bool:
    """The stamp sits within the first 40 lines, as `head -n 40 | grep -E` reads it."""
    lines = content.split(b"\n", STAMP_LINES)
    return STAMP.search(b"\n".join(lines[:STAMP_LINES])) is not None


class Batch:
    """One long-running `git cat-file --batch`, asked one name at a time."""

    def __init__(self) -> None:
        try:
            self.proc = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise Unknown(f"git cat-file did not start: {exc}") from exc

    def read(self, spec: str) -> bytes | None:
        """The object's bytes, or None when it does not exist."""
        if "\n" in spec:
            raise Unknown("a path holding a newline cannot be asked of cat-file --batch")
        try:
            self.proc.stdin.write(spec.encode("utf-8") + b"\n")
            self.proc.stdin.flush()
            header = self.proc.stdout.readline()
            if not header:
                raise Unknown("git cat-file ended mid-stream")
            header = header.rstrip(b"\n")
            if header.endswith(b" missing"):
                return None
            parts = header.split(b" ")
            if len(parts) != 3 or not parts[2].isdigit():
                raise Unknown(f"git cat-file answered {header!r}")
            size = int(parts[2])
            data = self.proc.stdout.read(size + 1)
            if len(data) != size + 1:
                raise Unknown("git cat-file ended mid-object")
            return data[:size]
        except (OSError, ValueError) as exc:
            raise Unknown(f"git cat-file failed: {exc}") from exc

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()


def verdict(local: str, remote: str) -> int:
    if not local or not remote or ZERO.match(remote):
        return 1
    try:
        probe = subprocess.run(["git", "cat-file", "-e", f"{remote}^{{commit}}"],
                               capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unknown(f"git did not run: {exc}") from exc
    if probe.returncode != 0:
        return 1
    try:
        diff = subprocess.run(["git", "diff", "--name-only", "-z", remote, local],
                              capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unknown(f"git did not run: {exc}") from exc
    if diff.returncode != 0:
        raise Unknown("git diff failed")
    names = [n.decode("utf-8", errors="surrogateescape") for n in diff.stdout.split(b"\0") if n]
    if not names:
        return 1
    batch = Batch()
    try:
        for name in dict.fromkeys(names):
            if name == ".gitignore":
                continue
            # A deleted file is judged by the side that still has it.
            content = batch.read(f"{local}:{name}")
            if content is None:
                content = batch.read(f"{remote}:{name}")
            if content is None or not stamped(content):
                return 1
        return 0
    finally:
        batch.close()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: rendered_only.py <local sha> <remote sha>", file=sys.stderr)
        return 2
    try:
        return verdict(argv[0], argv[1])
    except Unknown as exc:
        print(f"rendered_only: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
