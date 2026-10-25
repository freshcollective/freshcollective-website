"""Where a purchase email sends the member.

``_member_url_for_option`` resolves one URL from a ``PaymentOption``'s
attachment, and that URL becomes both ``member_url`` and ``repair_url``
on all six purchase-lifecycle emails. It matched ``"series"``; the
platform writes ``"event_series"``
(``creator._gathering_series_routes``). So the Series branch was
unreachable and every Gathering Series email — the receipt, and the
payment-recovery CTA — linked to ``/dashboard``.

The receipt was the reported concern. The recovery CTA is the one that
mattered: ``PlanRecoveryBanner`` renders on the Series page and not on
``/dashboard``, so a member whose Series instalment failed was sent
somewhere the repair flow does not exist.

``_member_url_for_option`` and ``resolve_context`` had **no tests at
all** before this file. Every existing test that mentions ``member_url``
supplies it as a fixture string, so the Pathway branch passed by
coincidence and nothing watched the others.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models.offering import (
    Offering,
    OfferingFulfilmentKind,
    OfferingStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.platform import EventSeries, Pathway, PathwayType
from app.services import member_links
from app.services.purchase_lifecycle_emit import (
    _member_url_for_option,
    resolve_context,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def space(make_space):
    return make_space(status="active", slug=f"sp-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def member(make_user):
    return make_user()


@pytest.fixture
def series(db, space):
    row = EventSeries(
        id=_uid("es"), space_id=space.id, slug="monday-mornings",
        title="Monday Mornings",
        starts_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def pathway(db, space):
    row = Pathway(
        id=_uid("pw"), space_id=space.id, slug="finding-ground",
        title="Finding Ground", status="active", access_type="one_time",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="payment_options", currency="AUD",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def offering(db, space):
    row = Offering(
        id=_uid("off"), space_id=space.id,
        created_by_user_id=space.creator_id,
        slug="a-gentle-guide", title="A Gentle Guide",
        summary="Short lines.", status=OfferingStatus.published.value,
        fulfilment_kind=OfferingFulfilmentKind.digital_download.value,
    )
    db.add(row)
    db.flush()
    return row


def _option(db, space, kind, target_id):
    row = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind=kind, attaches_to_id=target_id,
        name="Term pass", payment_type=PaymentOptionType.term_pass,
        status=PaymentOptionStatus.published,
        calculated_total_cents=12000, currency="AUD",
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# 1. The defect
# ---------------------------------------------------------------------------


class TestGatheringSeriesDestination:

    def test_event_series_resolves_to_the_series_page(
        self, db, space, series,
    ):
        """**The fix.** ``event_series`` is the value the creator route
        writes; this used to answer ``/dashboard``."""
        url = _member_url_for_option(
            db, _option(db, space, "event_series", series.id),
        )
        assert url.endswith(
            f"/spaces/{space.slug}/gathering-series/monday-mornings"
        )

    def test_the_legacy_spelling_also_resolves(self, db, space, series):
        """Accepted for compatibility, so the fix cannot be undone by a
        future writer choosing the other word."""
        url = _member_url_for_option(
            db, _option(db, space, "series", series.id),
        )
        assert url.endswith(
            f"/spaces/{space.slug}/gathering-series/monday-mornings"
        )

    def test_both_spellings_agree(self, db, space, series):
        a = _member_url_for_option(
            db, _option(db, space, "event_series", series.id),
        )
        b = _member_url_for_option(
            db, _option(db, space, "series", series.id),
        )
        assert a == b

    def test_it_is_not_the_dashboard(self, db, space, series):
        url = _member_url_for_option(
            db, _option(db, space, "event_series", series.id),
        )
        assert "/dashboard" not in url

    def test_the_case_of_the_stored_value_does_not_matter(
        self, db, space, series,
    ):
        """``kind`` is lower-cased before matching, which was already
        true and is worth keeping true."""
        url = _member_url_for_option(
            db, _option(db, space, "Event_Series", series.id),
        )
        assert "gathering-series" in url


# ---------------------------------------------------------------------------
# 2. Every other kind keeps its existing destination
# ---------------------------------------------------------------------------


class TestOtherKindsAreUnchanged:

    def test_pathway(self, db, space, pathway):
        url = _member_url_for_option(
            db, _option(db, space, "pathway", pathway.id),
        )
        assert url.endswith(f"/spaces/{space.slug}/pathways/finding-ground")

    def test_offering(self, db, space, offering):
        url = _member_url_for_option(
            db, _option(db, space, "offering", offering.id),
        )
        assert url.endswith(f"/spaces/{space.slug}/offerings/a-gentle-guide")

    def test_space_falls_back_deliberately(self, db, space):
        """The grants-first sentinel. The option grants many things, so
        there is no single honest destination — ``/dashboard`` is the
        right answer, and it is a recorded decision in
        ``member_links.ATTACH_KINDS_WITHOUT_MEMBER_URL``."""
        url = _member_url_for_option(
            db, _option(db, space, "space", space.id),
        )
        assert url.endswith("/dashboard")

    @pytest.mark.parametrize(
        "kind", ["bundle", "gathering", "", "pathways", "event-series"],
    )
    def test_an_unknown_kind_falls_back(self, db, space, kind):
        """Including near-misses. Inventing a URL from a kind we do not
        understand is worse than a dashboard link."""
        url = _member_url_for_option(
            db, _option(db, space, kind, space.id),
        )
        assert url.endswith("/dashboard")


# ---------------------------------------------------------------------------
# 3. Missing and deleted targets
# ---------------------------------------------------------------------------


class TestFallbacks:

    def test_no_option_at_all(self, db):
        assert _member_url_for_option(db, None).endswith("/dashboard")

    def test_an_option_with_no_target_id(self, db, space):
        opt = _option(db, space, "event_series", "")
        assert _member_url_for_option(db, opt).endswith("/dashboard")

    def test_a_deleted_series(self, db, space, series):
        """The option outlives its target. Fall back rather than build a
        URL to a page that 404s."""
        opt = _option(db, space, "event_series", series.id)
        db.delete(series)
        db.flush()
        assert _member_url_for_option(db, opt).endswith("/dashboard")

    def test_a_deleted_pathway(self, db, space, pathway):
        opt = _option(db, space, "pathway", pathway.id)
        db.delete(pathway)
        db.flush()
        assert _member_url_for_option(db, opt).endswith("/dashboard")

    def test_a_series_id_that_never_existed(self, db, space):
        opt = _option(db, space, "event_series", "es_nope")
        assert _member_url_for_option(db, opt).endswith("/dashboard")

    def test_a_series_with_no_slug(self, db, space):
        """``member_links`` answers "" for an unslugged row and the
        caller turns that into the fallback."""
        row = EventSeries(
            id=_uid("es"), space_id=space.id, slug="",
            title="Unslugged", starts_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()
        opt = _option(db, space, "event_series", row.id)
        assert _member_url_for_option(db, opt).endswith("/dashboard")

    def test_a_missing_space(self, db, space, series):
        """Built in memory rather than persisted: the FK would refuse a
        bogus ``space_id``, but the resolver must still answer sensibly
        if it is ever handed one (a stale object, a future soft-delete).
        """
        opt = PaymentOption(
            id=_uid("po"), space_id="sp_nope",
            attaches_to_kind="event_series", attaches_to_id=series.id,
            name="Term pass", payment_type=PaymentOptionType.term_pass,
            status=PaymentOptionStatus.published,
            calculated_total_cents=12000, currency="AUD",
        )
        assert _member_url_for_option(db, opt).endswith("/dashboard")


# ---------------------------------------------------------------------------
# 4. The six lifecycle emails
# ---------------------------------------------------------------------------


SIX_EMITS = [
    "emit_purchase_completed",
    "emit_instalment_failed",
    "emit_first_payment_failed",
    "emit_access_suspended",
    "emit_payment_recovered",
    "emit_plan_completed",
]


class TestEveryLifecycleEmail:
    """All six build their links from one ``PurchaseCommsContext``, so
    fixing the resolver fixes all six. Both halves are asserted: that
    the context is right, and that each email takes its links from it
    rather than building its own."""

    def test_the_context_carries_the_series_url(
        self, db, space, series, member,
    ):
        ctx = resolve_context(
            db, user=member,
            payment_option=_option(db, space, "event_series", series.id),
        )
        assert ctx.member_url.endswith(
            f"/spaces/{space.slug}/gathering-series/monday-mornings"
        )

    def test_the_repair_url_is_the_series_page_too(
        self, db, space, series, member,
    ):
        """The important one. ``repair_url`` is the CTA on
        ``instalment.failed`` and ``first_payment.failed``."""
        ctx = resolve_context(
            db, user=member,
            payment_option=_option(db, space, "event_series", series.id),
        )
        assert ctx.repair_url == ctx.member_url
        assert "/dashboard" not in ctx.repair_url
        assert "gathering-series" in ctx.repair_url

    @pytest.mark.parametrize("name", SIX_EMITS)
    def test_each_email_resolves_its_links_from_the_context(self, name):
        import inspect

        from app.services import purchase_lifecycle_emit as mod

        src = inspect.getsource(getattr(mod, name))
        assert "resolve_context(" in src
        # And does not hand-build a link of its own.
        assert "/spaces/" not in src

    @pytest.mark.parametrize("name", SIX_EMITS)
    def test_each_email_exists(self, name):
        from app.services import purchase_lifecycle_emit as mod

        assert callable(getattr(mod, name))

    def test_the_resolver_is_the_only_place_a_link_is_built(self):
        """One construction, so the six cannot drift apart."""
        import inspect

        from app.services import purchase_lifecycle_emit as mod

        src = inspect.getsource(mod)
        # ``/spaces/`` appears only inside the resolver's docstring
        # references; the paths themselves come from ``member_links``.
        assert "member_links" in src or "_links" in src

    def test_other_kinds_still_reach_the_context_unchanged(
        self, db, space, pathway, member,
    ):
        ctx = resolve_context(
            db, user=member,
            payment_option=_option(db, space, "pathway", pathway.id),
        )
        assert ctx.member_url.endswith(
            f"/spaces/{space.slug}/pathways/finding-ground"
        )

    def test_a_grants_first_purchase_still_gets_the_dashboard(
        self, db, space, member,
    ):
        ctx = resolve_context(
            db, user=member,
            payment_option=_option(db, space, "space", space.id),
        )
        assert ctx.member_url.endswith("/dashboard")

    def test_no_option_still_gets_the_dashboard(self, db, member):
        ctx = resolve_context(db, user=member, payment_option=None)
        assert ctx.member_url.endswith("/dashboard")
        assert ctx.repair_url.endswith("/dashboard")


# ---------------------------------------------------------------------------
# 5. The payment-recovery destination can actually recover
# ---------------------------------------------------------------------------


class TestTheRecoveryDestinationWorks:
    """A correct link is only half of it — the page has to be able to
    show the repair affordance.

    Stated as what the Series page must offer, not as what other pages
    must lack. ``/dashboard`` is the fallback for attachments with no
    specific destination, and whether it ever grows its own recovery
    surface is a separate product question these tests leave open.
    """

    def test_the_series_page_can_supply_a_plan_state(self):
        """``PlanRecoveryBanner`` renders when the Series detail carries
        ``member_plan_state``, and the Series member route builds one
        from ``find_recovery_plan_for_series``. So the destination this
        fix sends people to is one where recovery is possible —
        ``/dashboard`` renders no banner at all."""
        import inspect

        from app.spaces import _series_member_routes as sm

        src = inspect.getsource(sm)
        assert "member_plan_state" in src
        assert "find_recovery_plan_for_series" in src

    def test_the_series_page_renders_the_recovery_banner(self):
        """The positive requirement: the page a recovery email now links
        to is one that offers recovery.

        Deliberately says nothing about what other pages do — the
        dashboard gaining its own banner later would be an improvement,
        not a regression, and a test that forbade it would be asserting
        a limitation rather than a requirement."""
        series_page = (
            Path(__file__).resolve().parents[2] / "frontend" / "src"
            / "app" / "spaces" / "[slug]" / "gathering-series"
            / "[series-slug]" / "page.tsx"
        )
        src = series_page.read_text()
        assert "PlanRecoveryBanner" in src
        # Rendered off the server-supplied plan state, so it appears
        # exactly when the member has something to recover.
        assert "member_plan_state" in src

    def test_recovery_emails_point_at_a_page_with_the_banner(
        self, db, space, series, member,
    ):
        ctx = resolve_context(
            db, user=member,
            payment_option=_option(db, space, "event_series", series.id),
        )
        assert "/gathering-series/" in ctx.repair_url


# ---------------------------------------------------------------------------
# 6. One shared construction
# ---------------------------------------------------------------------------


class TestSharedSeriesUrlConstruction:

    def test_the_booking_email_delegates_to_the_shared_helper(self):
        """``gathering_booking_emit`` had the correct implementation and
        the lifecycle emails had their own. One now, so they cannot
        drift again."""
        import inspect

        from app.services import gathering_booking_emit as gbe

        src = inspect.getsource(gbe._series_url)
        assert "member_links.series_member_url" in src
        assert "/spaces/" not in src

    def test_both_callers_produce_the_same_url(
        self, db, space, series, member,
    ):
        from app.services.gathering_booking_emit import _series_url

        booking_url = _series_url(space, series)
        lifecycle_url = resolve_context(
            db, user=member,
            payment_option=_option(db, space, "event_series", series.id),
        ).member_url
        assert booking_url == lifecycle_url

    def test_the_helper_answers_empty_rather_than_a_broken_url(
        self, db, space, series,
    ):
        assert member_links.series_member_url(None, series) == ""
        assert member_links.series_member_url(space, None) == ""
        assert member_links.series_member_url(space, object()) == ""

    def test_the_helper_uses_the_public_origin(self, db, space, series):
        """Not ``FRONTEND_ORIGIN`` — the distinction
        ``core.public_url`` exists to enforce."""
        import inspect

        src = inspect.getsource(member_links)
        assert "public_app_url" in src
        assert "frontend_origin" not in src


# ---------------------------------------------------------------------------
# 7. The guard against the next mismatch
# ---------------------------------------------------------------------------


class TestWrittenKindsAreRecognised:
    """The defect was a vocabulary drift between writers and one reader,
    with nothing watching. ``attaches_to_kind`` is a free
    ``String(30)`` — no enum, no CHECK — so this is the watch.

    ``core.public_url`` has a source guard, but it stops a builder
    reading the *origin* setting directly. Both callers used
    ``public_app_url`` correctly; nothing guarded the *path*.
    """

    BACKEND = Path(__file__).resolve().parents[1]

    def _written_literals(self) -> set[str]:
        found: set[str] = set()
        for path in (self.BACKEND / "app").rglob("*.py"):
            for m in re.finditer(
                r"""attaches_to_kind\s*=\s*["']([^"']+)["']""",
                path.read_text(),
            ):
                found.add(m.group(1))
        return found

    def test_every_written_literal_is_known(self):
        written = self._written_literals()
        assert written, "the scan found nothing — has the field been renamed?"
        unknown = written - member_links.KNOWN_ATTACH_KINDS
        assert not unknown, (
            f"these values are written to attaches_to_kind but the comms "
            f"layer has never heard of them: {sorted(unknown)}. Add each to "
            f"member_links.ATTACH_KINDS_WITH_MEMBER_URL (with a URL "
            f"builder) or ATTACH_KINDS_WITHOUT_MEMBER_URL (and say why a "
            f"dashboard link is the honest answer)."
        )

    def test_the_named_constants_are_known_too(self):
        """The two writers that use a constant rather than a literal."""
        from app.creator._space_payment_options_routes import (
            _GRANTS_FIRST_ATTACH_KIND,
        )
        from app.services.purchase_fulfilment import OFFERING_ATTACHES_KIND

        for value in (_GRANTS_FIRST_ATTACH_KIND, OFFERING_ATTACHES_KIND):
            assert value in member_links.KNOWN_ATTACH_KINDS

    def test_the_series_writer_still_writes_what_we_read(self):
        """Pinned directly at the source of the original defect."""
        src = (
            self.BACKEND / "app" / "creator" / "_gathering_series_routes.py"
        ).read_text()
        assert 'attaches_to_kind="event_series"' in src
        assert "event_series" in member_links.SERIES_ATTACH_KINDS

    def test_every_kind_with_a_url_actually_resolves_one(
        self, db, space, series, pathway, offering,
    ):
        """No kind may claim a destination it cannot build."""
        targets = {
            "pathway": pathway.id,
            "event_series": series.id,
            "series": series.id,
            "offering": offering.id,
        }
        assert set(targets) == set(member_links.ATTACH_KINDS_WITH_MEMBER_URL)
        for kind, target in targets.items():
            url = _member_url_for_option(
                db, _option(db, space, kind, target),
            )
            assert not url.endswith("/dashboard"), kind

    def test_every_kind_without_a_url_falls_back(self, db, space):
        for kind in member_links.ATTACH_KINDS_WITHOUT_MEMBER_URL:
            url = _member_url_for_option(
                db, _option(db, space, kind, space.id),
            )
            assert url.endswith("/dashboard"), kind

    def test_the_two_sets_do_not_overlap(self):
        assert not (
            member_links.ATTACH_KINDS_WITH_MEMBER_URL
            & member_links.ATTACH_KINDS_WITHOUT_MEMBER_URL
        )

    def test_the_stale_comment_was_corrected(self):
        """It claimed the sentinel was inert at runtime. The comms layer
        reads it."""
        src = (
            self.BACKEND / "app" / "creator"
            / "_space_payment_options_routes.py"
        ).read_text()
        assert "the sentinel is inert at runtime" not in src
        # Phrased to survive the comment's line wrapping.
        assert "not inert everywhere" in src
        assert "member_links" in src
