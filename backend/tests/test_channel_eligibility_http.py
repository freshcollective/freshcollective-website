"""Channel eligibility through the endpoints a member actually calls.

The predicates have their own tests. These drive HTTP, because an
endpoint can disagree with its helper — the member channel list once
did, and the mention-autocomplete audience was built from a second
copy of the rule. A test that asserts the helper cannot see that.

Every case is checked on four surfaces at once: the channel list, the
channel feed, an individual post, and posting. A channel missing from
navigation while its content answers a direct URL is not access
control.
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
from app.db.session import get_db
from app.main import app
from app.models.access_pass import AccessPass, AccessPassStatus, AccessPassType
from app.models.platform import (
    BookingStatus,
    ChannelExperienceLink,
    ChannelMembership,
    CommunityPost,
    ConversationChannel,
    EntitlementStatus,
    Enrollment,
    EventBooking,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def owner(make_user):
    return make_user(role="creator")


@pytest.fixture
def space(make_space, owner):
    return make_space(creator=owner)


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
    def _make(kind="pathway", **kw):
        row = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Linked Channel",
            slug=f"linked-{uuid.uuid4().hex[:8]}", channel_type=kind,
            member_posting_allowed=True, **kw,
        )
        db.add(row)
        db.flush()
        return row
    return _make


@pytest.fixture
def link(db):
    def _link(ch, *, pathway=None, event=None, series=None):
        db.add(ChannelExperienceLink(
            id=_uid("cel"), channel_id=ch.id,
            pathway_id=pathway.id if pathway is not None else None,
            event_id=event.id if event is not None else None,
            series_id=series.id if series is not None else None,
        ))
        db.flush()
    return _link


@pytest.fixture
def post(db, space, owner):
    def _make(ch):
        row = CommunityPost(
            id=_uid("cp"), space_id=space.id, channel_id=ch.id,
            author_id=owner.id, body="Among those who joined",
            is_visible=True, publication_status="published",
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


def _surfaces(client, space, ch, a_post):
    """The four member-facing answers, as a dict of booleans."""
    listed = client.get(f"/api/spaces/{space.slug}/channels")
    in_list = (
        listed.status_code == 200
        and ch.id in [c["id"] for c in listed.json()]
    )
    feed = client.get(
        f"/api/spaces/{space.slug}/community?channel={ch.slug}",
    )
    detail = client.get(f"/api/spaces/{space.slug}/community/{a_post.id}")
    created = client.post(
        f"/api/spaces/{space.slug}/community",
        json={"body": "Hello", "channel_slug": ch.slug},
    )
    return {
        "in_list": in_list,
        "feed": feed.status_code == 200,
        "post_detail": detail.status_code == 200,
        "can_create": created.status_code in (200, 201),
    }


def _assert_all(surfaces: dict, expected: bool):
    for name, got in surfaces.items():
        assert got is expected, (
            f"{name} answered {got}, expected {expected} — "
            "every surface must agree"
        )


@pytest.fixture
def free_pathway(db, space):
    row = Pathway(
        id=_uid("pw"), space_id=space.id, title="Open Practice",
        slug=f"open-{uuid.uuid4().hex[:8]}",
        status="active", access_type="free",
    )
    db.add(row)
    db.flush()
    return row


class TestFreePathwayBrowsingVersusJoining:
    """§2 — the business rule, end to end."""

    @pytest.fixture
    def setup(self, db, space, channel, link, free_pathway, post):
        ch = channel()
        link(ch, pathway=free_pathway)
        p = post(ch)
        db.commit()
        return ch, p

    def test_viewing_without_joining_is_refused_everywhere(
        self, db, space, setup, join, make_user, as_user,
    ):
        ch, p = setup
        browser = make_user()
        join(space, browser)
        db.commit()

        _assert_all(_surfaces(as_user(browser), space, ch, p), False)

    def test_joining_opens_every_surface(
        self, db, space, setup, free_pathway, join, make_user, as_user,
    ):
        """An Enrollment is what a free Pathway writes when somebody
        starts it, and the only record it ever writes."""
        ch, p = setup
        learner = make_user()
        join(space, learner)
        db.add(Enrollment(
            id=_uid("en"), user_id=learner.id,
            pathway_id=free_pathway.id, status="active",
        ))
        db.commit()

        _assert_all(_surfaces(as_user(learner), space, ch, p), True)


class TestPaidPathway:
    @pytest.fixture
    def paid(self, db, space, channel, link, post):
        pw = Pathway(
            id=_uid("pw"), space_id=space.id, title="Deep Work",
            slug=f"deep-{uuid.uuid4().hex[:8]}",
            status="active", access_type="one_time",
        )
        db.add(pw)
        db.flush()
        ch = channel()
        link(ch, pathway=pw)
        p = post(ch)
        db.commit()
        return ch, p, pw

    def test_an_entitlement_opens_it(
        self, db, space, paid, join, make_user, as_user,
    ):
        ch, p, pw = paid
        buyer = make_user()
        join(space, buyer)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, status=EntitlementStatus.active,
            source="one_time_purchase",
        ))
        db.commit()

        _assert_all(_surfaces(as_user(buyer), space, ch, p), True)

    def test_a_progress_row_alone_does_not(
        self, db, space, paid, join, make_user, as_user,
    ):
        """The pinned rule for paid Pathways: an Enrollment with no
        live entitlement is somebody whose access was revoked or has
        expired, and must not stand in for the purchase."""
        ch, p, pw = paid
        former = make_user()
        join(space, former)
        db.add(Enrollment(
            id=_uid("en"), user_id=former.id, pathway_id=pw.id,
            status="active",
        ))
        db.commit()

        _assert_all(_surfaces(as_user(former), space, ch, p), False)


class TestGatherings:
    @pytest.fixture
    def setup(self, db, space, channel, link, post, make_event):
        event = make_event(space=space)
        ch = channel(kind="gathering")
        link(ch, event=event)
        p = post(ch)
        db.commit()
        return ch, p, event

    def test_a_confirmed_booking_opens_it(
        self, db, space, setup, join, make_user, as_user,
    ):
        ch, p, event = setup
        attendee = make_user()
        join(space, attendee)
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        ))
        db.commit()

        _assert_all(_surfaces(as_user(attendee), space, ch, p), True)

    def test_a_checkout_hold_does_not(
        self, db, space, setup, join, make_user, as_user,
    ):
        """Starting Stripe Checkout is never participation."""
        ch, p, event = setup
        shopper = make_user()
        join(space, shopper)
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=shopper.id,
            status=BookingStatus.pending_payment, source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=20),
        ))
        db.commit()

        _assert_all(_surfaces(as_user(shopper), space, ch, p), False)

    def test_membership_survives_the_gathering_finishing(
        self, db, space, setup, join, make_user, as_user,
    ):
        """§2 persistence, asserted through the endpoints."""
        ch, p, event = setup
        attendee = make_user()
        join(space, attendee)
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        ))
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=attendee.id,
            role="member", source="experience", status="active",
        ))
        event.starts_at = datetime.utcnow() - timedelta(days=60)
        event.ends_at = datetime.utcnow() - timedelta(days=60)
        db.commit()

        _assert_all(_surfaces(as_user(attendee), space, ch, p), True)

    def test_membership_survives_unlinking(
        self, db, space, setup, join, make_user, as_user,
    ):
        ch, p, event = setup
        attendee = make_user()
        join(space, attendee)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=attendee.id,
            role="member", source="experience", status="active",
        ))
        db.query(ChannelExperienceLink).filter(
            ChannelExperienceLink.channel_id == ch.id,
        ).delete()
        db.commit()

        _assert_all(_surfaces(as_user(attendee), space, ch, p), True)


class TestSeries:
    def test_a_valid_pass_opens_it(
        self, db, space, channel, link, post, join, make_user, as_user,
    ):
        series = EventSeries(
            id=_uid("es"), space_id=space.id, title="Term",
            slug=f"term-{uuid.uuid4().hex[:6]}", starts_at=datetime.utcnow(),
        )
        db.add(series)
        db.flush()
        ch = channel(kind="series")
        link(ch, series=series)
        p = post(ch)
        holder = make_user()
        join(space, holder)
        db.add(AccessPass(
            id=_uid("ap"), user_id=holder.id, space_id=space.id,
            eligible_series_id=series.id, status=AccessPassStatus.active,
            pass_type=AccessPassType.term_pass,
        ))
        db.commit()

        _assert_all(_surfaces(as_user(holder), space, ch, p), True)


class TestCreatorControl:
    """§2 and §4 — the creator decides, and that decision holds."""

    @pytest.fixture
    def setup(self, db, space, channel, link, free_pathway, post):
        ch = channel()
        link(ch, pathway=free_pathway)
        p = post(ch)
        db.commit()
        return ch, p

    def test_a_creator_added_member_needs_no_experience(
        self, db, space, setup, join, make_user, as_user,
    ):
        ch, p = setup
        guest = make_user()
        join(space, guest)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=guest.id,
            role="member", source="manual", status="active",
        ))
        db.commit()

        _assert_all(_surfaces(as_user(guest), space, ch, p), True)

    def test_a_removed_member_is_refused_everywhere(
        self, db, space, setup, free_pathway, join, make_user, as_user,
    ):
        """Removed while still qualifying through the Pathway."""
        ch, p = setup
        removed = make_user()
        join(space, removed)
        db.add(Enrollment(
            id=_uid("en"), user_id=removed.id,
            pathway_id=free_pathway.id, status="active",
        ))
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=ch.id, user_id=removed.id,
            role="member", source="experience", status="removed",
            removed_reason="creator", removed_at=datetime.utcnow(),
        ))
        db.commit()

        _assert_all(_surfaces(as_user(removed), space, ch, p), False)

    def test_the_owner_reaches_their_own_channel(
        self, db, space, setup, owner, as_user,
    ):
        ch, p = setup
        _assert_all(_surfaces(as_user(owner), space, ch, p), True)

    def test_a_moderator_does_too(
        self, db, space, setup, join, make_user, as_user,
    ):
        ch, p = setup
        mod = make_user()
        join(space, mod, role=SpaceRole.moderator)
        db.commit()
        _assert_all(_surfaces(as_user(mod), space, ch, p), True)


class TestPlatformAdministrator:
    """§3 and §4 — no member-facing reach into restricted channels."""

    def test_a_restricted_channel_stays_shut(
        self, db, space, channel, link, free_pathway, post, join,
        make_user, as_user,
    ):
        ch = channel()
        link(ch, pathway=free_pathway)
        p = post(ch)
        admin = make_user(role="admin")
        join(space, admin)
        db.commit()

        _assert_all(_surfaces(as_user(admin), space, ch, p), False)

    def test_an_open_channel_still_answers(
        self, db, space, post, join, make_user, as_user,
    ):
        """Administration, Creator Studio and Community Care read
        these; nothing is withheld in them anyway."""
        ch = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Common Room",
            slug=f"common-{uuid.uuid4().hex[:6]}", channel_type="open",
            member_posting_allowed=True,
        )
        db.add(ch)
        db.flush()
        p = post(ch)
        admin = make_user(role="admin")
        join(space, admin)
        db.commit()

        surfaces = _surfaces(as_user(admin), space, ch, p)
        assert surfaces["in_list"] is True
        assert surfaces["feed"] is True
        assert surfaces["post_detail"] is True
