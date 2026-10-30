"""The shapes World Management already depends on.

BI-2 moves several reporting endpoints onto a shared metric registry.
These tests exist to make a shape change *fail* rather than be
discovered: each one pins the fields a live admin page reads today, so a
refactor that drops or renames one is caught here instead of on screen.

They assert on keys and types, not on values — values are the registry's
job and are tested there. Deliberately paranoid about the endpoints with
a live consumer:

* ``/platform/overview``   → app/admin/overview (Mother World)
* ``/commerce/overview``   → app/admin/revenue
* ``/revenue/summary/periodic`` → app/admin/payments
* ``/payments``, ``/payments/ledger`` → app/admin/payments
* ``/platform/users|collectives|creators`` → the respective shells
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_admin_user, get_current_user
from app.core.database import get_db
from app.main import app


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def admin(make_user):
    return make_user(role="admin")


def as_admin(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_admin_user] = lambda: user


#: Exactly what ``app/admin/overview/page.tsx`` reads. A missing key here
#: is a blank tile in Mother World.
OVERVIEW_KEYS = {
    "total_collectives", "active_collectives", "draft_collectives",
    "archived_collectives",
    "total_users", "admin_users", "creator_users", "member_users",
    "pending_access_requests", "pending_invitations",
    "total_gross_cents", "succeeded_transactions",
    "upcoming_gatherings", "total_gross_cents_today", "total_gross_cents_7d",
    "failed_transactions_7d", "recent_moments", "world_health",
    "connect_routing_ready", "connect_recovery_outstanding",
}


class TestPlatformOverviewContract:
    def test_every_field_the_dashboard_reads_is_present(self, client, admin):
        as_admin(admin)
        res = client.get("/api/admin/platform/overview")
        assert res.status_code == 200, res.text
        body = res.json()
        missing = OVERVIEW_KEYS - set(body)
        assert not missing, f"Mother World would lose: {sorted(missing)}"

    def test_the_counts_are_integers(self, client, admin):
        as_admin(admin)
        body = client.get("/api/admin/platform/overview").json()
        for k in OVERVIEW_KEYS - {
            "recent_moments", "world_health",
            "connect_routing_ready", "connect_recovery_outstanding",
        }:
            assert isinstance(body[k], int), f"{k} is {type(body[k]).__name__}"

    def test_the_collective_counts_are_internally_consistent(self, client, admin):
        """active + draft + archived must not exceed the total."""
        as_admin(admin)
        b = client.get("/api/admin/platform/overview").json()
        assert (
            b["active_collectives"] + b["draft_collectives"] + b["archived_collectives"]
        ) <= b["total_collectives"]

    def test_the_user_counts_are_internally_consistent(self, client, admin):
        as_admin(admin)
        b = client.get("/api/admin/platform/overview").json()
        assert b["admin_users"] + b["creator_users"] + b["member_users"] == b["total_users"]

    def test_it_refuses_a_non_admin(self, client, make_user):
        app.dependency_overrides[get_current_user] = lambda: make_user(role="creator")
        res = client.get("/api/admin/platform/overview")
        assert res.status_code in (401, 403)


class TestCommerceOverviewContract:
    """The sole data source for the live Revenue page."""

    def test_the_window_shape_is_preserved(self, client, admin):
        as_admin(admin)
        res = client.get("/api/admin/commerce/overview?period=this_month")
        assert res.status_code == 200, res.text
        body = res.json()
        assert "current" in body
        cur = body["current"]
        assert "bounds" in cur and "revenue" in cur
        for k in ("label", "starts_at", "ends_at"):
            assert k in cur["bounds"], k

    def test_the_revenue_block_keeps_its_fields(self, client, admin):
        as_admin(admin)
        rev = client.get(
            "/api/admin/commerce/overview?period=this_month"
        ).json()["current"]["revenue"]
        # The separation the business depends on, by its real field
        # names: FC's own revenue split into subscription and platform
        # fee, gross creator sales, creator net, and payout state — five
        # distinct figures that must never collapse into one.
        for k in (
            "total_fc_revenue_cents",
            "subscription_revenue_cents",
            "platform_fee_revenue_cents",
            "total_gross_sales_cents",
            "total_creator_net_cents",
            "paid_out_cents",
            "pending_payout_cents",
            "succeeded_transactions",
            "refunded_transactions",
            "failed_transactions",
        ):
            assert k in rev, f"commerce revenue lost {k}"
            assert isinstance(rev[k], int)

    def test_fc_revenue_is_the_sum_of_its_two_streams(self, client, admin):
        """The invariant that keeps FC revenue distinct from volume."""
        as_admin(admin)
        rev = client.get(
            "/api/admin/commerce/overview?period=all_time"
        ).json()["current"]["revenue"]
        assert rev["total_fc_revenue_cents"] == (
            rev["subscription_revenue_cents"] + rev["platform_fee_revenue_cents"]
        )

    def test_all_time_returns_no_previous_window(self, client, admin):
        as_admin(admin)
        body = client.get("/api/admin/commerce/overview?period=all_time").json()
        assert body.get("previous") is None

    def test_an_invalid_period_is_refused(self, client, admin):
        as_admin(admin)
        assert client.get(
            "/api/admin/commerce/overview?period=last_fortnight"
        ).status_code == 422

    def test_it_refuses_a_non_admin(self, client, make_user):
        app.dependency_overrides[get_current_user] = lambda: make_user(role="creator")
        assert client.get(
            "/api/admin/commerce/overview"
        ).status_code in (401, 403)


class TestRevenueAndPaymentContracts:
    def test_periodic_revenue_summary_shape(self, client, admin):
        as_admin(admin)
        res = client.get("/api/admin/revenue/summary/periodic?period=this_month")
        assert res.status_code == 200, res.text
        assert "current" in res.json()

    def test_payments_list_shape(self, client, admin):
        as_admin(admin)
        res = client.get("/api/admin/payments")
        assert res.status_code == 200, res.text
        assert isinstance(res.json(), list)

    def test_payments_ledger_shape(self, client, admin):
        as_admin(admin)
        res = client.get("/api/admin/payments/ledger")
        assert res.status_code == 200, res.text
        assert isinstance(res.json(), list)

    def test_payment_summary_shape(self, client, admin):
        as_admin(admin)
        res = client.get("/api/admin/payments/summary")
        assert res.status_code == 200, res.text
        body = res.json()
        assert "total_processing_fee_cents" in body


class TestPlatformListContracts:
    @pytest.mark.parametrize("path", [
        "/api/admin/platform/users",
        "/api/admin/platform/collectives",
        "/api/admin/platform/creators",
    ])
    def test_each_list_still_returns_a_list(self, client, admin, path):
        as_admin(admin)
        res = client.get(path)
        assert res.status_code == 200, res.text
        assert isinstance(res.json(), list)

    @pytest.mark.parametrize("path", [
        "/api/admin/platform/users",
        "/api/admin/platform/collectives",
        "/api/admin/platform/creators",
        "/api/admin/platform/overview",
        "/api/admin/commerce/overview",
    ])
    def test_none_of_them_are_reachable_without_admin(
        self, client, make_user, path,
    ):
        app.dependency_overrides[get_current_user] = lambda: make_user()
        assert client.get(path).status_code in (401, 403)
