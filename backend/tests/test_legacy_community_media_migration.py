"""Moving legacy Conversation images onto their canonical key.

The old writer flattened ``{slug}/community`` into ``{slug}_community``.
These tests are mostly about what the migration refuses to do, because
the dangerous operations are the delete and the reference rewrite, and
the only thing standing between a member's image and oblivion is the
order of operations.

Storage is exercised for real in filesystem mode rather than mocked:
the copy-then-verify-then-delete sequence is the substance, and a
mocked ``copy_object`` would assert nothing about it.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_legacy_community_media_migration.py
"""

from __future__ import annotations

import pathlib
import tempfile
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

import app.models.community_care  # noqa: F401
from app.core import storage
from app.models.platform import (
    CommunityPost,
    PostComment,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.legacy_community_media import (
    URL_PREFIX,
    audit,
    migrate,
    parse_legacy_key,
    remaining_legacy_references,
)

OCEAN = "671a71b7daa944a1a4aa5e761ddcfd3d_ocean.jpeg"
BYTES = b"\xff\xd8\xff\xe0" + b"ocean" * 40


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def upload_dir(monkeypatch):
    """Real filesystem storage, isolated per test."""
    d = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(storage, "UPLOAD_DIR", d)
    return d


def _write(upload_dir: pathlib.Path, key: str, data: bytes = BYTES) -> None:
    p = upload_dir / key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


@pytest.fixture
def mk_channel(db):
    def _make(space):
        cid = _uid("ch")
        db.execute(text(
            "INSERT INTO conversation_channels "
            "(id, space_id, name, slug, channel_type, is_default, "
            " is_archived, show_in_navigation, position, member_posting_allowed) "
            "VALUES (:i, :s, 'Common Room', 'common-room', 'general', "
            "        true, false, true, 0, true)"
        ), {"i": cid, "s": space.id})
        db.flush()
        return cid
    return _make


@pytest.fixture
def conversation(db, make_user, make_space, mk_channel):
    """A Collective with a post and a comment, ready to carry an image."""
    def _make(slug: str = None):
        creator = make_user(role="creator")
        space = make_space(
            creator=creator, slug=slug or f"embody-{uuid.uuid4().hex[:6]}",
            name="EMBODY", status="active",
        )
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=creator.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        channel = mk_channel(space)
        post = CommunityPost(
            id=_uid("cp"), space_id=space.id, author_id=creator.id,
            channel_id=channel, body="A post", is_visible=True,
        )
        db.add(post)
        db.flush()
        comment = PostComment(
            id=_uid("pc"), post_id=post.id, author_id=creator.id,
            body="A comment",
        )
        db.add(comment)
        db.flush()
        return creator, space, post, comment
    return _make


def legacy_url(slug: str, filename: str = OCEAN) -> str:
    return f"{URL_PREFIX}media/{slug}_community/{filename}"


def canonical_url(slug: str, filename: str = OCEAN) -> str:
    return f"{URL_PREFIX}media/{slug}/community/{filename}"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_a_legacy_key_is_recognised_and_its_destination_derived(self):
        parsed = parse_legacy_key(legacy_url("embody"))
        assert parsed == ("embody_community", "embody", OCEAN)

    def test_a_canonical_key_is_not_a_candidate(self):
        assert parse_legacy_key(canonical_url("embody")) is None

    def test_unrelated_media_is_not_a_candidate(self):
        for url in (
            f"{URL_PREFIX}media/embody/asset.png",
            f"{URL_PREFIX}platform-artwork/member_card_a/A.webp",
            f"{URL_PREFIX}avatars/x.png",
            "https://example.com/x.png",
            "", None,
        ):
            assert parse_legacy_key(url) is None, url

    def test_the_audit_finds_a_legacy_comment_image(
        self, db, conversation, upload_dir,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}")

        found = audit(db)
        mine = [c for c in found if c.row_id == comment.id]
        assert len(mine) == 1
        c = mine[0]
        assert c.table == "post_comments"
        assert c.dest_key == f"media/{space.slug}/community/{OCEAN}"
        assert c.space_slug == space.slug
        assert c.safe, c.blockers

    def test_the_audit_finds_a_legacy_post_image(
        self, db, conversation, upload_dir,
    ):
        _c, space, post, _comment = conversation()
        post.image_url = legacy_url(space.slug)
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}")

        mine = [c for c in audit(db) if c.row_id == post.id]
        assert len(mine) == 1
        assert mine[0].table == "community_posts"

    def test_a_canonical_reference_is_left_alone(
        self, db, conversation, upload_dir,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = canonical_url(space.slug)
        db.flush()
        assert [c for c in audit(db) if c.row_id == comment.id] == []

    def test_the_audit_writes_nothing(self, db, conversation, upload_dir):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}")
        before = db.scalar(text(
            "SELECT image_url FROM post_comments WHERE id = :i"
        ), {"i": comment.id})

        audit(db)
        audit(db)

        assert db.scalar(text(
            "SELECT image_url FROM post_comments WHERE id = :i"
        ), {"i": comment.id}) == before
        assert (upload_dir / f"media/{space.slug}_community/{OCEAN}").is_file()
        assert not (upload_dir / f"media/{space.slug}/community/{OCEAN}").exists()


# ---------------------------------------------------------------------------
# The ambiguity the compatibility resolver has to live with
# ---------------------------------------------------------------------------

class TestLegitimateSlugsAreNotMisclassified:
    def test_a_real_collective_named_with_the_suffix_blocks(
        self, db, conversation, upload_dir,
    ):
        """The whole reason this cannot be a blind string rewrite.

        If a Collective's slug genuinely *is* ``x_community``, the key
        is not legacy at all and moving it would relocate that
        Collective's own media.
        """
        _c, space, _post, comment = conversation(slug="wellness_community")
        comment.image_url = legacy_url("wellness")  # -> wellness_community/
        db.flush()
        _write(upload_dir, f"media/wellness_community/{OCEAN}")

        mine = [c for c in audit(db) if c.row_id == comment.id]
        assert len(mine) == 1
        assert not mine[0].safe
        assert any("real Collective slug" in b for b in mine[0].blockers)

    def test_an_unresolvable_owner_blocks(self, db, conversation, upload_dir):
        _c, _space, _post, comment = conversation()
        comment.image_url = legacy_url("no-such-collective")
        db.flush()

        mine = [c for c in audit(db) if c.row_id == comment.id]
        assert not mine[0].safe
        assert any("no Collective with slug" in b for b in mine[0].blockers)

    def test_a_reference_in_the_wrong_collective_blocks(
        self, db, conversation, upload_dir,
    ):
        """The derived destination must match where the row actually
        lives, or an image moves into a Collective it was never in."""
        _c, space_a, _p, _com = conversation(slug="alpha")
        _c2, _space_b, _p2, comment_b = conversation(slug="beta")
        comment_b.image_url = legacy_url("alpha")
        db.flush()
        _write(upload_dir, f"media/alpha_community/{OCEAN}")

        mine = [c for c in audit(db) if c.row_id == comment_b.id]
        assert not mine[0].safe
        assert any("belongs to space" in b for b in mine[0].blockers)


# ---------------------------------------------------------------------------
# Storage preconditions
# ---------------------------------------------------------------------------

class TestStoragePreconditions:
    def test_a_missing_source_blocks(self, db, conversation, upload_dir):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        # Nothing written to storage.

        mine = [c for c in audit(db) if c.row_id == comment.id]
        assert not mine[0].safe
        assert any("source object is missing" in b for b in mine[0].blockers)

    def test_a_destination_with_different_content_blocks(
        self, db, conversation, upload_dir,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}", BYTES)
        _write(upload_dir, f"media/{space.slug}/community/{OCEAN}", b"different")

        mine = [c for c in audit(db) if c.row_id == comment.id]
        assert not mine[0].safe
        assert any("different content" in b for b in mine[0].blockers)

    def test_an_identical_destination_is_a_completed_copy_not_a_collision(
        self, db, conversation, upload_dir,
    ):
        """A run that stopped between copy and repoint must be able to
        finish, not refuse forever."""
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}")
        _write(upload_dir, f"media/{space.slug}/community/{OCEAN}")

        mine = [c for c in audit(db) if c.row_id == comment.id]
        assert mine[0].safe, mine[0].blockers
        assert mine[0].already_copied is True


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

class TestApply:
    def _one(self, db, comment_id):
        return next(c for c in audit(db) if c.row_id == comment_id)

    def test_it_copies_repoints_and_then_deletes(
        self, db, conversation, upload_dir,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        src = f"media/{space.slug}_community/{OCEAN}"
        dst = f"media/{space.slug}/community/{OCEAN}"
        _write(upload_dir, src)

        result = migrate(db, [self._one(db, comment.id)])
        db.flush()

        assert (upload_dir / dst).read_bytes() == BYTES, "copied intact"
        assert not (upload_dir / src).exists(), "source removed last"
        assert db.scalar(text(
            "SELECT image_url FROM post_comments WHERE id = :i"
        ), {"i": comment.id}) == canonical_url(space.slug)
        assert result.references_updated == 1
        assert result.deleted == [src]

    def test_keep_source_leaves_the_old_object(
        self, db, conversation, upload_dir,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        src = f"media/{space.slug}_community/{OCEAN}"
        _write(upload_dir, src)

        migrate(db, [self._one(db, comment.id)], delete_source=False)
        db.flush()

        assert (upload_dir / src).is_file(), "source kept"
        assert (upload_dir / f"media/{space.slug}/community/{OCEAN}").is_file()
        assert db.scalar(text(
            "SELECT image_url FROM post_comments WHERE id = :i"
        ), {"i": comment.id}) == canonical_url(space.slug)

    def test_a_failed_reference_update_does_not_delete_the_source(
        self, db, conversation, upload_dir, monkeypatch,
    ):
        """The chosen failure mode: a duplicate object costs pennies,
        a deleted-too-early object costs a member their image."""
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        src = f"media/{space.slug}_community/{OCEAN}"
        _write(upload_dir, src)
        candidate = self._one(db, comment.id)

        deleted: list[str] = []
        monkeypatch.setattr(storage, "delete_file", lambda k: deleted.append(k))
        real_execute = db.execute

        def boom(stmt, *a, **kw):
            if "UPDATE" in str(stmt).upper():
                raise RuntimeError("database went away")
            return real_execute(stmt, *a, **kw)

        monkeypatch.setattr(db, "execute", boom)

        with pytest.raises(RuntimeError, match="database went away"):
            migrate(db, [candidate])

        monkeypatch.undo()
        assert deleted == [], "nothing may be deleted when the update fails"
        assert (upload_dir / src).is_file(), "the readable object survives"

    def test_a_failed_copy_verification_aborts_before_any_delete(
        self, db, conversation, upload_dir, monkeypatch,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        src = f"media/{space.slug}_community/{OCEAN}"
        _write(upload_dir, src)
        candidate = self._one(db, comment.id)

        deleted: list[str] = []
        monkeypatch.setattr(storage, "delete_file", lambda k: deleted.append(k))
        # A copy that silently does nothing.
        monkeypatch.setattr(storage, "copy_object", lambda s, d: None)

        with pytest.raises(RuntimeError, match="not there"):
            migrate(db, [candidate])

        assert deleted == []
        assert (upload_dir / src).is_file()

    def test_a_truncated_copy_aborts_before_any_delete(
        self, db, conversation, upload_dir, monkeypatch,
    ):
        """A copy that lands but is not the same object.

        The destination existing is not proof the copy worked — a
        partial transfer leaves a shorter file there. Size and, where
        the backend gives one, the content hash are compared before
        anything is deleted.
        """
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        src = f"media/{space.slug}_community/{OCEAN}"
        _write(upload_dir, src)
        candidate = self._one(db, comment.id)

        deleted: list[str] = []
        monkeypatch.setattr(storage, "delete_file", lambda k: deleted.append(k))

        def truncated(s_key, d_key):
            dest = upload_dir / d_key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(BYTES[:10])

        monkeypatch.setattr(storage, "copy_object", truncated)

        with pytest.raises(RuntimeError, match="differs in size"):
            migrate(db, [candidate])

        assert deleted == [], "a bad copy must never lead to a delete"
        assert (upload_dir / src).read_bytes() == BYTES, "source intact"

    def test_a_same_size_but_different_copy_aborts_too(
        self, db, conversation, upload_dir, monkeypatch,
    ):
        """Same length, different bytes. Caught by the hash, which the
        filesystem backend supplies and R2 gives as an ETag."""
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        src = f"media/{space.slug}_community/{OCEAN}"
        _write(upload_dir, src)
        candidate = self._one(db, comment.id)

        deleted: list[str] = []
        monkeypatch.setattr(storage, "delete_file", lambda k: deleted.append(k))

        def corrupted(s_key, d_key):
            dest = upload_dir / d_key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"X" * len(BYTES))

        monkeypatch.setattr(storage, "copy_object", corrupted)

        with pytest.raises(RuntimeError, match="content hash"):
            migrate(db, [candidate])

        assert deleted == []
        assert (upload_dir / src).read_bytes() == BYTES

    def test_the_delete_happens_after_the_reference_update(
        self, db, conversation, upload_dir, monkeypatch,
    ):
        """Order asserted directly, not inferred.

        Reordering these two is the one change that could lose a
        member's image, and it would pass every other test here.
        """
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}")

        order: list[str] = []
        real_execute = db.execute

        def watched_execute(stmt, *a, **kw):
            if "UPDATE" in str(stmt).upper():
                order.append("update")
            return real_execute(stmt, *a, **kw)

        monkeypatch.setattr(db, "execute", watched_execute)
        real_delete = storage.delete_file
        monkeypatch.setattr(
            storage, "delete_file",
            lambda k: (order.append("delete"), real_delete(k))[1],
        )

        migrate(db, [self._one(db, comment.id)])

        assert "update" in order and "delete" in order
        assert order.index("update") < order.index("delete"), order

    def test_a_shared_object_moves_all_of_its_references(
        self, db, conversation, upload_dir,
    ):
        _c, space, post, comment = conversation()
        url = legacy_url(space.slug)
        post.image_url = url
        comment.image_url = url
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}")

        candidates = [c for c in audit(db) if c.url == url]
        assert len(candidates) == 2
        assert all(c.other_references == 1 for c in candidates)

        migrate(db, candidates[:1])  # one candidate rewrites both rows
        db.flush()

        for table, row_id in (("community_posts", post.id),
                              ("post_comments", comment.id)):
            assert db.scalar(text(
                f"SELECT image_url FROM {table} WHERE id = :i"  # noqa: S608
            ), {"i": row_id}) == canonical_url(space.slug)

    def test_a_blocked_candidate_is_skipped_not_migrated(
        self, db, conversation, upload_dir,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        # No source object -> blocked.
        result = migrate(db, audit(db))
        assert result.copied == []
        assert result.deleted == []
        assert result.skipped


class TestIdempotence:
    def test_a_second_run_finds_nothing(self, db, conversation, upload_dir):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        _write(upload_dir, f"media/{space.slug}_community/{OCEAN}")

        migrate(db, audit(db))
        db.flush()

        assert remaining_legacy_references(db) == 0
        second = migrate(db, audit(db))
        assert second.copied == []
        assert second.deleted == []
        assert second.references_updated == 0

    def test_resuming_after_a_copy_only_run_completes(
        self, db, conversation, upload_dir,
    ):
        _c, space, _post, comment = conversation()
        comment.image_url = legacy_url(space.slug)
        db.flush()
        src = f"media/{space.slug}_community/{OCEAN}"
        _write(upload_dir, src)

        migrate(db, audit(db), delete_source=False)
        db.flush()
        # References are canonical, old object still there.
        assert remaining_legacy_references(db) == 0
        assert (upload_dir / src).is_file()


# ---------------------------------------------------------------------------
# Authorisation is unchanged
# ---------------------------------------------------------------------------

class TestAuthorisationStillHolds:
    def test_the_canonical_key_is_member_only(self, db, conversation, upload_dir):
        from app.uploads.authorization import authorize_upload

        creator, space, _post, _comment = conversation()
        key = f"media/{space.slug}/community/{OCEAN}"

        authorize_upload(key, creator, db)  # must not raise

    def test_a_non_member_is_refused_the_canonical_key(
        self, db, conversation, make_user, upload_dir,
    ):
        from fastapi import HTTPException

        from app.uploads.authorization import authorize_upload

        _c, space, _post, _comment = conversation()
        stranger = make_user()
        key = f"media/{space.slug}/community/{OCEAN}"

        with pytest.raises(HTTPException) as exc:
            authorize_upload(key, stranger, db)
        assert exc.value.status_code == 403

    def test_migration_introduces_no_cross_collective_access(
        self, db, conversation, make_user, upload_dir,
    ):
        """A member of another Collective must not gain access just
        because the key moved."""
        from fastapi import HTTPException

        from app.uploads.authorization import authorize_upload

        _c, space_a, _p, comment_a = conversation(slug="alpha")
        creator_b, _space_b, _p2, _c2 = conversation(slug="beta")
        comment_a.image_url = legacy_url("alpha")
        db.flush()
        _write(upload_dir, f"media/alpha_community/{OCEAN}")

        migrate(db, audit(db))
        db.flush()

        with pytest.raises(HTTPException):
            authorize_upload(f"media/alpha/community/{OCEAN}", creator_b, db)


class TestNotScheduled:
    def test_the_script_is_a_one_time_manual_tool(self):
        src = (
            pathlib.Path(__file__).resolve().parent.parent
            / "scripts" / "migrate_legacy_community_media_keys.py"
        ).read_text()
        import re

        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = re.sub(r"#.*", "", code)
        assert '"--apply"' in code
        assert "action=\"store_true\"" in code
        # The write path sits behind the apply guard.
        assert code.index("if not args.apply:") < code.index("migrate(db, safe")
        assert "cron" not in code.lower()
        assert "schedule" not in code.lower()

    def test_it_is_absent_from_the_blueprint(self):
        blueprint = (
            pathlib.Path(__file__).resolve().parent.parent.parent / "render.yaml"
        ).read_text()
        assert "migrate_legacy_community_media_keys" not in blueprint


# ---------------------------------------------------------------------------
# Deleting the orphaned legacy object, after the migration
# ---------------------------------------------------------------------------


class TestOrphanCleanup:
    """The second half: the migration ran with ``--keep-source``, so the
    old object is still in storage and deliberately unreferenced.

    Discovery is useless here — nothing points at the old key, which is
    the *goal* — so the pair is named explicitly and the question becomes
    "prove this is safe to lose". These tests are mostly about the ways
    it refuses, since the operation is irreversible and the canonical
    object is the only copy left once it completes.
    """

    def _pair(self, slug, filename=OCEAN):
        return (
            f"media/{slug}_community/{filename}",
            f"media/{slug}/community/{filename}",
        )

    def _migrated(self, db, conversation, upload_dir, make_user, *, bytes_=BYTES):
        """A Collective whose reply image has already been migrated:
        canonical reference in the DB, both objects still in storage."""
        creator, space, post, comment = conversation()
        src, dest = self._pair(space.slug)
        _write(upload_dir, src, bytes_)
        _write(upload_dir, dest, bytes_)
        comment.image_url = canonical_url(space.slug)
        db.flush()
        make_user()  # an outsider, so the deny side can be verified
        return space, comment, src, dest

    # -- the clean case ----------------------------------------------

    def test_a_properly_migrated_object_is_safe_to_delete(
        self, db, conversation, upload_dir, make_user,
    ):
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        c = check_orphan(db, src, dest)

        assert c.blockers == [], c.blockers
        assert c.safe
        assert c.source_exists and not c.already_deleted
        assert c.legacy_references == []
        assert any(comment.id in r for r in c.canonical_references), (
            c.canonical_references
        )
        # The authorisation half actually ran, both directions.
        assert c.member_allowed == "allowed"
        assert c.non_member_denied == "denied"

    def test_the_audit_deletes_nothing(
        self, db, conversation, upload_dir, make_user,
    ):
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        check_orphan(db, src, dest)
        assert (upload_dir / src).is_file()
        assert (upload_dir / dest).is_file()

    def test_apply_removes_the_legacy_object_and_only_that(
        self, db, conversation, upload_dir, make_user,
    ):
        from app.services.legacy_community_media import (
            check_orphan, delete_orphan,
        )

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        assert delete_orphan(check_orphan(db, src, dest)) is True

        assert not (upload_dir / src).exists()
        assert (upload_dir / dest).is_file()
        assert (upload_dir / dest).read_bytes() == BYTES
        # And the reference still resolves to the canonical object.
        assert comment.image_url == canonical_url(space.slug)

    def test_re_running_after_a_successful_delete_is_a_no_op(
        self, db, conversation, upload_dir, make_user,
    ):
        from app.services.legacy_community_media import (
            check_orphan, delete_orphan,
        )

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        delete_orphan(check_orphan(db, src, dest))

        again = check_orphan(db, src, dest)
        assert again.safe, again.blockers
        assert again.already_deleted
        assert any("already gone" in n for n in again.notes)
        assert delete_orphan(again) is False
        assert (upload_dir / dest).is_file()

    # -- the refusals -------------------------------------------------

    def test_a_missing_canonical_object_blocks(
        self, db, conversation, upload_dir, make_user,
    ):
        """The one that matters most: if the replacement is not there,
        deleting the legacy object destroys the only copy."""
        from app.services.legacy_community_media import (
            check_orphan, delete_orphan,
        )

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        (upload_dir / dest).unlink()

        c = check_orphan(db, src, dest)
        assert not c.safe
        assert any("canonical object is missing" in b for b in c.blockers)
        with pytest.raises(RuntimeError, match="refusing to delete"):
            delete_orphan(c)
        assert (upload_dir / src).is_file()

    def test_a_different_size_at_the_destination_blocks(
        self, db, conversation, upload_dir, make_user,
    ):
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        _write(upload_dir, dest, BYTES[:-10])

        c = check_orphan(db, src, dest)
        assert any("sizes differ" in b for b in c.blockers), c.blockers

    def test_the_same_size_but_different_bytes_blocks(
        self, db, conversation, upload_dir, make_user,
    ):
        """Size alone is not identity. A truncated-then-padded copy, or
        a different image that happens to weigh the same, must not pass
        as the replacement."""
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        other = bytes(b ^ 0x5A for b in BYTES)
        assert len(other) == len(BYTES)
        _write(upload_dir, dest, other)

        c = check_orphan(db, src, dest)
        assert any("content hashes differ" in b for b in c.blockers), c.blockers

    def test_a_surviving_legacy_reference_blocks(
        self, db, conversation, upload_dir, make_user,
    ):
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        # A second post still on the old URL — the migration did not
        # finish, so the bytes are still being served from the old key.
        comment.image_url = legacy_url(space.slug)
        db.flush()

        c = check_orphan(db, src, dest)
        assert any("still point at the legacy URL" in b for b in c.blockers), (
            c.blockers
        )

    def test_a_legacy_reference_anywhere_in_the_schema_blocks(
        self, db, conversation, upload_dir, make_user,
    ):
        """The scan is wider than the two columns the migration writes.

        A migration cares where Conversation images are *written*. A
        delete cares whether anything at all still points at the bytes —
        so this searches every text column that could hold a media URL,
        by substring, and one hit outside the expected pair is enough to
        stop it.
        """
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        db.execute(text(
            "UPDATE spaces SET cover_image_url = :u WHERE id = :i"
        ), {"u": legacy_url(space.slug), "i": space.id})
        db.flush()

        c = check_orphan(db, src, dest)
        assert any("still point at the legacy URL" in b for b in c.blockers), (
            c.blockers
        )
        assert any("spaces.cover_image_url" in r for r in c.legacy_references)
        assert c.columns_scanned > len(("community_posts", "post_comments"))

    def test_no_canonical_reference_blocks(
        self, db, conversation, upload_dir, make_user,
    ):
        """Zero references to either URL is not "clean", it is a sign
        the migration moved the reference somewhere unexpected."""
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        comment.image_url = None
        db.flush()

        c = check_orphan(db, src, dest)
        assert any("no database reference points at" in b for b in c.blockers), (
            c.blockers
        )

    def test_no_verifiable_member_blocks(
        self, db, conversation, upload_dir, make_user,
    ):
        """If the canonical key cannot be *shown* to serve, the legacy
        object stays. An unprovable success is a refusal."""
        from app.services.legacy_community_media import check_orphan

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        db.execute(text(
            "UPDATE space_memberships SET status = 'removed' WHERE space_id = :i"
        ), {"i": space.id})
        db.execute(text(
            "UPDATE spaces SET creator_id = NULL WHERE id = :i"
        ), {"i": space.id})
        db.flush()

        c = check_orphan(db, src, dest)
        assert any("cannot prove the canonical image" in b for b in c.blockers), (
            c.blockers
        )

    def test_a_canonical_key_a_member_cannot_read_blocks(
        self, db, conversation, upload_dir, make_user, monkeypatch,
    ):
        """Deleting the legacy object is only safe if the replacement
        authorises. A 403 on the canonical path would leave a broken
        image and nothing to fall back to."""
        from app.services import legacy_community_media as svc
        from fastapi import HTTPException

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )

        import app.uploads.authorization as authz

        def deny(file_path, user, db_):
            raise HTTPException(status_code=403, detail="Access denied.")

        monkeypatch.setattr(authz, "authorize_upload", deny)

        c = svc.check_orphan(db, src, dest)
        assert any("cannot read the canonical object" in b for b in c.blockers), (
            c.blockers
        )
        assert c.member_allowed and c.member_allowed.startswith("DENIED")

    def test_a_silently_failed_delete_is_reported_not_swallowed(
        self, db, conversation, upload_dir, make_user, monkeypatch,
    ):
        """``storage.delete_file`` swallows backend errors by design, so
        the result is verified rather than trusted."""
        from app.services.legacy_community_media import (
            check_orphan, delete_orphan,
        )

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        monkeypatch.setattr(storage, "delete_file", lambda key: None)

        c = check_orphan(db, src, dest)
        with pytest.raises(RuntimeError, match="still there"):
            delete_orphan(c)
        assert (upload_dir / src).is_file()
        assert (upload_dir / dest).is_file()

    def test_losing_the_canonical_object_during_the_delete_is_fatal(
        self, db, conversation, upload_dir, make_user, monkeypatch,
    ):
        """Should be impossible. Checked anyway, because the alternative
        is reporting success while the image is gone."""
        from app.services.legacy_community_media import (
            check_orphan, delete_orphan,
        )

        space, comment, src, dest = self._migrated(
            db, conversation, upload_dir, make_user,
        )
        c = check_orphan(db, src, dest)

        real = storage.delete_file

        def delete_both(key):
            real(key)
            real(dest)

        monkeypatch.setattr(storage, "delete_file", delete_both)
        with pytest.raises(RuntimeError, match="restore from backup"):
            delete_orphan(c)

    # -- the script around it -----------------------------------------

    def test_the_cleanup_script_defaults_to_the_known_pair(self):
        """Named explicitly, not discovered. The pair is the production
        object and its canonical replacement, and they differ only in
        where the separator sits.

        Read with ``ast`` rather than imported. Operational scripts set
        ``FC_SERVICE_ROLE`` at import time so they can run outside the
        web process, and importing one mid-suite leaves that in
        ``os.environ`` for every test after it — which is exactly how
        this broke three unrelated boot-guard tests on its first run.
        """
        import ast

        path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "scripts/delete_legacy_community_media_object.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue  # BACKEND_ROOT and friends are not literals
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = value
        src = consts["DEFAULT_SOURCE_KEY"]
        dest = consts["DEFAULT_DEST_KEY"]
        assert src.startswith("media/embody_community/")
        assert dest.startswith("media/embody/community/")
        assert src.rsplit("/", 1)[1] == dest.rsplit("/", 1)[1]

    def test_the_cleanup_script_is_not_scheduled(self):
        """A one-time delete must not be wired into the blueprint. A
        ``value:`` entry there is reasserted on every sync, so a
        scheduled delete would come back after being removed."""
        blueprint = (
            pathlib.Path(__file__).resolve().parent.parent.parent / "render.yaml"
        )
        assert blueprint.exists()
        assert "delete_legacy_community_media_object" not in blueprint.read_text()


class TestDiscoveryDoesNotOverMatch:
    """``LIKE`` reads a bare ``_`` as a single-character wildcard, and
    these two keys differ only in that character::

        media/embody_community/ocean.jpeg     <- legacy
        media/embody/community/ocean.jpeg     <- canonical

    So an unescaped ``%_community/%`` prefilter matches both, and every
    correctly migrated reference comes back as a candidate. The regex
    downstream threw them out, so the audit's answer was right while its
    query was wrong — the kind of thing that stays invisible until a
    second caller reuses the pattern and has no regex behind it.
    """

    def test_the_prefilter_sql_the_audit_actually_sends_is_escaped(self, db):
        """Captured off the cursor, not read off a literal in the test.

        Asserting on a pattern written out here would prove only that
        the test can spell it. These are the statements and parameters
        the audit hands to the database.
        """
        from sqlalchemy import event

        sent: list[tuple[str, object]] = []

        def record(conn, cursor, statement, params, context, executemany):
            sent.append((statement, params))

        bind = db.get_bind()
        event.listen(bind, "before_cursor_execute", record)
        try:
            audit(db)
        finally:
            event.remove(bind, "before_cursor_execute", record)

        prefilters = [
            (st, pr) for st, pr in sent if "LIKE" in st and "community" in str(pr)
        ]
        assert prefilters, [st for st, _ in sent]
        for statement, params in prefilters:
            assert "ESCAPE" in statement, statement
            assert "\\_community/" in str(params), params

        # And the escaped pattern really does separate the two shapes,
        # asked of this same database rather than of LIKE in the
        # abstract.
        legacy = "/api/uploads/media/embody_community/ocean.jpeg"
        canonical = "/api/uploads/media/embody/community/ocean.jpeg"
        pattern = next(
            v for _st, pr in prefilters
            for v in (pr.values() if hasattr(pr, "values") else pr)
            if "community" in str(v)
        )
        matched = db.execute(text(
            "SELECT v FROM (VALUES (:a), (:b)) AS t(v) "
            "WHERE v LIKE :p ESCAPE '\\'"
        ), {"a": legacy, "b": canonical, "p": pattern}).scalars().all()
        assert matched == [legacy]

    def test_a_canonical_reference_is_not_a_candidate(
        self, db, conversation, upload_dir,
    ):
        """The behaviour the escaping protects, end to end."""
        creator, space, post, comment = conversation()
        comment.image_url = canonical_url(space.slug)
        post.image_url = canonical_url(space.slug, "other.png")
        db.flush()
        assert audit(db) == []


class TestTheDenySideIsActuallyExercised:
    """``check_orphan`` verifies that a non-member is refused the
    canonical key. A check like that is easy to write so that it passes
    without having asked anything — the refusal arrives as an exception,
    and an exception is also what a broken call produces.

    So: make the authoriser allow everybody and confirm it notices, and
    make it fail in a non-authorisation way and confirm it does not
    count that as a refusal.
    """

    def _migrated(self, db, conversation, upload_dir, make_user):
        creator, space, post, comment = conversation()
        src = f"media/{space.slug}_community/{OCEAN}"
        dest = f"media/{space.slug}/community/{OCEAN}"
        _write(upload_dir, src)
        _write(upload_dir, dest)
        comment.image_url = canonical_url(space.slug)
        db.flush()
        make_user()
        return space, src, dest

    def test_a_non_member_who_can_read_it_blocks(
        self, db, conversation, upload_dir, make_user, monkeypatch,
    ):
        from app.services import legacy_community_media as svc
        import app.uploads.authorization as authz

        space, src, dest = self._migrated(db, conversation, upload_dir, make_user)
        monkeypatch.setattr(authz, "authorize_upload", lambda *a, **k: None)

        c = svc.check_orphan(db, src, dest)
        assert any("a non-member can read" in b for b in c.blockers), c.blockers
        assert c.non_member_denied.startswith("ALLOWED")

    def test_a_crash_in_the_authoriser_is_not_a_refusal(
        self, db, conversation, upload_dir, make_user, monkeypatch,
    ):
        """The quiet failure: a broken authoriser raises, and a bare
        ``except`` would record that as "correctly denied" — proving
        nothing while looking like proof."""
        from app.services import legacy_community_media as svc
        import app.uploads.authorization as authz
        from fastapi import HTTPException

        space, src, dest = self._migrated(db, conversation, upload_dir, make_user)

        calls = {"n": 0}

        def allow_member_then_explode(file_path, user, db_):
            calls["n"] += 1
            if calls["n"] == 1:
                return  # the member read succeeds
            raise RuntimeError("connection reset")

        monkeypatch.setattr(authz, "authorize_upload", allow_member_then_explode)

        c = svc.check_orphan(db, src, dest)
        assert any("could not verify" in b for b in c.blockers), c.blockers
        assert "errored" in c.non_member_denied

        # And a 500 from the authoriser is not a refusal either.
        calls["n"] = 0

        def allow_member_then_500(file_path, user, db_):
            calls["n"] += 1
            if calls["n"] == 1:
                return
            raise HTTPException(status_code=500, detail="boom")

        monkeypatch.setattr(authz, "authorize_upload", allow_member_then_500)
        c = svc.check_orphan(db, src, dest)
        assert any("rather than a refusal" in b for b in c.blockers), c.blockers
