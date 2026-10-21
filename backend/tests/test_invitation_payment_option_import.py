"""FC-API-A: the Collective invitations endpoints returned HTTP 500.

    ImportError: cannot import name 'PaymentOption'
                 from 'app.models.platform'
    app/creator/routes.py:2605, in _invitation_response()

``PaymentOption`` lives in ``app.models.payment_option``.
``app.models.platform`` never exported it, so the import raised every
time — and because it sits **above** the ``if inv.payment_option_id:``
guard, an invitation with no payment option failed in exactly the same
way as one with. Listing, creating and sending were all affected; only
delete, which does not build a response body, escaped.

Why it reached production
-------------------------

A module-level import of a missing name fails at import time and takes
the whole app down, which is impossible to miss. This was a
**function-level** import, so it failed only when the function ran —
and nothing exercised these three endpoints. There was no test touching
``/invitations`` at all.

So these tests go through the real HTTP stack rather than calling the
handler, because the thing being protected is the status code a creator
receives. A 500 from a serialisation helper is indistinguishable from
a working endpoint until somebody opens the page.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user, get_verified_creator_user
from app.core.database import get_db
from app.main import app
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.platform import (
    Pathway,
    PathwayType,
    Space,
    SpaceInvitation,
    SpaceMembership,
    SpaceMembershipStatus,
)
from app.models.user import User


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def creator_space(db, make_user):
    """A Collective and the creator who owns it."""
    owner = make_user(role="creator")
    space = Space(
        id=_uid("s"), slug=f"inv-{uuid.uuid4().hex[:8]}",
        name="Invitation Collective", status="active", creator_id=owner.id,
    )
    db.add(space)
    db.flush()
    db.add(SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=owner.id, role="creator",
        status=SpaceMembershipStatus.active, source="creator_owner",
        joined_at=datetime.utcnow(),
    ))
    db.flush()
    return space, owner


@pytest.fixture
def client(db, creator_space):
    """A real HTTP client, authenticated as the Collective's owner.

    Both creator dependencies are overridden because the invitation
    endpoints do not all use the same one: listing takes
    ``get_creator_user`` and creating takes
    ``get_verified_creator_user``.
    """
    _space, owner = creator_space

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_creator_user] = lambda: owner
    app.dependency_overrides[get_verified_creator_user] = lambda: owner
    yield TestClient(app, follow_redirects=False)
    for dep in (get_db, get_creator_user, get_verified_creator_user):
        app.dependency_overrides.pop(dep, None)


def _payment_option(db, space) -> PaymentOption:
    """A published Payment Option in this Collective, attached to a
    Pathway — the shape a real joining option has."""
    pw = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Practice", status="active", access_type="free",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(pw)
    db.flush()
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="pathway",
        attaches_to_id=pw.id, name="Founding member rate",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published, currency="AUD",
        override_total_cents=12000,
    )
    db.add(opt)
    db.flush()
    return opt


def _invitation(db, space, owner, *, option: PaymentOption | None = None,
                email: str | None = None) -> SpaceInvitation:
    inv = SpaceInvitation(
        id=_uid("inv"), space_id=space.id,
        email=email or f"invitee-{uuid.uuid4().hex[:8]}@example.test",
        name="Invited Person", role="learner", note=None,
        invited_by_id=owner.id, token=str(uuid.uuid4()),
        payment_option_id=option.id if option else None,
        payment_status="unpaid" if option else None,
    )
    db.add(inv)
    db.flush()
    return inv


# ---------------------------------------------------------------------------
# The reported failure
# ---------------------------------------------------------------------------


class TestListingInvitations:

    def test_an_invitation_without_a_payment_option_lists(
        self, client, db, creator_space,
    ):
        """The case the original report makes easy to overlook.

        The broken import sat above the ``if inv.payment_option_id:``
        guard, so it ran unconditionally — an invitation with no payment
        option failed identically. A test that only covered the
        payment-option branch would have missed half the blast radius
        and, worse, suggested the bug was conditional.
        """
        space, owner = creator_space
        inv = _invitation(db, space, owner)
        res = client.get(f"/api/creator/spaces/{space.slug}/invitations")
        assert res.status_code == 200, res.text
        body = res.json()
        assert [i["id"] for i in body] == [inv.id]
        assert body[0]["payment_option_id"] is None
        assert body[0]["payment_option_name"] is None

    def test_an_invitation_with_a_payment_option_lists_its_name(
        self, client, db, creator_space,
    ):
        """And the branch the import was there to serve actually works —
        the Payment Option's name is resolved and returned."""
        space, owner = creator_space
        opt = _payment_option(db, space)
        inv = _invitation(db, space, owner, option=opt)
        res = client.get(f"/api/creator/spaces/{space.slug}/invitations")
        assert res.status_code == 200, res.text
        [row] = res.json()
        assert row["id"] == inv.id
        assert row["payment_option_id"] == opt.id
        assert row["payment_option_name"] == "Founding member rate"

    def test_a_mixed_list_returns_both(self, client, db, creator_space):
        """Both shapes in one response, which is what a real Collective
        running a paid cohort alongside free invitations produces."""
        space, owner = creator_space
        opt = _payment_option(db, space)
        with_opt = _invitation(db, space, owner, option=opt)
        without = _invitation(db, space, owner)
        res = client.get(f"/api/creator/spaces/{space.slug}/invitations")
        assert res.status_code == 200, res.text
        by_id = {i["id"]: i for i in res.json()}
        assert set(by_id) == {with_opt.id, without.id}
        assert by_id[with_opt.id]["payment_option_name"] == "Founding member rate"
        assert by_id[without.id]["payment_option_name"] is None

    def test_an_empty_list_is_an_empty_list(self, client, creator_space):
        space, _owner = creator_space
        res = client.get(f"/api/creator/spaces/{space.slug}/invitations")
        assert res.status_code == 200, res.text
        assert res.json() == []

    def test_an_archived_payment_option_still_resolves_its_name(
        self, client, db, creator_space,
    ):
        """An option a creator has archived keeps its name on the
        invitation. Archiving is the lifecycle an option actually has —
        it is never hard-deleted once referenced, which the foreign key
        below enforces — so this is the real "stale option" case rather
        than an invented one."""
        space, owner = creator_space
        opt = _payment_option(db, space)
        inv = _invitation(db, space, owner, option=opt)
        opt.status = PaymentOptionStatus.archived.value
        db.flush()
        res = client.get(f"/api/creator/spaces/{space.slug}/invitations")
        assert res.status_code == 200, res.text
        [row] = res.json()
        assert row["id"] == inv.id
        assert row["payment_option_name"] == "Founding member rate"

    def test_the_foreign_key_is_what_makes_a_dangling_id_impossible(self):
        """Why ``opt.name if opt else None`` is belt-and-braces.

        An earlier version of this test set ``payment_option_id`` to a
        value with no row behind it and expected a null name. The
        database refused the write: ``space_invitations
        .payment_option_id`` carries a foreign key, so that state is
        unreachable. Asserting the constraint says the same thing
        truthfully, and would notice if the key were ever dropped —
        at which point the ``else None`` branch stops being theoretical.
        """
        from app.models.platform import SpaceInvitation
        col = SpaceInvitation.__table__.c.payment_option_id
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "payment_options.id" in targets, targets
        assert col.nullable, (
            "an invitation without a Payment Option must remain possible"
        )


class TestCreatingInvitations:
    """``create_invitation`` returns through the same helper, so it was
    broken too — the creator saw a 500 after the row had already been
    committed."""

    def test_creating_without_a_payment_option(
        self, client, db, creator_space,
    ):
        space, _owner = creator_space
        res = client.post(
            f"/api/creator/spaces/{space.slug}/invitations",
            json={"email": "new-person@example.test", "name": "New Person",
                  "role": "learner"},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["email"] == "new-person@example.test"
        assert body["payment_option_name"] is None
        # And it is really there.
        assert db.query(SpaceInvitation).filter(
            SpaceInvitation.id == body["id"],
        ).one().email == "new-person@example.test"

    def test_creating_with_a_payment_option(self, client, db, creator_space):
        space, _owner = creator_space
        opt = _payment_option(db, space)
        res = client.post(
            f"/api/creator/spaces/{space.slug}/invitations",
            json={"email": "paid-person@example.test", "name": "Paid Person",
                  "role": "learner", "payment_option_id": opt.id,
                  "payment_status": "unpaid"},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["payment_option_id"] == opt.id
        assert body["payment_option_name"] == "Founding member rate"

    def test_the_duplicate_guards_still_answer_409(
        self, client, db, creator_space,
    ):
        """Behaviour that must not change. A 500 from the response
        helper would mask these, so they are asserted alongside."""
        space, owner = creator_space
        _invitation(db, space, owner, email="already@example.test")
        res = client.post(
            f"/api/creator/spaces/{space.slug}/invitations",
            json={"email": "already@example.test", "role": "learner"},
        )
        assert res.status_code == 409, res.text

        member = db.query(User).filter(User.id == owner.id).one()
        res = client.post(
            f"/api/creator/spaces/{space.slug}/invitations",
            json={"email": member.email.lower(), "role": "learner"},
        )
        assert res.status_code == 409, res.text


class TestDeletingAnInvitation:
    """Delete returns 204 with no body, so it never reached the broken
    helper — asserted so the hotfix is known not to have changed it."""

    def test_delete_still_works(self, client, db, creator_space):
        space, owner = creator_space
        inv = _invitation(db, space, owner)
        res = client.delete(
            f"/api/creator/spaces/{space.slug}/invitations/{inv.id}",
        )
        assert res.status_code == 204, res.text
        assert db.query(SpaceInvitation).filter(
            SpaceInvitation.id == inv.id,
        ).first() is None


class TestAcceptingAnInvitation:
    """Acceptance lives in ``app/spaces/routes.py`` and builds its own
    response, so it never reached the broken helper and was never
    affected.

    Covered anyway, because "the hotfix did not disturb acceptance" is
    the claim being made and an untested claim is a guess. It also
    closes the loop the brief asked for: listing, creation **and**
    acceptance.
    """

    def test_accepting_an_invitation_joins_the_collective(
        self, db, creator_space, make_user,
    ):
        from app.spaces.routes import accept_invite
        space, owner = creator_space
        invitee = make_user(email="joiner@example.test")
        inv = _invitation(db, space, owner, email="joiner@example.test")
        token = inv.token

        out = accept_invite(token, db=db, current_user=invitee)
        assert out == {"accepted": True, "space_slug": space.slug}

        row = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == invitee.id,
            )
            .one()
        )
        assert row.status == SpaceMembershipStatus.active
        assert row.source == "invited"
        # Consumed.
        assert db.query(SpaceInvitation).filter(
            SpaceInvitation.id == inv.id,
        ).first() is None

    def test_accepting_an_invitation_that_carries_a_payment_option(
        self, db, creator_space, make_user,
    ):
        """The shape most likely to have been disturbed by a change to
        payment-option handling. Acceptance does not read the option at
        all — membership is granted and the invitation consumed exactly
        as for a free one."""
        space, owner = creator_space
        opt = _payment_option(db, space)
        invitee = make_user(email="paidjoiner@example.test")
        inv = _invitation(
            db, space, owner, option=opt, email="paidjoiner@example.test",
        )
        from app.spaces.routes import accept_invite
        out = accept_invite(inv.token, db=db, current_user=invitee)
        assert out["accepted"] is True
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == invitee.id,
        ).one().status == SpaceMembershipStatus.active
        # The Payment Option itself is untouched by acceptance.
        db.refresh(opt)
        assert opt.name == "Founding member rate"
        assert opt.status.value == "published"

    def test_an_unknown_token_is_refused(self, db, make_user):
        from fastapi import HTTPException
        from app.spaces.routes import accept_invite
        with pytest.raises(HTTPException) as e:
            accept_invite(str(uuid.uuid4()), db=db, current_user=make_user())
        assert e.value.status_code in (404, 410)


class TestTheManualMemberPathThatSharedTheBug:
    """``_manual_member_response`` carried the identical broken import at
    line 9501, inside ``if m.payment_option_id and db is not None:``.

    Guarded, so it only raised for a manual member who had a Payment
    Option attached — which is why it never appeared in Sentry beside
    FC-API-A. It is the same defect and is fixed by the same change.
    """

    def test_a_manual_member_with_a_payment_option_resolves_its_name(
        self, db, creator_space,
    ):
        from app.creator.routes import _manual_member_response
        from app.models.platform import ManualMember
        space, _owner = creator_space
        opt = _payment_option(db, space)
        m = ManualMember(
            id=_uid("mm"), space_id=space.id, first_name="Ada",
            last_name="Member", email="ada@example.test",
            payment_option_id=opt.id, payment_status="paid", status="offline",
        )
        db.add(m)
        db.flush()
        out = _manual_member_response(m, db)
        assert out.payment_option_id == opt.id
        assert out.payment_option_name == "Founding member rate"

    def test_a_manual_member_without_one_is_unaffected(
        self, db, creator_space,
    ):
        from app.creator.routes import _manual_member_response
        from app.models.platform import ManualMember
        space, _owner = creator_space
        m = ManualMember(
            id=_uid("mm"), space_id=space.id, first_name="Bo",
            last_name=None, email=None, payment_option_id=None,
            payment_status=None, status="offline",
        )
        db.add(m)
        db.flush()
        out = _manual_member_response(m, db)
        assert out.payment_option_id is None
        assert out.payment_option_name is None
        assert out.display_name == "Bo"


# ---------------------------------------------------------------------------
# The same mistake, found elsewhere by the same scan
# ---------------------------------------------------------------------------


class TestTheAttendancePathThatSharedTheBug:
    """``attendance._payment_label`` carried the same mistake with a
    different model — ``PaymentTransaction`` from
    ``app.models.platform`` — and a second fault behind it: the next
    line read ``tx.amount_cents``, which is not a column either.

    Correcting only the import would have moved the failure one line
    down, from ImportError to AttributeError, which is why this has
    tests rather than just a corrected import.
    """

    def _booking_with_payment(self, db, creator_space, gross: int):
        from datetime import timedelta
        from app.models.payment import (
            PaymentProvider, PaymentTransaction, PaymentTransactionStatus,
            PaymentTransactionType, PayoutStatus,
        )
        from app.models.platform import (
            BookingStatus, Event, EventBooking,
        )
        space, owner = creator_space
        ev = Event(
            id=_uid("ev"), space_id=space.id, created_by_id=owner.id,
            title="Gathering", starts_at=datetime.utcnow() + timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
            location_type="zoom", is_published=True, status="active",
            requires_booking=True, capacity=10,
            booking_access_type="paid_separately", gathering_type="workshop",
            attendance_format="online", ticket_price_cents=2500,
            ticket_currency="AUD",
        )
        db.add(ev)
        db.flush()
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.gathering_ticket_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=owner.id, creator_user_id=owner.id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=gross,
            platform_fee_basis_points=0, platform_fee_cents=0,
            net_creator_amount_cents=0, net_platform_amount_cents=0,
            payout_status=PayoutStatus.not_applicable, stripe_mode="test",
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        db.add(txn)
        db.flush()
        booking = EventBooking(
            id=_uid("bk"), event_id=ev.id, user_id=owner.id,
            status=BookingStatus.confirmed, payment_transaction_id=txn.id,
        )
        db.add(booking)
        db.flush()
        return booking

    def test_a_paid_booking_shows_the_amount_charged(
        self, db, creator_space,
    ):
        """What the attendee paid, formatted — the label this code was
        always meant to produce and never once did in production."""
        from app.creator.attendance import _payment_label
        booking = self._booking_with_payment(db, creator_space, 2500)
        assert _payment_label(booking) == "AUD 25.00 · Paid"

    def test_a_zero_amount_still_reads_as_paid(self, db, creator_space):
        """A complimentary ticket recorded as a zero-value transaction.
        ``0 is not None``, so the label says so rather than falling
        through to "Included with collective" — which would describe a
        different thing."""
        from app.creator.attendance import _payment_label
        booking = self._booking_with_payment(db, creator_space, 0)
        assert _payment_label(booking) == "AUD 0.00 · Paid"

    def test_the_amount_guard_is_belt_and_braces(self):
        """``if tx.gross_amount_cents is not None`` cannot be false for a
        row that exists — the column is NOT NULL.

        An earlier version of this test tried to create a transaction
        without an amount and the database refused it. The guard is
        harmless and worth keeping, but it is not a live branch, and
        saying so is better than a test that pretends to exercise it.
        """
        from app.models.payment import PaymentTransaction
        assert PaymentTransaction.__table__.c.gross_amount_cents.nullable is False

    def test_the_other_label_branches_are_untouched(self, db, creator_space):
        """The fix must not have changed the three labels that never
        loaded a transaction."""
        from app.creator.attendance import _payment_label
        from app.models.platform import BookingStatus, EventBooking

        class _Fake:
            access_pass_id = None
            payment_transaction_id = None
            source = None

        b = _Fake()
        b.access_pass_id = "ap_1"
        assert _payment_label(b) == "Included in pass"
        b.access_pass_id = None
        b.source = "creator_manual"
        assert _payment_label(b) == "Complimentary (creator added)"
        b.source = "self"
        assert _payment_label(b) == "Included with collective"

    def test_gross_amount_cents_is_a_real_column(self):
        """And ``amount_cents`` is not — the second fault, pinned so a
        future edit cannot reintroduce it."""
        from app.models.payment import PaymentTransaction
        cols = {c.name for c in PaymentTransaction.__table__.c}
        assert "gross_amount_cents" in cols
        assert "amount_cents" not in cols


class TestNoOtherBrokenImportsFromPlatform:

    def test_every_name_imported_from_platform_actually_exists(self):
        """A source guard over the whole repository.

        Three of these were live when FC-API-A was reported — two for
        ``PaymentOption`` and one for ``PaymentTransaction`` — and all
        three were function-level, so none of them failed at import
        time. This walks the AST instead, which finds them whether or
        not anything calls the function.
        """
        import ast
        import pathlib

        import app.models.platform as platform_mod

        exported = set(dir(platform_mod))
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders: list[str] = []
        for path in sorted(root.rglob("*.py")):
            if ".venv" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module != "app.models.platform":
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if alias.name not in exported:
                        offenders.append(
                            f"{path.relative_to(root)}:{node.lineno} "
                            f"imports {alias.name!r}"
                        )
        assert offenders == [], (
            "name(s) imported from app.models.platform that it does not "
            "export — a function-level import of one of these raises only "
            "when the function runs: " + "; ".join(offenders)
        )

    def test_the_two_payment_models_are_where_the_fix_says(self):
        """The positive half: the names resolve from their real homes."""
        from app.models.payment import PaymentTransaction
        from app.models.payment_option import PaymentOption
        assert PaymentOption.__tablename__ == "payment_options"
        assert PaymentTransaction.__tablename__ == "payment_transactions"
