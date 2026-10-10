"""The payout side of a recipient account: schedule, entity type, headroom.

These are the pieces that decide *when* a creator's money leaves Stripe and
*whose* identity Stripe verifies, plus the monitoring that watches whether
Fresh Collective can still cover what it owes now that it absorbs Stripe's
processing fee.

Nothing here talks to Stripe. The payout schedule and balance reads are
patched, because the behaviour under test is how Fresh Collective reacts to
Stripe's answers — including Stripe refusing.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import stripe

from app.models.payment import (
    ConnectTransferStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.services import stripe_connect_accounts as accounts

ACCOUNTS = "app.services.stripe_connect_accounts"


def _rendered(mock_log) -> str:
    """A patched logger call rendered the way the log file would show it.

    Asserted against the logger directly rather than through ``caplog``:
    importing the FastAPI app reconfigures logging, so propagation-based
    capture passes or fails according to test *order*. That is false
    confidence about whether a condition is really being reported.
    """
    args = mock_log.call_args.args
    template, params = args[0], args[1:]
    try:
        return template % params
    except TypeError:
        return " ".join(str(a) for a in args)


_WEEKLY = {"interval": "weekly", "weekly_anchor": "monday"}


class _FakeAccountApi:
    """Records ``Account.modify`` and answers with a schedule.

    ``retrieve_schedule`` is what a follow-up read reports, for the case
    where the write response carried no schedule of its own.
    """

    def __init__(self, *, schedule=_WEEKLY, error=None, retrieve_schedule=None,
                 retrieve_error=None, omit_schedule=False):
        self.calls: list[tuple[str, dict]] = []
        self.retrieves: list[str] = []
        outer = self

        class _Account:
            @staticmethod
            def modify(account_id, **kwargs):
                outer.calls.append((account_id, kwargs))
                if error is not None:
                    raise error
                if omit_schedule:
                    return {"id": account_id}
                return {"id": account_id,
                        "settings": {"payouts": {"schedule": schedule}}}

            @staticmethod
            def retrieve(account_id, **kwargs):
                outer.retrieves.append(account_id)
                if retrieve_error is not None:
                    raise retrieve_error
                return {"id": account_id,
                        "settings": {"payouts": {
                            "schedule": retrieve_schedule}}}

        self.Account = _Account


# ---------------------------------------------------------------------------
# Weekly payouts
# ---------------------------------------------------------------------------


class TestWeeklyPayoutSchedule:
    def test_it_asks_stripe_for_weekly_payouts_anchored_on_monday(self):
        fake = _FakeAccountApi()
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake):
            schedule = accounts.set_weekly_payout_schedule("acct_123")

        assert len(fake.calls) == 1
        account_id, kwargs = fake.calls[0]
        assert account_id == "acct_123"
        assert kwargs["settings"]["payouts"]["schedule"] == {
            "interval": "weekly", "weekly_anchor": "monday",
        }
        assert schedule == {"interval": "weekly", "weekly_anchor": "monday"}

    def test_the_constant_is_not_mutated_by_the_call(self):
        """The payload is built from a copy. A Stripe SDK that mutated what it
        was handed would otherwise poison every later account."""
        before = dict(accounts.WEEKLY_PAYOUT_SCHEDULE)
        fake = _FakeAccountApi()
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake):
            accounts.set_weekly_payout_schedule("acct_123")
        _, kwargs = fake.calls[0]
        payload = kwargs["settings"]["payouts"]["schedule"]
        payload["interval"] = "daily"            # as a bad SDK might
        assert dict(accounts.WEEKLY_PAYOUT_SCHEDULE) == before

    def test_a_write_that_did_not_take_is_reported_not_assumed(self):
        """The quiet failure this guards against: Stripe accepts the call but
        the account is still on daily. Silence here would cost a payout fee
        every day a creator sells, with nothing in the logs to find."""
        fake = _FakeAccountApi(schedule={"interval": "daily", "delay_days": 2})
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake), \
             patch.object(accounts.logger, "error") as err:
            result = accounts.set_weekly_payout_schedule("acct_123")

        # Reports what Stripe actually says rather than what was asked for.
        assert result == {"interval": "daily", "delay_days": 2}
        assert err.call_count == 1
        logged = _rendered(err)
        assert "acct_123" in logged
        assert "daily" in logged

    def test_it_confirms_by_reading_when_the_write_says_nothing(self):
        """A modify response without a schedule is not evidence the schedule
        took. One read settles it instead of assuming."""
        fake = _FakeAccountApi(omit_schedule=True, retrieve_schedule=_WEEKLY)
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake):
            assert accounts.set_weekly_payout_schedule("acct_123") == _WEEKLY
        assert fake.retrieves == ["acct_123"]

    def test_it_does_not_read_again_when_the_write_already_answered(self):
        """One call, not two, in the ordinary case."""
        fake = _FakeAccountApi()
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake):
            accounts.set_weekly_payout_schedule("acct_123")
        assert fake.retrieves == []

    def test_an_unconfirmable_write_is_an_error_not_a_success(self):
        """Write accepted, confirmation unavailable. Unverified is not the
        same as fine, and must not be logged as if it were."""
        fake = _FakeAccountApi(
            omit_schedule=True,
            retrieve_error=stripe.APIConnectionError("no route"),
        )
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake), \
             patch.object(accounts.logger, "error") as err:
            assert accounts.set_weekly_payout_schedule("acct_123") is None
        assert err.call_count == 1

    def test_a_refusal_is_logged_at_error_with_the_consequence(self):
        """Previously a warning. It is a standing cost, not a transient
        hiccup, so it belongs at a level somebody reads."""
        fake = _FakeAccountApi(error=stripe.InvalidRequestError("nope", param=None))
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake), \
             patch.object(accounts.logger, "warning") as warn, \
             patch.object(accounts.logger, "error") as err:
            assert accounts.set_weekly_payout_schedule("acct_123") is None

        assert err.call_count == 1, "a refused payout schedule must be an ERROR"
        assert warn.call_args_list == [], "and not merely a warning"
        logged = _rendered(err)
        assert "acct_123" in logged
        # Says what it means, so the reader does not have to infer the impact.
        assert "daily" in logged
        assert "transfers" in logged.lower()

    def test_a_refusal_returns_none_and_never_raises(self):
        """An account that was created must not be lost because its payout
        interval could not be set. The interval is re-readable and re-settable;
        a half-created account is not."""
        fake = _FakeAccountApi(error=stripe.InvalidRequestError("nope", param=None))
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake):
            assert accounts.set_weekly_payout_schedule("acct_123") is None

    @pytest.mark.parametrize("boom", [
        stripe.InvalidRequestError("refused", param=None),
        stripe.APIConnectionError("no route"),
        RuntimeError("something nobody predicted"),
        KeyError(0),            # the shape bug stripe 15.2.0 actually throws
    ])
    def test_no_failure_of_any_kind_blocks_onboarding(self, boom):
        """Whatever goes wrong, the creator still has a usable account.

        Losing a successfully created account over a payout cadence would
        leave that creator with no way to be paid at all — far worse than a
        suboptimal interval, and not recoverable the way an interval is.
        """
        fake = _FakeAccountApi(error=boom)
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake):
            assert accounts.set_weekly_payout_schedule("acct_123") is None

    def test_an_unreadable_answer_returns_none_rather_than_a_guess(self):
        """Stripe answered, but not with a schedule. Reporting ``None`` lets the
        projection show the real interval from the next sync instead of
        recording an interval that was never confirmed."""
        fake = _FakeAccountApi(schedule="weekly")      # a string, not an object
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake):
            assert accounts.set_weekly_payout_schedule("acct_123") is None


# ---------------------------------------------------------------------------
# Entity type
# ---------------------------------------------------------------------------


class TestEntityType:
    def test_the_supported_set_is_exactly_what_stripe_accepts(self):
        assert accounts.SUPPORTED_ENTITY_TYPES == frozenset({"individual", "company"})

    @pytest.mark.parametrize("bad", ["sole_trader", "Individual", "", "INDIVIDUAL"])
    def test_an_unsupported_entity_type_is_refused_before_stripe_is_called(self, bad):
        """Entity type is fixed at creation and cannot be changed afterwards,
        so a typo must fail loudly here rather than create an account whose
        identity requirements can never be satisfied."""
        fake = _FakeAccountApi()
        with patch(f"{ACCOUNTS}.get_stripe", return_value=fake), \
             patch(f"{ACCOUNTS}.get_stripe_client", return_value=fake):
            with pytest.raises(accounts.ConnectError) as exc:
                accounts.create_recipient_account(
                    display_name="A Creator",
                    contact_email="creator@example.com",
                    country="AU",
                    entity_type=bad,
                )
        assert "entity_type" in str(exc.value)
        assert fake.calls == []        # nothing was created


# ---------------------------------------------------------------------------
# Balance headroom
# ---------------------------------------------------------------------------


def _owed_txn(db, **overrides) -> PaymentTransaction:
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "payment_provider": PaymentProvider.stripe,
        "currency": "AUD",
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "processing_fee_cents": 200,
        "payout_status": PayoutStatus.pending,
        "stripe_mode": "test",
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": "acct_1ConnectReady",
        "connect_transfer_status": ConnectTransferStatus.pending.value,
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


class _FakeBalance:
    """Stripe answers with plain mappings here."""

    def __init__(self, available_cents: int, currency: str = "aud"):
        self.available = [{"currency": currency, "amount": available_cents}]


class _StripeObjectEntry:
    """What the real SDK returns: attribute access, and no ``.get()``.

    ``StripeObject.get`` raises ``AttributeError`` in stripe 15.2.0, so a
    reader that assumes a mapping fails against the live SDK while passing
    every test written with dicts.
    """

    def __init__(self, currency: str, amount: int):
        self.currency = currency
        self.amount = amount

    def get(self, *a, **k):
        raise AttributeError("StripeObject has no attribute 'get'")

    def __getitem__(self, key):
        raise TypeError("not subscriptable in the way a dict is")


class _FakeBalanceStripeShaped:
    def __init__(self, available_cents: int, currency: str = "aud"):
        self.available = [_StripeObjectEntry(currency, available_cents)]


class TestBalanceHeadroom:
    """Reported, never enforced.

    Absorbing the processing fee means a sale can add less to FC's balance than
    the transfer takes out, so the gap is worth watching. It must never gate a
    transfer: ``source_transaction`` lets Stripe accept the request while the
    charge settles, and ``balance_insufficient`` is already retryable, so
    gating here would turn a cash-flow wobble into unpaid creators.
    """

    @staticmethod
    def _run(db, balance):
        from scripts import fc_connect_transfer_sweeper as cron
        with patch("stripe.Balance.retrieve", return_value=balance), \
             patch.object(cron, "capture_job_summary", return_value="evt_1") as cap:
            event = cron.report_balance_headroom(db)
        return event, cap

    def test_a_sufficient_balance_raises_nothing(self, db):
        _owed_txn(db)
        event, cap = self._run(db, _FakeBalance(50_000))
        assert event is None
        assert cap.call_args_list == []

    def test_a_shortfall_is_reported_with_the_amount_short(self, db):
        _owed_txn(db)                      # owes 9200
        event, cap = self._run(db, _FakeBalance(5_000))
        assert event == "evt_1"
        assert cap.call_count == 1
        assert cap.call_args.kwargs["level"] == "error"
        assert cap.call_args.kwargs["short_aud_cents"] == 9200 - 5_000

    def test_nothing_owed_reads_no_balance_at_all(self, db):
        """No pending Connect rows means no question to answer, and no reason
        to spend a Stripe call on it."""
        from scripts import fc_connect_transfer_sweeper as cron
        with patch("stripe.Balance.retrieve") as retrieve, \
             patch.object(cron, "capture_job_summary") as cap:
            assert cron.report_balance_headroom(db) is None
        assert retrieve.call_args_list == []
        assert cap.call_args_list == []

    def test_only_rows_still_owed_are_counted(self, db):
        """Already-sent and not-yet-paid rows are not a claim on the balance."""
        _owed_txn(db)                                                     # 9200
        _owed_txn(db, connect_transfer_status=ConnectTransferStatus.sent.value)
        _owed_txn(
            db, connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        # A manual row carries no Connect state at all — the schema forbids
        # it — so it cannot be a claim on the Connect balance either.
        #
        # Which is also why the query's ``payout_model = 'connect'`` predicate
        # cannot be observed failing from here: a row can only be
        # ``connect_transfer_status = 'pending'`` if it is a Connect row, so
        # dropping that predicate changes nothing while the check constraint
        # ``ck_payment_transactions_non_connect_has_no_transfer`` stands. It is
        # kept as belt and braces, not as the load-bearing filter.
        _owed_txn(
            db,
            payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
        )
        event, cap = self._run(db, _FakeBalance(9_000))
        assert cap.call_args.kwargs["short_aud_cents"] == 9200 - 9_000

    def test_it_reads_the_real_sdk_object_shape_too(self, db):
        """The dict-shaped fakes above would not catch a reader that only
        works on mappings. The live SDK hands back attribute-only objects."""
        _owed_txn(db)                      # owes 9200
        event, cap = self._run(db, _FakeBalanceStripeShaped(5_000))
        assert event == "evt_1"
        assert cap.call_args.kwargs["short_aud_cents"] == 9200 - 5_000

    def test_an_unreadable_entry_is_skipped_not_counted_as_zero(self, db):
        """A balance entry Fresh Collective cannot read must not be reported
        as A$0 available — that would raise a shortfall alert that is not
        real. Treated as "no answer for this currency" instead."""
        _owed_txn(db)

        class _Opaque:
            pass

        class _Balance:
            available = [_Opaque()]

        event, cap = self._run(db, _Balance())
        # Nothing readable, so nothing claimed to be available: the genuine
        # shortfall is still reported, and reported as the full amount owed.
        assert cap.call_args.kwargs["short_aud_cents"] == 9200

    def test_a_stripe_read_that_fails_does_not_fail_the_cron(self, db):
        """The sweep has already run by this point. A monitoring read must
        never be the thing that turns a successful sweep into a failed job."""
        from scripts import fc_connect_transfer_sweeper as cron
        _owed_txn(db)
        with patch("stripe.Balance.retrieve", side_effect=stripe.APIConnectionError("x")), \
             patch.object(cron, "capture_job_summary") as cap:
            assert cron.report_balance_headroom(db) is None
        assert cap.call_args_list == []


# ---------------------------------------------------------------------------
# Finding the accounts that never took
# ---------------------------------------------------------------------------


def _csa(db, creator_id, **overrides):
    """A connected account row, payout-ready unless overridden."""
    from datetime import datetime

    from app.models.creator_stripe_account import (
        CreatorStripeAccount,
        FEE_DISCLOSURE_VERSION,
        OnboardingState,
    )
    values = {
        "id": f"csa_{uuid.uuid4()}",
        "creator_user_id": creator_id,
        "stripe_mode": "test",
        "stripe_account_id": f"acct_{uuid.uuid4().hex[:12]}",
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


class TestFindingStragglers:
    def test_a_weekly_account_is_not_a_straggler(self, db, make_user):
        _csa(db, make_user(role="creator").id, payout_interval="weekly")
        assert accounts.accounts_not_on_weekly_payouts(db) == []

    def test_a_daily_account_is_listed_with_its_interval(self, db, make_user):
        creator = make_user(role="creator")
        row = _csa(db, creator.id, payout_interval="daily")
        found = accounts.accounts_not_on_weekly_payouts(db)
        assert found == [(creator.id, row.stripe_account_id, "daily")]

    def test_an_unknown_interval_is_listed_too(self, db, make_user):
        """SQL's ``<> 'weekly'`` is false for NULL, so an account whose
        interval was never learned would otherwise be reported as fine —
        the opposite of the truth. Unverified is not the same as correct.
        """
        creator = make_user(role="creator")
        row = _csa(db, creator.id, payout_interval=None)
        assert accounts.accounts_not_on_weekly_payouts(db) == [
            (creator.id, row.stripe_account_id, None),
        ]

    def test_a_row_with_no_stripe_account_is_not_listed(self, db, make_user):
        """Nothing was created, so there is no schedule to be wrong."""
        _csa(
            db, make_user(role="creator").id,
            stripe_account_id=None, payout_interval=None,
            onboarding_state="not_started",
            transfers_status=None, transfers_enabled=False,
            payouts_status=None, payouts_enabled=False,
            details_submitted=False, external_account_count=0,
        )
        assert accounts.accounts_not_on_weekly_payouts(db) == []

    def test_it_separates_the_good_from_the_bad(self, db, make_user):
        good = make_user(role="creator")
        bad = make_user(role="creator")
        _csa(db, good.id, payout_interval="weekly")
        _csa(db, bad.id, payout_interval="daily")
        found = accounts.accounts_not_on_weekly_payouts(db)
        assert [c for c, _, _ in found] == [bad.id]

    def test_it_costs_no_stripe_calls(self, db, make_user):
        """It reads the interval every sync already projected onto the row,
        so checking every account is free."""
        _csa(db, make_user(role="creator").id, payout_interval="daily")
        with patch(f"{ACCOUNTS}.get_stripe") as api:
            accounts.accounts_not_on_weekly_payouts(db)
        assert api.call_args_list == []


class TestTheCronSurfacesStragglers:
    @staticmethod
    def _run(db):
        from scripts import fc_connect_transfer_sweeper as cron
        with patch.object(cron, "capture_job_summary", return_value="evt_1") as cap, \
             patch.object(cron, "id_logger") as ids:
            event = cron.report_payout_schedule_stragglers(db)
        return event, cap, ids

    def test_nothing_is_reported_when_every_account_is_weekly(self, db, make_user):
        _csa(db, make_user(role="creator").id, payout_interval="weekly")
        event, cap, _ = self._run(db)
        assert event is None
        assert cap.call_args_list == []

    def test_a_daily_account_is_reported_as_a_warning(self, db, make_user):
        """Warning, not error: creator earnings and transfers are unaffected.
        It is a cost and cadence problem that somebody should fix."""
        _csa(db, make_user(role="creator").id, payout_interval="daily")
        event, cap, _ = self._run(db)
        assert event == "evt_1"
        assert cap.call_args.kwargs["level"] == "warning"
        assert cap.call_args.kwargs["accounts"] == 1
        assert cap.call_args.kwargs["on_daily"] == 1

    def test_account_ids_stay_out_of_the_sentry_summary(self, db, make_user):
        """Ids go to the Render log, like the needs-attention list. Acting on
        one means opening the account, which is not a thing to do from a
        breadcrumb trail."""
        creator = make_user(role="creator")
        row = _csa(db, creator.id, payout_interval="daily")
        _, cap, ids = self._run(db)

        summary = str(cap.call_args)
        assert row.stripe_account_id not in summary
        assert creator.id not in summary
        # But they are recoverable by an operator who needs them.
        assert ids.warning.call_count == 1

    def test_the_summary_carries_only_counts(self, db, make_user):
        """``capture_job_summary`` accepts ints and replaces anything else
        with DROPPED_NOT_A_COUNT, logging as it goes. This first shipped
        passing a list of interval names, so the field never reached Sentry
        and every run logged a warning about it. Counts instead."""
        from app.core.observability import DROPPED_NOT_A_COUNT

        _csa(db, make_user(role="creator").id, payout_interval="daily")
        _csa(db, make_user(role="creator").id, payout_interval=None)
        _csa(db, make_user(role="creator").id, payout_interval="monthly")
        _, cap, _ = self._run(db)

        kwargs = {k: v for k, v in cap.call_args.kwargs.items() if k != "level"}
        assert all(isinstance(v, int) for v in kwargs.values()), kwargs
        assert DROPPED_NOT_A_COUNT not in kwargs.values()
        assert kwargs == {
            "accounts": 3,
            "on_daily": 1,
            "interval_unknown": 1,
            "other_interval": 1,
        }

    def test_a_broken_listing_does_not_fail_the_cron(self, db):
        from scripts import fc_connect_transfer_sweeper as cron
        with patch.object(
            cron.connect_accounts, "accounts_not_on_weekly_payouts",
            side_effect=RuntimeError("db gone"),
        ), patch.object(cron, "capture_job_summary") as cap:
            assert cron.report_payout_schedule_stragglers(db) is None
        assert cap.call_args_list == []


class TestAdministratorsCanSeeTheInterval:
    """The reactive half of the straggler report.

    The cron tells an administrator that *some* account is wrong; this tells
    them whether *this* creator's is, while they are looking at them.
    """

    def test_the_readiness_response_reports_the_real_interval(self, db, make_user):
        from app.admin.connect_routes import _readiness

        creator = make_user(role="creator")
        _csa(db, creator.id, payout_interval="daily")
        assert _readiness(db, creator.id).payout_interval == "daily"

    def test_it_reports_weekly_when_weekly(self, db, make_user):
        from app.admin.connect_routes import _readiness

        creator = make_user(role="creator")
        _csa(db, creator.id, payout_interval="weekly")
        assert _readiness(db, creator.id).payout_interval == "weekly"

    def test_a_creator_with_no_account_reports_none(self, db, make_user):
        from app.admin.connect_routes import _readiness

        creator = make_user(role="creator")
        assert _readiness(db, creator.id).payout_interval is None
