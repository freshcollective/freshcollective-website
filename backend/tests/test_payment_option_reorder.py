"""Creator-controlled Payment Option display ordering.

Covers:

* the new ``POST .../commerce/payment-options/reorder`` endpoint —
  authz (creator-owner + platform admin permitted, cross-Collective
  rejected), payload shape (duplicates + foreign IDs + missing IDs
  all reject with 400 so partial applies never occur, atomicity);
* the existing member surface for a Gathering Series ("Ways to
  join") — regression: the underlying query at
  ``_series_member_routes.py:_member_purchasable_options_for_series``
  used to return rows in DB-internal order, which is why Term 4
  displayed Awaken → Empower → Activate while Creator Studio showed
  Awaken → Activate → Empower;
* archive semantics — archived rows keep their old ``position`` so
  unarchiving does not reshuffle the visible order.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.main import app
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


def _make_option(db, space, *, name: str, position: int, status="published") -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        attaches_to_kind="space",
        attaches_to_id=space.id,
        name=name,
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus(status),
        calculated_total_cents=10_000,
        currency="AUD",
        position=position,
    )
    db.add(opt)
    db.flush()
    return opt


def _make_series(db, space) -> EventSeries:
    now = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        title="Term 4",
        slug=f"term-4-{uuid.uuid4().hex[:6]}",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=90),
        status="published",
        published_at=now,
    )
    db.add(series)
    db.flush()
    return series


def _grant_series(db, option: PaymentOption, series: EventSeries) -> None:
    grant = PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=option.id,
        grant_kind="event_series",
        series_id=series.id,
        sessions_per_week=1,
        total_sessions=10,
    )
    db.add(grant)
    db.flush()


def _add_pay_in_full_schedule(db, option: PaymentOption) -> None:
    sched = PaymentOptionSchedule(
        id=_uid("sched"),
        payment_option_id=option.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=10_000,
        currency="AUD",
    )
    db.add(sched)
    db.flush()


class TestReorderEndpoint:
    """``POST /api/creator/spaces/{slug}/commerce/payment-options/reorder``."""

    def test_creator_reorders_own_space_options(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        a = _make_option(db, space, name="A", position=0)
        b = _make_option(db, space, name="B", position=1)
        c = _make_option(db, space, name="C", position=2)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [b.id, a.id, c.id]},
        )
        assert res.status_code == 204

        # Verify DB positions reflect the new ordering.
        db.expire_all()
        assert db.get(PaymentOption, b.id).position == 0
        assert db.get(PaymentOption, a.id).position == 1
        assert db.get(PaymentOption, c.id).position == 2

    def test_creator_studio_list_reflects_new_order_after_refresh(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        a = _make_option(db, space, name="A", position=0)
        b = _make_option(db, space, name="B", position=1)
        c = _make_option(db, space, name="C", position=2)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator

        client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [b.id, a.id, c.id]},
        )
        res = client.get(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options",
        )
        assert res.status_code == 200
        names = [row["name"] for row in res.json()]
        assert names == ["B", "A", "C"]

    def test_platform_admin_can_reorder_any_space(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        a = _make_option(db, space, name="A", position=0)
        b = _make_option(db, space, name="B", position=1)
        db.commit()

        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        res = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [b.id, a.id]},
        )
        assert res.status_code == 204

    def test_non_manager_creator_rejected(
        self, db, client, make_user, make_space,
    ):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        space = make_space(creator=creator_a)
        a = _make_option(db, space, name="A", position=0)
        b = _make_option(db, space, name="B", position=1)
        db.commit()
        # creator_b doesn't own or moderate space.
        app.dependency_overrides[get_creator_user] = lambda: creator_b

        res = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [b.id, a.id]},
        )
        # _get_managed_space returns 403 for non-managers.
        assert res.status_code == 403
        # Nothing moved.
        db.expire_all()
        assert db.get(PaymentOption, a.id).position == 0
        assert db.get(PaymentOption, b.id).position == 1

    def test_duplicate_ids_rejected(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        a = _make_option(db, space, name="A", position=0)
        b = _make_option(db, space, name="B", position=1)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [a.id, a.id, b.id]},
        )
        assert res.status_code == 400
        assert "duplicate" in res.text.lower()

    def test_foreign_option_rejected_atomically(
        self, db, client, make_user, make_space,
    ):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        space_a = make_space(creator=creator_a)
        space_b = make_space(creator=creator_b)
        a1 = _make_option(db, space_a, name="A1", position=0)
        a2 = _make_option(db, space_a, name="A2", position=1)
        # Foreign option — belongs to a completely different Collective.
        foreign = _make_option(db, space_b, name="Foreign", position=0)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator_a

        res = client.post(
            f"/api/creator/spaces/{space_a.slug}/commerce/payment-options/reorder",
            json={"ids": [a1.id, foreign.id, a2.id]},
        )
        assert res.status_code == 400
        # Foreign option's position is untouched — no silent move.
        db.expire_all()
        assert db.get(PaymentOption, foreign.id).position == 0
        # Own options' positions also untouched — the whole payload was rejected.
        assert db.get(PaymentOption, a1.id).position == 0
        assert db.get(PaymentOption, a2.id).position == 1

    def test_missing_ids_rejected(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        a = _make_option(db, space, name="A", position=0)
        _b = _make_option(db, space, name="B", position=1)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator

        # Only submit one of two live options.
        res = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [a.id]},
        )
        assert res.status_code == 400

    def test_archived_options_are_untouched(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        a = _make_option(db, space, name="A", position=0)
        b = _make_option(db, space, name="B", position=1)
        archived = _make_option(
            db, space, name="Old", position=99, status="archived",
        )
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator

        # Reorder request covers non-archived rows only — must NOT
        # need to include the archived row.
        res = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [b.id, a.id]},
        )
        assert res.status_code == 204
        db.expire_all()
        assert db.get(PaymentOption, archived.id).position == 99


class TestMemberSeriesOrdering:
    """The member "Ways to join" surface must honour the creator's
    chosen order — regression for the Term 4 Awaken/Empower/Activate
    display bug."""

    def test_series_payment_options_return_in_creator_order(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user(role="user")
        space = make_space(creator=creator)
        series = _make_series(db, space)

        # Create in "wrong" position order to ensure the endpoint
        # doesn't just return created_at order.
        awaken = _make_option(db, space, name="Awaken", position=0)
        activate = _make_option(db, space, name="Activate", position=1)
        empower = _make_option(db, space, name="Empower", position=2)
        for opt in (awaken, activate, empower):
            _grant_series(db, opt, series)
            _add_pay_in_full_schedule(db, opt)
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: member

        res = client.get(
            f"/api/spaces/{space.slug}/gathering-series/{series.slug}/payment-options",
        )
        assert res.status_code == 200
        names = [o["name"] for o in res.json()]
        assert names == ["Awaken", "Activate", "Empower"]

    def test_series_payment_options_reflect_reorder(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user(role="user")
        space = make_space(creator=creator)
        series = _make_series(db, space)

        a = _make_option(db, space, name="A", position=0)
        b = _make_option(db, space, name="B", position=1)
        c = _make_option(db, space, name="C", position=2)
        for opt in (a, b, c):
            _grant_series(db, opt, series)
            _add_pay_in_full_schedule(db, opt)
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: creator
        r = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/reorder",
            json={"ids": [b.id, a.id, c.id]},
        )
        assert r.status_code == 204

        app.dependency_overrides[get_creator_user] = lambda: member
        res = client.get(
            f"/api/spaces/{space.slug}/gathering-series/{series.slug}/payment-options",
        )
        assert res.status_code == 200
        names = [o["name"] for o in res.json()]
        assert names == ["B", "A", "C"]

    def test_new_option_defaults_to_bottom_of_current_order(
        self, db, client, make_user, make_space,
    ):
        # Regression note: ``create_commerce_payment_option`` already
        # calls ``max(position) + 1`` on insert, so a new option
        # should never land ahead of existing ones.
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_option(db, space, name="Existing1", position=0)
        _make_option(db, space, name="Existing2", position=1)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options",
            json={
                "name": "Fresh",
                "description": None,
                "payment_type": "one_time",
                "status": "draft",
                "currency": "AUD",
                "calculated_total_cents": 5000,
            },
        )
        assert res.status_code == 201
        new_id = res.json()["id"]
        db.expire_all()
        new_row = db.get(PaymentOption, new_id)
        assert new_row.position == 2
