"""From publishing a post to the provider call, in one pass.

The gap this closes
-------------------
The earlier suite stopped at recipient resolution and template
rendering, and I said so at the time. Delivery then failed in
production and those tests stayed green, because everything they
asserted was working — the event, the audience, the email body. What
nothing covered was the stretch between "an intent exists" and
"Resend was called", which is where the failure lived.

So these drive the whole path: an HTTP post, the event it writes,
routing, intent creation, dispatch, and the provider's ``send``
replaced with a stub that records what it was handed. The assertion
that matters is that the stub was called at all.

The outbound guard is deliberately part of the path. It refuses
RFC-reserved recipients in *every* environment, production included,
because such a send can only hard-bounce — so a Collective whose
members all use ``@example.com`` produces intents and no email, with
nothing in the provider dashboard. That is the guard working, not
failing, and it is asserted here so the distinction is legible.
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_user,
    get_optional_user,
    get_verified_current_user,
)
from app.comms.intents import STATE_QUEUED, STATE_SENT
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.db.session import get_db
from app.main import app
from app.models.platform import (
    ConversationChannel,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def sent(monkeypatch):
    """Replace the Resend SDK with a recorder.

    conftest installs a tripwire over the real SDK, so a send that
    escaped this stub would raise rather than reach the network.
    """
    calls: list[dict] = []

    def _stub_send(req, *args, **kwargs):
        # The provider calls ``send(request)`` or ``send(request,
        # options)`` depending on configuration, so the stub has to
        # accept both — a one-argument stub fails as a TypeError that
        # the dispatcher records as a provider error, which looks
        # exactly like a delivery failure.
        calls.append(req)
        return {"id": f"re_{uuid.uuid4().hex[:10]}"}

    # Patch the real SDK's send, which is both what the provider calls
    # and what conftest's tripwire guards — replacing
    # ``sys.modules["resend"]`` does not take effect, because the
    # provider's ``import resend`` resolves to the already-imported
    # module object.
    import resend
    monkeypatch.setattr(resend.Emails, "send", _stub_send)
    from app.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "resend_api_key", "test-key",
                        raising=False)
    monkeypatch.setattr(_cfg.settings, "email_from", "hello@freshcollective.au",
                        raising=False)
    # Production, so the guard's non-production layer stands aside and
    # the reserved-domain layer is the only one that can fire — exactly
    # the shape of the live environment.
    monkeypatch.setattr(_cfg.settings, "app_env", "production", raising=False)
    return calls


@pytest.fixture
def community_email_default(db):
    """Set the ``(community, email_transactional)`` channel default.

    The production failure was this row seeded ``default_enabled =
    false`` by migration 097, so every member without an explicit
    preference resolved to ``silent`` and the intent was created
    ``recorded`` — nothing to send, nothing in Resend.

    The tests set it rather than relying on whichever value the test
    database happens to hold, so both directions can be asserted and
    neither depends on migration state.
    """
    from sqlalchemy import text

    def _set(enabled: bool):
        db.execute(text("""
            UPDATE communication_channel_defaults
            SET default_enabled = :enabled
            WHERE category_key = 'community'
              AND channel = 'email_transactional'
        """), {"enabled": enabled})
        db.flush()
    return _set


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


@pytest.fixture
def channel(db, space):
    row = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Moonlit Circle",
        slug=f"moonlit-{uuid.uuid4().hex[:8]}", channel_type="open",
        member_posting_allowed=True,
    )
    db.add(row)
    db.flush()
    return row


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


def _publish(client, space, ch, body="A note for the circle"):
    r = client.post(
        f"/api/spaces/{space.slug}/community",
        json={"body": body, "channel_slug": ch.slug},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _route_and_dispatch(db, post_id):
    """Run what the request's background task runs.

    TestClient executes background tasks, but ``_route_event_bg``
    opens its own ``SessionLocal`` — which in the suite is a separate
    transaction that cannot see this test's uncommitted rows. So the
    same two steps are driven here against the test session instead,
    which is the code under test either way.
    """
    from app.comms.intents import DELIVERY_MODE_LIVE, STATE_RECORDED
    from app.comms.routing import route_event
    from app.comms.worker import dispatch_specific_intent

    event = (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == "community.post.published",
            CommunicationEvent.subject_id == post_id,
        )
        .one()
    )
    from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL

    result = route_event(db, event, delivery_mode=DELIVERY_MODE_LIVE)
    db.flush()
    dispatched = []
    for intent_id in result.intent_ids:
        intent = db.get(CommunicationIntent, intent_id)
        if intent is None or intent.state != STATE_QUEUED:
            continue
        # Email only. The in-app intent writes a `notifications` row,
        # which trips a foreign key under this suite's savepoint
        # fixtures and leaves the session unusable for the dispatch
        # that follows it — so dispatching it here would make these
        # tests fail for a reason that has nothing to do with email.
        # In-app delivery has its own coverage.
        if intent.channel != CHANNEL_EMAIL_TRANSACTIONAL:
            continue
        dispatch_specific_intent(db, intent_id)
        db.flush()
        dispatched.append(intent_id)
    return event, result, dispatched


class TestTheWholePath:
    def test_a_deliverable_member_reaches_the_provider(
        self, db, space, channel, join, kelly, make_user, as_user, sent,
        community_email_default,
    ):
        """The assertion the earlier suite was missing."""
        community_email_default(True)
        member = make_user(email=f"m{uuid.uuid4().hex[:8]}@freshcollective.au")
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, channel)
        _, result, dispatched = _route_and_dispatch(db, post["id"])

        assert result.intent_ids, "routing produced no intents"
        assert dispatched, "no intent was dispatched"
        assert len(sent) >= 1, (
            "nothing reached the provider — this is the production "
            "failure the suite used to miss"
        )

        req = sent[0]
        assert req["to"] == [member.email]
        assert "Kelly" in req["subject"]
        assert "Moonlit Circle" in req["subject"]
        assert "View Conversation" in req["html"]
        assert f"/community/{post['id']}" in req["html"]

    def test_the_intent_is_marked_sent(
        self, db, space, channel, join, kelly, make_user, as_user, sent,
        community_email_default,
    ):
        community_email_default(True)
        member = make_user(email=f"m{uuid.uuid4().hex[:8]}@freshcollective.au")
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, channel)
        _, _, dispatched = _route_and_dispatch(db, post["id"])

        states = {
            db.get(CommunicationIntent, i).state for i in dispatched
        }
        assert STATE_SENT in states, f"states were {states}"


@pytest.fixture
def guard_as_in_production(monkeypatch):
    """Make the outbound guard behave as it does in production.

    Layer 1 of the guard steps aside inside a test process — on
    purpose, because the suite is protected at the SDK boundary
    instead, and the comms tests legitimately drive dispatch against
    their own stub. That means the reserved-domain layer never fires
    under pytest, so without this the production behaviour cannot be
    asserted at all.

    Safe to do here because the Resend SDK is already replaced by the
    recording stub, which is the only egress these tests have.
    """
    from app.comms import delivery_guard

    monkeypatch.setattr(
        delivery_guard, "running_in_test_process", lambda: False,
    )


class TestReservedRecipientsProduceNoEmail:
    """The cause worth naming, because it looks identical to a bug."""

    def test_an_example_com_member_gets_an_intent_and_no_send(
        self, db, space, channel, join, kelly, make_user, as_user, sent,
        community_email_default, guard_as_in_production,
    ):
        community_email_default(True)
        tester = make_user(email=f"t{uuid.uuid4().hex[:8]}@example.com")
        join(space, tester)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, channel)
        _, result, _ = _route_and_dispatch(db, post["id"])

        assert result.intent_ids, (
            "the recipient resolved and an intent was created — the "
            "pipeline is working"
        )
        assert sent == [], (
            "a reserved domain can only hard-bounce, so no send is "
            "correct; nothing appears in the provider dashboard"
        )

    def test_the_guard_classifies_reserved_domains(self):
        """``outbound_email_block`` itself defers inside a test process
        — layer 1, deliberately, because the suite is guarded at the
        SDK boundary instead. So the classification is asserted
        through ``is_reserved_recipient``, which is the part that runs
        identically in production.
        """
        from app.comms.delivery_guard import is_reserved_recipient

        for addr in (
            "t@example.com", "t@example.test", "t@example.invalid",
            "t@fc.localhost",
        ):
            assert is_reserved_recipient(addr) is True, addr
        assert is_reserved_recipient("kelly@freshcollective.au") is False

    def test_a_mixed_collective_mails_only_the_deliverable_member(
        self, db, space, channel, join, kelly, make_user, as_user, sent,
        community_email_default, guard_as_in_production,
    ):
        community_email_default(True)
        real = make_user(email=f"r{uuid.uuid4().hex[:8]}@freshcollective.au")
        tester = make_user(email=f"t{uuid.uuid4().hex[:8]}@example.test")
        for m in (real, tester):
            join(space, m)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, channel)
        _, result, _ = _route_and_dispatch(db, post["id"])

        assert len(result.intent_ids) >= 2, "both members should resolve"
        recipients = [r["to"][0] for r in sent]
        assert real.email in recipients
        assert tester.email not in recipients


class TestIneligibleMembersGetNothing:
    def test_a_private_channel_does_not_mail_the_collective(
        self, db, space, join, kelly, make_user, as_user, sent,
        community_email_default,
    ):
        community_email_default(True)
        from app.models.platform import ChannelMembership

        private = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Inner Circle",
            slug=f"inner-{uuid.uuid4().hex[:8]}", channel_type="private",
            member_posting_allowed=True,
        )
        db.add(private)
        db.flush()

        inside = make_user(email=f"i{uuid.uuid4().hex[:8]}@freshcollective.au")
        outside = make_user(email=f"o{uuid.uuid4().hex[:8]}@freshcollective.au")
        for m in (inside, outside):
            join(space, m)
        join(space, kelly, role=SpaceRole.creator)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=private.id, user_id=inside.id,
            role="member", source="manual", status="active",
        ))
        db.commit()

        post = _publish(as_user(kelly), space, private)
        _route_and_dispatch(db, post["id"])

        recipients = [r["to"][0] for r in sent]
        assert inside.email in recipients
        assert outside.email not in recipients, (
            "an excerpt of a private conversation was mailed to a "
            "Collective member who cannot open it"
        )

    def test_the_author_is_never_mailed(
        self, db, space, channel, join, kelly, make_user, as_user, sent,
        community_email_default,
    ):
        community_email_default(True)
        member = make_user(email=f"m{uuid.uuid4().hex[:8]}@freshcollective.au")
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, channel)
        _route_and_dispatch(db, post["id"])

        assert kelly.email not in [r["to"][0] for r in sent]


class TestProviderFailureIsContained:
    def test_a_provider_error_does_not_lose_the_post(
        self, db, space, channel, join, kelly, make_user, as_user,
        monkeypatch, community_email_default,
    ):
        """§5 — a failed email must not unpublish or duplicate a post."""
        from app.core import config as _cfg
        from app.models.platform import CommunityPost

        def _boom(req, *args, **kwargs):
            raise RuntimeError("provider unavailable")

        import resend
        monkeypatch.setattr(resend.Emails, "send", _boom)
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "k",
                            raising=False)
        monkeypatch.setattr(_cfg.settings, "email_from",
                            "hello@freshcollective.au", raising=False)
        monkeypatch.setattr(_cfg.settings, "app_env", "production",
                            raising=False)
        community_email_default(True)

        member = make_user(email=f"m{uuid.uuid4().hex[:8]}@freshcollective.au")
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, channel)
        _route_and_dispatch(db, post["id"])

        rows = (
            db.query(CommunityPost)
            .filter(CommunityPost.id == post["id"])
            .all()
        )
        assert len(rows) == 1, "the post must not be duplicated"
        assert rows[0].publication_status == "published", (
            "the post must not disappear because an email failed"
        )

    def test_dispatch_is_idempotent_per_intent(
        self, db, space, channel, join, kelly, make_user, as_user, sent,
        community_email_default,
    ):
        """A retry must not send twice."""
        community_email_default(True)
        from app.comms.worker import dispatch_specific_intent

        member = make_user(email=f"m{uuid.uuid4().hex[:8]}@freshcollective.au")
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()

        post = _publish(as_user(kelly), space, channel)
        _, _, dispatched = _route_and_dispatch(db, post["id"])
        first = len(sent)

        for intent_id in dispatched:
            try:
                dispatch_specific_intent(db, intent_id)
            except Exception:
                # The dispatcher guards on state and may refuse a
                # non-queued intent outright. Refusing is the correct
                # outcome; sending again is not.
                pass
        assert len(sent) == first, "a second dispatch sent the email again"


class TestTheProductionCause:
    """The failure, reproduced, and the fix that resolves it.

    Migration 097 seeded ``(community, email_transactional)`` with
    ``default_enabled = false``. ``get_effective_preference`` resolves
    a disabled default to ``silent``, and the decision pipeline creates
    a *recorded* intent for a silent preference — a row stating there
    was nothing to send. So the event existed, an intent existed, the
    recipient was correct, the template rendered, and no email was ever
    handed to Resend.

    Migration 178 flips that one boolean. These two tests are the same
    scenario either side of it.
    """

    @pytest.fixture
    def scenario(self, db, space, channel, join, kelly, make_user, as_user):
        member = make_user(email=f"m{uuid.uuid4().hex[:8]}@freshcollective.au")
        join(space, member)
        join(space, kelly, role=SpaceRole.creator)
        db.commit()
        return member

    def test_with_the_default_off_nothing_is_sent(
        self, db, space, channel, kelly, as_user, sent, scenario,
        community_email_default, guard_as_in_production,
    ):
        community_email_default(False)
        post = _publish(as_user(kelly), space, channel)
        _, result, dispatched = _route_and_dispatch(db, post["id"])

        from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL

        email_intents = [
            db.get(CommunicationIntent, i) for i in result.intent_ids
        ]
        email_intents = [
            i for i in email_intents
            if i is not None and i.channel == CHANNEL_EMAIL_TRANSACTIONAL
        ]
        assert email_intents, "an intent is still created"
        assert email_intents[0].state == "recorded", (
            "a silent preference records rather than queues — which is "
            "why routing looked healthy while nothing sent"
        )
        assert dispatched == [], "nothing queued, so nothing dispatched"
        assert sent == [], "and nothing reached the provider"

    def test_with_the_default_on_the_email_is_sent(
        self, db, space, channel, kelly, as_user, sent, scenario,
        community_email_default, guard_as_in_production,
    ):
        community_email_default(True)
        post = _publish(as_user(kelly), space, channel)
        _, _, dispatched = _route_and_dispatch(db, post["id"])

        assert dispatched, "the intent is queued and dispatched"
        assert len(sent) == 1
        assert sent[0]["to"] == [scenario.email]

    def test_an_explicit_opt_out_still_wins_after_the_fix(
        self, db, space, channel, kelly, as_user, sent, scenario,
        community_email_default, guard_as_in_production,
    ):
        """Turning the default on must not override anybody's choice."""
        from app.comms.categories import (
            CATEGORY_COMMUNITY, CHANNEL_EMAIL_TRANSACTIONAL,
        )
        from app.comms.preferences import set_preference

        community_email_default(True)
        set_preference(
            db, user_id=scenario.id, category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority="silent",
        )
        db.flush()

        post = _publish(as_user(kelly), space, channel)
        _route_and_dispatch(db, post["id"])

        assert sent == [], (
            "an opted-out member was emailed because the category "
            "default changed"
        )
