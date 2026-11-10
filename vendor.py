################################################################################
# File: vendor.py
# Path: {PROJECT_ROOT}/vendor.py
# Created by: Ryan Severe
# Created: 2026-10-28
# Last Updated: 2026-11-07
# Description: The vendored core a profile renders with. Validates
#              an <owner>/<repo>@<tag-or-sha> source before it reaches a URL,
#              hashes core/ byte for byte, checks core/VENDORED offline,
#              fetches, validates and atomically swaps in a pinned core, and
#              lists newer release tags without changing anything.
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

import hashlib
import http.client
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CORE_DIR = "core"
VENDORED = "VENDORED"
GITATTRIBUTES = ".gitattributes"
# The hash is of the archive's exact bytes. Git converting line endings on a Windows
# checkout would make every clone there read as locally edited.
GITATTRIBUTES_TEXT = "* -text\n"
# Running `python core/sync.py` writes these; they are caches, not the vendored copy.
NOT_HASHED_DIRS = frozenset({"__pycache__"})

# GitHub's own limits: 1-39 characters, alphanumeric or single hyphens, no hyphen at
# either end. Repository names: letters, digits, '.', '_', '-', never '.' or '..'.
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}")
TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
# Full length only: a short SHA can become ambiguous, and VENDORED records the full one.
SHA = re.compile(r"[0-9a-f]{40}")
CONTENT_HASH = re.compile(r"sha256:[0-9a-f]{64}")
KEYS = ("source", "tag", "sha", "content-hash")

API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
TIMEOUT = 30
# The archive is held in memory, so the cap bounds the read.
MAX_DOWNLOAD = 50 * 1024 * 1024
MAX_UNPACKED = 200 * 1024 * 1024
# Built beside core/ inside the profile, so every swap is a rename on one volume.
INCOMING = ".core-incoming-"
OUTGOING = ".core-outgoing-"
TAGS_PER_PAGE = 100
# Past this many pages the tag list is not known to be complete, so the answer is unknown.
MAX_TAG_PAGES = 10

Fetch = Callable[[str, str], bytes]
"""(url, Accept header) -> body. Raises VendorError on any failure; tests inject a fake."""


class VendorError(Exception):
    """A refusal. The message names what was wrong."""


class LookupFailed(VendorError):
    """The remote could not be read, so the answer is unknown - never "up to date"."""


@dataclass(frozen=True)
class Source:
    """A validated <owner>/<repo>@<ref>. Only parse_source builds one."""

    owner: str
    repo: str
    ref: str

    @property
    def is_tag(self) -> bool:
        """True for a vX.Y.Z tag, False for a full SHA."""
        return TAG.fullmatch(self.ref) is not None

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}@{self.ref}"


@dataclass(frozen=True)
class Record:
    """What core/VENDORED holds. `tag` is empty when the core was vendored by SHA."""

    source: str
    tag: str
    sha: str
    content_hash: str


def parse_source(text: str) -> Source:
    """<owner>/<repo>@<vX.Y.Z or 40-hex SHA>, refused on any deviation.

    Every part ends up in a URL, so nothing outside the fixed character sets passes:
    no slash, query, fragment, whitespace or path segment can be smuggled in.
    """
    shape = f"source {text!r} is not <owner>/<repo>@<vX.Y.Z or full SHA>"
    if not isinstance(text, str) or text.count("@") != 1:
        raise VendorError(shape)
    name, ref = text.split("@")
    if name.count("/") != 1:
        raise VendorError(shape)
    owner, repo = name.split("/")
    if not OWNER.fullmatch(owner):
        raise VendorError(f"{shape}: owner {owner!r} is not a GitHub account name")
    if not REPO.fullmatch(repo) or repo in (".", ".."):
        raise VendorError(f"{shape}: repository {repo!r} is not a GitHub repository name")
    if not (TAG.fullmatch(ref) or SHA.fullmatch(ref)):
        raise VendorError(f"{shape}: ref {ref!r} is neither a vX.Y.Z tag nor a full "
                          "40-character lowercase SHA")
    return Source(owner, repo, ref)


def _hashed_files(core: Path) -> list[tuple[str, Path]]:
    """Every file under core/ that the hash covers, as (POSIX relative path, path), sorted.

    A symbolic link is refused rather than followed or skipped: an archive extracts none,
    so one is an edit, and following it would hash something outside core/.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(core, followlinks=False):
        for name in dirnames + filenames:
            if Path(dirpath, name).is_symlink():
                raise VendorError(f"{Path(dirpath, name)} is a symbolic link; a vendored "
                                  "core holds none")
        dirnames[:] = [d for d in dirnames if d not in NOT_HASHED_DIRS]
        for name in filenames:
            path = Path(dirpath, name)
            rel = path.relative_to(core).as_posix()
            if rel != VENDORED:
                found.append((rel, path))
    return sorted(found)


def content_hash(core: Path) -> str:
    """sha256 over core/'s exact bytes, VENDORED and __pycache__ excepted.

    Each file contributes its relative path, its length and its bytes, each framed, so
    moving bytes between files or renaming one changes the hash.
    """
    digest = hashlib.sha256()
    for rel, path in _hashed_files(core):
        data = path.read_bytes()
        digest.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode("ascii") + b"\0")
        digest.update(data)
    return "sha256:" + digest.hexdigest()


def format_record(record: Record) -> str:
    """VENDORED's text. key=value lines, the same shape as .githooks/gate-config."""
    return ("# Written by sync.py --vendor-core. Never edit it, or core/:"
            " --check-core compares the two.\n"
            f"source={record.source}\n"
            f"tag={record.tag}\n"
            f"sha={record.sha}\n"
            f"content-hash={record.content_hash}\n")


def read_record(core: Path) -> Record:
    """Parse core/VENDORED. Missing, unreadable or malformed is a refusal, never a blank."""
    path = core / VENDORED
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise VendorError(f"{path} is missing, so there is nothing to check core/ against. "
                          "Vendor the core with --vendor-core.") from None
    except (OSError, UnicodeDecodeError) as error:
        raise VendorError(f"{path} is unreadable: {error}") from None
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in KEYS:
            raise VendorError(f"{path}:{number}: unexpected line {line!r}")
        if key in values:
            raise VendorError(f"{path}:{number}: {key} is given twice")
        values[key] = value
    missing = [key for key in KEYS if key not in values]
    if missing:
        raise VendorError(f"{path} has no {', '.join(missing)}")
    try:
        parse_source(f"{values['source']}@{values['sha']}")
    except VendorError as error:
        raise VendorError(f"{path}: {error}") from None
    if values["tag"] and not TAG.fullmatch(values["tag"]):
        raise VendorError(f"{path}: tag {values['tag']!r} is not vX.Y.Z")
    if not CONTENT_HASH.fullmatch(values["content-hash"]):
        raise VendorError(f"{path}: content-hash {values['content-hash']!r} is not "
                          "sha256:<64 hex>")
    return Record(values["source"], values["tag"], values["sha"], values["content-hash"])


def check_core(core: Path) -> Record:
    """Raise unless core/ is exactly what VENDORED recorded. Never touches the network."""
    if not core.is_dir():
        raise VendorError(f"{core} does not exist, so no core is vendored here")
    record = read_record(core)
    attributes = core / GITATTRIBUTES
    if not attributes.is_file() or attributes.read_bytes() != GITATTRIBUTES_TEXT.encode():
        raise VendorError(f"{attributes} is missing or changed. It must be exactly "
                          f"{GITATTRIBUTES_TEXT.strip()!r}, or git rewrites line endings "
                          "and the hash cannot match.")
    actual = content_hash(core)
    if actual != record.content_hash:
        raise VendorError(f"{core} differs from what was vendored ({record.content_hash}, "
                          f"now {actual}). A vendored core is never edited in place: "
                          "re-vendor it, or make the change in the core's own repository.")
    return record


def check_report(core: Path) -> int:
    """--check-core: one line, exit 0 only when core/ matches VENDORED."""
    try:
        record = check_core(core)
    except VendorError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    version = record.tag or "by SHA"
    print(f"[OK] core/ matches VENDORED: {record.source} {version} {record.sha[:12]}")
    return 0


def http_get(url: str, accept: str) -> bytes:
    """GET url with an explicit timeout and no credentials. Any failure is a refusal."""
    request = urllib.request.Request(url, headers={"Accept": accept,
                                                   "User-Agent": "ai-toolbox-vendor"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_DOWNLOAD + 1)
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise VendorError(f"could not fetch {url}: {error}") from None
    _refuse_oversize(body, url)
    return body


def _refuse_oversize(body: bytes, url: str) -> None:
    if len(body) > MAX_DOWNLOAD:
        raise VendorError(f"{url} returned more than {MAX_DOWNLOAD} bytes; refusing it")


def resolve_sha(source: Source, fetch: Fetch) -> str:
    """The full SHA source names. A tag is asked of GitHub, and the answer is validated."""
    if not source.is_tag:
        return source.ref
    url = f"{API}/repos/{source.owner}/{source.repo}/commits/{source.ref}"
    answer = fetch(url, "application/vnd.github.sha").decode("ascii", "replace").strip()
    if not SHA.fullmatch(answer):
        raise VendorError(f"{url} answered {answer[:80]!r}, not a full SHA")
    return answer


def _archive_files(archive: bytes) -> list[tuple[str, bytes]]:
    """Every file in a codeload archive as (path under its top folder, bytes).

    The whole archive is checked and read before anything is written, so a refusal
    leaves nothing behind. Only plain files and folders under one top-level folder pass.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            return _read_members(tar)
    except (tarfile.TarError, OSError, EOFError, zlib.error) as error:
        raise VendorError(f"the downloaded archive is unreadable: {error}") from None


def _read_members(tar: tarfile.TarFile) -> list[tuple[str, bytes]]:
    top = None
    files: list[tuple[str, bytes]] = []
    # Case-folded: a core must check out on Windows, where two such paths are one file.
    seen: set[str] = set()
    total = 0
    for member in tar:
        name = member.name.rstrip("/") if member.isdir() else member.name
        parts = name.split("/")
        # ':' is a drive on Windows, or an alternate data stream after a file name.
        if "\\" in name or ":" in name or any(p in ("", ".", "..") for p in parts):
            raise VendorError(f"archive member {member.name!r} is not a plain relative path")
        if not (member.isfile() or member.isdir()):
            raise VendorError(f"archive member {name!r} is a link or special file; "
                              "a vendored core holds neither")
        if top is None:
            top = parts[0]
        elif parts[0] != top:
            raise VendorError(f"the archive has more than one top-level entry: {top!r} "
                              f"and {parts[0]!r}")
        rel = "/".join(parts[1:])
        if not rel or member.isdir():
            continue
        if rel == VENDORED:
            raise VendorError(f"the archive carries {VENDORED}, which only --vendor-core "
                              "writes")
        if rel.casefold() in seen:
            raise VendorError(f"the archive holds {rel!r} twice, or two paths that differ "
                              "only in case")
        seen.add(rel.casefold())
        total += member.size
        if total > MAX_UNPACKED:
            raise VendorError(f"the archive unpacks to more than {MAX_UNPACKED} bytes; "
                              "refusing it")
        files.append((rel, tar.extractfile(member).read()))
    if not files:
        raise VendorError("the archive holds no files")
    return files


def _build(incoming: Path, source: Source, sha: str,
           files: list[tuple[str, bytes]]) -> tuple[Record, list[str]]:
    """Write the new core into incoming/ with its .gitattributes and VENDORED, and check it."""
    notes = []
    for rel, data in files:
        if rel == GITATTRIBUTES:
            notes.append(f"the archive's own {GITATTRIBUTES} was replaced with "
                         f"{GITATTRIBUTES_TEXT.strip()!r}")
            continue
        path = incoming / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (incoming / GITATTRIBUTES).write_bytes(GITATTRIBUTES_TEXT.encode())
    record = Record(f"{source.owner}/{source.repo}", source.ref if source.is_tag else "",
                    sha, content_hash(incoming))
    (incoming / VENDORED).write_bytes(format_record(record).encode("utf-8"))
    check_core(incoming)
    return record, notes


def _swap(incoming: Path, core: Path) -> list[str]:
    """Move incoming/ to core/, keeping the old core/ until the new one is in place."""
    outgoing = None
    if core.exists():
        outgoing = core.parent / (OUTGOING + incoming.name[len(INCOMING):])
        try:
            core.rename(outgoing)
        except OSError as error:
            raise VendorError(f"could not move {core} aside, so nothing changed: "
                              f"{error}") from None
    try:
        incoming.rename(core)
    except OSError as error:
        if outgoing is None:
            raise VendorError(f"could not move the new core into {core}: {error}") from None
        try:
            outgoing.rename(core)
        except OSError as again:
            raise VendorError(f"could not move the new core into {core} ({error}), nor the "
                              f"previous one back ({again}). Rename {outgoing} to {core} "
                              "by hand.") from None
        raise VendorError(f"could not move the new core into {core}; the previous one is "
                          f"restored: {error}") from None
    if outgoing is not None:
        shutil.rmtree(outgoing, ignore_errors=True)
        if outgoing.exists():
            return [f"the previous core is left at {outgoing}; delete it by hand"]
    return []


def vendor_core(profile: Path, text: str, fetch: Fetch) -> tuple[Record, list[str]]:
    """Replace <profile>/core/ with the core text names, and record it in core/VENDORED.

    The source is validated before any call, and an existing core/ must match its record
    before anything is fetched, so a local edit is never overwritten. The new core is
    built and checked beside the old one, and only then swapped in.
    """
    source = parse_source(text)
    core = profile / CORE_DIR
    if core.exists() or core.is_symlink():
        try:
            check_core(core)
        except VendorError as error:
            raise VendorError(f"refusing to replace {core}: {error}") from None
    sha = resolve_sha(source, fetch)
    url = f"{CODELOAD}/{source.owner}/{source.repo}/tar.gz/{sha}"
    archive = fetch(url, "application/x-gzip")
    _refuse_oversize(archive, url)
    files = _archive_files(archive)
    incoming = Path(tempfile.mkdtemp(prefix=INCOMING, dir=profile))
    try:
        record, notes = _build(incoming, source, sha, files)
        notes += _swap(incoming, core)
    except OSError as error:
        raise VendorError(f"could not build the new core in {incoming}: {error}") from None
    finally:
        shutil.rmtree(incoming, ignore_errors=True)
        if incoming.exists():
            print(f"[WARN] could not remove {incoming}; delete it by hand", file=sys.stderr)
    return record, notes


def vendor_report(profile: Path, text: str, fetch: Fetch | None = None) -> int:
    """--vendor-core: one [OK] line on success; any refusal is one [ERROR] line, exit 1."""
    try:
        record, notes = vendor_core(profile, text, fetch or http_get)
    except VendorError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    for note in notes:
        print(f"[NOTE] {note}")
    version = record.tag or "by SHA"
    print(f"[OK] vendored {record.source} {version} {record.sha[:12]} into "
          f"{profile / CORE_DIR}")
    return 0


@dataclass(frozen=True)
class Updates:
    """What --check-updates found. `newer` is newest first; any warning makes it unknown."""

    record: Record
    newer: list[str]
    latest: str | None
    warnings: list[str]


def _version(tag: str) -> tuple[int, int, int]:
    major, minor, patch = tag[1:].split(".")
    return int(major), int(minor), int(patch)


def release_tags(source: Source, fetch: Fetch) -> dict[str, str]:
    """Every vX.Y.Z tag on the source repository, name -> commit SHA.

    Other tag names are skipped. Anything that leaves the list in doubt - a failed call,
    an answer that is not a tag list, a release with no valid SHA, more pages than the
    cap - is LookupFailed, because a partial list could hide the newest release.
    """
    tags: dict[str, str] = {}
    for page in range(1, MAX_TAG_PAGES + 1):
        url = (f"{API}/repos/{source.owner}/{source.repo}/tags"
               f"?per_page={TAGS_PER_PAGE}&page={page}")
        try:
            entries = json.loads(fetch(url, "application/vnd.github+json"))
        except VendorError as error:
            raise LookupFailed(str(error)) from None
        except ValueError as error:
            raise LookupFailed(f"{url} did not return JSON: {error}") from None
        if not isinstance(entries, list):
            raise LookupFailed(f"{url} did not return a list of tags")
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str):
                raise LookupFailed(f"{url} returned a tag with no name: {entry!r:.80}")
            if not TAG.fullmatch(name):
                continue
            commit = entry.get("commit")
            sha = commit.get("sha") if isinstance(commit, dict) else None
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise LookupFailed(f"{url} returned release {name} with no valid commit SHA")
            tags[name] = sha
        if len(entries) < TAGS_PER_PAGE:
            return tags
    raise LookupFailed(f"{source.owner}/{source.repo} has more than "
                       f"{MAX_TAG_PAGES * TAGS_PER_PAGE} tags, so the list is not known "
                       "to be complete")


def check_updates(core: Path, fetch: Fetch) -> Updates:
    """Compare core/VENDORED with the source's release tags. Changes nothing."""
    record = read_record(core)
    source = parse_source(f"{record.source}@{record.sha}")
    tags = release_tags(source, fetch)
    ordered = sorted(tags, key=_version, reverse=True)
    newer: list[str] = []
    warnings: list[str] = []
    if record.tag:
        if record.tag not in tags:
            warnings.append(f"{record.tag} is no longer a release tag on {record.source}, "
                            "so this copy matches no release")
        elif tags[record.tag] != record.sha:
            warnings.append(f"{record.tag} now points at {tags[record.tag][:12]}, not the "
                            f"vendored {record.sha[:12]}: the release was moved")
        newer = [name for name in ordered if _version(name) > _version(record.tag)]
    return Updates(record, newer, ordered[0] if ordered else None, warnings)


def updates_report(core: Path, fetch: Fetch | None = None) -> int:
    """--check-updates. Exit 0 up to date, 1 refused, 2 newer available, 3 unknown.

    "Could not check" never shares a code with "up to date".
    """
    try:
        result = check_updates(core, fetch or http_get)
    except LookupFailed as error:
        print(f"[UNKNOWN] could not check for updates: {error}. Whether a newer release "
              "exists is unknown.", file=sys.stderr)
        return 3
    except VendorError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    record = result.record
    for warning in result.warnings:
        print(f"[WARN] {warning}")
    if not record.tag:
        print(f"[UNKNOWN] vendored by SHA {record.sha[:12]}, so whether a release is newer "
              f"is unknown. Newest release on {record.source}: "
              f"{result.latest or 'none'}")
        return 3
    if result.newer:
        print(f"[UPDATE] {len(result.newer)} release(s) newer than {record.tag} on "
              f"{record.source}: {', '.join(result.newer)}")
    if result.warnings:
        print(f"[UNKNOWN] {record.tag} cannot be confirmed as a release, so whether this "
              "copy is current is unknown")
        return 3
    if result.newer:
        return 2
    print(f"[OK] up to date: {record.tag} is the newest release on {record.source}")
    return 0
