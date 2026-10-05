"""Deleting abandoned uploads, and — mostly — not deleting anything else.

The job removes storage objects that nothing references. The failure
that matters is not "an orphan survived" — that costs a few cents a
year — it is "a member's image was deleted", which cannot be undone. So
almost every test here is about something being *kept*, and the ones
about deletion are narrow.

Storage is exercised for real in filesystem mode, with ``os.utime`` to
age objects, because age comes from the object's own timestamp and a
mocked backend would assert nothing about that.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_orphaned_media_cleanup.py
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import app.models.community_care  # noqa: F401
from app.core import storage
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    PostComment,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import orphaned_media as om

BYTES = b"\xff\xd8\xff\xe0" + b"jpeg" * 60

#: What the uploader actually names things: 32 hex from uuid4, then the
#: sanitised stem. Tests use this shape because the job refuses keys
#: that do not have it.
def _written_name(stem: str = "ocean", ext: str = ".jpeg") -> str:
    return f"{uuid.uuid4().hex}{'_'}{stem}{ext}"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def upload_dir(monkeypatch):
    d = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(storage, "UPLOAD_DIR", d)
    return d


@pytest.fixture
def put(upload_dir):
    """Write an object and give it an age in hours."""
    def _put(key: str, *, age_hours: float = 0.0, data: bytes = BYTES) -> str:
        path = upload_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        when = (
            datetime.now(timezone.utc) - timedelta(hours=age_hours)
        ).timestamp()
        os.utime(path, (when, when))
        return key
    return _put


@pytest.fixture
def collective(db, make_user, make_space):
    """A Collective with a channel, a post and a comment to hang
    references off."""
    def _make():
        creator = make_user(role="creator")
        space = make_space(creator=creator, name="EMBODY")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=creator.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        channel = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Common Room",
            slug="common-room",
        )
        db.add(channel)
        db.flush()
        post = CommunityPost(
            id=_uid("cp"), space_id=space.id, author_id=creator.id,
            channel_id=channel.id, body="A post",
        )
        db.add(post)
        db.flush()
        comment = PostComment(
            id=_uid("pc"), post_id=post.id, author_id=creator.id, body="Hi",
        )
        db.add(comment)
        db.flush()
        return creator, space, post, comment
    return _make


def conversation_key(slug: str, name: str | None = None) -> str:
    return f"media/{slug}/community/{name or _written_name()}"


# ---------------------------------------------------------------------------
# Namespace classification
# ---------------------------------------------------------------------------


class TestNamespaceClassification:
    def test_only_the_conversation_namespace_is_eligible(self):
        """The scope of the whole job, asserted in one place.

        Widening this is a product decision with a blast radius, not a
        refactor, so it should take a deliberate test change.
        """
        eligible = {n for n, ns in om.NAMESPACES.items() if ns.eligible}
        assert eligible == {"conversation-image"}

    @pytest.mark.parametrize("key,expected", [
        ("media/embody/community/abc_x.jpeg", "conversation-image"),
        ("media/embody/abc_x.jpeg", "media-library"),
        ("media/world-guide/abc_x.png", "world-guide-image"),
        ("media/embody_community/abc_x.jpeg", "legacy-flattened"),
        ("avatars/abc_x.jpg", "avatar"),
        ("covers/abc_x.jpg", "space-cover"),
        ("logos/embody/abc_x.png", "space-logo"),
        ("pathway-covers/abc_x.jpg", "pathway-cover"),
        ("event-thumbnails/abc_x.jpg", "event-thumbnail"),
        ("steps/step-1/abc_x.pdf", "step-resource"),
        ("platform-artwork/brand/logo/abc_x.png", "platform-artwork"),
        ("platform-artwork/place-artwork/kew/abc_x.jpg", "platform-artwork"),
        ("island-artwork/embody/abc_x.png", "island-artwork"),
        ("something-new/abc_x.jpg", "unclassified"),
        ("media/", "unclassified"),
        ("", "unclassified"),
    ])
    def test_classification(self, key, expected):
        assert om.classify(key) == expected

    def test_every_classification_has_a_namespace_entry(self):
        """A missing entry would be a ``KeyError`` mid-sweep, in
        production, on a key shape nobody anticipated — which is exactly
        when this code needs to keep working."""
        samples = [
            "media/x/community/f.jpg", "media/x/f.jpg",
            "media/world-guide/f.png", "media/x_community/f.jpg",
            "avatars/f.jpg", "covers/f.jpg", "logos/x/f.png",
            "pathway-covers/f.jpg", "event-thumbnails/f.jpg",
            "steps/s/f.pdf", "platform-artwork/a/b.png",
            "island-artwork/x/f.png", "nonsense", "",
        ]
        for key in samples:
            assert om.classify(key) in om.NAMESPACES, key

    def test_the_legacy_flattened_shape_is_not_read_as_a_library_key(self):
        """It has the same segment count as a Media Library key and
        would otherwise be classified as one belonging to a Collective
        that does not exist."""
        assert om.classify("media/embody_community/a_b.jpeg") != "media-library"


# ---------------------------------------------------------------------------
# What is kept
# ---------------------------------------------------------------------------


class TestObjectsThatMustBeKept:
    def test_a_referenced_old_object_is_kept(self, db, collective, put):
        creator, space, post, comment = collective()
        key = conversation_key(space.slug)
        put(key, age_hours=1000)
        comment.image_url = f"/api/uploads/{key}"
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        kept = [c for c in report.referenced if c.key == key]
        assert kept and comment.id in kept[0].references[0]

    def test_an_unreferenced_object_inside_the_grace_period_is_kept(
        self, db, collective, put,
    ):
        """The window the whole design exists to protect: uploaded, not
        yet posted, member still typing."""
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=71)

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert [c.key for c in report.too_young] == [key]
        assert "grace period" in report.too_young[0].exclusions[0]

    def test_an_unreferenced_object_past_the_grace_period_is_a_candidate(
        self, db, collective, put,
    ):
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=73)

        report = om.audit(db)
        assert [c.key for c in report.orphans] == [key]
        assert report.orphans[0].space_slug == space.slug
        assert report.orphans[0].orphan

    def test_platform_artwork_is_excluded(self, db, collective, put):
        collective()
        key = put(
            f"platform-artwork/brand/logo/{_written_name('logo', '.png')}",
            age_hours=5000,
        )
        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert report.by_namespace["platform-artwork"] == 1
        assert key not in [c.key for c in report.unclassified]

    def test_a_media_library_asset_with_an_owning_row_is_excluded(
        self, db, collective, put,
    ):
        """Unreferenced by any post, by design, from the moment it is
        uploaded. Its row owns it."""
        creator, space, post, comment = collective()
        name = _written_name("asset", ".jpeg")
        key = put(f"media/{space.slug}/{name}", age_hours=5000)

        db.execute(text(
            "INSERT INTO creator_media_assets "
            "(id, space_id, uploaded_by_user_id, title, original_filename, "
            " stored_filename, storage_path, file_url, mime_type, media_type, "
            " file_size_bytes, extension, status) "
            "VALUES (:i, :s, :u, 'Asset', 'asset.jpeg', :n, :p, :url, "
            "        'image/jpeg', 'image', 100, '.jpeg', 'active')"
        ), {
            "i": _uid("ma"), "s": space.id, "u": creator.id, "n": name,
            "p": key, "url": f"/api/uploads/{key}",
        })
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert report.by_namespace["media-library"] == 1

    def test_an_archived_media_asset_still_owns_its_object(
        self, db, collective, put,
    ):
        """Deleting a Media Library asset archives the row rather than
        removing it, and keeps the object on purpose. ``status`` must not
        change the answer."""
        creator, space, post, comment = collective()
        name = _written_name("asset", ".jpeg")
        key = f"media/{space.slug}/community/{name}"
        put(key, age_hours=5000)
        db.execute(text(
            "INSERT INTO creator_media_assets "
            "(id, space_id, uploaded_by_user_id, title, original_filename, "
            " stored_filename, storage_path, file_url, mime_type, media_type, "
            " file_size_bytes, extension, status) "
            "VALUES (:i, :s, :u, 'Asset', 'asset.jpeg', :n, :p, :url, "
            "        'image/jpeg', 'image', 100, '.jpeg', 'archived')"
        ), {
            "i": _uid("ma"), "s": space.id, "u": creator.id, "n": name,
            "p": key, "url": f"/api/uploads/{key}",
        })
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        owned = [c for c in report.owned if c.key == key]
        assert owned and "archived" in owned[0].owning_asset

    def test_an_unknown_namespace_is_excluded(self, db, collective, put):
        collective()
        put(f"brand-new-feature/{_written_name()}", age_hours=9000)
        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert report.by_namespace["unclassified"] == 1

    def test_a_key_whose_collective_does_not_exist_is_kept(
        self, db, collective, put,
    ):
        """Right shape, no owner. Nothing can be established about it,
        so it is not a candidate."""
        collective()
        key = put(conversation_key("no-such-collective"), age_hours=9000)
        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert key in [c.key for c in report.unclassified]

    def test_a_filename_the_uploader_would_not_produce_is_kept(
        self, db, collective, put,
    ):
        """The uuid4 prefix is what makes a filename search a dependable
        reference test. Without it, a filename search could match
        unrelated rows or miss the real one, so the job declines to
        judge."""
        creator, space, post, comment = collective()
        key = put(f"media/{space.slug}/community/holiday.jpg", age_hours=9000)
        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert key in [c.key for c in report.unclassified]

    def test_a_reference_embedded_in_rich_text_is_found(
        self, db, collective, put,
    ):
        """The reason the scan reads every text column rather than a
        list of ``*_url`` ones. A block-editor document mentioning the
        URL is as much a reference as a dedicated column."""
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)
        post.body = (
            '{"type":"doc","content":[{"type":"image","attrs":'
            f'{{"src":"/api/uploads/{key}"}}}}]}}'
        )
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert any("community_posts.body" in r
                   for r in report.referenced[0].references)

    def test_a_bare_key_reference_is_found(self, db, collective, put):
        """``step_resources.url`` stores the bare key, not a URL. A
        URL-only scan would miss it, so both forms are searched — and
        the filename alone catches either."""
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)
        post.title = key  # a bare key, in some other column
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []

    def test_a_percent_encoded_reference_is_found(self, db, collective, put):
        """A sanitised filename has nothing in it that percent-encoding
        would change, so searching the filename covers encoded URLs
        without needing to enumerate encodings."""
        creator, space, post, comment = collective()
        name = _written_name()
        key = put(conversation_key(space.slug, name), age_hours=9000)
        post.body = f"https://example.test/api%2Fuploads%2F{name}"
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []

    def test_underscores_in_the_key_do_not_break_the_scan(
        self, db, collective, put,
    ):
        """``LIKE`` reads ``_`` as a single-character wildcard, and
        these keys are full of underscores. With ``LIKE`` the scan both
        over-matches — finding "references" to objects nobody mentions,
        which is merely useless — and, worse, a search built the other
        way round can match the wrong object entirely.
        """
        creator, space, post, comment = collective()
        a = put(conversation_key(space.slug, _written_name("my_holiday_pic")),
                age_hours=9000)
        b = put(conversation_key(space.slug, _written_name("my_holiday_pic")),
                age_hours=9000)

        # Only A is referenced. B must still be a candidate, and A must
        # not be — the two names differ only in their uuid prefix.
        comment.image_url = f"/api/uploads/{a}"
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == [b]
        assert [c.key for c in report.referenced] == [a]

    def test_one_heavily_referenced_key_cannot_hide_another(
        self, db, collective, put,
    ):
        """A per-column row limit would be a correctness bug here, not a
        performance tweak: the busy key fills the quota and the quiet
        one's single reference never comes back, so a referenced object
        is reported as an orphan."""
        creator, space, post, comment = collective()
        busy = put(conversation_key(space.slug), age_hours=9000)
        quiet = put(conversation_key(space.slug), age_hours=9000)

        channel = db.execute(text(
            "SELECT id FROM conversation_channels WHERE space_id = :s LIMIT 1"
        ), {"s": space.id}).scalar()
        for _ in range(60):
            db.add(CommunityPost(
                id=_uid("cp"), space_id=space.id, author_id=creator.id,
                channel_id=channel, body="x",
                image_url=f"/api/uploads/{busy}",
            ))
        db.add(CommunityPost(
            id=_uid("cp"), space_id=space.id, author_id=creator.id,
            channel_id=channel, body="x",
            image_url=f"/api/uploads/{quiet}",
        ))
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert {c.key for c in report.referenced} == {busy, quiet}


# ---------------------------------------------------------------------------
# Audit writes nothing
# ---------------------------------------------------------------------------


class TestTheAuditIsReadOnly:
    def test_the_audit_deletes_nothing_and_writes_nothing(
        self, db, collective, put, upload_dir,
    ):
        creator, space, post, comment = collective()
        keys = [
            put(conversation_key(space.slug), age_hours=9000),
            put(conversation_key(space.slug), age_hours=1),
            put(f"avatars/{_written_name('face', '.jpg')}", age_hours=9000),
        ]
        before = {p: p.read_bytes() for p in upload_dir.rglob("*") if p.is_file()}
        rows_before = db.execute(
            text("SELECT count(*) FROM community_posts")
        ).scalar()

        report = om.audit(db)
        assert len(report.orphans) == 1

        after = {p: p.read_bytes() for p in upload_dir.rglob("*") if p.is_file()}
        assert after == before
        assert db.execute(
            text("SELECT count(*) FROM community_posts")
        ).scalar() == rows_before
        assert all((upload_dir / k).is_file() for k in keys)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


class TestApply:
    def test_it_deletes_the_candidate_and_nothing_else(
        self, db, collective, put, upload_dir,
    ):
        creator, space, post, comment = collective()
        orphan = put(conversation_key(space.slug), age_hours=9000)
        young = put(conversation_key(space.slug), age_hours=2)
        referenced = put(conversation_key(space.slug), age_hours=9000)
        comment.image_url = f"/api/uploads/{referenced}"
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == [orphan]

        outcome = om.delete_orphans(db, report.orphans)
        assert [c.key for c in outcome.deleted] == [orphan]
        assert outcome.skipped == []
        assert outcome.freed_bytes == len(BYTES)

        assert not (upload_dir / orphan).exists()
        assert (upload_dir / young).is_file()
        assert (upload_dir / referenced).is_file()

    def test_an_object_that_gains_a_reference_between_scan_and_delete_is_kept(
        self, db, collective, put, upload_dir,
    ):
        """The race the grace period narrows but cannot close: an audit
        can be hours old by the time somebody types --apply, and a
        member can publish in that window."""
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)

        report = om.audit(db)
        assert [c.key for c in report.orphans] == [key]

        # Meanwhile, the member finally posts.
        comment.image_url = f"/api/uploads/{key}"
        db.flush()

        outcome = om.delete_orphans(db, report.orphans)
        assert outcome.deleted == []
        assert len(outcome.skipped) == 1
        assert "a reference appeared since the audit" in outcome.skipped[0][1]
        assert (upload_dir / key).is_file()

    def test_an_object_that_gains_an_owning_asset_row_is_kept(
        self, db, collective, put, upload_dir,
    ):
        creator, space, post, comment = collective()
        name = _written_name()
        key = put(conversation_key(space.slug, name), age_hours=9000)
        report = om.audit(db)
        assert [c.key for c in report.orphans] == [key]

        db.execute(text(
            "INSERT INTO creator_media_assets "
            "(id, space_id, uploaded_by_user_id, title, original_filename, "
            " stored_filename, storage_path, file_url, mime_type, media_type, "
            " file_size_bytes, extension, status) "
            "VALUES (:i, :s, :u, 'A', 'a.jpeg', :n, :p, :url, 'image/jpeg', "
            "        'image', 100, '.jpeg', 'active')"
        ), {
            "i": _uid("ma"), "s": space.id, "u": creator.id, "n": name,
            "p": key, "url": f"/api/uploads/{key}",
        })
        db.flush()

        outcome = om.delete_orphans(db, report.orphans)
        assert outcome.deleted == []
        assert "now owned by" in outcome.skipped[0][1]
        assert (upload_dir / key).is_file()

    def test_an_object_re_uploaded_under_the_same_key_is_kept(
        self, db, collective, put, upload_dir,
    ):
        """Age is re-read from storage immediately before the delete, so
        a key that is old in the audit and fresh at apply time is
        skipped."""
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)
        report = om.audit(db)
        assert [c.key for c in report.orphans] == [key]

        put(key, age_hours=0)  # same key, new bytes, new mtime

        outcome = om.delete_orphans(db, report.orphans)
        assert outcome.deleted == []
        assert "grace period" in outcome.skipped[0][1]
        assert (upload_dir / key).is_file()

    def test_one_skip_does_not_stop_the_others(
        self, db, collective, put, upload_dir,
    ):
        creator, space, post, comment = collective()
        keep = put(conversation_key(space.slug), age_hours=9000)
        go_a = put(conversation_key(space.slug), age_hours=9000)
        go_b = put(conversation_key(space.slug), age_hours=9000)

        report = om.audit(db)
        assert len(report.orphans) == 3

        comment.image_url = f"/api/uploads/{keep}"
        db.flush()

        outcome = om.delete_orphans(db, report.orphans)
        assert {c.key for c in outcome.deleted} == {go_a, go_b}
        assert [k for k, _ in outcome.skipped] == [keep]
        assert (upload_dir / keep).is_file()

    def test_a_second_run_does_nothing(self, db, collective, put, upload_dir):
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)

        first = om.audit(db)
        om.delete_orphans(db, first.orphans)

        second = om.audit(db)
        assert second.orphans == []
        outcome = om.delete_orphans(db, second.orphans)
        assert outcome.deleted == []
        assert outcome.skipped == []

    def test_re_applying_a_stale_candidate_list_is_safe(
        self, db, collective, put,
    ):
        """Idempotence against the list, not just against the audit: the
        same candidates handed to a second apply must not error."""
        creator, space, post, comment = collective()
        put(conversation_key(space.slug), age_hours=9000)
        report = om.audit(db)
        om.delete_orphans(db, report.orphans)

        again = om.delete_orphans(db, report.orphans)
        assert again.deleted == []
        assert again.skipped[0][1] == "already gone from storage"

    def test_a_silently_failed_delete_is_not_reported_as_success(
        self, db, collective, put, monkeypatch, upload_dir,
    ):
        """``storage.delete_file`` swallows backend errors by design, so
        the outcome is verified rather than trusted."""
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)
        report = om.audit(db)
        monkeypatch.setattr(storage, "delete_file", lambda k: None)

        with pytest.raises(RuntimeError, match="still there"):
            om.delete_orphans(db, report.orphans)
        assert (upload_dir / key).is_file()

    def test_a_failed_listing_aborts_instead_of_finding_nothing(
        self, db, collective, put, monkeypatch,
    ):
        """"I found nothing" and "I could not look" must never be the
        same answer. An empty listing from a broken backend would make
        every object look unreferenced — and, worse, make the sweep
        report a clean bucket."""
        collective()

        def explode(prefix):
            raise RuntimeError("R2 unavailable")

        monkeypatch.setattr(storage, "list_objects", explode)
        with pytest.raises(RuntimeError, match="R2 unavailable"):
            om.audit(db)

    def test_the_job_never_writes_to_the_database(
        self, db, collective, put,
    ):
        """It removes objects that are *already* unreferenced. Making
        something orphaned by clearing its row first would be the one
        unforgivable version of this job."""
        creator, space, post, comment = collective()
        put(conversation_key(space.slug), age_hours=9000)
        comment.image_url = "/api/uploads/media/other/community/x_y.jpg"
        db.flush()

        counts_before = {
            t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: S608
            for t in ("community_posts", "post_comments", "creator_media_assets")
        }
        urls_before = db.execute(text(
            "SELECT id, image_url FROM post_comments ORDER BY id"
        )).all()

        report = om.audit(db)
        om.delete_orphans(db, report.orphans)

        assert {
            t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: S608
            for t in counts_before
        } == counts_before
        assert db.execute(text(
            "SELECT id, image_url FROM post_comments ORDER BY id"
        )).all() == urls_before


# ---------------------------------------------------------------------------
# Grace period
# ---------------------------------------------------------------------------


class TestGracePeriod:
    def test_the_default_is_seventy_two_hours(self):
        assert om.DEFAULT_GRACE_HOURS == 72

    def test_the_minimum_is_a_day(self):
        assert om.MINIMUM_GRACE_HOURS == 24
        assert om.MINIMUM_GRACE_HOURS <= om.DEFAULT_GRACE_HOURS

    def test_the_boundary_decides_on_the_grace_period(
        self, db, collective, put,
    ):
        """Either side of 72h, with a margin.

        Asserting on the exact boundary would be testing the clock: the
        object's mtime is stamped microseconds before the audit reads
        ``now``, so a key written "72h ago" lands a hair outside a 72h
        window. The behaviour that matters is which side of the period
        an object falls on, not how a tie breaks.
        """
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=71.5)
        assert [c.key for c in om.audit(db, grace_hours=72).orphans] == []
        assert [c.key for c in om.audit(db, grace_hours=71).orphans] == [key]

    def test_age_comes_from_storage_not_from_a_database_column(
        self, db, collective, put,
    ):
        """An orphan has no row, so there is no created_at to read. The
        object's own timestamp is the only age available — and the only
        one that stays correct when a row never existed."""
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)
        report = om.audit(db)
        assert report.orphans[0].age_hours > 8000

        put(key, age_hours=3)
        report = om.audit(db)
        assert [c.key for c in report.orphans] == []

    def test_the_script_refuses_a_grace_period_below_the_minimum(self):
        """Run as a subprocess, not imported: operational scripts set
        ``FC_SERVICE_ROLE`` at import time and that leaks into every
        later test in the process."""
        script = (
            pathlib.Path(__file__).resolve().parent.parent
            / "scripts/cleanup_orphaned_uploaded_media.py"
        )
        result = subprocess.run(
            [sys.executable, str(script), "--apply", "--older-than-hours", "1"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "Refusing a 1h grace period" in result.stdout + result.stderr
        assert om.UNSAFE_OVERRIDE_FLAG in result.stdout + result.stderr

    def test_the_unsafe_override_has_to_be_spelled_out(self):
        """Not ``-f``, not ``--force``. Something nobody types by
        accident or copies out of a runbook without reading."""
        assert om.UNSAFE_OVERRIDE_FLAG.startswith("--")
        assert len(om.UNSAFE_OVERRIDE_FLAG) > 20
        assert "accept" in om.UNSAFE_OVERRIDE_FLAG


# ---------------------------------------------------------------------------
# Operational shape
# ---------------------------------------------------------------------------


class TestOperationalShape:
    def test_it_is_not_scheduled(self):
        """A sweep that deletes storage objects should not be wired into
        the blueprint on the pass that introduces it. A ``value:`` entry
        there is reasserted on every sync, so a scheduled delete comes
        back after being removed."""
        blueprint = (
            pathlib.Path(__file__).resolve().parent.parent.parent / "render.yaml"
        )
        assert blueprint.exists()
        assert "cleanup_orphaned_uploaded_media" not in blueprint.read_text()

    def test_both_buckets_are_listed(self):
        """The bucket is chosen by key prefix, so a single root listing
        would silently cover only the private one — and every public
        artwork object would come back as "not found in storage"."""
        assert "" in om.LISTING_PREFIXES
        assert any(p.startswith("platform-artwork") for p in om.LISTING_PREFIXES)

    def test_the_reference_scan_covers_json_columns(self, db):
        """Block-editor content and serialised payloads live in
        json/jsonb, and a text-only catalogue query would skip them."""
        columns = om.searchable_columns(db)
        assert columns
        assert any(needs_cast for _t, _c, needs_cast in columns), (
            "no json/jsonb column found — the catalogue query has stopped "
            "including them"
        )

    def test_the_scan_is_not_limited_to_url_shaped_column_names(self, db):
        """The point of the broad scan: a reference can be anywhere, so
        the catalogue query must not filter by column name."""
        columns = om.searchable_columns(db)
        names = {c for _t, c, _j in columns}
        assert any("url" not in n and "image" not in n for n in names)
        assert len(columns) > 100, len(columns)

    def test_needles_cover_every_representation(self):
        key = "media/embody/community/" + "a" * 32 + "_ocean.jpeg"
        needles = om.needles_for(key)
        filename = key.rsplit("/", 1)[-1]
        assert filename in needles
        assert key in needles
        assert "/api/uploads/" + key in needles
        # The filename is a substring of both other forms, which is why
        # it alone catches encoded and embedded references.
        assert all(filename in n for n in needles)


# ---------------------------------------------------------------------------
# The predicates that mutation testing found untested
# ---------------------------------------------------------------------------


class TestSafetyPredicatesInDetail:
    """Each of these exists because a mutation to the predicate it
    covers survived the first round. They are the checks that are
    reachable but that nothing was exercising."""

    def test_an_object_with_no_modification_time_is_kept(
        self, db, collective, put, monkeypatch, upload_dir,
    ):
        """Age is the predicate protecting an in-flight upload, so no
        timestamp means no delete.

        The filesystem backend always has an mtime; an S3-compatible
        HEAD that omits ``LastModified`` would not, and this is the
        branch that decides what happens then.
        """
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)
        report = om.audit(db)
        assert [c.key for c in report.orphans] == [key]

        real_head = storage.object_head

        def head_without_time(rel_path):
            info = real_head(rel_path)
            if info is None:
                return None
            return storage.ObjectInfo(
                size=info.size, content_type=info.content_type,
                etag=info.etag, last_modified=None,
            )

        monkeypatch.setattr(storage, "object_head", head_without_time)
        outcome = om.delete_orphans(db, report.orphans)
        assert outcome.deleted == []
        assert "no modification time" in outcome.skipped[0][1]
        assert (upload_dir / key).is_file()

    def test_the_reference_scan_is_exact_substring_not_a_pattern(
        self, db, collective, put,
    ):
        """``strpos``, not ``LIKE``.

        Under ``LIKE`` the needle's underscores are single-character
        wildcards, so a stored string that differs from the real
        filename at exactly those positions matches. Here that would
        make an abandoned object look referenced — the harmless
        direction, but it also means the scan is not answering the
        question it claims to.
        """
        creator, space, post, comment = collective()
        name = _written_name("ocean")
        key = put(conversation_key(space.slug, name), age_hours=9000)

        # Same string, with every underscore replaced. A literal
        # substring search finds nothing; a LIKE pattern matches.
        near_miss = name.replace("_", "X")
        post.body = f"see /api/uploads/media/{space.slug}/community/{near_miss}"
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == [key]
        assert report.referenced == []

    def test_many_candidates_referenced_in_one_column_are_all_found(
        self, db, collective, put,
    ):
        """No row limit on the per-column query.

        A limit would be a correctness bug rather than a tuning choice:
        a production sweep can have dozens of candidates, and once their
        needles outnumber the limit, some keys' references stop coming
        back and referenced objects are reported as orphans.

        Forty keys, three needles each: a hundred and twenty grouped
        rows, comfortably past any plausible cap, and far enough past it
        that a key cannot keep one of its needles by luck.
        """
        creator, space, post, comment = collective()
        channel = db.execute(text(
            "SELECT id FROM conversation_channels WHERE space_id = :s LIMIT 1"
        ), {"s": space.id}).scalar()

        keys = [
            put(conversation_key(space.slug), age_hours=9000) for _ in range(40)
        ]
        for key in keys:
            db.add(CommunityPost(
                id=_uid("cp"), space_id=space.id, author_id=creator.id,
                channel_id=channel, body="x",
                image_url=f"/api/uploads/{key}",
            ))
        db.flush()

        report = om.audit(db)
        assert report.orphans == [], [c.key for c in report.orphans]
        assert {c.key for c in report.referenced} == set(keys)

    def test_a_reference_inside_a_jsonb_column_is_found(
        self, db, collective, put,
    ):
        """json/jsonb columns are cast and searched, not skipped.

        Block-editor documents and serialised payloads live in them, and
        a text-only catalogue query would walk straight past a real
        reference.
        """
        creator, space, post, comment = collective()
        key = put(conversation_key(space.slug), age_hours=9000)

        db.execute(text(
            "UPDATE spaces SET home_config = CAST(:cfg AS jsonb) WHERE id = :i"
        ), {
            "cfg": '{"hero": {"image": "/api/uploads/' + key + '"}}',
            "i": space.id,
        })
        db.flush()

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert any("spaces.home_config" in r
                   for r in report.referenced[0].references)

    def test_apply_does_not_trust_the_candidate_list_it_is_handed(
        self, db, collective, put, upload_dir,
    ):
        """``delete_orphans`` re-classifies every key itself.

        The candidate list is an argument, which means it can come from
        a stale audit, a hand-edited run, or a future caller that built
        it some other way. Namespace eligibility is cheap to re-derive
        from the key, so it is re-derived rather than believed.
        """
        creator, space, post, comment = collective()
        artwork = put(
            f"platform-artwork/brand/logo/{_written_name('logo', '.png')}",
            age_hours=9000,
        )
        library = put(
            f"media/{space.slug}/{_written_name('asset')}", age_hours=9000,
        )

        handed_over = [
            om.Candidate(
                key=k, size=len(BYTES),
                last_modified=datetime.now(timezone.utc) - timedelta(days=90),
                namespace=om.classify(k), age_hours=9000,
            )
            for k in (artwork, library)
        ]
        outcome = om.delete_orphans(db, handed_over)

        assert outcome.deleted == []
        assert len(outcome.skipped) == 2
        assert all("no longer eligible" in reason for _k, reason in outcome.skipped)
        assert (upload_dir / artwork).is_file()
        assert (upload_dir / library).is_file()

    def test_a_naive_timestamp_is_read_as_utc_not_as_local_time(self):
        """Storage timestamps are UTC. Converting a naive one *from*
        local time would shift it by the host's offset — eleven hours
        here — which on the wrong side of the grace period means
        deleting an upload that is still in flight.
        """
        import time as _time

        naive = datetime(2026, 1, 2, 3, 4, 5)
        previous = os.environ.get("TZ")
        os.environ["TZ"] = "Australia/Melbourne"
        _time.tzset()
        try:
            result = om._aware(naive)
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            _time.tzset()

        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)
        # The wall clock is unchanged: it was already UTC, just unlabelled.
        assert result.replace(tzinfo=None) == naive

    def test_an_aware_timestamp_is_left_alone(self):
        aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        assert om._aware(aware) is aware


# ---------------------------------------------------------------------------
# Age must not hide reference status
# ---------------------------------------------------------------------------


class TestAReferencedObjectIsAlwaysReportedAsReferenced:
    """From a production audit that read as though a live image were
    unreferenced.

    The object was the canonical copy the legacy-media migration had
    just created, so its ``LastModified`` was hours old. The audit
    short-circuited on age before the reference scan ran, and printed::

        conversation-image  3 ELIGIBLE
        has a live reference  0

    Nothing was ever at risk — a young object is not a candidate — but
    the two facts an operator needs separated before pressing --apply
    had been merged into one. "Kept because something points at it" and
    "kept because it is recent" are different assurances, and only the
    first survives the grace period being lowered, a clock skewing, or
    an object being re-copied.

    So the reference scan now runs for every in-namespace object and age
    is applied after it.
    """

    #: The exact shape from the production report.
    CANONICAL = "media/embody/community/{uuid}_IMG_3359.jpeg"

    def _embody(self, db, collective, put, *, age_hours: float):
        creator, space, post, comment = collective()
        key = self.CANONICAL.format(uuid=uuid.uuid4().hex)
        # The slug has to be the one in the key.
        db.execute(text("UPDATE spaces SET slug = :s WHERE id = :i"),
                   {"s": "embody", "i": space.id})
        db.flush()
        put(key, age_hours=age_hours)
        comment.image_url = f"/api/uploads/{key}"
        db.flush()
        return space, comment, key

    def test_a_freshly_copied_referenced_object_reports_as_referenced(
        self, db, collective, put,
    ):
        """The production case, as a test: 20h old and referenced."""
        space, comment, key = self._embody(db, collective, put, age_hours=20)

        report = om.audit(db)
        assert [c.key for c in report.orphans] == []
        assert [c.key for c in report.referenced] == [key]
        # And explicitly NOT filed under age, which is what made the
        # report misleading.
        assert key not in [c.key for c in report.too_young]
        assert any(comment.id in r for r in report.referenced[0].references)

    def test_the_canonical_url_shape_is_matched(self, db, collective, put):
        """``/api/uploads/media/embody/community/<uuid>_IMG_3359.jpeg``
        — searched for by filename, bare key and full URL."""
        space, comment, key = self._embody(db, collective, put, age_hours=20)
        url = f"/api/uploads/{key}"

        assert comment.image_url == url
        hits = om.find_references(db, [key])
        assert hits[key], hits
        assert any("post_comments.image_url" in h for h in hits[key])

        for needle in om.needles_for(key):
            assert needle in url or url.endswith(needle) or needle in key, needle

    def test_every_in_namespace_object_is_reference_searched(
        self, db, collective, put,
    ):
        """The count that makes the report readable.

        Without it, "has a live reference 0" cannot be distinguished
        from "nothing was checked".
        """
        creator, space, post, comment = collective()
        young = put(conversation_key(space.slug), age_hours=1)
        old = put(conversation_key(space.slug), age_hours=9000)

        report = om.audit(db)
        assert report.reference_checked == 2, report.reference_checked
        assert {young, old} == {
            c.key for c in report.referenced + report.owned
            + report.too_young + report.orphans
        }

    def test_no_referenced_object_is_ever_filed_anywhere_else(
        self, db, collective, put,
    ):
        """The invariant, over a mixed set. If a reference exists, the
        object appears in exactly one group: referenced."""
        creator, space, post, comment = collective()
        channel = db.execute(text(
            "SELECT id FROM conversation_channels WHERE space_id = :s LIMIT 1"
        ), {"s": space.id}).scalar()

        referenced_keys = []
        for age in (0.5, 20, 100, 9000):
            key = put(conversation_key(space.slug), age_hours=age)
            db.add(CommunityPost(
                id=_uid("cp"), space_id=space.id, author_id=creator.id,
                channel_id=channel, body="x",
                image_url=f"/api/uploads/{key}",
            ))
            referenced_keys.append(key)
        unreferenced_old = put(conversation_key(space.slug), age_hours=9000)
        unreferenced_young = put(conversation_key(space.slug), age_hours=2)
        db.flush()

        report = om.audit(db)
        assert sorted(c.key for c in report.referenced) == sorted(referenced_keys)
        assert [c.key for c in report.orphans] == [unreferenced_old]
        assert [c.key for c in report.too_young] == [unreferenced_young]
        for group in (report.orphans, report.too_young, report.owned):
            for candidate in group:
                assert candidate.references == [], candidate.key

    def test_a_referenced_object_is_never_a_candidate_at_any_age(
        self, db, collective, put,
    ):
        """Even with the grace period at its minimum, a referenced
        object stays out of the candidate list."""
        space, comment, key = self._embody(db, collective, put, age_hours=9000)
        for grace in (24, 72, 168):
            report = om.audit(db, grace_hours=grace)
            assert [c.key for c in report.orphans] == [], grace
            assert [c.key for c in report.referenced] == [key], grace


# ---------------------------------------------------------------------------
# Excluded namespaces are listable
# ---------------------------------------------------------------------------


class TestExcludedObjectsCanBeListed:
    """A count cannot answer "which two objects are those?".

    The production audit reported ``legacy-flattened 2 excluded`` and
    then had nothing to print, because excluded candidates were counted
    and discarded. They are retained now.
    """

    def test_excluded_candidates_are_retained_not_just_counted(
        self, db, collective, put,
    ):
        creator, space, post, comment = collective()
        legacy_a = put(
            f"media/{space.slug}_community/{_written_name('ocean')}",
            age_hours=9000,
        )
        legacy_b = put(
            f"media/{space.slug}_community/{_written_name('IMG_3359')}",
            age_hours=9000,
        )
        library = put(f"media/{space.slug}/{_written_name('asset')}", age_hours=50)

        report = om.audit(db)
        assert report.excluded_namespace["legacy-flattened"] == 2
        assert sorted(c.key for c in report.in_namespace("legacy-flattened")) == (
            sorted([legacy_a, legacy_b])
        )
        assert [c.key for c in report.in_namespace("media-library")] == [library]
        # Still not candidates.
        assert [c.key for c in report.orphans] == []

    def test_describe_namespace_fills_in_reference_status(
        self, db, collective, put,
    ):
        """An excluded namespace is not reference-scanned by the audit —
        there is no point searching for objects nothing will delete. The
        detail view answers the question on request instead."""
        creator, space, post, comment = collective()
        referenced = put(
            f"media/{space.slug}_community/{_written_name('ocean')}",
            age_hours=9000,
        )
        orphaned = put(
            f"media/{space.slug}_community/{_written_name('other')}",
            age_hours=9000,
        )
        comment.image_url = f"/api/uploads/{referenced}"
        db.flush()

        report = om.audit(db)
        # Not scanned during the audit itself.
        assert all(
            c.references == [] for c in report.in_namespace("legacy-flattened")
        )

        described = om.describe_namespace(db, report, "legacy-flattened")
        by_key = {c.key: c for c in described}
        assert by_key[referenced].references, by_key[referenced]
        assert any(
            comment.id in r for r in by_key[referenced].references
        )
        assert by_key[orphaned].references == []
        # Sizes, ages and content types are available for the report.
        assert by_key[orphaned].size > 0
        assert by_key[orphaned].age_hours > 8000

    def test_describe_namespace_writes_and_deletes_nothing(
        self, db, collective, put, upload_dir,
    ):
        creator, space, post, comment = collective()
        key = put(
            f"media/{space.slug}_community/{_written_name()}", age_hours=9000,
        )
        before = {p: p.read_bytes() for p in upload_dir.rglob("*") if p.is_file()}
        rows = db.execute(text("SELECT count(*) FROM post_comments")).scalar()

        report = om.audit(db)
        om.describe_namespace(db, report, "legacy-flattened")

        assert {p: p.read_bytes() for p in upload_dir.rglob("*")
                if p.is_file()} == before
        assert db.execute(
            text("SELECT count(*) FROM post_comments")).scalar() == rows
        assert (upload_dir / key).is_file()

    def test_an_unknown_namespace_name_is_empty_rather_than_an_error(
        self, db, collective, put,
    ):
        collective()
        report = om.audit(db)
        assert om.describe_namespace(db, report, "no-such-namespace") == []
