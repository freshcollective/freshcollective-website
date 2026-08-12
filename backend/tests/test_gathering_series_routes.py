"""Gathering Series creator API — Step 2 route tests.

Covers the CRUD, attach-via-event-PATCH flow, series-scoped Payment
Option surface, and the BulkEventCreateResponse naming (canonical
``recurrence_series_id`` + deprecated ``series_id`` alias).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.creator._gathering_series_routes import (
    create_gathering_series,
    create_series_payment_option,
    delete_gathering_series,
    delete_series_payment_option,
    get_gathering_series,
    list_gathering_series,
    list_series_gatherings,
    list_series_payment_options,
    update_gathering_series,
    update_series_payment_option,
)
from app.creator.routes import (
    bulk_create_events,
    create_event,
    update_event,
)
from app.creator.schemas import (
    EventCreateRequest,
    EventUpdateRequest,
    GatheringSeriesCreateRequest,
    GatheringSeriesUpdateRequest,
    RecurrenceRequest,
    SeriesPaymentOptionCreateRequest,
    SeriesPaymentOptionUpdateRequest,
)
from app.models.access_pass import AccessPassStatus
from app.models.creator_billing import CreatorPlan, CreatorSubscription
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.platform import (
    Event,
    EventSeries,
    Pathway,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _seed_creator_plan(db):
    """Autouse — every creator user resolves to the cheapest active
    plan (Creator) via resolve_creator_plan's fallback."""
    if not db.query(CreatorPlan).filter(CreatorPlan.slug == "creator").first():
        db.add(CreatorPlan(
            id=_uid("plan"),
            name="Creator",
            slug="creator",
            monthly_price_cents=1900,
            currency="AUD",
            transaction_fee_basis_points=800,
            collective_limit=1,
            is_active=True,
        ))
        db.flush()
    yield


# ---------------------------------------------------------------------------
# Series CRUD
# ---------------------------------------------------------------------------


class TestSeriesCRUD:
    def test_create_series_with_ends_at(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        body = GatheringSeriesCreateRequest(
            title="EMBODY Spring Term",
            description="Six weeks in a small circle.",
            starts_at=datetime.utcnow() + timedelta(days=14),
            ends_at=datetime.utcnow() + timedelta(days=70),
        )
        row = create_gathering_series(
            slug=space.slug, body=body, db=db, current_user=creator,
        )
        assert row["title"] == "EMBODY Spring Term"
        assert row["status"] == "draft"
        assert row["ends_at"] is not None
        assert row["slug"].startswith("embody-spring-term")

    def test_create_series_without_ends_at_is_ongoing(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        row = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Ongoing Weekly Circle",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        assert row["ends_at"] is None

    def test_create_series_end_before_start_rejected(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        with pytest.raises(HTTPException) as ex:
            create_gathering_series(
                slug=space.slug,
                body=GatheringSeriesCreateRequest(
                    title="Bad",
                    starts_at=datetime.utcnow() + timedelta(days=10),
                    ends_at=datetime.utcnow() + timedelta(days=5),
                ),
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 400

    def test_slug_collision_auto_suffixed(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        r1 = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Spring Term",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        r2 = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Spring Term",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        assert r1["slug"] != r2["slug"]

    def test_update_clears_ends_at_to_ongoing(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        r = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term",
                starts_at=datetime.utcnow(),
                ends_at=datetime.utcnow() + timedelta(days=30),
            ),
            db=db, current_user=creator,
        )
        assert r["ends_at"] is not None
        r2 = update_gathering_series(
            slug=space.slug, series_slug=r["slug"],
            body=GatheringSeriesUpdateRequest(ends_at=None),
            db=db, current_user=creator,
        )
        assert r2["ends_at"] is None

    def test_delete_empty_series_succeeds(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        r = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Empty",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        delete_gathering_series(
            slug=space.slug, series_slug=r["slug"],
            db=db, current_user=creator,
        )
        assert db.query(EventSeries).filter(EventSeries.id == r["id"]).first() is None

    def test_delete_draft_series_auto_detaches_events(
        self, db, make_user, make_space,
    ):
        """Under the Step-2 polish lifecycle rule, a draft Series that
        has never been published can be permanently deleted. Attached
        Gatherings are auto-detached — they are NOT deleted, and the
        historic ``recurrence_series_id`` tag on each Event remains
        intact so any bulk-create provenance survives."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Has-events",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        e = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Session",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                attendance_format="online",
                booking_access_type="included_with_collective",
                series_id=s["id"],
            ),
            db=db, current_user=creator,
        )
        delete_gathering_series(
            slug=space.slug, series_slug=s["slug"],
            db=db, current_user=creator,
        )
        # Series row gone.
        assert db.query(EventSeries).filter(EventSeries.id == s["id"]).first() is None
        # Event row survives; series_id cleared.
        db.expire_all()
        ev = db.query(Event).filter(Event.id == e["id"]).one()
        assert ev.series_id is None

    def test_delete_published_series_refused(
        self, db, make_user, make_space,
    ):
        """Once a Series has been published, ``published_at`` is set
        and never cleared. Hard-delete refuses; the Creator must
        archive instead so historical AccessPass references remain
        resolvable."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Published-once",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        # Publish then unpublish → published_at is still set.
        update_gathering_series(
            slug=space.slug, series_slug=s["slug"],
            body=GatheringSeriesUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        update_gathering_series(
            slug=space.slug, series_slug=s["slug"],
            body=GatheringSeriesUpdateRequest(status="draft"),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as ex:
            delete_gathering_series(
                slug=space.slug, series_slug=s["slug"],
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 409

    def test_delete_series_with_active_options_refused(
        self, db, make_user, make_space,
    ):
        """Active Payment Options are not silently archived by
        deleting the Series — the Creator must archive them
        explicitly first."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Draft-with-active-po",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        create_series_payment_option(
            slug=space.slug, series_slug=s["slug"],
            body=SeriesPaymentOptionCreateRequest(
                name="Live", payment_type="term_pass", status="published",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as ex:
            delete_gathering_series(
                slug=space.slug, series_slug=s["slug"],
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 409

    def test_publish_stamps_published_at_once(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Stamp",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        assert s["published_at"] is None
        updated = update_gathering_series(
            slug=space.slug, series_slug=s["slug"],
            body=GatheringSeriesUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        assert updated["published_at"] is not None
        first_stamp = updated["published_at"]
        # Republish after unpublish must NOT reset the stamp.
        update_gathering_series(
            slug=space.slug, series_slug=s["slug"],
            body=GatheringSeriesUpdateRequest(status="draft"),
            db=db, current_user=creator,
        )
        re_pub = update_gathering_series(
            slug=space.slug, series_slug=s["slug"],
            body=GatheringSeriesUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        assert re_pub["published_at"] == first_stamp

    def test_list_series_returns_counts(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term", starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Session A",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                booking_access_type="included_with_collective",
                series_id=s["id"],
            ),
            db=db, current_user=creator,
        )
        create_series_payment_option(
            slug=space.slug, series_slug=s["slug"],
            body=SeriesPaymentOptionCreateRequest(
                name="Awaken",
                payment_type="term_pass",
                status="published",
                total_sessions=10, sessions_per_week=1,
                price_per_session_cents=2000,
            ),
            db=db, current_user=creator,
        )
        rows = list_gathering_series(
            slug=space.slug, db=db, current_user=creator,
        )
        assert len(rows) == 1
        assert rows[0]["gathering_count"] == 1
        assert rows[0]["payment_option_count"] == 1


# ---------------------------------------------------------------------------
# Event <-> Series attach / detach via event PATCH
# ---------------------------------------------------------------------------


class TestEventSeriesAttachment:
    def test_attach_via_patch(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term", starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        e = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Standalone Session",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                booking_access_type="included_with_collective",
            ),
            db=db, current_user=creator,
        )
        assert e["series_id"] is None

        updated = update_event(
            slug=space.slug, event_id=e["id"],
            body=EventUpdateRequest(series_id=s["id"]),
            db=db, current_user=creator,
        )
        assert updated["series_id"] == s["id"]

    def test_detach_via_patch_null(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term", starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        e = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Session",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                booking_access_type="included_with_collective",
                series_id=s["id"],
            ),
            db=db, current_user=creator,
        )
        assert e["series_id"] == s["id"]

        detached = update_event(
            slug=space.slug, event_id=e["id"],
            body=EventUpdateRequest(series_id=None),
            db=db, current_user=creator,
        )
        assert detached["series_id"] is None

    def test_attach_rejects_series_from_other_space(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space_a = make_space(creator=creator)
        space_b = make_space(creator=creator)
        db.commit()
        s_b = create_gathering_series(
            slug=space_b.slug,
            body=GatheringSeriesCreateRequest(
                title="B-series", starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as ex:
            create_event(
                slug=space_a.slug,
                body=EventCreateRequest(
                    title="Cross-space",
                    starts_at=datetime.utcnow() + timedelta(days=1),
                    gathering_type="circle",
                    booking_access_type="included_with_collective",
                    series_id=s_b["id"],
                ),
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 400


# ---------------------------------------------------------------------------
# Recurring bulk-create assigns semantic series_id + response naming
# ---------------------------------------------------------------------------


class TestBulkCreateAssignsSeries:
    def test_bulk_create_all_events_belong_to_series(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term",
                starts_at=datetime.utcnow(),
                ends_at=datetime.utcnow() + timedelta(days=90),
            ),
            db=db, current_user=creator,
        )
        # Weekly, Mon+Wed, for 4 occurrences.
        resp = bulk_create_events(
            slug=space.slug,
            body=EventCreateRequest(
                title="EMBODY Session",
                starts_at=datetime.utcnow() + timedelta(days=1),
                ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
                gathering_type="circle",
                booking_access_type="included_with_series",
                series_id=s["id"],
                recurrence=RecurrenceRequest(
                    days_of_week=[0, 2],  # Mon + Wed
                    end_after_n=4,
                ),
            ),
            db=db, current_user=creator,
        )
        assert resp.created_count == 4
        # Both response names carry the same recurrence tag.
        assert resp.recurrence_series_id == resp.series_id
        # Every generated Event carries the semantic series link too.
        for e in db.query(Event).filter(Event.recurrence_series_id == resp.recurrence_series_id).all():
            assert e.series_id == s["id"]

    def test_bulk_response_alias_is_deprecated_but_present(
        self, db, make_user, make_space,
    ):
        """The deprecated ``series_id`` field is still on the wire so
        legacy callers don't break. Same value as
        ``recurrence_series_id`` — this test locks that in."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        resp = bulk_create_events(
            slug=space.slug,
            body=EventCreateRequest(
                title="X",
                starts_at=datetime.utcnow() + timedelta(days=1),
                ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
                gathering_type="circle",
                booking_access_type="included_with_collective",
                recurrence=RecurrenceRequest(
                    days_of_week=[1], end_after_n=2,
                ),
            ),
            db=db, current_user=creator,
        )
        payload = resp.model_dump()
        assert payload["recurrence_series_id"] == payload["series_id"]


# ---------------------------------------------------------------------------
# Series-attached Payment Options
# ---------------------------------------------------------------------------


class TestSeriesPaymentOptions:
    def test_create_series_payment_option_default_shape(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term",
                starts_at=datetime.utcnow(),
                ends_at=datetime.utcnow() + timedelta(days=60),
            ),
            db=db, current_user=creator,
        )
        opt = create_series_payment_option(
            slug=space.slug, series_slug=s["slug"],
            body=SeriesPaymentOptionCreateRequest(
                name="Activate",
                payment_type="term_pass",
                status="published",
                total_sessions=20,
                sessions_per_week=2,
                price_per_session_cents=1700,
            ),
            db=db, current_user=creator,
        )
        assert opt["attaches_to_kind"] == "event_series"
        assert opt["attaches_to_id"] == s["id"]
        assert opt["pathway_id"] is None
        assert opt["calculated_total_cents"] == 20 * 1700
        assert opt["grants_pathway_id"] is None

    def test_grants_pathway_id_validated_against_space(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space_a = make_space(creator=creator)
        space_b = make_space(creator=creator)
        db.commit()
        # Pathway in space_b — cannot be granted from a space_a series option.
        pw_b = Pathway(
            id=_uid("pw"),
            space_id=space_b.id,
            slug="p",
            title="Elsewhere",
            status="active",
            access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw_b)
        db.flush()

        s = create_gathering_series(
            slug=space_a.slug,
            body=GatheringSeriesCreateRequest(
                title="Term-A",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as ex:
            create_series_payment_option(
                slug=space_a.slug, series_slug=s["slug"],
                body=SeriesPaymentOptionCreateRequest(
                    name="Bundle",
                    payment_type="term_pass",
                    grants_pathway_id=pw_b.id,
                ),
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 400

    def test_delete_option_soft_archives(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term", starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        opt = create_series_payment_option(
            slug=space.slug, series_slug=s["slug"],
            body=SeriesPaymentOptionCreateRequest(
                name="Doomed", payment_type="term_pass",
            ),
            db=db, current_user=creator,
        )
        delete_series_payment_option(
            slug=space.slug, series_slug=s["slug"],
            option_id=opt["id"], db=db, current_user=creator,
        )
        row = db.query(PaymentOption).filter(PaymentOption.id == opt["id"]).one()
        assert row.status == PaymentOptionStatus.archived

    def test_update_grants_pathway_id_clear_via_null(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        pw = Pathway(
            id=_uid("pw"),
            space_id=space.id,
            slug="practice",
            title="Practice",
            status="active",
            access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw)
        db.flush()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term", starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        opt = create_series_payment_option(
            slug=space.slug, series_slug=s["slug"],
            body=SeriesPaymentOptionCreateRequest(
                name="Includes-Pathway",
                payment_type="term_pass",
                grants_pathway_id=pw.id,
            ),
            db=db, current_user=creator,
        )
        assert opt["grants_pathway_id"] == pw.id

        cleared = update_series_payment_option(
            slug=space.slug, series_slug=s["slug"], option_id=opt["id"],
            body=SeriesPaymentOptionUpdateRequest(grants_pathway_id=None),
            db=db, current_user=creator,
        )
        assert cleared["grants_pathway_id"] is None


# ---------------------------------------------------------------------------
# Serialisation of pathway-attached options carries the polymorphic fields
# ---------------------------------------------------------------------------


class TestPaymentOptionSerialisation:
    def test_pathway_option_response_exposes_attaches_to(
        self, db, make_user, make_space,
    ):
        """Sanity: existing pathway-attached options serialise the new
        polymorphic fields so the frontend can key on them safely."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pw = Pathway(
            id=_uid("pw"),
            space_id=space.id,
            slug="p",
            title="P",
            status="active",
            access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw)
        db.flush()
        opt = PaymentOption(
            id=_uid("po"),
            space_id=space.id,
            pathway_id=pw.id,
            attaches_to_kind="pathway",
            attaches_to_id=pw.id,
            name="One-off",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            currency="AUD",
        )
        db.add(opt)
        db.commit()

        from app.creator.routes import _option_to_dict as _dict
        d = _dict(opt)
        assert d["attaches_to_kind"] == "pathway"
        assert d["attaches_to_id"] == pw.id


# ---------------------------------------------------------------------------
# Series-pass invariant — an Event with booking_access_type =
# 'included_with_series' MUST belong to a Series. Enforced server-side
# for create + bulk create + update.
# ---------------------------------------------------------------------------


class TestSeriesPassInvariant:
    def test_create_series_pass_without_series_id_rejected(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        with pytest.raises(HTTPException) as ex:
            create_event(
                slug=space.slug,
                body=EventCreateRequest(
                    title="Broken",
                    starts_at=datetime.utcnow() + timedelta(days=1),
                    gathering_type="circle",
                    attendance_format="online",
                    booking_access_type="included_with_series",
                    # No series_id — this is the invalid pairing.
                ),
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 400
        assert "Series pass" in str(ex.value.detail)

    def test_create_series_pass_with_series_id_accepted(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        result = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Fine",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                attendance_format="online",
                booking_access_type="included_with_series",
                series_id=s["id"],
            ),
            db=db, current_user=creator,
        )
        assert result["booking_access_type"] == "included_with_series"
        assert result["series_id"] == s["id"]

    def test_bulk_create_series_pass_without_series_id_rejected(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        with pytest.raises(HTTPException) as ex:
            bulk_create_events(
                slug=space.slug,
                body=EventCreateRequest(
                    title="Weekly",
                    starts_at=datetime.utcnow() + timedelta(days=1),
                    ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
                    gathering_type="circle",
                    attendance_format="online",
                    booking_access_type="included_with_series",
                    # series_id omitted — invalid.
                    recurrence=RecurrenceRequest(
                        days_of_week=[0], end_after_n=3,
                    ),
                ),
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 400

    def test_update_detach_from_series_while_series_gated_rejected(
        self, db, make_user, make_space,
    ):
        """An existing Series-pass gathering cannot be detached from
        the Series without first changing its access type — the
        resulting state (series_id=null AND access=included_with_series)
        would be unresolvable and is refused."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        e = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Session",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                attendance_format="online",
                booking_access_type="included_with_series",
                series_id=s["id"],
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as ex:
            update_event(
                slug=space.slug, event_id=e["id"],
                body=EventUpdateRequest(series_id=None),
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 400

    def test_update_swap_access_and_detach_in_one_call_allowed(
        self, db, make_user, make_space,
    ):
        """The invariant checks the RESULTING state — a caller may
        change the access type away from Series pass AND clear the
        series id in the same PATCH."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        e = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Session",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                attendance_format="online",
                booking_access_type="included_with_series",
                series_id=s["id"],
            ),
            db=db, current_user=creator,
        )
        result = update_event(
            slug=space.slug, event_id=e["id"],
            body=EventUpdateRequest(
                booking_access_type="included_with_collective",
                series_id=None,
            ),
            db=db, current_user=creator,
        )
        assert result["booking_access_type"] == "included_with_collective"
        assert result["series_id"] is None

    def test_update_switch_to_series_pass_without_series_rejected(
        self, db, make_user, make_space,
    ):
        """Flipping an existing collective-gathering to Series pass
        without also attaching it to a Series is refused."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        e = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Standalone",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                attendance_format="online",
                booking_access_type="included_with_collective",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as ex:
            update_event(
                slug=space.slug, event_id=e["id"],
                body=EventUpdateRequest(
                    booking_access_type="included_with_series",
                    # No series_id → resulting state is invalid.
                ),
                db=db, current_user=creator,
            )
        assert ex.value.status_code == 400

    def test_update_attach_and_switch_together_allowed(
        self, db, make_user, make_space,
    ):
        """Attaching to a Series AND switching to Series pass in the
        same PATCH is allowed — the resulting state is valid."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        s = create_gathering_series(
            slug=space.slug,
            body=GatheringSeriesCreateRequest(
                title="Term",
                starts_at=datetime.utcnow(),
            ),
            db=db, current_user=creator,
        )
        e = create_event(
            slug=space.slug,
            body=EventCreateRequest(
                title="Standalone",
                starts_at=datetime.utcnow() + timedelta(days=1),
                gathering_type="circle",
                attendance_format="online",
                booking_access_type="included_with_collective",
            ),
            db=db, current_user=creator,
        )
        result = update_event(
            slug=space.slug, event_id=e["id"],
            body=EventUpdateRequest(
                booking_access_type="included_with_series",
                series_id=s["id"],
            ),
            db=db, current_user=creator,
        )
        assert result["booking_access_type"] == "included_with_series"
        assert result["series_id"] == s["id"]
