"""Move legacy Conversation images onto the key they should have had.

The bug
-------
``save_media_file`` used to sanitise the whole ``space_slug`` string, so
Collective Conversations — the one caller that passed a path — had its
separator flattened::

    expected:  media/{slug}/community/{file}
    written:   media/{slug}_community/{file}

The writer was fixed, so new uploads are nested. Objects written before
that are still at the flattened key, still referenced by live posts and
comments, and are readable only because
``uploads/authorization._authorise_media`` learned to resolve the old
shape.

That compatibility branch carries a small edge: it resolves a plain slug
first, so a Collective whose slug genuinely *was* ``{target}_community``
would match before the legacy interpretation and its members could read
the target's legacy Conversation images. Not reachable for anything
written after the fix — a nested key puts the slug in a whole segment
that naming cannot spoof — but it is only closable by moving the old
objects and then deleting the branch.

What is actually stored
-----------------------
A **URL path**, not a bare key: ``community_posts.image_url`` and
``post_comments.image_url`` hold ``/api/uploads/media/…``. So migrating
means rewriting the URL, and the storage key is that URL minus the
``/api/uploads/`` prefix. Both the legacy and canonical keys begin
``media/``, so both route to the private bucket and the copy is
same-bucket.

Order of operations
-------------------
Copy, verify, update the reference, then delete — in that order, and
never the other way round. The storage and the database cannot be
committed together, so the boundary is chosen deliberately: if the
database update fails after the copy, an extra duplicate object is left
behind, which costs pennies. Deleting first, or deleting before the
reference moves, would risk the only readable copy of a member's image.

Re-runnable. A reference already canonical is reported and skipped, and
a candidate whose destination already matches the source is treated as a
completed copy rather than a collision.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import storage

logger = logging.getLogger(__name__)

#: The URL prefix the DB stores in front of a storage key.
URL_PREFIX = "/api/uploads/"

#: The suffix the old flattening produced.
LEGACY_SUFFIX = "_community"

#: Where a Conversation image belongs, as a format.
CANONICAL_PREFIX = "media/{slug}/community/"

#: Columns that can reference a Conversation image. Both store a URL.
#: ``creator_media_assets`` is deliberately absent: its caller passed a
#: single-segment ``space.slug``, so it was never affected — confirmed
#: against real data, 81 rows and none flattened.
REFERENCE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("community_posts", "image_url"),
    ("post_comments", "image_url"),
)

_LEGACY_KEY = re.compile(r"^media/(?P<flat>[^/]+_community)/(?P<file>.+)$")


@dataclass
class Candidate:
    """One database reference to a legacy object."""

    table: str
    column: str
    row_id: str
    url: str
    source_key: str
    flat_segment: str
    derived_slug: str
    filename: str
    dest_key: str | None = None
    dest_url: str | None = None

    space_id: str | None = None
    space_slug: str | None = None
    space_name: str | None = None
    author_email: str | None = None
    created_at: object | None = None

    source_exists: bool = False
    source_info: object | None = None
    dest_exists: bool = False
    dest_info: object | None = None
    other_references: int = 0

    blockers: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.blockers

    @property
    def already_copied(self) -> bool:
        """Destination present and identical — the copy half is done."""
        a, b = self.source_info, self.dest_info
        if a is None or b is None:
            return False
        return a.size == b.size and (
            a.etag is None or b.etag is None or a.etag == b.etag
        )


def parse_legacy_key(url: str | None) -> tuple[str, str, str] | None:
    """``(flat_segment, derived_slug, filename)`` for a legacy URL.

    Returns None for anything already canonical or unrelated, so the
    caller never has to guess which shape it is looking at.
    """
    if not url or URL_PREFIX not in url:
        return None
    key = url.split(URL_PREFIX, 1)[1]
    m = _LEGACY_KEY.match(key)
    if not m:
        return None
    flat = m.group("flat")
    return flat, flat[: -len(LEGACY_SUFFIX)], m.group("file")


def audit(db: Session) -> list[Candidate]:
    """Every legacy reference, fully described. Writes nothing."""
    candidates: list[Candidate] = []

    for table, column in REFERENCE_COLUMNS:
        rows = db.execute(text(
            f"SELECT id, {column} FROM {table} "  # noqa: S608 - fixed allowlist
            f"WHERE {column} LIKE :pattern"
        ), {"pattern": f"%{URL_PREFIX}media/%{LEGACY_SUFFIX}/%"}).all()

        for row_id, url in rows:
            parsed = parse_legacy_key(url)
            if parsed is None:
                continue
            flat, slug, filename = parsed
            c = Candidate(
                table=table, column=column, row_id=row_id, url=url,
                source_key=url.split(URL_PREFIX, 1)[1],
                flat_segment=flat, derived_slug=slug, filename=filename,
            )
            _resolve_owner(db, c)
            _resolve_objects(db, c)
            _count_other_references(db, c)
            candidates.append(c)

    return candidates


def _resolve_owner(db: Session, c: Candidate) -> None:
    """Which Collective this belongs to, and refuse if it is ambiguous."""
    # The flattened segment could, in principle, be a real slug. If a
    # Collective is actually named that, the key is not legacy at all
    # and must be left alone — that is the exact ambiguity the
    # compatibility resolver has to live with, and the reason this
    # refuses rather than guesses.
    literal = db.execute(text(
        "SELECT id, slug, name FROM spaces WHERE slug = :s"
    ), {"s": c.flat_segment}).first()
    if literal is not None:
        c.blockers.append(
            f"'{c.flat_segment}' is a real Collective slug, so this key may "
            f"not be legacy at all"
        )
        return

    owner = db.execute(text(
        "SELECT id, slug, name FROM spaces WHERE slug = :s"
    ), {"s": c.derived_slug}).first()
    if owner is None:
        c.blockers.append(
            f"no Collective with slug '{c.derived_slug}' — owner cannot be "
            f"resolved"
        )
        return

    c.space_id, c.space_slug, c.space_name = owner[0], owner[1], owner[2]
    c.dest_key = CANONICAL_PREFIX.format(slug=c.space_slug) + c.filename
    c.dest_url = URL_PREFIX + c.dest_key

    # The post or comment must belong to that same Collective, or the
    # derived destination would move somebody's image into a Collective
    # it was never part of.
    owning_space = _row_space_id(db, c)
    if owning_space is not None and owning_space != c.space_id:
        c.blockers.append(
            f"{c.table}.{c.row_id} belongs to space {owning_space}, not to "
            f"'{c.derived_slug}' ({c.space_id})"
        )


def _row_space_id(db: Session, c: Candidate) -> str | None:
    """The Collective the referencing row actually sits in."""
    if c.table == "community_posts":
        row = db.execute(text(
            "SELECT p.space_id, u.email, p.created_at FROM community_posts p "
            "LEFT JOIN users u ON u.id = p.author_id WHERE p.id = :i"
        ), {"i": c.row_id}).first()
    else:
        row = db.execute(text(
            "SELECT p.space_id, u.email, c.created_at "
            "FROM post_comments c "
            "JOIN community_posts p ON p.id = c.post_id "
            "LEFT JOIN users u ON u.id = c.author_id WHERE c.id = :i"
        ), {"i": c.row_id}).first()
    if row is None:
        return None
    c.author_email, c.created_at = row[1], row[2]
    return row[0]


def _resolve_objects(db: Session, c: Candidate) -> None:
    """Does the source exist, and is anything already at the destination?"""
    try:
        c.source_info = storage.object_head(c.source_key)
    except Exception as exc:  # pragma: no cover - backend failure
        c.blockers.append(f"could not read the source object: {exc}")
        return
    c.source_exists = c.source_info is not None
    if not c.source_exists:
        c.blockers.append(f"source object is missing: {c.source_key}")

    if not c.dest_key:
        return
    try:
        c.dest_info = storage.object_head(c.dest_key)
    except Exception as exc:  # pragma: no cover
        c.blockers.append(f"could not read the destination object: {exc}")
        return
    c.dest_exists = c.dest_info is not None

    if c.dest_exists and c.source_exists and not c.already_copied:
        c.blockers.append(
            f"destination already exists with different content "
            f"(source {c.source_info.size}B vs dest {c.dest_info.size}B) — "
            f"refusing to overwrite"
        )


def _count_other_references(db: Session, c: Candidate) -> None:
    """Anything else pointing at the same object.

    Shared references are not a blocker by themselves — every one of
    them is rewritten in the same transaction — but an unexpected count
    is worth seeing before pressing apply.
    """
    total = 0
    for table, column in REFERENCE_COLUMNS:
        total += db.scalar(text(
            f"SELECT count(*) FROM {table} WHERE {column} = :u"  # noqa: S608
        ), {"u": c.url}) or 0
    c.other_references = total - 1


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

@dataclass
class MigrationResult:
    copied: list[str] = field(default_factory=list)
    references_updated: int = 0
    deleted: list[str] = field(default_factory=list)
    already_canonical: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def migrate(
    db: Session, candidates: list[Candidate], *, delete_source: bool = True,
) -> MigrationResult:
    """Copy, verify, repoint, then delete. Caller commits.

    Ordering is the whole safety argument. Storage and the database
    cannot commit together, so the failure left behind is chosen: a
    duplicate object costs pennies, a deleted-too-early object costs a
    member their image.
    """
    result = MigrationResult()

    for c in candidates:
        if not c.safe:
            result.skipped.append(
                f"{c.table}.{c.row_id}: " + "; ".join(c.blockers)
            )
            continue
        assert c.dest_key and c.dest_url  # guaranteed by a clean audit

        # 1. Copy, unless an identical object is already there from a
        #    previous run that stopped partway.
        if c.already_copied:
            logger.info(
                "legacy_community_media: destination already matches, "
                "skipping copy for %s", c.dest_key,
            )
        else:
            storage.copy_object(c.source_key, c.dest_key)
            result.copied.append(f"{c.source_key} -> {c.dest_key}")

        # 2. Verify the copy before anything else happens.
        after = storage.object_head(c.dest_key)
        if after is None:
            raise RuntimeError(
                f"copy reported success but {c.dest_key} is not there"
            )
        if c.source_info is not None and after.size != c.source_info.size:
            raise RuntimeError(
                f"copied object differs in size: {c.source_key} "
                f"{c.source_info.size}B -> {c.dest_key} {after.size}B"
            )
        if (
            c.source_info is not None
            and c.source_info.etag and after.etag
            and c.source_info.etag != after.etag
        ):
            raise RuntimeError(
                f"copied object differs in content hash: {c.source_key}"
            )

        # 3. Repoint every reference to this exact URL, in the caller's
        #    transaction. Matched on the full URL rather than row id so
        #    a shared object moves all of its references at once.
        for table, column in REFERENCE_COLUMNS:
            res = db.execute(text(
                f"UPDATE {table} SET {column} = :new "  # noqa: S608
                f"WHERE {column} = :old"
            ), {"new": c.dest_url, "old": c.url})
            result.references_updated += res.rowcount or 0

        # 4. Delete the source. Last, and only now.
        if delete_source:
            storage.delete_file(c.source_key)
            result.deleted.append(c.source_key)

    return result


def remaining_legacy_references(db: Session) -> int:
    """For the re-audit that has to come back zero before the
    compatibility resolver can be removed."""
    return len(audit(db))
