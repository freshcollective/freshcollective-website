"""Has this creator published paid content inside this Collective?

``creator.routes._derived_has_paid_content`` answers a **configuration**
question, and must not be confused with the public pricing helper that
sits next to it in this codebase:

* ``spaces.pathway_pricing.min_paid_price_cents_for_space`` — what can a
  visitor buy right now, and at what headline price? Depends on member
  checkoutability, and therefore on
  ``finite_plan_member_checkout_enabled``.
* this helper — has the creator published paid content? A Collective
  whose instalment plans are not yet offered to members still contains
  paid content, and the creator has still configured it.

The distinction is load-bearing. The Creator Studio settings panel
labels this "Contains paid content inside this collective … also
detected automatically when you publish a paid pathway", and gates the
creator's own "What's included?" and "Paid separately" copy fields on
it. Deriving it from member checkoutability would make a creator's
configuration flicker in and out of existence behind a platform feature
flag they cannot see, taking their copy with it. ``TestItIsNotThePublic
PricingQuestion`` pins the two apart.

The bug this replaces: the helper scanned ``Pathway.price_cents > 0``,
which is the legacy column and is stale by design once a Pathway moves
to ``pricing_mode='payment_options'``. It was wrong in both directions
— claiming paid content for a price the creator had stopped selling at,
and denying it for a Pathway priced wholly through its published
Options. The old implementation had no test coverage at all.
"""

from __future__ import annotations

import uuid

import pytest

from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.creator.routes import _derived_has_paid_content
from app.main import app
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType


# Test Connect Instalments: 2 weekly payments of $2, $4 committed.
INSTALMENT_CENTS = 200
INSTALMENT_COUNT = 2
PLAN_TOTAL_CENTS = INSTALMENT_CENTS * INSTALMENT_COUNT   # 400
STALE_LEGACY_CENTS = 500


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(db, make_space):
    s = make_space(status="active", is_public=True, auto_grant_role=None)
    db.flush()
    return s


def _pathway(
    db, space, *, pricing_mode: str, price_cents: int | None,
    status: str = "active", access_type: str = "one_time",
    title: str = "Test Pathway",
) -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status=status,
        access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode=pricing_mode,
        price_cents=price_cents,
        currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _option(
    db, space, *,
    status: PaymentOptionStatus = PaymentOptionStatus.published,
    payment_type: PaymentOptionType = PaymentOptionType.one_time,
    calculated_total_cents: int | None = None,
    legacy_pathway_id: str | None = None,
    name: str = "Test Connect Instalments",
) -> PaymentOption:
    """A PaymentOption. ``legacy_pathway_id`` populates the deprecated
    ``pathway_id`` column; leave it None for the grants-first shape that
    most real Options have."""
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=legacy_pathway_id,
        attaches_to_kind="space",
        attaches_to_id=space.id,
        name=name,
        payment_type=payment_type,
        status=status,
        calculated_total_cents=calculated_total_cents,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _grant_pathway(db, option, pathway) -> None:
    """Link via PaymentOptionGrant — the grants-first association."""
    db.add(PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=option.id,
        grant_kind="pathway",
        pathway_id=pathway.id,
    ))
    db.flush()


def _finite_schedule(
    db, option, *,
    status: str = "published",
    instalment_cents: int = INSTALMENT_CENTS,
    count: int = INSTALMENT_COUNT,
) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=option.id,
        name=f"{count} weekly payments",
        schedule_type="recurring_installments",
        status=status,
        total_amount_cents=instalment_cents * count,
        installment_amount_cents=instalment_cents,
        installment_count=count,
        interval="weekly",
        stripe_interval="week",
        stripe_interval_count=1,
        currency="AUD",
        position=0,
    )
    db.add(s)
    db.flush()
    return s


def _pay_in_full_schedule(
    db, option, *, cents: int, status: str = "published",
) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=option.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status=status,
        total_amount_cents=cents,
        currency="AUD",
        position=0,
    )
    db.add(s)
    db.flush()
    return s


def _derived(db, space) -> bool:
    return _derived_has_paid_content(space.id, db)


@pytest.fixture
def plans_not_offered_to_members(monkeypatch):
    """The production default: ``finite_plan_member_checkout_enabled``
    is False, so no member can check out an instalment plan today."""
    from app.core.config import settings
    monkeypatch.setattr(
        settings, "finite_plan_member_checkout_enabled", False,
    )


@pytest.fixture
def plans_offered_to_members(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(
        settings, "finite_plan_member_checkout_enabled", True,
    )


# ---------------------------------------------------------------------------
# 1 + 2 — the reported shape, and its independence from the feature flag
# ---------------------------------------------------------------------------


class TestAPathwayPricedByItsOptions:
    def test_published_finite_option_counts_as_paid_content(
        self, db, space, plans_offered_to_members,
    ):
        """``price_cents=NULL`` — the normal state after a clean switch
        — plus a published 2 x $2 plan. The old rule said False and took
        the creator's copy fields with it."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        assert _derived(db, space) is True

    def test_it_is_still_true_with_member_plan_checkout_disabled(
        self, db, space, plans_not_offered_to_members,
    ):
        """The point of keeping this helper separate. The creator has
        published paid content; whether a member can buy it today is a
        different question, asked elsewhere."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        assert _derived(db, space) is True

    def test_the_flag_makes_no_difference_either_way(self, db, space):
        """Asserted as an equivalence rather than two separate cases, so
        a future dependency on the flag cannot slip in unnoticed."""
        from app.core.config import settings

        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        original = settings.finite_plan_member_checkout_enabled
        try:
            results = []
            for enabled in (True, False):
                settings.finite_plan_member_checkout_enabled = enabled
                results.append(_derived(db, space))
        finally:
            settings.finite_plan_member_checkout_enabled = original

        assert results == [True, True], results

    def test_a_structurally_invalid_plan_still_counts(
        self, db, space, plans_offered_to_members,
    ):
        """Schedule *shape* is not this helper's business. A plan whose
        total disagrees with per-instalment x count would be refused at
        checkout, but the creator has still published paid content and
        still needs their copy fields."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        schedule = _finite_schedule(db, option)
        schedule.total_amount_cents = 999          # != 200 x 2
        db.flush()

        assert _derived(db, space) is True

    def test_an_option_priced_on_its_own_columns_counts(self, db, space):
        """The other half of "genuinely paid": no schedules, but a
        positive ``calculated_total_cents``."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space, calculated_total_cents=2500)
        _grant_pathway(db, option, pathway)

        assert _derived(db, space) is True

    def test_the_stale_legacy_column_is_not_what_answers(self, db, space):
        """A payment-options Pathway carrying 500 with no published
        Option at all. The old rule claimed paid content here, for a
        price the creator had stopped selling at."""
        _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )

        assert _derived(db, space) is False


# ---------------------------------------------------------------------------
# 3 + 4 — unpublished and free Options do not count
# ---------------------------------------------------------------------------


class TestNothingPublishedAndNothingPaid:
    def test_a_draft_option_only_is_not_published_paid_content(
        self, db, space, plans_offered_to_members,
    ):
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        option = _option(db, space, status=PaymentOptionStatus.draft)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        assert _derived(db, space) is False

    def test_an_archived_option_only_does_not_count(self, db, space):
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(
            db, space,
            status=PaymentOptionStatus.archived,
            calculated_total_cents=2500,
        )
        _grant_pathway(db, option, pathway)

        assert _derived(db, space) is False

    def test_a_free_published_option_only_does_not_count(self, db, space):
        """``payment_type='free'`` with no price anywhere."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(
            db, space,
            payment_type=PaymentOptionType.free,
            name="Free Option",
        )
        _grant_pathway(db, option, pathway)
        _pay_in_full_schedule(db, option, cents=0)

        assert _derived(db, space) is False

    def test_a_free_option_is_refused_even_if_a_price_lingers(
        self, db, space,
    ):
        """Belt and braces on "genuinely free": the type is checked as
        well as the amounts, so a free Option with a stray total left on
        it does not read as paid content."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(
            db, space,
            payment_type=PaymentOptionType.free,
            calculated_total_cents=2500,
            name="Free Option",
        )
        _grant_pathway(db, option, pathway)

        assert _derived(db, space) is False

    def test_a_zero_priced_schedule_does_not_count(self, db, space):
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        _pay_in_full_schedule(db, option, cents=0)

        assert _derived(db, space) is False

    def test_an_option_with_no_price_configured_at_all_does_not_count(
        self, db, space,
    ):
        """Published, paid type, but nothing priced: no schedules and
        both authoring columns NULL. Not free — unfinished. It must not
        read as published paid content, because there is no paid content
        to describe yet."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space, calculated_total_cents=None)
        _grant_pathway(db, option, pathway)

        assert _derived(db, space) is False

    def test_a_draft_schedule_on_a_published_option_does_not_count(
        self, db, space,
    ):
        """The Option is published but its only price is on an
        unpublished schedule, so no price has been published."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option, status="draft")

        assert _derived(db, space) is False

    def test_a_draft_pathway_does_not_count(self, db, space):
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            status="draft",
        )
        option = _option(db, space, calculated_total_cents=2500)
        _grant_pathway(db, option, pathway)

        assert _derived(db, space) is False

    def test_an_archived_pathway_does_not_count(self, db, space):
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            status="archived",
        )
        option = _option(db, space, calculated_total_cents=2500)
        _grant_pathway(db, option, pathway)

        assert _derived(db, space) is False

    def test_a_collective_with_nothing_in_it(self, db, space):
        assert _derived(db, space) is False


# ---------------------------------------------------------------------------
# 5 — legacy Pathways unchanged
# ---------------------------------------------------------------------------


class TestLegacyPathwaysAreUnchanged:
    def test_a_legacy_paid_pathway_counts(self, db, space):
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)

        assert _derived(db, space) is True

    def test_a_legacy_pathway_needs_a_paid_access_type(self, db, space):
        """Unchanged: a 'free' access type is not paid content even with
        a price sitting on the row."""
        _pathway(
            db, space, pricing_mode="legacy", price_cents=1800,
            access_type="free",
        )

        assert _derived(db, space) is False

    def test_a_legacy_pathway_with_no_price_does_not_count(self, db, space):
        _pathway(db, space, pricing_mode="legacy", price_cents=None)

        assert _derived(db, space) is False

    def test_a_zero_priced_legacy_pathway_does_not_count(self, db, space):
        _pathway(db, space, pricing_mode="legacy", price_cents=0)

        assert _derived(db, space) is False

    def test_a_draft_legacy_pathway_does_not_count(self, db, space):
        _pathway(
            db, space, pricing_mode="legacy", price_cents=1800,
            status="draft",
        )

        assert _derived(db, space) is False

    def test_a_subscription_pathway_counts(self, db, space):
        _pathway(
            db, space, pricing_mode="legacy", price_cents=1800,
            access_type="subscription",
        )

        assert _derived(db, space) is True

    def test_either_mode_is_enough(self, db, space):
        """One of each, where only the legacy one is paid."""
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)
        _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            title="Unpriced Options Pathway",
        )

        assert _derived(db, space) is True


# ---------------------------------------------------------------------------
# 6 — grants-first Options
# ---------------------------------------------------------------------------


class TestGrantsFirstOptionsAreFound:
    def test_a_grants_first_option_with_no_legacy_link_counts(
        self, db, space, plans_offered_to_members,
    ):
        """Most real Options are grants-first: ``pathway_id`` is NULL and
        the association lives in ``payment_option_grants``. Reading the
        column alone would be a blind spot, which is why the join goes
        through ``pathway_option_pairs()``."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space, legacy_pathway_id=None)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        assert option.pathway_id is None          # the premise
        assert _derived(db, space) is True

    def test_a_legacy_linked_option_with_no_grant_row_counts(
        self, db, space, plans_offered_to_members,
    ):
        """The other arm of the union, for Options predating grants."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space, legacy_pathway_id=pathway.id)
        _finite_schedule(db, option)

        grants = (
            db.query(PaymentOptionGrant)
            .filter(PaymentOptionGrant.payment_option_id == option.id)
            .all()
        )
        assert grants == []                        # the premise
        assert _derived(db, space) is True

    def test_an_option_granting_a_pathway_in_another_collective(
        self, db, space, make_space, plans_offered_to_members,
    ):
        """Scoping: the Option must reach a Pathway in *this* space."""
        other = make_space(status="active", is_public=True, auto_grant_role=None)
        db.flush()
        other_pathway = _pathway(
            db, other, pricing_mode="payment_options", price_cents=None,
            title="Other Collective Pathway",
        )
        _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, other)
        _grant_pathway(db, option, other_pathway)
        _finite_schedule(db, option)

        assert _derived(db, space) is False
        assert _derived(db, other) is True


# ---------------------------------------------------------------------------
# The two helpers answer different questions, on purpose
# ---------------------------------------------------------------------------


class TestItIsNotThePublicPricingQuestion:
    def test_they_disagree_when_plans_are_not_offered_to_members(
        self, db, space, plans_not_offered_to_members,
    ):
        """The case that forced them apart. The creator has published a
        paid plan; no member can buy it while the flag is off. Both
        answers are correct for their own question, and collapsing them
        would blank the creator's copy fields behind a flag they cannot
        see."""
        from app.spaces import pathway_pricing

        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        assert _derived(db, space) is True
        assert pathway_pricing.min_paid_price_cents_for_space(
            db, space.id,
        ) is None

    def test_they_agree_once_plans_are_offered(
        self, db, space, plans_offered_to_members,
    ):
        """Not an arbitrary divergence: with the flag on, the published
        plan is both configured and buyable."""
        from app.spaces import pathway_pricing

        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        assert _derived(db, space) is True
        assert pathway_pricing.min_paid_price_cents_for_space(
            db, space.id,
        ) == PLAN_TOTAL_CENTS

    def test_they_agree_on_a_legacy_collective(self, db, space):
        from app.spaces import pathway_pricing

        _pathway(db, space, pricing_mode="legacy", price_cents=1800)

        assert _derived(db, space) is True
        assert pathway_pricing.min_paid_price_cents_for_space(
            db, space.id,
        ) == 1800

    def test_they_agree_that_a_draft_option_is_nothing(
        self, db, space, plans_offered_to_members,
    ):
        from app.spaces import pathway_pricing

        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, space, status=PaymentOptionStatus.draft)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        assert _derived(db, space) is False
        assert pathway_pricing.min_paid_price_cents_for_space(
            db, space.id,
        ) is None


# ---------------------------------------------------------------------------
# The surface the creator actually sees
# ---------------------------------------------------------------------------


@pytest.fixture
def creator_client(db, make_user, make_space):
    """``GET /api/creator/spaces/{slug}`` as the Collective's owner."""
    creator = make_user(role="creator")
    owned = make_space(creator=creator, status="active", is_public=True,
                       auto_grant_role=None)
    db.flush()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_creator_user] = lambda: creator
    yield TestClient(app, follow_redirects=False), owned
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


class TestTheCreatorStudioPayload:
    """The helper is private, so these drive the endpoint that gates the
    "What's included?" and "Paid separately" fields in the settings
    panel. Without them the fix is only proven one call short of the
    thing the creator sees."""

    def test_the_settings_payload_reports_paid_content(
        self, db, creator_client, plans_not_offered_to_members,
    ):
        client, owned = creator_client
        pathway = _pathway(
            db, owned, pricing_mode="payment_options", price_cents=None,
        )
        option = _option(db, owned)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        res = client.get(f"/api/creator/spaces/{owned.slug}")

        assert res.status_code == 200, res.text
        assert res.json()["derived_has_paid_internal_content"] is True

    def test_the_settings_payload_reports_none_for_a_draft_option(
        self, db, creator_client, plans_offered_to_members,
    ):
        client, owned = creator_client
        pathway = _pathway(
            db, owned,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        option = _option(db, owned, status=PaymentOptionStatus.draft)
        _grant_pathway(db, option, pathway)
        _finite_schedule(db, option)

        res = client.get(f"/api/creator/spaces/{owned.slug}")

        assert res.status_code == 200, res.text
        assert res.json()["derived_has_paid_internal_content"] is False

    def test_the_settings_payload_still_reports_a_legacy_pathway(
        self, db, creator_client,
    ):
        client, owned = creator_client
        _pathway(db, owned, pricing_mode="legacy", price_cents=1800)

        res = client.get(f"/api/creator/spaces/{owned.slug}")

        assert res.status_code == 200, res.text
        assert res.json()["derived_has_paid_internal_content"] is True
