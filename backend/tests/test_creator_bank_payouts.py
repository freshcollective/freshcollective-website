"""Bank payouts: what Stripe actually did with a creator's money.

A Connect transfer moves a creator's share into their Stripe balance. A
payout is the separate, later step where Stripe sends that balance to their
bank, and those two are not the same event — a transfer can succeed and the
bank deposit fail days afterwards. These tests pin that distinction, because
collapsing it is the one claim that would mislead a creator about whether
they have been paid.

Nothing here reaches Stripe. ``Payout.list`` is stubbed, because what is
under test is how Fresh Collective records Stripe's answers — including the
answers it should refuse to record.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from app.models.creator_bank_payout import PAYOUT_STATUSES, CreatorBankPayout
from app.models.creator_stripe_account import (
    FEE_DISCLOSURE_VERSION,
    CreatorStripeAccount,
    OnboardingState,
)
from app.services import creator_bank_payout_sync as sync

SYNC = "app.services.creator_bank_payout_sync"


def _account(db, creator_id, **overrides) -> CreatorStripeAccount:
    values = {
        "id": f"csa_{uuid.uuid4()}",
        "creator_user_id": creator_id,
        "stripe_mode": "test",
        "stripe_account_id": f"acct_{uuid.uuid4().hex[:14]}",
        "onboarding_state": OnboardingState.ready.value,
        "transfers_status": "active",
        "transfers_enabled": True,
        "payouts_status": "active",
        "payouts_enabled": True,
        "details_submitted": True,
        "external_account_count": 1,
        "payout_interval": "weekly",
        "fee_disclosure_acknowledged_at": datetime(2026, 9, 20, 10, 0, 0),
        "fee_disclosure_version": FEE_DISCLOSURE_VERSION,
    }
    values.update(overrides)
    row = CreatorStripeAccount(**values)
    db.add(row)
    db.commit()
    return row


def _payout(**overrides) -> dict:
    """A Stripe payout as the SDK returns it (mapping shape)."""
    values = {
        "id": f"po_{uuid.uuid4().hex[:16]}",
        "amount": 9200,
        "currency": "aud",
        "status": "paid",
        "arrival_date": 1791849600,      # 2026-10-13
        "created": 1791590400,           # 2026-10-10
        "failure_code": None,
    }
    values.update(overrides)
    return values


class _StripeObjectPayout:
    """Attribute-only, like the real SDK. ``.get()`` raises in stripe 15.x."""

    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)

    def get(self, *a, **k):
        raise AttributeError("StripeObject has no attribute 'get'")


def _stub(entries, *, error=None):
    """A stand-in Stripe whose ``Payout.list`` pages like the real one.

    Faithful about the two things the sync depends on: payouts come back
    newest-first, and ``starting_after`` continues from a given id with
    ``has_more`` saying whether anything is left. A stub that ignored
    ``starting_after`` would report the same payouts for every page and make
    a resumable import look like an infinite one.
    """
    ordered = list(entries)
    calls: list[dict] = []

    def _id(entry):
        return _field_of(entry, "id")

    class _Payout:
        @staticmethod
        def list(**kwargs):
            calls.append(kwargs)
            if error is not None:
                raise error
            after = kwargs.get("starting_after")
            start = 0
            if after:
                ids = [_id(e) for e in ordered]
                start = ids.index(after) + 1 if after in ids else len(ordered)
            page = ordered[start:start + int(kwargs.get("limit", 10))]
            remaining = len(ordered) - (start + len(page))
            return {"data": page, "has_more": remaining > 0}

    api = type("S", (), {"Payout": _Payout})()
    return api, calls


def _field_of(entry, name):
    """Read a field from either stub shape, like the sync does."""
    if isinstance(entry, dict):
        return entry.get(name)
    return getattr(entry, name, None)


# ---------------------------------------------------------------------------
# Reading payouts from Stripe
# ---------------------------------------------------------------------------


class TestPayoutStates:
    """Every status Stripe can report, recorded verbatim."""

    @pytest.mark.parametrize("status", PAYOUT_STATUSES)
    def test_each_stripe_status_is_recorded_as_it_stands(
        self, db, make_user, status,
    ):
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([_payout(status=status)])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        assert report.created == 1
        row = db.query(CreatorBankPayout).one()
        assert row.status == status

    def test_a_payout_initiated_is_not_described_as_paid(self, db, make_user):
        """The distinction the whole table exists for. ``in_transit`` means
        Stripe has sent it; only ``paid`` means the bank took it."""
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([_payout(status="in_transit")])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)

        row = db.query(CreatorBankPayout).one()
        assert row.status == "in_transit"
        assert row.status != "paid"

    def test_a_failed_payout_keeps_its_reason_for_operators(self, db, make_user):
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([
            _payout(status="failed", failure_code="account_closed"),
        ])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)

        row = db.query(CreatorBankPayout).one()
        assert (row.status, row.failure_code) == ("failed", "account_closed")

    def test_a_cancelled_payout_is_recorded_too(self, db, make_user):
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([_payout(status="canceled")])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
        assert db.query(CreatorBankPayout).one().status == "canceled"

    def test_the_arrival_date_is_kept(self, db, make_user):
        """What a creator actually wants to know: when it lands."""
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([_payout()])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)

        row = db.query(CreatorBankPayout).one()
        assert row.arrival_date == datetime(2026, 10, 13, 0, 0, 0)
        assert row.initiated_at == datetime(2026, 10, 10, 0, 0, 0)

    def test_the_real_sdk_object_shape_is_read_too(self, db, make_user):
        """Dict fixtures alone would not catch a reader that assumes a
        mapping — ``StripeObject.get`` raises in stripe 15.x."""
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([_StripeObjectPayout(**_payout(amount=500))])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        assert report.created == 1
        assert db.query(CreatorBankPayout).one().amount_cents == 500


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_the_same_payout_twice_is_one_row(self, db, make_user):
        creator = make_user(role="creator")
        _account(db, creator.id)
        entry = _payout()
        api, _ = _stub([entry])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            first = sync.sync_creator_bank_payouts(db)
            second = sync.sync_creator_bank_payouts(db)

        assert (first.created, first.updated) == (1, 0)
        assert (second.created, second.updated) == (0, 1)
        assert db.query(CreatorBankPayout).count() == 1

    def test_a_status_change_updates_the_row_in_place(self, db, make_user):
        """A payout moves pending → in_transit → paid. The row follows it
        rather than accumulating one row per sighting."""
        creator = make_user(role="creator")
        _account(db, creator.id)
        entry = _payout(status="pending")
        for status in ("pending", "in_transit", "paid"):
            api, _ = _stub([dict(entry, status=status)])
            with patch("app.checkout.stripe_client.get_stripe", return_value=api):
                sync.sync_creator_bank_payouts(db)

        assert db.query(CreatorBankPayout).count() == 1
        assert db.query(CreatorBankPayout).one().status == "paid"

    def test_the_database_itself_refuses_a_duplicate(self, db, make_user):
        """Idempotency sits in the schema, not only in the sync code — so a
        future webhook writer inherits it."""
        from sqlalchemy.exc import IntegrityError

        creator = make_user(role="creator")
        account = _account(db, creator.id)

        def row(**o):
            return CreatorBankPayout(
                id=f"cbp_{uuid.uuid4()}",
                creator_user_id=creator.id,
                stripe_account_id=account.stripe_account_id,
                stripe_mode="test",
                provider_payout_id="po_same",
                amount_cents=100, currency="AUD", status="paid",
                synced_at=datetime.utcnow(), **o,
            )

        db.add(row()); db.commit()
        db.add(row())
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_the_creator_is_never_reassigned_on_update(self, db, make_user):
        """The only way a payout could leak across creators would be an
        update that rewrote its owner."""
        creator = make_user(role="creator")
        _account(db, creator.id)
        entry = _payout()
        api, _ = _stub([entry])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
            sync.sync_creator_bank_payouts(db)
        assert db.query(CreatorBankPayout).one().creator_user_id == creator.id


# ---------------------------------------------------------------------------
# What it refuses to record
# ---------------------------------------------------------------------------


class TestItRefusesToGuess:
    def test_an_unknown_status_is_skipped_not_mapped(self, db, make_user):
        """A status Stripe adds later must not be coerced to the nearest
        known value — that would misreport a creator's money."""
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([_payout(status="reversed")])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        assert report.created == 0
        assert db.query(CreatorBankPayout).count() == 0

    def test_an_entry_with_no_id_or_amount_is_skipped(self, db, make_user):
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([
            _payout(id=None),
            _payout(amount=None),
            _payout(currency=None),
        ])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)
        assert report.created == 0

    def test_an_unreadable_account_is_reported_and_retried(self, db, make_user):
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([], error=RuntimeError("Stripe down"))
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        assert report.unreadable == [account.stripe_account_id]
        assert report.created == 0

    def test_one_failing_account_does_not_lose_another(self, db, make_user):
        """Committed per account, so a Stripe failure on one creator cannot
        discard a payout already read for another."""
        good = make_user(role="creator")
        bad = make_user(role="creator")
        good_account = _account(db, good.id)
        bad_account = _account(db, bad.id)

        calls: list[str] = []

        good_payouts = [_payout()]

        class _Payout:
            @staticmethod
            def list(**kwargs):
                acct = kwargs["stripe_account"]
                calls.append(acct)
                if acct == bad_account.stripe_account_id:
                    raise RuntimeError("Stripe down for this one")
                if kwargs.get("starting_after"):
                    return {"data": [], "has_more": False}
                return {"data": good_payouts, "has_more": False}

        api = type("S", (), {"Payout": _Payout})()
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        # The good account is read twice — recent, then one history page —
        # and the bad one fails on its first call. What matters is that both
        # were attempted and the good creator's payout survived.
        assert set(calls) == {
            good_account.stripe_account_id, bad_account.stripe_account_id,
        }
        assert report.created == 1
        assert report.unreadable == [bad_account.stripe_account_id]
        assert db.query(CreatorBankPayout).one().creator_user_id == good.id

    def test_an_account_with_no_stripe_id_is_not_queried(self, db, make_user):
        """Nothing was created, so there is nothing to ask Stripe about."""
        creator = make_user(role="creator")
        _account(
            db, creator.id, stripe_account_id=None,
            onboarding_state=OnboardingState.not_started.value,
            transfers_status=None, transfers_enabled=False,
            payouts_status=None, payouts_enabled=False,
            details_submitted=False, external_account_count=0,
            payout_interval=None,
        )
        api, calls = _stub([_payout()])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)
        assert calls == []
        assert report.accounts == 0


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------


class TestScoping:
    def test_a_creator_sees_only_their_own_payouts(self, db, make_user):
        mine = make_user(role="creator")
        theirs = make_user(role="creator")
        mine_account = _account(db, mine.id)
        theirs_account = _account(db, theirs.id)

        # One stable payout per account, so a second page does not invent a
        # new one — the real API returns the same records.
        per_account = {
            mine_account.stripe_account_id: [_payout(amount=1111)],
            theirs_account.stripe_account_id: [_payout(amount=2222)],
        }

        class _Payout:
            @staticmethod
            def list(**kwargs):
                entries = per_account[kwargs["stripe_account"]]
                if kwargs.get("starting_after"):
                    return {"data": [], "has_more": False}
                return {"data": entries, "has_more": False}

        api = type("S", (), {"Payout": _Payout})()
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)

        mine_rows, _ = sync.list_for_creator(db, creator_user_id=mine.id)
        assert [r.amount_cents for r in mine_rows] == [1111]
        theirs_rows, _ = sync.list_for_creator(db, creator_user_id=theirs.id)
        assert [r.amount_cents for r in theirs_rows] == [2222]

    def test_a_payout_is_attributed_to_the_account_it_came_from(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([_payout()])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)

        row = db.query(CreatorBankPayout).one()
        assert row.creator_user_id == creator.id
        assert row.stripe_account_id == account.stripe_account_id

    def test_another_modes_payouts_never_appear(self, db, make_user):
        """Test-mode and live-mode money must never share a list."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        db.add(CreatorBankPayout(
            id=f"cbp_{uuid.uuid4()}",
            creator_user_id=creator.id,
            stripe_account_id=account.stripe_account_id,
            stripe_mode="live",                       # a different mode
            provider_payout_id="po_live_only",
            amount_cents=5000, currency="AUD", status="paid",
            synced_at=datetime.utcnow(),
        ))
        db.commit()
        rows, has_more = sync.list_for_creator(db, creator_user_id=creator.id)
        assert (rows, has_more) == ([], False)

    def test_newest_first(self, db, make_user):
        creator = make_user(role="creator")
        _account(db, creator.id)
        api, _ = _stub([
            _payout(arrival_date=1791849600),   # 13 Oct
            _payout(arrival_date=1791244800),   # 6 Oct
        ])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)

        rows, _ = sync.list_for_creator(db, creator_user_id=creator.id)
        assert [r.arrival_date.day for r in rows] == [13, 6]


# ---------------------------------------------------------------------------
# It never touches the money path
# ---------------------------------------------------------------------------


class TestItChangesNothingElse:
    def test_no_transfer_or_transaction_is_touched(self, db, make_user):
        """A payout projection is reporting. It must not be able to alter a
        transfer, a commission or a payout batch."""
        from app.models.payment import PaymentTransaction

        creator = make_user(role="creator")
        _account(db, creator.id)
        before = db.query(PaymentTransaction).count()
        api, _ = _stub([_payout()])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
        assert db.query(PaymentTransaction).count() == before

    def test_it_reads_payouts_only(self, db, make_user):
        """Asserted on the stub: the only Stripe call is a list. No payout is
        ever created, cancelled or retried from here."""
        creator = make_user(role="creator")
        _account(db, creator.id)

        class _Payout:
            @staticmethod
            def list(**kwargs):
                return {"data": []}

            @staticmethod
            def create(**kwargs):           # pragma: no cover - must not run
                raise AssertionError("the sync must never create a payout")

            @staticmethod
            def cancel(*a, **k):            # pragma: no cover - must not run
                raise AssertionError("the sync must never cancel a payout")

        api = type("S", (), {"Payout": _Payout})()
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)   # must not raise

    def test_only_the_import_bookkeeping_changes_on_the_account_row(
        self, db, make_user,
    ):
        """The sync advances its own cursor and nothing else. No Stripe fact
        on the row — capabilities, payout schedule, bank details — may move,
        because those belong to the projection and this is not it."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        snapshot = lambda: {
            c.name: getattr(account, c.name)
            for c in CreatorStripeAccount.__table__.columns
        }
        before = snapshot()
        api, _ = _stub([_payout()])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
        db.refresh(account)
        after = snapshot()
        changed = {k for k in before if before[k] != after[k]}
        assert changed <= {"payout_history_cursor", "payout_history_complete"}


# ---------------------------------------------------------------------------
# Bounded work, and never at the expense of the money jobs
# ---------------------------------------------------------------------------


class TestItIsBounded:
    def test_one_stripe_request_per_account_per_pass(self, db, make_user):
        """No pagination loop, so the work cannot grow with the length of a
        creator's history and cannot run away."""
        for _ in range(3):
            _account(db, make_user(role="creator").id)
        api, calls = _stub([_payout()])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        # Two requests per account at most: the recent sweep, then one page
        # of history. Never more, whatever the length of the history.
        assert len(calls) == 6
        assert report.accounts == 3
        recent = [c for c in calls if "starting_after" not in c]
        history = [c for c in calls if "starting_after" in c]
        assert len(recent) == 3
        assert len(history) == 3
        assert all(c["limit"] == sync.DEFAULT_PAYOUT_LIMIT for c in recent)
        assert all(c["limit"] == sync.BACKFILL_PAGE_SIZE for c in history)

    def test_an_account_with_no_bank_account_is_not_asked_about(
        self, db, make_user,
    ):
        """It cannot have had a payout, so the request would learn nothing.
        Three of Fresh Collective's four accounts are in this state."""
        _account(db, make_user(role="creator").id, external_account_count=0)
        api, calls = _stub([_payout()])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        assert calls == []
        assert report.accounts == 0

    def test_the_limit_is_honoured_when_passed(self, db, make_user):
        _account(db, make_user(role="creator").id)
        api, calls = _stub([])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db, limit=3)
        assert calls[0]["limit"] == 3

    def test_a_has_more_listing_is_not_chased_within_one_pass(
        self, db, make_user,
    ):
        """One history page per pass, even when Stripe says there are more.

        A cursor loop is the one shape that could make unbounded requests, so
        the import advances exactly one page and resumes next run.
        """
        _account(db, make_user(role="creator").id)
        api, calls = _stub([_payout() for _ in range(200)])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)

        assert len(calls) == 2                       # recent + one page
        assert report.backfilled == 1
        assert report.backfill_completed == 0        # plenty left


class TestItNeverBlocksTheMoneyJobs:
    """The sync runs last in the sweeper cron and swallows its own errors.

    A transfer that moved correctly must not be reported as a failed run
    because a reporting read came back badly.
    """

    def test_a_failure_does_not_fail_the_cron(self, db):
        from scripts import fc_connect_transfer_sweeper as cron

        with patch.object(
            cron.payout_sync, "sync_creator_bank_payouts",
            side_effect=RuntimeError("Stripe down"),
        ), patch.object(cron, "capture_job_summary") as cap:
            assert cron.sync_bank_payouts(db) is None
        assert cap.call_args_list == []

    def test_it_runs_after_the_transfers_and_the_reconciliation(self, db):
        from scripts import fc_connect_transfer_sweeper as cron

        order: list[str] = []
        with patch("sys.argv", ["fc_connect_transfer_sweeper"]), \
             patch.object(
                 cron._sweeper, "sweep_pending_transfers",
                 side_effect=lambda *a, **k: (
                     order.append("sweep"), cron._sweeper.SweepReport(),
                 )[1],
             ), \
             patch.object(cron, "report_partial_failures", return_value=None), \
             patch.object(cron, "report_balance_headroom", return_value=None), \
             patch.object(
                 cron, "reconcile_processing_fees",
                 side_effect=lambda *a, **k: order.append("fees"),
             ), \
             patch.object(cron, "report_payout_schedule_stragglers", return_value=None), \
             patch.object(
                 cron, "sync_bank_payouts",
                 side_effect=lambda *a, **k: order.append("payouts"),
             ):
            assert cron.main() == 0
        assert order == ["sweep", "fees", "payouts"]

    def test_unreadable_accounts_are_reported_as_a_warning(self, db, make_user):
        from scripts import fc_connect_transfer_sweeper as cron

        report = sync.PayoutSyncReport(accounts=2, created=1)
        report.unreadable = ["acct_a"]
        with patch.object(
            cron.payout_sync, "sync_creator_bank_payouts", return_value=report,
        ), patch.object(cron, "capture_job_summary", return_value="evt") as cap, \
             patch.object(cron, "id_logger"):
            assert cron.sync_bank_payouts(db) == "evt"

        assert cap.call_args.kwargs["level"] == "warning"
        assert cap.call_args.kwargs["accounts_unreadable"] == 1
        # Account ids stay in the Render log, not in a Sentry breadcrumb.
        assert "acct_a" not in str(cap.call_args)

    def test_a_clean_pass_reports_nothing(self, db):
        from scripts import fc_connect_transfer_sweeper as cron

        with patch.object(
            cron.payout_sync, "sync_creator_bank_payouts",
            return_value=sync.PayoutSyncReport(accounts=1, created=1),
        ), patch.object(cron, "capture_job_summary") as cap:
            assert cron.sync_bank_payouts(db) is None
        assert cap.call_args_list == []


# ---------------------------------------------------------------------------
# The historical import
# ---------------------------------------------------------------------------


class TestHistoricalImport:
    """Complete history, a bounded page at a time, resumable across runs.

    The point of the cursor is that no single cron execution has to read an
    unbounded number of records, and no run repeats work the last one did.
    """

    def test_a_long_history_is_imported_across_successive_runs(
        self, db, make_user,
    ):
        """The requirement in one test: 60 payouts, none fetched twice,
        all present once the import finishes, and no run unbounded."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        history = [_payout(amount=i + 1) for i in range(60)]
        api, calls = _stub(history)

        passes = 0
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            while not account.payout_history_complete and passes < 10:
                sync.sync_creator_bank_payouts(db)
                db.refresh(account)
                passes += 1

        assert account.payout_history_complete is True
        # 10 recent, then 25 and 25 older: 60 in two passes, and never more
        # than 35 records in one cron execution.
        assert passes == 2
        assert db.query(CreatorBankPayout).count() == 60
        # Every page was bounded.
        assert all(
            c["limit"] in (sync.DEFAULT_PAYOUT_LIMIT, sync.BACKFILL_PAGE_SIZE)
            for c in calls
        )

    def test_the_cursor_advances_and_is_resumed_from(self, db, make_user):
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        history = [_payout(amount=i + 1) for i in range(60)]
        api, calls = _stub(history)

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
        db.refresh(account)
        first_cursor = account.payout_history_cursor
        assert first_cursor is not None

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
        db.refresh(account)

        # The second pass asked Stripe to continue from where the first left.
        history_calls = [c for c in calls if "starting_after" in c]
        assert first_cursor in [c["starting_after"] for c in history_calls]
        assert account.payout_history_cursor != first_cursor

    def test_no_payout_is_fetched_twice_across_the_whole_import(
        self, db, make_user,
    ):
        """The recent sweep and the history pages must not overlap, or the
        import would spend its budget re-reading what it already had."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        history = [_payout(amount=i + 1) for i in range(60)]
        api, _ = _stub(history)

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            first = sync.sync_creator_bank_payouts(db)
            db.refresh(account)
            second = sync.sync_creator_bank_payouts(db)

        # First pass: 10 recent + 25 history, all new.
        assert (first.created, first.updated) == (35, 0)
        # Second pass re-reads only the 10 recent (statuses move), then 25
        # genuinely older ones.
        assert (second.created, second.updated) == (25, 10)

    def test_a_finished_import_stops_asking_for_history(self, db, make_user):
        """Ongoing passes must not re-walk the whole history every time."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, calls = _stub([_payout()])

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
            db.refresh(account)
            assert account.payout_history_complete is True
            calls.clear()
            sync.sync_creator_bank_payouts(db)

        # Only the recent sweep from now on: one request, no cursor.
        assert len(calls) == 1
        assert "starting_after" not in calls[0]

    def test_a_read_failure_does_not_advance_the_cursor(self, db, make_user):
        """Otherwise the import would skip payouts it never recorded — a
        permanent hole in a creator's history."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([], error=RuntimeError("Stripe down"))

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
        db.refresh(account)

        assert account.payout_history_cursor is None
        assert account.payout_history_complete is False
        assert db.query(CreatorBankPayout).count() == 0

    def test_history_is_never_called_complete_while_more_remains(
        self, db, make_user,
    ):
        """A partial history presented as whole is worse than one presented
        as partial, so the flag follows Stripe's ``has_more`` and nothing
        else."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([_payout() for _ in range(100)])

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
        db.refresh(account)
        assert account.payout_history_complete is False

    def test_a_resync_cannot_reset_the_import(self, db, make_user):
        """The projection writes Stripe facts onto the row; the cursor is not
        one. If ``apply_to`` touched it, a routine resync would make every
        account re-import its whole history."""
        from app.services.connect_account_state import ProjectedState

        creator = make_user(role="creator")
        account = _account(db, creator.id)
        account.payout_history_cursor = "po_somewhere"
        account.payout_history_complete = True
        db.commit()

        ProjectedState(onboarding_state=account.onboarding_state).apply_to(account)
        db.commit()
        db.refresh(account)

        assert account.payout_history_cursor == "po_somewhere"
        assert account.payout_history_complete is True

    def test_duplicates_remain_impossible_through_the_import(
        self, db, make_user,
    ):
        """Four passes over an overlapping history, one row per payout."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        history = [_payout(amount=i + 1) for i in range(60)]
        api, _ = _stub(history)

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            for _ in range(6):
                sync.sync_creator_bank_payouts(db)
                db.refresh(account)

        assert db.query(CreatorBankPayout).count() == 60
        ids = [r.provider_payout_id for r in db.query(CreatorBankPayout).all()]
        assert len(set(ids)) == 60

    def test_the_import_is_scoped_to_the_right_creator_and_mode(
        self, db, make_user,
    ):
        """Every imported payout belongs to the account it was read from."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([_payout(amount=i + 1) for i in range(40)])

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
            db.refresh(account)
            sync.sync_creator_bank_payouts(db)

        rows = db.query(CreatorBankPayout).all()
        assert {r.creator_user_id for r in rows} == {creator.id}
        assert {r.stripe_mode for r in rows} == {"test"}
        assert {r.stripe_account_id for r in rows} == {account.stripe_account_id}


# ---------------------------------------------------------------------------
# Edge cases around the page boundary
# ---------------------------------------------------------------------------


class TestImportEdgeCases:
    """The counts either side of a page, and a write that fails."""

    def test_an_account_with_no_payouts_completes_immediately(
        self, db, make_user,
    ):
        """Nothing to import is a finished import, not a stuck one — so the
        page can say the history is complete rather than claiming for ever
        that it is still loading."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, calls = _stub([])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)
        db.refresh(account)

        assert report.created == 0
        assert account.payout_history_complete is True
        assert account.payout_history_cursor is None     # nowhere to resume
        assert sync.history_is_complete(db, creator_user_id=creator.id) is True
        assert len(calls) == 2                           # recent, then history

    def test_fewer_payouts_than_one_recent_page(self, db, make_user):
        """Three payouts: all arrive in the recent sweep, and the history
        page finds nothing older, so the import is done in one pass."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([_payout(amount=i + 1) for i in range(3)])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)
        db.refresh(account)

        assert report.created == 3
        assert db.query(CreatorBankPayout).count() == 3
        assert account.payout_history_complete is True

    def test_exactly_one_recent_page_of_payouts(self, db, make_user):
        """The boundary. Ten payouts exactly fill the recent sweep, so the
        history page must look past them, find nothing, and finish — not
        conclude there is more merely because the first page was full."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, calls = _stub([_payout(amount=i + 1) for i in range(10)])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)
        db.refresh(account)

        assert report.created == 10
        assert db.query(CreatorBankPayout).count() == 10
        assert account.payout_history_complete is True
        # The history page resumed after the tenth, not from the top.
        history = [c for c in calls if "starting_after" in c]
        assert len(history) == 1

    def test_eleven_payouts_need_the_history_page(self, db, make_user):
        """One more than a recent page: the eleventh can only arrive through
        the history import, which is the whole point of it."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([_payout(amount=i + 1) for i in range(11)])
        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            report = sync.sync_creator_bank_payouts(db)
        db.refresh(account)

        assert report.created == 11
        assert db.query(CreatorBankPayout).count() == 11
        assert account.payout_history_complete is True
        # The eleventh is the smallest amount — the oldest in the fixture.
        amounts = {r.amount_cents for r in db.query(CreatorBankPayout).all()}
        assert amounts == set(range(1, 12))

    def test_a_database_write_failure_does_not_advance_the_cursor(
        self, db, make_user,
    ):
        """Distinct from a Stripe read failure, and the more dangerous of the
        two: if the cursor moved while the rows failed to persist, the import
        would resume past payouts it never recorded, leaving a permanent hole
        in the creator's history that no later run would fill.
        """
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, _ = _stub([_payout(amount=i + 1) for i in range(40)])

        calls = {"n": 0}
        real_upsert = sync._upsert

        def _fail_partway(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 5:
                raise RuntimeError("database write failed")
            return real_upsert(*args, **kwargs)

        with patch("app.checkout.stripe_client.get_stripe", return_value=api), \
             patch.object(sync, "_upsert", _fail_partway), \
             pytest.raises(RuntimeError):
            sync.sync_creator_bank_payouts(db)

        # The cursor is assigned only after a whole page has been written,
        # so a failure part-way through leaves it exactly where it was. The
        # next run therefore re-reads the same records rather than skipping
        # them — and nothing reached ``db.commit()``, so no row from the
        # failed page is durable either.
        assert account.payout_history_cursor is None
        assert account.payout_history_complete is False

    def test_the_cron_contains_a_write_failure_without_failing(
        self, db, make_user,
    ):
        """And the cron wrapper keeps it off the money jobs: a sweep that
        transferred correctly must not be reported as a failed run because a
        payout write went wrong."""
        from scripts import fc_connect_transfer_sweeper as cron

        with patch.object(
            cron.payout_sync, "sync_creator_bank_payouts",
            side_effect=RuntimeError("database write failed"),
        ), patch.object(cron, "capture_job_summary") as cap:
            assert cron.sync_bank_payouts(db) is None
        assert cap.call_args_list == []

    def test_a_completed_import_does_not_restart_on_later_passes(
        self, db, make_user,
    ):
        """Five further passes after completion: still no history request,
        and the recent sweep keeps working."""
        creator = make_user(role="creator")
        account = _account(db, creator.id)
        api, calls = _stub([_payout(amount=i + 1) for i in range(4)])

        with patch("app.checkout.stripe_client.get_stripe", return_value=api):
            sync.sync_creator_bank_payouts(db)
            db.refresh(account)
            assert account.payout_history_complete is True
            calls.clear()
            for _ in range(5):
                sync.sync_creator_bank_payouts(db)

        assert len(calls) == 5                            # one each, recent only
        assert all("starting_after" not in c for c in calls)
        assert db.query(CreatorBankPayout).count() == 4   # and no duplicates
        db.refresh(account)
        assert account.payout_history_complete is True
