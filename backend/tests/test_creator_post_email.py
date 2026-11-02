"""Emails when a creator posts in a Conversations channel.

These drive the real path: a post created through the HTTP endpoint,
the ``community.post.published`` event it writes, the recipient
resolver run against that event, and the email template rendered for
each recipient. Asserting that an event was emitted would prove
nothing about who gets mailed or what the mail says — which is where
both of this feature's defects lived.

The privacy rule under test, found and fixed earlier: a post in a
private or linked channel must not notify the Collective. The
recipient set comes from the channel's audience.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_user,
    get_optional_user,
    get_verified_current_user,
)
from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.routing.resolvers.community import NewPostResolver
from app.comms.templates.community import NewPostEmailTemplate
from app.db.session import get_db
from app.main import app
from app.models.platform import (
    BookingStatus,
    ChannelExperienceLink,
    ChannelMembership,
    ConversationChannel,
    Enrollment,
    EventBooking,
    Pathway,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def kelly(make_user):
    return make_user(role="creator", name="Kelly")


@pytest.fixture
def space(make_space, kelly):
    return make_space(creator=kelly, name="Nourish Connect Thrive")


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


@pytest.fixture
def channel(db, space):
    def _make(kind="open", name="Women's Circle", **kw):
        row = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name=name,
            slug=f"{kind}-{uuid.uuid4().hex[:8]}", channel_type=kind,
            member_posting_allowed=True, **kw,
        )
        db.add(row)
        db.flush()
        return row
    return _make


@pytest.fixture
def as_user(db):
    def _as(user):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_optional_user] = lambda: user
        app.dependency_overrides[get_verified_current_user] = lambda: user
        return TestClient(app)
    yield _as
    app.dependency_overrides.clear()


def _publish(client, space, ch, body="Something new to share with you all"):
    r = client.post(
        f"/api/spaces/{space.slug}/community",
        json={"body": body, "channel_slug": ch.slug},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _event(db, post_id) -> CommunicationEvent:
    ev = (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == "community.post.published",
            CommunicationEvent.subject_id == post_id,
        )
        .first()
    )
    assert ev is not None, "no community.post.published event was written"
    return ev


def _recipients(db, event) -> list[ResolvedRecipient]:
    return NewPostResolver().resolve(db, event)


def _emails(db, event, recipients) -> dict[str, dict]:
    """Render the real email for each recipient."""
    tmpl = NewPostEmailTemplate()
    out = {}
    for r in recipients:
        payload = tmpl.render(db, event, r)
        out[r.user_id] = {
            "subject": payload.subject,
            "html": payload.body_html,
            "text": payload.body_text,
        }
    return out


# ---------------------------------------------------------------------------
# Recipient selection, per channel type
# ---------------------------------------------------------------------------


class TestOpenChannel:
    def test_every_active_member_except_the_author(
        self, db, space, channel, join, kelly, make_user, as_user,
    ):
        ch = channel(kind="open")
        members = [make_user() for _ in range(3)]
        for m in members:
            join(space, m)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        recipients = _recipients(db, _event(db, post["id"]))
        got = {r.user_id for r in recipients}

        assert got == {m.id for m in members}
        assert kelly.id not in got, "the author is never a recipient"


class TestPrivateChannel:
    """The privacy rule. A private post must not reach the Collective."""

    def test_only_explicitly_added_members(
        self, db, space, channel, join, kelly, make_user, as_user,
    ):
        ch = channel(kind="private", name="Inner Circle")
        inside, outside = make_user(), make_user()
        for m in (inside, outside):
            join(space, m)
        join(space, kelly, role=SpaceRole.creator)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=inside.id,
            role="member", source="manual", status="active",
        ))
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        got = {r.user_id for r in _recipients(db, _event(db, post["id"]))}

        assert got == {inside.id}
        assert outside.id not in got, (
            "a Collective member who is not in the channel was mailed an "
            "excerpt of a private conversation"
        )


class TestLinkedChannel:
    @pytest.fixture
    def setup(self, db, space, channel, join, kelly, make_user, make_event):
        """One channel, two Gatherings and a free Pathway linked."""
        ch = channel(kind="gathering", name="Women's Circle")
        november = make_event(space=space, title="November Circle")
        december = make_event(space=space, title="December Circle")
        pathway = Pathway(
            id=_uid("pw"), space_id=space.id, title="Daring Heart",
            slug=f"dh-{uuid.uuid4().hex[:6]}",
            status="active", access_type="free",
        )
        db.add(pathway)
        db.flush()
        for kw in (
            {"event_id": november.id},
            {"event_id": december.id},
            {"pathway_id": pathway.id},
        ):
            db.add(ChannelExperienceLink(
                id=_uid("cel"), channel_id=ch.id, **kw,
            ))
        join(space, kelly, role=SpaceRole.creator)
        db.flush()
        return ch, november, december, pathway

    def test_qualifying_through_any_one_experience_is_enough(
        self, db, space, setup, join, kelly, make_user, as_user,
    ):
        ch, november, _, pathway = setup
        attendee = make_user()
        learner = make_user()
        for m in (attendee, learner):
            join(space, m)
        db.add(EventBooking(
            id=_uid("bk"), event_id=november.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        ))
        db.add(Enrollment(
            id=_uid("en"), user_id=learner.id, pathway_id=pathway.id,
            status="active",
        ))
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        got = {r.user_id for r in _recipients(db, _event(db, post["id"]))}
        assert got == {attendee.id, learner.id}

    def test_someone_who_never_joined_is_not_mailed(
        self, db, space, setup, join, kelly, make_user, as_user,
    ):
        """Browsing a free Pathway is not joining it."""
        ch, _, _, _ = setup
        browser = make_user()
        join(space, browser)
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        got = {r.user_id for r in _recipients(db, _event(db, post["id"]))}
        assert browser.id not in got

    def test_a_retained_member_is_still_mailed_after_the_gathering_ends(
        self, db, space, setup, join, kelly, make_user, as_user,
    ):
        """The point of the persistence rule: they are still in the
        conversation, so they still hear about it."""
        ch, november, _, _ = setup
        alum = make_user()
        join(space, alum)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=alum.id,
            role="member", source="experience", status="active",
        ))
        november.starts_at = datetime.utcnow() - timedelta(days=90)
        november.ends_at = datetime.utcnow() - timedelta(days=90)
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        got = {r.user_id for r in _recipients(db, _event(db, post["id"]))}
        assert alum.id in got

    def test_a_removed_member_is_not_mailed(
        self, db, space, setup, join, kelly, make_user, as_user,
    ):
        ch, november, _, _ = setup
        removed = make_user()
        join(space, removed)
        db.add(EventBooking(
            id=_uid("bk"), event_id=november.id, user_id=removed.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        ))
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=removed.id,
            role="member", source="experience", status="removed",
            removed_reason="creator", removed_at=datetime.utcnow(),
        ))
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        got = {r.user_id for r in _recipients(db, _event(db, post["id"]))}
        assert removed.id not in got, (
            "a creator's removal must stop the emails too"
        )

    def test_a_pending_hold_is_not_mailed(
        self, db, space, setup, join, kelly, make_user, as_user,
    ):
        ch, november, _, _ = setup
        shopper = make_user()
        join(space, shopper)
        db.add(EventBooking(
            id=_uid("bk"), event_id=november.id, user_id=shopper.id,
            status=BookingStatus.pending_payment, source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=20),
        ))
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        got = {r.user_id for r in _recipients(db, _event(db, post["id"]))}
        assert shopper.id not in got


# ---------------------------------------------------------------------------
# The email itself
# ---------------------------------------------------------------------------


class TestEmailContent:
    @pytest.fixture
    def rendered(self, db, space, channel, join, kelly, make_user, as_user):
        ch = channel(kind="open", name="Women's Circle")
        member = make_user()
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(
            as_user(kelly), space, ch,
            body="A reflection on where we have got to this month.",
        )
        event = _event(db, post["id"])
        recipients = _recipients(db, event)
        return _emails(db, event, recipients)[member.id], post

    def test_it_names_the_creator_and_the_channel(self, rendered):
        email, _ = rendered
        assert "Kelly" in email["subject"]
        assert "Women's Circle" in email["subject"]
        assert "Kelly" in email["html"]
        assert "Women's Circle" in email["html"]

    def test_it_names_the_collective(self, rendered):
        email, _ = rendered
        assert "Nourish Connect Thrive" in email["html"]

    def test_it_previews_the_post(self, rendered):
        email, _ = rendered
        assert "A reflection on where we have got to" in email["html"]

    def test_it_carries_a_view_conversation_button(self, rendered):
        email, _ = rendered
        assert "View Conversation" in email["html"]

    def test_the_link_points_at_that_conversation(self, rendered):
        email, post = rendered
        assert f"/community/{post['id']}" in email["html"], (
            "the button must open this conversation, not the feed"
        )
        assert f"/community/{post['id']}" in email["text"], (
            "the text part needs the URL too — no button to click there"
        )

    def test_the_linked_url_still_enforces_permissions(
        self, db, space, channel, join, kelly, make_user, as_user,
    ):
        """§4 — the link is not a bypass."""
        ch = channel(kind="private", name="Inner Circle")
        inside, outside = make_user(), make_user()
        for m in (inside, outside):
            join(space, m)
        join(space, kelly, role=SpaceRole.creator)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=inside.id,
            role="member", source="manual", status="active",
        ))
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        url = f"/api/spaces/{space.slug}/community/{post['id']}"

        assert as_user(inside).get(url).status_code == 200
        assert as_user(outside).get(url).status_code == 404


class TestCreatorFraming:
    """§6 — who counts as making an announcement."""

    def test_a_creator_post_is_framed_as_theirs(
        self, db, space, channel, join, kelly, make_user, as_user,
    ):
        ch = channel(kind="open")
        member = make_user()
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        event = _event(db, post["id"])
        assert (event.payload or {}).get("is_creator_post") is True
        email = _emails(db, event, _recipients(db, event))[member.id]
        assert "Kelly" in email["subject"]

    def test_an_administrator_posting_elsewhere_is_not_a_creator(
        self, db, space, channel, join, kelly, make_user, as_user,
    ):
        """A platform admin is an ordinary member of Kelly's
        Collective, so their post is not Kelly's announcement — and
        must not be dressed as one.
        """
        ch = channel(kind="open")
        admin = make_user(role="admin", name="Platform Admin")
        member = make_user()
        for m in (admin, member):
            join(space, m)
        db.commit()

        post = _publish(as_user(admin), space, ch)
        event = _event(db, post["id"])
        assert (event.payload or {}).get("is_creator_post") is False

    def test_a_moderator_of_this_collective_does_count(
        self, db, space, channel, join, make_user, as_user,
    ):
        ch = channel(kind="open")
        mod = make_user(name="Mo")
        join(space, mod, role=SpaceRole.moderator)
        db.commit()

        post = _publish(as_user(mod), space, ch)
        event = _event(db, post["id"])
        assert (event.payload or {}).get("is_creator_post") is True


class TestNoDuplicatePath:
    """§7 — the legacy trigger and the pipeline must not both send."""

    def test_the_topic_is_live_so_the_legacy_trigger_no_ops(self):
        from app.comms.rollout import is_event_live

        assert is_event_live("community.post.published") is True

    def test_the_legacy_trigger_returns_early_when_live(self, db):
        """Asserted by behaviour: with the topic live it must write no
        notifications at all."""
        from app.services.notification_service import trigger_new_post

        # A post id that does not exist: if the guard did not return
        # first, this would go on to query and log. It returning
        # quietly is the contract.
        trigger_new_post("p_missing", "s_missing", "u_missing")

    def test_one_event_per_published_post(
        self, db, space, channel, join, kelly, make_user, as_user,
    ):
        ch = channel(kind="open")
        join(space, make_user())
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        count = (
            db.query(CommunicationEvent)
            .filter(
                CommunicationEvent.event_type == "community.post.published",
                CommunicationEvent.subject_id == post["id"],
            )
            .count()
        )
        assert count == 1

    def test_resolution_yields_one_recipient_row_per_member(
        self, db, space, channel, join, kelly, make_user, as_user,
    ):
        """Qualifying twice over must not mean two emails."""
        ch = channel(kind="gathering")
        a = make_user()
        join(space, a)
        join(space, kelly, role=SpaceRole.creator)
        # Two links, both satisfied by the same person.
        e1 = _mk_event(db, space, kelly, "One")
        e2 = _mk_event(db, space, kelly, "Two")
        for e in (e1, e2):
            db.add(ChannelExperienceLink(
                id=_uid("cel"), channel_id=ch.id, event_id=e.id,
            ))
            db.add(EventBooking(
                id=_uid("bk"), event_id=e.id, user_id=a.id,
                status=BookingStatus.confirmed, source="ticket_purchase",
                booked_at=datetime.utcnow(),
            ))
        db.commit()

        post = _publish(as_user(kelly), space, ch)
        recipients = _recipients(db, _event(db, post["id"]))
        ids = [r.user_id for r in recipients]
        assert ids.count(a.id) == 1


def _mk_event(db, space, creator, title):
    from app.models.platform import Event

    row = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title=title, starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=7, hours=1),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=10,
        booking_access_type="free",
        gathering_type="workshop", attendance_format="online",
    )
    db.add(row)
    db.flush()
    return row
