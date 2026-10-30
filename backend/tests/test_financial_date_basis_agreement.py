"""The endpoints and the registry must agree about the same payment.

BI-2 gave each financial metric its own event date but only converted
one of the three implementations. ``_compute_payment_summary`` and
``_compute_revenue_summary`` kept filtering on ``created_at`` while the
registry declared settlement, so a payment created in September and
settled in October counted as October revenue through
``/reporting/query`` and as September revenue through
``/commerce/overview``.

That is the original defect in different clothes. These tests are the
guard that stops it coming back a third time: the figure an endpoint
reports and the figure the registry reports must be the same number for
the same window, and no reporting query may filter money by a raw
``created_at`` or ``updated_at`` again.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_admin_user, get_current_user
from app.core.database import get_db
from app.core.periods import resolve_period
from app.main import app
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import platform_scope


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def admin(make_user):
    a = make_user(role="admin")
    app.dependency_overrides[get_current_user] = lambda: a
    app.dependency_overrides[get_admin_user] = lambda: a
    return a


def _txn(db, space, creator, payer, *, created_at, settled_at, gross=10000):
    t = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payer_user_id=payer.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=1000,
        platform_fee_cents=gross // 10,
        net_creator_amount_cents=gross - gross // 10,
        stripe_mode="test",
        created_at=created_at,
        updated_at=created_at,
        settled_at=settled_at,
        settled_at_source="observed" if settled_at else None,
    )
    db.add(t)
    db.flush()
    return t


def _registry_gross(db, bounds):
    return REGISTRY.get("gross_collective_sales_cents").evaluate(
        db, platform_scope(), Window(bounds.starts_at, bounds.ends_at, bounds.label),
    ).value


class TestTheEndpointAndTheRegistryAgree:
    def test_a_payment_settled_in_a_later_month_counts_in_that_month_everywhere(
        self, client, db, admin, make_user, make_space,
    ):
        """The exact divergence, now pinned.

        Created last month, settled this month. Before the fix the
        endpoint said 0 and the registry said the full amount.
        """
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        _txn(
            db, space, creator, make_user(),
            created_at=month_start - timedelta(days=5),
            settled_at=month_start + timedelta(days=1),
        )
        db.commit()

        bounds, _ = resolve_period("this_month")
        endpoint = client.get(
            "/api/admin/commerce/overview?period=this_month&stripe_mode=test"
        ).json()["current"]["revenue"]["total_gross_sales_cents"]
        assert endpoint == _registry_gross(db, bounds)
        assert endpoint == 10000

    def test_they_agree_on_an_unsettled_historical_payment(
        self, client, db, admin, make_user, make_space,
    ):
        """A pre-BI-1 payment falls back to creation on both sides."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        _txn(
            db, space, creator, make_user(),
            created_at=month_start + timedelta(days=2),
            settled_at=None,
        )
        db.commit()
        bounds, _ = resolve_period("this_month")
        endpoint = client.get(
            "/api/admin/commerce/overview?period=this_month&stripe_mode=test"
        ).json()["current"]["revenue"]["total_gross_sales_cents"]
        assert endpoint == _registry_gross(db, bounds) == 10000

    def test_they_agree_over_all_time(
        self, client, db, admin, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(db, space, creator, make_user(),
             created_at=datetime(2025, 3, 1), settled_at=None, gross=5000)
        _txn(db, space, creator, make_user(),
             created_at=datetime(2026, 3, 1), settled_at=datetime(2026, 3, 2),
             gross=7000)
        db.commit()
        bounds, _ = resolve_period("all_time")
        endpoint = client.get(
            "/api/admin/commerce/overview?period=all_time&stripe_mode=test"
        ).json()["current"]["revenue"]["total_gross_sales_cents"]
        assert endpoint == _registry_gross(db, bounds) == 12000

    def test_the_payments_list_and_the_summary_use_the_same_period(
        self, client, db, admin, make_user, make_space,
    ):
        """A payment in the summary must be findable in the list."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        t = _txn(
            db, space, creator, make_user(),
            created_at=month_start - timedelta(days=5),
            settled_at=month_start + timedelta(days=1),
        )
        db.commit()
        listed = client.get(
            "/api/admin/payments?period=this_month&stripe_mode=test"
        ).json()
        assert t.id in {row["id"] for row in listed}


class TestNoReportingQueryFiltersMoneyByARawRowDate:
    """A structural guard, not a behavioural one.

    The two previous occurrences of this bug were both introduced by
    somebody writing a fresh date filter rather than reusing the shared
    one. This fails the moment that happens again.
    """

    def test_the_admin_reporting_module_has_no_raw_money_date_filters(self):
        import pathlib
        import re

        src = pathlib.Path("app/admin/routes.py").read_text()
        offenders = re.findall(
            r"PaymentTransaction\.(?:created_at|updated_at)\s*(?:>=|<=|<|>)\s*\w",
            src,
        )
        assert not offenders, (
            "money is being filtered by a raw row date again — use "
            "app.reporting.dates.settlement_date() so the endpoints and the "
            f"registry cannot disagree. Found: {offenders}"
        )

    def test_the_registry_and_the_admin_helpers_share_one_definition(self):
        from app.admin import routes as admin_routes
        from app.reporting import dates, metrics

        assert admin_routes._financial_date is dates.settlement_date
        assert metrics._settlement_date_column is dates.settlement_date

    def test_every_money_metric_declares_a_money_date_basis(self):
        from app.reporting.registry import DateBasis

        money_bases = {
            DateBasis.payment_settled, DateBasis.refunded,
            DateBasis.payout_marked, DateBasis.none,
        }
        for m in REGISTRY.all():
            if m.key.endswith("_cents"):
                assert m.date_basis in money_bases, (
                    f"{m.key} attributes money by {m.date_basis.value}"
                )
