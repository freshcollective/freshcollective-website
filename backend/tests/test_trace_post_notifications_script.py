"""The notification diagnostic runs against the real schema.

Sentry FC-API-K was an ``AttributeError`` from this script:
``CommunicationChannelDefault`` has ``default_enabled``, a boolean,
and the script read ``default_priority``. Nothing exercised it, so a
wrong attribute name shipped and only surfaced when it was run by
hand in production — reported as an application error with zero users
affected, because no request was involved.

So this drives ``run_trace`` over a seeded post and asserts it reaches
the end. Every model attribute the diagnostic touches is dereferenced
on the way, which is what makes a stale assumption fail here instead
of in somebody's terminal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models.platform import (
    BookingStatus,
    ChannelExperienceLink,
    ChannelMembership,
    CommunityPost,
    ConversationChannel,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "trace_post_notifications.py"
)


def _load_script():
    """Import the script by path — it is not an installed module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "trace_post_notifications", SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def kelly(make_user):
    return make_user(role="creator", name="Kelly")


@pytest.fixture
def space(make_space, kelly):
    return make_space(creator=kelly, name="Moonlit Circle")


@pytest.fixture
def join(db):
    def _join(space, user, role=SpaceRole.learner):
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=user.id, space_id=space.id,
            role=role, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
    return _join


def _post(db, space, author, channel):
    row = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, body="A note for the circle",
        is_visible=True, publication_status="published",
        published_at=datetime.utcnow(),
        notifications_processed_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


class TestItRunsToCompletion:
    def test_an_open_channel_post(
        self, db, space, channel_factory, kelly, join, make_user, capsys,
    ):
        """The shape the production run had: an open channel with
        several members."""
        ch = channel_factory("open")
        for _ in range(3):
            join(space, make_user())
        join(space, kelly, role=SpaceRole.creator)
        post = _post(db, space, kelly, ch)
        db.commit()

        module = _load_script()
        assert module.run_trace(db, post) == 0

        out = capsys.readouterr().out
        # The stage the AttributeError killed, and the ones after it.
        assert "PREFERENCES" in out
        assert "default_enabled=" in out
        assert "INTENTS" in out
        assert "OUTBOUND GUARD" in out
        assert "Nothing was written." in out

    def test_a_private_channel_post(
        self, db, space, channel_factory, kelly, join, make_user, capsys,
    ):
        ch = channel_factory("private")
        inside = make_user()
        join(space, inside)
        join(space, make_user())
        join(space, kelly, role=SpaceRole.creator)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=inside.id,
            role="member", source="manual", status="active",
        ))
        post = _post(db, space, kelly, ch)
        db.commit()

        module = _load_script()
        assert module.run_trace(db, post) == 0
        out = capsys.readouterr().out
        assert "private" in out
        assert "not added to this private channel" in out

    def test_a_linked_channel_post_with_several_links(
        self, db, space, channel_factory, kelly, join, make_user,
        make_event, capsys,
    ):
        """Dereferences ``ChannelExperienceLink.experience_type`` and
        ``experience_id``, which are properties rather than columns."""
        ch = channel_factory("gathering")
        a, b = make_event(space=space), make_event(space=space)
        for ev in (a, b):
            db.add(ChannelExperienceLink(
                id=_uid("cel"), channel_id=ch.id, event_id=ev.id,
            ))
        attendee = make_user()
        join(space, attendee)
        join(space, kelly, role=SpaceRole.creator)
        db.add(EventBooking(
            id=_uid("bk"), event_id=a.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        ))
        post = _post(db, space, kelly, ch)
        db.commit()

        module = _load_script()
        assert module.run_trace(db, post) == 0
        out = capsys.readouterr().out
        assert "links         2" in out
        assert "gathering " in out

    def test_a_removed_member_is_explained(
        self, db, space, channel_factory, kelly, join, make_user, capsys,
    ):
        ch = channel_factory("private")
        removed = make_user()
        join(space, removed)
        join(space, kelly, role=SpaceRole.creator)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=removed.id,
            role="member", source="experience", status="removed",
            removed_reason="creator", removed_at=datetime.utcnow(),
        ))
        post = _post(db, space, kelly, ch)
        db.commit()

        module = _load_script()
        assert module.run_trace(db, post) == 0
        assert "removed by creator" in capsys.readouterr().out


class TestTheAttributeThatBroke:
    def test_the_model_has_default_enabled_not_default_priority(self):
        """Pins the fact the script got wrong."""
        from app.comms.models import CommunicationChannelDefault

        columns = {c.name for c in CommunicationChannelDefault.__table__.c}
        assert "default_enabled" in columns
        assert "default_priority" not in columns

    def test_the_script_does_not_mention_the_wrong_name(self):
        source = SCRIPT.read_text()
        offending = [
            line for line in source.splitlines()
            if "default_priority" in line and "does not" not in line
        ]
        assert offending == [], offending

    def test_the_default_is_reported_as_a_resolved_priority(
        self, db, space, channel_factory, kelly, join, make_user, capsys,
    ):
        """``default_enabled`` is a boolean; the useful thing to print
        is what it resolves to, since that is what decides delivery."""
        ch = channel_factory("open")
        join(space, make_user())
        join(space, kelly, role=SpaceRole.creator)
        post = _post(db, space, kelly, ch)
        db.commit()

        module = _load_script()
        module.run_trace(db, post)
        out = capsys.readouterr().out
        assert ("→ immediate" in out) or ("→ silent" in out)


class TestItIsReadOnly:
    def test_it_writes_nothing(
        self, db, space, channel_factory, kelly, join, make_user,
    ):
        from app.comms.models import CommunicationEvent, CommunicationIntent

        ch = channel_factory("open")
        join(space, make_user())
        join(space, kelly, role=SpaceRole.creator)
        post = _post(db, space, kelly, ch)
        db.commit()

        before = (
            db.query(CommunicationEvent).count(),
            db.query(CommunicationIntent).count(),
            db.query(ChannelMembership).count(),
            db.query(CommunityPost).count(),
        )
        module = _load_script()
        module.run_trace(db, post)
        after = (
            db.query(CommunicationEvent).count(),
            db.query(CommunicationIntent).count(),
            db.query(ChannelMembership).count(),
            db.query(CommunityPost).count(),
        )
        assert before == after

    def test_the_source_contains_no_write_statement(self):
        """A diagnostic that can be run against production must not
        learn to write. Cheap to assert, and the kind of thing a later
        edit does by accident."""
        source = SCRIPT.read_text().lower()
        for forbidden in (
            "db.add(", "db.commit()", "db.delete(", "db.merge(",
            "update ", "insert into", "delete from",
        ):
            assert forbidden not in source, forbidden


class TestAddressesAreMasked:
    def test_only_the_domain_is_printed(
        self, db, space, channel_factory, kelly, join, make_user, capsys,
    ):
        ch = channel_factory("open")
        member = make_user(email="verylongname@freshcollective.au")
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        post = _post(db, space, kelly, ch)
        db.commit()

        module = _load_script()
        module.run_trace(db, post)
        out = capsys.readouterr().out
        assert "verylongname@" not in out, "the local part was printed"
        assert "v***@freshcollective.au" in out


@pytest.fixture
def channel_factory(db, space):
    def _make(kind: str):
        row = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Moonlit Circle",
            slug=f"{kind}-{uuid.uuid4().hex[:8]}", channel_type=kind,
            member_posting_allowed=True,
        )
        db.add(row)
        db.flush()
        return row
    return _make
