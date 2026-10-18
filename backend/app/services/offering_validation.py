"""Content-based validation for Offering files.

**This module performs structural validation. It is not a malware
scanner and must never be described as one.** It answers one question:
*is this file genuinely the kind of thing it claims to be, and is its
structure safe to hand to a purchaser?* A file that passes has not
been checked for malware, because nothing here checks for malware. The
validation record (``checks_performed``) says exactly which checks ran,
so that claim is backed by data rather than by assumption.

Why a signature table rather than a dependency
----------------------------------------------

The format set is small, fixed and already enumerated in
``offering_files.OFFERING_ALLOWED_TYPES``. A hand-written table is
sixty lines, has no system library behind it (``python-magic`` needs
``libmagic`` installed on the Render image), and is directly testable
against genuine fixtures. Approved as the preferred approach.

The three-way agreement rule
----------------------------

Phase A compared the *declared* content type against the extension.
Both of those come from the uploader, so a renamed executable passed.
Validation here adds the only value that does not: the bytes. A file is
accepted only when **signature, extension and declared type all
agree**. Any disagreement is a rejection — not a correction — because
a mismatch is a stronger signal than any single value.

Budgets are enforced, not assumed
---------------------------------

Every inspection runs inside an :class:`InspectionBudget`: a byte
ceiling, a wall-clock ceiling and an entry ceiling, all checked inside
the loops rather than estimated in advance. A 100 MB archive is *not*
assumed to take a few seconds. If a file cannot be inspected within
the budget it is **rejected**, with a message saying so — never
approved on a partial result, and never left in limbo.
"""

from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Iterable

from app.services.offering_files import (
    LEGACY_OFFICE_EXTENSIONS,
    MACRO_EXTENSIONS,
    OFFERING_ALLOWED_TYPES,
    OFFERING_FORBIDDEN_EXTENSIONS,
    all_extensions,
)

# ---------------------------------------------------------------------------
# Policy version
# ---------------------------------------------------------------------------

#: The identity of the current required-check set.
#:
#: Stored on every validated file. When the policy changes this is
#: bumped, which is what lets a later reader tell "passed under policy
#: 1" from "passed under policy 2" without inferring it from dates —
#: and what lets the revalidation sweep find files that have never seen
#: a newly-added check.
VALIDATION_POLICY_VERSION = 1


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


class BudgetExceeded(Exception):
    """Inspection could not complete within its limits.

    Deliberately *not* an internal error. A file we cannot finish
    inspecting cannot be approved, and saying so plainly is better for
    a creator than an indefinite pending state.
    """

    def __init__(self, limit: str) -> None:
        super().__init__(f"inspection budget exceeded: {limit}")
        self.limit = limit


@dataclass
class InspectionBudget:
    """Enforceable ceilings for one file's inspection.

    Wall-clock is the one that makes the others honest. Byte and entry
    ceilings bound what a *well-behaved* archive can cost; a
    pathological one can be slow without being large — many tiny
    entries, or deeply inefficient compression — so elapsed time is
    checked in the same loops.
    """

    #: Total decompressed bytes across every entry.
    max_decompressed_bytes: int = 1024 * 1024 * 1024  # 1 GB
    #: Entries in one archive.
    max_entries: int = 2000
    #: Wall-clock for the whole inspection of one file.
    max_seconds: float = 60.0
    #: Rows of a CSV. Exceeding it is a rejection, never a partial pass.
    max_csv_rows: int = 2_000_000
    #: Bytes of a CSV read for formula inspection. Same rule.
    max_csv_bytes: int = 100 * 1024 * 1024

    _started: float = field(default_factory=time.monotonic, init=False)
    _bytes: int = field(default=0, init=False)

    def restart_clock(self) -> None:
        self._started = time.monotonic()
        self._bytes = 0

    def tick(self) -> None:
        """Called inside every loop that can run long."""
        if time.monotonic() - self._started > self.max_seconds:
            raise BudgetExceeded("time")

    def spend_bytes(self, n: int) -> None:
        self._bytes += n
        if self._bytes > self.max_decompressed_bytes:
            raise BudgetExceeded("decompressed_size")
        self.tick()

    @property
    def spent_bytes(self) -> int:
        return self._bytes


#: Read size for every streaming loop. Bounds resident memory: the
#: inspector never holds more than one chunk plus the archive's central
#: directory, whatever the file's size.
CHUNK = 64 * 1024

#: Bytes read from the head of a file (or archive entry) to identify it.
SNIFF = 512


# ---------------------------------------------------------------------------
# Signature table
# ---------------------------------------------------------------------------

#: A format's identity, as the bytes show it.
#:
#: ``kind`` is the coarse family used for policy decisions — notably
#: ``video``, which is prohibited regardless of what a file is called.
@dataclass(frozen=True)
class Identified:
    fmt: str
    kind: str  # document | spreadsheet | presentation | audio | video | archive | text | executable | unknown


def _is_ooxml_or_zip(head: bytes) -> bool:
    # Local file header, or an empty/spanned archive.
    return head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def _iso_bmff_brand(head: bytes) -> str | None:
    """The ``ftyp`` brand of an ISO base-media file, or None.

    This is the audio/video discriminator, and it is why extension
    checks alone cannot enforce "no video": an MP4 renamed ``.m4a`` —
    or ``.pdf`` — still declares its brand here.
    """
    if len(head) < 12 or head[4:8] != b"ftyp":
        return None
    return head[8:12].decode("ascii", "replace").strip().upper()


#: Brands that mean audio. Everything else in the ISO-BMFF family is
#: treated as video, which is the safe default for a prohibited kind:
#: an unrecognised brand is refused rather than waved through.
_AUDIO_BRANDS = {"M4A", "M4B", "F4A", "MP4A"}


def identify(head: bytes) -> Identified:
    """Identify a format from its leading bytes.

    Never raises. Returns ``kind='unknown'`` when nothing matches,
    which the caller treats as a rejection — the table is an
    allow-list, so an unrecognised signature fails closed.
    """
    h = head

    if h[:5] == b"%PDF-":
        return Identified("pdf", "document")

    if h[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        # OLE2 compound file: legacy .doc/.xls/.ppt, and also the
        # container used by a great many malicious droppers. Identified
        # so it can be *recognised and refused*, not permitted.
        return Identified("ole2", "legacy_office")

    if h[:2] == b"MZ":
        return Identified("pe", "executable")
    if h[:4] == b"\x7fELF":
        return Identified("elf", "executable")
    if h[:4] in (b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return Identified("macho", "executable")
    if h[:2] == b"#!":
        return Identified("script", "executable")

    brand = _iso_bmff_brand(h)
    if brand is not None:
        if brand in _AUDIO_BRANDS:
            return Identified("m4a", "audio")
        return Identified(f"iso-{brand.lower()}", "video")

    if h[:3] == b"ID3":
        return Identified("mp3", "audio")
    # MPEG audio frame sync: 11 set bits.
    if len(h) >= 2 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0:
        return Identified("mp3", "audio")

    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return Identified("wav", "audio")
    if h[:4] == b"RIFF" and h[8:12] == b"AVI ":
        return Identified("avi", "video")

    if h[:4] == b"OggS":
        return Identified("ogg", "audio")
    if h[:4] == b"fLaC":
        return Identified("flac", "audio")
    if h[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return Identified("aac", "audio")

    if h[:6] in (b"GIF87a", b"GIF89a"):
        return Identified("gif", "image")
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return Identified("png", "image")
    if h[:3] == b"\xff\xd8\xff":
        return Identified("jpeg", "image")

    if h[:6] == b"\xfd7zXZ\x00":
        return Identified("xz", "archive")
    if h[:2] == b"\x1f\x8b":
        return Identified("gzip", "archive")
    if h[:3] == b"BZh":
        return Identified("bzip2", "archive")
    if h[:6] == b"7z\xbc\xaf\x27\x1c":
        return Identified("7z", "archive")
    if h[:4] == b"Rar!":
        return Identified("rar", "archive")

    if _is_ooxml_or_zip(h):
        # Which ZIP-family format it is cannot be told from the header —
        # it needs the central directory. ``inspect_zip_family`` does
        # that; here it is simply "a ZIP container".
        return Identified("zip-container", "archive")

    return Identified("unknown", "unknown")


#: Extension → the signature formats acceptable for it.
#:
#: ZIP-family extensions all map to ``zip-container`` because the
#: header cannot distinguish them; the package check narrows it.
_EXTENSION_SIGNATURES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"pdf"}),
    ".zip": frozenset({"zip-container"}),
    ".docx": frozenset({"zip-container"}),
    ".xlsx": frozenset({"zip-container"}),
    ".pptx": frozenset({"zip-container"}),
    ".mp3": frozenset({"mp3"}),
    ".m4a": frozenset({"m4a"}),
    ".wav": frozenset({"wav"}),
    ".aac": frozenset({"aac"}),
    # Text formats have no signature. Validated by decoding instead.
    ".csv": frozenset(),
    ".txt": frozenset(),
    ".md": frozenset(),
}


#: OOXML packages, by extension → the directory the format requires.
_OOXML_ROOTS: dict[str, str] = {
    ".docx": "word/",
    ".xlsx": "xl/",
    ".pptx": "ppt/",
}

#: Any entry whose name contains this is a VBA project, whatever the
#: package calls itself. Catches a macro workbook renamed ``.xlsx``.
_VBA_MARKER = "vbaproject.bin"


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


class ValidationFailure(Exception):
    """A definite, file-attributable reason not to accept this file."""

    def __init__(self, reason: str, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class CheckOutcome:
    """One check's result, as recorded on the file."""

    id: str
    version: int
    outcome: str          # pass | fail
    reason: str | None = None
    detail: str = ""

    def as_record(self) -> dict:
        rec = {"id": self.id, "version": self.version, "outcome": self.outcome}
        if self.reason:
            rec["reason"] = self.reason
        if self.detail:
            rec["detail"] = self.detail
        return rec


# ---------------------------------------------------------------------------
# Check: signature agreement
# ---------------------------------------------------------------------------


def check_signature(
    *, filename: str, declared_type: str, head: bytes,
) -> Identified:
    """Signature, extension and declared type must all agree.

    Returns the identification so later checks can use the family
    without re-sniffing.
    """
    exts = all_extensions(filename)
    if not exts:
        raise ValidationFailure(
            "no_extension",
            "That file needs a file extension so members know what it is.",
        )
    for e in exts:
        if e in OFFERING_FORBIDDEN_EXTENSIONS:
            raise ValidationFailure(
                "forbidden_type",
                "That file type cannot be sold as a download.",
            )
    ext = exts[-1]

    if ext in MACRO_EXTENSIONS:
        raise ValidationFailure(
            "macro_document",
            "This file includes macros, which we can't accept. Saving it "
            "as .docx, .xlsx or .pptx usually works — macros are rarely "
            "needed in a template.",
        )
    if ext in LEGACY_OFFICE_EXTENSIONS:
        raise ValidationFailure(
            "legacy_office",
            "This is an older Office format. Please save it as .docx, "
            ".xlsx or .pptx and upload again.",
        )
    if ext not in OFFERING_ALLOWED_TYPES:
        raise ValidationFailure(
            "unsupported_type",
            "That file type is not supported for Offerings.",
        )

    ident = identify(head)

    # Prohibited kinds are refused on the bytes, whatever the name says.
    if ident.kind == "video":
        raise ValidationFailure(
            "video_detected",
            "This looks like a video. Offerings doesn't host video — "
            "videos belong in a Pathway, or you can link to your own "
            "video host.",
            detail=ident.fmt,
        )
    if ident.kind == "executable":
        raise ValidationFailure(
            "forbidden_type",
            "That file type cannot be sold as a download.",
            detail=ident.fmt,
        )
    if ident.kind == "legacy_office":
        raise ValidationFailure(
            "legacy_office",
            "This is an older Office format. Please save it as .docx, "
            ".xlsx or .pptx and upload again.",
        )

    expected = _EXTENSION_SIGNATURES.get(ext)
    if expected is None:
        raise ValidationFailure(
            "unsupported_type",
            "That file type is not supported for Offerings.",
        )
    if expected:
        if ident.fmt not in expected:
            raise ValidationFailure(
                "signature_mismatch",
                "This file's contents don't match its file type.",
                detail=f"{ext} declared, {ident.fmt} found",
            )
    else:
        # Text family: no signature exists, so prove it is text rather
        # than something else wearing a .txt name.
        if ident.kind != "unknown":
            raise ValidationFailure(
                "signature_mismatch",
                "This file's contents don't match its file type.",
                detail=f"{ext} declared, {ident.fmt} found",
            )

    # Declared type must agree too — the Phase A rule, kept.
    accepted_types = OFFERING_ALLOWED_TYPES[ext]
    declared = (declared_type or "").split(";")[0].strip().lower()
    if not declared:
        raise ValidationFailure(
            "missing_content_type",
            "That upload did not say what kind of file it is.",
        )
    if declared not in accepted_types:
        raise ValidationFailure(
            "content_type_mismatch",
            "That file's type does not match its extension.",
        )
    return ident


# ---------------------------------------------------------------------------
# Check: structure
# ---------------------------------------------------------------------------


def check_structure(
    *, filename: str, ident: Identified, stream: io.BufferedIOBase,
    budget: InspectionBudget,
) -> None:
    """Confirm the file parses as far as cheaply possible.

    Corruption is far more often a bad upload than an attack, and
    catching it here means a purchaser never pays for a file their
    reader refuses to open.
    """
    ext = all_extensions(filename)[-1]

    if ident.fmt == "pdf":
        tail = _read_tail(stream, 2048)
        if b"%%EOF" not in tail:
            raise ValidationFailure(
                "unreadable",
                "We couldn't read this file — it may not have uploaded "
                "completely. Please try again.",
                detail="pdf: no trailer",
            )
        return

    if ext in _OOXML_ROOTS or ext == ".zip":
        # Opening the central directory is the structural check for the
        # whole ZIP family; inspect_zip_family does it and raises on a
        # malformed archive.
        return

    if ident.kind in ("audio",):
        # Header already matched a frame sync or container box. Anything
        # deeper needs a decoder, which is out of scope and would be a
        # new dependency.
        return


def _read_tail(stream: io.BufferedIOBase, n: int) -> bytes:
    pos = stream.tell()
    try:
        stream.seek(0, io.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - n))
        return stream.read(n)
    finally:
        stream.seek(pos)


# ---------------------------------------------------------------------------
# Check: ZIP family — type-aware
# ---------------------------------------------------------------------------

#: Extensions permitted *inside* a .zip bundle. Deliberately narrower
#: than nothing-at-all: a bundle may contain the documents Offerings
#: sells, and nested OOXML packages are inspected one level.
_ZIP_MEMBER_ALLOWED = frozenset(OFFERING_ALLOWED_TYPES) - {".zip"}


def inspect_zip_family(
    *, filename: str, stream: io.BufferedIOBase, budget: InspectionBudget,
) -> dict:
    """Open a ZIP-family file and apply the policy for what it claims.

    Office packages get a package check; a ``.zip`` gets full bundle
    inspection. This split is the whole reason normal workbooks are not
    judged against archive rules — they are made of compressed XML, and
    that is not a finding.

    Returns a summary dict for the validation record.
    """
    ext = all_extensions(filename)[-1]
    try:
        zf = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as exc:
        raise ValidationFailure(
            "unreadable",
            "We couldn't read this file — it may not have uploaded "
            "completely. Please try again.",
            detail=f"bad zip: {exc}",
        ) from exc

    infos = zf.infolist()
    if len(infos) > budget.max_entries:
        raise ValidationFailure(
            "too_many_entries",
            f"This archive contains more than {budget.max_entries} files. "
            "Please split it into smaller downloads.",
        )

    # Encryption first: an encrypted archive is both prohibited and
    # uninspectable, and the two reasons reinforce each other.
    for info in infos:
        if info.flag_bits & 0x1:
            raise ValidationFailure(
                "encrypted_archive",
                "This ZIP is password-protected, so we can't check what's "
                "inside. Please upload an unprotected version.",
            )

    if ext in _OOXML_ROOTS:
        return _check_ooxml_package(ext, zf, infos)
    return _check_zip_bundle(zf, infos, budget)


def _check_ooxml_package(ext: str, zf: zipfile.ZipFile, infos) -> dict:
    """An Office package: expect its own shape, refuse a VBA project."""
    names = [i.filename for i in infos]
    lowered = [n.lower() for n in names]

    if "[Content_Types].xml" not in names:
        raise ValidationFailure(
            "unreadable",
            "This doesn't look like a valid Office document. Please "
            "re-save it and upload again.",
            detail="ooxml: no [Content_Types].xml",
        )
    root = _OOXML_ROOTS[ext]
    if not any(n.startswith(root) for n in names):
        raise ValidationFailure(
            "signature_mismatch",
            "This file's contents don't match its file type.",
            detail=f"ooxml: no {root} part",
        )
    for n in lowered:
        if _VBA_MARKER in n:
            raise ValidationFailure(
                "macro_document",
                "This file includes macros, which we can't accept. Saving "
                "it as .docx, .xlsx or .pptx usually works — macros are "
                "rarely needed in a template.",
                detail="vbaProject.bin present",
            )
    return {"kind": "ooxml_package", "entries": len(infos)}


def _check_zip_bundle(
    zf: zipfile.ZipFile, infos, budget: InspectionBudget,
) -> dict:
    """A bundle a purchaser will extract. Every entry must be sellable."""
    declared_total = 0
    for info in infos:
        budget.tick()
        name = info.filename

        # Path safety — the risk is on the purchaser's machine at
        # extraction time; we never extract to disk ourselves.
        if name.startswith("/") or name.startswith("\\"):
            raise ValidationFailure("unsafe_archive", _UNSAFE_MSG, detail="absolute path")
        if re.match(r"^[A-Za-z]:", name):
            raise ValidationFailure("unsafe_archive", _UNSAFE_MSG, detail="drive letter")
        parts = name.replace("\\", "/").split("/")
        if ".." in parts:
            raise ValidationFailure("unsafe_archive", _UNSAFE_MSG, detail="traversal")

        # Entry kind — symlinks, devices and FIFOs have no place in a
        # sold bundle, and a symlink is either a mistake or an attack.
        #
        # Only the file-TYPE bits are examined, and only when they are
        # present. Many writers (including Python's own ``writestr``,
        # and most Windows tools) store permission bits with no type
        # bits at all, so ``external_attr >> 16`` is ``0o600`` and the
        # type field is zero. Treating that as "not a regular file"
        # rejected every ordinary archive — caught by the legitimate-
        # bundle test, which is why that test exists.
        ftype = (info.external_attr >> 16) & 0o170000
        if ftype and ftype not in (0o100000, 0o040000):
            raise ValidationFailure(
                "unsafe_archive", _UNSAFE_MSG, detail=f"entry type {oct(ftype)}",
            )

        if info.is_dir():
            continue

        declared_total += info.file_size
        if declared_total > budget.max_decompressed_bytes:
            raise ValidationFailure("zip_bomb", _BOMB_MSG, detail="declared total")
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > 200:
                raise ValidationFailure(
                    "zip_bomb", _BOMB_MSG, detail=f"ratio {ratio:.0f}:1",
                )

        _check_zip_member(zf, info, budget)

    return {
        "kind": "zip_bundle",
        "entries": len(infos),
        "decompressed_bytes": budget.spent_bytes,
    }


_UNSAFE_MSG = (
    "This ZIP contains entries we can't accept — it may have unsafe file "
    "paths or shortcuts. Please rebuild the archive from a plain folder."
)
_BOMB_MSG = (
    "This archive expands to far more than we can accept. Please reduce "
    "its contents or split it into smaller downloads."
)
_ZIP_CONTENT_MSG = (
    "This ZIP contains files that can't be sold as downloads. Remove them "
    "and upload again, or add the files directly instead of zipping them."
)


def _check_zip_member(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, budget: InspectionBudget,
) -> None:
    """Validate one entry: name, type, and its own leading bytes."""
    name = info.filename
    exts = all_extensions(name.rsplit("/", 1)[-1])
    if not exts:
        raise ValidationFailure(
            "zip_contents", _ZIP_CONTENT_MSG, detail="entry without extension",
        )
    for e in exts:
        if e in OFFERING_FORBIDDEN_EXTENSIONS:
            raise ValidationFailure(
                "zip_executable", _ZIP_CONTENT_MSG, detail=f"entry {e}",
            )
    ext = exts[-1]
    if ext in MACRO_EXTENSIONS:
        raise ValidationFailure(
            "zip_contents", _ZIP_CONTENT_MSG, detail="macro document inside",
        )
    if ext in LEGACY_OFFICE_EXTENSIONS:
        raise ValidationFailure(
            "zip_contents", _ZIP_CONTENT_MSG, detail="legacy Office inside",
        )
    if ext == ".zip":
        # Nested ordinary archives are refused: unbounded recursion,
        # and a bundle of bundles has no legitimate use here.
        raise ValidationFailure(
            "nested_zip",
            "This ZIP contains another ZIP file. Please add the files "
            "directly instead of nesting archives.",
        )
    if ext not in _ZIP_MEMBER_ALLOWED:
        raise ValidationFailure(
            "zip_contents", _ZIP_CONTENT_MSG, detail=f"entry {ext}",
        )

    # The entry's own bytes. This is the video gate inside archives: a
    # member named ``holiday.pdf`` that is really an MP4 is caught here
    # and nowhere else.
    with zf.open(info) as fh:
        head = fh.read(SNIFF)
        budget.spend_bytes(len(head))
        ident = identify(head)
        if ident.kind == "video":
            raise ValidationFailure(
                "zip_video",
                "This ZIP contains video files, which Offerings doesn't "
                "host. Remove them and upload again — videos belong in a "
                "Pathway, or you can link to your own video host.",
                detail=ident.fmt,
            )
        if ident.kind == "executable":
            raise ValidationFailure(
                "zip_executable", _ZIP_CONTENT_MSG, detail=ident.fmt,
            )
        if ident.kind == "legacy_office":
            raise ValidationFailure(
                "zip_contents", _ZIP_CONTENT_MSG, detail="legacy Office inside",
            )
        if ext in _OOXML_ROOTS:
            # One level of nested package inspection, so an .xlsm cannot
            # travel inside a .zip by being renamed .xlsx.
            rest = head + fh.read()
            budget.spend_bytes(len(rest) - len(head))
            try:
                inner = zipfile.ZipFile(io.BytesIO(rest))
            except zipfile.BadZipFile:
                raise ValidationFailure(
                    "zip_contents", _ZIP_CONTENT_MSG,
                    detail="unreadable Office entry",
                ) from None
            _check_ooxml_package(ext, inner, inner.infolist())
            return

        if ext == ".csv":
            # A formula-injection CSV inside a bundle is the same threat
            # as one uploaded directly, and ZIP must not be the way
            # around the rule. Read it under the CSV byte ceiling — a
            # bundled CSV too large to inspect is refused, not waved
            # through, exactly as a standalone one is.
            rest = head + fh.read(budget.max_csv_bytes + 1 - len(head))
            budget.spend_bytes(len(rest) - len(head))
            if len(rest) > budget.max_csv_bytes:
                raise ValidationFailure(
                    "csv_too_large_to_check",
                    "A CSV inside this ZIP is too large for us to check in "
                    "full. Please split it into smaller files.",
                )
            check_csv(stream=io.BytesIO(rest), budget=budget)
            return

        # Everything else: stream it to enforce the real expansion
        # budget. The central directory can lie; this cannot.
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            budget.spend_bytes(len(chunk))


# ---------------------------------------------------------------------------
# Check: CSV formula injection
# ---------------------------------------------------------------------------

#: Characters that make a spreadsheet treat a cell as a formula.
#: ``-`` and ``+`` are handled separately because a negative number is
#: legitimate data and rejecting it would be the bug.
_FORMULA_LEAD = ("=", "@")
#: Control characters that spreadsheet apps skip before parsing, so a
#: cell beginning with them can still reach the formula parser.
_SKIPPED = "\t\r\n\x00\x0b\x0c  ​﻿"
#: Payload markers that matter wherever they appear, not just leading.
_PAYLOAD_MARKERS = ("dde(", "cmd|", "msexcel|", "rundll32", "powershell")

_NUMERIC = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _cell_is_dangerous(raw: str) -> bool:
    """Would a spreadsheet treat this cell as an executable formula?

    The rule that protects creators: a leading ``-`` or ``+`` is only
    dangerous when the cell is **not a number**. ``-5``, ``+3.5`` and
    ``-1.2e-4`` are ordinary data and must pass; ``-2+3+cmd|'/c calc'``
    is not a number and must not.
    """
    if not raw:
        return False
    low = raw.lower()
    for marker in _PAYLOAD_MARKERS:
        if marker in low:
            return True

    # Strip leading characters a spreadsheet ignores, so whitespace and
    # control characters cannot smuggle a formula past a naive check on
    # the first character.
    stripped = raw.lstrip(_SKIPPED)
    if not stripped:
        return False
    first = stripped[0]
    if first in _FORMULA_LEAD:
        return True
    if first in "+-":
        return not _NUMERIC.match(stripped.strip())
    return False


def check_csv(
    *, stream: io.BufferedIOBase, budget: InspectionBudget,
) -> dict:
    """Inspect **every** cell of a CSV, inside a bounded budget.

    Approved refinement: a partially-inspected CSV is never passed. If
    the file exceeds the row or byte ceiling, it is rejected with a
    message a creator can act on — because "we checked some of it" is
    not a basis for making a file available.
    """
    stream.seek(0)
    raw = stream.read(budget.max_csv_bytes + 1)
    if len(raw) > budget.max_csv_bytes:
        raise ValidationFailure(
            "csv_too_large_to_check",
            "This CSV is too large for us to check in full. Please split "
            "it into smaller files.",
        )

    text: str | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValidationFailure(
            "unreadable",
            "We couldn't read this file — it may not have uploaded "
            "completely. Please try again.",
            detail="csv: undecodable",
        )

    rows = 0
    cells = 0
    try:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            rows += 1
            if rows > budget.max_csv_rows:
                raise ValidationFailure(
                    "csv_too_large_to_check",
                    "This CSV has too many rows for us to check in full. "
                    "Please split it into smaller files.",
                )
            if rows % 500 == 0:
                budget.tick()
            for cell in row:
                cells += 1
                if _cell_is_dangerous(cell):
                    raise ValidationFailure(
                        "csv_formula",
                        "Some cells in this CSV start with characters that "
                        "spreadsheet apps treat as formulas. Please remove "
                        "them — plain numbers and text are fine.",
                        detail=f"row {rows}",
                    )
    except csv.Error as exc:
        raise ValidationFailure(
            "unreadable",
            "We couldn't read this file — it may not have uploaded "
            "completely. Please try again.",
            detail=f"csv: {exc}",
        ) from exc

    # Complete inspection, and the record says so.
    return {"rows_inspected": rows, "cells_inspected": cells, "complete": True}


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    id: str
    version: int


#: The checks a file must pass to be available, and the identity of
#: this set. Adding antivirus later is one entry here plus a worker —
#: see ``docs`` in the Phase B plan.
REQUIRED_CHECKS: tuple[Check, ...] = (
    Check("declared", 1),
    Check("signature", 1),
    Check("structure", 1),
    Check("zip_contents", 1),
    Check("csv_formula", 1),
)

#: Checks that exist but are not required. Empty today. An antivirus
#: check would live here first, so it can be exercised in production
#: before it starts gating availability.
OPTIONAL_CHECKS: tuple[Check, ...] = ()


def required_check_ids() -> frozenset[str]:
    return frozenset(c.id for c in REQUIRED_CHECKS)


def missing_required(performed: Iterable[dict]) -> frozenset[str]:
    """Required check ids absent from a file's record.

    Non-empty means the file has **not** been checked to current
    policy, whatever its status says. This is what the revalidation
    sweep queries, and what keeps an older file from being represented
    as having passed checks it never received.
    """
    seen = {
        str(entry.get("id"))
        for entry in performed
        if entry.get("outcome") == "pass"
    }
    return required_check_ids() - seen


__all__ = [
    "VALIDATION_POLICY_VERSION",
    "InspectionBudget",
    "BudgetExceeded",
    "Identified",
    "identify",
    "MACRO_EXTENSIONS",
    "LEGACY_OFFICE_EXTENSIONS",
    "ValidationFailure",
    "CheckOutcome",
    "check_signature",
    "check_structure",
    "inspect_zip_family",
    "check_csv",
    "Check",
    "REQUIRED_CHECKS",
    "OPTIONAL_CHECKS",
    "required_check_ids",
    "missing_required",
    "CHUNK",
    "SNIFF",
]
