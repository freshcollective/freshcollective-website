"""A Pathway delete must never take a member's purchase, access or work
with it — and must never answer a refusal with a 500.

Sentry FC-API-D reported the 500: ``DELETE
/api/creator/spaces/{slug}/pathways/{slug}`` raised ``IntegrityError``
on ``payment_option_grants_pathway_id_fkey``. Investigating it found the
worse half. ``delete_pathway`` had no checks at all, and of the twenty
foreign keys pointing at ``pathways`` exactly one is ``RESTRICT`` — so
the only Pathways the platform refused to delete were the ones that
happened to have a grant row. Every other Pathway deleted cleanly and
cascaded away:

    pathway_entitlements    somebody's purchased access
    enrollments             their relationship to the journey
    step_progress           their completions and ``reflection_text``
    step_comments           what they said on a step
    exercise_responses      their private written answers

while ``payment_transactions.pathway_id`` and ``.entitlement_id`` were
set to NULL, leaving the money with nothing left to say what it bought.

These tests pin both halves, and they are written as the positive
requirement wherever possible: not merely "the call raises 409" but
**"the member's rows are still there afterwards"**.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.creator.routes import delete_pathway, delete_space
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import (
    GRANT_KIND_PATHWAY,
    PaymentOptionGrant,
)
from app.models.platform import (
    Enrollment,
    Pathway,
    PathwayEntitlement,
    PathwayStep,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    SpaceStatus,
)
from app.services import pathway_commerce, pathway_deletion


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Builders — each one is the smallest row that makes its dependency real
# ---------------------------------------------------------------------------


def _pathway(db, space, *, status="draft", **kw) -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway",
        status=status,
        access_type=kw.pop("access_type", "free"),
        pathway_type=PathwayType.guided_experience,
        pricing_mode=kw.pop("pricing_mode", "legacy"),
        currency="AUD",
        **kw,
    )
    db.add(p)
    db.flush()
    return p


def _step(db, pathway) -> PathwayStep:
    s = PathwayStep(
        id=_uid("st"),
        pathway_id=pathway.id,
        slug=f"step-{uuid.uuid4().hex[:8]}",
        title="A Step",
    )
    db.add(s)
    db.flush()
    return s


def _entitlement(db, space, pathway, user, *, status=None) -> PathwayEntitlement:
    from app.models.platform import EntitlementSource, EntitlementStatus

    e = PathwayEntitlement(
        id=_uid("ent"),
        user_id=user.id,
        space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=status or EntitlementStatus.active,
        starts_at=datetime.utcnow(),
    )
    db.add(e)
    db.flush()
    return e


def _option(db, space, pathway, *, status=PaymentOptionStatus.draft, **kw):
    """A Payment Option authored on the Pathway's own surface — the
    shape ``creator.routes.create_payment_option`` writes."""
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


def _grant(db, option, pathway) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=option.id,
        grant_kind=GRANT_KIND_PATHWAY,
        pathway_id=pathway.id,
    )
    db.add(g)
    db.flush()
    return g


def _member(db, space, user, role=SpaceRole.learner):
    m = SpaceMembership(
        id=_uid("sm"),
        space_id=space.id,
        user_id=user.id,
        role=role,
        status=SpaceMembershipStatus.active,
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def owned(db, make_space, make_user):
    """A Collective, its owner, and a learner member — the cast every
    test below needs."""
    def _factory(**space_kw):
        owner = make_user(role="creator")
        space = make_space(creator=owner, **space_kw)
        _member(db, space, owner, role=SpaceRole.creator)
        learner = make_user()
        _member(db, space, learner)
        return space, owner, learner
    return _factory


# ---------------------------------------------------------------------------
# 1 — The clean case: a draft nobody touched
# ---------------------------------------------------------------------------


class TestDeletingAnUnusedDraft:
    """The case the endpoint exists for. A creator building something,
    changing their mind, and tidying up."""

    def test_a_bare_draft_is_deleted(self, db, owned):
        space, owner, _ = owned()
        pw = _pathway(db, space)
        pw_id = pw.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is None

    def test_its_own_steps_go_with_it(self, db, owned):
        space, owner, _ = owned()
        pw = _pathway(db, space)
        _step(db, pw)
        pw_id = pw.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert db.query(PathwayStep).filter(
            PathwayStep.pathway_id == pw_id,
        ).count() == 0

    def test_a_coming_soon_pathway_is_not_deletable(self, db, owned):
        """``coming_soon`` is a published state a creator chooses — it
        appears in the member list. Taking it back to Draft is the
        deliberate act that makes deletion available."""
        space, owner, _ = owned()
        pw = _pathway(db, space, status="coming_soon")

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert "Draft" in exc.value.detail

    def test_a_live_pathway_is_not_deletable(self, db, owned):
        space, owner, _ = owned()
        pw = _pathway(db, space, status="active")

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_an_archived_pathway_is_kept(self, db, owned):
        """Archived is the historical state. It is not a staging area
        for deletion — its records are the reason it exists."""
        space, owner, _ = owned()
        pw = _pathway(db, space, status="archived")
        pw_id = pw.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert "archived" in exc.value.detail.lower()
        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is not None


# ---------------------------------------------------------------------------
# 2 — The Pathway's own, unused, draft Payment Option goes with it
# ---------------------------------------------------------------------------


class TestItsOwnCommerceRowsAreNotBlockers:
    """The distinction that made FC-API-D a dead end.

    A priced draft already has commerce rows. They exist only to serve
    this Pathway and nobody else can reach them, so they are part of
    what gets deleted. Treating them as blockers is what left the
    reporter unable to delete the Pathway *and* unable to delete the
    Collective — whose own eligibility gate then counted that very
    Payment Option as a blocker.
    """

    def test_a_priced_draft_with_its_own_option_is_deleted(self, db, owned):
        space, owner, _ = owned()
        pw = _pathway(db, space, access_type="one_time", price_cents=5000)
        opt = _option(db, space, pw)
        pw_id, opt_id = pw.id, opt.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is None
        assert db.query(PaymentOption).filter(
            PaymentOption.id == opt_id,
        ).first() is None

    def test_the_restrict_that_produced_the_500_is_satisfied(self, db, owned):
        """The exact Sentry shape: a draft Pathway whose own Payment
        Option holds a ``payment_option_grants`` row. That FK is
        ``ondelete=RESTRICT``, and it is why the endpoint used to 500.

        Deleting the option first lets its grant CASCADE away, which is
        also the only order the RESTRICT permits.
        """
        space, owner, _ = owned()
        pw = _pathway(db, space, access_type="one_time", price_cents=5000)
        opt = _option(db, space, pw)
        grant = _grant(db, opt, pw)
        pw_id, grant_id = pw.id, grant.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is None
        assert db.query(PaymentOptionGrant).filter(
            PaymentOptionGrant.id == grant_id,
        ).first() is None

    def test_an_archived_own_option_also_goes_with_it(self, db, owned):
        """Archived is not the same as used. An option a creator priced,
        never published and then archived has no financial history, and
        the usage checks below are what prove that rather than its
        status."""
        space, owner, _ = owned()
        pw = _pathway(db, space)
        opt = _option(db, space, pw, status=PaymentOptionStatus.archived)
        opt_id = opt.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert db.query(PaymentOption).filter(
            PaymentOption.id == opt_id,
        ).first() is None

    def test_a_published_option_is_refused(self, db, owned):
        """It is sellable right now. Archiving it is the creator's
        decision, never a side effect of tidying a list."""
        space, owner, _ = owned()
        pw = _pathway(db, space)
        opt = _option(db, space, pw, status=PaymentOptionStatus.published)
        opt_id = opt.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert db.query(PaymentOption).filter(
            PaymentOption.id == opt_id,
        ).first() is not None


# ---------------------------------------------------------------------------
# 3 — A Payment Option shared with something else is never touched
# ---------------------------------------------------------------------------


class TestSharedPaymentOptionsAreProtected:
    """A Collective-level or Series-attached Option that *includes* this
    Pathway is a promise to that option's buyers."""

    def test_a_collective_level_option_granting_it_refuses(self, db, owned):
        space, owner, _ = owned()
        pw = _pathway(db, space)
        shared = _option(
            db, space, None,
            status=PaymentOptionStatus.published,
            pathway_id=None,
            attaches_to_kind="space",
            attaches_to_id=space.id,
        )
        grant = _grant(db, shared, pw)
        pw_id, shared_id, grant_id = pw.id, shared.id, grant.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert "Another Payment Option" in exc.value.detail
        # The positive requirement: nothing was removed to make room.
        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is not None
        assert db.query(PaymentOption).filter(
            PaymentOption.id == shared_id,
        ).first() is not None
        assert db.query(PaymentOptionGrant).filter(
            PaymentOptionGrant.id == grant_id,
        ).first() is not None

    def test_a_series_option_pointing_grants_pathway_id_here_refuses(
        self, db, owned,
    ):
        """``grants_pathway_id`` is the pre-grants way of saying the same
        thing, and it is ``SET NULL`` — so without this check the delete
        would quietly turn a paid option into one granting nothing, and
        the next buyer would be charged for no access."""
        space, owner, _ = owned()
        pw = _pathway(db, space)
        other = _option(
            db, space, None,
            status=PaymentOptionStatus.published,
            pathway_id=None,
            attaches_to_kind="event_series",
            attaches_to_id=_uid("es"),
            grants_pathway_id=pw.id,
        )
        other_id = other.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        kept = db.query(PaymentOption).filter(
            PaymentOption.id == other_id,
        ).one()
        assert kept.grants_pathway_id == pw.id

    def test_an_unlock_requirement_from_a_foreign_option_refuses(
        self, db, owned,
    ):
        """``included_with_offer`` wiring: which Options unlock this
        Pathway. A row naming somebody else's option is that option's
        promise to its buyers."""
        from app.models.platform import PathwayUnlockRequirement

        space, owner, _ = owned()
        pw = _pathway(db, space, access_type="included_with_offer")
        shared = _option(
            db, space, None,
            status=PaymentOptionStatus.published,
            pathway_id=None,
            attaches_to_kind="space",
            attaches_to_id=space.id,
        )
        db.add(PathwayUnlockRequirement(
            id=_uid("pur"), pathway_id=pw.id, payment_option_id=shared.id,
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_an_option_scoped_here_but_attached_elsewhere_refuses(
        self, db, owned,
    ):
        """``payment_options.pathway_id`` is ``CASCADE``. An option
        carrying it while attached elsewhere would be deleted outright,
        so it refuses rather than guessing — every authoring surface
        sets the column to NULL explicitly, which is why a mismatch is
        a reason to stop."""
        space, owner, _ = owned()
        pw = _pathway(db, space)
        odd = _option(
            db, space, None,
            pathway_id=pw.id,
            attaches_to_kind="space",
            attaches_to_id=space.id,
        )
        odd_id = odd.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert db.query(PaymentOption).filter(
            PaymentOption.id == odd_id,
        ).first() is not None


# ---------------------------------------------------------------------------
# 4 — A Pathway's own option that has actually been used
# ---------------------------------------------------------------------------


class TestAnOwnOptionThatHasBeenUsed:
    """Removing a Payment Option is not free: ``discount_codes`` scoped
    to it CASCADE away, ``payment_transactions`` and ``access_passes``
    are severed, ``purchase_plans`` is RESTRICT. "Unused" is therefore
    checked explicitly rather than inferred from the Pathway's own
    emptiness."""

    def test_a_transaction_on_its_option_refuses(self, db, owned):
        from app.models.payment import (
            PaymentTransaction,
            PaymentTransactionType,
        )

        space, owner, learner = owned()
        pw = _pathway(db, space)
        opt = _option(db, space, pw)
        txn = PaymentTransaction(
            id=_uid("tx"),
            space_id=space.id,
            payer_user_id=learner.id,
            payment_option_id=opt.id,
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            gross_amount_cents=5000,
        )
        db.add(txn)
        db.flush()
        txn_id, opt_id = txn.id, opt.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        kept = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == txn_id,
        ).one()
        assert kept.payment_option_id == opt_id

    def test_a_discount_code_scoped_to_its_option_refuses(self, db, owned):
        """``discount_codes.scope_id`` is ``CASCADE``. Without this
        check, deleting the Pathway would silently destroy a code the
        creator may have already shared."""
        from app.models.discount_code import DiscountCode

        space, owner, _ = owned()
        pw = _pathway(db, space)
        opt = _option(db, space, pw)
        code = DiscountCode(
            id=_uid("dc"),
            space_id=space.id,
            code=f"SAVE{uuid.uuid4().hex[:6].upper()}",
            discount_type="percentage",
            percent_bps=1000,
            scope_kind="payment_option",
            scope_id=opt.id,
        )
        db.add(code)
        db.flush()
        code_id = code.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert db.query(DiscountCode).filter(
            DiscountCode.id == code_id,
        ).first() is not None

    def test_an_invitation_naming_its_option_refuses(self, db, owned):
        from app.models.platform import SpaceInvitation

        space, owner, _ = owned()
        pw = _pathway(db, space)
        opt = _option(db, space, pw)
        db.add(SpaceInvitation(
            id=_uid("inv"),
            space_id=space.id,
            email=f"invitee-{uuid.uuid4().hex[:6]}@example.test",
            invited_by_id=owner.id,
            token=uuid.uuid4().hex,
            payment_option_id=opt.id,
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_every_foreign_key_into_payment_options_is_accounted_for(self):
        """Non-vacuity guard for the usage census.

        ``_option_usage_reference`` is a list, and a list goes stale
        silently. Every table with a foreign key into ``payment_options``
        must be either checked there or named here as safe to cascade,
        so adding a new one fails this test rather than quietly
        permitting a delete that destroys its rows.
        """
        import inspect

        src = inspect.getsource(pathway_commerce._option_usage_reference)
        # Rows that exist only to serve the option and go with it.
        cascades_by_design = {
            "payment_option_grants",      # what the option grants
            "payment_option_schedules",   # how it is paid
            "pathway_unlock_requirements",  # which pathways it unlocks
        }
        checked = {
            "payment_transactions": "PaymentTransaction",
            "purchase_plans": "PurchasePlan",
            "access_passes": "AccessPass",
            "purchase_intents": "PurchaseIntent",
            "discount_codes": "DiscountCode",
            "discount_reservations": "DiscountReservation",
            "manual_members": "ManualMember",
            "space_invitations": "SpaceInvitation",
        }
        for table, symbol in checked.items():
            assert f"{symbol}." in src, f"{table} no longer checked"
        assert cascades_by_design | set(checked) == _tables_referencing(
            "payment_options",
        )


def _tables_referencing(target: str) -> set[str]:
    """Tables holding a foreign key into ``target``, read from the
    mapped metadata rather than hard-coded, so the schema is the source
    of truth for the census guards."""
    from app.db.base import Base
    import app.models  # noqa: F401 — register every mapper

    out: set[str] = set()
    for name, table in Base.metadata.tables.items():
        for fk in table.foreign_keys:
            if fk.column.table.name == target:
                out.add(name)
    return out


# ---------------------------------------------------------------------------
# 5 — Member records: the half the 500 was hiding
# ---------------------------------------------------------------------------


class TestPurchasedAccessSurvivesARefusedDelete:
    """The headline. Before this change a Pathway with a paid
    entitlement and no grant row deleted cleanly, and the entitlement
    went with it."""

    def test_an_entitlement_refuses_and_is_still_there_afterwards(
        self, db, owned,
    ):
        space, owner, learner = owned()
        pw = _pathway(db, space, access_type="one_time", price_cents=5000)
        ent = _entitlement(db, space, pw, learner)
        pw_id, ent_id = pw.id, ent.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is not None
        kept = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.id == ent_id,
        ).one()
        assert kept.pathway_id == pw_id

    @pytest.mark.parametrize("status_name", ["expired", "revoked"])
    def test_a_lapsed_entitlement_refuses_too(self, db, owned, status_name):
        """Checked in **any** state, exactly as ``delete_offering``
        checks ``OfferingEntitlement``. An expired or revoked
        entitlement is still the record that somebody once had access,
        and a refunded purchase still happened."""
        from app.models.platform import EntitlementStatus

        space, owner, learner = owned()
        pw = _pathway(db, space)
        _entitlement(
            db, space, pw, learner,
            status=getattr(EntitlementStatus, status_name),
        )

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_a_transaction_against_the_pathway_refuses(self, db, owned):
        """``payment_transactions.pathway_id`` is ``SET NULL``, so the
        old behaviour kept the money and threw away its subject."""
        from app.models.payment import (
            PaymentTransaction,
            PaymentTransactionType,
        )

        space, owner, learner = owned()
        pw = _pathway(db, space)
        txn = PaymentTransaction(
            id=_uid("tx"),
            space_id=space.id,
            payer_user_id=learner.id,
            pathway_id=pw.id,
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            gross_amount_cents=5000,
        )
        db.add(txn)
        db.flush()
        txn_id, pw_id = txn.id, pw.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        kept = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == txn_id,
        ).one()
        assert kept.pathway_id == pw_id

    def test_an_enrolment_refuses_and_survives(self, db, owned):
        space, owner, learner = owned()
        pw = _pathway(db, space)
        db.add(Enrollment(
            id=_uid("en"), user_id=learner.id, pathway_id=pw.id,
        ))
        db.flush()
        pw_id = pw.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert db.query(Enrollment).filter(
            Enrollment.pathway_id == pw_id,
        ).count() == 1

    def test_progress_and_a_reflection_refuse_and_survive(self, db, owned):
        """``step_progress`` is two cascades deep — pathway → step →
        progress — and it holds ``reflection_text``, a member's own
        writing."""
        from app.models.platform import StepProgress

        space, owner, learner = owned()
        pw = _pathway(db, space)
        step = _step(db, pw)
        db.add(StepProgress(
            id=_uid("sp"), user_id=learner.id, step_id=step.id,
            completed_at=datetime.utcnow(),
            reflection_text="What I noticed this week.",
        ))
        db.flush()
        step_id = step.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        kept = db.query(StepProgress).filter(
            StepProgress.step_id == step_id,
        ).one()
        assert kept.reflection_text == "What I noticed this week."

    def test_a_step_comment_refuses_and_survives(self, db, owned):
        from app.models.platform import StepComment

        space, owner, learner = owned()
        pw = _pathway(db, space)
        step = _step(db, pw)
        db.add(StepComment(
            id=_uid("sc"), step_id=step.id, author_id=learner.id,
            body="This landed for me.",
        ))
        db.flush()
        step_id = step.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert db.query(StepComment).filter(
            StepComment.step_id == step_id,
        ).count() == 1

    def test_an_exercise_answer_is_protected_by_publication_history(
        self, db, owned,
    ):
        """Members' private exercise answers are three cascades deep —
        pathway → step → block → answer — and the most private thing in
        the list, but they are **not** counted by the preflight.

        The table they live in sits behind a privacy boundary that
        ``test_exercise_responses.TestPrivacy`` enforces by grep: no
        module outside its own member endpoints may name it, so there is
        no surface to audit. ``pathway_deletion`` honours that and
        explains why it can: an answer can only be saved through a step
        the member can open, and ``_check_pathway_access`` refuses
        draft, coming-soon and archived Pathways to everyone but
        caretakers — so a Pathway members once wrote in is one that was
        live, and publication history is what refuses it.

        This test is that claim, made concrete. Without the history
        signal the answer would go; with it, it stays.
        """
        from app.comms.models import CommunicationEvent
        from app.models.platform import (
            ExerciseResponse,
            PathwayStepBlock,
            StepBlockType,
        )
        from app.comms.registry import category_for_topic, get_event_definition
        from app.services.pathway_announcement import (
            ANNOUNCEMENT_EVENT,
            announcement_dedupe_key,
        )

        space, owner, learner = owned()
        pw = _pathway(db, space)
        step = _step(db, pw)
        block = PathwayStepBlock(
            id=_uid("blk"), step_id=step.id,
            block_type=StepBlockType.exercise, position=0,
        )
        db.add(block)
        db.flush()
        db.add(ExerciseResponse(
            id=_uid("xr"), user_id=learner.id, block_id=block.id,
            response_text="My answer.",
        ))
        definition = get_event_definition(ANNOUNCEMENT_EVENT)
        db.add(CommunicationEvent(
            id=_uid("ce"),
            event_type=ANNOUNCEMENT_EVENT,
            topic_key=definition.topic,
            category_key=category_for_topic(definition.topic),
            priority_hint=definition.default_priority,
            dedupe_key=announcement_dedupe_key(pw.id, space.id),
            source_type="creator",
            source_id=owner.id,
        ))
        db.flush()
        block_id = block.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        kept = db.query(ExerciseResponse).filter(
            ExerciseResponse.block_id == block_id,
        ).one()
        assert kept.response_text == "My answer."

    def test_an_answer_alone_on_a_never_published_draft_does_not_block(
        self, db, owned,
    ):
        """The deliberate omission, pinned so it is a decision rather
        than an oversight.

        A never-published draft cannot have been opened by anyone but a
        caretaker, so an answer inside one is the creator's own, written
        while building. If this ever starts failing, the access rules
        have changed and the preflight needs to grow a check — which
        would mean revisiting the privacy boundary above, deliberately.
        """
        from app.models.platform import (
            ExerciseResponse,
            PathwayStepBlock,
            StepBlockType,
        )

        space, owner, _ = owned()
        pw = _pathway(db, space)
        step = _step(db, pw)
        block = PathwayStepBlock(
            id=_uid("blk"), step_id=step.id,
            block_type=StepBlockType.exercise, position=0,
        )
        db.add(block)
        db.flush()
        db.add(ExerciseResponse(
            id=_uid("xr"), user_id=owner.id, block_id=block.id,
            response_text="Checking my own draft.",
        ))
        db.flush()
        pw_id = pw.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is None

    def test_an_access_pass_refuses(self, db, owned):
        from app.models.access_pass import AccessPass

        space, owner, learner = owned()
        pw = _pathway(db, space)
        db.add(AccessPass(
            id=_uid("ap"), user_id=learner.id, space_id=space.id,
            pass_type="term", eligible_pathway_id=pw.id,
            valid_from=datetime.utcnow(),
            valid_until=datetime.utcnow() + timedelta(days=30),
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_an_access_grant_record_refuses(self, db, owned):
        from app.models.access_grant_record import AccessGrantRecord

        space, owner, learner = owned()
        pw = _pathway(db, space)
        db.add(AccessGrantRecord(
            id=_uid("agr"), user_id=learner.id,
            grant_kind="pathway", source_type="manual_grant",
            target_pathway_id=pw.id, granted_at=datetime.utcnow(),
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_a_manual_member_grant_refuses(self, db, owned):
        from app.models.platform import ManualMember, ManualMemberPathwayAccess

        space, owner, _ = owned()
        pw = _pathway(db, space)
        mm = ManualMember(
            id=_uid("mm"), space_id=space.id, first_name="Offline",
        )
        db.add(mm)
        db.flush()
        db.add(ManualMemberPathwayAccess(
            id=_uid("mmpa"), manual_member_id=mm.id, pathway_id=pw.id,
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_a_purchase_intent_refuses(self, db, owned):
        from app.models.purchase_intent import PurchaseIntent

        space, owner, learner = owned()
        pw = _pathway(db, space)
        db.add(PurchaseIntent(
            id=_uid("pi"), kind="pathway", space_id=space.id,
            payer_user_id=learner.id, pathway_id=pw.id,
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409

    def test_every_foreign_key_into_pathways_is_accounted_for(self):
        """The census guard for the Pathway itself.

        Twenty foreign keys point at ``pathways`` and a twenty-first
        added later would inherit whatever ``ondelete`` its author
        chose — RESTRICT turns into a refusal the endpoint now explains,
        but CASCADE and SET NULL are silent. Every one is classified
        here, so a new reference fails this test rather than quietly
        becoming collateral.
        """
        blocks = {
            "pathway_entitlements", "enrollments",
            "manual_member_pathway_access", "access_grant_records",
            "payment_option_grants", "access_passes",
            "payment_transactions", "purchase_intents",
            "pathway_unlock_requirements", "conversation_channels",
            "events",
        }
        # Content the Pathway owns, deleted with it. Member work held
        # *inside* this content (step_progress, step_comments,
        # exercise_responses) blocks separately — see the tests above.
        owned_content = {
            "pathway_steps", "pathway_sections", "pathway_about_blocks",
            "payment_options", "space_resource_pathways",
        }
        # Severed on purpose. ``activities`` is a feed entry that
        # carries its own URL in its payload, and ``space_resources``
        # is creator-only Library metadata — the member-facing
        # resources endpoint is retired.
        severed = {"activities", "space_resources"}

        assert blocks | owned_content | severed == _tables_referencing(
            "pathways",
        )


# ---------------------------------------------------------------------------
# 6 — Publication history, without a ``published_at`` column
# ---------------------------------------------------------------------------


class TestPublicationHistory:
    """Offerings and Series stamp ``published_at``; Pathways do not, and
    one is deliberately not being added. The question is asked of two
    records that already exist, because either can be missing from a
    Pathway that really was published — both writers swallow their own
    failures rather than fail a creator's publish."""

    def test_the_announcement_record_blocks_a_returned_to_draft_pathway(
        self, db, owned,
    ):
        from app.comms.models import CommunicationEvent
        from app.services.pathway_announcement import (
            ANNOUNCEMENT_EVENT,
            announcement_dedupe_key,
        )

        space, owner, _ = owned()
        pw = _pathway(db, space)
        # Built from the registry rather than by hand, so the row is
        # the shape ``comms.emit`` really writes.
        from app.comms.registry import category_for_topic, get_event_definition

        definition = get_event_definition(ANNOUNCEMENT_EVENT)
        db.add(CommunicationEvent(
            id=_uid("ce"),
            event_type=ANNOUNCEMENT_EVENT,
            topic_key=definition.topic,
            category_key=category_for_topic(definition.topic),
            priority_hint=definition.default_priority,
            dedupe_key=announcement_dedupe_key(pw.id, space.id),
            source_type="creator",
            source_id=owner.id,
        ))
        db.flush()

        assert pathway_deletion.was_ever_published(db, pw) is True
        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)
        assert exc.value.status_code == 409
        assert "live to members before" in exc.value.detail

    def test_the_activity_record_blocks_it_too(self, db, owned):
        """The second signal, checked independently — the announcement
        emit is wrapped in a ``try/except`` that logs and continues, so
        its absence does not mean the Pathway was never live."""
        from app.models.activity import (
            CATEGORY_OF,
            DEFAULT_PRIORITY_OF,
            Activity,
            ActivityType,
        )

        space, owner, _ = owned()
        pw = _pathway(db, space)
        kind = ActivityType.pathway_published
        db.add(Activity(
            id=_uid("act"),
            event_type=kind.value,
            category=CATEGORY_OF[kind],
            priority=DEFAULT_PRIORITY_OF[kind],
            collective_id=space.id,
            pathway_id=pw.id,
        ))
        db.flush()

        assert pathway_deletion.was_ever_published(db, pw) is True
        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)
        assert exc.value.status_code == 409

    def test_a_never_published_draft_has_no_history(self, db, owned):
        space, _owner, _ = owned()
        pw = _pathway(db, space)
        assert pathway_deletion.was_ever_published(db, pw) is False


# ---------------------------------------------------------------------------
# 7 — The conversation channel
# ---------------------------------------------------------------------------


class TestThePathwayChannel:
    def test_an_empty_channel_goes_with_the_pathway(self, db, owned):
        """``create_pathway`` provisions it at birth on request, so
        refusing on its mere existence would make every Pathway created
        with a channel undeletable — the same trap as the Payment
        Option. Leaving it behind is worse than deleting it:
        ``pathway_id`` is ``SET NULL`` and ``can_view_channel`` reads
        ``channel.pathway_id is not None``, so it would strand an empty
        row nobody can open."""
        from app.models.platform import ConversationChannel

        space, owner, _ = owned()
        pw = _pathway(db, space)
        ch = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Pathway chat",
            slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type="pathway",
            pathway_id=pw.id,
        )
        db.add(ch)
        db.flush()
        ch_id = ch.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert db.query(ConversationChannel).filter(
            ConversationChannel.id == ch_id,
        ).first() is None

    def test_a_channel_with_posts_refuses_and_keeps_them(self, db, owned):
        from app.models.platform import CommunityPost, ConversationChannel

        space, owner, learner = owned()
        pw = _pathway(db, space)
        ch = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Pathway chat",
            slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type="pathway",
            pathway_id=pw.id,
        )
        db.add(ch)
        db.flush()
        post = CommunityPost(
            id=_uid("cp"), space_id=space.id, author_id=learner.id,
            channel_id=ch.id, body="Checking in from week two.",
        )
        db.add(post)
        db.flush()
        post_id, ch_id = post.id, ch.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert db.query(CommunityPost).filter(
            CommunityPost.id == post_id,
        ).first() is not None
        assert db.query(ConversationChannel).filter(
            ConversationChannel.id == ch_id,
        ).first() is not None


# ---------------------------------------------------------------------------
# 8 — A Gathering gated on this Pathway
# ---------------------------------------------------------------------------


class TestAGatheringGatedOnThisPathway:
    def test_a_booking_requirement_refuses(self, db, owned, make_event):
        """``events.booking_required_pathway_id`` is ``SET NULL``, and
        ``gathering_booking_rules`` computes ``is_pathway_gated`` from
        ``bool(required_pathway_id)`` — so nulling it does not break the
        gate, it removes it, and the Gathering silently becomes bookable
        by any member."""
        from app.models.platform import Event

        space, owner, _ = owned()
        pw = _pathway(db, space)
        ev = make_event(space=space)
        ev.booking_access_type = "included_with_pathway"
        ev.booking_required_pathway_id = pw.id
        db.flush()
        ev_id = ev.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        kept = db.query(Event).filter(Event.id == ev_id).one()
        assert kept.booking_required_pathway_id == pw.id


# ---------------------------------------------------------------------------
# 9 — An unexpected integrity violation is a 409, not a 500
# ---------------------------------------------------------------------------


class TestAnUnexpectedIntegrityErrorIsNotA500:
    def test_a_foreign_key_the_census_missed_answers_409(
        self, db, owned, monkeypatch,
    ):
        """The backstop. FC-API-D was an ``IntegrityError`` escaping as
        a 500; the census above is what prevents it, and this is what
        happens if the census is ever wrong — which it will eventually
        be, because new foreign keys arrive without reading this module.

        Simulated by making the preflight pass while the commit fails,
        which is exactly the shape a missed FK produces.
        """
        space, owner, _ = owned()
        pw = _pathway(db, space)
        # A Collective-level Option granting this Pathway — the exact
        # reference whose RESTRICT produced FC-API-D's 500.
        shared = _option(
            db, space, None,
            status=PaymentOptionStatus.published,
            pathway_id=None,
            attaches_to_kind="space",
            attaches_to_id=space.id,
        )
        grant = _grant(db, shared, pw)
        pw_id, grant_id = pw.id, grant.id

        # Blind the preflight, leaving only the database to object.
        monkeypatch.setattr(
            pathway_deletion, "blocking_reference", lambda db, pathway: None,
        )

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=owner)

        assert exc.value.status_code == 409
        assert "Nothing has been changed" in exc.value.detail

        # The session is usable again, which is the observable half of
        # the rollback: without it the transaction stays in a failed
        # state and every later query in the same request raises
        # ``PendingRollbackError`` instead of answering.
        #
        # "The rows are still there" is deliberately NOT asserted here.
        # ``conftest.db`` wraps the whole test in one SAVEPOINT, so the
        # handler's ``db.rollback()`` discards this test's own setup
        # along with the delete — the absence of the row afterwards is
        # a fixture artefact, not behaviour. Atomicity is the database's
        # guarantee; that the handler asks for it is pinned by
        # ``test_the_endpoint_handles_integrity_errors_at_all``.
        assert db.query(Pathway).filter(Pathway.id == pw_id).count() >= 0
        assert grant_id

    def test_the_endpoint_handles_integrity_errors_at_all(self):
        """Source contract: the handler must name ``IntegrityError`` and
        answer 409. Asserted on the source because the alternative is a
        test that can only fail by crashing the suite.

        Docstrings and comments are stripped first — this codebase has
        tripped blunt ``in`` checks on its own prose more than once.
        """
        import ast
        import inspect

        src = inspect.getsource(delete_pathway)
        tree = ast.parse(src.strip())
        # Drop the function docstring, then unparse so comments are gone.
        fn = tree.body[0]
        if (
            fn.body
            and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
        ):
            fn.body = fn.body[1:]
        code = ast.unparse(fn)
        assert "IntegrityError" in code
        assert "409" in code
        assert "rollback" in code


# ---------------------------------------------------------------------------
# 10 — Permissions and cross-Collective isolation
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_another_creator_cannot_delete_it(self, db, owned, make_user):
        space, _owner, _ = owned()
        pw = _pathway(db, space)
        outsider = make_user(role="creator")
        pw_id = pw.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=outsider)

        assert exc.value.status_code in (403, 404)
        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is not None

    def test_a_learner_cannot_delete_it(self, db, owned):
        space, _owner, learner = owned()
        pw = _pathway(db, space)

        with pytest.raises(HTTPException) as exc:
            delete_pathway(space.slug, pw.slug, db=db, current_user=learner)

        assert exc.value.status_code in (403, 404)

    def test_a_pathway_in_another_collective_is_not_found(
        self, db, owned, make_space,
    ):
        """Cross-Collective isolation: the slug is resolved *within* the
        caller's Collective, so a matching slug elsewhere is a 404 and
        never somebody else's row."""
        space_a, owner_a, _ = owned()
        other_owner = make_space()  # a second Collective, different owner
        pw_elsewhere = _pathway(db, other_owner)
        pw_id = pw_elsewhere.id

        with pytest.raises(HTTPException) as exc:
            delete_pathway(
                space_a.slug, pw_elsewhere.slug, db=db, current_user=owner_a,
            )

        assert exc.value.status_code == 404
        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is not None

    def test_a_moderator_may_delete_a_draft(self, db, owned, make_user):
        """``_get_managed_space`` admits moderators, and this endpoint
        keeps that — unlike the Collective delete, which is owner-only.
        Deleting an unused draft is ordinary studio work; the records
        that matter are protected by the checks, not by the role."""
        space, _owner, _ = owned()
        mod = make_user(role="creator")
        _member(db, space, mod, role=SpaceRole.moderator)
        pw = _pathway(db, space)
        pw_id = pw.id

        delete_pathway(space.slug, pw.slug, db=db, current_user=mod)

        assert db.query(Pathway).filter(Pathway.id == pw_id).first() is None


# ---------------------------------------------------------------------------
# 11 — The Collective delete this unblocks, unchanged
# ---------------------------------------------------------------------------


class TestTheCollectiveDeleteIsUnchanged:
    """FC-API-D's reporter could not delete their test Pathway, so its
    auto-created Payment Option stayed, so the Collective delete refused
    with "1 payment option(s)" — a complete dead end. Deleting the
    Pathway now clears that option, which clears the Collective gate.

    The Collective gate itself is deliberately untouched, and these
    tests pin that: it still refuses on each record it refused on
    before, and it is still owner-only.
    """

    def test_the_dead_end_from_the_report_now_clears(self, db, make_space, make_user):
        from app.models.platform import Space

        owner = make_user(role="creator")
        space = make_space(creator=owner, status=SpaceStatus.draft)
        _member(db, space, owner, role=SpaceRole.creator)
        pw = _pathway(db, space, access_type="one_time", price_cents=5000)
        opt = _option(db, space, pw)
        _grant(db, opt, pw)
        space_id, slug = space.id, space.slug

        # Step one: the Pathway, which used to be an unhandled 500.
        delete_pathway(slug, pw.slug, db=db, current_user=owner)
        # Step two: the Collective, which used to refuse on the option.
        delete_space(slug, db=db, current_user=owner)

        assert db.query(Space).filter(Space.id == space_id).first() is None

    def test_an_entitlement_still_blocks_the_collective_delete(
        self, db, make_space, make_user,
    ):
        space = make_space(status=SpaceStatus.draft)
        owner = db.query(type(space)).filter(
            type(space).id == space.id,
        ).one().creator_id
        from app.models.user import User
        owner_user = db.query(User).filter(User.id == owner).one()
        _member(db, space, owner_user, role=SpaceRole.creator)
        pw = _pathway(db, space)
        learner = make_user()
        _entitlement(db, space, pw, learner)

        with pytest.raises(HTTPException) as exc:
            delete_space(space.slug, db=db, current_user=owner_user)

        assert exc.value.status_code == 409
        assert "pathway entitlement(s)" in exc.value.detail

    def test_the_collective_delete_is_still_owner_only(
        self, db, owned, make_user,
    ):
        space, _owner, _ = owned(status=SpaceStatus.draft)
        mod = make_user(role="creator")
        _member(db, space, mod, role=SpaceRole.moderator)

        with pytest.raises(HTTPException) as exc:
            delete_space(space.slug, db=db, current_user=mod)

        assert exc.value.status_code == 403
