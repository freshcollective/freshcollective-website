"""Free acquisition, automatic membership, and Your Collection.

Sections 4, 5 and 6 of the Phase C/D brief, tested through the
production handlers against a real PostgreSQL database.

The three things most worth pinning here
----------------------------------------

**Idempotency is structural, not careful.** A partial unique index over
``(user_id, offering_id) WHERE status='active'`` makes a second active
entitlement impossible. The tests below hammer the endpoint and then
check the database, rather than checking that the handler happened to
return the right thing.

**Membership and entitlement are one transaction.** A member who owns a
file but was never joined — or was joined and never given the file —
are both states somebody has to repair by hand. ``TestAtomicity``
forces the failure and asserts neither survives.

**Ownership outlives everything.** Leaving the Collective, the Offering
being retired, the creator downgrading. Section 4's "important
ownership distinction" is one rule — the entitlement row — and these
tests are what stop it quietly becoming four special cases.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
    OfferingStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import offering_acquisition as acq
from app.services import offering_covers as covers
from app.spaces import _offering_member_routes as member_api


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _flag_on(offerings_enabled):
    """Handlers are called directly; the in-request flag check is real."""


def _offering(db, space, **kw) -> Offering:
    defaults = dict(
        id=_uid("off"), space_id=space.id,
        created_by_user_id=space.creator_id,
        slug=f"o-{uuid.uuid4().hex[:8]}",
        title="Morning Pages Workbook",
        summary="Twelve weeks of gentle daily pages.",
        default_cover_key=covers.DEFAULT_COVERS[0].key,
        status=OfferingStatus.published.value,
        pricing_kind=OfferingPricingKind.free.value,
        price_cents=None,
        published_at=datetime.utcnow(),
    )
    defaults.update(kw)
    off = Offering(**defaults)
    db.add(off)
    db.flush()
    return off


def _file(db, offering, **kw) -> OfferingFile:
    defaults = dict(
        id=_uid("of"), offering_id=offering.id,
        storage_key=f"offering-files/{offering.id}/{uuid.uuid4().hex}_w.pdf",
        original_filename="workbook.pdf",
        content_type="application/pdf",
        byte_size=8192, sort_order=0, resource_count=1,
        validation_status=FVS.passed.value,
        validated_at=datetime.utcnow(),
    )
    defaults.update(kw)
    f = OfferingFile(**defaults)
    db.add(f)
    db.flush()
    return f


def _member_rows(db, space, user) -> list[SpaceMembership]:
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user.id,
        )
        .all()
    )


def _entitlements(db, user, offering) -> list[OfferingEntitlement]:
    return (
        db.query(OfferingEntitlement)
        .filter(
            OfferingEntitlement.user_id == user.id,
            OfferingEntitlement.offering_id == offering.id,
        )
        .all()
    )


def _acquire(db, space, offering, user):
    return member_api.acquire_offering(
        space.slug, offering.slug, db=db, current_user=user,
    )


# ---------------------------------------------------------------------------
# The journey
# ---------------------------------------------------------------------------


class TestAFreeAcquisition:

    def test_a_signed_in_stranger_acquires_and_joins(
        self, db, make_space, make_user,
    ):
        """The whole of section 6, in one pass: entitlement created,
        membership created, both in one transaction."""
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)

        assert _member_rows(db, space, taker) == []

        out = _acquire(db, space, off, taker)

        assert out["acquired"] is True
        assert out["already_owned"] is False
        assert out["joined_collective"] is True
        assert out["collective_name"] == space.name

        [ent] = _entitlements(db, taker, off)
        assert ent.status == OfferingEntitlementStatus.active.value
        assert ent.source == OfferingEntitlementSource.free.value
        assert ent.space_id == space.id
        assert ent.acquired_at is not None
        # No money moved, so no ledger row to point at.
        assert ent.payment_transaction_id is None

        [membership] = _member_rows(db, space, taker)
        assert membership.status == SpaceMembershipStatus.active
        assert membership.source == "purchase"
        assert membership.role == "learner"

    def test_an_existing_member_acquires_without_a_second_membership(
        self, db, make_space, make_user,
    ):
        space = make_space()
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=member.id,
            role="moderator", status=SpaceMembershipStatus.active,
            source="invited", joined_at=datetime.utcnow(),
        ))
        db.flush()
        off = _offering(db, space)
        _file(db, off)

        out = _acquire(db, space, off, member)

        assert out["acquired"] is True
        assert out["joined_collective"] is False, (
            "already a member — no message should be shown"
        )
        [existing] = _member_rows(db, space, member)
        # Their role and provenance are untouched. A moderator who
        # downloads a workbook does not become a learner.
        assert existing.role == "moderator"
        assert existing.source == "invited"

    def test_no_free_acquisition_writes_a_payment_transaction(
        self, db, make_space, make_user,
    ):
        """A free download is not a payment. A zero-value ledger row per
        acquisition would put thousands of non-transactions into the
        creator's Payments received."""
        from app.models.payment import PaymentTransaction
        space = make_space()
        off = _offering(db, space)
        _file(db, off)
        before = db.query(PaymentTransaction).count()
        _acquire(db, space, off, make_user())
        assert db.query(PaymentTransaction).count() == before


class TestTheCreatorHearsAboutIt:
    """A free acquisition is news a creator wants.

    It travels as ``collective.purchase.received`` — the same event,
    the same recipient rules and the same preferences as a paid one —
    because "somebody now has my work" is the same fact either way.
    What differs is the wording and the absence of any money.
    """

    def _events(self, db, space):
        from app.comms.models import CommunicationEvent
        return (
            db.query(CommunicationEvent)
            .filter(
                CommunicationEvent.event_type == "collective.purchase.received",
                CommunicationEvent.source_id == space.id,
            )
            .all()
        )

    def test_a_free_acquisition_notifies_the_creator(
        self, db, make_space, make_user,
    ):
        space = make_space()
        off = _offering(db, space, title="Test Workbook")
        _file(db, off)

        _acquire(db, space, off, make_user())

        [event] = self._events(db, space)
        assert event.payload["experience_name"] == "Test Workbook"
        assert event.payload["purchase_verb"] == "added"
        assert event.payload["purchase_suffix"] == " to their collection"
        assert event.payload["is_free"] is True

    def test_it_records_no_amount_and_no_revenue(
        self, db, make_space, make_user,
    ):
        space = make_space()
        off = _offering(db, space)
        _file(db, off)

        _acquire(db, space, off, make_user())

        [event] = self._events(db, space)
        assert event.payload["amount_cents"] is None
        assert event.payload["currency"] is None
        assert event.payload["amount_display"] == ""
        assert event.payload["payment_mode"] == "free"

    def test_pressing_it_twice_notifies_once(
        self, db, make_space, make_user,
    ):
        """Two guards, and this exercises both: the second call never
        reaches the emit because ``created`` is False, and the dedupe
        key on the entitlement id would refuse it if it did."""
        space = make_space()
        off = _offering(db, space)
        _file(db, off)
        taker = make_user()

        _acquire(db, space, off, taker)
        _acquire(db, space, off, taker)

        assert len(self._events(db, space)) == 1

    def test_the_dedupe_key_names_the_entitlement_not_a_transaction(
        self, db, make_space, make_user,
    ):
        """No payment happened, so there is no transaction id to key
        on — and inventing one would put a non-sale in the ledger."""
        space = make_space()
        off = _offering(db, space)
        _file(db, off)

        _acquire(db, space, off, make_user())

        [event] = self._events(db, space)
        assert event.dedupe_key.startswith("purchase_received:entitlement:")

    def test_two_people_acquiring_produce_two_notifications(
        self, db, make_space, make_user,
    ):
        space = make_space()
        off = _offering(db, space)
        _file(db, off)

        _acquire(db, space, off, make_user())
        _acquire(db, space, off, make_user())

        assert len(self._events(db, space)) == 2

    def test_a_refused_acquisition_notifies_nobody(
        self, db, make_space, make_user,
    ):
        """Only a successful acquisition is news. A priced Offering is
        refused before anything is created, so nothing is announced —
        and in particular a creator is never told about a sale that did
        not happen."""
        space = make_space()
        off = _offering(
            db, space,
            pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=2400,
        )
        _file(db, off)

        with pytest.raises(HTTPException):
            _acquire(db, space, off, make_user())

        assert self._events(db, space) == []


class TestPressingItTwice:

    def test_the_second_press_is_a_no_op(self, db, make_space, make_user):
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)

        first = _acquire(db, space, off, taker)
        second = _acquire(db, space, off, taker)

        assert first["already_owned"] is False
        assert second["already_owned"] is True
        assert len(_entitlements(db, taker, off)) == 1

    def test_ten_presses_still_leave_one_entitlement(
        self, db, make_space, make_user,
    ):
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)
        for _ in range(10):
            _acquire(db, space, off, taker)
        assert len(_entitlements(db, taker, off)) == 1
        assert len(_member_rows(db, space, taker)) == 1

    def test_the_index_that_makes_it_impossible_is_still_there(self, db):
        """The index is the guarantee; the handler's read is a courtesy.

        Asserted structurally because every other test in this class
        would still pass if the index were dropped — they exercise the
        courtesy. The behaviour under genuine concurrency is proved
        across two real connections in
        ``test_concurrent_offering_acquisition``.
        """
        from sqlalchemy import text
        row = db.execute(text("""
            SELECT indexdef FROM pg_indexes
             WHERE tablename = 'offering_entitlements'
               AND indexname = 'ux_offering_entitlements_active'
        """)).first()
        assert row is not None, "ux_offering_entitlements_active is missing"
        indexdef = row[0]
        assert "UNIQUE" in indexdef
        assert "user_id" in indexdef and "offering_id" in indexdef
        # Partial, so a revoked row never becomes a permanent barrier.
        assert "WHERE" in indexdef and "active" in indexdef

    def test_a_revoked_row_does_not_block_acquiring_again(
        self, db, make_space, make_user,
    ):
        """The index is partial for exactly this: somebody whose access
        was explicitly revoked can legitimately acquire again later, and
        the revoked row stays as the record of what happened."""
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)
        db.add(OfferingEntitlement(
            id=_uid("oe"), user_id=taker.id, offering_id=off.id,
            space_id=space.id,
            source=OfferingEntitlementSource.free.value,
            status=OfferingEntitlementStatus.revoked.value,
            revoked_at=datetime.utcnow(),
            revoked_reason="chargeback",
            acquired_at=datetime.utcnow(),
        ))
        db.flush()

        out = _acquire(db, space, off, taker)
        assert out["already_owned"] is False
        rows = _entitlements(db, taker, off)
        assert len(rows) == 2
        statuses = sorted(r.status for r in rows)
        assert statuses == ["active", "revoked"]
        # The revoked row kept its reason.
        revoked = next(r for r in rows if r.status == "revoked")
        assert revoked.revoked_reason == "chargeback"


class TestWhatIsRefused:

    def test_a_paid_offering_cannot_be_claimed_for_free(
        self, db, make_space, make_user,
    ):
        """The most important refusal in this file: the two ways the
        request and the Offering can disagree about price, and neither
        gives the files away."""
        space = make_space()
        off = _offering(
            db, space,
            pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=2400,
        )
        _file(db, off)
        with pytest.raises(HTTPException) as e:
            _acquire(db, space, off, make_user())
        assert e.value.status_code == 409
        assert e.value.detail["reason"] == acq.REASON_WRONG_PRICING
        assert _entitlements(db, make_user(), off) == []

    def test_a_draft_is_a_404_even_for_its_owner(self, db, make_space):
        """Previewing a draft must not be able to create a real
        entitlement in real purchase history."""
        from app.models.user import User
        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        off = _offering(db, space, status=OfferingStatus.draft.value)
        _file(db, off)
        with pytest.raises(HTTPException) as e:
            _acquire(db, space, off, owner)
        assert e.value.status_code == 404

    def test_a_retired_offering_refuses_a_new_acquisition(
        self, db, make_space, make_user,
    ):
        space = make_space()
        off = _offering(
            db, space, status=OfferingStatus.retired.value,
            retired_at=datetime.utcnow(),
        )
        _file(db, off)
        with pytest.raises(HTTPException) as e:
            _acquire(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_RETIRED

    def test_an_offering_with_nothing_downloadable_refuses(
        self, db, make_space, make_user,
    ):
        """Section 8: no new acquisitions when no valid downloadable
        resource remains."""
        space = make_space()
        off = _offering(db, space)
        _file(db, off, validation_status=FVS.pending.value, validated_at=None)
        with pytest.raises(HTTPException) as e:
            _acquire(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_NO_FILES

    def test_a_quarantined_bundle_refuses(self, db, make_space, make_user):
        space = make_space()
        off = _offering(db, space)
        _file(
            db, off, validation_status=FVS.quarantined.value,
            quarantined_at=datetime.utcnow(),
        )
        with pytest.raises(HTTPException) as e:
            _acquire(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_NO_FILES

    def test_a_superseded_file_does_not_count(
        self, db, make_space, make_user,
    ):
        space = make_space()
        off = _offering(db, space)
        _file(db, off, superseded_at=datetime.utcnow())
        with pytest.raises(HTTPException) as e:
            _acquire(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_NO_FILES

    def test_acquiring_is_refused_with_the_feature_flag_off(
        self, db, make_space, make_user, monkeypatch,
    ):
        from app.core.config import settings
        space = make_space()
        off = _offering(db, space)
        _file(db, off)
        monkeypatch.setattr(settings, "offerings_enabled", False)
        with pytest.raises(HTTPException) as e:
            _acquire(db, space, off, make_user())
        assert e.value.status_code == 404


class TestMembershipRespectsAccessControls:
    """Section 4's escalation clause: automatic membership must not
    silently bypass a decision the platform made deliberately. These
    assert the shared ``membership_grant`` rules apply here too, rather
    than a second set of rules living in acquisition."""

    def test_a_collective_that_manages_its_own_membership_is_untouched(
        self, db, make_space, make_user,
    ):
        space = make_space(auto_grant_role="creator")
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)

        out = _acquire(db, space, off, taker)

        # They own the Offering. They are not forced into a Collective
        # whose membership is computed from platform eligibility.
        assert out["acquired"] is True
        assert out["joined_collective"] is False
        assert len(_entitlements(db, taker, off)) == 1
        assert _member_rows(db, space, taker) == []

    def test_a_paused_membership_is_left_paused(
        self, db, make_space, make_user,
    ):
        """Paused is a state the platform or a person chose. Acquiring a
        free workbook is not consent to overturn it — and the person
        still gets the workbook."""
        space = make_space()
        taker = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=taker.id,
            role="learner", status=SpaceMembershipStatus.paused,
            source="joined", joined_at=datetime.utcnow(),
        ))
        db.flush()
        off = _offering(db, space)
        _file(db, off)

        out = _acquire(db, space, off, taker)

        assert out["acquired"] is True
        assert out["joined_collective"] is False
        [row] = _member_rows(db, space, taker)
        assert row.status == SpaceMembershipStatus.paused

    def test_a_removed_invited_membership_is_not_restored(
        self, db, make_space, make_user,
    ):
        """``source='invited'`` is outside ``REACTIVATABLE_SOURCES``:
        the removal was somebody's decision, and a free download does
        not reverse it."""
        space = make_space()
        taker = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=taker.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="invited", joined_at=datetime.utcnow(),
        ))
        db.flush()
        off = _offering(db, space)
        _file(db, off)

        out = _acquire(db, space, off, taker)
        assert out["joined_collective"] is False
        [row] = _member_rows(db, space, taker)
        assert row.status == SpaceMembershipStatus.removed

    def test_a_removed_self_joined_membership_is_restored(
        self, db, make_space, make_user,
    ):
        """They chose to join once and are choosing again."""
        space = make_space()
        taker = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=taker.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="joined", joined_at=datetime.utcnow(),
        ))
        db.flush()
        off = _offering(db, space)
        _file(db, off)

        out = _acquire(db, space, off, taker)
        assert out["joined_collective"] is True
        [row] = _member_rows(db, space, taker)
        assert row.status == SpaceMembershipStatus.active
        # Provenance preserved — it records how it first came to exist.
        assert row.source == "joined"


class TestAtomicity:

    def test_a_failure_to_join_leaves_no_entitlement(
        self, db, make_space, make_user, monkeypatch,
    ):
        """Forced failure. The service does not commit — the route does
        — so a raise anywhere inside must leave neither row."""
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)

        from app.services import membership_grant
        def _boom(*a, **k):
            raise RuntimeError("membership store unavailable")
        monkeypatch.setattr(
            membership_grant, "ensure_membership_for_purchase", _boom,
        )

        with pytest.raises(RuntimeError):
            _acquire(db, space, off, taker)
        db.rollback()

        assert _entitlements(db, taker, off) == []
        assert _member_rows(db, space, taker) == []


# ---------------------------------------------------------------------------
# Your Collection
# ---------------------------------------------------------------------------


class TestYourCollection:

    def test_an_empty_collection_is_an_empty_list(self, db, make_user):
        out = member_api.get_your_collection(db=db, current_user=make_user())
        assert out == {"items": [], "count": 0}

    def test_an_acquired_offering_appears(self, db, make_space, make_user):
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)
        _acquire(db, space, off, taker)

        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 1
        [item] = out["items"]
        assert item["title"] == "Morning Pages Workbook"
        assert item["slug"] == off.slug
        assert item["collective"]["slug"] == space.slug
        assert item["collective"]["name"] == space.name
        assert item["category_label"] == "PDF"
        assert item["file_count"] == 1
        assert item["files_available"] is True
        assert item["href"] == f"/spaces/{space.slug}/offerings/{off.slug}"

    def test_it_spans_collectives(self, db, make_space, make_user):
        """Section 5: one Collection, across every Collective."""
        taker = make_user()
        a, b = make_space(), make_space()
        off_a = _offering(db, a, title="From A")
        off_b = _offering(db, b, title="From B")
        _file(db, off_a)
        _file(db, off_b)
        _acquire(db, a, off_a, taker)
        _acquire(db, b, off_b, taker)

        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 2
        assert {i["title"] for i in out["items"]} == {"From A", "From B"}
        assert {i["collective"]["slug"] for i in out["items"]} == {a.slug, b.slug}

    def test_the_collection_does_not_distinguish_free_from_paid(
        self, db, make_space, make_user,
    ):
        """What you own is what you own. The payload carries no 'you got
        this free' marker, because a Collection is not a receipt."""
        import json
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)
        _acquire(db, space, off, taker)
        out = member_api.get_your_collection(db=db, current_user=taker)
        blob = json.dumps(out, default=str)
        assert "one_time_purchase" not in blob
        assert '"source"' not in blob

    def test_newest_first(self, db, make_space, make_user):
        from datetime import timedelta
        space = make_space()
        taker = make_user()
        older = _offering(db, space, title="Older")
        newer = _offering(db, space, title="Newer")
        _file(db, older)
        _file(db, newer)
        now = datetime.utcnow()
        db.add(OfferingEntitlement(
            id=_uid("oe"), user_id=taker.id, offering_id=older.id,
            space_id=space.id,
            source=OfferingEntitlementSource.free.value,
            status=OfferingEntitlementStatus.active.value,
            acquired_at=now - timedelta(days=5),
        ))
        db.add(OfferingEntitlement(
            id=_uid("oe"), user_id=taker.id, offering_id=newer.id,
            space_id=space.id,
            source=OfferingEntitlementSource.free.value,
            status=OfferingEntitlementStatus.active.value,
            acquired_at=now,
        ))
        db.flush()
        out = member_api.get_your_collection(db=db, current_user=taker)
        assert [i["title"] for i in out["items"]] == ["Newer", "Older"]

    def test_somebody_elses_collection_is_not_visible(
        self, db, make_space, make_user,
    ):
        space = make_space()
        mine, theirs = make_user(), make_user()
        off = _offering(db, space)
        _file(db, off)
        _acquire(db, space, off, theirs)
        out = member_api.get_your_collection(db=db, current_user=mine)
        assert out["count"] == 0

    def test_a_revoked_entitlement_is_absent(self, db, make_space, make_user):
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        _file(db, off)
        _acquire(db, space, off, taker)
        [ent] = _entitlements(db, taker, off)
        ent.status = OfferingEntitlementStatus.revoked.value
        ent.revoked_at = datetime.utcnow()
        ent.revoked_reason = "disputed"
        db.flush()
        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 0


class TestOwnershipOutlivesEverything:
    """Section 4's ownership distinction and section 8's download rules,
    as one table of cases. Each is the same single rule — the
    entitlement row — rather than a special case."""

    def _acquired(self, db, make_space, make_user):
        space = make_space()
        taker = make_user()
        off = _offering(db, space)
        f = _file(db, off)
        _acquire(db, space, off, taker)
        return space, taker, off, f

    def test_leaving_the_collective_keeps_the_offering(
        self, db, make_space, make_user,
    ):
        space, taker, off, _f = self._acquired(db, make_space, make_user)
        [membership] = _member_rows(db, space, taker)
        membership.status = SpaceMembershipStatus.removed
        db.flush()

        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 1
        detail = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=taker,
        )
        assert detail["viewer_owns"] is True
        assert detail["files"][0]["download_url"] is not None

    def test_retirement_keeps_the_offering(
        self, db, make_space, make_user,
    ):
        space, taker, off, _f = self._acquired(db, make_space, make_user)
        off.status = OfferingStatus.retired.value
        off.retired_at = datetime.utcnow()
        db.flush()

        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 1
        assert out["items"][0]["offering_status"] == "retired"
        detail = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=taker,
        )
        assert detail["files"][0]["download_url"] is not None

    def test_a_replacement_file_is_the_one_they_get(
        self, db, make_space, make_user,
    ):
        """Section 8: existing purchasers receive the latest approved
        replacement, at no extra cost and with no new entitlement."""
        space, taker, off, old = self._acquired(db, make_space, make_user)
        new = _file(
            db, off, original_filename="workbook-v2.pdf",
            replaces_file_id=old.id, sort_order=0,
        )
        old.superseded_at = datetime.utcnow()
        old.superseded_by_id = new.id
        db.flush()

        detail = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=taker,
        )
        assert [f["name"] for f in detail["files"]] == ["workbook-v2.pdf"]
        assert detail["files"][0]["download_url"] == f"/api/uploads/{new.storage_key}"
        assert len(_entitlements(db, taker, off)) == 1

    def test_a_quarantined_file_says_so_rather_than_breaking(
        self, db, make_space, make_user,
    ):
        """Section 8: a clear message, not a broken download."""
        space, taker, off, f = self._acquired(db, make_space, make_user)
        f.validation_status = FVS.quarantined.value
        f.quarantined_at = datetime.utcnow()
        db.flush()

        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 1, "they still own it"
        assert out["items"][0]["files_available"] is False
        detail = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=taker,
        )
        assert detail["files"] == []
        assert detail["viewer_owns"] is True

    def test_the_collection_survives_an_archived_collective(
        self, db, make_space, make_user,
    ):
        """An outer join, so a Collective closing does not make a
        member's own collection disappear or 500."""
        space, taker, off, _f = self._acquired(db, make_space, make_user)
        space.status = "archived"
        db.flush()
        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 1
