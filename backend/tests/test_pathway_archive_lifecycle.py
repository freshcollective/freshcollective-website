"""Archiving a Pathway takes it out of circulation, not out of a
member's hands.

The defect
----------
All three access surfaces tested ``status in ("draft", "archived",
"coming_soon")`` and refused **before** looking at what the member
held. So the Pathway Settings status dropdown — which has always
offered ``Archived``, with no warning — silently revoked every
purchase. The member's entitlement row, their progress and their
written reflections all stayed in the database and all became
unreachable.

Nothing else on the platform behaves that way. ``retire_offering``
states it outright: *"Nothing about existing ownership is touched —
entitlements are not read here, let alone revoked, and download
authorisation never consults Offering status."* And
``pathway_access.unlock_option_ids_for_pathway`` has always treated an
archived **Payment Option** as one whose *"historical buyers keep what
they paid for"*. The Pathway status gate was the only place that
disagreed with the rest of the system.

What archiving means now
------------------------
Four things, and these tests are one section per thing:

1. **Out of public discovery.** Unchanged, and asserted here so it
   cannot regress — archived Pathways are absent from the anonymous
   listing, the Explore counts and the Collective payload.
2. **No new purchases.** Enforced at the checkout door rather than by
   archiving the creator's Payment Options behind their back.
3. **Purchasers keep it.** A durable acquisition record — an active
   entitlement, or an active pass on an including Option — opens an
   archived Pathway. Applied *in addition to* the ordinary access-type
   rule, so nothing is widened.
4. **Reversible.** Nothing is deleted, and the creator can restore it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.creator.routes import (
    list_pathways as creator_list_pathways,
    update_pathway,
)
from app.creator.schemas import PathwayUpdateRequest
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES,
    GRANT_KIND_PATHWAY,
    PaymentOptionGrant,
)
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    PathwayStatus,
    PathwayStep,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepProgress,
)
from app.services import pathway_commerce
from app.services.pathway_access import compute_pathway_access
from app.spaces.routes import (
    hydrate_public_space_cards,
    list_pathways as member_list_pathways,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _pathway(db, space, *, status=PathwayStatus.archived,
             access_type="one_time", **kw) -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=kw.pop("title", "Archived Pathway"),
        status=status,
        access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy",
        currency="AUD",
        **kw,
    )
    db.add(p)
    db.flush()
    return p


def _member(db, space, user, role=SpaceRole.learner, status=None):
    m = SpaceMembership(
        id=_uid("sm"),
        space_id=space.id,
        user_id=user.id,
        role=role,
        status=status or SpaceMembershipStatus.active,
    )
    db.add(m)
    db.flush()
    return m


def _entitlement(db, space, pathway, user, *, status=None, ends_at=None):
    e = PathwayEntitlement(
        id=_uid("ent"),
        user_id=user.id,
        space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=status or EntitlementStatus.active,
        starts_at=datetime.utcnow() - timedelta(days=30),
        ends_at=ends_at,
    )
    db.add(e)
    db.flush()
    return e


def _option(db, space, pathway, *, status=PaymentOptionStatus.published, **kw):
    """An Option authored on the Pathway's own payment-options surface."""
    now = datetime.utcnow()
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=kw.pop("pathway_id", pathway.id if pathway else None),
        attaches_to_kind=kw.pop("attaches_to_kind", "pathway"),
        attaches_to_id=kw.pop(
            "attaches_to_id", pathway.id if pathway else space.id,
        ),
        name="An Option",
        payment_type=PaymentOptionType.one_time,
        status=status,
        override_total_cents=5000,
        currency="AUD",
        created_at=now,
        updated_at=now,
        **kw,
    )
    db.add(opt)
    db.flush()
    return opt


def _grant(db, option, *, pathway=None, series_id=None):
    g = PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=option.id,
        grant_kind=(
            GRANT_KIND_PATHWAY if pathway is not None
            else GRANT_KIND_EVENT_SERIES
        ),
        pathway_id=pathway.id if pathway is not None else None,
        series_id=series_id,
    )
    db.add(g)
    db.flush()
    return g


@pytest.fixture
def world(db, make_space, make_user):
    """A Collective, its owner, a purchaser and a bystander."""
    def _factory(**space_kw):
        owner = make_user(role="creator")
        space = make_space(creator=owner, **space_kw)
        _member(db, space, owner, role=SpaceRole.creator)
        buyer = make_user()
        _member(db, space, buyer)
        bystander = make_user()
        _member(db, space, bystander)
        return space, owner, buyer, bystander
    return _factory


# ---------------------------------------------------------------------------
# 1 — Purchasers keep what they bought
# ---------------------------------------------------------------------------


class TestPurchasersKeepArchivedPathways:
    def test_a_one_time_buyer_keeps_access(self, db, world):
        space, _owner, buyer, _by = world()
        pw = _pathway(db, space, access_type="one_time", price_cents=5000)
        _entitlement(db, space, pw, buyer)

        assert compute_pathway_access(buyer, pw, space, db) is True

    def test_a_subscriber_keeps_access(self, db, world):
        space, _owner, buyer, _by = world()
        pw = _pathway(db, space, access_type="subscription")
        _entitlement(db, space, pw, buyer)

        assert compute_pathway_access(buyer, pw, space, db) is True

    def test_a_manual_grant_holder_keeps_access(self, db, world):
        """A Creator's deliberate grant lands in the same table as a
        purchase, and is just as much a record of access having been
        given. Revoking it on archive would undo the Creator's own
        decision."""
        space, _owner, buyer, _by = world()
        pw = _pathway(db, space)
        ent = _entitlement(db, space, pw, buyer)
        ent.source = EntitlementSource.manual_grant
        db.flush()

        assert compute_pathway_access(buyer, pw, space, db) is True

    def test_a_buyer_who_left_the_collective_keeps_a_one_time_purchase(
        self, db, world, make_user,
    ):
        """``one_time`` has never consulted membership — a purchase is
        the member's property, not a membership perk. Archiving must
        not quietly introduce a membership requirement that the live
        Pathway does not have."""
        space, _owner, _buyer, _by = world()
        departed = make_user()
        _member(
            db, space, departed, status=SpaceMembershipStatus.removed,
        )
        pw = _pathway(db, space, access_type="one_time", price_cents=5000)
        _entitlement(db, space, pw, departed)

        assert compute_pathway_access(departed, pw, space, db) is True

    def test_the_pathway_content_endpoint_agrees(self, db, world):
        """The 403-raising surface, asserted separately — three copies
        of this rule drifting apart is the defect this file's sibling
        (``test_included_with_offer_entitlement_access``) exists for."""
        from app.spaces.routes import _check_pathway_access

        space, _owner, buyer, bystander = world()
        pw = _pathway(db, space)
        _entitlement(db, space, pw, buyer)

        _check_pathway_access(buyer, pw, space, db)  # does not raise

        with pytest.raises(HTTPException) as exc:
            _check_pathway_access(bystander, pw, space, db)
        assert exc.value.status_code == 403
        assert "archived" in exc.value.detail.lower()


class TestNonPurchasersAreDenied:
    def test_a_plain_member_cannot_open_it(self, db, world):
        space, _owner, _buyer, bystander = world()
        pw = _pathway(db, space)

        assert compute_pathway_access(bystander, pw, space, db) is False

    def test_an_anonymous_visitor_cannot_open_it(self, db, world):
        space, *_ = world()
        pw = _pathway(db, space)

        assert compute_pathway_access(None, pw, space, db) is False

    @pytest.mark.parametrize("access_type", ["free", "included"])
    def test_archiving_closes_a_free_or_included_pathway(
        self, db, world, access_type,
    ):
        """There is no acquisition behind membership-granted access, so
        there is nothing to preserve — and archiving has to mean
        something for the Pathways that are not sold individually.
        Letting membership alone open an archived Pathway would be the
        "additional access" this change must not grant.
        """
        space, _owner, _buyer, bystander = world()
        pw = _pathway(db, space, access_type=access_type)

        assert compute_pathway_access(bystander, pw, space, db) is False

    @pytest.mark.parametrize(
        "status", [EntitlementStatus.revoked, EntitlementStatus.expired],
    )
    def test_a_dead_entitlement_opens_nothing(self, db, world, status):
        space, _owner, buyer, _by = world()
        pw = _pathway(db, space)
        _entitlement(db, space, pw, buyer, status=status)

        assert compute_pathway_access(buyer, pw, space, db) is False

    def test_a_lapsed_entitlement_opens_nothing(self, db, world):
        space, _owner, buyer, _by = world()
        pw = _pathway(db, space)
        _entitlement(
            db, space, pw, buyer,
            ends_at=datetime.utcnow() - timedelta(days=1),
        )

        assert compute_pathway_access(buyer, pw, space, db) is False

    def test_a_caretaker_keeps_access_without_holding_anything(
        self, db, world,
    ):
        space, owner, _buyer, _by = world()
        pw = _pathway(db, space)

        assert compute_pathway_access(owner, pw, space, db) is True


# ---------------------------------------------------------------------------
# 2 — Out of public discovery
# ---------------------------------------------------------------------------


class TestArchivedPathwaysAreNotDiscoverable:
    def test_an_anonymous_listing_omits_it(self, db, world):
        space, *_ = world()
        _pathway(db, space, status=PathwayStatus.active, title="Live one")
        _pathway(db, space, title="Archived one")

        titles = {
            p.title for p in member_list_pathways(
                space.slug, db=db, current_user=None,
            )
        }
        assert titles == {"Live one"}

    def test_a_plain_member_listing_omits_it(self, db, world):
        space, _owner, _buyer, bystander = world()
        _pathway(db, space, status=PathwayStatus.active, title="Live one")
        _pathway(db, space, title="Archived one")

        titles = {
            p.title for p in member_list_pathways(
                space.slug, db=db, current_user=bystander,
            )
        }
        assert titles == {"Live one"}

    def test_the_public_count_omits_it(self, db, world):
        space, *_ = world()
        _pathway(db, space, status=PathwayStatus.active)
        _pathway(db, space)
        _pathway(db, space)

        cards = hydrate_public_space_cards([space], db)
        assert cards[0].pathway_count == 1

    def test_a_purchaser_can_still_find_it_in_their_own_list(self, db, world):
        """The personal exception. Preserved access is worth nothing if
        the Pathway is invisible to the person who holds it — they would
        have access and no link.

        Personal, not public: resolved for this one caller, which is
        why the two tests above still see nothing.
        """
        space, _owner, buyer, _by = world()
        _pathway(db, space, status=PathwayStatus.active, title="Live one")
        archived = _pathway(db, space, title="Archived one")
        _entitlement(db, space, archived, buyer)

        rows = member_list_pathways(space.slug, db=db, current_user=buyer)
        by_title = {p.title: p for p in rows}
        assert set(by_title) == {"Live one", "Archived one"}
        # And it renders unlocked, because they do have access.
        assert by_title["Archived one"].user_has_access is True

    def test_the_exception_does_not_leak_to_a_bystander(self, db, world):
        space, _owner, buyer, bystander = world()
        archived = _pathway(db, space, title="Archived one")
        _entitlement(db, space, archived, buyer)

        titles = {
            p.title for p in member_list_pathways(
                space.slug, db=db, current_user=bystander,
            )
        }
        assert titles == set()

    def test_a_caretaker_sees_it_as_they_always_did(self, db, world):
        space, owner, _buyer, _by = world()
        _pathway(db, space, title="Archived one")

        titles = {
            p.title for p in member_list_pathways(
                space.slug, db=db, current_user=owner,
            )
        }
        assert titles == {"Archived one"}


# ---------------------------------------------------------------------------
# 3 — No new purchases
# ---------------------------------------------------------------------------


class TestArchivingStopsNewPurchases:
    def test_its_own_option_can_no_longer_be_sold(self, db, world):
        space, _owner, _buyer, _by = world()
        pw = _pathway(db, space)
        opt = _option(db, space, pw)
        _grant(db, opt, pathway=pw)

        reason = pathway_commerce.unsellable_reason(db, opt)
        assert reason is not None
        assert "archived" in reason.lower()
        with pytest.raises(HTTPException) as exc:
            pathway_commerce.check_sellable_or_raise(db, opt)
        assert exc.value.status_code == 409

    def test_a_live_pathways_option_still_sells(self, db, world):
        space, _owner, _buyer, _by = world()
        pw = _pathway(db, space, status=PathwayStatus.active)
        opt = _option(db, space, pw)
        _grant(db, opt, pathway=pw)

        assert pathway_commerce.unsellable_reason(db, opt) is None

    def test_a_bundle_with_one_archived_pathway_still_sells(self, db, world):
        """Refusing it would take away access to the Pathways that are
        still on offer, which is the opposite of the instruction. The
        creator archived one item out of five; the bundle still sells
        the other four."""
        space, _owner, _buyer, _by = world()
        live = _pathway(db, space, status=PathwayStatus.active)
        archived = _pathway(db, space)
        opt = _option(
            db, space, None,
            pathway_id=None, attaches_to_kind="space",
            attaches_to_id=space.id,
        )
        _grant(db, opt, pathway=live)
        _grant(db, opt, pathway=archived)

        assert pathway_commerce.unsellable_reason(db, opt) is None

    def test_a_collective_option_granting_only_archived_pathways_stops(
        self, db, world,
    ):
        """Functionally identical to a Pathway-attached Option: every
        single thing it hands over is archived, so there is nothing
        left for a buyer to receive."""
        space, _owner, _buyer, _by = world()
        a = _pathway(db, space)
        b = _pathway(db, space)
        opt = _option(
            db, space, None,
            pathway_id=None, attaches_to_kind="space",
            attaches_to_id=space.id,
        )
        _grant(db, opt, pathway=a)
        _grant(db, opt, pathway=b)

        assert pathway_commerce.unsellable_reason(db, opt) is not None

    def test_a_series_option_bundling_an_archived_pathway_still_sells(
        self, db, world, make_space,
    ):
        """The Option sells the Series. Its bundled Pathway grant being
        archived does not stop people buying the term."""
        from app.models.platform import EventSeries

        space, _owner, _buyer, _by = world()
        archived = _pathway(db, space)
        series = EventSeries(
            id=_uid("es"), space_id=space.id,
            slug=f"es-{uuid.uuid4().hex[:8]}", title="A Term",
            starts_at=datetime.utcnow(), status="published",
        )
        db.add(series)
        db.flush()
        opt = _option(
            db, space, None,
            pathway_id=None, attaches_to_kind="event_series",
            attaches_to_id=series.id,
        )
        _grant(db, opt, series_id=series.id)
        _grant(db, opt, pathway=archived)

        assert pathway_commerce.unsellable_reason(db, opt) is None

    def test_the_legacy_grants_pathway_id_pointer_is_read_too(
        self, db, world,
    ):
        """Fulfilment falls back to ``grants_pathway_id`` for Options
        that are not grant-ready, so a guard reading only grant rows
        would be bypassable by the other pointer."""
        space, _owner, _buyer, _by = world()
        archived = _pathway(db, space)
        opt = _option(
            db, space, None,
            pathway_id=None, attaches_to_kind="space",
            attaches_to_id=space.id,
            grants_pathway_id=archived.id,
        )

        assert pathway_commerce.unsellable_reason(db, opt) is not None

    def test_an_option_granting_no_pathway_is_untouched(self, db, world):
        space, _owner, _buyer, _by = world()
        opt = _option(
            db, space, None,
            pathway_id=None, attaches_to_kind="space",
            attaches_to_id=space.id,
        )

        assert pathway_commerce.unsellable_reason(db, opt) is None

    @pytest.mark.parametrize(
        "status", [PathwayStatus.draft, PathwayStatus.coming_soon],
    )
    def test_draft_and_coming_soon_are_deliberately_not_refused_here(
        self, db, world, status,
    ):
        """Scope, pinned so it reads as a decision. The legacy
        ``/api/checkout/pathway`` door refuses any non-active status,
        but the unified door never has — and a pre-sale of a
        coming-soon Pathway is a plausible deliberate arrangement
        rather than an obvious mistake. This guard is about what
        *archiving* means.
        """
        space, _owner, _buyer, _by = world()
        pw = _pathway(db, space, status=status)
        opt = _option(db, space, pw)
        _grant(db, opt, pathway=pw)

        assert pathway_commerce.unsellable_reason(db, opt) is None

    def test_the_unified_checkout_door_applies_the_guard(self):
        """Source contract on the door rather than a live Stripe round
        trip. Both branches of ``POST /api/checkout`` must call it —
        the pay-in-full/free path and the finite-plan path — because a
        guard on one of two doors is not a guard.

        Read from the parsed source with docstrings dropped, so the
        prose in this file and in the route cannot satisfy it.
        """
        import ast
        import inspect

        from app.checkout import routes as checkout_routes

        src = inspect.getsource(checkout_routes)
        tree = ast.parse(src)
        calls = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr == "check_sellable_or_raise"
            ):
                calls += 1
        assert calls >= 2, f"only {calls} checkout door(s) guarded"


# ---------------------------------------------------------------------------
# 4 — Nothing is destroyed, and it is reversible
# ---------------------------------------------------------------------------


class TestArchivingPreservesEverything:
    def test_progress_and_entitlements_survive_archiving(self, db, world):
        """Archiving is a status change and nothing else. Asserted
        because the delete path *does* cascade these away, and the two
        operations must not be confused."""
        space, owner, buyer, _by = world()
        pw = _pathway(db, space, status=PathwayStatus.active)
        step = PathwayStep(
            id=_uid("st"), pathway_id=pw.id,
            slug=f"step-{uuid.uuid4().hex[:8]}", title="A Step",
        )
        db.add(step)
        db.flush()
        db.add(StepProgress(
            id=_uid("sp"), user_id=buyer.id, step_id=step.id,
            completed_at=datetime.utcnow(),
            reflection_text="What I noticed.",
        ))
        ent = _entitlement(db, space, pw, buyer)
        db.flush()
        ent_id, step_id = ent.id, step.id

        update_pathway(
            space.slug, pw.slug,
            body=PathwayUpdateRequest(status="archived"),
            background_tasks=_NoTasks(),
            db=db, current_user=owner,
        )

        assert db.query(PathwayEntitlement).filter(
            PathwayEntitlement.id == ent_id,
        ).one().status == EntitlementStatus.active
        assert db.query(StepProgress).filter(
            StepProgress.step_id == step_id,
        ).one().reflection_text == "What I noticed."
        assert db.query(PathwayStep).filter(
            PathwayStep.id == step_id,
        ).first() is not None

    def test_payment_records_survive_archiving(self, db, world):
        from app.models.payment import (
            PaymentTransaction,
            PaymentTransactionType,
        )

        space, owner, buyer, _by = world()
        pw = _pathway(db, space, status=PathwayStatus.active)
        txn = PaymentTransaction(
            id=_uid("tx"), space_id=space.id, payer_user_id=buyer.id,
            pathway_id=pw.id,
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            gross_amount_cents=5000,
        )
        db.add(txn)
        db.flush()
        txn_id = txn.id

        update_pathway(
            space.slug, pw.slug,
            body=PathwayUpdateRequest(status="archived"),
            background_tasks=_NoTasks(),
            db=db, current_user=owner,
        )

        kept = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == txn_id,
        ).one()
        assert kept.pathway_id == pw.id

    def test_its_payment_options_are_not_archived_behind_the_creator(
        self, db, world,
    ):
        """Deliberate, and the reason the sell guard reads status at the
        door instead.

        A Pathway's Options are authored by hand and listed on the
        Settings page with their own Archive buttons. The platform's
        standing rule about them is explicit —
        ``delete_gathering_series`` refuses rather than archive,
        because they "belong to the Series and archiving them is a
        Creator choice, not an automatic side effect". Auto-archiving
        would also be a one-way door: restoring the Pathway would not
        un-archive them.
        """
        space, owner, _buyer, _by = world()
        pw = _pathway(db, space, status=PathwayStatus.active)
        opt = _option(db, space, pw)
        opt_id = opt.id

        update_pathway(
            space.slug, pw.slug,
            body=PathwayUpdateRequest(status="archived"),
            background_tasks=_NoTasks(),
            db=db, current_user=owner,
        )

        assert db.query(PaymentOption).filter(
            PaymentOption.id == opt_id,
        ).one().status == PaymentOptionStatus.published


class TestCreatorVisibilityAndRestoration:
    def test_creator_studio_lists_archived_pathways(self, db, world):
        space, owner, _buyer, _by = world()
        _pathway(db, space, title="Archived one")
        _pathway(db, space, status=PathwayStatus.active, title="Live one")

        rows = creator_list_pathways(space.slug, db=db, current_user=owner)
        by_title = {r["title"]: r for r in rows}
        assert set(by_title) == {"Archived one", "Live one"}
        assert by_title["Archived one"]["status"] == "archived"

    def test_restoring_returns_it_to_draft(self, db, world):
        """Restored to Draft rather than straight back to Live: the
        creator decides when it returns to members, and a silent
        re-publish is not theirs to assume."""
        space, owner, _buyer, _by = world()
        pw = _pathway(db, space)

        out = update_pathway(
            space.slug, pw.slug,
            body=PathwayUpdateRequest(status="draft"),
            background_tasks=_NoTasks(),
            db=db, current_user=owner,
        )

        assert out["status"] == "draft"
        db.refresh(pw)
        assert pw.status == PathwayStatus.draft

    def test_restoring_then_publishing_restores_member_access(self, db, world):
        space, owner, _buyer, bystander = world()
        pw = _pathway(db, space, access_type="free")
        assert compute_pathway_access(bystander, pw, space, db) is False

        update_pathway(
            space.slug, pw.slug,
            body=PathwayUpdateRequest(status="active"),
            background_tasks=_NoTasks(),
            db=db, current_user=owner,
        )
        db.refresh(pw)

        assert compute_pathway_access(bystander, pw, space, db) is True

    def test_restoring_makes_its_option_sellable_again(self, db, world):
        """The symmetry the auto-archive approach would have broken."""
        space, owner, _buyer, _by = world()
        pw = _pathway(db, space)
        opt = _option(db, space, pw)
        _grant(db, opt, pathway=pw)
        assert pathway_commerce.unsellable_reason(db, opt) is not None

        update_pathway(
            space.slug, pw.slug,
            body=PathwayUpdateRequest(status="active"),
            background_tasks=_NoTasks(),
            db=db, current_user=owner,
        )
        db.refresh(pw)

        assert pathway_commerce.unsellable_reason(db, opt) is None


class _NoTasks:
    """Stand-in for ``BackgroundTasks``. ``update_pathway`` only ever
    adds to it when an announcement was emitted, which none of these
    status changes does — archiving announces nothing, and republishing
    finds the dedupe key already present."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def add_task(self, *args, **kwargs) -> None:  # pragma: no cover
        self.calls.append((args, kwargs))
