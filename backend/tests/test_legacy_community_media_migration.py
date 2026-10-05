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
