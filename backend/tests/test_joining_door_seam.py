"""The joining door, end to end.

The previous round tested each layer alone and shipped a blocker: the
creator's nomination was silently discarded by an allowlist, the stored
value was never serialised back, the price was read from the wrong
columns, and the door omitted the schedule id the checkout endpoint
requires. Every one of those lived in a seam between two layers that
were individually green.

So this file walks the whole chain in one test:

    creator nominates
      → the row changes
      → the creator GET says so
      → the public payload carries the door
      → the door names real, checkoutable schedules
      → a checkout request built from it satisfies the endpoint's schema
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_creator_user, get_current_user, get_optional_user,
    get_verified_creator_user, get_verified_current_user,
)
from app.checkout.schemas import UnifiedCheckoutRequest
from app.core.database import get_db
from app.main import app
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.payment_option_grant import PaymentOptionGrant


@pytest.fixture
def plans_enabled():
    """Payment-plan checkout is a platform gate, ON in production.
    The joining door must follow exactly the same gate the Series
    surface does — never advertise a schedule checkout would refuse."""
    with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
        yield


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    for dep in (get_current_user, get_optional_user, get_creator_user,
                get_verified_current_user, get_verified_creator_user):
        app.dependency_overrides[dep] = lambda u=user: u


def as_anonymous():
    app.dependency_overrides[get_optional_user] = lambda: None


@pytest.fixture
def embody_like(db, make_space, make_user):
    """A purchase-required Collective shaped like EMBODY: a term
    option granting a Series plus two Pathways, sold either in full or
    over ten weekly instalments."""
    from app.models.platform import EventSeries, Pathway

    owner = make_user(role="creator")
    space = make_space(
        is_public=True, creator=owner, join_policy="purchase_required",
    )
    series = EventSeries(
        id=f"es_{uuid.uuid4().hex[:12]}", space_id=space.id,
        slug="term-4", title="Term 4 2026", status="published",
        starts_at=datetime(2026, 10, 5), ends_at=datetime(2026, 12, 12),
    )
    db.add(series)
    pathway = Pathway(
        id=str(uuid.uuid4()), space_id=space.id, slug="in-person",
        title="In-Person Sessions", status="active",
    )
    db.add(pathway)
    db.flush()

    option = PaymentOption(
        id=f"po_{uuid.uuid4().hex[:12]}", space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Awaken — 1 Session per week",
        payment_type=PaymentOptionType.term_pass,
        status=PaymentOptionStatus.published,
        currency="AUD",
        # Exactly the production shape that broke the first version:
        # the authoring price columns are empty; the real commitment
        # lives on the schedules below.
        override_total_cents=None, calculated_total_cents=None,
        term_start_date=date(2026, 10, 5), term_end_date=date(2026, 12, 12),
        is_joining_option=False,
    )
    db.add(option)
    db.flush()
    db.add(PaymentOptionGrant(
        id=str(uuid.uuid4()), payment_option_id=option.id,
        grant_kind="event_series", series_id=series.id,
        sessions_per_week=1, total_sessions=10,
    ))
    db.add(PaymentOptionGrant(
        id=str(uuid.uuid4()), payment_option_id=option.id,
        grant_kind="pathway", pathway_id=pathway.id,
    ))
    db.add(PaymentOptionSchedule(
        id=str(uuid.uuid4()), payment_option_id=option.id,
        name="Pay in full", schedule_type="pay_in_full", status="published",
        total_amount_cents=18000, currency="AUD", position=0,
    ))
    db.add(PaymentOptionSchedule(
        id=str(uuid.uuid4()), payment_option_id=option.id,
        name="Weekly payments", schedule_type="recurring_installments",
        status="published", total_amount_cents=18000,
        installment_amount_cents=1800, installment_count=10,
        interval="week", stripe_interval="week", stripe_interval_count=1,
        currency="AUD", position=1,
    ))
    db.flush()
    return {"space": space, "owner": owner, "option": option, "series": series}


class TestTheWholeSeam:
    def test_nomination_travels_from_creator_to_a_valid_checkout_request(
        self, client, db, embody_like, plans_enabled,
    ):
        space, owner, option = (
            embody_like["space"], embody_like["owner"], embody_like["option"],
        )
        as_user(owner)
        base = f"/api/creator/spaces/{space.slug}/commerce/payment-options"

        # 1. Nothing is a door yet, so the Collective is closed.
        as_anonymous()
        assert client.get(f"/api/spaces/{space.slug}").json()["joining_options"] == []

        # 2. The creator nominates it.
        as_user(owner)
        patched = client.patch(f"{base}/{option.id}", json={"is_joining_option": True})
        assert patched.status_code == 200, patched.text

        # 3. The row actually changed — not just the response.
        db.refresh(option)
        assert option.is_joining_option is True, "the allowlist swallowed it"

        # 4. The response said so too.
        assert patched.json()["is_joining_option"] is True

        # 5. And it survives a reload, which is where the creator
        #    would have noticed the checkbox untick itself.
        reloaded = client.get(base).json()
        assert [o["is_joining_option"] for o in reloaded if o["id"] == option.id] == [True]

        # 6. The public payload now carries the door.
        as_anonymous()
        body = client.get(f"/api/spaces/{space.slug}").json()
        assert body["join_policy"] == "purchase_required"
        doors = body["joining_options"]
        assert len(doors) == 1
        door = doors[0]
        assert door["name"] == "Awaken — 1 Session per week"

        # 7. With a real price, from the schedules — the Option's own
        #    price columns are NULL, which is what used to render
        #    "No price set".
        assert door["price_cents"] == 18000
        assert door["currency"] == "AUD"

        # 8. And both ways to pay, each marked checkoutable.
        by_type = {s["schedule_type"]: s for s in door["schedules"]}
        assert set(by_type) == {"pay_in_full", "recurring_installments"}
        assert by_type["pay_in_full"]["total_amount_cents"] == 18000
        plan = by_type["recurring_installments"]
        assert plan["installment_amount_cents"] == 1800
        assert plan["installment_count"] == 10
        assert plan["interval"] == "week"
        assert all(s["is_member_checkoutable"] for s in door["schedules"])

        # 9. A checkout request built from that door satisfies the
        #    endpoint's schema — both ids present. The first door sent
        #    only the option id and 422'd before any logic ran.
        for schedule in door["schedules"]:
            req = UnifiedCheckoutRequest(
                payment_option_id=door["id"],
                payment_option_schedule_id=schedule["id"],
                success_url="https://x.test/spaces/s/about?checkout=success",
                cancel_url="https://x.test/spaces/s/about?checkout=cancel",
            )
            assert req.payment_option_id == option.id
            assert req.payment_option_schedule_id == schedule["id"]

    def test_the_pay_in_full_and_plan_ids_are_distinct_and_real(
        self, client, db, embody_like, plans_enabled,
    ):
        """Each CTA must carry its own schedule — sending the same id
        for both would silently charge the wrong commitment."""
        space, owner, option = (
            embody_like["space"], embody_like["owner"], embody_like["option"],
        )
        as_user(owner)
        client.patch(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/{option.id}",
            json={"is_joining_option": True},
        )
        as_anonymous()
        door = client.get(f"/api/spaces/{space.slug}").json()["joining_options"][0]
        ids = [s["id"] for s in door["schedules"]]
        assert len(set(ids)) == 2
        stored = {
            s.id for s in db.query(PaymentOptionSchedule).filter(
                PaymentOptionSchedule.payment_option_id == option.id,
            )
        }
        assert set(ids) <= stored


class TestDoorsThatMustNotOpen:
    @pytest.mark.parametrize("status", [
        PaymentOptionStatus.draft, PaymentOptionStatus.archived,
    ])
    def test_an_unpublished_option_stays_hidden_even_when_nominated(
        self, client, db, embody_like, status,
    ):
        option = embody_like["option"]
        option.is_joining_option = True
        option.status = status
        db.flush()
        as_anonymous()
        body = client.get(f"/api/spaces/{embody_like['space'].slug}").json()
        assert body["joining_options"] == []

    def test_an_option_with_no_checkoutable_schedule_is_withheld(
        self, client, db, embody_like,
    ):
        """A door that cannot complete a purchase is not a door.
        Better to show none than a button that 4xx's."""
        option = embody_like["option"]
        option.is_joining_option = True
        for s in db.query(PaymentOptionSchedule).filter(
            PaymentOptionSchedule.payment_option_id == option.id,
        ):
            s.status = "draft"
        db.flush()
        as_anonymous()
        body = client.get(f"/api/spaces/{embody_like['space'].slug}").json()
        assert body["joining_options"] == []

    def test_purchase_required_with_no_doors_stays_closed(
        self, client, db, embody_like, make_user,
    ):
        """And there is still no free escape hatch."""
        as_anonymous()
        assert client.get(
            f"/api/spaces/{embody_like['space'].slug}").json()["joining_options"] == []
        as_user(make_user(role="user"))
        res = client.post(f"/api/spaces/{embody_like['space'].slug}/join")
        assert res.status_code == 403
        assert res.json()["detail"]["code"] == "join_purchase_required"


class TestOpenCollectivesUnchanged:
    def test_an_open_collective_advertises_nothing_and_joins_freely(
        self, client, db, embody_like, make_user,
    ):
        space, option = embody_like["space"], embody_like["option"]
        space.join_policy = "open"
        option.is_joining_option = True
        db.flush()

        as_anonymous()
        assert client.get(f"/api/spaces/{space.slug}").json()["joining_options"] == []

        joiner = make_user(role="user")
        as_user(joiner)
        assert client.post(f"/api/spaces/{space.slug}/join").status_code == 201


class TestPriceSemantics:
    def test_the_headline_prefers_pay_in_full(self, db, embody_like):
        from app.spaces.joining_doors import list_joining_doors
        embody_like["option"].is_joining_option = True
        db.flush()
        door = list_joining_doors(db, embody_like["space"])[0]
        assert door["price_cents"] == 18000

    def test_a_plan_only_option_still_prices(self, db, embody_like):
        """No pay-in-full schedule is not the same as no price."""
        from app.spaces.joining_doors import list_joining_doors
        option = embody_like["option"]
        option.is_joining_option = True
        db.query(PaymentOptionSchedule).filter(
            PaymentOptionSchedule.payment_option_id == option.id,
            PaymentOptionSchedule.schedule_type == "pay_in_full",
        ).delete()
        db.flush()
        doors = list_joining_doors(db, embody_like["space"])
        # Whether a plan-only option is checkoutable depends on a
        # platform gate; either it is offered with a real price, or it
        # is withheld entirely. It must never be offered priceless.
        if doors:
            assert doors[0]["price_cents"] == 18000

    def test_legacy_option_columns_are_not_the_source(self, db, embody_like):
        """Setting them must not change the advertised price — the
        schedules are authoritative."""
        from app.spaces.joining_doors import list_joining_doors
        option = embody_like["option"]
        option.is_joining_option = True
        option.override_total_cents = 999_99
        option.calculated_total_cents = 888_88
        db.flush()
        door = list_joining_doors(db, embody_like["space"])[0]
        assert door["price_cents"] == 18000


class TestTheCheckoutGate:
    def test_with_plans_off_only_pay_in_full_is_offered(
        self, client, db, embody_like,
    ):
        """The door follows the platform gate rather than re-encoding
        it, so it can never advertise a plan the endpoint refuses."""
        from app.spaces.joining_doors import list_joining_doors
        embody_like["option"].is_joining_option = True
        db.flush()
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", False,
        ):
            door = list_joining_doors(db, embody_like["space"])[0]
        assert [s["schedule_type"] for s in door["schedules"]] == ["pay_in_full"]
        assert door["price_cents"] == 18000

    def test_with_plans_on_both_ways_to_pay_are_offered(
        self, client, db, embody_like, plans_enabled,
    ):
        from app.spaces.joining_doors import list_joining_doors
        embody_like["option"].is_joining_option = True
        db.flush()
        door = list_joining_doors(db, embody_like["space"])[0]
        assert {s["schedule_type"] for s in door["schedules"]} == {
            "pay_in_full", "recurring_installments",
        }


class TestDoorsDescribeWhatTheyGrant:
    """The About page tells a visitor what their purchase brings. It
    must read that from the same grant rows fulfilment does, or the
    page and the purchase drift — which is how the card came to
    advertise a second payment that did not exist."""

    def test_a_door_carries_its_grant_titles(self, client, db, embody_like):
        from app.spaces.joining_doors import list_joining_doors
        embody_like["option"].is_joining_option = True
        db.flush()
        door = list_joining_doors(db, embody_like["space"])[0]
        assert door["included_titles"] == ["Term 4 2026", "In-Person Sessions"]

    def test_a_door_carries_its_session_allowance(self, db, embody_like):
        from app.spaces.joining_doors import list_joining_doors
        embody_like["option"].is_joining_option = True
        db.flush()
        door = list_joining_doors(db, embody_like["space"])[0]
        assert door["sessions_per_week"] == 1
        assert door["sessions_total"] == 10

    def test_titles_come_from_grants_not_from_the_creator_summaries(
        self, db, embody_like,
    ):
        """``paid_content_summary`` describes the old shape — free
        membership, paid content inside — and must not be what the
        joining purchase is described by."""
        from app.spaces.joining_doors import list_joining_doors
        space = embody_like["space"]
        space.paid_content_summary = "Term access is paid separately"
        space.included_access_summary = "Community and updates"
        embody_like["option"].is_joining_option = True
        db.flush()
        door = list_joining_doors(db, space)[0]
        assert "Term 4 2026" in door["included_titles"]
        assert "paid separately" not in " ".join(door["included_titles"]).lower()

    def test_a_door_with_no_grants_reports_an_empty_list_not_an_error(
        self, db, embody_like,
    ):
        from app.models.payment_option_grant import PaymentOptionGrant
        from app.spaces.joining_doors import list_joining_doors
        option = embody_like["option"]
        option.is_joining_option = True
        db.query(PaymentOptionGrant).filter(
            PaymentOptionGrant.payment_option_id == option.id,
        ).delete()
        db.flush()
        door = list_joining_doors(db, embody_like["space"])[0]
        assert door["included_titles"] == []
        assert door["sessions_per_week"] is None
