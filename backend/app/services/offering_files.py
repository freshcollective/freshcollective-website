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

# ---------------------------------------------------------------------------
# These three are the *platform* ceiling: the absolute maximum, which no
# plan may exceed and no account may bypass — not a Platform Owner, not
# an admin, not the unrestricted Founding Creator plan. They exist
# because fc-api runs on a 0.5-CPU / 512 MB Render instance, and that
# bound is a property of the infrastructure rather than of anybody's
# subscription.
#
# Per-plan allowances live in ``app.creator.plan_config`` and are
# resolved against these by ``app.services.offering_limits``, which
# always takes the smaller of the two. Every value below is therefore
# equal to the most generous approved plan value: the ceiling is real,
# but today no creator meets it before meeting their plan limit first.
# ---------------------------------------------------------------------------

#: Per file. Matches the Creator Portfolio allowance.
#:
#: Lowered from 100 MB when the approved per-plan limits landed. Phase A
#: picked 100 MB before the plan table existed and before the request
#: path had been measured; the measured path (see the B5 report) will not
#: carry 100 MB inside the BFF proxy's timeout, so a ceiling above the
#: highest plan allowance would only have described a request that
#: cannot succeed. No production rows exist, so nothing is grandfathered.
MAX_OFFERING_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

#: Across one Offering's current bundle. Matches the Creator Portfolio
#: allowance. Lowered from 500 MB for the same reason.
MAX_OFFERING_BUNDLE_BYTES = 150 * 1024 * 1024  # 150 MB

#: Count limit as well as byte limit. A bundle of 200 tiny files is a
#: usability problem for the buyer and a pathological case for the
#: download UI, even though it is well inside the byte ceiling.
#:
#: **Raised** from 25, which is the one place the approved limits
#: genuinely conflicted with the Phase A design: Creator and Creator
#: Portfolio are both allowed 50 files, and a 25-file platform ceiling
#: would have silently capped a paid plan at half its stated allowance.
#: Resolved upwards rather than by weakening anything — a file *count*
#: is not a security control, and the inspection budget that is one
#: (``InspectionBudget.max_entries``, 2000 entries per archive) is
#: untouched.
MAX_OFFERING_FILE_COUNT = 50


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
    ".docx": frozenset({
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
    # Spreadsheets
    ".xlsx": frozenset({
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }),
    ".csv": frozenset({"text/csv", "application/csv", "text/plain"}),
    # Presentations
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


#: Macro-enabled Office extensions. Named rather than merely unlisted so
#: the creator is told to save as the non-macro variant — "unsupported
#: format" would leave them guessing at a one-click fix.
MACRO_EXTENSIONS: frozenset[str] = frozenset({
    ".docm", ".xlsm", ".pptm", ".dotm", ".xltm", ".potm", ".xlam", ".ppam",
})

#: Legacy binary Office, removed from the allow-list by approval. These
#: are OLE compound files that can carry a VBA project with no outward
#: signal, so "is this safe?" is unanswerable without much heavier
#: machinery — and "save as .xlsx" is a one-click fix for a creator.
#: Named for the same reason as the macro set.
LEGACY_OFFICE_EXTENSIONS: frozenset[str] = frozenset({
    ".doc", ".xls", ".ppt", ".dot", ".xlt", ".pot",
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
# Resolved limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OfferingLimits:
    """The four numbers that govern one creator's uploads.

    Already resolved: a plan's allowance reduced by the platform ceiling,
    so every consumer enforces one set of values and none of them repeats
    the lookup. Built by
    :func:`app.services.offering_limits.resolve_offering_limits` — the
    only place that reads a plan — and carried from there into the upload
    endpoint, the replacement endpoint and the publication check.

    ``plan_name`` is here so a refusal can say *which* plan's limit was
    hit without the message being assembled from a second plan lookup.
    """

    max_files: int
    max_file_bytes: int
    max_bundle_bytes: int
    zip_bundles_allowed: bool
    plan_name: str = "current"

    @property
    def file_mb(self) -> int:
        return self.max_file_bytes // (1024 * 1024)

    @property
    def bundle_mb(self) -> int:
        return self.max_bundle_bytes // (1024 * 1024)


#: The ceiling as a limits object, for callers with no plan in hand
#: (tests of the pure rules, and the structural revalidation path, which
#: re-checks a stored file's *contents* and must not fail it because the
#: creator has since downgraded).
PLATFORM_LIMITS = OfferingLimits(
    max_files=MAX_OFFERING_FILE_COUNT,
    max_file_bytes=MAX_OFFERING_FILE_BYTES,
    max_bundle_bytes=MAX_OFFERING_BUNDLE_BYTES,
    zip_bundles_allowed=True,
    plan_name="platform",
)


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
    limits: OfferingLimits | None = None,
    existing_bundle_bytes: int = 0,
    existing_bundle_count: int = 0,
    resource_count: int = 1,
) -> ValidatedOfferingFile:
    """Accept or refuse one Offering file.

    ``limits`` is the creator's resolved plan allowance. It defaults to
    :data:`PLATFORM_LIMITS` so the pure rules stay testable without a
    plan, and so a caller that forgets to pass one gets the ceiling
    rather than no limit at all — the safe direction for an omission.

    ``existing_bundle_bytes`` / ``existing_bundle_count`` describe the
    Offering's **current** bundle, so the caller counts superseded rows
    out of both. The limits apply to what a buyer would download, not
    to everything ever uploaded — otherwise replacing a file five times
    would exhaust the budget for a bundle that never grew.

    ``resource_count`` is how many downloadable resources *this* upload
    contributes: 1 for a plain file or an Office package, and the number
    of member files for a ZIP bundle. Passing it is what stops an archive
    being a way around the file allowance; the caller counts the entries
    (cheaply, from the central directory) before calling.

    Raises :class:`OfferingFileRejected`. Returns the normalised values
    to persist on success.
    """
    limits = limits or PLATFORM_LIMITS

    if byte_size <= 0:
        raise OfferingFileRejected(
            "empty_file", "That file is empty.",
        )
    if byte_size > limits.max_file_bytes:
        raise OfferingFileRejected(
            "file_too_large",
            f"Your {limits.plan_name} plan allows files up to "
            f"{limits.file_mb} MB. This one is larger.",
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

    # Named before the allow-list is consulted, so these two get a
    # message that tells the creator what to do instead of a generic
    # "unsupported format".
    if extension in MACRO_EXTENSIONS:
        raise OfferingFileRejected(
            "macro_document",
            "This file includes macros, which we can't accept. Saving it "
            "as .docx, .xlsx or .pptx usually works — macros are rarely "
            "needed in a template.",
        )
    if extension in LEGACY_OFFICE_EXTENSIONS:
        raise OfferingFileRejected(
            "legacy_office",
            "This is an older Office format. Please save it as .docx, "
            ".xlsx or .pptx and upload again.",
        )

    accepted = OFFERING_ALLOWED_TYPES.get(extension)
    if accepted is None:
        raise OfferingFileRejected(
            "unsupported_type",
            "That file type is not supported for Offerings.",
        )

    # ZIP bundles are a plan capability, refused before the archive is
    # inspected or stored. Community's allowance is a single file, so an
    # archive would let one upload carry fifty resources and make the
    # file limit meaningless — the prohibition is what gives that limit
    # its meaning rather than a separate restriction on top of it.
    if extension == ".zip" and not limits.zip_bundles_allowed:
        raise OfferingFileRejected(
            "zip_not_permitted",
            f"Your {limits.plan_name} plan doesn't include ZIP bundles. "
            "Upload the file on its own, or upgrade to Creator to sell a "
            "bundle.",
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

    # Resource count, not row count: a ZIP contributes its member files.
    if existing_bundle_count + max(1, resource_count) > limits.max_files:
        if limits.max_files == 1:
            detail = (
                f"Your {limits.plan_name} plan includes one downloadable "
                "file per Offering. Upgrade to Creator to add more."
            )
        else:
            detail = (
                f"Your {limits.plan_name} plan allows up to "
                f"{limits.max_files} files per Offering."
            )
        raise OfferingFileRejected("too_many_files", detail)

    if existing_bundle_bytes + byte_size > limits.max_bundle_bytes:
        raise OfferingFileRejected(
            "bundle_too_large",
            f"Your {limits.plan_name} plan allows {limits.bundle_mb} MB "
            "of files per Offering. This upload would go over.",
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
    "MACRO_EXTENSIONS",
    "LEGACY_OFFICE_EXTENSIONS",
    "OfferingFileRejected",
    "ValidatedOfferingFile",
    "OfferingLimits",
    "PLATFORM_LIMITS",
    "sanitise_filename",
    "all_extensions",
    "validate_offering_upload",
    "build_storage_key",
    "offering_id_from_storage_key",
]
