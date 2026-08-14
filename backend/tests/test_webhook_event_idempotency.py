"""FIP1 — webhook event idempotency helper (lease-based).

Verifies the durable guarantees documented in
``services/webhook_idempotency.py``:

* First event processes; row created + marked ``succeeded``.
* Duplicate delivery skips without re-invoking the handler.
* Failed handler leaves row ``failed`` + re-raises; retry works.
* ``SkipWebhookEvent`` marks the row ``skipped`` without failing.
* Uniqueness of ``(provider, provider_event_id)`` is DB-enforced.
* Genuinely concurrent delivery — one runs, the other skips as
  ``in_flight``.
* Stale ``pending`` row (dead worker) is reclaimed on later
  delivery and the handler runs.
* Crash-after-domain-commit — the handler was idempotent, so a
  replay after lease expiry does not duplicate the domain effect.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.models.webhook_event import WebhookEvent, WebhookEventOutcome
from app.services.webhook_idempotency import (
    ProcessOutcome,
    SkipWebhookEvent,
    process_webhook_event,
)


def _eid() -> str:
    return f"evt_test_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------


class TestFirstProcessing:
    def test_first_delivery_runs_handler_and_marks_succeeded(self, db):
        eid = _eid()
        calls = []

        def handler():
            calls.append(1)

        result = process_webhook_event(
            db,
            provider="stripe",
            provider_event_id=eid,
            event_type="checkout.session.completed",
            handler=handler,
        )

        assert result.result == "processed"
        assert calls == [1]

        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .one()
        )
        assert row.outcome == WebhookEventOutcome.succeeded
        assert row.processed_at is not None
        assert row.attempt_count == 1
        assert row.error_message is None
        # Lease timestamp is set on the initial insert.
        assert row.processing_started_at is not None


class TestDuplicateDelivery:
    def test_second_delivery_skips_without_running_handler(self, db):
        eid = _eid()
        calls = []

        def handler():
            calls.append(1)

        process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="checkout.session.completed", handler=handler,
        )
        assert calls == [1]

        result = process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="checkout.session.completed", handler=handler,
        )
        assert result.result == "skipped"
        assert calls == [1]

        rows = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].outcome == WebhookEventOutcome.succeeded


class TestFailurePath:
    def test_failed_handler_marks_failed_and_reraises(self, db):
        eid = _eid()

        def handler():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            process_webhook_event(
                db, provider="stripe", provider_event_id=eid,
                event_type="checkout.session.completed", handler=handler,
            )

        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .one()
        )
        assert row.outcome == WebhookEventOutcome.failed
        assert row.error_message == "boom"
        assert row.processed_at is None
        assert row.attempt_count == 1

    def test_retry_after_failure_reruns_and_succeeds(self, db):
        eid = _eid()
        calls = []

        def flaky_handler():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("temporary")

        with pytest.raises(RuntimeError):
            process_webhook_event(
                db, provider="stripe", provider_event_id=eid,
                event_type="invoice.payment_succeeded", handler=flaky_handler,
            )

        result = process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="invoice.payment_succeeded", handler=flaky_handler,
        )
        assert result.result == "processed"
        assert calls == [1, 1]

        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .one()
        )
        assert row.outcome == WebhookEventOutcome.succeeded
        assert row.attempt_count == 2
        assert row.error_message is None
        assert row.processed_at is not None


class TestSkipEvent:
    def test_skip_event_marks_skipped_without_reraise(self, db):
        eid = _eid()

        def handler():
            raise SkipWebhookEvent("event type not handled by this deployment")

        result = process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="charge.dispute.created", handler=handler,
        )
        assert result.result == "skipped"

        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .one()
        )
        assert row.outcome == WebhookEventOutcome.skipped
        assert row.processed_at is not None


class TestUniqueConstraint:
    def test_provider_event_id_unique_per_provider(self, db):
        from sqlalchemy.exc import IntegrityError

        eid = _eid()
        process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="checkout.session.completed",
            handler=lambda: None,
        )
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO webhook_events "
                    "(id, provider, provider_event_id, event_type, outcome) "
                    "VALUES ('whe_dup', 'stripe', :eid, 'checkout.session.completed', 'pending')"
                ),
                {"eid": eid},
            )
            db.flush()
        db.rollback()

    def test_same_event_id_different_provider_is_ok(self, db):
        eid = _eid()
        process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="a", handler=lambda: None,
        )
        process_webhook_event(
            db, provider="other-provider", provider_event_id=eid,
            event_type="b", handler=lambda: None,
        )
        rows = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .all()
        )
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Lease-based recovery — the FIP1 hardening additions
# ---------------------------------------------------------------------------


class TestConcurrentDelivery:
    def test_second_delivery_while_first_in_flight_returns_in_flight(self, db):
        """Genuine concurrency simulation.

        Worker A begins processing (its handler is arbitrarily slow).
        Worker B arrives with the same event id while A's lease is
        still fresh. B must not execute the handler — it should
        return ``in_flight``.

        We simulate A's mid-processing state by manually inserting a
        ``pending`` row with a *just-set* ``processing_started_at``,
        then calling the helper on the same event id. The helper
        must see the fresh lease and skip.
        """
        eid = _eid()
        # Simulate worker A's committed pending row (mid-handler).
        row_id = f"whe_{uuid.uuid4().hex[:24]}"
        db.execute(
            text("""
                INSERT INTO webhook_events (
                    id, provider, provider_event_id, event_type,
                    outcome, received_at, processing_started_at, attempt_count
                ) VALUES (
                    :id, 'stripe', :eid, 'invoice.payment_succeeded',
                    'pending', :now, :now, 1
                )
            """),
            {"id": row_id, "eid": eid, "now": datetime.utcnow()},
        )
        db.commit()

        # Worker B arrives now.
        calls = []
        result = process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="invoice.payment_succeeded",
            handler=lambda: calls.append(1),
            lease_seconds=300,  # 5-minute lease — row is fresh.
        )
        assert result.result == "in_flight"
        assert calls == []  # handler never ran

        # Row is unchanged.
        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .one()
        )
        assert row.outcome == WebhookEventOutcome.pending
        assert row.attempt_count == 1


class TestStalePendingReclaim:
    def test_stale_pending_row_is_reclaimed_and_processed(self, db):
        """A crashed worker's pending row is recovered by the next delivery.

        Simulate: worker A committed a ``pending`` row and then
        died — its ``processing_started_at`` is 10 minutes old.
        Worker B arrives; with a 5-second lease the row is stale
        and should be reclaimed + handler executed.
        """
        eid = _eid()
        stale_ts = datetime.utcnow() - timedelta(minutes=10)
        row_id = f"whe_{uuid.uuid4().hex[:24]}"
        db.execute(
            text("""
                INSERT INTO webhook_events (
                    id, provider, provider_event_id, event_type,
                    outcome, received_at, processing_started_at, attempt_count
                ) VALUES (
                    :id, 'stripe', :eid, 'invoice.payment_succeeded',
                    'pending', :ts, :ts, 1
                )
            """),
            {"id": row_id, "eid": eid, "ts": stale_ts},
        )
        db.commit()

        calls = []
        result = process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="invoice.payment_succeeded",
            handler=lambda: calls.append(1),
            lease_seconds=5,  # 5-second lease — 10-minute row is stale.
        )
        assert result.result == "processed"
        assert calls == [1]  # handler ran

        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .one()
        )
        assert row.outcome == WebhookEventOutcome.succeeded
        assert row.attempt_count == 2  # incremented on reclaim
        assert row.processing_started_at is not None
        assert row.processing_started_at > stale_ts
        assert row.error_message is None


class TestCrashAfterDomainCommit:
    """Crash-after-domain-commit safety.

    The riskiest failure mode: handler runs, commits its domain
    writes, then the worker dies before the helper marks the row
    ``succeeded``. The row stays ``pending`` until the lease
    expires; a later delivery reclaims and re-runs the handler.

    The handler MUST be idempotent — see the contract in
    ``services/webhook_idempotency.py``. This test uses a
    representative idempotent handler backed by a natural key
    (``provider_invoice_id``) and verifies that a replay produces
    exactly one domain row, not two.
    """

    def test_replay_after_crash_does_not_duplicate_domain_writes(self, db):
        eid = _eid()
        invoice_key = f"in_test_{uuid.uuid4().hex[:12]}"

        # An idempotent handler: uses ``INSERT ... ON CONFLICT DO
        # NOTHING`` keyed on ``provider_invoice_id`` so a replay
        # after a crash writes zero new rows. This is exactly the
        # pattern FIP2/FIP3 handlers must adopt.
        def idempotent_handler():
            # Guard against duplicate insertion via a pre-check on
            # the natural key. FIP2/FIP3 handlers should use this
            # pattern (or a DB unique constraint + ON CONFLICT DO
            # NOTHING) so a lease-triggered replay does not
            # produce a second PaymentTransaction row.
            already = db.execute(
                text(
                    "SELECT id FROM payment_transactions "
                    "WHERE provider_invoice_id = :i"
                ),
                {"i": invoice_key},
            ).first()
            if already is not None:
                return
            db.execute(
                text("""
                    INSERT INTO payment_transactions (
                        id, transaction_type, status, payment_provider,
                        currency, gross_amount_cents,
                        platform_fee_basis_points, platform_fee_cents,
                        payout_status, provider_invoice_id,
                        fulfilment_status, stripe_mode
                    ) VALUES (
                        :id, 'member_payment_option_purchase', 'succeeded', 'stripe',
                        'AUD', 2000, 800, 160, 'pending', :invoice,
                        'applied', 'test'
                    )
                """),
                {
                    "id": f"txn_{uuid.uuid4().hex[:16]}",
                    "invoice": invoice_key,
                },
            )
            db.commit()

        # ── Step 1: simulate worker A that committed the domain
        # write but died before marking outcome. We insert the
        # pending row + call the handler directly, then leave the
        # webhook_events row in ``pending`` with a stale timestamp.
        stale_ts = datetime.utcnow() - timedelta(minutes=10)
        row_id = f"whe_{uuid.uuid4().hex[:24]}"
        db.execute(
            text("""
                INSERT INTO webhook_events (
                    id, provider, provider_event_id, event_type,
                    outcome, received_at, processing_started_at, attempt_count
                ) VALUES (
                    :id, 'stripe', :eid, 'invoice.payment_succeeded',
                    'pending', :ts, :ts, 1
                )
            """),
            {"id": row_id, "eid": eid, "ts": stale_ts},
        )
        db.commit()
        idempotent_handler()  # domain write committed by worker A

        # Sanity: one domain row exists.
        count_before = db.execute(
            text(
                "SELECT COUNT(*) FROM payment_transactions "
                "WHERE provider_invoice_id = :i"
            ),
            {"i": invoice_key},
        ).scalar_one()
        assert count_before == 1

        # ── Step 2: worker B arrives after lease expiry. Should
        # reclaim the pending row, re-run the handler. Because the
        # handler is idempotent, no second domain row is written.
        result = process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="invoice.payment_succeeded",
            handler=idempotent_handler,
            lease_seconds=5,
        )
        assert result.result == "processed"

        # Domain state is unchanged — still one row.
        count_after = db.execute(
            text(
                "SELECT COUNT(*) FROM payment_transactions "
                "WHERE provider_invoice_id = :i"
            ),
            {"i": invoice_key},
        ).scalar_one()
        assert count_after == 1

        # Webhook row is now succeeded.
        row = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == eid)
            .one()
        )
        assert row.outcome == WebhookEventOutcome.succeeded
        assert row.attempt_count == 2


class TestReclaimUnderConcurrentContention:
    def test_two_workers_racing_to_reclaim_stale_row_only_one_wins(self, db):
        """When two deliveries observe the same stale row, exactly one reclaims.

        The reclaim UPDATE is guarded by the age predicate. If two
        workers try to reclaim simultaneously, one wins, the other's
        UPDATE touches zero rows, and the loser treats the row as
        in-flight (the winner is now processing).
        """
        eid = _eid()
        stale_ts = datetime.utcnow() - timedelta(minutes=10)
        row_id = f"whe_{uuid.uuid4().hex[:24]}"
        db.execute(
            text("""
                INSERT INTO webhook_events (
                    id, provider, provider_event_id, event_type,
                    outcome, received_at, processing_started_at, attempt_count
                ) VALUES (
                    :id, 'stripe', :eid, 'invoice.payment_succeeded',
                    'pending', :ts, :ts, 1
                )
            """),
            {"id": row_id, "eid": eid, "ts": stale_ts},
        )
        db.commit()

        # Worker A reclaims + starts processing (long-running).
        # We simulate mid-processing by running the reclaim UPDATE
        # directly without invoking the handler yet.
        now = datetime.utcnow()
        reclaimed = db.execute(
            text(
                "UPDATE webhook_events "
                "SET outcome = 'pending', "
                "    processing_started_at = :now, "
                "    attempt_count = attempt_count + 1 "
                "WHERE id = :id "
                "AND outcome = 'pending' "
                "AND processing_started_at < :cutoff "
                "RETURNING id"
            ),
            {
                "id": row_id, "now": now,
                "cutoff": now - timedelta(seconds=5),
            },
        ).first()
        db.commit()
        assert reclaimed is not None  # A won the lease

        # Worker B arrives — sees a freshly-leased pending row.
        calls = []
        result = process_webhook_event(
            db, provider="stripe", provider_event_id=eid,
            event_type="invoice.payment_succeeded",
            handler=lambda: calls.append(1),
            lease_seconds=300,
        )
        assert result.result == "in_flight"
        assert calls == []
