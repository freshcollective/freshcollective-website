"""The real EMBODY signup shape: a space-attached, one-time pass.

Production verification corrected an assumption in the original audit.
The live $306 purchase was NOT a Series-attached option. It was
"⚡ Activate — 2 Sessions per week": ``payment_type='one_time'``,
``attaches_to_kind='space'``, attached to EMBODY, with no purchase plan.
Its 19 confirmed bookings were made against the pass afterwards, not
created at fulfilment.

The existing notification tests call the emitter directly, which proves
the event and its recipients but not that the *webhook path* reaches it
for this option shape. That is the gap this file closes: it drives
``_handle_checkout_completed`` with a genuine space-attached one-time
purchase and asserts the creator is told exactly once.

No email is sent: these assert on the emitted ``CommunicationEvent`` row
and never enter the delivery layer.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import app.models.community_care  # noqa: F401
import app.main  # noqa: F401 — bootstraps the comms registries
from app.checkout.schemas import UnifiedCheckoutRequest
from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import get_resolver_for
from app.core.config import settings
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

CREATOR_EVENT = "collective.purchase.received"
MEMBER_EVENT = "purchase.completed"
OPTION_NAME = "⚡ Activate — 2 Sessions per week"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


def _space_attached_option(db, space) -> PaymentOption:
    """The live shape: attached to the SPACE, one-time, sessions-per-week."""
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="space", attaches_to_id=space.id,
        name=OPTION_NAME, payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=30600, currency="AUD",
        sessions_per_week=2,
    )
    db.add(opt)
    db.flush()
    return opt


def _schedule(db, option) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        payment_option_id=option.id,
        name="Pay in full", schedule_type="pay_in_full",
        status="published", total_amount_cents=30600, currency="AUD",
    )
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def live_shape(db, make_space, make_user, stripe_configured):
    """A Collective, its creator, a buyer, and the real option shape."""
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    buyer = make_user(name="Rosalind Franklin")
    opt = _space_attached_option(db, space)
    sched = _schedule(db, opt)
    db.flush()
    return space, creator, buyer, opt, sched


def _buy(db, buyer, opt, sched, session_id: str) -> dict:
    """Create the checkout session and return Stripe's metadata."""
    from app.checkout.routes import create_unified_checkout_session

    with patch("stripe.checkout.Session.create") as m:
        m.return_value = SimpleNamespace(
            id=session_id, url="https://checkout.stripe.test/x",
        )
        create_unified_checkout_session(
            UnifiedCheckoutRequest(
                payment_option_id=opt.id,
                payment_option_schedule_id=sched.id,
                success_url="https://ok/s", cancel_url="https://ok/c",
            ),
            current_user=buyer, db=db,
        )
    return m.call_args.kwargs["metadata"]


def _complete(db, metadata: dict, session_id: str) -> None:
    from app.webhooks.routes import _handle_checkout_completed

    _handle_checkout_completed(
        {
            "id": session_id,
            "payment_status": "paid",
            "payment_intent": f"pi_{session_id}",
            "amount_total": 30600,
            "currency": "aud",
            "metadata": metadata,
        },
        db,
    )


def _events(db, space_id: str, event_type: str) -> list[CommunicationEvent]:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == event_type,
            CommunicationEvent.source_id == space_id,
        )
        .all()
    )


class TestTheRealSpaceAttachedPurchase:
    def test_it_reaches_the_generic_path_and_notifies_the_creator(
        self, db, live_shape,
    ):
        """The live case. A space-attached one-time purchase writes no
        ``purchase_type`` metadata, so it falls past the
        standalone-gathering and finite-plan branches into the generic
        handler — which is where the emit had to go."""
        space, _creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_space_attached")

        _complete(db, meta, "cs_space_attached")

        assert len(_events(db, space.id, CREATOR_EVENT)) == 1

    def test_the_member_receipt_still_fires(self, db, live_shape):
        """Production showed the member lifecycle working — in_app sent,
        email delivered. Adding the creator notification must not have
        disturbed it."""
        space, _creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_member_too")

        _complete(db, meta, "cs_member_too")

        member_events = (
            db.query(CommunicationEvent)
            .filter(
                CommunicationEvent.event_type == MEMBER_EVENT,
                CommunicationEvent.actor_user_id == buyer.id,
            )
            .all()
        )
        assert len(member_events) == 1

    def test_the_notification_names_the_option_the_member_bought(
        self, db, live_shape,
    ):
        space, _creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_names_option")

        _complete(db, meta, "cs_names_option")

        payload = _events(db, space.id, CREATOR_EVENT)[0].payload
        assert payload["experience_name"] == OPTION_NAME
        assert payload["collective_name"] == space.name

    def test_the_payment_mode_is_single_not_plan(self, db, live_shape):
        """No purchase plan on the live transaction, so the copy must not
        say a first instalment has landed."""
        space, _creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_single_mode")

        _complete(db, meta, "cs_single_mode")

        assert _events(db, space.id, CREATOR_EVENT)[0].payload["payment_mode"] == "single"

    def test_session_count_is_absent_because_no_bookings_are_created_yet(
        self, db, live_shape,
    ):
        """A sessions-per-week pass grants credits; the bookings come
        afterwards. At purchase time the honest answer is "none", and the
        template omits the "covers N Gatherings" line rather than
        claiming a number."""
        space, _creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_no_fanout")

        _complete(db, meta, "cs_no_fanout")

        assert _events(db, space.id, CREATOR_EVENT)[0].payload["session_count"] is None

    def test_a_webhook_redelivery_does_not_notify_twice(self, db, live_shape):
        """Stripe redelivers. Two guards stand here — the
        ``fulfilment_status == applied`` short-circuit and the dedupe key
        on the transaction id — and the creator must hear once."""
        space, _creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_redelivered")

        _complete(db, meta, "cs_redelivered")
        _complete(db, meta, "cs_redelivered")

        assert len(_events(db, space.id, CREATOR_EVENT)) == 1

    def test_the_collectives_creator_is_the_recipient(self, db, live_shape):
        space, creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_recipient")

        _complete(db, meta, "cs_recipient")

        event = _events(db, space.id, CREATOR_EVENT)[0]
        recipients = get_resolver_for(CREATOR_EVENT).resolve(db, event)
        assert {r.user_id for r in recipients} == {creator.id}

    def test_the_buyer_is_named_without_their_email(self, db, live_shape):
        space, _creator, buyer, opt, sched = live_shape
        meta = _buy(db, buyer, opt, sched, "cs_no_email")

        _complete(db, meta, "cs_no_email")

        payload = _events(db, space.id, CREATOR_EVENT)[0].payload
        assert payload["buyer_name"] == "Rosalind Franklin"
        assert "@" not in str(payload)
