"""Offerings Phase A — models, constraints, storage and authorisation.

What these tests are really defending is a set of product promises that
are easy to state and easy to break:

  * You keep what you paid for when you leave the Collective, when the
    Collective closes, and when the product is retired.
  * You get the current version of what you bought, not the version you
    bought, and not any superseded version.
  * Nobody reaches a paid file by being a member, by being a creator
    somewhere else, or by guessing a key.

Every one of those is a negative assertion about access, which is the
kind that passes vacuously if the fixture is wrong. So each
authorisation test here is paired with a positive control in the same
class: if the entitled purchaser could not download either, the suite
would be proving nothing.

Nothing in this file touches Stripe or production data. One
``PaymentTransaction`` is created locally to prove the entitlement's
optional ledger link, and no payment is processed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFulfilmentKind,
    OfferingStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import offering_files as of
from app.uploads.authorization import authorize_upload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _offering(db, space, **overrides) -> Offering:
    defaults = dict(
        id=_uid("off"),
        space_id=space.id,
        created_by_user_id=space.creator_id,
        slug=f"guide-{uuid.uuid4().hex[:8]}",
        title="A Gentle Guide",
        summary="Short lines for a card.",
        status=OfferingStatus.published.value,
        fulfilment_kind=OfferingFulfilmentKind.digital_download.value,
    )
    defaults.update(overrides)
    row = Offering(**defaults)
    db.add(row)
    db.flush()
    return row


def _file(db, offering, *, name="workbook.pdf", **overrides) -> OfferingFile:
    """A file that has passed validation.

    Phase B added a validation gate, so a row left at its ``pending``
    default is correctly undownloadable. The tests in this file are
    about *ownership* — who may read what they paid for — so their
    fixtures are files that have cleared their checks. Validation
    itself is exercised in ``test_offering_validation.py``, including
    that a pending file is refused even an entitled purchaser.
    """
    from app.services.offering_validation import (
        REQUIRED_CHECKS, VALIDATION_POLICY_VERSION,
    )
    defaults = dict(
        id=_uid("ofl"),
        offering_id=offering.id,
        storage_key=of.build_storage_key(offering_id=offering.id, filename=name),
        original_filename=name,
        content_type="application/pdf",
        byte_size=2048,
        sort_order=0,
        validation_status="passed",
        checks_performed=[
            {"id": c.id, "version": c.version, "outcome": "pass"}
            for c in REQUIRED_CHECKS
        ],
        validation_policy_version=VALIDATION_POLICY_VERSION,
    )
    defaults.update(overrides)
    row = OfferingFile(**defaults)
    db.add(row)
    db.flush()
    return row


def _entitle(db, user, offering, **overrides) -> OfferingEntitlement:
    defaults = dict(
        id=_uid("oen"),
        user_id=user.id,
        offering_id=offering.id,
        space_id=offering.space_id,
        source=OfferingEntitlementSource.one_time_purchase.value,
        status=OfferingEntitlementStatus.active.value,
    )
    defaults.update(overrides)
    row = OfferingEntitlement(**defaults)
    db.add(row)
    db.flush()
    return row


def _member(db, user, space, status=SpaceMembershipStatus.active):
    row = SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role="learner", status=status, source="joined",
        joined_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def offerings_on(monkeypatch):
    """Turn the feature on for tests that are about something else.

    The flag's own default is asserted separately — through the settings
    object rather than through this fixture, so the fixture cannot hide
    a change to it.
    """
    from app.core.config import settings
    monkeypatch.setattr(settings, "offerings_enabled", True)
    yield


def _authorise(key, user, db):
    """Run the resolver, returning the HTTP status it refused with, or
    None when it allowed."""
    try:
        authorize_upload(key, user, db)
        return None
    except HTTPException as exc:
        return exc.status_code


# ---------------------------------------------------------------------------
# 1 · Models and constraints
# ---------------------------------------------------------------------------


class TestOfferingModel:
    def test_an_offering_belongs_to_one_collective(self, db, make_space):
        space = make_space()
        off = _offering(db, space)
        assert off.space_id == space.id
        assert off.status == "published"
        assert off.fulfilment_kind == "digital_download"

    def test_slug_is_unique_within_a_collective(self, db, make_space):
        space = make_space()
        _offering(db, space, slug="morning-pages")
        with pytest.raises(IntegrityError):
            _offering(db, space, slug="morning-pages")
            db.flush()
        db.rollback()

    def test_the_same_slug_is_free_in_another_collective(
        self, db, make_space,
    ):
        """Two Collectives may each sell "morning-pages" and neither
        should have to care what the other named things."""
        a, b = make_space(), make_space()
        _offering(db, a, slug="morning-pages")
        _offering(db, b, slug="morning-pages")
        db.flush()  # no IntegrityError

    def test_status_is_constrained(self, db, make_space):
        space = make_space()
        with pytest.raises(IntegrityError):
            _offering(db, space, status="on_sale")
            db.flush()
        db.rollback()

    def test_fulfilment_kind_is_constrained_but_extensible(self, db, make_space):
        """Phase 1 accepts one value. The column is a string so a
        physical kind can be added by widening the CHECK, not by
        migrating an enum."""
        space = make_space()
        with pytest.raises(IntegrityError):
            _offering(db, space, fulfilment_kind="physical")
            db.flush()
        db.rollback()

    def test_default_status_is_draft(self, db, make_space):
        space = make_space()
        row = Offering(
            id=_uid("off"), space_id=make_space().id, slug="s", title="T",
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        assert row.status == "draft"
        assert row.published_at is None
        assert row.retired_at is None


class TestOfferingFileModel:
    def test_files_belong_to_an_offering_in_order(self, db, make_space):
        off = _offering(db, make_space())
        _file(db, off, name="a.pdf", sort_order=1)
        _file(db, off, name="b.pdf", sort_order=0)
        db.refresh(off)
        assert [f.original_filename for f in off.files] == ["b.pdf", "a.pdf"]

    def test_a_storage_key_cannot_be_reused(self, db, make_space):
        """Two rows naming one object would make "supersede this file"
        ambiguous and could keep a superseded key reachable."""
        off = _offering(db, make_space())
        first = _file(db, off)
        with pytest.raises(IntegrityError):
            _file(db, off, storage_key=first.storage_key)
            db.flush()
        db.rollback()

    def test_zero_byte_files_are_refused(self, db, make_space):
        off = _offering(db, make_space())
        with pytest.raises(IntegrityError):
            _file(db, off, byte_size=0)
            db.flush()
        db.rollback()

    def test_a_replacement_pointer_requires_a_supersede_timestamp(
        self, db, make_space,
    ):
        """A file claiming to be both current and replaced is not a
        state the schema allows."""
        off = _offering(db, make_space())
        old = _file(db, off, name="v1.pdf")
        new = _file(db, off, name="v2.pdf")
        old.superseded_by_id = new.id  # but no superseded_at
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_a_file_cannot_supersede_itself(self, db, make_space):
        off = _offering(db, make_space())
        f = _file(db, off)
        f.superseded_at = datetime.utcnow()
        f.superseded_by_id = f.id
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_removal_and_replacement_are_distinguishable(self, db, make_space):
        """One mechanism, two lifecycle events — and a reader can tell
        which happened."""
        off = _offering(db, make_space())
        replaced = _file(db, off, name="v1.pdf")
        replacement = _file(db, off, name="v2.pdf")
        replaced.superseded_at = datetime.utcnow()
        replaced.superseded_by_id = replacement.id

        removed = _file(db, off, name="extra.pdf")
        removed.superseded_at = datetime.utcnow()
        removed.superseded_by_id = None
        db.flush()

        assert replaced.superseded_by_id == replacement.id, "replaced"
        assert removed.superseded_by_id is None, "removed, nothing stood in"
        assert not replaced.is_current and not removed.is_current
        assert replacement.is_current


class TestEntitlementConstraints:
    def test_an_entitlement_records_who_owns_what_and_how(
        self, db, make_space, make_user,
    ):
        off = _offering(db, make_space())
        buyer = make_user()
        ent = _entitle(db, buyer, off)
        assert ent.is_active
        assert ent.source == "one_time_purchase"
        assert ent.space_id == off.space_id
        assert ent.acquired_at is not None
        assert ent.payment_transaction_id is None

    def test_duplicate_active_ownership_is_refused(
        self, db, make_space, make_user,
    ):
        """The replayed-webhook guard, in the schema rather than in a
        handler that has to remember."""
        off = _offering(db, make_space())
        buyer = make_user()
        _entitle(db, buyer, off)
        with pytest.raises(IntegrityError):
            _entitle(db, buyer, off)
            db.flush()
        db.rollback()

    def test_re_acquiring_after_revocation_is_allowed(
        self, db, make_space, make_user,
    ):
        """Why the index is partial. A full UNIQUE would make a revoked
        row a permanent barrier and force a reactivate-in-place path,
        losing the record of what happened."""
        off = _offering(db, make_space())
        buyer = make_user()
        first = _entitle(db, buyer, off)
        first.status = OfferingEntitlementStatus.revoked.value
        first.revoked_at = datetime.utcnow()
        first.revoked_reason = "Chargeback"
        db.flush()

        second = _entitle(db, buyer, off)
        db.flush()
        assert second.is_active
        assert not first.is_active

    def test_two_members_may_own_the_same_offering(
        self, db, make_space, make_user,
    ):
        off = _offering(db, make_space())
        _entitle(db, make_user(), off)
        _entitle(db, make_user(), off)
        db.flush()

    def test_a_revoked_row_must_say_when(self, db, make_space, make_user):
        off = _offering(db, make_space())
        with pytest.raises(IntegrityError):
            _entitle(
                db, make_user(), off,
                status=OfferingEntitlementStatus.revoked.value,
            )  # revoked_at left NULL
            db.flush()
        db.rollback()

    def test_an_active_row_must_not_claim_revocation(
        self, db, make_space, make_user,
    ):
        off = _offering(db, make_space())
        with pytest.raises(IntegrityError):
            _entitle(db, make_user(), off, revoked_at=datetime.utcnow())
            db.flush()
        db.rollback()

    def test_source_is_constrained_to_the_three_approved_routes(
        self, db, make_space, make_user,
    ):
        off = _offering(db, make_space())
        for src in ("one_time_purchase", "free", "admin_grant"):
            _entitle(db, make_user(), off, source=src)
        db.flush()
        with pytest.raises(IntegrityError):
            _entitle(db, make_user(), off, source="subscription")
            db.flush()
        db.rollback()

    def test_it_can_link_to_a_payment_transaction(
        self, db, make_space, make_event, make_pending_txn,
    ):
        """The optional ledger link, which Phase D will populate. The
        ledger stays the financial source of truth; this is only a
        pointer to it.

        The transaction here is a locally-built pending row — the
        fixture needs an Event because every ledger row the suite makes
        today is a ticket purchase. Nothing is charged, and no Stripe
        call happens.
        """
        space = make_space()
        off = _offering(db, space)
        event = make_event(space=space)
        txn, payer = make_pending_txn(space=space, event=event)
        ent = _entitle(db, payer, off, payment_transaction_id=txn.id)
        db.flush()
        assert ent.payment_transaction_id == txn.id

    def test_losing_the_ledger_link_does_not_destroy_the_entitlement(
        self, db, make_space, make_event, make_pending_txn,
    ):
        """``SET NULL``, matching ``access_passes``. The ledger is the
        financial record; ownership must not depend on the pointer to
        it surviving."""
        from app.models.payment import PaymentTransaction
        space = make_space()
        off = _offering(db, space)
        event = make_event(space=space)
        txn, payer = make_pending_txn(space=space, event=event)
        ent = _entitle(db, payer, off, payment_transaction_id=txn.id)
        db.flush()
        db.delete(db.query(PaymentTransaction).filter(
            PaymentTransaction.id == txn.id,
        ).one())
        db.flush()
        db.refresh(ent)
        assert ent.payment_transaction_id is None
        assert ent.is_active, "ownership survives"


# ---------------------------------------------------------------------------
# 2 · Ownership survives the Collective
# ---------------------------------------------------------------------------


class TestOwnershipPreservation:
    def test_an_offering_anyone_owns_cannot_be_deleted(
        self, db, make_space, make_user,
    ):
        """The last line of the promise. Not a code path that remembers
        — the database itself refuses."""
        off = _offering(db, make_space())
        _entitle(db, make_user(), off)
        db.flush()
        db.delete(off)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_a_collective_with_offerings_cannot_be_deleted(
        self, db, make_space,
    ):
        """``RESTRICT``, deliberately unlike every cascading sibling
        table. An Offering can be somebody's paid property."""
        from app.models.platform import Space
        space = make_space()
        _offering(db, space)
        db.flush()
        db.delete(db.query(Space).filter(Space.id == space.id).one())
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_an_offering_nobody_owns_can_be_deleted_and_takes_its_files(
        self, db, make_space,
    ):
        """The converse, so the RESTRICT above is shown to be about
        ownership rather than a blanket refusal. File rows cascade
        because they are part of the Offering, not property."""
        off = _offering(db, make_space())
        _file(db, off)
        db.flush()
        off_id = off.id
        db.delete(off)
        db.flush()
        assert db.query(OfferingFile).filter(
            OfferingFile.offering_id == off_id,
        ).count() == 0

    def test_the_delete_space_endpoint_counts_offerings_as_a_blocker(self):
        """Source contract. The database would refuse the delete either
        way; this is what turns a foreign-key 500 into the 409 every
        other blocker produces."""
        import inspect
        from app.creator import routes as creator_routes
        src = inspect.getsource(creator_routes.delete_space)
        assert "Offering" in src, "delete_space must count Offerings"
        assert "offering(s)" in src, "and name them in the blocker list"


# ---------------------------------------------------------------------------
# 3 · Download authorisation
# ---------------------------------------------------------------------------


class TestDownloadAuthorisation:
    def test_the_entitled_purchaser_is_allowed(
        self, db, make_space, make_user, offerings_on,
    ):
        """The positive control. Every refusal below is only meaningful
        because this passes."""
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        assert _authorise(f.storage_key, buyer, db) is None

    def test_an_unentitled_member_is_refused(
        self, db, make_space, make_user, offerings_on,
    ):
        """Membership of the Collective is not ownership of its
        products — the rule that separates this namespace from every
        other one in the dispatch table."""
        space = make_space()
        off = _offering(db, space)
        f = _file(db, off)
        member = make_user()
        _member(db, member, space)
        db.flush()
        assert _authorise(f.storage_key, member, db) == 403

    def test_a_stranger_is_refused(
        self, db, make_space, make_user, offerings_on,
    ):
        off = _offering(db, make_space())
        f = _file(db, off)
        db.flush()
        assert _authorise(f.storage_key, make_user(), db) == 403

    def test_the_collectives_owner_is_allowed(
        self, db, make_space, make_user, offerings_on,
    ):
        from app.models.user import User
        space = make_space()
        off = _offering(db, space)
        f = _file(db, off)
        db.flush()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        assert _authorise(f.storage_key, owner, db) is None

    def test_a_platform_admin_is_allowed(
        self, db, make_space, make_user, offerings_on,
    ):
        off = _offering(db, make_space())
        f = _file(db, off)
        db.flush()
        assert _authorise(f.storage_key, make_user(role="admin"), db) is None

    def test_a_creator_of_another_collective_is_refused(
        self, db, make_space, make_user, offerings_on,
    ):
        """Being a creator somewhere is not managing this. The same
        distinction ``_user_can_view_space_media`` makes, applied here."""
        off = _offering(db, make_space())
        f = _file(db, off)
        other_space = make_space()
        db.flush()
        from app.models.user import User
        intruder = db.query(User).filter(
            User.id == other_space.creator_id,
        ).one()
        assert _authorise(f.storage_key, intruder, db) == 403

    def test_cross_collective_file_access_is_refused(
        self, db, make_space, make_user, offerings_on,
    ):
        """Entitled to A, pasting B's key. Checked explicitly rather
        than assumed from the fact that the caller owns *something*."""
        off_a = _offering(db, make_space())
        off_b = _offering(db, make_space())
        file_b = _file(db, off_b)
        buyer = make_user()
        _entitle(db, buyer, off_a)
        db.flush()
        assert _authorise(file_b.storage_key, buyer, db) == 403

    def test_a_key_whose_offering_does_not_exist_is_404_not_403(
        self, db, make_user, offerings_on,
    ):
        """404 rather than 403, matching every other resolver, so the
        route cannot be used to enumerate which Offering ids are real."""
        key = f"{of.OFFERING_FILES_PREFIX}/{_uid('off')}/{uuid.uuid4().hex}_x.pdf"
        assert _authorise(key, make_user(), db) == 404

    def test_a_malformed_key_discloses_nothing(
        self, db, make_user, offerings_on,
    ):
        for key in (
            of.OFFERING_FILES_PREFIX,
            f"{of.OFFERING_FILES_PREFIX}/",
            f"{of.OFFERING_FILES_PREFIX}/only-two-segments",
        ):
            assert _authorise(key, make_user(), db) in (403, 404), key

    def test_an_unknown_file_in_a_real_offering_is_404(
        self, db, make_space, make_user, offerings_on,
    ):
        """Entitled, right Offering, no such file row. The object may
        well not exist in R2 either, and saying which is not this
        route's business."""
        off = _offering(db, make_space())
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        ghost = of.build_storage_key(offering_id=off.id, filename="ghost.pdf")
        assert _authorise(ghost, buyer, db) == 404

    def test_an_unknown_namespace_is_still_default_denied(
        self, db, make_user, offerings_on,
    ):
        """The pre-existing guarantee, re-asserted here because this
        phase added entries to the dispatch table."""
        assert _authorise("offerings/x/y.pdf", make_user(), db) == 403
        assert _authorise("offering-exports/x/y.pdf", make_user(), db) == 403


class TestOwnershipOutlastsMembershipAndStatus:
    def test_a_purchaser_who_leaves_keeps_their_files(
        self, db, make_space, make_user, offerings_on,
    ):
        space = make_space()
        off = _offering(db, space)
        f = _file(db, off)
        buyer = make_user()
        membership = _member(db, buyer, space)
        _entitle(db, buyer, off)
        db.flush()
        assert _authorise(f.storage_key, buyer, db) is None, "while a member"

        membership.status = SpaceMembershipStatus.removed
        db.flush()
        assert _authorise(f.storage_key, buyer, db) is None, "after leaving"

    def test_a_purchaser_who_was_never_a_member_can_download(
        self, db, make_space, make_user, offerings_on,
    ):
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        assert db.query(SpaceMembership).filter(
            SpaceMembership.user_id == buyer.id,
        ).count() == 0
        assert _authorise(f.storage_key, buyer, db) is None

    def test_a_retired_offering_still_serves_its_purchasers(
        self, db, make_space, make_user, offerings_on,
    ):
        """Stopping future sales is not removing what someone bought —
        the whole point of ``retired``."""
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        off.status = OfferingStatus.retired.value
        off.retired_at = datetime.utcnow()
        db.flush()
        assert _authorise(f.storage_key, buyer, db) is None

    def test_a_draft_offering_still_serves_an_existing_entitlement(
        self, db, make_space, make_user, offerings_on,
    ):
        """Unpublishing must not strand an owner either."""
        off = _offering(db, make_space(), status=OfferingStatus.draft.value)
        f = _file(db, off)
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        assert _authorise(f.storage_key, buyer, db) is None

    def test_a_revoked_entitlement_loses_access(
        self, db, make_space, make_user, offerings_on,
    ):
        """Revocation is the one thing that does remove access — and it
        is an explicit act, never a side effect of a refund."""
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user()
        ent = _entitle(db, buyer, off)
        db.flush()
        assert _authorise(f.storage_key, buyer, db) is None

        ent.status = OfferingEntitlementStatus.revoked.value
        ent.revoked_at = datetime.utcnow()
        ent.revoked_reason = "Confirmed fraud"
        db.flush()
        assert _authorise(f.storage_key, buyer, db) == 403


class TestVersioning:
    def test_a_purchaser_gets_the_current_file(
        self, db, make_space, make_user, offerings_on,
    ):
        off = _offering(db, make_space())
        current = _file(db, off, name="v2.pdf")
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        assert _authorise(current.storage_key, buyer, db) is None

    def test_a_purchaser_cannot_reach_a_superseded_file(
        self, db, make_space, make_user, offerings_on,
    ):
        """Bought last year, replaced since. They get today's bundle —
        not the version they originally acquired, and not both."""
        off = _offering(db, make_space())
        old = _file(db, off, name="v1.pdf")
        new = _file(db, off, name="v2.pdf")
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        assert _authorise(old.storage_key, buyer, db) is None, "before replacement"

        old.superseded_at = datetime.utcnow()
        old.superseded_by_id = new.id
        db.flush()
        assert _authorise(old.storage_key, buyer, db) == 403, "after replacement"
        assert _authorise(new.storage_key, buyer, db) is None, "current is served"

    def test_a_removed_file_is_also_unreachable(
        self, db, make_space, make_user, offerings_on,
    ):
        """Removal, not replacement: nothing stood in for it."""
        off = _offering(db, make_space())
        keep = _file(db, off, name="keep.pdf")
        drop = _file(db, off, name="drop.pdf")
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        drop.superseded_at = datetime.utcnow()
        db.flush()
        assert _authorise(drop.storage_key, buyer, db) == 403
        assert _authorise(keep.storage_key, buyer, db) is None

    def test_creators_and_admins_may_read_history(
        self, db, make_space, make_user, offerings_on,
    ):
        """Controlled access to superseded versions, for recovery and
        audit. Nothing is physically deleted in this phase."""
        from app.models.user import User
        space = make_space()
        off = _offering(db, space)
        old = _file(db, off, name="v1.pdf")
        db.flush()
        old.superseded_at = datetime.utcnow()
        db.flush()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        assert _authorise(old.storage_key, owner, db) is None
        assert _authorise(old.storage_key, make_user(role="admin"), db) is None


class TestFeatureFlag:
    def test_it_is_disabled_by_default(self):
        """Asserted against the settings object, not through the test
        fixture, so a fixture cannot hide a changed default."""
        from app.core.config import Settings
        assert Settings().offerings_enabled is False

    def test_an_owner_can_still_download_while_the_feature_is_disabled(
        self, db, make_space, make_user,
    ):
        """**Reversed in Phase B, deliberately.**

        Phase A had the flag refuse even a fully entitled purchaser,
        and flagged that for revisiting before the first real purchase.
        Revisited and approved: feature availability and existing
        download entitlements are separate concerns. Turning Offerings
        off stops new activity; it must not reach back and take away a
        file somebody paid for.

        This test previously asserted the opposite — and, once the
        validation gate landed, kept passing for a different reason
        than it claimed, which is its own argument for rewriting it
        rather than adjusting it.
        """
        off = _offering(db, make_space())
        f = _file(db, off)
        buyer = make_user()
        _entitle(db, buyer, off)
        db.flush()
        from app.core.config import settings
        assert settings.offerings_enabled is False
        assert _authorise(f.storage_key, buyer, db) is None

    def test_covers_are_refused_while_disabled(self, db, make_space):
        off = _offering(db, make_space())
        db.flush()
        from app.models.user import User
        owner = db.query(User).filter(User.id == off.created_by_user_id).one()
        key = f"{of.OFFERING_COVERS_PREFIX}/{off.id}/{uuid.uuid4().hex}_c.png"
        assert _authorise(key, owner, db) == 403

    def test_every_offering_route_is_gated_by_the_feature_flag(self):
        """**Updated in B4.** This asserted that no Offering route
        existed at all, which was true while the phase shipped no
        endpoints. B4 adds the creator API, so the guarantee it was
        really protecting — nothing reachable while Offerings is off —
        moves from "no routes" to "every route gated".

        Rewritten rather than deleted, so the change of fact is visible
        in the suite's history.
        """
        from fastapi.routing import APIRoute
        from app.main import app
        routes = [
            r for r in app.routes
            if isinstance(r, APIRoute) and "offerings" in r.path
        ]
        assert routes, "B4 ships the creator API; expected routes"
        for r in routes:
            names = [
                getattr(d.call, "__name__", "") for d in r.dependant.dependencies
            ]
            assert "require_offerings_enabled" in names, r.path


# ---------------------------------------------------------------------------
# 4 · Storage: namespace, routing and validation
# ---------------------------------------------------------------------------


class TestStorageRouting:
    def test_offering_files_land_in_the_private_bucket(self, monkeypatch):
        """By the existing rule rather than a new one: everything that
        is not ``platform-artwork`` is private."""
        from app.core import storage
        from app.core.config import settings
        monkeypatch.setattr(settings, "r2_bucket_private", "fc-private")
        monkeypatch.setattr(settings, "r2_bucket_public", "fc-public")
        key = of.build_storage_key(offering_id="off_1", filename="a.pdf")
        assert storage._bucket_for_key(key) == "fc-private"

    def test_covers_are_also_private(self, monkeypatch):
        from app.core import storage
        from app.core.config import settings
        monkeypatch.setattr(settings, "r2_bucket_private", "fc-private")
        monkeypatch.setattr(settings, "r2_bucket_public", "fc-public")
        key = f"{of.OFFERING_COVERS_PREFIX}/off_1/abc_cover.png"
        assert storage._bucket_for_key(key) == "fc-private"

    def test_no_public_route_serves_offering_files(self):
        """The two public upload routes are enumerated in source. A
        third naming either Offering namespace would be the one change
        that makes a purchased file world-readable."""
        import inspect
        from app.uploads import routes as upload_routes
        src = inspect.getsource(upload_routes)
        # Strip comments and docstrings so the prose explaining *why*
        # there is no such route does not trip the check.
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith(("#", '"', "'", "*"))
        )
        for public_decorator in (
            '@uploads_router.get("/offering-files',
            '@uploads_router.get("/offering-covers',
        ):
            assert public_decorator not in code, public_decorator

    def test_downloads_are_forced_as_attachments(self):
        """Signed on the URL, not merely set on our 302 — the bytes
        come from R2, so a header on the redirect decides nothing."""
        import inspect
        from app.uploads import routes as upload_routes
        src = inspect.getsource(upload_routes._redirect_to_presigned_r2)
        assert "ResponseContentDisposition" in src
        assert "attachment" in src
        src_all = inspect.getsource(upload_routes.serve_upload)
        assert "force_download" in src_all

    def test_the_key_carries_the_offering_id(self):
        key = of.build_storage_key(offering_id="off_abc", filename="x.pdf")
        assert key.startswith(f"{of.OFFERING_FILES_PREFIX}/off_abc/")
        assert of.offering_id_from_storage_key(key) == "off_abc"

    def test_a_repeated_filename_never_repeats_a_key(self):
        """What makes "never overwrite an object still needed" a
        property of the key rather than a rule to remember."""
        a = of.build_storage_key(offering_id="off_1", filename="same.pdf")
        b = of.build_storage_key(offering_id="off_1", filename="same.pdf")
        assert a != b

    def test_a_traversal_filename_cannot_escape_the_namespace(self):
        key = of.build_storage_key(
            offering_id="off_1", filename="../../etc/passwd",
        )
        assert key.startswith(f"{of.OFFERING_FILES_PREFIX}/off_1/")
        assert ".." not in key


class TestFileValidation:
    @pytest.mark.parametrize("name,ctype", [
        ("guide.pdf", "application/pdf"),
        ("bundle.zip", "application/zip"),
        ("notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("budget.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("data.csv", "text/csv"),
        ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ("meditation.mp3", "audio/mpeg"),
        ("reading.m4a", "audio/mp4"),
    ])
    def test_every_approved_format_is_accepted(self, name, ctype):
        out = of.validate_offering_upload(
            filename=name, content_type=ctype, byte_size=1024,
        )
        assert out.content_type == ctype.split(";")[0]

    @pytest.mark.parametrize("name,ctype", [
        ("legacy.doc", "application/msword"),
        ("legacy.xls", "application/vnd.ms-excel"),
        ("legacy.ppt", "application/vnd.ms-powerpoint"),
    ])
    def test_legacy_office_formats_are_now_refused(self, name, ctype):
        """These were accepted in Phase A and removed by approval in
        Phase B: they are OLE containers that can carry a VBA project
        with no outward signal. Rewritten rather than deleted, so the
        change of policy is visible in the suite's history.
        """
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename=name, content_type=ctype, byte_size=1024,
            )
        assert exc.value.reason == "legacy_office"
        assert ".xlsx" in exc.value.message, "tell the creator the fix"

    @pytest.mark.parametrize("name", [
        "installer.exe", "script.sh", "macro.vbs", "app.apk",
        "payload.js", "tool.py", "lib.dll",
    ])
    def test_executables_are_refused(self, name):
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename=name, content_type="application/octet-stream",
                byte_size=10,
            )
        assert exc.value.reason in ("forbidden_type", "unsupported_type")

    def test_a_double_extension_cannot_smuggle_an_executable(self):
        """Checked against *every* suffix, not just the last one."""
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="invoice.pdf.exe", content_type="application/pdf",
                byte_size=10,
            )
        assert exc.value.reason == "forbidden_type"

    def test_an_unsupported_but_harmless_type_is_refused(self):
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="clip.mp4", content_type="video/mp4", byte_size=10,
            )
        assert exc.value.reason == "unsupported_type"

    def test_a_mismatched_content_type_is_refused(self):
        """Neither the extension nor the declared type is trusted
        alone; the disagreement is the signal."""
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="guide.pdf", content_type="application/zip",
                byte_size=10,
            )
        assert exc.value.reason == "content_type_mismatch"

    def test_a_missing_extension_is_refused(self):
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="README", content_type="text/plain", byte_size=10,
            )
        assert exc.value.reason == "no_extension"

    def test_a_missing_content_type_is_refused(self):
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="guide.pdf", content_type=None, byte_size=10,
            )
        assert exc.value.reason == "missing_content_type"

    def test_an_empty_file_is_refused(self):
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="guide.pdf", content_type="application/pdf",
                byte_size=0,
            )
        assert exc.value.reason == "empty_file"

    def test_the_per_file_ceiling_is_enforced(self):
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="huge.zip", content_type="application/zip",
                byte_size=of.MAX_OFFERING_FILE_BYTES + 1,
            )
        assert exc.value.reason == "file_too_large"
        # And the boundary itself is allowed.
        of.validate_offering_upload(
            filename="exact.zip", content_type="application/zip",
            byte_size=of.MAX_OFFERING_FILE_BYTES,
        )

    def test_the_bundle_ceiling_is_enforced(self):
        """Without this, "multiple files supported" has no ceiling at
        all and the egress bill is unbounded."""
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="one-more.pdf", content_type="application/pdf",
                byte_size=1024,
                existing_bundle_bytes=of.MAX_OFFERING_BUNDLE_BYTES,
            )
        assert exc.value.reason == "bundle_too_large"

    def test_the_file_count_ceiling_is_enforced(self):
        with pytest.raises(of.OfferingFileRejected) as exc:
            of.validate_offering_upload(
                filename="one-more.pdf", content_type="application/pdf",
                byte_size=1024,
                existing_bundle_count=of.MAX_OFFERING_FILE_COUNT,
            )
        assert exc.value.reason == "too_many_files"

    def test_filenames_are_sanitised(self):
        out = of.validate_offering_upload(
            filename="My Guide (final!).pdf", content_type="application/pdf",
            byte_size=10,
        )
        assert "/" not in out.original_filename
        assert " " not in out.original_filename
        assert out.original_filename.endswith(".pdf")

    def test_the_global_upload_allow_list_is_not_widened(self):
        """The reason this module exists. Adding ``.zip`` and ``.xlsx``
        to ``core.storage.ALLOWED_EXTENSIONS`` would let somebody
        upload an archive as their avatar."""
        from app.core.storage import ALLOWED_EXTENSIONS
        for ext in (".zip", ".xlsx", ".csv", ".pptx", ".xls", ".ppt"):
            assert ext not in ALLOWED_EXTENSIONS, ext


# ---------------------------------------------------------------------------
# 5 · Nothing else moved
# ---------------------------------------------------------------------------


class TestExistingBehaviourUnchanged:
    def test_the_pre_existing_namespaces_still_dispatch(self):
        """Phase A added two entries to the table; it must not have
        disturbed the eight that were there."""
        from app.uploads import authorization
        for prefix in (
            "avatars", "covers", "logos", "island-artwork",
            "pathway-covers", "event-thumbnails", "steps", "media",
        ):
            assert prefix in authorization._DISPATCH, prefix

    def test_the_offer_pages_table_is_untouched(self):
        """Retired, deliberately preserved, and emphatically not the
        model Offerings was built on."""
        from app.db.base import Base
        assert "offer_pages" in Base.metadata.tables
        assert "offerings" in Base.metadata.tables
        offerings = Base.metadata.tables["offerings"]
        assert offerings.name != "offer_pages"

    def test_migration_104_still_exists(self):
        import pathlib
        versions = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
        assert (versions / "104_offer_pages.py").exists()

    def test_gathering_capacity_rule_is_unchanged(self):
        """Offerings touched neither capacity nor fulfilment. Pinned
        because this phase edited files next door to both."""
        from app.services.gathering_tickets import CAPACITY_USED_SQL
        sql = str(CAPACITY_USED_SQL)
        assert "pending_payment" in sql and "confirmed" in sql
        assert "hold_expires_at" not in sql

    def test_the_three_original_grant_kinds_still_mean_what_they_did(self):
        """Phase A deliberately did not add an Offering grant kind,
        because it needed the live CHECK constraint altered — approved
        and done in migration 162.

        What this guards now is that widening it did not disturb the
        three that were already there. Their *values* are the part that
        matters: every ``payment_option_grants`` row in production
        carries one of these strings, so a rename would orphan live
        commerce rows from the resolver that reads them."""
        from app.models import payment_option_grant as pog
        assert pog.GRANT_KIND_PATHWAY == "pathway"
        assert pog.GRANT_KIND_EVENT_SERIES == "event_series"
        assert pog.GRANT_KIND_GATHERING == "gathering"
        assert pog.GRANT_KIND_OFFERING == "offering"

    def test_only_payment_option_grants_gained_an_offering_column(self):
        """Phase A was purely additive — three new tables and nothing
        bolted onto a table holding production rows.

        Phase C/D adds exactly one column to one existing table:
        ``payment_option_grants.offering_id``, which is how a Payment
        Option comes to sell an Offering and therefore how Offerings
        reach the existing checkout at all. Named here rather than the
        rule being dropped, so the *next* column on a live table still
        has to be a deliberate decision rather than an accident."""
        from app.db.base import Base
        new = {"offerings", "offering_files", "offering_entitlements"}
        permitted = {"payment_option_grants": {"offering_id"}}
        for name, table in Base.metadata.tables.items():
            if name in new:
                continue
            offenders = [
                c.name for c in table.columns
                if "offering" in c.name
                and c.name not in permitted.get(name, set())
            ]
            assert offenders == [], f"{name}: {offenders}"
