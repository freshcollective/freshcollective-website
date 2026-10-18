"""What an Offering file may be, and where it lives.

Deliberately separate from ``app.core.storage``'s global
``ALLOWED_EXTENSIONS``. That list governs every upload destination in
the platform — avatars, Collective covers, Pathway step resources,
Media Library. Adding ``.zip`` and ``.xlsx`` to it would let a member
upload an archive as their profile picture, which is a widening nobody
asked for and a new attack surface on surfaces that do not need it.

So this module owns an Offering-specific allow-list, and the Offerings
upload path is expected to call :func:`validate_offering_upload`
*instead of* relying on the global one. One product decision, one
place.

Phase A scope
-------------

The validation rules, the size limits and the storage-key shape. The
creator upload endpoint that calls them is Phase B. Everything here is
pure except :func:`build_storage_key`, which only needs a uuid — so it
is all directly testable without a request, a session or R2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------

#: The private storage namespace for downloadable Offering assets.
#:
#: It is not ``platform-artwork`` and never may be: ``_bucket_for_key``
#: in ``app.core.storage`` routes everything that is not that one prefix
#: to the **private** bucket, so this namespace lands there by the
#: existing rule rather than by a new one. There is deliberately no
#: public route for it — see ``app/uploads/routes.py``, where the two
#: public routes are enumerated explicitly and everything else falls to
#: the authenticated catch-all.
OFFERING_FILES_PREFIX = "offering-files"

#: Cover images live apart from the files people pay for. A cover is
#: shown to anyone who can see the Offering; a file only to someone who
#: owns it. Separate namespaces mean a future change to how covers are
#: cached or served cannot reach the paid assets.
OFFERING_COVERS_PREFIX = "offering-covers"


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

#: Per file. Below the platform-wide 200 MB in ``core.storage`` on
#: purpose: a workbook, a guide, a recording or a template bundle fits
#: comfortably, and the ceiling bounds both a single upload and the
#: blast radius of a mistake. Raise it with evidence, not in advance.
MAX_OFFERING_FILE_BYTES = 100 * 1024 * 1024  # 100 MB

#: Across one Offering's current bundle. Without this, "multiple files
#: supported" has no ceiling at all — ten 100 MB files is a gigabyte
#: per product and an egress bill nobody predicted.
MAX_OFFERING_BUNDLE_BYTES = 500 * 1024 * 1024  # 500 MB

#: Count limit as well as byte limit. A bundle of 200 tiny files is a
#: usability problem for the buyer and a pathological case for the
#: download UI, even though it is well inside the byte ceiling.
MAX_OFFERING_FILE_COUNT = 25


# ---------------------------------------------------------------------------
# Allow-list
# ---------------------------------------------------------------------------

#: Extension → the content types accepted for it.
#:
#: Both halves are checked, and against each other. A client that sends
#: ``report.pdf`` with ``application/zip``, or ``payload.zip`` labelled
#: ``application/pdf``, is refused — neither value is trusted alone, and
#: a mismatch is a stronger signal than either on its own.
#:
#: The lists are generous about *spelling* because browsers and
#: operating systems genuinely disagree (``audio/mpeg`` vs
#: ``audio/mp3``; the four Office variants), and strict about *kind*.
OFFERING_ALLOWED_TYPES: dict[str, frozenset[str]] = {
    # Documents
    ".pdf": frozenset({"application/pdf"}),
    ".doc": frozenset({"application/msword"}),
    ".docx": frozenset({
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }),
    ".rtf": frozenset({"application/rtf", "text/rtf"}),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
    ".epub": frozenset({"application/epub+zip"}),
    # Spreadsheets
    ".xls": frozenset({"application/vnd.ms-excel"}),
    ".xlsx": frozenset({
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }),
    ".csv": frozenset({"text/csv", "application/csv", "text/plain"}),
    # Presentations
    ".ppt": frozenset({"application/vnd.ms-powerpoint"}),
    ".pptx": frozenset({
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }),
    # Audio
    ".mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    ".m4a": frozenset({"audio/mp4", "audio/x-m4a", "audio/m4a"}),
    ".wav": frozenset({"audio/wav", "audio/x-wav", "audio/wave"}),
    ".aac": frozenset({"audio/aac", "audio/x-aac"}),
    # Archives — the bundle format, and the riskiest entry here.
    ".zip": frozenset({"application/zip", "application/x-zip-compressed"}),
}

#: Extensions that must never be accepted, checked **before** the
#: allow-list and against *every* extension in the filename rather than
#: only the last one.
#:
#: Redundant by construction — none of these is in the allow-list — and
#: kept because the cost of the allow-list ever being widened carelessly
#: is a creator distributing an executable to paying members under
#: Fresh Collective's name. Belt and braces, cheaply.
OFFERING_FORBIDDEN_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".app", ".msi", ".bat", ".cmd",
    ".com", ".scr", ".pif", ".cpl", ".jar", ".sh", ".bash", ".zsh",
    ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".mjs", ".jse", ".wsf",
    ".wsh", ".hta", ".reg", ".lnk", ".scf", ".inf", ".apk", ".deb",
    ".rpm", ".dmg", ".pkg", ".py", ".pyc", ".rb", ".pl", ".php",
})


class OfferingFileRejected(ValueError):
    """An upload that must not be stored.

    A ``ValueError`` subclass so the Phase B endpoint can map it to a
    422 without this module importing FastAPI — the same separation
    ``ticket_pricing`` keeps.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        #: Machine-readable, for tests and for the creator UI to branch
        #: on without parsing prose.
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ValidatedOfferingFile:
    """An upload that passed every check, normalised."""

    extension: str
    content_type: str
    byte_size: int
    original_filename: str


# ---------------------------------------------------------------------------
# Filename handling
# ---------------------------------------------------------------------------

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitise_filename(name: str) -> str:
    """A filename safe to put in a storage key and a download header.

    Strips any directory component first — a browser on some platforms
    will happily send ``..\\..\\evil.pdf`` as the field value, and the
    basename is the only part that was ever meaningful.
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    cleaned = _SAFE_NAME.sub("_", base).strip("._-")
    return cleaned[:120] or "file"


def all_extensions(name: str) -> list[str]:
    """Every dotted suffix in a filename, lower-cased.

    ``archive.zip`` → ``['.zip']``; ``invoice.pdf.exe`` → ``['.pdf',
    '.exe']``. Checking all of them is what makes a double extension
    fail the forbidden-list rather than passing on its last suffix.
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    parts = [p for p in base.split(".")[1:] if p]
    return [f".{p.lower()}" for p in parts]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_offering_upload(
    *,
    filename: str,
    content_type: str | None,
    byte_size: int,
    existing_bundle_bytes: int = 0,
    existing_bundle_count: int = 0,
) -> ValidatedOfferingFile:
    """Accept or refuse one Offering file.

    ``existing_bundle_bytes`` / ``existing_bundle_count`` describe the
    Offering's **current** bundle, so the caller counts superseded rows
    out of both. The limits apply to what a buyer would download, not
    to everything ever uploaded — otherwise replacing a file five times
    would exhaust the budget for a bundle that never grew.

    Raises :class:`OfferingFileRejected`. Returns the normalised values
    to persist on success.
    """
    if byte_size <= 0:
        raise OfferingFileRejected(
            "empty_file", "That file is empty.",
        )
    if byte_size > MAX_OFFERING_FILE_BYTES:
        mb = MAX_OFFERING_FILE_BYTES // (1024 * 1024)
        raise OfferingFileRejected(
            "file_too_large",
            f"Each file must be {mb} MB or smaller.",
        )

    exts = all_extensions(filename)
    if not exts:
        raise OfferingFileRejected(
            "no_extension",
            "That file needs a file extension so members know what it is.",
        )

    # Forbidden first, across every suffix, so ``guide.pdf.exe`` cannot
    # pass by having an allowed extension somewhere in the name.
    for ext in exts:
        if ext in OFFERING_FORBIDDEN_EXTENSIONS:
            raise OfferingFileRejected(
                "forbidden_type",
                "That file type cannot be sold as a download.",
            )

    extension = exts[-1]
    accepted = OFFERING_ALLOWED_TYPES.get(extension)
    if accepted is None:
        raise OfferingFileRejected(
            "unsupported_type",
            "That file type is not supported for Offerings.",
        )

    declared = (content_type or "").split(";")[0].strip().lower()
    if not declared:
        raise OfferingFileRejected(
            "missing_content_type",
            "That upload did not say what kind of file it is.",
        )
    if declared not in accepted:
        # The mismatch, not either value alone. Naming both halves in
        # the log-facing reason would leak a client-controlled string
        # into a message a member sees, so the prose stays general.
        raise OfferingFileRejected(
            "content_type_mismatch",
            "That file's type does not match its extension.",
        )

    if existing_bundle_count + 1 > MAX_OFFERING_FILE_COUNT:
        raise OfferingFileRejected(
            "too_many_files",
            f"An Offering can include up to {MAX_OFFERING_FILE_COUNT} files.",
        )
    if existing_bundle_bytes + byte_size > MAX_OFFERING_BUNDLE_BYTES:
        mb = MAX_OFFERING_BUNDLE_BYTES // (1024 * 1024)
        raise OfferingFileRejected(
            "bundle_too_large",
            f"An Offering's files must total {mb} MB or less.",
        )

    return ValidatedOfferingFile(
        extension=extension,
        content_type=declared,
        byte_size=byte_size,
        original_filename=sanitise_filename(filename),
    )


# ---------------------------------------------------------------------------
# Storage keys
# ---------------------------------------------------------------------------


def build_storage_key(*, offering_id: str, filename: str) -> str:
    """The R2 key for one Offering file.

    ``offering-files/{offering_id}/{uuid}_{sanitised}``.

    The Offering id is a whole path segment, which is what lets the
    download authoriser resolve the owning Offering from the key
    without a reverse lookup on the stored URL — and, more importantly,
    lets it verify that the file the caller asked for belongs to the
    Offering they claim an entitlement to.

    The uuid prefix means a creator re-uploading the same filename
    never collides with, or overwrites, the object the previous version
    still points at. That is the mechanism behind "never accidentally
    overwrite a storage object still needed for recovery": not a rule
    someone has to remember, but a key that cannot repeat.
    """
    return (
        f"{OFFERING_FILES_PREFIX}/{offering_id}/"
        f"{uuid4().hex}_{sanitise_filename(filename)}"
    )


def offering_id_from_storage_key(key: str) -> str | None:
    """The Offering id embedded in a key, or None if the shape is wrong.

    Shape-only; it says nothing about whether that Offering exists.
    Callers resolve the row and decide.
    """
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != OFFERING_FILES_PREFIX or not parts[1]:
        return None
    return parts[1]


__all__ = [
    "OFFERING_FILES_PREFIX",
    "OFFERING_COVERS_PREFIX",
    "MAX_OFFERING_FILE_BYTES",
    "MAX_OFFERING_BUNDLE_BYTES",
    "MAX_OFFERING_FILE_COUNT",
    "OFFERING_ALLOWED_TYPES",
    "OFFERING_FORBIDDEN_EXTENSIONS",
    "OfferingFileRejected",
    "ValidatedOfferingFile",
    "sanitise_filename",
    "all_extensions",
    "validate_offering_upload",
    "build_storage_key",
    "offering_id_from_storage_key",
]
