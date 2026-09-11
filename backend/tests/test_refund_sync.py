"""Stripe refund sync — ``charge.refunded`` handler + summary
aggregation.

Pinned invariants:

  1. Full / partial / multiple partial refunds land the correct
     ``refunded_amount_cents`` + ``status`` + ``last_refunded_at``
     on the anchoring ``PaymentTransaction`` row.
  2. Monotonic guards — out-of-order distinct Stripe events cannot
     regress amount, downgrade status, or move the timestamp
     backwards.
  3. Same-event-id duplicate deliveries are a no-op via the
     existing ``WebhookEvent`` idempotency mechanism.
  4. Lookup falls back from ``provider_charge_id`` to
     ``provider_payment_intent_id`` on pay-in-full rows; charge id
     is opportunistically backfilled on match.
  5. Access-side state (AccessPass, PathwayEntitlement,
     AccessGrantRecord, SpaceMembership, EventBooking) is NEVER
     touched by refund handling. Refund and access-revocation are
     completely independent.
  6. Summary aggregation follows the revised semantics:
     Gross = original amounts (historical), Refunds = cumulative
     refunded, Net Retained = Gross − Refunds.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.creator.routes import get_creator_payment_summary
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    PathwayType,
)
from app.models.webhook_event import WebhookEvent, WebhookEventOutcome
from app.webhooks.refund_handlers import handle_charge_refunded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _seed_pay_in_full_txn(
    db, *, creator, member,
    gross_cents: int = 20000,
    provider_charge_id: str | None = None,
    provider_payment_intent_id: str | None = None,
) -> PaymentTransaction:
    """A succeeded pay-in-full PaymentTransaction — the state the
    checkout.session.completed handler would leave the row in."""
    now = datetime.utcnow()
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=member.id,
        creator_user_id=creator.id,
        currency="AUD",
        gross_amount_cents=gross_cents,
        platform_fee_basis_points=0,
        platform_fee_cents=0,
        net_creator_amount_cents=gross_cents,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        provider_charge_id=provider_charge_id,
        provider_payment_intent_id=provider_payment_intent_id,
        created_at=now, updated_at=now,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def _seed_pay_in_full_purchase_with_access(db, make_user, make_space):
    """Seed a succeeded purchase PLUS the access rows the fulfilment
    would have written (AccessPass + PathwayEntitlement). Used to
    verify the refund handler never touches access state."""
    creator = make_user(role="creator")
    member = make_user()
    space = make_space(creator=creator)
    pathway = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="EMBODY In-Person Sessions", status="active",
        access_type="one_time", price_cents=20000,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(pathway)
    db.flush()
    now = datetime.utcnow()
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=member.id,
        creator_user_id=creator.id,
        space_id=space.id,
        pathway_id=pathway.id,
        currency="AUD",
        gross_amount_cents=20000,
        platform_fee_basis_points=0,
        platform_fee_cents=0,
        net_creator_amount_cents=20000,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        provider_payment_intent_id="pi_awaken_test",
        created_at=now, updated_at=now,
    )
    db.add(txn)
    db.flush()
    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now, created_at=now, updated_at=now,
    )
    db.add(ent)
    db.flush()
    ap = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn.id,
        pass_type=AccessPassType.pathway_access,
        status=AccessPassStatus.active,
        valid_from=now,
        grants_pathway_id=pathway.id,
        pathway_entitlement_id=ent.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add(ap)
    db.commit()
    db.refresh(txn); db.refresh(ent); db.refresh(ap)
    return {"creator": creator, "member": member, "space": space,
            "pathway": pathway, "txn": txn, "ent": ent, "pass": ap}


def _charge_dict(
    *, id: str, amount_refunded: int, refunded: bool,
    payment_intent: str | None = None,
) -> dict:
    """Minimal Stripe Charge shape — the fields the handler reads.
    Full Stripe charges carry many more fields; the handler only
    consults amount_refunded, refunded (bool), id, payment_intent."""
    return {
        "id": id,
        "amount_refunded": amount_refunded,
        "refunded": refunded,
        "payment_intent": payment_intent,
    }


def _fire_charge_refunded(
    db, *, charge: dict, event_id: str | None = None,
    event_created: int | None = None, event_livemode: bool = False,
) -> None:
    """Invoke the handler as the dispatcher would."""
    handle_charge_refunded(
        charge, db,
        provider_event_id=event_id or f"evt_{uuid.uuid4().hex[:12]}",
        event_created=event_created,
        event_livemode=event_livemode,
    )
    db.commit()


# Fixed instants used by monotonicity tests.
T1 = int(datetime(2026, 9, 11, 10, 0, 0).timestamp())
T2 = int(datetime(2026, 9, 11, 11, 0, 0).timestamp())
T3 = int(datetime(2026, 9, 11, 12, 0, 0).timestamp())


# ---------------------------------------------------------------------------
# 1. Basic refund semantics — full / partial / multiple partial.
# ---------------------------------------------------------------------------


class TestBasicRefundSemantics:
    def test_full_refund_flips_status_and_stamps_amount(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_test_1",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_test_1", amount_refunded=20000, refunded=True),
            event_created=T1,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 20000
        assert txn.status == PaymentTransactionStatus.refunded
        assert txn.last_refunded_at is not None

    def test_partial_refund_flips_status_partial_and_stamps_amount(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_test_2",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_test_2", amount_refunded=5000, refunded=False),
            event_created=T1,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 5000
        assert txn.status == PaymentTransactionStatus.partially_refunded

    def test_multiple_partial_refunds_accumulate_via_cumulative_amount(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_test_3",
        )
        # Two distinct events (different ids), first $50 then a second
        # partial that brings cumulative to $125.
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_test_3", amount_refunded=5000, refunded=False),
            event_id="evt_a", event_created=T1,
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_test_3", amount_refunded=12500, refunded=False),
            event_id="evt_b", event_created=T2,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 12500
        assert txn.status == PaymentTransactionStatus.partially_refunded

    def test_partial_then_full_reaches_full_status(self, db, make_user):
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_test_4",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_test_4", amount_refunded=5000, refunded=False),
            event_id="evt_1", event_created=T1,
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_test_4", amount_refunded=20000, refunded=True),
            event_id="evt_2", event_created=T2,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 20000
        assert txn.status == PaymentTransactionStatus.refunded


# ---------------------------------------------------------------------------
# 2. Monotonicity — out-of-order distinct events must not regress state.
# ---------------------------------------------------------------------------


class TestMonotonicGuards:
    def test_newer_partial_arrives_first_then_older_partial_does_not_regress(
        self, db, make_user,
    ):
        """First delivery: partial $200 (newer). Second delivery: an
        older partial $50 arrives out of order. Amount must stay at
        200; status must stay partially_refunded."""
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=30000, provider_charge_id="ch_ooo_1",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_ooo_1", amount_refunded=20000, refunded=False),
            event_id="evt_newer", event_created=T2,
        )
        db.refresh(txn)
        newer_stamp = txn.last_refunded_at
        assert txn.refunded_amount_cents == 20000

        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_ooo_1", amount_refunded=5000, refunded=False),
            event_id="evt_older", event_created=T1,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 20000   # not regressed
        assert txn.status == PaymentTransactionStatus.partially_refunded
        assert txn.last_refunded_at == newer_stamp   # not moved backwards

    def test_full_arrives_then_older_partial_stays_fully_refunded(
        self, db, make_user,
    ):
        """A ``refunded`` row must not downgrade to
        ``partially_refunded`` on a late older partial event."""
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_ooo_2",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_ooo_2", amount_refunded=20000, refunded=True),
            event_id="evt_full", event_created=T2,
        )
        db.refresh(txn)
        assert txn.status == PaymentTransactionStatus.refunded
        full_stamp = txn.last_refunded_at

        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_ooo_2", amount_refunded=5000, refunded=False),
            event_id="evt_late_partial", event_created=T1,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 20000
        assert txn.status == PaymentTransactionStatus.refunded    # not downgraded
        assert txn.last_refunded_at == full_stamp

    def test_timestamp_monotonic_across_same_amount_events(self, db, make_user):
        """Two distinct events with the SAME cumulative amount but
        different created timestamps, arriving out of order.
        ``last_refunded_at`` reflects the LATER created, not the one
        that arrived last."""
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_ts_1",
        )
        # First-delivered event carries the LATER created (T2).
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_ts_1", amount_refunded=5000, refunded=False),
            event_id="evt_ts_later", event_created=T2,
        )
        db.refresh(txn)
        later_stamp = txn.last_refunded_at

        # Second-delivered event carries the earlier created (T1) —
        # same cumulative amount, but timestamp must not regress.
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_ts_1", amount_refunded=5000, refunded=False),
            event_id="evt_ts_earlier", event_created=T1,
        )
        db.refresh(txn)
        assert txn.last_refunded_at == later_stamp


# ---------------------------------------------------------------------------
# 3. Same-event-id duplicate delivery is a no-op via WebhookEvent.
# ---------------------------------------------------------------------------


class TestSameEventIdIdempotency:
    def test_duplicate_delivery_of_same_event_is_noop(self, db, make_user):
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_idem_1",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_idem_1", amount_refunded=5000, refunded=False),
            event_id="evt_once", event_created=T1,
        )
        db.refresh(txn)
        first_amount = txn.refunded_amount_cents
        first_stamp = txn.last_refunded_at

        # Redeliver same event id — WebhookEvent already marks it
        # succeeded, so the handler body must not run.
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_idem_1", amount_refunded=99999, refunded=True),
            event_id="evt_once", event_created=T3,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == first_amount
        assert txn.last_refunded_at == first_stamp
        assert txn.status == PaymentTransactionStatus.partially_refunded

        # WebhookEvent row is present and succeeded.
        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == "evt_once")
            .one()
        )
        assert row.outcome == WebhookEventOutcome.succeeded


# ---------------------------------------------------------------------------
# 4. Lookup paths — charge id first, PI fallback, unknown charge skipped.
# ---------------------------------------------------------------------------


class TestChargeLookup:
    def test_pi_fallback_matches_and_backfills_charge_id(self, db, make_user):
        """Pay-in-full row: ``provider_charge_id`` is NULL,
        ``provider_payment_intent_id`` is set. The handler matches
        via PI and opportunistically backfills the charge id."""
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000,
            provider_charge_id=None,
            provider_payment_intent_id="pi_lookup_test",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(
                id="ch_backfill_1", amount_refunded=5000, refunded=False,
                payment_intent="pi_lookup_test",
            ),
            event_created=T1,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 5000
        assert txn.provider_charge_id == "ch_backfill_1"    # opportunistically backfilled

    def test_charge_id_lookup_matches_finite_plan_instalment(self, db, make_user):
        """Finite-plan handler populates ``provider_charge_id`` on
        write. Direct match, no PI fallback needed."""
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=2500, provider_charge_id="ch_instalment_3",
            provider_payment_intent_id="pi_instalment_3",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_instalment_3", amount_refunded=2500, refunded=True),
            event_created=T1,
        )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 2500
        assert txn.status == PaymentTransactionStatus.refunded

    def test_unknown_charge_is_skipped_not_500(self, db, make_user):
        """No matching row — record as skipped, don't raise."""
        creator = make_user(role="creator")
        make_user()  # payer, unused

        _fire_charge_refunded(
            db,
            charge=_charge_dict(
                id="ch_unknown", amount_refunded=5000, refunded=False,
                payment_intent="pi_unknown",
            ),
            event_id="evt_unknown", event_created=T1,
        )

        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == "evt_unknown")
            .one()
        )
        assert row.outcome == WebhookEventOutcome.skipped


# ---------------------------------------------------------------------------
# 5. Access-side state is NEVER touched by refund handling.
# ---------------------------------------------------------------------------


class TestRefundDoesNotTouchAccess:
    def test_full_refund_leaves_all_access_rows_intact(
        self, db, make_user, make_space,
    ):
        """A refund on a purchase that granted access must not
        cancel the pass, revoke the entitlement, or otherwise touch
        access state — that is a separate operator action via the
        Payments received revoke UI."""
        s = _seed_pay_in_full_purchase_with_access(db, make_user, make_space)

        _fire_charge_refunded(
            db,
            charge=_charge_dict(
                id="ch_awaken_test", amount_refunded=20000, refunded=True,
                payment_intent="pi_awaken_test",
            ),
            event_created=T1,
        )

        db.refresh(s["txn"])
        db.refresh(s["ent"])
        db.refresh(s["pass"])
        # Payment is refunded.
        assert s["txn"].status == PaymentTransactionStatus.refunded
        assert s["txn"].refunded_amount_cents == 20000
        # But access is untouched.
        assert s["ent"].status == EntitlementStatus.active
        assert s["ent"].revoked_at is None
        assert s["pass"].status == AccessPassStatus.active
        assert s["pass"].revoked_at is None


# ---------------------------------------------------------------------------
# 6. Summary aggregation follows the revised Gross / Refunds / Net Retained
#    semantics.
# ---------------------------------------------------------------------------


class TestPaymentSummarySemantics:
    def test_no_refunds_gross_equals_net_retained(self, db, make_user):
        creator = make_user(role="creator")
        member = make_user()
        _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_none",
        )
        summary = get_creator_payment_summary(current_user=creator, db=db)
        assert summary.total_gross_amount_cents == 20000
        assert summary.total_refunded_amount_cents == 0
        assert summary.total_net_retained_amount_cents == 20000
        assert summary.succeeded_count == 1
        assert summary.refunded_count == 0
        assert summary.partially_refunded_count == 0

    def test_partial_refund_reduces_net_retained(self, db, make_user):
        """Partial refund of $50 on a $200 sale → Gross=200,
        Refunds=50, Net Retained=150. Historically-successful row is
        still counted in gross."""
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_partial",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_partial", amount_refunded=5000, refunded=False),
            event_created=T1,
        )
        db.refresh(txn)

        summary = get_creator_payment_summary(current_user=creator, db=db)
        assert summary.total_gross_amount_cents == 20000
        assert summary.total_refunded_amount_cents == 5000
        assert summary.total_net_retained_amount_cents == 15000
        assert summary.succeeded_count == 0
        assert summary.refunded_count == 1
        assert summary.partially_refunded_count == 1

    def test_full_refund_nets_to_zero_but_stays_in_gross(self, db, make_user):
        """Fully-refunded row still contributes historical gross but
        nets to zero — Gross=200, Refunds=200, Net Retained=0."""
        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_full",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_full", amount_refunded=20000, refunded=True),
            event_created=T1,
        )
        db.refresh(txn)

        summary = get_creator_payment_summary(current_user=creator, db=db)
        assert summary.total_gross_amount_cents == 20000
        assert summary.total_refunded_amount_cents == 20000
        assert summary.total_net_retained_amount_cents == 0
        assert summary.succeeded_count == 0
        assert summary.refunded_count == 1
        assert summary.partially_refunded_count == 0

    def test_mixed_purchases_aggregate_correctly(self, db, make_user):
        """One succeeded + one partial + one fully refunded across
        three rows. Verifies the three figures at once."""
        creator = make_user(role="creator")
        member = make_user()
        # 1) $100 succeeded
        _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=10000, provider_charge_id="ch_mix_1",
        )
        # 2) $200 sale, $50 partial refund → net 150
        txn2 = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_mix_2",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_mix_2", amount_refunded=5000, refunded=False),
            event_id="evt_mix_2", event_created=T1,
        )
        db.refresh(txn2)
        # 3) $50 sale, fully refunded → net 0
        txn3 = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=5000, provider_charge_id="ch_mix_3",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_mix_3", amount_refunded=5000, refunded=True),
            event_id="evt_mix_3", event_created=T2,
        )
        db.refresh(txn3)

        summary = get_creator_payment_summary(current_user=creator, db=db)
        assert summary.total_gross_amount_cents == 35000  # 100 + 200 + 50
        assert summary.total_refunded_amount_cents == 10000  # 50 + 50
        assert summary.total_net_retained_amount_cents == 25000  # 100 + 150 + 0
        assert summary.succeeded_count == 1
        assert summary.refunded_count == 2  # combined (partial + fully)
        assert summary.partially_refunded_count == 1


# ---------------------------------------------------------------------------
# 7. List endpoint carries refund fields per row.
# ---------------------------------------------------------------------------


class TestRowShape:
    def test_list_row_includes_refund_state(self, db, make_user):
        from app.creator.routes import list_creator_payments

        creator = make_user(role="creator")
        member = make_user()
        txn = _seed_pay_in_full_txn(
            db, creator=creator, member=member,
            gross_cents=20000, provider_charge_id="ch_row_1",
        )
        _fire_charge_refunded(
            db,
            charge=_charge_dict(id="ch_row_1", amount_refunded=5000, refunded=False),
            event_created=T1,
        )
        db.refresh(txn)

        rows = list_creator_payments(current_user=creator, db=db)
        [row] = [r for r in rows if r.id == txn.id]
        assert row.status == "partially_refunded"
        assert row.refunded_amount_cents == 5000
        assert row.last_refunded_at is not None
