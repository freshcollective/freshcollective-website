"""PaymentOptionGrant — B1 foundation tests.

Covers migration 108 in isolation. No behaviour change lives on top
of the grants table yet (backfill + code flip come in B2), so this
file exercises structural invariants only:

  * Model round-trip for each grant kind (pathway / event_series /
    gathering).
  * Relationship: ``PaymentOption.grants`` loads back what we insert.
  * CHECK constraint: exactly one target column populated, matched
    to ``grant_kind``.
  * CHECK constraint: Series-only fields (sessions_per_week /
    total_sessions / window overrides) refused on pathway /
    gathering grants.
  * Unique constraints: an Option cannot grant the same target
    twice.
  * FK cascade on Option delete: grants go with a deleted Option.
  * FK RESTRICT on target delete: hard-deleting a granted Pathway /
    Series / Event raises IntegrityError so the Creator must remove
    the grant first.
  * Pydantic ``PaymentOptionGrantCreate`` validator surfaces the
    same rules with a friendlier error.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.creator.schemas import PaymentOptionGrantCreate
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.platform import (
    Event,
    EventSeries,
    Pathway,
    PathwayType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_pathway(db, space, *, title: str = "Practice") -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status="active",
        access_type="free",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _make_series(
    db, space, *, title: str = "EMBODY Term",
) -> EventSeries:
    starts_at = datetime.utcnow() + timedelta(days=7)
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(days=90),
        status="published",
    )
    db.add(s)
    db.flush()
    return s


def _make_event(db, space) -> Event:
    """A published paid-separately event needs a ticket price (check
    constraint on events). Use ``included_with_collective`` here so
    the grant tests don't need to model the ticket price too — the
    grants layer doesn't care what access type the target event has."""
    e = Event(
        id=_uid("e"),
        space_id=space.id,
        created_by_id=space.creator_id,
        title="Standalone workshop",
        starts_at=datetime.utcnow() + timedelta(days=14),
        ends_at=datetime.utcnow() + timedelta(days=14, hours=2),
        location_type="zoom",
        is_published=True,
        status="active",
        requires_booking=True,
        capacity=20,
        booking_access_type="included_with_collective",
        gathering_type="workshop",
        attendance_format="online",
    )
    db.add(e)
    db.flush()
    return e


def _make_option(db, space, *, name: str = "Awaken") -> PaymentOption:
    """A minimally-valid PaymentOption for grant tests. Legacy
    ``attaches_to_*`` columns are still required — we point them at a
    throwaway pathway just to satisfy the NOT NULL constraints. B1
    intentionally leaves those columns in place."""
    p = _make_pathway(db, space, title=f"legacy target for {name}")
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=p.id,
        attaches_to_kind="pathway",
        attaches_to_id=p.id,
        name=name,
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=10000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


# ---------------------------------------------------------------------------
# Round-trip + relationship
# ---------------------------------------------------------------------------


class TestModelRoundTrip:
    def test_pathway_grant_round_trip(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space, title="The EMBODY Practice")

        g = PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="pathway",
            pathway_id=pathway.id,
        )
        db.add(g)
        db.commit()
        db.refresh(g)

        assert g.id  # default uuid populated
        assert g.grant_kind == "pathway"
        assert g.pathway_id == pathway.id
        assert g.series_id is None
        assert g.event_id is None
        assert g.sessions_per_week is None
        assert g.position == 0

    def test_event_series_grant_carries_series_only_fields(self, db, make_space):
        space = make_space()
        option = _make_option(db, space, name="Awaken")
        series = _make_series(db, space, title="EMBODY Term 3 2026")

        g = PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="event_series",
            series_id=series.id,
            sessions_per_week=1,
            total_sessions=10,
            valid_from_override=None,
            valid_until_override=None,
        )
        db.add(g)
        db.commit()
        db.refresh(g)

        assert g.series_id == series.id
        assert g.sessions_per_week == 1
        assert g.total_sessions == 10

    def test_gathering_grant_round_trip(self, db, make_space):
        space = make_space()
        option = _make_option(db, space, name="Standard ticket")
        event = _make_event(db, space)

        g = PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="gathering",
            event_id=event.id,
        )
        db.add(g)
        db.commit()
        db.refresh(g)

        assert g.event_id == event.id
        assert g.pathway_id is None
        assert g.series_id is None

    def test_option_relationship_orders_by_position(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        pw = _make_pathway(db, space, title="A")
        series = _make_series(db, space)

        # Insert intentionally in reverse position order.
        db.add(PaymentOptionGrant(
            payment_option_id=option.id, grant_kind="event_series",
            series_id=series.id, position=5,
        ))
        db.add(PaymentOptionGrant(
            payment_option_id=option.id, grant_kind="pathway",
            pathway_id=pw.id, position=0,
        ))
        db.commit()
        db.expire(option)  # force reload of the grants relationship

        kinds = [g.grant_kind for g in option.grants]
        assert kinds == ["pathway", "event_series"]  # position 0 then 5


# ---------------------------------------------------------------------------
# CHECK: target must match kind
# ---------------------------------------------------------------------------


class TestTargetMatchesKindConstraint:
    def test_pathway_kind_requires_pathway_id(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="pathway",
                pathway_id=None,
            ))
            db.commit()
        db.rollback()

    def test_pathway_kind_rejects_series_id(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space)
        series = _make_series(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="pathway",
                pathway_id=pathway.id,
                series_id=series.id,   # extraneous
            ))
            db.commit()
        db.rollback()

    def test_event_series_kind_requires_series_id(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="event_series",
                series_id=None,
            ))
            db.commit()
        db.rollback()

    def test_gathering_kind_requires_event_id(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="gathering",
                event_id=None,
            ))
            db.commit()
        db.rollback()

    def test_unknown_kind_rejected(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="bundle",  # not one of the three kinds
                pathway_id=pathway.id,
            ))
            db.commit()
        db.rollback()


# ---------------------------------------------------------------------------
# CHECK: Series-only fields never on non-Series grants
# ---------------------------------------------------------------------------


class TestSeriesOnlyFieldsConstraint:
    def test_pathway_grant_rejects_sessions_per_week(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="pathway",
                pathway_id=pathway.id,
                sessions_per_week=1,   # not valid for pathway grants
            ))
            db.commit()
        db.rollback()

    def test_gathering_grant_rejects_total_sessions(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        event = _make_event(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="gathering",
                event_id=event.id,
                total_sessions=5,      # not valid for gathering grants
            ))
            db.commit()
        db.rollback()

    def test_pathway_grant_accepts_window_override(self, db, make_space):
        """Migration 109 relaxed the constraint: Pathway grants may
        carry ``valid_from_override`` / ``valid_until_override`` so
        the backfill can encode the effective term end for bundled
        Pathway grants without fulfilment having to guess."""
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space)
        end = datetime.utcnow() + timedelta(days=30)
        g = PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="pathway",
            pathway_id=pathway.id,
            valid_until_override=end,
        )
        db.add(g)
        db.commit()
        db.refresh(g)
        assert g.valid_until_override == end

    def test_gathering_grant_rejects_window_override(self, db, make_space):
        """Windows remain forbidden on Gathering grants — an Event's
        own ``starts_at`` / ``ends_at`` already defines its window."""
        space = make_space()
        option = _make_option(db, space)
        event = _make_event(db, space)
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="gathering",
                event_id=event.id,
                valid_until_override=datetime.utcnow() + timedelta(days=30),
            ))
            db.commit()
        db.rollback()


# ---------------------------------------------------------------------------
# Uniqueness: same Option cannot grant the same target twice
# ---------------------------------------------------------------------------


class TestUniqueness:
    def test_duplicate_pathway_grant_on_same_option_rejected(
        self, db, make_space,
    ):
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space, title="Home Practice")
        db.add(PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="pathway",
            pathway_id=pathway.id,
        ))
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(PaymentOptionGrant(
                payment_option_id=option.id,
                grant_kind="pathway",
                pathway_id=pathway.id,  # same target on same option
            ))
            db.commit()
        db.rollback()

    def test_same_pathway_across_different_options_allowed(
        self, db, make_space,
    ):
        """The EMBODY Practice can be granted by both Awaken and
        Empower — that's the whole point of the multi-experience
        model. Uniqueness is per (option, target), not per target."""
        space = make_space()
        awaken = _make_option(db, space, name="Awaken")
        empower = _make_option(db, space, name="Empower")
        pathway = _make_pathway(db, space, title="Home Practice")

        db.add(PaymentOptionGrant(
            payment_option_id=awaken.id,
            grant_kind="pathway", pathway_id=pathway.id,
        ))
        db.add(PaymentOptionGrant(
            payment_option_id=empower.id,
            grant_kind="pathway", pathway_id=pathway.id,
        ))
        db.commit()

        rows = (
            db.query(PaymentOptionGrant)
            .filter(PaymentOptionGrant.pathway_id == pathway.id)
            .all()
        )
        assert {g.payment_option_id for g in rows} == {awaken.id, empower.id}


# ---------------------------------------------------------------------------
# FK cascade / restrict
# ---------------------------------------------------------------------------


class TestForeignKeyBehaviour:
    def test_option_delete_cascades_to_grants(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space)
        db.add(PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="pathway", pathway_id=pathway.id,
        ))
        db.commit()
        assert db.query(PaymentOptionGrant).count() == 1

        db.delete(option)
        db.commit()
        assert db.query(PaymentOptionGrant).count() == 0

    def test_pathway_delete_restricted_when_granted(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        pathway = _make_pathway(db, space, title="Home Practice")
        db.add(PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="pathway", pathway_id=pathway.id,
        ))
        db.commit()

        db.delete(pathway)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_series_delete_restricted_when_granted(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        series = _make_series(db, space, title="Term 3")
        db.add(PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="event_series", series_id=series.id,
            sessions_per_week=1, total_sessions=10,
        ))
        db.commit()

        db.delete(series)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_event_delete_restricted_when_granted(self, db, make_space):
        space = make_space()
        option = _make_option(db, space)
        event = _make_event(db, space)
        db.add(PaymentOptionGrant(
            payment_option_id=option.id,
            grant_kind="gathering", event_id=event.id,
        ))
        db.commit()

        db.delete(event)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# ---------------------------------------------------------------------------
# Pydantic validator surface
# ---------------------------------------------------------------------------


class TestPydanticValidator:
    def test_pathway_grant_accepts_pathway_id(self):
        g = PaymentOptionGrantCreate(
            grant_kind="pathway", pathway_id="pw_abc",
        )
        assert g.grant_kind == "pathway"

    def test_event_series_grant_accepts_series_only_fields(self):
        g = PaymentOptionGrantCreate(
            grant_kind="event_series", series_id="es_abc",
            sessions_per_week=1, total_sessions=10,
        )
        assert g.total_sessions == 10

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(
                grant_kind="bundle", pathway_id="pw_abc",
            )

    def test_pathway_kind_missing_pathway_id_rejected(self):
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(grant_kind="pathway")

    def test_pathway_kind_with_extra_target_rejected(self):
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(
                grant_kind="pathway",
                pathway_id="pw_abc",
                series_id="es_abc",
            )

    def test_pathway_kind_with_sessions_per_week_rejected(self):
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(
                grant_kind="pathway", pathway_id="pw_abc",
                sessions_per_week=1,
            )

    def test_gathering_kind_with_total_sessions_rejected(self):
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(
                grant_kind="gathering", event_id="e_abc",
                total_sessions=5,
            )

    def test_pathway_kind_accepts_window_override(self):
        """Migration 109 relaxed the model — Pathway grants can
        carry window overrides so bundled Pathway grants can encode
        the effective term end."""
        end = datetime.utcnow() + timedelta(days=30)
        g = PaymentOptionGrantCreate(
            grant_kind="pathway", pathway_id="pw_abc",
            valid_until_override=end,
        )
        assert g.valid_until_override == end

    def test_gathering_kind_with_window_override_rejected(self):
        """Windows on Gathering grants stay forbidden."""
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(
                grant_kind="gathering", event_id="e_abc",
                valid_until_override=datetime.utcnow(),
            )

    def test_non_positive_sessions_rejected(self):
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(
                grant_kind="event_series", series_id="es_abc",
                total_sessions=0,
            )
        with pytest.raises(ValueError):
            PaymentOptionGrantCreate(
                grant_kind="event_series", series_id="es_abc",
                sessions_per_week=-1,
            )
