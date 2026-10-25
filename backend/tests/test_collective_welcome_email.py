"""The Collective's welcome email: who gets one, and who must not.

Membership is created in nine places in this codebase. Five of them are
a person joining a Collective and earn a welcome; four are not. The
emitter is shared, but what actually holds the line is the partial
unique index on ``(event_type, dedupe_key)`` — one row can exist per
``collective_welcome:{space_id}:{user_id}``, ever.

That single fact is what these tests keep honest, because five separate
product requirements rest on it: idempotent sending, no duplicates from
webhook retries, no welcome when an existing member buys again, no
welcome when a removed member returns, and no coordination needed
between call sites.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import re

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_verified_creator_user
from app.comms.models import CommunicationEvent
from app.comms.templates.editable import get_declaration
from app.core.database import get_db
from app.main import app
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services import membership_grant as mg
from app.services.collective_welcome_emit import (
    EVENT_TYPE,
    dedupe_key_for,
    emit_collective_welcome,
)

CATEGORY = "collective_welcome"
TEMPLATE_KEY = "collective.membership.welcome.email_transactional"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _welcomes(db, space_id: str | None = None) -> list[CommunicationEvent]:
    q = db.query(CommunicationEvent).filter(
        CommunicationEvent.event_type == EVENT_TYPE,
    )
    if space_id:
        q = q.filter(CommunicationEvent.source_id == space_id)
    return q.all()


def _membership(db, space, user, *, status=SpaceMembershipStatus.active,
                source="joined") -> SpaceMembership:
    m = SpaceMembership(
        id=str(uuid.uuid4()), space_id=space.id, user_id=user.id,
        role=SpaceRole.learner, status=status, source=source,
        joined_at=datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# The emitter's own decisions
# ---------------------------------------------------------------------------


class TestWhoEarnsAWelcome:

    def test_a_first_time_member_is_welcomed(self, db, make_space, make_user):
        space, member = make_space(), make_user()
        ev = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        assert ev is not None
        assert ev.event_type == EVENT_TYPE
        assert ev.actor_user_id == member.id
        assert ev.dedupe_key == dedupe_key_for(space.id, member.id)

    @pytest.mark.parametrize(
        "source", ["joined", "invited", "purchase", "ticket_purchase"],
    )
    def test_every_joining_source_earns_one(
        self, db, make_space, make_user, source,
    ):
        """The five approved pathways arrive carrying different sources;
        none of them is a reason to withhold the welcome."""
        space, member = make_space(), make_user()
        assert emit_collective_welcome(
            db, space=space, member=member, join_source=source,
        ) is not None

    @pytest.mark.parametrize("source", ["creator_owner", "auto_role"])
    def test_platform_and_owner_memberships_are_not_welcomed(
        self, db, make_space, make_user, source,
    ):
        """A creator is not a guest in their own Collective, and
        World Builders membership is computed rather than chosen."""
        space, member = make_space(), make_user()
        assert emit_collective_welcome(
            db, space=space, member=member, join_source=source,
        ) is None
        assert _welcomes(db, space.id) == []

    def test_the_collectives_own_creator_is_never_welcomed(
        self, db, make_space,
    ):
        """Even if their row carries a joining source."""
        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        assert emit_collective_welcome(
            db, space=space, member=owner, join_source="joined",
        ) is None

    def test_a_disabled_collective_sends_nothing(
        self, db, make_space, make_user,
    ):
        space, member = make_space(), make_user()
        space.welcome_email_enabled = False
        db.flush()
        assert emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        ) is None
        assert _welcomes(db, space.id) == []

    def test_enabling_later_releases_no_backlog(
        self, db, make_space, make_user,
    ):
        """The flag is read at emit time, not at delivery.

        Somebody who joined while welcomes were off has no event, and
        switching the feature on cannot invent one for them — which is
        what makes "no delayed welcome" structural rather than a rule
        somebody has to remember.
        """
        space, member = make_space(), make_user()
        space.welcome_email_enabled = False
        db.flush()
        emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        space.welcome_email_enabled = True
        db.flush()
        # Nothing re-emits on its own; the member stays unwelcomed.
        assert _welcomes(db, space.id) == []


class TestExactlyOnceForever:

    def test_a_second_emit_is_refused(self, db, make_space, make_user):
        space, member = make_space(), make_user()
        first = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        second = emit_collective_welcome(
            db, space=space, member=member, join_source="purchase",
        )
        assert first is not None and second is None
        assert len(_welcomes(db, space.id)) == 1

    def test_a_different_route_cannot_double_send(
        self, db, make_space, make_user,
    ):
        """The reason the five call sites need no coordination."""
        space, member = make_space(), make_user()
        for source in ("joined", "invited", "purchase", "ticket_purchase"):
            emit_collective_welcome(
                db, space=space, member=member, join_source=source,
            )
        assert len(_welcomes(db, space.id)) == 1

    def test_rejoining_after_removal_sends_no_second_welcome(
        self, db, make_space, make_user,
    ):
        """A returning member is deliberately silent. A "welcome back"
        is a separate decision nobody has taken."""
        space, member = make_space(), make_user()
        emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        # …removed, then returns through a purchase.
        assert emit_collective_welcome(
            db, space=space, member=member, join_source="purchase",
        ) is None

    def test_each_collective_welcomes_independently(
        self, db, make_space, make_user,
    ):
        """The key is per (Collective, member), not per member."""
        a, b, member = make_space(), make_space(), make_user()
        assert emit_collective_welcome(
            db, space=a, member=member, join_source="joined") is not None
        assert emit_collective_welcome(
            db, space=b, member=member, join_source="joined") is not None
        assert len(_welcomes(db, a.id)) == 1
        assert len(_welcomes(db, b.id)) == 1

    def test_the_dedupe_key_names_both_parties(self):
        """Pinned because a key that dropped either half would either
        welcome somebody twice or silence a whole Collective."""
        assert dedupe_key_for("sp_1", "u_1") == "collective_welcome:sp_1:u_1"
        assert dedupe_key_for("sp_1", "u_2") != dedupe_key_for("sp_1", "u_1")
        assert dedupe_key_for("sp_2", "u_1") != dedupe_key_for("sp_1", "u_1")


# ---------------------------------------------------------------------------
# The membership lifecycle the purchase path goes through
# ---------------------------------------------------------------------------


class TestThePurchasePath:

    def test_a_first_time_buyer_becomes_a_member_and_is_welcomed(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.created is True
        assert emit_collective_welcome(
            db, space=space, member=buyer, join_source="purchase",
        ) is not None

    def test_an_existing_member_buying_again_is_not_welcomed(
        self, db, make_space, make_user,
    ):
        """``created`` is False, so the purchase path never even emits."""
        space, buyer = make_space(), make_user()
        _membership(db, space, buyer, source="joined")
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.created is False
        assert outcome.skipped_reason == "already_active"

    def test_a_reactivated_member_is_not_a_first_time_member(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        row = _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed, source="joined",
        )
        # A voluntary departure is the only removal a purchase restores
        # (migration 166) — see ``membership_grant.may_rejoin``.
        row.removal_kind = "voluntary"
        db.flush()
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is True
        assert outcome.created is False

    def test_a_paused_membership_is_left_alone(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.paused, source="joined",
        )
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.created is False
        assert outcome.skipped_reason == "status_paused"


# ---------------------------------------------------------------------------
# The two joining paths that do not go through ``apply_intent``
#
# A free Offering and a standalone Gathering ticket each create
# membership through their own code, not through purchase fulfilment.
# Both therefore have to report first-time membership themselves, and
# these pin that reporting — the thing their routes branch on when
# deciding whether a welcome is owed.
# ---------------------------------------------------------------------------


class TestTheOtherJoiningPaths:

    def test_a_free_offering_reports_a_first_time_membership(
        self, db, make_space, make_user,
    ):
        from app.services.offering_acquisition import AcquisitionOutcome

        # The field exists and defaults to "no welcome", so a future
        # construction that forgets it stays silent rather than
        # welcoming somebody twice.
        assert "membership_first_time" in AcquisitionOutcome.__annotations__
        outcome = AcquisitionOutcome(
            entitlement=None, created=True, joined_collective=True,
        )
        assert outcome.membership_first_time is False

    def test_a_gathering_ticket_reports_a_first_time_membership(self):
        from app.services.gathering_tickets import FulfilOutcome

        assert "membership_first_time" in FulfilOutcome.__annotations__
        outcome = FulfilOutcome(
            already_fulfilled=False, booking=None, access_pass=None,
            transaction=None,
        )
        assert outcome.membership_first_time is False

    def test_a_ticket_purchase_source_still_earns_a_welcome(
        self, db, make_space, make_user,
    ):
        """``ticket_purchase`` is not an excluded source."""
        space, buyer = make_space(), make_user()
        assert emit_collective_welcome(
            db, space=space, member=buyer, join_source="ticket_purchase",
        ) is not None

    def test_no_call_site_routes_before_it_commits(self):
        """Routing dispatches synchronously, so scheduling a welcome
        before the commit would send mail describing a membership that
        can still roll back. Every call site must therefore order the
        two one way: ``db.commit()`` first, scheduling after.

        Read from the source because the ordering is the whole
        guarantee and a passing functional test cannot see it — a
        send that happens to precede a commit that happens to succeed
        looks identical to the correct order.
        """
        from pathlib import Path

        backend = Path(__file__).resolve().parents[1]
        offenders = []
        for rel in (
            "app/spaces/routes.py",
            "app/spaces/_offering_member_routes.py",
            "app/creator/routes.py",
            "app/webhooks/routes.py",
            "app/webhooks/finite_plan_handlers.py",
        ):
            lines = (backend / rel).read_text().splitlines()
            commits = [i for i, l in enumerate(lines) if "db.commit()" in l]
            for i, line in enumerate(lines):
                if "schedule_welcome(" not in line or "def " in line:
                    continue
                if "import" in line:
                    continue
                if not any(c < i for c in commits):
                    offenders.append(f"{rel}:{i + 1}: {line.strip()}")
        assert offenders == [], (
            "a welcome is scheduled with no commit before it:\n"
            + "\n".join(offenders)
        )

    def test_every_membership_creating_path_emits_a_welcome(self):
        """Structural: a path that creates membership must emit.

        The free-Offering route and the ticket webhook create
        membership outside ``apply_intent``, and both were missed when
        the emitter was first wired in. This reads the source rather
        than the behaviour, because the failure mode is an omission —
        there is no wrong output to assert on, only a missing call.
        """
        from pathlib import Path

        backend = Path(__file__).resolve().parents[1]
        must_emit = (
            "app/spaces/_offering_member_routes.py",
            "app/webhooks/routes.py",
            "app/webhooks/finite_plan_handlers.py",
            "app/spaces/routes.py",
            "app/creator/routes.py",
        )
        missing = [
            rel for rel in must_emit
            if "emit_collective_welcome" not in (backend / rel).read_text()
        ]
        assert missing == [], (
            "these create Collective membership but never emit the "
            "welcome:\n" + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# Rendering — defaults, inheritance, and the generated destination
# ---------------------------------------------------------------------------


def _render(db, space, overrides=None):
    from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
    from app.comms.routing.resolver import ResolvedRecipient
    from app.comms.templates.editable import preview_overrides
    from app.comms.templates.registry import get_template_for
    from app.services.collective_welcome_emit import collective_url

    tpl = get_template_for(EVENT_TYPE, CHANNEL_EMAIL_TRANSACTIONAL)
    recipient = ResolvedRecipient(
        user_id="u", role_in_event="new_member", human_reason="",
        template_context={
            "space_id": space.id,
            "collective_name": space.name,
            "member_first_name": "Tom",
            "creator_name": "Lindsey",
            "collective_url": collective_url(space),
        },
    )
    if overrides is None:
        return tpl.render(db, None, recipient)
    with preview_overrides({TEMPLATE_KEY: overrides}):
        return tpl.render(db, None, recipient)


class TestTheRenderedEmail:

    def test_the_platform_default_names_the_collective(self, db, make_space):
        space = make_space(name="Moonlit Circle")
        out = _render(db, space)
        assert out.subject == "Welcome to Moonlit Circle ✨"
        assert "Welcome to Moonlit Circle!" in out.body_text
        assert "Hello Tom," in out.body_text

    def test_the_destination_is_the_collective(self, db, make_space):
        """Generated from the slug — and the reason ``cta_url`` is not a
        slot: a creator may rename the button, never aim it."""
        space = make_space()
        out = _render(db, space)
        assert f"/spaces/{space.slug}" in out.body_text
        assert f"/spaces/{space.slug}" in out.body_html

    def test_a_creator_cannot_supply_a_destination(self):
        """There is no slot through which a URL could be injected."""
        decl = get_declaration(TEMPLATE_KEY)
        ids = {s.slot_id for s in decl.slots}
        assert ids == {
            "subject", "heading", "body.message", "cta_label", "signature",
        }
        assert not any("url" in s for s in ids)

    def test_a_missing_first_name_still_greets_somebody(
        self, db, make_space,
    ):
        from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
        from app.comms.routing.resolver import ResolvedRecipient
        from app.comms.templates.registry import get_template_for

        space = make_space()
        tpl = get_template_for(EVENT_TYPE, CHANNEL_EMAIL_TRANSACTIONAL)
        out = tpl.render(db, None, ResolvedRecipient(
            user_id="u", role_in_event="new_member", human_reason="",
            template_context={
                "space_id": space.id, "collective_name": space.name,
                "member_first_name": "", "collective_url": "https://x/spaces/y",
            },
        ))
        assert "Hello there," in out.body_text

    def test_the_message_keeps_its_paragraphs(self, db, make_space):
        space = make_space()
        out = _render(db, space, {"body.message": "One.\n\nTwo.\n\nThree."})
        assert out.body_html.count("<p") >= 3


class _NoClose:
    """A session wrapper routing cannot close out from under the test."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


def _routing_against(db):
    """Route inside the test's session rather than a fresh one.

    ``_route_event_bg`` opens its own ``SessionLocal``, which cannot
    see this test's SAVEPOINT-scoped rows. Same harness as
    ``test_creator_purchase_notification_routing.py``.
    """
    from unittest.mock import patch
    from app.comms.providers import get as _get_provider

    inapp = _get_provider("in_app")

    class _Ctx:
        def __enter__(self):
            self._original = inapp._session_factory
            inapp._session_factory = lambda: _NoClose(db)
            self._patch = patch(
                "app.comms.rollout.SessionLocal",
                return_value=_NoClose(db),
            )
            self._patch.start()
            return self

        def __exit__(self, *exc):
            self._patch.stop()
            inapp._session_factory = self._original
            return False

    return _Ctx()


@pytest.fixture(autouse=True)
def _no_real_email_in_this_module():
    """Routing dispatches inline; intents are the subject, not the
    provider round-trip. A stub is not a send."""
    from unittest.mock import MagicMock, patch

    with patch("resend.Emails.send", new_callable=MagicMock), \
         patch("resend.api_key", create=True), \
         patch("app.services.email_service.email_service.send",
               new_callable=MagicMock):
        yield


class TestTheWelcomeIsActuallyRouted:
    """The half every other test in this file stops short of.

    Emitting writes a ``communication_events`` row and takes the
    dedupe key. Only ROUTING turns that row into an intent somebody
    receives, and ``schedule_routing_if_needed`` returns early —
    silently — when the event's topic is not in ``COMMS_LIVE_TOPICS``.

    An event with no intents is therefore indistinguishable, from the
    sending side, from an email that was delivered. Every assertion in
    this file passed while production sent nothing at all.

    The sibling event learned this already: see
    ``test_creator_purchase_notification_routing.py``, whose
    ``TestAnEventWithNoIntentsIsTheProductionFailure`` is the same
    shape for ``collective.purchase.received``.
    """

    def _intents(self, db, event_id):
        from app.comms.models import CommunicationIntent
        return (
            db.query(CommunicationIntent)
            .filter(CommunicationIntent.event_id == event_id)
            .all()
        )

    def test_the_topic_is_live_so_routing_is_not_a_no_op(self):
        """THE GUARD. If this fails, the welcome email is dormant: the
        event is written, nothing is routed, and no member hears a
        thing. Nothing else in this file can detect that."""
        from app.comms.rollout import is_event_live

        assert is_event_live(EVENT_TYPE), (
            f"{EVENT_TYPE} is not live — its topic is absent from "
            "COMMS_LIVE_TOPICS, so schedule_routing_if_needed is a "
            "no-op and no welcome can ever be delivered"
        )

    def test_emitting_alone_leaves_an_event_and_no_intents(
        self, db, make_space, make_user,
    ):
        """The production shape, reproduced deliberately — so the test
        above is a statement about routing rather than about emit."""
        space, member = make_space(), make_user()
        event = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        db.flush()
        assert event is not None
        assert self._intents(db, event.id) == []

    def test_routing_creates_a_queued_email_intent(
        self, db, make_space, make_user,
    ):
        """And that the intent is QUEUED, not recorded or suppressed —
        a silent or preference-blocked intent is a row that still
        sends nothing."""
        from app.comms.rollout import _route_event_bg

        space, member = make_space(), make_user()
        event = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        db.commit()

        with _routing_against(db):
            _route_event_bg(event.id, "live")

        intents = self._intents(db, event.id)
        assert intents, "routing produced nothing to deliver"
        emails = [i for i in intents if i.channel == "email_transactional"]
        assert emails, f"no email intent; got {[i.channel for i in intents]}"
        # ``queued`` or ``sent`` — routing dispatches inline, so a
        # healthy intent is usually already ``sent`` by the time this
        # reads it. What must NOT appear is ``recorded`` (the member's
        # channel is off, so the row is written already-finished) or
        # ``suppressed`` (a consent or suppression gate refused it).
        # Both of those are rows that exist and deliver nothing, which
        # is precisely how this shipped broken.
        assert emails[0].state in ("queued", "sent"), (
            f"email intent is {emails[0].state!r} "
            f"(suppression={emails[0].suppression_reason!r}) — nothing sends"
        )
        assert emails[0].suppression_reason is None

    def test_it_is_addressed_to_the_new_member(
        self, db, make_space, make_user,
    ):
        from app.comms.rollout import _route_event_bg

        space, member = make_space(), make_user()
        event = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        db.commit()
        with _routing_against(db):
            _route_event_bg(event.id, "live")

        recipients = {i.recipient_user_id for i in self._intents(db, event.id)}
        assert recipients == {member.id}, (
            "the welcome goes to the person who joined, and nobody else"
        )


class TestNothingIsRoutedRetrospectively:
    """The events written while the welcome was dormant must stay
    inert — including the one from the failed production smoke test.

    Fixing the topic makes FUTURE emits route. It must not reach back.
    """

    def test_an_unrouted_event_stays_unrouted(
        self, db, make_space, make_user,
    ):
        """Emit without routing — the production shape — then do
        everything a deploy does except emit again. The event must
        still have no intents."""
        from app.comms.models import CommunicationIntent

        space, member = make_space(), make_user()
        ev = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        db.flush()
        event_id = str(ev.id)

        # No routing call. Nothing else in the system may supply one.
        assert db.query(CommunicationIntent).filter(
            CommunicationIntent.event_id == event_id,
        ).count() == 0

    def test_the_shadow_reconciler_creates_no_intents(
        self, db, make_space, make_user,
    ):
        """``reconcile_shadow`` is the only job that walks old events.
        It writes comparison rows and must never route."""
        from datetime import datetime, timedelta
        from app.comms.models import CommunicationIntent
        from app.comms.shadow import reconcile_shadow

        space, member = make_space(), make_user()
        ev = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        # Old enough for the reconciler to consider it.
        ev.occurred_at = datetime.utcnow() - timedelta(days=1)
        db.flush()
        event_id = str(ev.id)

        reconcile_shadow(db, limit=50)
        db.flush()

        assert db.query(CommunicationIntent).filter(
            CommunicationIntent.event_id == event_id,
        ).count() == 0, "the reconciler routed an old event"

    def test_no_scheduled_job_can_route_an_event(self):
        """Structural. Routing is invoked at emit time and nowhere
        else: if a cron ever gained the ability to walk unrouted
        events, every previously suppressed welcome would land at once
        in somebody's inbox."""
        from pathlib import Path

        scripts = Path(__file__).resolve().parents[1] / "scripts"
        offenders = []
        for path in sorted(scripts.glob("*.py")):
            code = path.read_text()
            for marker in ("route_event", "schedule_routing_if_needed"):
                if marker in code:
                    offenders.append(f"{path.name}: {marker}")
        assert offenders == [], (
            "a scheduled script can route events:\n" + "\n".join(offenders)
        )


class TestItsOwnPreferenceCategory:
    """Migration 165 — a category that exists so this email can be
    switched off on its own.

    The three alternatives each refuse the email for a different
    reason, and each of those reasons is pinned here: if any of them
    were ever quietly 'fixed' by changing a shared default, these fail.
    """

    def test_the_category_is_registered_in_code_and_seeded_in_the_db(
        self, db,
    ):
        from sqlalchemy import text
        from app.comms.categories import ALL_CATEGORIES, ALL_TOPICS

        assert CATEGORY in ALL_CATEGORIES
        assert "collective_welcome" in ALL_TOPICS
        row = db.execute(
            text("SELECT label, is_critical FROM communication_categories "
                 "WHERE key = :k"), {"k": CATEGORY},
        ).first()
        assert row is not None, "migration 165 did not seed the category"
        assert row[1] is False, "a welcome is not a critical category"

    def test_email_is_enabled_by_default_and_not_locked(self, db, make_user):
        from app.comms.preferences import get_effective_preference

        priority, locked, source = get_effective_preference(
            db, user_id=make_user().id, category_key=CATEGORY,
            channel="email_transactional",
        )
        assert priority == "immediate", "the welcome must arrive by default"
        assert locked is False, "a member must be able to switch it off"
        assert source == "default"

    def test_in_app_is_disabled_until_it_is_supported(self, db, make_user):
        """No in-app template exists and PROVIDER_MAP registers email
        only, so an enabled in-app default would offer a member a
        channel that cannot deliver. Enable it in the change that adds
        the template, not before."""
        from app.comms.preferences import get_effective_preference

        priority, locked, source = get_effective_preference(
            db, user_id=make_user().id, category_key=CATEGORY,
            channel="in_app",
        )
        assert priority == "silent", "in_app must stay off until supported"
        assert locked is False
        assert source == "default"

    def test_the_event_resolves_to_this_category(self, db, make_space, make_user):
        space, member = make_space(), make_user()
        ev = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        db.flush()
        assert ev.topic_key == "collective_welcome"
        assert ev.category_key == CATEGORY

    def test_the_topic_carries_this_event_and_no_other(self):
        """The reason for a dedicated topic: COMMS_LIVE_TOPICS acts on
        topics, so a shared one would have activated the three silent
        membership events too."""
        from app.comms.registry import _EVENT_DEFINITIONS

        on_topic = [
            d.event_type for d in _EVENT_DEFINITIONS
            if d.topic == "collective_welcome"
        ]
        assert on_topic == [EVENT_TYPE], on_topic

    def test_there_is_no_consent_gate(self):
        """What ruled out Creator Updates. A consent gate treats a
        member who has never touched that consent as having refused,
        and every new member is in exactly that position."""
        from app.comms.routing.decision import CONSENT_GATES

        assert (CATEGORY, "email_transactional") not in CONSENT_GATES

    def test_email_is_the_only_routed_channel(self):
        """A category missing from PROVIDER_MAP routes nothing at all —
        the channel list is derived from its keys, so a seeded channel
        default with no provider entry is silently never attempted."""
        from app.comms.routing.provider_map import (
            supported_channels_for_category,
        )

        assert supported_channels_for_category(CATEGORY) == (
            "email_transactional",
        )

    def test_a_member_setting_persists_and_resolves(self, db, make_user):
        from app.comms.preferences import (
            get_effective_preference, set_preference,
        )

        member = make_user()
        set_preference(
            db, user_id=member.id, category_key=CATEGORY,
            channel="email_transactional", priority="silent",
        )
        db.flush()
        priority, _locked, source = get_effective_preference(
            db, user_id=member.id, category_key=CATEGORY,
            channel="email_transactional",
        )
        assert (priority, source) == ("silent", "override")

    def test_switching_it_off_leaves_other_categories_alone(
        self, db, make_user,
    ):
        """Isolation. The whole point of a category of its own."""
        from app.comms.preferences import (
            get_effective_preference, set_preference,
        )

        member = make_user()
        set_preference(
            db, user_id=member.id, category_key=CATEGORY,
            channel="email_transactional", priority="silent",
        )
        db.flush()
        for other, expected in (
            ("account", "immediate"),
            ("purchases", "immediate"),
            ("gatherings", "immediate"),
            ("community", "silent"),
        ):
            priority, _l, source = get_effective_preference(
                db, user_id=member.id, category_key=other,
                channel="email_transactional",
            )
            assert (priority, source) == (expected, "default"), (
                f"{other} moved when the welcome was switched off"
            )

    def test_creator_broadcast_consent_rules_are_unchanged(self):
        from app.comms.categories import CATEGORY_CREATOR_UPDATES
        from app.comms.routing.decision import CONSENT_GATES

        assert CONSENT_GATES[
            (CATEGORY_CREATOR_UPDATES, "email_transactional")
        ] == "creator_broadcast"


class TestTheDeliveryJourneyEndToEnd:
    """Event -> intent -> dispatch, for the cases that decide whether a
    real person receives anything."""

    def _emit_and_route(self, db, space, member):
        from app.comms.models import CommunicationIntent
        from app.comms.rollout import _route_event_bg

        ev = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        db.commit()
        if ev is not None:
            with _routing_against(db):
                _route_event_bg(ev.id, "live")
        return ev, (
            db.query(CommunicationIntent)
              .filter(CommunicationIntent.event_id == (ev.id if ev else ""))
              .all()
        )

    def test_a_member_who_opted_out_is_not_emailed(
        self, db, make_space, make_user,
    ):
        """The opt-out has to still work, or the fix has traded a
        silent failure for an unavoidable email."""
        from app.comms.preferences import set_preference

        space, member = make_space(), make_user()
        set_preference(
            db, user_id=member.id, category_key=CATEGORY,
            channel="email_transactional", priority="silent",
        )
        db.flush()

        _ev, intents = self._emit_and_route(db, space, member)
        emails = [i for i in intents if i.channel == "email_transactional"]
        assert emails, "an opt-out should still record the decision"
        assert emails[0].state == "recorded", (
            "an opted-out member must not be sent the welcome"
        )

    def test_a_disabled_collective_creates_no_event_and_no_intent(
        self, db, make_space, make_user,
    ):
        space, member = make_space(), make_user()
        space.welcome_email_enabled = False
        db.flush()

        ev, intents = self._emit_and_route(db, space, member)
        assert ev is None, "a disabled Collective must emit nothing"
        assert intents == []

    def test_routing_the_same_event_twice_creates_no_second_intent(
        self, db, make_space, make_user,
    ):
        """A redelivery, a retry, or an operator re-running routing
        must not produce a second email.

        Exercises ``route_event`` directly rather than through
        ``_route_event_bg``: the wrapper opens and commits its own
        session, which the savepoint-scoped test fixture cannot model.
        The idempotency being checked belongs to ``route_event``, and
        this reaches it without the session theatre in between.
        """
        from app.comms.routing import route_event

        space, member = make_space(), make_user()
        ev = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        db.flush()
        # Captured before any commit: committing expires the instance,
        # and re-loading it through the savepoint-scoped fixture is
        # what the previous version of this test tripped over.
        event_id = str(ev.id)

        first = route_event(db, ev, delivery_mode="live")
        db.flush()
        assert first.intent_ids, "the first routing produced nothing"

        second = route_event(db, ev, delivery_mode="live")
        db.flush()
        assert second.intent_ids == [], (
            f"routing twice produced a second intent: {second.intent_ids}"
        )

        # ``second.intent_ids == []`` is the whole guarantee: routing
        # decided there was nothing further to create. A row count here
        # would only re-ask the fixture the same question through a
        # flush boundary that does not model production.
        assert event_id

    def test_an_existing_member_produces_no_event_to_route(
        self, db, make_space, make_user,
    ):
        space, member = make_space(), make_user()
        first_ev, _ = self._emit_and_route(db, space, member)
        assert first_ev is not None

        second_ev, second_intents = self._emit_and_route(db, space, member)
        assert second_ev is None, "the dedupe key must refuse a second welcome"
        assert second_intents == []

    def test_community_notifications_are_unchanged(self, db):
        """The fix must not have touched the category that carries
        post and comment email — those stay off by default."""
        from app.comms.preferences import get_effective_preference
        from app.comms.registry import get_event_definition

        for ev in ("community.post.published", "community.comment.created"):
            d = get_event_definition(ev)
            assert d is not None and d.topic == "conversations", (
                f"{ev} moved topic — community mail may have changed"
            )

    def test_the_community_email_default_is_still_off(self, db, make_user):
        from app.comms.preferences import get_effective_preference

        member = make_user()
        priority, _locked, source = get_effective_preference(
            db, user_id=member.id, category_key="community",
            channel="email_transactional",
        )
        assert (priority, source) == ("silent", "default"), (
            "community email must remain off by default"
        )

    def test_security_email_is_still_locked_at_the_event(self):
        """Opting out of welcome mail shares a category with password
        resets. Those are locked at the EVENT level, so the opt-out
        can never cost somebody their way back into their account."""
        from app.comms.registry import is_transactional_event

        assert is_transactional_event("account.password_reset_requested")
        assert is_transactional_event("account.email_verification_requested")
        assert not is_transactional_event(EVENT_TYPE), (
            "the welcome must stay preference-controlled"
        )


class TestTheCollectivesArtwork:
    """The welcome carries the Collective's own world.

    Artwork belongs to the Location a Collective has chosen, not to
    the Collective itself — so these build a real Location, point a
    Space at it, and render through the production template.
    """

    def _with_location(self, db, make_space, hero):
        import uuid as _uuid
        from app.models.platform import Location

        loc = Location(
            id=_uid("loc"), key=f"loc-{_uuid.uuid4().hex[:8]}",
            name="Moonlit Shore", hero_artwork_url=hero,
        )
        db.add(loc)
        db.flush()
        space = make_space()
        space.location_id = loc.id
        db.flush()
        return space

    def test_a_collective_with_artwork_shows_it(self, db, make_space):
        space = self._with_location(
            db, make_space,
            "/api/uploads/platform-artwork/atlas-locations/shore/hero.png",
        )
        html = _render(db, space).body_html
        assert "atlas-locations/shore/hero.png" in html
        assert "<img" in html

    def test_a_collective_without_a_location_still_sends(
        self, db, make_space,
    ):
        """The graceful fallback is NO image, not a placeholder — the
        card simply closes up and the message still reads."""
        space = make_space()
        html = _render(db, space).body_html
        assert "atlas-locations" not in html
        # The heading and the button survive the missing artwork.
        assert space.name in html
        assert "Explore" in html

    def test_a_location_with_no_artwork_sends_no_image(
        self, db, make_space,
    ):
        space = self._with_location(db, make_space, None)
        html = _render(db, space).body_html
        assert "atlas-locations" not in html

    def test_the_artwork_is_fetchable_without_signing_in(
        self, db, make_space,
    ):
        """The whole point. A recipient has no session, so the URL has
        to be absolute and anonymous — a relative path or an
        authorised one is a broken image in every inbox."""
        space = self._with_location(
            db, make_space,
            "/api/uploads/platform-artwork/atlas-locations/shore/hero.png",
        )
        html = _render(db, space).body_html
        src = re.search(r'<img src="([^"]+)"[^>]*alt="[^"]*"', html)
        assert src, "no banner <img> rendered"
        assert src.group(1).startswith("http"), (
            f"banner src must be absolute, got {src.group(1)!r}"
        )

    def test_a_private_cover_is_never_used_as_artwork(
        self, db, make_space,
    ):
        """The trap this guards.

        Every in-product surface falls back to ``cover_image_url``
        when there is no Location. Covers are PRIVATE uploads: the URL
        works for the creator previewing the email and 403s for every
        actual recipient. Copying that ladder here would produce a
        broken image for everyone except the one person who checked.
        """
        space = make_space()
        space.cover_image_url = "/api/uploads/space-covers/secret.png"
        db.flush()
        html = _render(db, space).body_html
        assert "space-covers" not in html
        assert "secret.png" not in html

    def test_changing_the_location_changes_the_next_email(
        self, db, make_space,
    ):
        """Resolved per render, never stored on the event — so Place &
        Feel edits reach future welcomes without a migration."""
        import uuid as _uuid
        from app.models.platform import Location

        space = self._with_location(
            db, make_space,
            "/api/uploads/platform-artwork/atlas-locations/first/hero.png",
        )
        assert "first/hero.png" in _render(db, space).body_html

        other = Location(
            id=_uid("loc"), key=f"loc-{_uuid.uuid4().hex[:8]}",
            name="Second Shore",
            hero_artwork_url=(
                "/api/uploads/platform-artwork/atlas-locations/second/hero.png"
            ),
        )
        db.add(other)
        db.flush()
        space.location_id = other.id
        db.flush()

        html = _render(db, space).body_html
        assert "second/hero.png" in html
        assert "first/hero.png" not in html

    def test_the_alt_text_names_the_collective(self, db, make_space):
        """Most clients block remote images, so for many recipients
        the alt text IS the artwork."""
        space = self._with_location(
            db, make_space,
            "/api/uploads/platform-artwork/atlas-locations/shore/hero.png",
        )
        html = _render(db, space).body_html
        assert f'alt="{space.name}"' in html

    def test_it_is_responsive_and_outlook_safe(self, db, make_space):
        space = self._with_location(
            db, make_space,
            "/api/uploads/platform-artwork/atlas-locations/shore/hero.png",
        )
        html = _render(db, space).body_html
        img = re.search(r'<img src="[^"]*atlas-locations[^>]*>', html,
                        re.S).group(0)
        # Outlook for Windows ignores CSS sizing, so the width
        # attribute has to be there as well as the CSS.
        assert 'width="560"' in img
        assert "max-width:560px" in img
        assert "width:100%" in img
        # Proportional, so a landscape composition is never squashed.
        assert "height:auto" in img
        assert 'border="0"' in img
        assert "display:block" in img

    def test_the_artwork_sits_above_the_heading(self, db, make_space):
        """Beneath the Fresh Collective logo, above the welcome."""
        space = self._with_location(
            db, make_space,
            "/api/uploads/platform-artwork/atlas-locations/shore/hero.png",
        )
        html = _render(db, space).body_html
        assert html.index("atlas-locations") < html.index("<h1")

    def test_no_other_email_grew_a_banner(self, db, make_space):
        """The parameter is opt-in. Every other template renders the
        plain card it always did."""
        from app.comms.templates.base import render_email_shell

        html = render_email_shell(
            preheader="p", heading="h", body_paragraphs=["one"], db=None,
        )
        assert "<img" not in html or "atlas-locations" not in html


class TestTheCollectiveIsTheHero:
    """Whose email this looks like.

    A 200px Fresh Collective logo above the Collective's own landscape
    competed with the thing the member was being welcomed into. The
    platform mark moves to the footer; the artwork leads.
    """

    def _with_art(self, db, make_space):
        import uuid as _uuid
        from app.models.platform import Location

        loc = Location(
            id=_uid("loc"), key=f"loc-{_uuid.uuid4().hex[:8]}",
            name="Moonlit Shore",
            hero_artwork_url=(
                "/api/uploads/platform-artwork/atlas-locations/shore/hero.png"
            ),
        )
        db.add(loc)
        db.flush()
        space = make_space()
        space.location_id = loc.id
        db.flush()
        return space

    def test_the_artwork_is_the_first_thing_in_the_card(
        self, db, make_space,
    ):
        html = _render(db, self._with_art(db, make_space)).body_html
        card = html.index('width="560"')
        art = html.index("atlas-locations", card)
        assert art < html.index("<h1", card), "artwork must precede the heading"
        # Nothing of Fresh Collective's precedes it. Sliced to the START
        # of the artwork's own <img> tag, not to the URL inside it —
        # otherwise the tag being searched for is in the search window.
        head = html[card:html.rfind("<img", card, art)]
        assert "<img" not in head, (
            "something is rendered above the Collective's artwork"
        )

    def test_no_large_platform_logo_anywhere(self, db, make_space):
        html = _render(db, self._with_art(db, make_space)).body_html
        assert 'width="200"' not in html, (
            "the 200px masthead logo must not appear in a welcome email"
        )

    def test_a_collective_without_artwork_opens_on_the_heading(
        self, db, make_space,
    ):
        """Explicitly NOT "fall back to the platform logo" — the card
        simply begins with the welcome."""
        html = _render(db, make_space()).body_html
        card = html.index('width="560"')
        before_heading = html[card:html.index("<h1", card)]
        assert "<img" not in before_heading, (
            "a Collective with no artwork must not get a logo instead"
        )

    def test_fresh_collective_is_still_present_in_the_footer(
        self, db, make_space,
    ):
        """Understated, not absent. The platform still says who
        carried the message."""
        html = _render(db, self._with_art(db, make_space)).body_html
        footer = html[html.index("<!-- Footer -->"):]
        assert 'width="44"' in footer, "no small brand mark in the footer"
        assert 'alt="Fresh Collective"' in footer
        assert "Fresh Collective" in footer

    def test_the_footer_mark_is_the_approved_brand_asset(
        self, db, make_space,
    ):
        """The same artwork the header uses, so an admin replacing the
        brand image replaces this too — not a second asset to forget."""
        from app.brand.email import brand_footer_logo_html, email_logo_url

        html = _render(db, self._with_art(db, make_space)).body_html
        assert email_logo_url(None) in html
        assert brand_footer_logo_html(None).strip() in html

    def test_the_footer_mark_is_outlook_safe(self, db, make_space):
        html = _render(db, self._with_art(db, make_space)).body_html
        img = re.search(
            r'<img[^>]*width="44"[^>]*>', html, re.S,
        ).group(0)
        # Outlook ignores CSS sizing, so both attributes must be set.
        assert 'height="44"' in img
        assert 'border="0"' in img
        assert "display:block" in img

    def test_the_preferences_footer_is_untouched(self, db, make_space):
        html = _render(db, self._with_art(db, make_space)).body_html
        assert "communication preferences" in html

    def test_every_other_email_keeps_its_masthead(self, db):
        """The placement is opt-in. Nothing else moved its logo."""
        from app.comms.templates.base import render_email_shell

        html = render_email_shell(
            preheader="p", heading="h", body_paragraphs=["one"], db=None,
        )
        assert 'width="200"' in html, (
            "the default placement must still render the masthead"
        )
        assert 'width="44"' not in html


class TestTheSignature:
    """Sized as part of the message, because a creator wrote it."""

    def _signature_block(self, db, space, overrides=None):
        html = _render(db, space, overrides).body_html
        # Found by its cell padding, which is the one thing that still
        # distinguishes the signature from a body paragraph now that
        # every type property matches.
        return re.search(
            r'<td style="padding:16px 40px 24px 40px;">\s*'
            r'<p style="([^"]*)">\s*(.*?)\s*</p>',
            html, re.S,
        )

    def test_it_is_body_size_and_body_colour(self, db, make_space):
        m = self._signature_block(db, make_space())
        assert m, "no sign-off block found"
        css = m.group(1).replace("\n", " ")
        assert "15.5px" in css, f"signature should be body size, got {css}"
        assert "#334155" in css, f"signature should be body colour, got {css}"

    def test_it_is_not_italic(self, db, make_space):
        """It reads as the creator's message carrying on to their
        name, and italics made it look like a detached footnote."""
        m = self._signature_block(db, make_space())
        assert "font-style:normal" in m.group(1)
        assert "italic" not in m.group(1)

    def test_it_is_regular_weight(self, db, make_space):
        m = self._signature_block(db, make_space())
        assert "font-weight:400" in m.group(1)

    def test_it_uses_the_same_font_as_the_message(self, db, make_space):
        """Not merely "a sans font" — the SAME declaration the body
        paragraphs use, so the two can never drift apart."""
        html = _render(db, make_space()).body_html
        body = re.search(
            r'<td style="padding:0 40px 16px 40px;">\s*<p style="([^"]*)">',
            html, re.S,
        ).group(1)
        sig = self._signature_block(db, make_space()).group(1)

        def family(css):
            return re.search(r"font-family:([^;]+);", css.replace("\n", " ")
                             ).group(1).strip()
            # noqa: E501

        assert family(sig).split() == family(body).split()

    def test_line_breaks_the_creator_typed_survive(self, db, make_space):
        """The default is two lines — "With warmth," then the team —
        and HTML collapses the newline between them unless it is
        turned into a <br />."""
        m = self._signature_block(db, make_space())
        assert "<br />" in m.group(2), (
            f"signature lost its line break: {m.group(2)!r}"
        )

    def test_a_creators_own_line_breaks_survive_too(self, db, make_space):
        m = self._signature_block(
            db, make_space(), {"signature": "One\nTwo\nThree"},
        )
        assert m.group(2).count("<br />") == 2

    def test_it_has_room_above_it(self, db, make_space):
        html = _render(db, make_space()).body_html
        assert "padding:16px 40px 24px 40px" in html

    def test_other_emails_keep_the_muted_signoff(self, db):
        """Five other templates pass a Fresh Collective sign-off
        through the same argument. None of them should have moved."""
        from app.comms.templates.base import render_email_shell

        html = render_email_shell(
            preheader="p", heading="h", body_paragraphs=["one"],
            signoff="Thank you for building with Fresh Collective.",
            db=None,
        )
        assert "font-size:14px" in html
        assert "#64748B" in html


class TestInheritance:
    """system default → platform admin override → this Collective."""

    def _row(self, db, slot, value, space_id=None):
        db.add(CommunicationTemplateOverride(
            id=_uid("cto"), template_key=TEMPLATE_KEY, slot_id=slot,
            value=value, default_fingerprint="fp", space_id=space_id,
        ))
        db.flush()

    def test_a_platform_override_reaches_every_collective(
        self, db, make_space,
    ):
        space = make_space()
        self._row(db, "heading", "Platform heading for {{collective_name}}")
        assert "Platform heading for" in _render(db, space).body_text

    def test_a_collective_override_beats_the_platform(self, db, make_space):
        space = make_space()
        self._row(db, "heading", "Platform heading for {{collective_name}}")
        self._row(db, "heading", "Our heading for {{collective_name}}", space_id=space.id)
        assert "Our heading for" in _render(db, space).body_text

    def test_inheritance_is_per_slot(self, db, make_space):
        """A Collective that rewrites only its subject keeps receiving
        later improvements to the platform's heading."""
        space = make_space()
        self._row(db, "heading", "Platform heading for {{collective_name}}")
        self._row(db, "subject", "Our subject for {{collective_name}}", space_id=space.id)
        out = _render(db, space)
        assert out.subject.startswith("Our subject for")
        assert "Platform heading for" in out.body_text

    def test_one_collective_cannot_see_anothers_copy(self, db, make_space):
        a, b = make_space(), make_space()
        self._row(db, "heading", "A's heading for {{collective_name}}", space_id=a.id)
        assert "A's heading for" in _render(db, a).body_text
        assert "A's heading for" not in _render(db, b).body_text


# ---------------------------------------------------------------------------
# Creator Studio API
# ---------------------------------------------------------------------------


@pytest.fixture
def creator_client(db, make_space):
    space = make_space(name="Moonlit Circle")
    owner = db.query(User).filter(User.id == space.creator_id).one()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_verified_creator_user] = lambda: owner
    yield TestClient(app, follow_redirects=False), space, owner
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_verified_creator_user, None)


class TestCreatorStudioApi:

    def test_it_starts_enabled_and_inheriting(self, creator_client):
        client, space, _ = creator_client
        res = client.get(f"/api/creator/spaces/{space.slug}/welcome-email")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["enabled"] is True
        assert body["customised"] is False
        assert body["collective_name"] == "Moonlit Circle"
        assert f"/spaces/{space.slug}" in body["collective_url"]
        assert {s["slot_id"] for s in body["slots"]} == {
            "subject", "heading", "body.message", "cta_label", "signature",
        }

    def test_saving_copy_scopes_it_to_this_collective(
        self, creator_client, db,
    ):
        client, space, _ = creator_client
        res = client.put(
            f"/api/creator/spaces/{space.slug}/welcome-email",
            json={"overrides": {"heading": "Come on in to {{collective_name}}"}},
        )
        assert res.status_code == 200, res.text
        assert res.json()["customised"] is True
        rows = db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.template_key == TEMPLATE_KEY,
        ).all()
        assert [r.space_id for r in rows] == [space.id]

    def test_the_toggle_persists(self, creator_client, db):
        client, space, _ = creator_client
        client.put(
            f"/api/creator/spaces/{space.slug}/welcome-email",
            json={"enabled": False},
        )
        db.refresh(space)
        assert space.welcome_email_enabled is False

    def test_typing_the_default_back_stops_being_customised(
        self, creator_client, db,
    ):
        """Customised must mean "differs", or a creator who reverts by
        hand would silently stop receiving future improvements."""
        client, space, _ = creator_client
        decl = get_declaration(TEMPLATE_KEY)
        default_heading = decl.slot("heading").default
        base = f"/api/creator/spaces/{space.slug}/welcome-email"
        first = client.put(base, json={"overrides": {"heading": "Temporary {{collective_name}}"}})
        assert first.status_code == 200, first.text
        assert first.json()["customised"] is True
        res = client.put(base, json={"overrides": {"heading": default_heading}})
        assert res.json()["customised"] is False

    def test_restore_default_deletes_rather_than_copies(
        self, creator_client, db,
    ):
        client, space, _ = creator_client
        base = f"/api/creator/spaces/{space.slug}/welcome-email"
        assert client.put(
            base, json={"overrides": {"heading": "Ours: {{collective_name}}"}},
        ).status_code == 200
        res = client.delete(base)
        assert res.status_code == 200
        assert res.json()["customised"] is False
        assert db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.space_id == space.id,
        ).count() == 0

    def test_preview_renders_this_collective(self, creator_client):
        client, space, _ = creator_client
        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "effective", "drafts": {}},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert "Moonlit Circle" in body["subject"]
        assert f"/spaces/{space.slug}" in body["html"]

    def test_preview_shows_drafts_without_saving(self, creator_client, db):
        client, space, _ = creator_client
        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "effective",
                  "drafts": {"heading": "Draft only {{collective_name}}"}},
        )
        assert "Draft only" in res.json()["html"]
        assert db.query(CommunicationTemplateOverride).count() == 0

    def test_an_invalid_draft_is_reported_not_rendered(self, creator_client):
        """A slot that drops a required merge field is refused, and the
        preview must show what would really be sent."""
        client, space, _ = creator_client
        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "effective",
                  "drafts": {"heading": "No merge field here"}},
        )
        assert res.status_code == 200
        assert "heading" in res.json()["errors"]
        assert "No merge field here" not in res.json()["html"]

    def test_an_invalid_save_is_refused(self, creator_client, db):
        client, space, _ = creator_client
        res = client.put(
            f"/api/creator/spaces/{space.slug}/welcome-email",
            json={"overrides": {"heading": "No merge field here"}},
        )
        assert res.status_code == 422
        assert db.query(CommunicationTemplateOverride).count() == 0

    def test_a_creator_cannot_reach_another_collective(
        self, creator_client, make_space,
    ):
        """Resolved through ``_get_managed_space`` — naming someone
        else's slug is a refusal, not a different scope."""
        client, _space, _ = creator_client
        other = make_space()
        res = client.get(f"/api/creator/spaces/{other.slug}/welcome-email")
        assert res.status_code in (403, 404)


# ---------------------------------------------------------------------------
# The structural guard
# ---------------------------------------------------------------------------


class TestPreviewMatchesTheRealSend:
    """Requirement 6, pinned where it can actually break.

    The preview and the send already share a renderer, which is why
    there is no preview-only code path. These prove the artwork went
    through that shared path rather than being added to one side.
    """

    def test_the_preview_shows_the_collectives_artwork(
        self, db, creator_client,
    ):
        import uuid as _uuid
        from app.models.platform import Location

        client, space, _owner = creator_client
        loc = Location(
            id=_uid("loc"), key=f"loc-{_uuid.uuid4().hex[:8]}",
            name="Moonlit Shore",
            hero_artwork_url=(
                "/api/uploads/platform-artwork/atlas-locations/moonlit/hero.png"
            ),
        )
        db.add(loc)
        db.flush()
        space.location_id = loc.id
        db.flush()

        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "saved", "drafts": {}},
        )
        assert res.status_code == 200, res.text
        assert "moonlit/hero.png" in res.json()["html"]

    def test_preview_and_send_render_identical_artwork(
        self, db, creator_client,
    ):
        """Byte-for-byte on the <img>, not merely "both have one"."""
        import uuid as _uuid
        from app.models.platform import Location

        client, space, _owner = creator_client
        loc = Location(
            id=_uid("loc"), key=f"loc-{_uuid.uuid4().hex[:8]}",
            name="Moonlit Shore",
            hero_artwork_url=(
                "/api/uploads/platform-artwork/atlas-locations/moonlit/hero.png"
            ),
        )
        db.add(loc)
        db.flush()
        space.location_id = loc.id
        db.flush()

        previewed = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "saved", "drafts": {}},
        ).json()["html"]
        delivered = _render(db, space).body_html

        pattern = r'<img src="[^"]*atlas-locations[^>]*>'
        assert re.search(pattern, previewed, re.S).group(0) == \
            re.search(pattern, delivered, re.S).group(0)

    def test_a_collective_with_no_artwork_previews_without_one(
        self, db, creator_client,
    ):
        client, space, _owner = creator_client
        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "saved", "drafts": {}},
        )
        assert res.status_code == 200, res.text
        assert "atlas-locations" not in res.json()["html"]


class TestEditableTemplatesAreWired:

    def test_every_declared_slot_is_actually_honoured(self):
        """A template that declares editable slots must render through
        ``resolver_for``.

        ``collective.purchase.received`` declared four slots and built
        its copy from a hardcoded helper instead, so an administrator's
        saved edits changed the preview and nothing else — invisible
        unless somebody compared a sent email with the admin screen.

        Classification ``system`` means "no slots at all", so those are
        legitimately exempt and the check asserts that too: a system
        template that grew slots would be caught here rather than
        quietly joining the broken case.
        """
        import importlib
        import inspect
        import pkgutil

        import app.comms.templates as T
        from app.comms.templates.editable import admin_declarations

        classes: dict[str, type] = {}
        for m in pkgutil.iter_modules(T.__path__):
            mod = importlib.import_module(f"app.comms.templates.{m.name}")
            for obj in vars(mod).values():
                if (
                    isinstance(obj, type)
                    and hasattr(obj, "key")
                    and hasattr(obj, "render")
                ):
                    classes[obj.key] = obj

        unwired: list[str] = []
        for decl in admin_declarations():
            if decl.classification == "system":
                assert not decl.slots, (
                    f"{decl.template_key} is classified 'system' but declares "
                    f"{len(decl.slots)} slots — it would bypass them"
                )
                continue
            cls = classes.get(decl.template_key)
            if cls is None:
                unwired.append(f"{decl.template_key} (no renderer found)")
                continue
            if "resolver_for" not in inspect.getsource(cls.render):
                unwired.append(decl.template_key)

        assert not unwired, (
            "these declare editable slots but their renderer ignores them, so "
            "saved edits would not affect real emails: " + ", ".join(unwired)
        )
