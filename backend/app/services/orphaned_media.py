"""Finding uploaded objects that nothing references, and only those.

The problem
-----------
One upload flow writes an object before anything points at it. The
Conversations composer uploads as soon as a member picks an image and
gets back a URL; the post that carries that URL is saved later, or
never. Remove the image, close the composer, abandon the draft — the
object stays in R2 for ever, referenced by nothing.

Why this is deliberately narrow
-------------------------------
"Delete every unreferenced object" is the wrong instrument, because
*unreferenced* means different things per namespace. A Media Library
asset is unreferenced by any post the moment it is uploaded and is
supposed to be: its ``creator_media_assets`` row owns it, and archiving
that row keeps the object on purpose. Platform artwork is referenced
from config and templates. So eligibility is a property of the upload
*class*, established by reading each writer, not of the object.

Exactly one namespace is eligible here: ``media/{slug}/community/`` —
the only flow proven to publish a URL to a browser before any row
exists. Everything else is listed, classified and reported, so the next
pass argues from the audit rather than from a guess.

The bias
--------
Leaving an orphan costs a few cents a year. Deleting a referenced object
destroys something a member made and cannot be undone. Every ambiguity
therefore resolves to "keep":

  * an unrecognised key shape is not a candidate
  * a slug that resolves to no Collective is not a candidate
  * a filename that does not match what the writer produces is not a
    candidate
  * any hit, anywhere, in any text or JSON column, in any
    representation, is a live reference
  * a storage backend that errors aborts rather than reporting an empty
    listing — "I found nothing" and "I could not look" must never be
    the same answer

Age comes from the object's own ``LastModified``, because an orphan has
no row to carry a created-at.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import storage

logger = logging.getLogger(__name__)

URL_PREFIX = "/api/uploads/"

#: Long enough that a member can pick an image, write a long post, get
#: interrupted, and come back the next day to publish it. Short enough
#: that abandoned uploads do not accumulate for months. The composer
#: holds its URL in browser state only, so the realistic exposure is a
#: single session plus whatever a reopened tab survives.
DEFAULT_GRACE_HOURS = 72

#: Below this, a sweep stops protecting the upload-then-save window it
#: exists to protect, and starts racing the member who is still typing.
#: Overridable only by saying so in as many words.
MINIMUM_GRACE_HOURS = 24

UNSAFE_OVERRIDE_FLAG = "--yes-i-accept-deleting-in-flight-uploads"

#: What ``save_media_file``/``save_file`` name an object:
#: ``{uuid4().hex}_{sanitised stem}{ext}``. The 32 hex characters are
#: what make a filename search a reliable reference test, so a filename
#: that does not have them is not something this job can reason about.
_WRITER_FILENAME = re.compile(r"^[0-9a-f]{32}_[\w\-]*\.[A-Za-z0-9]+$")


# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Namespace:
    """One upload class, as read off its writer."""

    name: str
    #: True only where the object can exist with no row by design, and
    #: the only thing that ever references it is a column this job can
    #: search exhaustively.
    eligible: bool
    #: Printed in the audit next to every object, so an exclusion is
    #: always accompanied by its reason.
    note: str


NAMESPACES: dict[str, Namespace] = {
    "conversation-image": Namespace(
        "conversation-image", True,
        "uploaded by the composer before any row exists; referenced only "
        "by community_posts.image_url / post_comments.image_url",
    ),
    "world-guide-image": Namespace(
        "world-guide-image", False,
        "same upload-before-save lifecycle, but the URL is pasted into "
        "Markdown by hand and lands in rich-text columns — reportable, "
        "not yet eligible",
    ),
    "media-library": Namespace(
        "media-library", False,
        "owned by a creator_media_assets row from the moment of upload; "
        "archiving that row deliberately keeps the object",
    ),
    "legacy-flattened": Namespace(
        "legacy-flattened", False,
        "historical key shape from the migrated Conversations flattening "
        "— handled by its own one-time script",
    ),
    "avatar": Namespace(
        "avatar", False,
        "row updated in the same request; replacement deletes the old "
        "object already",
    ),
    "space-cover": Namespace(
        "space-cover", False,
        "row updated in the same request; replacement deletes the old "
        "object already",
    ),
    "space-logo": Namespace(
        "space-logo", False,
        "row updated in the same request; replacement deletes the old "
        "object already",
    ),
    "pathway-cover": Namespace(
        "pathway-cover", False,
        "row updated in the same request; replacement deletes the old "
        "object already",
    ),
    "event-thumbnail": Namespace(
        "event-thumbnail", False,
        "row updated in the same request; replacement deletes the old "
        "object already",
    ),
    "step-resource": Namespace(
        "step-resource", False,
        "owned by a step_resources row, which stores the BARE key rather "
        "than a URL — a reference shape a URL-only scan would miss",
    ),
    "platform-artwork": Namespace(
        "platform-artwork", False,
        "platform/static artwork in the public bucket — brand assets, "
        "Atlas and Place artwork; referenced from config and templates",
    ),
    "island-artwork": Namespace(
        "island-artwork", False,
        "generated Collective artwork; no writer found in application "
        "code, so its lifecycle is not established",
    ),
    "unclassified": Namespace(
        "unclassified", False,
        "key shape matches no known writer — excluded by default-deny",
    ),
}

#: Listed separately because the bucket is chosen by key prefix: one
#: sweep of the private bucket from the root, one of the public artwork
#: prefix. A single root listing would silently cover only one of them.
LISTING_PREFIXES: tuple[str, ...] = ("", "platform-artwork/")


def classify(key: str) -> str:
    """Which upload class a key belongs to. Default-deny."""
    if key.startswith("platform-artwork/"):
        return "platform-artwork"
    if key.startswith("avatars/"):
        return "avatar"
    if key.startswith("covers/"):
        return "space-cover"
    if key.startswith("logos/"):
        return "space-logo"
    if key.startswith("pathway-covers/"):
        return "pathway-cover"
    if key.startswith("event-thumbnails/"):
        return "event-thumbnail"
    if key.startswith("steps/"):
        return "step-resource"
    if key.startswith("island-artwork/"):
        return "island-artwork"

    if key.startswith("media/"):
        parts = key.split("/")
        # media/world-guide/{file}
        if len(parts) == 3 and parts[1] == "world-guide":
            return "world-guide-image"
        # media/{slug}/community/{file} — the eligible shape.
        if len(parts) == 4 and parts[2] == "community":
            return "conversation-image"
        if len(parts) == 3:
            # media/{slug}_community/{file} is the flattened legacy
            # shape, which is a single segment and would otherwise look
            # like an ordinary library key for a Collective that does
            # not exist.
            if parts[1].endswith("_community"):
                return "legacy-flattened"
            return "media-library"
    return "unclassified"


# ---------------------------------------------------------------------------
# Reference detection
# ---------------------------------------------------------------------------


def searchable_columns(db: Session) -> list[tuple[str, str, bool]]:
    """Every text-ish or JSON column that could carry an upload
    reference, as ``(table, column, needs_cast)``.

    Deliberately not filtered by column name. A reference can sit in
    ``image_url``, but it can equally sit inside a block-editor
    document, a serialised email payload or a template body, and the
    whole point of this scan is that it does not need to know which.

    Restricted to tables with an ``id`` column so every query it then
    runs is known to be valid — a scan that catches query failures and
    carries on would turn "could not look" into "found nothing".
    """
    rows = db.execute(text(
        "SELECT c.table_name, c.column_name, c.data_type "
        "FROM information_schema.columns c "
        "JOIN information_schema.tables t "
        "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
        " AND t.table_type = 'BASE TABLE' "
        "WHERE c.table_schema = 'public' "
        "  AND c.data_type IN ('text', 'character varying', 'character', "
        "                      'json', 'jsonb') "
        "  AND EXISTS ("
        "    SELECT 1 FROM information_schema.columns k "
        "    WHERE k.table_schema = c.table_schema "
        "      AND k.table_name = c.table_name AND k.column_name = 'id'"
        "  ) "
        "ORDER BY c.table_name, c.column_name"
    )).all()
    return [
        (r[0], r[1], r[2] in ("json", "jsonb"))
        for r in rows
    ]


def needles_for(key: str) -> list[str]:
    """What to search for, to catch every representation at once.

    The filename is the one that matters. It carries 32 hex characters
    from ``uuid4()``, so it is globally unique, and it is a substring of
    the bare key, of the canonical ``/api/uploads/…`` URL, of a
    percent-encoded URL (nothing in a sanitised filename encodes), and
    of any of those embedded in JSON or rich text. Searching it is
    strictly broader than searching any single representation, which is
    the direction to err in.

    The key and the URL are searched too, so the report can say which
    form matched when one does.
    """
    filename = key.rsplit("/", 1)[-1]
    return [filename, key, URL_PREFIX + key]


def find_references(db: Session, keys: list[str]) -> dict[str, list[str]]:
    """Map each key to the places that reference it.

    One query per column for all keys at once, rather than one per
    (key, column): the work is in scanning the table, and doing it once
    per column keeps a sweep of hundreds of candidates to the same cost
    as a sweep of one.

    ``strpos``, never ``LIKE`` — these keys are full of underscores and
    ``LIKE`` reads ``_`` as "any character", which is how a search for
    ``media/x_community/f`` quietly matches ``media/x/community/f``.

    Grouped by needle rather than capped with a row limit. A ``LIMIT``
    here would be a correctness bug, not a performance tweak: one
    heavily-referenced key could fill the quota and hide every hit for
    the others in the same column, and a missed hit means an object
    that *is* referenced gets reported as an orphan. Grouping bounds
    the result to one row per needle while keeping every needle's
    answer.
    """
    hits: dict[str, list[str]] = {k: [] for k in keys}
    if not keys:
        return hits

    needle_to_key: dict[str, str] = {}
    for key in keys:
        for needle in needles_for(key):
            needle_to_key[needle] = key
    all_needles = list(needle_to_key)

    for table, column, needs_cast in searchable_columns(db):
        expr = f'CAST("{column}" AS text)' if needs_cast else f'"{column}"'
        rows = db.execute(text(
            f"SELECT n, min(CAST(id AS text)) AS sample_id, count(*) AS n_rows "
            f'FROM "{table}" '  # noqa: S608 - table from the catalogue
            f"CROSS JOIN LATERAL unnest(CAST(:needles AS text[])) AS n "
            f"WHERE strpos({expr}, n) > 0 "
            f"GROUP BY n"
        ), {"needles": all_needles}).all()
        for needle, sample_id, n_rows in rows:
            key = needle_to_key.get(needle)
            if key is None:
                continue
            # All three needles for a key are substrings of one another,
            # so one row routinely matches all three. Report the place
            # once.
            more = f" (+{n_rows - 1} more)" if n_rows > 1 else ""
            where = f"{table}.{column}={sample_id}{more}"
            if where not in hits[key]:
                hits[key].append(where)
    return hits


def owning_media_asset(db: Session, key: str) -> str | None:
    """A ``creator_media_assets`` row that owns this object, if any.

    Checked explicitly as well as by the broad scan. The broad scan
    would find it, but an exclusion this important should be visible in
    the report as its own reason rather than as a generic hit, and the
    row survives archiving on purpose.
    """
    row = db.execute(text(
        "SELECT id, status FROM creator_media_assets "
        "WHERE storage_path = :k OR file_url = :u OR storage_path = :u "
        "LIMIT 1"
    ), {"k": key, "u": URL_PREFIX + key}).first()
    return f"creator_media_assets={row[0]} (status={row[1]})" if row else None


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One storage object and everything known about it."""

    key: str
    size: int
    last_modified: datetime
    namespace: str

    age_hours: float = 0.0
    content_type: str | None = None
    space_slug: str | None = None
    space_id: str | None = None

    references: list[str] = field(default_factory=list)
    owning_asset: str | None = None
    exclusions: list[str] = field(default_factory=list)

    @property
    def orphan(self) -> bool:
        return not self.exclusions

    @property
    def filename(self) -> str:
        return self.key.rsplit("/", 1)[-1]


@dataclass
class AuditReport:
    grace_hours: int
    now: datetime
    storage_mode: str
    prefixes: tuple[str, ...]
    columns_scanned: int = 0
    total_scanned: int = 0
    by_namespace: dict[str, int] = field(default_factory=dict)
    too_young: list[Candidate] = field(default_factory=list)
    referenced: list[Candidate] = field(default_factory=list)
    owned: list[Candidate] = field(default_factory=list)
    excluded_namespace: dict[str, int] = field(default_factory=dict)
    #: Every object excluded by its namespace, kept rather than counted.
    #: A count alone cannot answer "which two objects are those?", which
    #: is the first thing an operator asks about an excluded group.
    excluded: list[Candidate] = field(default_factory=list)
    unclassified: list[Candidate] = field(default_factory=list)
    orphans: list[Candidate] = field(default_factory=list)
    #: How many objects actually reached the reference scan. Printed, so
    #: "has a live reference 0" can never be read as "none of these is
    #: referenced" when it might mean "none of them was checked".
    reference_checked: int = 0

    def in_namespace(self, namespace: str) -> list[Candidate]:
        """Every candidate in one namespace, whatever became of it."""
        groups = (
            self.orphans, self.referenced, self.owned, self.too_young,
            self.unclassified, self.excluded,
        )
        return [c for group in groups for c in group if c.namespace == namespace]

    @property
    def reclaimable_bytes(self) -> int:
        return sum(c.size for c in self.orphans)


def audit(
    db: Session, *, grace_hours: int = DEFAULT_GRACE_HOURS,
    now: datetime | None = None,
) -> AuditReport:
    """Classify every stored object and decide which are orphans.

    Writes nothing.
    """
    now = now or datetime.now(timezone.utc)
    report = AuditReport(
        grace_hours=grace_hours,
        now=now,
        storage_mode="R2" if _r2_enabled() else "filesystem",
        prefixes=LISTING_PREFIXES,
    )
    cutoff = now - timedelta(hours=grace_hours)

    objects: dict[str, storage.StoredObject] = {}
    for prefix in LISTING_PREFIXES:
        # Raises on a backend failure, by design. A partial listing
        # treated as complete is how a reconciliation job deletes
        # something it merely failed to see.
        for obj in storage.list_objects(prefix):
            objects[obj.key] = obj

    report.total_scanned = len(objects)

    eligible: list[Candidate] = []
    for key, obj in sorted(objects.items()):
        ns = classify(key)
        report.by_namespace[ns] = report.by_namespace.get(ns, 0) + 1
        candidate = Candidate(
            key=key, size=obj.size, last_modified=obj.last_modified,
            namespace=ns,
            age_hours=(now - _aware(obj.last_modified)).total_seconds() / 3600,
        )

        if not NAMESPACES[ns].eligible:
            candidate.exclusions.append(f"namespace '{ns}' is not eligible")
            if ns == "unclassified":
                report.unclassified.append(candidate)
            else:
                report.excluded.append(candidate)
            report.excluded_namespace[ns] = (
                report.excluded_namespace.get(ns, 0) + 1
            )
            continue

        if not _WRITER_FILENAME.match(candidate.filename):
            # Not something either writer produced, so its name is not
            # a dependable unique handle and this job cannot establish
            # that nothing references it.
            candidate.exclusions.append(
                f"filename '{candidate.filename}' is not the shape the "
                f"uploader produces"
            )
            report.unclassified.append(candidate)
            continue

        slug = key.split("/")[1]
        candidate.space_slug = slug
        row = db.execute(text(
            "SELECT id FROM spaces WHERE slug = :s"
        ), {"s": slug}).first()
        if row is None:
            candidate.exclusions.append(
                f"no Collective with slug '{slug}' — cannot establish what "
                f"this belongs to"
            )
            report.unclassified.append(candidate)
            continue
        candidate.space_id = row[0]

        # Age is applied below, *after* the reference scan, not here.
        # Short-circuiting on it was safe — a young object was never
        # deleted — but it made the report unreadable: an object
        # protected by a live reference and one protected only by being
        # recent came out indistinguishable, both reported as "inside
        # the grace period" with "has a live reference 0" beside them.
        # That is exactly the pair of facts an operator needs separated
        # before pressing --apply, and it mattered in practice: the
        # object the legacy migration had just copied looked, in the
        # report, like an unreferenced file waiting out its grace
        # period.
        eligible.append(candidate)

    # One reference sweep for every in-namespace object, regardless of
    # age. The cost is per column, not per key, so widening this is
    # free; what it buys is that nothing in the eligible namespace is
    # ever reported without its reference status known.
    columns = searchable_columns(db)
    report.columns_scanned = len(columns)
    found = find_references(db, [c.key for c in eligible])
    report.reference_checked = len(eligible)

    for candidate in eligible:
        candidate.references = found.get(candidate.key, [])
        candidate.owning_asset = owning_media_asset(db, candidate.key)
        if candidate.owning_asset:
            candidate.exclusions.append(
                f"owned by {candidate.owning_asset}"
            )
            report.owned.append(candidate)
            continue
        if candidate.references:
            # Reported as referenced whatever its age. A referenced
            # object is kept because something points at it, and that is
            # the reason worth printing.
            candidate.exclusions.append(
                f"{len(candidate.references)} live reference(s): "
                + ", ".join(candidate.references[:5])
            )
            report.referenced.append(candidate)
            continue
        if _aware(candidate.last_modified) > cutoff:
            candidate.exclusions.append(
                f"{candidate.age_hours:.1f}h old, inside the {grace_hours}h "
                f"grace period"
            )
            report.too_young.append(candidate)
            continue
        report.orphans.append(candidate)

    # Content type only for the handful that survived. A listing does
    # not carry it and a HEAD per object would be wasteful across a
    # whole bucket, but the report should say what it is about to
    # delete.
    for candidate in report.orphans:
        info = storage.object_head(candidate.key)
        if info is not None:
            candidate.content_type = info.content_type

    return report


def _r2_enabled() -> bool:
    from app.core.config import settings
    return bool(settings.is_r2_enabled)


def _aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC. R2 returns aware datetimes; a
    filesystem stat might not, depending on the platform."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def describe_namespace(
    db: Session, report: AuditReport, namespace: str,
) -> list[Candidate]:
    """Fill in reference status and content type for one namespace.

    Read-only. Needed because an excluded namespace is, by design, not
    reference-scanned during the audit — there is no point searching the
    database for objects nothing will delete. But "which two objects are
    those, and is anything still pointing at them?" is the first
    question an operator asks about an excluded group, and answering it
    should not require a different tool.

    Scoped to one namespace rather than widening the audit, so asking
    about two legacy keys does not pull every object in the bucket
    through a schema-wide search.
    """
    candidates = report.in_namespace(namespace)
    if not candidates:
        return []

    found = find_references(db, [c.key for c in candidates])
    for candidate in candidates:
        candidate.references = found.get(candidate.key, [])
        candidate.owning_asset = owning_media_asset(db, candidate.key)
        info = storage.object_head(candidate.key)
        if info is not None:
            candidate.content_type = info.content_type
    return candidates


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


@dataclass
class DeleteOutcome:
    deleted: list[Candidate] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    freed_bytes: int = 0


def delete_orphans(
    db: Session, candidates: list[Candidate], *,
    grace_hours: int = DEFAULT_GRACE_HOURS, now: datetime | None = None,
) -> DeleteOutcome:
    """Delete the candidates that still qualify, one at a time.

    Every predicate is re-evaluated immediately before each delete,
    against the database as it is now rather than as it was when the
    audit ran. The audit can be minutes or hours old by the time
    somebody reads it and types ``--apply``, and in that window a member
    can publish the post that references one of these objects. So a
    candidate that has gained a reference is skipped, not deleted, and
    the run continues.

    Storage errors are fatal. ``storage.delete_file`` swallows them, so
    success is established by re-reading the object rather than by the
    call returning.
    """
    now = now or datetime.now(timezone.utc)
    outcome = DeleteOutcome()

    for candidate in candidates:
        # Fresh HEAD: existence, size and age all re-read from storage.
        info = storage.object_head(candidate.key)
        if info is None:
            outcome.skipped.append(
                (candidate.key, "already gone from storage")
            )
            continue

        if classify(candidate.key) != candidate.namespace or not NAMESPACES[
            classify(candidate.key)
        ].eligible:
            outcome.skipped.append(
                (candidate.key, "namespace classification no longer eligible")
            )
            continue

        if info.last_modified is None:
            # No timestamp means no way to re-establish age, and age is
            # the predicate protecting an in-flight upload.
            outcome.skipped.append(
                (candidate.key, "storage reported no modification time")
            )
            continue
        age_hours = (
            now - _aware(info.last_modified)
        ).total_seconds() / 3600
        if age_hours < grace_hours:
            # Re-uploaded under the same key, or the clock moved. Either
            # way it is no longer outside the grace window.
            outcome.skipped.append(
                (candidate.key,
                 f"now only {age_hours:.1f}h old, inside the {grace_hours}h "
                 f"grace period")
            )
            continue

        # Ownership before the broad scan, in the same order as the
        # audit: an owning row would also show up as a generic hit, and
        # "now owned by creator_media_assets=…" says far more about why
        # this object is staying than "something mentions it".
        owner = owning_media_asset(db, candidate.key)
        if owner:
            outcome.skipped.append(
                (candidate.key, f"now owned by {owner}")
            )
            continue
        references = find_references(db, [candidate.key]).get(candidate.key, [])
        if references:
            outcome.skipped.append(
                (candidate.key,
                 f"a reference appeared since the audit: "
                 f"{', '.join(references[:3])}")
            )
            continue

        storage.delete_file(candidate.key)
        if storage.object_head(candidate.key) is not None:
            raise RuntimeError(
                f"delete reported no error but {candidate.key} is still "
                f"there — aborting rather than reporting a success"
            )
        logger.info("orphaned_media: deleted %s", candidate.key)
        outcome.deleted.append(candidate)
        outcome.freed_bytes += candidate.size

    return outcome
