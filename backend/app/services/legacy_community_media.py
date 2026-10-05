"""Move legacy Conversation images onto the key they should have had.

The bug
-------
``save_media_file`` used to sanitise the whole ``space_slug`` string, so
Collective Conversations — the one caller that passed a path — had its
separator flattened::

    expected:  media/{slug}/community/{file}
    written:   media/{slug}_community/{file}

The writer was fixed, so new uploads are nested. Objects written before
that sat at the flattened key, readable only because
``uploads/authorization._authorise_media`` had learned to resolve the
old shape — a compatibility branch with a small edge, since it resolved
a plain slug first and so a Collective genuinely named
``{target}_community`` would match ahead of the legacy interpretation.

Production has now been migrated: one reference, one object, zero legacy
references remaining, and the compatibility branch is deleted. What is
left here is the audit that proves it stays that way, and the cleanup of
the orphaned object at the bottom of this module.

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
        # ``ESCAPE`` and a backslashed underscore, because ``LIKE``
        # reads a bare ``_`` as "any character" — and the legacy and
        # canonical keys differ only in whether the separator before
        # ``community`` is ``_`` or ``/``. Unescaped, this prefilter
        # pulls in every canonical URL too; the regex below then
        # discards them, so the result was right and the query was not.
        rows = db.execute(text(
            f"SELECT id, {column} FROM {table} "  # noqa: S608 - fixed allowlist
            f"WHERE {column} LIKE :pattern ESCAPE '\\'"
        ), {"pattern": f"%{URL_PREFIX}media/%\\{LEGACY_SUFFIX}/%"}).all()

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


# ---------------------------------------------------------------------------
# Orphan cleanup
# ---------------------------------------------------------------------------
#
# After the migration, the old object is deliberately unreferenced: the
# database is canonical, so nothing points at the flattened key any
# more. That makes DB discovery useless for finding it — the absence of
# a reference is the goal, not the signal — so this half works from an
# explicit key pair and proves the object is safe to lose rather than
# inferring it.


@dataclass
class OrphanCheck:
    """One legacy object, examined against its canonical replacement."""

    source_key: str
    dest_key: str

    source_info: object | None = None
    dest_info: object | None = None

    legacy_references: list[str] = field(default_factory=list)
    canonical_references: list[str] = field(default_factory=list)
    columns_scanned: int = 0

    member_allowed: str | None = None
    non_member_denied: str | None = None

    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def source_url(self) -> str:
        return URL_PREFIX + self.source_key

    @property
    def dest_url(self) -> str:
        return URL_PREFIX + self.dest_key

    @property
    def source_exists(self) -> bool:
        return self.source_info is not None

    @property
    def already_deleted(self) -> bool:
        """Re-run of a completed cleanup. Not a failure."""
        return self.source_info is None

    @property
    def safe(self) -> bool:
        return not self.blockers


#: Column names worth searching for a surviving reference. Broader than
#: ``REFERENCE_COLUMNS`` on purpose: that list is where a Conversation
#: image is *written*, which is the right scope for a migration, but
#: this is about to delete bytes. Before that, the question is whether
#: *anything* in the database still points at them.
_MEDIA_COLUMN_PATTERNS = (
    "%url%", "%image%", "%media%", "%thumbnail%",
    "%asset%", "%artwork%", "%avatar%", "%logo%", "%cover%",
)


def media_text_columns(db: Session) -> list[tuple[str, str]]:
    """Every text-ish column that could plausibly hold a media URL.

    Restricted in SQL to tables that also have an ``id`` column, so
    every query the scan then runs is known to be valid. The earlier
    shape tried each column and caught failures, which meant a
    ``rollback()`` inside the caller's transaction — quietly discarding
    whatever the caller had not committed yet.
    """
    rows = db.execute(text(
        "SELECT c.table_name, c.column_name FROM information_schema.columns c "
        "JOIN information_schema.tables t "
        "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
        " AND t.table_type = 'BASE TABLE' "
        "WHERE c.table_schema = 'public' "
        "  AND c.data_type IN ('text', 'character varying', 'character') "
        "  AND (" + " OR ".join(
            f"c.column_name LIKE :p{i}"
            for i in range(len(_MEDIA_COLUMN_PATTERNS))
        ) + ") "
        "  AND EXISTS ("
        "    SELECT 1 FROM information_schema.columns k "
        "    WHERE k.table_schema = c.table_schema "
        "      AND k.table_name = c.table_name AND k.column_name = 'id'"
        "  ) "
        "ORDER BY c.table_name, c.column_name"
    ), {f"p{i}": p for i, p in enumerate(_MEDIA_COLUMN_PATTERNS)}).all()
    return [(r[0], r[1]) for r in rows]


def find_references(db: Session, url: str) -> tuple[list[str], int]:
    """Where this URL still appears, as ``table.column=id`` strings.

    Matched as a substring, not equality: a URL embedded in rich-text
    or JSON-ish content counts just as much as one in its own column
    when the question is "will deleting this break a page".

    ``strpos`` rather than ``LIKE``, because these URLs are full of
    underscores and ``LIKE`` reads ``_`` as "any character". The legacy
    and canonical keys differ only in whether the separator before
    ``community`` is ``_`` or ``/`` — so a ``LIKE`` search for the
    legacy URL matches the canonical one, and every properly migrated
    object looks like it still has a live legacy reference.
    """
    hits: list[str] = []
    columns = media_text_columns(db)
    for table, column in columns:
        rows = db.execute(text(
            f'SELECT id FROM "{table}" '  # noqa: S608 - from the catalogue
            f'WHERE strpos("{column}", :needle) > 0 LIMIT 25'
        ), {"needle": url}).all()
        hits.extend(f"{table}.{column}={r[0]}" for r in rows)
    return hits, len(columns)


def check_orphan(db: Session, source_key: str, dest_key: str) -> OrphanCheck:
    """Can this legacy object be deleted? Writes nothing.

    Every condition is proved, not assumed. The object is about to stop
    existing, and the only acceptable evidence that nobody needs it is
    that its replacement is byte-identical, present, referenced, and
    readable by exactly the people who should read it.
    """
    c = OrphanCheck(source_key=source_key, dest_key=dest_key)

    c.source_info = storage.object_head(source_key)
    c.dest_info = storage.object_head(dest_key)

    # The canonical object has to be there whether or not the source
    # still is — that is the one this check exists to protect.
    if c.dest_info is None:
        c.blockers.append(f"canonical object is missing: {dest_key}")

    if c.source_info is None:
        c.notes.append(
            "legacy object is already gone — this has run before, or the "
            "migration deleted it. Nothing to delete."
        )
    elif c.dest_info is not None:
        if c.source_info.size != c.dest_info.size:
            c.blockers.append(
                f"sizes differ: legacy {c.source_info.size}B vs canonical "
                f"{c.dest_info.size}B — these are not the same object"
            )
        src_tag, dst_tag = c.source_info.etag, c.dest_info.etag
        if src_tag and dst_tag:
            if src_tag != dst_tag:
                c.blockers.append(
                    f"content hashes differ: {src_tag} vs {dst_tag}"
                )
        else:
            # Not a blocker. R2 returns a plain MD5 etag for a
            # single-part upload and a composite one for multipart, so
            # an absent or unusable hash is a known shape of this
            # backend rather than evidence of a problem. Size matched.
            c.notes.append(
                "no comparable content hash on this backend — verified on "
                "size alone"
            )

    # Nothing may still point at the legacy URL, and something must
    # point at the canonical one. The second half matters as much as
    # the first: zero references to either would mean the migration
    # repointed that row somewhere else entirely.
    c.legacy_references, c.columns_scanned = find_references(db, c.source_url)
    c.canonical_references, _ = find_references(db, c.dest_url)

    if c.legacy_references:
        c.blockers.append(
            f"{len(c.legacy_references)} database reference(s) still point at "
            f"the legacy URL: {', '.join(c.legacy_references[:5])}"
        )
    if not c.canonical_references:
        c.blockers.append(
            f"no database reference points at the canonical URL {c.dest_url} "
            f"— the migration has not happened, or it moved the reference "
            f"somewhere else"
        )

    _check_canonical_authorisation(db, c)
    return c


def _check_canonical_authorisation(db: Session, c: OrphanCheck) -> None:
    """Prove the canonical key is readable by a member and nobody else.

    Deleting the legacy object is only safe if the replacement actually
    serves. A canonical object that exists but 403s for its own
    Collective's members would leave a broken image and no way back.
    """
    from fastapi import HTTPException

    from app.models.user import User
    from app.uploads.authorization import authorize_upload

    slug = c.dest_key.split("/")[1] if c.dest_key.count("/") >= 2 else None
    if not slug:
        c.blockers.append(f"cannot read a Collective slug from {c.dest_key}")
        return

    space = db.execute(text(
        "SELECT id FROM spaces WHERE slug = :s"
    ), {"s": slug}).first()
    if space is None:
        c.blockers.append(f"no Collective with slug '{slug}'")
        return
    space_id = space[0]

    member = db.execute(text(
        "SELECT u.id FROM space_memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.space_id = :s AND m.status = 'active' "
        "  AND coalesce(u.role, '') <> 'admin' LIMIT 1"
    ), {"s": space_id}).first()
    outsider = db.execute(text(
        "SELECT u.id FROM users u WHERE coalesce(u.role, '') <> 'admin' "
        "  AND u.id NOT IN ("
        "    SELECT user_id FROM space_memberships WHERE space_id = :s"
        "  ) "
        "  AND u.id NOT IN ("
        "    SELECT creator_id FROM spaces WHERE id = :s "
        "      AND creator_id IS NOT NULL"
        "  ) LIMIT 1"
    ), {"s": space_id}).first()

    if member is None:
        c.blockers.append(
            f"no active non-admin member of '{slug}' to verify authorisation "
            f"with — cannot prove the canonical image actually serves"
        )
        return

    try:
        authorize_upload(c.dest_key, db.get(User, member[0]), db)
        c.member_allowed = "allowed"
    except Exception as exc:
        c.member_allowed = f"DENIED ({exc})"
        c.blockers.append(
            f"a member of '{slug}' cannot read the canonical object — "
            f"deleting the legacy one would leave a broken image"
        )

    if outsider is None:
        c.notes.append("no non-member account available to verify the deny side")
        return
    try:
        authorize_upload(c.dest_key, db.get(User, outsider[0]), db)
    except HTTPException as exc:
        # Only a real authorisation refusal counts. Catching anything
        # at all here would let a crash in the authoriser read as a
        # correct denial, which is the one failure this check exists to
        # notice.
        if exc.status_code in (403, 404):
            c.non_member_denied = "denied"
        else:
            c.non_member_denied = f"unexpected status {exc.status_code}"
            c.blockers.append(
                f"the deny side returned {exc.status_code} rather than a "
                f"refusal — authorisation is not behaving as expected"
            )
    except Exception as exc:
        c.non_member_denied = f"errored ({exc})"
        c.blockers.append(
            f"could not verify that a non-member is refused {c.dest_key}: "
            f"{exc}"
        )
    else:
        c.non_member_denied = "ALLOWED — expected a denial"
        c.blockers.append(
            f"a non-member can read {c.dest_key} — the canonical path is not "
            f"enforcing membership"
        )


def delete_orphan(check: OrphanCheck) -> bool:
    """Delete the legacy object, and only it. True if it was removed.

    Verifies afterwards rather than trusting the call: ``delete_file``
    swallows backend errors by design, so a silent failure would
    otherwise be reported as a success.
    """
    if not check.safe:
        raise RuntimeError("refusing to delete: the audit found blockers")
    if check.already_deleted:
        return False

    storage.delete_file(check.source_key)

    if storage.object_head(check.source_key) is not None:
        raise RuntimeError(
            f"delete reported no error but {check.source_key} is still there"
        )
    if storage.object_head(check.dest_key) is None:
        raise RuntimeError(
            f"the canonical object {check.dest_key} is gone after deleting the "
            f"legacy one — this should be impossible; restore from backup"
        )
    return True
