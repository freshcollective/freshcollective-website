"""The pilot allow-list: who may use Offerings, and who may not see it.

Offerings goes to production as a **scoped pilot**. Two switches must
both say yes: ``OFFERINGS_ENABLED`` (does the feature exist) and
``OFFERINGS_PILOT_COLLECTIVES`` (in which Collectives). This file is
the regression coverage for the second one.

Everything here is asserted from the point of view of two Collectives
at once — one inside the pilot, one outside — because the property that
matters is not "the pilot Collective works" but **"the other one is
indistinguishable from the feature being switched off"**. A test that
only looked at the pilot Collective would pass with no allow-list at
all.

The three rules worth stating before the tests
----------------------------------------------

**Empty means nothing, not everything.** A cleared value turns a
controlled pilot off rather than into a public launch. An allow-list
that fails open is how a pilot becomes an incident.

**Downloads are never pilot-gated.** A Collective leaving the pilot
must not reach into what somebody already acquired, for exactly the
reason the feature flag does not reach into it either.

**Your Collection is gated on ownership, not on scope.** Filtering it
by the allow-list would hide a member's own purchase the moment its
Collective left the pilot. So the rule is "do you own anything", which
cannot drift out of step with the list and cannot hide a legitimate
acquisition.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.creator import _offering_routes as creator_api
from app.creator.schemas_offerings import OfferingCreateRequest
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
from app.models.user import User
from app.services import offering_acquisition as acq
from app.services import offering_covers as covers
from app.services import offering_pilot as pilot
from app.spaces import _offering_member_routes as member_api
from app.spaces import area_access, area_policies


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


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


def _own(db, user, offering, space) -> OfferingEntitlement:
    e = OfferingEntitlement(
        id=_uid("oe"), user_id=user.id, offering_id=offering.id,
        space_id=space.id,
        source=OfferingEntitlementSource.free.value,
        status=OfferingEntitlementStatus.active.value,
        acquired_at=datetime.utcnow(),
    )
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def two_collectives(db, make_space):
    """One Collective in the pilot, one outside it, each with a
    published free Offering ready to acquire."""
    inside = make_space()
    outside = make_space()
    a = _offering(db, inside)
    b = _offering(db, outside)
    _file(db, a)
    _file(db, b)
    return inside, outside, a, b


# ---------------------------------------------------------------------------
# Parsing — the config surface an operator actually touches
# ---------------------------------------------------------------------------


class TestTheAllowListParses:

    def test_a_single_slug(self):
        s = pilot._parse("moonlit-circle")
        assert s.admits(slug="moonlit-circle", space_id=None)
        assert not s.admits(slug="somewhere-else", space_id=None)

    def test_several_separated_by_commas(self):
        s = pilot._parse("moonlit-circle,embody,the-grove")
        for slug in ("moonlit-circle", "embody", "the-grove"):
            assert s.admits(slug=slug, space_id=None), slug
        assert not s.admits(slug="nourish", space_id=None)

    def test_whitespace_and_case_are_forgiven(self):
        """The value is typed by hand into a Render field."""
        s = pilot._parse("  Moonlit-Circle ,  EMBODY  ")
        assert s.admits(slug="moonlit-circle", space_id=None)
        assert s.admits(slug="embody", space_id=None)

    def test_an_id_matches_as_well_as_a_slug(self):
        """A slug is mutable — ``creator.routes`` lets an owner change
        it — so an operator who wants the entry to survive a rename can
        use the id instead.

        A generated uuid rather than a real Collective's: the mechanism
        is what is under test, and an earlier version of this file
        embedded an id that turned out to be from a stale database copy.
        A literal identifier in a test goes out of date silently.
        """
        space_id = str(uuid.uuid4())
        s = pilot._parse(space_id)
        assert s.admits(slug=None, space_id=space_id)
        assert s.admits(slug="anything", space_id=space_id)

    def test_a_uuid_id_matches_whatever_case_it_was_typed_in(self):
        """Postgres hands back lower-case uuids; an operator pasting one
        from a console may not. Tokens are lower-cased on parse, so both
        forms match the stored value."""
        space_id = str(uuid.uuid4())
        for typed in (space_id, space_id.upper(), f"  {space_id}  "):
            assert pilot._parse(typed).admits(
                slug=None, space_id=space_id,
            ), typed

    def test_slugs_and_ids_can_be_mixed_in_one_list(self):
        space_id = str(uuid.uuid4())
        s = pilot._parse(f"moonlit-circle, {space_id}")
        assert s.admits(slug="moonlit-circle", space_id="other")
        assert s.admits(slug="other", space_id=space_id)

    def test_a_wrong_id_admits_nothing_rather_than_the_wrong_collective(self):
        """The failure mode that matters if an identifier is mistyped or
        taken from the wrong database: the pilot closes. It does not
        open somewhere unintended."""
        intended, mistyped = str(uuid.uuid4()), str(uuid.uuid4())
        s = pilot._parse(mistyped)
        assert not s.admits(slug="moonlit-circle", space_id=intended)
        assert not s.admits(slug="anything-else", space_id="any-other-id")

    def test_star_opens_it_to_everything(self):
        s = pilot._parse("*")
        assert s.allow_all
        assert not s.is_restricted
        assert s.admits(slug="literally-anything", space_id=None)

    def test_empty_admits_NOTHING(self):
        """The decision this whole module turns on.

        A cleared value must turn the pilot off, not into a public
        launch. An operator mistake, or a blueprint sync overwriting a
        Dashboard entry — which has happened on this platform twice —
        would otherwise launch a commerce feature by accident.
        """
        for raw in ("", "   ", ",", " , , "):
            s = pilot._parse(raw)
            assert s.is_closed, repr(raw)
            assert not s.admits(slug="moonlit-circle", space_id="anything")

    def test_a_star_among_slugs_still_opens_everything(self):
        """Explicit beats partial — if somebody wrote ``*`` they meant
        it, and silently honouring only the slugs beside it would be a
        surprising half-measure."""
        assert pilot._parse("moonlit-circle,*").allow_all


class TestBothSwitchesAreRequired:

    def test_flag_off_means_nothing_however_open_the_pilot(
        self, db, make_space, monkeypatch,
    ):
        from app.core.config import settings
        space = make_space()
        monkeypatch.setattr(settings, "offerings_enabled", False)
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "*")
        assert pilot.offerings_available_for(space) is False

    def test_pilot_closed_means_nothing_however_on_the_flag(
        self, db, make_space, monkeypatch,
    ):
        from app.core.config import settings
        space = make_space()
        monkeypatch.setattr(settings, "offerings_enabled", True)
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "")
        assert pilot.offerings_available_for(space) is False

    def test_both_on_and_named_means_yes(
        self, db, make_space, offerings_pilot,
    ):
        space = make_space()
        offerings_pilot(space.slug)
        assert pilot.offerings_available_for(space) is True

    def test_describe_reports_each_state_for_an_operator(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "offerings_enabled", False)
        assert "disabled" in pilot.describe()
        monkeypatch.setattr(settings, "offerings_enabled", True)
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "")
        assert "NO Collective" in pilot.describe()
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "moonlit-circle")
        assert "moonlit-circle" in pilot.describe()
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "*")
        assert "ALL" in pilot.describe()


# ---------------------------------------------------------------------------
# Creator management and publishing
# ---------------------------------------------------------------------------


class TestCreatorSurfaces:

    def _owner(self, db, space) -> User:
        return db.query(User).filter(User.id == space.creator_id).one()

    def test_a_pilot_creator_can_list_and_create(
        self, db, two_collectives, offerings_pilot,
    ):
        inside, _outside, _a, _b = two_collectives
        offerings_pilot(inside.slug)
        owner = self._owner(db, inside)
        assert creator_api.list_offerings(
            inside.slug, db=db, current_user=owner,
        ) is not None
        created = creator_api.create_offering(
            inside.slug, OfferingCreateRequest(title="New thing"),
            db=db, current_user=owner,
        )
        assert created["status"] == OfferingStatus.draft.value

    def test_a_non_pilot_creator_is_refused_everything(
        self, db, two_collectives, offerings_pilot,
    ):
        """Their own Collective, their own ownership — and Offerings
        simply does not exist for them."""
        inside, outside, _a, b = two_collectives
        offerings_pilot(inside.slug)
        owner = self._owner(db, outside)

        for label, call in (
            ("list", lambda: creator_api.list_offerings(
                outside.slug, db=db, current_user=owner)),
            ("create", lambda: creator_api.create_offering(
                outside.slug, OfferingCreateRequest(title="x"),
                db=db, current_user=owner)),
            ("get", lambda: creator_api.get_offering(
                outside.slug, b.slug, db=db, current_user=owner)),
            ("readiness", lambda: creator_api.get_offering_readiness(
                outside.slug, b.slug, db=db, current_user=owner)),
            ("publish", lambda: creator_api.publish_offering(
                outside.slug, b.slug, db=db, current_user=owner)),
            ("retire", lambda: creator_api.retire_offering(
                outside.slug, b.slug, db=db, current_user=owner)),
        ):
            with pytest.raises(HTTPException) as e:
                call()
            assert e.value.status_code == 404, label

    def test_the_refusal_does_not_name_the_feature(
        self, db, two_collectives, offerings_pilot,
    ):
        """A creator outside the pilot must not learn that Offerings
        exists and that they are excluded from it."""
        inside, outside, _a, _b = two_collectives
        offerings_pilot(inside.slug)
        owner = self._owner(db, outside)
        with pytest.raises(HTTPException) as e:
            creator_api.list_offerings(outside.slug, db=db, current_user=owner)
        detail = str(e.value.detail).lower()
        assert "offering" not in detail
        assert "pilot" not in detail

    def test_every_creator_handler_refuses_a_non_pilot_collective(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """Behavioural sweep over every creator handler that names a
        Collective — including the About-block ones, which resolve
        through a module-level ``_resolve`` helper rather than calling
        ``_get_owned_space`` directly.

        An earlier version of this test read the source for a direct
        call and reported those five as uncovered. They are covered;
        the heuristic was one level too shallow. Calling them is the
        answer that cannot be wrong about indirection.
        """
        from app.creator import _offering_about_routes as about_api
        from app.creator import _offering_file_routes as files_api
        from app.creator.schemas import (
            AboutBlockCreateRequest, AboutBlockReorderRequest,
        )
        from app.creator.schemas_offerings import OfferingUpdateRequest

        inside, outside, _a, b = two_collectives
        offerings_pilot(inside.slug)
        owner = self._owner(db, outside)

        calls = {
            # Offering management
            "list_offerings": lambda: creator_api.list_offerings(
                outside.slug, db=db, current_user=owner),
            "create_offering": lambda: creator_api.create_offering(
                outside.slug, OfferingCreateRequest(title="x"),
                db=db, current_user=owner),
            "get_offering": lambda: creator_api.get_offering(
                outside.slug, b.slug, db=db, current_user=owner),
            "update_offering": lambda: creator_api.update_offering(
                outside.slug, b.slug, OfferingUpdateRequest(summary="x"),
                db=db, current_user=owner),
            "get_offering_readiness": lambda: creator_api.get_offering_readiness(
                outside.slug, b.slug, db=db, current_user=owner),
            "publish_offering": lambda: creator_api.publish_offering(
                outside.slug, b.slug, db=db, current_user=owner),
            "retire_offering": lambda: creator_api.retire_offering(
                outside.slug, b.slug, db=db, current_user=owner),
            # Files
            "list_offering_files": lambda: files_api.list_offering_files(
                slug=outside.slug, offering_slug=b.slug,
                db=db, current_user=owner),
            # About blocks — via ``_resolve``
            "list_offering_about_blocks": lambda: about_api.list_offering_about_blocks(
                slug=outside.slug, offering_slug=b.slug,
                db=db, current_user=owner),
            "create_offering_about_block": lambda: about_api.create_offering_about_block(
                slug=outside.slug, offering_slug=b.slug,
                body=AboutBlockCreateRequest(block_type="text", content="x"),
                db=db, current_user=owner),
            "reorder_offering_about_blocks": lambda: about_api.reorder_offering_about_blocks(
                slug=outside.slug, offering_slug=b.slug,
                body=AboutBlockReorderRequest(ids=[]),
                db=db, current_user=owner),
        }
        refused, allowed = [], []
        for name, call in calls.items():
            try:
                call()
                allowed.append(name)
            except HTTPException as exc:
                (refused if exc.status_code == 404 else allowed).append(
                    name if exc.status_code == 404 else f"{name}({exc.status_code})"
                )
        assert allowed == [], (
            "handler(s) reachable for a Collective outside the pilot: "
            + ", ".join(allowed)
        )
        assert len(refused) >= 11, refused

    def test_the_about_handlers_resolve_through_the_guarded_helper(self):
        """A source guard for the indirection the test above relies on.

        The five About handlers are covered because ``_resolve`` calls
        ``_get_owned_space``. If that helper ever stopped doing so, the
        behavioural test above would still fail — but this says *why*
        in one line rather than as five mysterious 200s.
        """
        import inspect
        import re
        from app.creator import _offering_about_routes as about_api
        src = re.sub(r"(?m)^\s*#.*$", "", inspect.getsource(about_api._resolve))
        assert "_get_owned_space" in src


# ---------------------------------------------------------------------------
# Public discovery
# ---------------------------------------------------------------------------


class TestPublicDiscovery:

    def test_the_pilot_collective_is_browsable_anonymously(
        self, db, two_collectives, offerings_pilot,
    ):
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        cards = member_api.list_member_offerings(
            inside.slug, db=db, current_user=None,
        )
        assert [c["slug"] for c in cards] == [a.slug]

    def test_a_non_pilot_collective_404s_its_catalogue(
        self, db, two_collectives, offerings_pilot,
    ):
        inside, outside, _a, _b = two_collectives
        offerings_pilot(inside.slug)
        with pytest.raises(HTTPException) as e:
            member_api.list_member_offerings(
                outside.slug, db=db, current_user=None,
            )
        assert e.value.status_code == 404

    def test_a_non_pilot_offering_detail_page_404s(
        self, db, two_collectives, offerings_pilot,
    ):
        inside, outside, _a, b = two_collectives
        offerings_pilot(inside.slug)
        with pytest.raises(HTTPException) as e:
            member_api.get_member_offering(
                outside.slug, b.slug, db=db, current_user=None,
            )
        assert e.value.status_code == 404

    def test_the_offerings_tab_appears_only_for_the_pilot_collective(
        self, db, two_collectives, offerings_pilot,
    ):
        """``area_access`` is what the tab bar, the Collective Home and
        both member routes all read, so this one assertion covers every
        presentation surface at once."""
        inside, outside, _a, _b = two_collectives
        offerings_pilot(inside.slug)
        in_areas = area_access.resolve_area_access(db, inside, None)
        out_areas = area_access.resolve_area_access(db, outside, None)
        assert in_areas.can_reach(area_policies.AREA_OFFERINGS)
        assert not out_areas.can_reach(area_policies.AREA_OFFERINGS)

    def test_the_pilot_changes_nothing_else_about_reachable_areas(
        self, db, two_collectives, offerings_pilot,
    ):
        """The one difference between a pilot and a non-pilot Collective
        must be Offerings. Anything else would mean the allow-list had
        reached into unrelated access control."""
        inside, outside, _a, _b = two_collectives
        offerings_pilot(inside.slug)
        in_set = set(area_access.resolve_area_access(db, inside, None).reachable)
        out_set = set(area_access.resolve_area_access(db, outside, None).reachable)
        assert in_set - out_set == {area_policies.AREA_OFFERINGS}
        assert out_set - in_set == set()

    def test_matching_by_id_works_through_the_whole_stack(
        self, db, two_collectives, offerings_pilot,
    ):
        """Not just the parser — the id form has to reach the surfaces."""
        inside, outside, a, _b = two_collectives
        offerings_pilot(inside.id)
        cards = member_api.list_member_offerings(
            inside.slug, db=db, current_user=None,
        )
        assert [c["slug"] for c in cards] == [a.slug]
        with pytest.raises(HTTPException):
            member_api.list_member_offerings(
                outside.slug, db=db, current_user=None,
            )

    def test_a_renamed_pilot_collective_still_matches_by_id(
        self, db, two_collectives, offerings_pilot,
    ):
        """The reason ids are accepted at all. A creator renaming their
        Collective must not silently switch the pilot off."""
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.id)
        inside.slug = f"renamed-{uuid.uuid4().hex[:8]}"
        db.flush()
        cards = member_api.list_member_offerings(
            inside.slug, db=db, current_user=None,
        )
        assert [c["slug"] for c in cards] == [a.slug]

    def test_a_renamed_pilot_collective_falls_out_if_listed_by_slug(
        self, db, two_collectives, offerings_pilot,
    ):
        """The documented consequence of the slug form, asserted so it
        is a known property rather than a surprise."""
        inside, _outside, _a, _b = two_collectives
        offerings_pilot(inside.slug)
        inside.slug = f"renamed-{uuid.uuid4().hex[:8]}"
        db.flush()
        with pytest.raises(HTTPException) as e:
            member_api.list_member_offerings(
                inside.slug, db=db, current_user=None,
            )
        assert e.value.status_code == 404


# ---------------------------------------------------------------------------
# Acquisition — free and paid
# ---------------------------------------------------------------------------


class TestFreeAcquisition:

    def test_a_pilot_offering_can_be_acquired(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        out = member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=make_user(),
        )
        assert out["acquired"] is True

    def test_a_non_pilot_offering_cannot_be_acquired(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        inside, outside, _a, b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        with pytest.raises(HTTPException) as e:
            member_api.acquire_offering(
                outside.slug, b.slug, db=db, current_user=taker,
            )
        assert e.value.status_code == 404
        assert db.query(OfferingEntitlement).filter(
            OfferingEntitlement.user_id == taker.id,
        ).all() == []

    def test_the_gate_refuses_in_the_service_too_not_only_the_route(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """Defence in depth. ``check_acquirable`` is what all three
        write paths guard with, so the rule has to hold there and not
        only at the one route that also calls ``require_area``."""
        inside, outside, _a, b = two_collectives
        offerings_pilot(inside.slug)
        result = acq.check_acquirable(
            db, offering=b, space=outside, user=make_user(),
        )
        assert result.can_acquire is False
        assert result.refusal == acq.REASON_OUTSIDE_PILOT

    def test_the_refusal_prose_does_not_reveal_the_pilot(self):
        assert "pilot" not in acq._MESSAGES[acq.REASON_OUTSIDE_PILOT].lower()
        assert "allow" not in acq._MESSAGES[acq.REASON_OUTSIDE_PILOT].lower()


class TestPaidCheckout:

    def test_checkout_is_refused_for_a_non_pilot_collective(
        self, db, two_collectives, offerings_pilot, make_user, monkeypatch,
    ):
        from app.checkout.routes import create_offering_checkout_session
        from app.checkout.schemas import OfferingCheckoutRequest
        from app.core.config import settings
        from app.services import offering_commerce
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")

        inside, outside, _a, b = two_collectives
        # Make the outside Offering genuinely sellable, so the only
        # thing standing in the way is the pilot.
        b.pricing_kind = OfferingPricingKind.one_time.value
        b.price_cents = 2400
        db.flush()
        offering_commerce.sync(db, offering=b, space=outside)
        db.flush()
        offerings_pilot(inside.slug)

        from unittest.mock import patch
        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                create_offering_checkout_session(
                    OfferingCheckoutRequest(
                        space_slug=outside.slug, offering_slug=b.slug,
                        success_url="https://ok/s", cancel_url="https://ok/c",
                    ),
                    current_user=make_user(), db=db,
                )
        assert e.value.status_code == 404
        assert m.call_count == 0, "Stripe must not be contacted"

    def test_the_unified_endpoint_also_refuses_a_non_pilot_offering(
        self, db, two_collectives, offerings_pilot, make_user, monkeypatch,
    ):
        """The other door. ``POST /api/checkout`` takes an option id and
        reaches ``guard_option_purchase``, which must apply the pilot
        rule too."""
        from app.checkout.routes import create_unified_checkout_session
        from app.checkout.schemas import UnifiedCheckoutRequest
        from app.core.config import settings
        from app.services import offering_commerce
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")

        inside, outside, _a, b = two_collectives
        b.pricing_kind = OfferingPricingKind.one_time.value
        b.price_cents = 2400
        db.flush()
        offering_commerce.sync(db, offering=b, space=outside)
        db.flush()
        option = offering_commerce.find_option(db, b)
        schedule = offering_commerce.pay_in_full_schedule(db, option)
        offerings_pilot(inside.slug)

        from unittest.mock import patch
        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                create_unified_checkout_session(
                    UnifiedCheckoutRequest(
                        payment_option_id=option.id,
                        payment_option_schedule_id=schedule.id,
                        success_url="https://ok/s", cancel_url="https://ok/c",
                    ),
                    current_user=make_user(), db=db,
                )
        assert e.value.status_code == 409
        assert e.value.detail["reason"] == acq.REASON_OUTSIDE_PILOT
        assert m.call_count == 0

    def test_a_pathway_purchase_is_untouched_by_the_pilot(
        self, db, make_space, make_user, offerings_pilot, monkeypatch,
    ):
        """The regression that matters most: the pilot must be invisible
        to every non-Offering purchase, whatever the allow-list says."""
        from unittest.mock import patch
        from types import SimpleNamespace
        from app.checkout.routes import create_unified_checkout_session
        from app.checkout.schemas import UnifiedCheckoutRequest
        from app.core.config import settings
        from app.models.payment_option import PaymentOption, PaymentOptionType
        from app.models.payment_option_grant import (
            GRANT_KIND_PATHWAY, PaymentOptionGrant,
        )
        from app.models.payment_option_schedule import PaymentOptionSchedule
        from app.models.platform import Pathway, PathwayType
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")

        space = make_space()
        # An allow-list that excludes this Collective entirely.
        offerings_pilot("some-other-collective")

        pw = Pathway(
            id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="Practice", status="active", access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw)
        option = PaymentOption(
            id=_uid("po"), space_id=space.id, attaches_to_kind="pathway",
            attaches_to_id=pw.id, name="Full access",
            payment_type=PaymentOptionType.one_time, status="published",
            currency="AUD", override_total_cents=5000,
        )
        db.add(option)
        db.flush()
        db.add(PaymentOptionGrant(
            id=_uid("pog"), payment_option_id=option.id,
            grant_kind=GRANT_KIND_PATHWAY, pathway_id=pw.id, position=0,
        ))
        schedule = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=option.id, name="Pay in full",
            schedule_type="pay_in_full", status="published",
            total_amount_cents=5000, currency="AUD",
        )
        db.add(schedule)
        db.flush()
        db.refresh(option)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = SimpleNamespace(
                id="cs_pathway_pilot", url="https://checkout.stripe.test/x",
            )
            res = create_unified_checkout_session(
                UnifiedCheckoutRequest(
                    payment_option_id=option.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://ok/s", cancel_url="https://ok/c",
                ),
                current_user=make_user(), db=db,
            )
        assert res.checkout_url == "https://checkout.stripe.test/x"
        assert m.call_count == 1


# ---------------------------------------------------------------------------
# Your Collection, and what the pilot must never take away
# ---------------------------------------------------------------------------


class TestYourCollection:

    def test_a_member_with_nothing_cannot_see_it_during_the_pilot(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """So Your World does not grow a Your Collection band for every
        account on the platform while the feature is still a trial."""
        inside, _outside, _a, _b = two_collectives
        offerings_pilot(inside.slug)
        with pytest.raises(HTTPException) as e:
            member_api.get_your_collection(db=db, current_user=make_user())
        assert e.value.status_code == 404

    def test_a_member_who_acquired_something_sees_it(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 1
        assert out["items"][0]["slug"] == a.slug

    def test_a_purchase_is_never_hidden_when_its_collective_leaves_the_pilot(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """The reason Your Collection is gated on ownership rather than
        on scope. Filtering by the allow-list would make a member's own
        acquisition disappear the moment an operator edited a config
        value — which is precisely what the download route and the
        feature flag both refuse to do."""
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )

        # The Collective is removed from the pilot afterwards.
        offerings_pilot("somewhere-else-entirely")

        out = member_api.get_your_collection(db=db, current_user=taker)
        assert out["count"] == 1, "their own purchase must still be listed"
        assert out["items"][0]["slug"] == a.slug

    def test_an_empty_collection_is_visible_once_the_pilot_opens_to_all(
        self, db, make_user, offerings_pilot,
    ):
        """After the pilot, an empty Collection is a legitimate state and
        renders its invitation rather than 404ing."""
        offerings_pilot(pilot.ALLOW_ALL)
        out = member_api.get_your_collection(db=db, current_user=make_user())
        assert out == {"items": [], "count": 0}

    def test_an_owners_detail_page_opens_after_their_collective_leaves(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """The adjustment this class exists to pin.

        An owner reaches this page from Your Collection, so the link
        must not break because an operator edited a config value. Their
        downloads are listed on it.

        An earlier version of this test asserted the opposite — a 404 —
        and recorded it as a known limitation. It is now a bug that
        would fail here.
        """
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        offerings_pilot("somewhere-else-entirely")

        out = member_api.get_member_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        assert out["viewer_owns"] is True
        assert out["title"] == a.title
        # And their download is on it.
        assert out["files"], "an owner must see their files"
        assert out["files"][0]["download_url"] is not None

    def test_that_page_offers_no_new_acquisition(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """The exemption restores *access*, not the shopfront. The page
        must not become a way to acquire in a Collective outside the
        pilot."""
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        offerings_pilot("somewhere-else-entirely")

        out = member_api.get_member_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        assert out["can_acquire"] is False
        # Owning is not a refusal, so no reason code is reported.
        assert out["acquire_blocked"] is None
        # And the endpoint that would acquire is still gated.
        with pytest.raises(HTTPException) as e:
            member_api.acquire_offering(
                inside.slug, a.slug, db=db, current_user=taker,
            )
        assert e.value.status_code == 404

    def test_the_exemption_needs_an_entitlement_for_THIS_offering(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """The narrowness is the security property.

        Owning *something else* must not open a non-pilot Offering —
        otherwise one acquisition would become a key to every
        Collective's catalogue.
        """
        inside, outside, a, b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        # They own ``a``. They do not own ``b``, in the non-pilot
        # Collective.
        with pytest.raises(HTTPException) as e:
            member_api.get_member_offering(
                outside.slug, b.slug, db=db, current_user=taker,
            )
        assert e.value.status_code == 404

    def test_a_signed_in_non_owner_is_still_refused(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        inside, _outside, a, _b = two_collectives
        offerings_pilot("somewhere-else-entirely")
        with pytest.raises(HTTPException) as e:
            member_api.get_member_offering(
                inside.slug, a.slug, db=db, current_user=make_user(),
            )
        assert e.value.status_code == 404

    def test_an_anonymous_visitor_is_still_refused(
        self, db, two_collectives, offerings_pilot,
    ):
        """Nobody can own anything without a session, so the exemption
        can never apply here — and the catalogue stays shut."""
        inside, _outside, a, _b = two_collectives
        offerings_pilot("somewhere-else-entirely")
        for call in (
            lambda: member_api.get_member_offering(
                inside.slug, a.slug, db=db, current_user=None),
            lambda: member_api.list_member_offerings(
                inside.slug, db=db, current_user=None),
        ):
            with pytest.raises(HTTPException) as e:
                call()
            assert e.value.status_code == 404

    def test_a_revoked_entitlement_does_not_open_the_page(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """``already_owns`` tests for an *active* row, so a revoked
        entitlement confers nothing — which is the same rule the
        download route applies."""
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        ent = db.query(OfferingEntitlement).filter(
            OfferingEntitlement.user_id == taker.id,
            OfferingEntitlement.offering_id == a.id,
        ).one()
        ent.status = OfferingEntitlementStatus.revoked.value
        ent.revoked_at = datetime.utcnow()
        ent.revoked_reason = "disputed"
        db.flush()
        offerings_pilot("somewhere-else-entirely")

        with pytest.raises(HTTPException) as e:
            member_api.get_member_offering(
                inside.slug, a.slug, db=db, current_user=taker,
            )
        assert e.value.status_code == 404

    def test_the_whole_route_from_your_collection_to_the_download(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """The journey the adjustment was asked for, end to end, with
        the Collective outside the pilot the whole way:

            Your Collection → the card's href → the detail page
                            → the download URL → the file
        """
        from app.uploads.authorization import authorize_upload
        inside, _outside, a, _b = two_collectives
        offerings_pilot(inside.slug)
        taker = make_user()
        member_api.acquire_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        offerings_pilot("somewhere-else-entirely")

        # 1. Your Collection lists it, with a link.
        coll = member_api.get_your_collection(db=db, current_user=taker)
        assert coll["count"] == 1
        href = coll["items"][0]["href"]
        assert href == f"/spaces/{inside.slug}/offerings/{a.slug}"

        # 2. That link opens.
        detail = member_api.get_member_offering(
            inside.slug, a.slug, db=db, current_user=taker,
        )
        assert detail["viewer_owns"] is True

        # 3. And the download URL on it authorises.
        key = detail["files"][0]["download_url"].removeprefix("/api/uploads/")
        authorize_upload(key, taker, db)   # must not raise

        # 4. While the shopfront stays shut.
        with pytest.raises(HTTPException):
            member_api.list_member_offerings(
                inside.slug, db=db, current_user=taker,
            )


class TestDownloadsAreNeverPilotGated:

    def test_an_owner_downloads_regardless_of_the_allow_list(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """The single most important assertion in this file.

        A Collective leaving the pilot — or the whole feature being
        switched off — must never reach into a file somebody already
        acquired. ``_authorise_offering_file`` consults neither switch,
        and this is what holds it to that.
        """
        from app.uploads.authorization import authorize_upload
        inside, _outside, a, _b = two_collectives
        f = db.query(OfferingFile).filter(
            OfferingFile.offering_id == a.id,
        ).one()
        taker = make_user()
        _own(db, taker, a, inside)

        for label, tokens in (
            ("in the pilot", (inside.slug,)),
            ("removed from the pilot", ("somewhere-else",)),
            ("pilot closed entirely", ()),
        ):
            offerings_pilot(*tokens)
            # Must not raise.
            authorize_upload(f.storage_key, taker, db)

    def test_a_non_owner_is_still_refused_regardless(
        self, db, two_collectives, offerings_pilot, make_user,
    ):
        """And the pilot must not accidentally *widen* access either."""
        from app.uploads.authorization import authorize_upload
        inside, _outside, a, _b = two_collectives
        f = db.query(OfferingFile).filter(
            OfferingFile.offering_id == a.id,
        ).one()
        stranger = make_user()
        for tokens in ((inside.slug,), ("somewhere-else",), ()):
            offerings_pilot(*tokens)
            with pytest.raises(HTTPException) as e:
                authorize_upload(f.storage_key, stranger, db)
            assert e.value.status_code in (403, 404)

    def test_the_authoriser_source_mentions_neither_switch(self):
        """A source guard, because this is a property that would be easy
        to break while 'making the pilot consistent'."""
        import inspect
        import re
        from app.uploads import authorization
        src = inspect.getsource(authorization._authorise_offering_file)
        src = re.sub(r"(?m)^\s*#.*$", "", src)
        src = re.sub(r'""".*?"""', "", src, flags=re.S)
        assert "offerings_enabled" not in src
        assert "offering_pilot" not in src
        assert "space_in_pilot" not in src


# ---------------------------------------------------------------------------
# General release — the state the pilot was built to end in
# ---------------------------------------------------------------------------


class TestGeneralRelease:
    """``OFFERINGS_PILOT_COLLECTIVES=*`` — Offerings for every Collective.

    The pilot's own docstring says a general release is setting the
    value to ``*``, "an explicit act, which is the point". Every test
    above proves the pilot RESTRICTS correctly; these prove the
    release state works, which is a different question and the one
    that matters once the restriction is lifted.

    Nothing here changes the security model: ownership, entitlement
    and draft visibility are enforced by their own guards, and the
    last tests in this class are what hold that line.
    """

    def _general_release(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "offerings_enabled", True)
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "*")

    def _owner(self, db, space) -> User:
        return db.query(User).filter(User.id == space.creator_id).one()

    def test_every_collective_is_admitted(
        self, db, two_collectives, monkeypatch,
    ):
        self._general_release(monkeypatch)
        inside, outside, _a, _b = two_collectives
        for space in (inside, outside):
            assert pilot.offerings_available_for(space) is True

    def test_both_creators_can_manage_their_own(
        self, db, two_collectives, monkeypatch,
    ):
        """The pilot's defining restriction — one Collective works, the
        other 404s — is gone, and each creator reaches their own."""
        self._general_release(monkeypatch)
        inside, outside, _a, _b = two_collectives
        for space in (inside, outside):
            owner = self._owner(db, space)
            assert creator_api.list_offerings(
                space.slug, db=db, current_user=owner,
            ) is not None
            created = creator_api.create_offering(
                space.slug, OfferingCreateRequest(title="Generally available"),
                db=db, current_user=owner,
            )
            assert created["status"] == OfferingStatus.draft.value

    def test_a_collective_created_after_the_release_is_included(
        self, db, make_space, monkeypatch,
    ):
        """No allow-list to add it to. A Collective made tomorrow has
        Offerings for the same reason every other one does."""
        self._general_release(monkeypatch)
        fresh = make_space()
        assert pilot.offerings_available_for(fresh) is True
        owner = self._owner(db, fresh)
        assert creator_api.list_offerings(
            fresh.slug, db=db, current_user=owner,
        ) is not None

    def test_renaming_a_collective_cannot_remove_its_offerings(
        self, db, make_space, monkeypatch,
    ):
        """Under the pilot a rename could drop a slug-listed Collective
        out of scope. With no list, a rename is just a rename."""
        self._general_release(monkeypatch)
        space = make_space()
        space.slug = "renamed-after-release"
        db.flush()
        assert pilot.offerings_available_for(space) is True

    def test_the_offerings_area_is_reachable_in_every_collective(
        self, db, two_collectives, monkeypatch,
    ):
        """What drives the Creator Studio sidebar and the member tab.
        During the pilot this answered False for the second Collective,
        which is what left stale navigation pointing at a 404."""
        from app.spaces.area_access import _offerings_available_for

        self._general_release(monkeypatch)
        inside, outside, _a, _b = two_collectives
        assert _offerings_available_for(inside) is True
        assert _offerings_available_for(outside) is True

    def test_a_published_offering_is_browsable_in_any_collective(
        self, db, two_collectives, make_user, monkeypatch,
    ):
        self._general_release(monkeypatch)
        inside, outside, a, b = two_collectives
        for space, off in ((inside, a), (outside, b)):
            cards = member_api.list_member_offerings(
                space.slug, db=db, current_user=None,
            )
            slugs = [c["slug"] for c in cards]
            assert off.slug in slugs, f"{off.slug} missing from {space.slug}"

    def test_a_free_offering_can_be_acquired_in_any_collective(
        self, db, two_collectives, make_user, monkeypatch,
    ):
        self._general_release(monkeypatch)
        inside, outside, a, b = two_collectives
        for space, off in ((inside, a), (outside, b)):
            taker = make_user()
            out = member_api.acquire_offering(
                space.slug, off.slug, db=db, current_user=taker,
            )
            assert out["acquired"] is True
            assert out["already_owned"] is False

    # ── The guards that must NOT relax with the pilot ────────────────

    def test_a_creator_still_cannot_touch_another_collectives_offering(
        self, db, two_collectives, monkeypatch,
    ):
        """Ownership is enforced by the creator guard, never by the
        pilot. Opening the pilot must not open this."""
        self._general_release(monkeypatch)
        inside, outside, _a, b = two_collectives
        intruder = self._owner(db, inside)

        with pytest.raises(HTTPException) as exc:
            creator_api.get_offering(
                outside.slug, b.slug, db=db, current_user=intruder,
            )
        assert exc.value.status_code in (403, 404)

    def test_a_draft_is_still_invisible_to_members(
        self, db, make_space, make_user, monkeypatch,
    ):
        """The one thing a general release must never do."""
        self._general_release(monkeypatch)
        space = make_space()
        draft = _offering(db, space, status=OfferingStatus.draft.value)
        _file(db, draft)

        cards = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert draft.slug not in [c["slug"] for c in cards]

        with pytest.raises(HTTPException) as exc:
            member_api.get_member_offering(
                space.slug, draft.slug, db=db, current_user=make_user(),
            )
        assert exc.value.status_code == 404

    def test_a_draft_cannot_be_acquired_even_when_generally_available(
        self, db, make_space, make_user, monkeypatch,
    ):
        self._general_release(monkeypatch)
        space = make_space()
        draft = _offering(db, space, status=OfferingStatus.draft.value)
        _file(db, draft)
        with pytest.raises(HTTPException):
            member_api.acquire_offering(
                space.slug, draft.slug, db=db, current_user=make_user(),
            )

    def test_the_master_switch_still_overrides_everything(
        self, db, make_space, monkeypatch,
    ):
        """``*`` is the scope, not the feature. OFFERINGS_ENABLED=false
        must still turn the whole thing off — the rollback path if the
        general release has to be undone."""
        from app.core.config import settings

        self._general_release(monkeypatch)
        monkeypatch.setattr(settings, "offerings_enabled", False)
        assert pilot.offerings_available_for(make_space()) is False

    def test_describe_tells_an_operator_it_is_generally_available(
        self, monkeypatch,
    ):
        from app.services.offering_pilot import describe

        self._general_release(monkeypatch)
        assert "ALL Collectives" in describe()
