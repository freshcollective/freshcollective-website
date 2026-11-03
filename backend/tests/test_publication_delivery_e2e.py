"""Publication announcements, all the way to the provider.

The Conversations failure was an event and an intent existing while
nothing reached Resend, and the tests stayed green because they
stopped short of dispatch. These do not stop short: the Resend SDK is
replaced by a recorder and the assertion that matters is that it was
called.

Covers `gathering.published`, `series.published` and
`pathway.published`, through:

    publication → event → resolver → preference → intent
                → template → outbound guard → provider

The harness mirrors `test_creator_post_delivery_e2e.py`, including the
two things that were easy to get wrong there: the stub must accept
`send(req, options)` as well as `send(req)`, and the outbound guard
defers inside a test process unless told otherwise.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.comms.intents import STATE_QUEUED, STATE_SENT
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.models.platform import (
    EventSeries,
    Pathway,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import publication_announcement as pub


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    def _stub_send(req, *args, **kwargs):
        # Both call shapes — the provider passes options when
        # configured, and a one-argument stub fails as a TypeError the
        # dispatcher records as a provider error.
        calls.append(req)
        return {"id": f"re_{uuid.uuid4().hex[:10]}"}

    import resend
    monkeypatch.setattr(resend.Emails, "send", _stub_send)

    from app.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "resend_api_key", "k", raising=False)
    monkeypatch.setattr(
        _cfg.settings, "email_from", "hello@freshcollective.au", raising=False,
    )
    monkeypatch.setattr(_cfg.settings, "app_env", "production", raising=False)
    return calls


@pytest.fixture
def guard_as_in_production(monkeypatch):
    """The guard's first layer stands aside inside a test process, so
    the reserved-domain rule never fires without this."""
    from app.comms import delivery_guard

    monkeypatch.setattr(
        delivery_guard, "running_in_test_process", lambda: False,
    )


@pytest.fixture
def kelly(make_user):
    return make_user(role="creator", name="Kelly")


@pytest.fixture
def space(make_space, kelly):
    return make_space(creator=kelly, name="Moonlit Circle")


@pytest.fixture
def member(db, space, make_user):
    who = make_user(email=f"m{uuid.uuid4().hex[:8]}@freshcollective.au")
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=who.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    db.flush()
    return who


@pytest.fixture
def creator_is_a_member(db, space, kelly):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=kelly.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    db.flush()


def _dispatch(db, event: CommunicationEvent):
    """Route the event and dispatch its email intent.

    Email only: the in-app intent writes a `notifications` row that
    trips a foreign key under this suite's savepoint fixtures and
    leaves the session unusable for the dispatch after it. In-app has
    its own coverage.
    """
    from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
    from app.comms.intents import DELIVERY_MODE_LIVE
    from app.comms.routing import route_event
    from app.comms.worker import dispatch_specific_intent

    result = route_event(db, event, delivery_mode=DELIVERY_MODE_LIVE)
    db.flush()
    dispatched = []
    for intent_id in result.intent_ids:
        intent = db.get(CommunicationIntent, intent_id)
        if intent is None or intent.state != STATE_QUEUED:
            continue
        if intent.channel != CHANNEL_EMAIL_TRANSACTIONAL:
            continue
        dispatch_specific_intent(db, intent_id)
        db.flush()
        dispatched.append(intent_id)
    return result, dispatched


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@pytest.fixture
def published_gathering(db, space, make_event, kelly, creator_is_a_member):
    gathering = make_event(
        space=space, is_published=True, title="November Circle",
        venue_locality="South Croydon, VIC",
    )
    db.flush()
    event = pub.announce_gathering_if_newly_published(
        db, gathering, actor_user_id=kelly.id,
    )
    assert event is not None
    db.commit()
    return gathering, event


@pytest.fixture
def published_series(db, space, kelly, creator_is_a_member):
    series = EventSeries(
        id=_uid("es"), space_id=space.id, title="Autumn Term",
        slug=f"term-{uuid.uuid4().hex[:8]}",
        starts_at=datetime.utcnow() + timedelta(days=7),
        status="published", published_at=datetime.utcnow(),
    )
    db.add(series)
    db.flush()
    event = pub.announce_series_if_newly_published(
        db, series, actor_user_id=kelly.id,
    )
    assert event is not None
    db.commit()
    return series, event


@pytest.fixture
def published_pathway(db, space, kelly, creator_is_a_member):
    from app.services.pathway_announcement import announce_if_newly_available

    pathway = Pathway(
        id=_uid("pw"), space_id=space.id, title="Know Yourself",
        slug=f"ky-{uuid.uuid4().hex[:8]}",
        status="active", access_type="free",
    )
    db.add(pathway)
    db.flush()
    event = announce_if_newly_available(db, pathway, actor_user_id=kelly.id)
    assert event is not None
    db.commit()
    return pathway, event


# ---------------------------------------------------------------------------
# The chain, per announcement
# ---------------------------------------------------------------------------


class TestGatheringReachesTheProvider:
    def test_the_email_is_handed_to_resend(
        self, db, space, member, published_gathering, sent,
    ):
        _gathering, event = published_gathering
        result, dispatched = _dispatch(db, event)

        assert result.intent_ids, "routing produced no intents"
        assert dispatched, "no email intent was dispatched"
        assert len(sent) == 1, (
            "nothing reached the provider — the gap that hid the "
            "Conversations failure"
        )
        req = sent[0]
        assert req["to"] == [member.email]
        assert "November Circle" in req["subject"]
        assert "Moonlit Circle" in req["html"]

    def test_the_intent_is_marked_sent(
        self, db, member, published_gathering, sent,
    ):
        _gathering, event = published_gathering
        _result, dispatched = _dispatch(db, event)
        states = {db.get(CommunicationIntent, i).state for i in dispatched}
        assert STATE_SENT in states, states

    def test_the_merge_fields_are_populated(
        self, db, member, published_gathering, sent,
    ):
        _gathering, event = published_gathering
        _dispatch(db, event)
        html = sent[0]["html"]
        assert "South Croydon, VIC" in html, "the public locality is missing"
        assert "Book Your Place" in html or "View Gathering" in html

    def test_the_link_points_at_the_real_route(
        self, db, space, member, published_gathering, sent,
    ):
        gathering, event = published_gathering
        _dispatch(db, event)
        assert f"/spaces/{space.slug}/events/{gathering.id}" in sent[0]["html"]

        from pathlib import Path

        route = (
            Path(__file__).resolve().parent.parent.parent / "frontend"
            / "src" / "app" / "spaces" / "[slug]" / "events" / "[eventId]"
            / "page.tsx"
        )
        assert route.exists(), f"no Next route for the CTA — {route}"

    def test_the_creator_is_not_emailed(
        self, db, kelly, member, published_gathering, sent,
    ):
        _gathering, event = published_gathering
        _dispatch(db, event)
        assert kelly.email not in [r["to"][0] for r in sent]

    def test_the_event_sits_on_the_gatherings_category(self):
        from app.comms.categories import TOPIC_TO_CATEGORY
        from app.comms.registry import get_event_definition

        for event_type in ("gathering.published", "series.published"):
            definition = get_event_definition(event_type)
            assert definition is not None, event_type
            assert TOPIC_TO_CATEGORY[definition.topic] == "gatherings"


class TestSeriesReachesTheProvider:
    def test_one_email_for_the_whole_term(
        self, db, space, member, published_series, sent,
    ):
        series, event = published_series
        _result, dispatched = _dispatch(db, event)
        assert dispatched
        assert len(sent) == 1
        assert "Autumn Term" in sent[0]["subject"]

    def test_the_link_points_at_the_series_page(
        self, db, space, member, published_series, sent,
    ):
        series, event = published_series
        _dispatch(db, event)
        assert (
            f"/spaces/{space.slug}/gathering-series/{series.slug}"
            in sent[0]["html"]
        )

        from pathlib import Path

        route = (
            Path(__file__).resolve().parent.parent.parent / "frontend"
            / "src" / "app" / "spaces" / "[slug]" / "gathering-series"
            / "[series-slug]" / "page.tsx"
        )
        assert route.exists(), f"no Next route for the CTA — {route}"

    def test_thirty_occurrences_add_no_further_emails(
        self, db, space, member, published_series, make_event, kelly, sent,
    ):
        """The headline guarantee, asserted at the provider."""
        series, event = published_series
        for _ in range(30):
            occurrence = make_event(space=space, is_published=True)
            occurrence.series_id = series.id
            db.flush()
            assert pub.announce_gathering_if_newly_published(
                db, occurrence, actor_user_id=kelly.id,
            ) is None

        _dispatch(db, event)
        assert len(sent) == 1, (
            f"{len(sent)} emails for one term of thirty sessions"
        )


class TestPathwayReachesTheProvider:
    def test_the_email_is_handed_to_resend(
        self, db, space, member, published_pathway, sent,
    ):
        pathway, event = published_pathway
        _result, dispatched = _dispatch(db, event)
        assert dispatched, (
            "no email intent — this is what migration 179 fixed"
        )
        assert len(sent) == 1
        assert f"/spaces/{space.slug}/pathways/{pathway.slug}" in sent[0]["html"]

    def test_the_provider_gets_a_pressable_button(
        self, db, space, member, published_pathway, sent, monkeypatch,
    ):
        """The path alone appearing in the HTML is what this assertion
        used to settle for, and an absolute URL contains the path as a
        substring — so the relative ``href`` that reached a member's
        inbox passed it. Parsed out of the handed-over HTML instead."""
        import re

        from app.core.config import settings

        monkeypatch.setattr(
            settings, "public_app_url", "https://freshcollective.au",
            raising=False,
        )
        pathway, event = published_pathway
        _dispatch(db, event)

        html = sent[0]["html"]
        button = re.search(
            r'<a href="([^"]*)"\s+style="[^"]*linear-gradient[^"]*">'
            r'\s*([^<]+?)\s*</a>',
            html, re.S,
        )
        assert button, "no CTA button in the email handed to Resend"
        href, label = button.group(1), button.group(2).strip()
        assert label == "Explore Pathway", label
        assert href == (
            f"https://freshcollective.au/spaces/{space.slug}"
            f"/pathways/{pathway.slug}"
        ), href

        copied = re.search(
            r"or copy this link:<br />\s*<span[^>]*>([^<]*)</span>", html, re.S,
        )
        assert copied and copied.group(1).strip() == href, (
            "the fallback link does not match the button"
        )
        assert href in sent[0]["text"], "the plain-text body lost the link"

    def test_the_creator_is_not_emailed(
        self, db, kelly, member, published_pathway, sent,
    ):
        """Part D's correction, asserted at the provider."""
        _pathway, event = published_pathway
        _dispatch(db, event)
        assert kelly.email not in [r["to"][0] for r in sent]


# ---------------------------------------------------------------------------
# The gates between an intent and an email
# ---------------------------------------------------------------------------


class TestOptOutsAreRespected:
    def test_a_silent_preference_sends_nothing(
        self, db, space, member, published_gathering, sent,
    ):
        from app.comms.categories import (
            CATEGORY_GATHERINGS, CHANNEL_EMAIL_TRANSACTIONAL,
        )
        from app.comms.preferences import set_preference

        set_preference(
            db, user_id=member.id, category_key=CATEGORY_GATHERINGS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority="silent",
        )
        db.flush()

        _gathering, event = published_gathering
        _dispatch(db, event)
        assert sent == [], "an opted-out member was emailed"


class TestTheOutboundGuard:
    def test_a_reserved_domain_does_not_reach_the_provider(
        self, db, space, make_event, make_user, kelly, sent,
        guard_as_in_production, creator_is_a_member,
    ):
        """Intents are created; no email leaves. Looks identical to a
        bug unless it is named."""
        tester = make_user(email=f"t{uuid.uuid4().hex[:8]}@example.com")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=tester.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        gathering = make_event(space=space, is_published=True)
        db.flush()
        event = pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        )
        db.commit()

        result, _dispatched = _dispatch(db, event)
        assert result.intent_ids, "the pipeline still ran"
        assert sent == []


class TestIdempotency:
    def test_routing_the_same_event_twice_sends_once(
        self, db, member, published_gathering, sent,
    ):
        """A real retry loads the event again, so this does too — and
        re-using the first pass's ORM instance made the test fail on
        an expired identity rather than on the behaviour."""
        _gathering, event = published_gathering
        event_id = event.id
        _dispatch(db, event)
        first = len(sent)
        assert first == 1
        db.commit()

        # The second pass collides with the intent's dedupe constraint,
        # which is what makes repeated processing safe — and the
        # rollback that follows is why the event has to be committed
        # and reloaded rather than carried over from the first pass.
        again = db.get(CommunicationEvent, event_id)
        assert again is not None, "the event vanished between passes"
        try:
            _dispatch(db, again)
        except Exception:
            # A collision is an acceptable outcome; sending twice is
            # not. That is what the assertion below checks.
            db.rollback()
        assert len(sent) == first, "a repeated event sent again"

    def test_dispatching_the_same_intent_twice_sends_once(
        self, db, member, published_gathering, sent,
    ):
        from app.comms.worker import dispatch_specific_intent

        _gathering, event = published_gathering
        _result, dispatched = _dispatch(db, event)
        first = len(sent)
        for intent_id in dispatched:
            try:
                dispatch_specific_intent(db, intent_id)
            except Exception:
                # The dispatcher guards on state and may refuse a
                # non-queued intent. Refusing is correct; sending again
                # is not.
                pass
        assert len(sent) == first


class TestAFailedSendDoesNotUndoThePublication:
    def test_the_gathering_stays_published(
        self, db, space, make_event, member, kelly, monkeypatch,
        creator_is_a_member,
    ):
        import resend
        from app.core import config as _cfg
        from app.models.platform import Event

        def _boom(req, *args, **kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr(resend.Emails, "send", _boom)
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "k", raising=False)
        monkeypatch.setattr(
            _cfg.settings, "email_from", "hello@freshcollective.au",
            raising=False,
        )
        monkeypatch.setattr(
            _cfg.settings, "app_env", "production", raising=False,
        )

        gathering = make_event(space=space, is_published=True)
        db.flush()
        event = pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        )
        db.commit()

        _dispatch(db, event)

        row = db.get(Event, gathering.id)
        assert row is not None
        assert row.is_published is True, (
            "a failed email unpublished the Gathering"
        )
        assert db.query(Event).filter(Event.id == gathering.id).count() == 1
