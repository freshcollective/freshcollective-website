"""Creator Studio Experience Picker visibility rules.

Regression: the picker was surfacing every Pathway / Series /
Gathering for the Collective — including archived rows the Creator
had already retired from their own Pathways management surface.
A Creator could pick an archived Pathway as a Payment Option
grant, promising a member access to something they can't actually
open. This test locks in the picker's post-fix visibility rule.

The Creator Studio Pathways list already hides ``archived`` (see
``frontend/src/app/creator-studio/pathways/PathwaysClient.tsx``
line ``visiblePathways = pathways.filter(p.status !== 'archived')``);
the picker now mirrors that predicate for consistency.

Draft + Coming Soon + Active remain selectable so a Creator can
still pre-bundle a Coming Soon Pathway into a Payment Option.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.creator._space_payment_options_routes import list_grantable_experiences


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def grove_like(db, make_user, make_space):
    """A Space with one Pathway per status + a Series + a Gathering
    covering every visibility state the picker filter must consider."""
    from app.models.platform import Pathway, EventSeries, Event

    creator = make_user(role="creator")
    space = make_space(creator=creator)

    def _pathway(*, title: str, status: str) -> Pathway:
        p = Pathway(
            id=_uid("p"),
            space_id=space.id,
            slug=f"p-{uuid.uuid4().hex[:8]}",
            title=title,
            status=status,
            access_type="one_time",
            pathway_type="guided_experience",
            currency="AUD",
            is_sequential=False,
            position=0,
        )
        db.add(p)
        return p

    active   = _pathway(title="Active Pathway",   status="active")
    draft    = _pathway(title="Draft Pathway",    status="draft")
    soon     = _pathway(title="Coming Soon Path", status="coming_soon")
    archived = _pathway(title="Archived Old Path", status="archived")

    starts = datetime.utcnow() + timedelta(days=1)
    series_active = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Active Series", starts_at=starts, status="published",
        published_at=starts,
    )
    series_archived = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Archived Series", starts_at=starts, status="archived",
    )
    db.add_all([series_active, series_archived])

    event_active = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Standalone Gathering",
        starts_at=starts, ends_at=starts + timedelta(hours=1),
        location_type="zoom", is_published=True, status="active",
        gathering_type="workshop", attendance_format="online",
        booking_access_type="all_members",
    )
    event_cancelled = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Cancelled Gathering",
        starts_at=starts, ends_at=starts + timedelta(hours=1),
        location_type="zoom", is_published=True, status="cancelled",
        gathering_type="workshop", attendance_format="online",
        booking_access_type="all_members",
    )
    db.add_all([event_active, event_cancelled])
    db.commit()

    return dict(
        space=space, creator=creator,
        pathways={"active": active, "draft": draft, "soon": soon, "archived": archived},
        series={"active": series_active, "archived": series_archived},
        events={"active": event_active, "cancelled": event_cancelled},
    )


class TestPickerFiltering:
    def test_archived_pathway_hidden(self, db, grove_like):
        rows = list_grantable_experiences(
            slug=grove_like["space"].slug, db=db,
            current_user=grove_like["creator"],
        )
        titles = {r["title"] for r in rows}
        assert "Archived Old Path" not in titles

    def test_active_draft_coming_soon_pathways_visible(self, db, grove_like):
        rows = list_grantable_experiences(
            slug=grove_like["space"].slug, db=db,
            current_user=grove_like["creator"],
        )
        titles = {r["title"] for r in rows if r["kind"] == "pathway"}
        assert "Active Pathway"    in titles
        assert "Draft Pathway"     in titles
        assert "Coming Soon Path"  in titles
        # And the archived one is not.
        assert "Archived Old Path" not in titles

    def test_series_archived_hidden(self, db, grove_like):
        rows = list_grantable_experiences(
            slug=grove_like["space"].slug, db=db,
            current_user=grove_like["creator"],
        )
        series_titles = {r["title"] for r in rows if r["kind"] == "event_series"}
        assert "Active Series"   in series_titles
        assert "Archived Series" not in series_titles

    def test_standalone_gathering_visible_but_frontend_disables_it(
        self, db, grove_like,
    ):
        """Backend still returns standalone Gatherings — the frontend
        Experience Picker renders them with an explicit 'Not yet
        available for Payment Options' badge + disabled Add. Keeping
        them backend-visible preserves roadmap clarity in the UI
        without letting the fulfilment layer see a new
        Gathering-grant it can't honour."""
        rows = list_grantable_experiences(
            slug=grove_like["space"].slug, db=db,
            current_user=grove_like["creator"],
        )
        gathering_titles = {r["title"] for r in rows if r["kind"] == "gathering"}
        assert "Standalone Gathering" in gathering_titles
        # Cancelled events are Event-lifecycle archive equivalent.
        assert "Cancelled Gathering" not in gathering_titles


class TestSnapshotImmutability:
    """A PurchasePlan's ``snapshot_grants_json`` must NOT change when
    the Creator later edits the Payment Option's grants. The plan
    represents a commercial commitment fixed at purchase time — the
    member paid for what was promised at that moment.

    This test simulates the exact browser-observed scenario: a plan
    is created snapshotting the current grants, then the Creator
    adds a new grant to the underlying Payment Option. Reads back
    the plan and asserts the snapshot is byte-identical to what was
    captured at creation."""

    def test_editing_option_grants_does_not_mutate_plan_snapshot(
        self, db, make_user, make_space,
    ):
        from app.models.payment_option import (
            PaymentOption, PaymentOptionStatus, PaymentOptionType,
        )
        from app.models.payment_option_grant import PaymentOptionGrant
        from app.models.payment_option_schedule import PaymentOptionSchedule
        from app.models.platform import Pathway, Event
        from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
        from app.services.purchase_fulfilment import (
            resolve_intent_for_option, serialise_intent,
        )

        creator = make_user(role="creator")
        member  = make_user()
        space   = make_space(creator=creator)

        # A Payment Option with one Pathway grant at the moment of
        # plan creation.
        pathway = Pathway(
            id=_uid("p"), space_id=space.id,
            slug=f"p-{uuid.uuid4().hex[:8]}", title="Initial Pathway",
            status="active", access_type="one_time",
            pathway_type="guided_experience", currency="AUD",
            is_sequential=False, position=0,
        )
        db.add(pathway)
        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            attaches_to_kind="pathway", attaches_to_id=pathway.id,
            name="FIP2 Immutability Test",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=6000, currency="AUD",
        )
        db.add(opt)
        db.flush()
        initial_grant = PaymentOptionGrant(
            payment_option_id=opt.id,
            grant_kind="pathway", pathway_id=pathway.id,
        )
        db.add(initial_grant)
        sched = PaymentOptionSchedule(
            id=_uid("sched"), payment_option_id=opt.id,
            name="Weekly × 3", schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2000, installment_count=3,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=6000, currency="AUD",
        )
        db.add(sched)
        db.commit()

        # Create the plan with its snapshot.
        now = datetime.utcnow()
        resolution = resolve_intent_for_option(
            db, payment_option=opt, metadata_pathway_id=None, now=now,
        )
        snapshot_at_creation = serialise_intent(resolution.intent)
        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=member.id, payment_option_id=opt.id,
            payment_option_schedule_id=sched.id, space_id=space.id,
            status=PurchasePlanStatus.pending_setup,
            currency="AUD",
            installment_amount_cents=2000, installments_expected=3,
            total_expected_cents=6000,
            stripe_interval="week", stripe_interval_count=1,
            snapshot_grants_json=snapshot_at_creation,
            stripe_mode="test",
        )
        db.add(plan)
        db.commit()
        plan_id = plan.id

        # Sanity: snapshot has exactly one entitlement.
        assert len(snapshot_at_creation["entitlements"]) == 1

        # Creator now adds a second grant to the Payment Option
        # (e.g. a Gathering) — this simulates the exact browser
        # scenario the user flagged.
        gathering = Event(
            id=_uid("e"), space_id=space.id, created_by_id=creator.id,
            title="Late-added Gathering",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
            location_type="zoom", is_published=True, status="active",
            gathering_type="workshop", attendance_format="online",
            booking_access_type="all_members",
        )
        db.add(gathering)
        db.flush()
        late_grant = PaymentOptionGrant(
            payment_option_id=opt.id,
            grant_kind="gathering", event_id=gathering.id,
        )
        db.add(late_grant)
        db.commit()

        # Re-read the plan. Snapshot must be byte-identical to what
        # was captured at plan creation — the Creator's edit must
        # not have retroactively rewritten it.
        db.expire_all()
        plan_after = db.execute(
            __import__("sqlalchemy").text(
                "SELECT snapshot_grants_json FROM purchase_plans WHERE id = :p"
            ),
            {"p": plan_id},
        ).one()
        assert plan_after.snapshot_grants_json == snapshot_at_creation

        # And to prove the Creator edit did land on the option
        # itself (so this test isn't a false positive because the
        # edit silently failed): current option grants count = 2.
        current_grants = db.execute(
            __import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM payment_option_grants "
                "WHERE payment_option_id = :o"
            ),
            {"o": opt.id},
        ).scalar_one()
        assert current_grants == 2
