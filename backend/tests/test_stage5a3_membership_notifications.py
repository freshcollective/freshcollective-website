"""Stage 5A.3 — the six transactional membership messages.

What these protect, beyond "an email went out":

* **The member's own agreement, not the catalogue.** Every amount is
  resolved at emit time from their subscription row. A creator who
  re-priced yesterday has not re-priced them, and a receipt with the
  wrong number is worse than one with none.
* **Scheduled is not ended.** A cancellation keeps access until the
  period runs out and says so with a date; only "ended" says access has
  ended. Conflating them is the mistake the brief names explicitly.
* **A replay sends nothing.** Dedupe keys are per-occurrence — an
  invoice, a grace window, a period — so a retried webhook is silent
  while a genuinely new occurrence still sends.
* **The creator is never a recipient.** Their view is Payments
  received; the rest of a member's billing is not theirs.

Also pinned: the topics these land on are already live. Stage 5A.2's
report implied a new ``collective_membership`` topic was needed; it is
not, and this file is where that is settled.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.comms.registry import TRANSACTIONAL_EVENT_TYPES, _EVENT_DEFINITIONS
from app.core.config import settings
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.services import collective_membership_emit as emit

NOW = datetime.utcnow()

EVENTS = (
    "collective.membership.purchased",
    "collective.membership.renewed",
    "collective.membership.payment_failed",
    "collective.membership.cancellation_scheduled",
    "collective.membership.ended",
    "collective.membership.reactivated",
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def world(db, make_user, make_space):
    creator = make_user(role="creator")
    member = make_user(name="Tom Test")
    space = make_space(creator=creator)
    space.name = "Life in Full Colour"
    space.pricing_type = "paid_monthly"
    space.pricing_amount_cents = 2_900
    space.pricing_currency = "AUD"
    db.flush()
    return dict(creator=creator, member=member, space=space)


def _sub(db, world, **kw):
    row = CollectiveMembership(
        id=_uid("cmem"), user_id=world["member"].id, space_id=world["space"].id,
        status=kw.pop("status", CollectiveMembershipStatus.active.value),
        interval=kw.pop("interval", "month"), interval_count=1,
        amount_cents=kw.pop("amount_cents", 2_900), currency="AUD",
        creator_user_id=world["creator"].id,
        platform_fee_basis_points=1_000, payout_model="manual",
        current_period_start=NOW,
        current_period_end=NOW + timedelta(days=30),
        created_at=NOW, updated_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Delivery configuration — the "critical infrastructure detail"
# ---------------------------------------------------------------------------


class TestTheyCanActuallyBeDelivered:
    def test_all_six_are_registered(self):
        registered = {e.event_type for e in _EVENT_DEFINITIONS}
        for event in EVENTS:
            assert event in registered, event

    def test_every_one_lands_on_a_live_topic(self):
        """The failure mode this guards: an event written and never
        delivered, which is how the Collective welcome shipped silent.

        Stage 5A.2's report implied a new ``collective_membership``
        topic was needed. It is not — a receipt belongs on ``purchases``
        and a billing-state notice on ``account``, mirroring the creator
        subscription family, and both are already live.
        """
        live = {t.strip() for t in settings.comms_live_topics.split(",")}
        by_type = {e.event_type: e for e in _EVENT_DEFINITIONS}
        for event in EVENTS:
            assert by_type[event].topic in live, (
                f"{event} is on topic {by_type[event].topic!r}, which is not "
                f"live — it would be written and never sent"
            )

    def test_receipts_and_notices_are_split_the_way_creator_billing_is(self):
        by_type = {e.event_type: e.topic for e in _EVENT_DEFINITIONS}
        assert by_type["collective.membership.purchased"] == "purchases"
        assert by_type["collective.membership.renewed"] == "purchases"
        for event in EVENTS[2:]:
            assert by_type[event] == "account", event

    def test_all_six_are_transactional(self):
        """A preference that could silence a failed-payment notice would
        leave somebody losing access without warning."""
        for event in EVENTS:
            assert event in TRANSACTIONAL_EVENT_TYPES, event

    @pytest.mark.parametrize("event", EVENTS)
    def test_each_has_a_resolver_and_both_templates(self, event):
        import app.comms.routing  # noqa: F401 — registration
        import app.comms.templates  # noqa: F401
        from app.comms.routing.resolver import get_resolver_for
        from app.comms.templates.registry import registered_templates

        assert get_resolver_for(event) is not None, event
        keys = set(registered_templates())
        assert (event, "email_transactional") in keys, event
        assert (event, "in_app") in keys, event


# ---------------------------------------------------------------------------
# The member's own agreement
# ---------------------------------------------------------------------------


class TestTheyDescribeTheAgreementNotTheCatalogue:
    def test_the_amount_is_the_members_own(self, db, world):
        sub = _sub(db, world, amount_cents=2_900)
        # The creator re-prices after the member subscribed.
        world["space"].pricing_amount_cents = 3_900
        db.flush()
        payload = emit._base_payload(db, sub)
        assert payload["amount_label"] == "A$29"
        assert "39" not in payload["amount_label"]

    def test_a_monthly_and_an_annual_agreement_read_differently(
        self, db, world,
    ):
        monthly = emit._base_payload(db, _sub(db, world, interval="month"))
        assert monthly["interval_label"] == "per month"
        db.query(CollectiveMembership).delete()
        db.flush()
        annual = emit._base_payload(
            db, _sub(db, world, interval="year", amount_cents=29_000),
        )
        assert annual["interval_label"] == "per year"
        assert annual["amount_label"] == "A$290"

    def test_it_names_the_collective_and_the_member(self, db, world):
        payload = emit._base_payload(db, _sub(db, world))
        assert payload["collective_name"] == "Life in Full Colour"
        assert payload["first_name"] == "Tom"
        assert payload["membership_url"].endswith("/settings/membership")

    @pytest.mark.parametrize("cents,currency,expected", [
        (2_900, "AUD", "A$29"),
        (2_950, "AUD", "A$29.50"),
        (29_000, "AUD", "A$290"),
        (500, "USD", "USD 5"),
        (None, "AUD", ""),
    ])
    def test_money_is_formatted_once_and_here(self, cents, currency, expected):
        assert emit._money(cents, currency) == expected


# ---------------------------------------------------------------------------
# What each message is allowed to claim
# ---------------------------------------------------------------------------


def _render(db, event_type, ctx):
    import app.comms.templates  # noqa: F401
    from app.comms.templates.registry import get_template_for
    from app.comms.routing.resolver import ResolvedRecipient

    template = get_template_for(event_type, "email_transactional")
    recipient = ResolvedRecipient(
        user_id="u", role_in_event="member", human_reason="",
        template_context=ctx,
    )
    return template.render(db, None, recipient)


BASE_CTX = {
    "first_name": "Tom", "collective_name": "Life in Full Colour",
    "collective_url": "https://fc.test/spaces/lifc",
    "membership_url": "https://fc.test/settings/membership",
    "amount_label": "A$29", "interval_label": "per month",
}


class TestWhatTheCopyMayClaim:
    def test_purchased_states_the_agreed_terms(self, db):
        out = _render(db, "collective.membership.purchased", {
            **BASE_CTX, "next_renewal_at": "2026-12-13T00:00:00",
        })
        assert "Life in Full Colour" in out.subject
        assert "A$29 per month" in out.body_text
        assert "13 December 2026" in out.body_text

    def test_payment_failed_says_access_continues(self, db):
        """Nothing is paused during grace, and the copy must not imply
        it is."""
        out = _render(db, "collective.membership.payment_failed", {
            **BASE_CTX, "grace_expires_at": "2026-12-20T00:00:00",
        })
        assert "still active" in out.body_text
        assert "20 December 2026" in out.body_text

    def test_cancellation_scheduled_is_not_an_ending(self, db):
        out = _render(db, "collective.membership.cancellation_scheduled", {
            **BASE_CTX, "access_until": "2026-12-13T00:00:00",
        })
        assert "won't be charged again" in out.body_text
        assert "stays active until 13 December 2026" in out.body_text
        assert "has ended" not in out.body_text

    def test_ended_says_so_and_protects_what_was_bought(self, db):
        out = _render(db, "collective.membership.ended", BASE_CTX)
        assert "has ended" in out.body_text
        assert "still yours" in out.body_text

    def test_nothing_tells_a_member_they_left_the_collective(self, db):
        """Cancelling renewal is not leaving, and no message may blur
        that."""
        for event in EVENTS:
            out = _render(db, event, {
                **BASE_CTX, "next_renewal_at": "2026-12-13T00:00:00",
                "grace_expires_at": "2026-12-20T00:00:00",
                "access_until": "2026-12-13T00:00:00",
            })
            assert "you have left" not in out.body_text.lower(), event
            assert "you've left" not in out.body_text.lower(), event

    def test_no_stripe_vocabulary_anywhere(self, db):
        for event in EVENTS:
            out = _render(db, event, {
                **BASE_CTX, "next_renewal_at": "2026-12-13T00:00:00",
                "grace_expires_at": "2026-12-20T00:00:00",
                "access_until": "2026-12-13T00:00:00",
            })
            lowered = out.body_text.lower()
            for word in ("stripe", "invoice", "dunning", "sub_", "webhook"):
                assert word not in lowered, f"{event}: {word}"

    def test_none_of_them_persuades(self, db):
        """Receipts and notices. Announcements are the creator's."""
        for event in EVENTS:
            out = _render(db, event, {
                **BASE_CTX, "next_renewal_at": "2026-12-13T00:00:00",
                "grace_expires_at": "2026-12-20T00:00:00",
                "access_until": "2026-12-13T00:00:00",
            })
            lowered = out.body_text.lower()
            for word in ("don't miss", "upgrade now", "limited time",
                         "act now", "special offer"):
                assert word not in lowered, f"{event}: {word}"

    def test_a_missing_amount_names_no_figure_rather_than_guessing(self, db):
        out = _render(db, "collective.membership.purchased", {
            **BASE_CTX, "amount_label": "", "next_renewal_at": None,
        })
        assert "A$" not in out.body_text
        assert "continues until you cancel it" in out.body_text


# ---------------------------------------------------------------------------
# Replays
# ---------------------------------------------------------------------------


class TestAReplaySendsNothing:
    def test_each_emit_has_a_per_occurrence_dedupe_key(self):
        """Keyed on the invoice, the window or the period — never on the
        subscription alone, which would send once and then never again.
        """
        import inspect
        src = inspect.getsource(emit)
        assert 'dedupe_key=f"cmem_renewed:{sub.id}:{invoice_id}"' in src
        assert "cmem_failed:{sub.id}:{_iso(sub.grace_expires_at)}" in src
        assert "cmem_ended:{sub.id}:{_iso(sub.ended_at)}" in src

    def test_a_comms_failure_never_breaks_the_billing(self, db, world):
        """The payment is the fact of record; the message is a courtesy
        on top of it. A raising emit would roll back the caller."""
        from unittest.mock import patch
        sub = _sub(db, world)
        with patch("app.comms.emit", side_effect=RuntimeError("comms down")):
            assert emit.emit_membership_purchased(db, sub=sub) is None

    def test_every_emit_is_wrapped(self):
        import inspect
        src = inspect.getsource(emit)
        for name in ("purchased", "renewed", "payment_failed",
                     "cancellation_scheduled", "ended", "reactivated"):
            fn = f"def emit_membership_{name}("
            assert src[:src.index(fn)].rstrip().endswith("@_safe_emit"), name
