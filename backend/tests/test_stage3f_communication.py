"""Stage 3F — three things that were computed and then not shown.

Each had a different cause, and none of them was the feature being
missing:

* The confirmation email's included experiences existed in the event
  payload and never reached the template, because the resolver's
  context is an allowlist and Stage 3E.1 did not add them to it.
* Sophie's two Pathways were classified as newly unlocked because the
  check asked whether an entitlement row predated the charge, and she
  had reached those Pathways without one.
* The purchase notification pointed at the dashboard for every
  purchase, so "Sunday Slow Down Series — purchase confirmed" opened a
  page that did not mention it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.platform import (
    EntitlementStatus, Pathway, PathwayEntitlement, PathwayType,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def space(make_space):
    return make_space()


def _pathway(db, space, *, access_type="included_with_offer", title="P"):
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active", access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy", currency="AUD",
    )
    db.add(p); db.flush()
    return p


# ===========================================================================
# Issue C — the email context is an allowlist
# ===========================================================================


class TestTheEmailContextCarriesTheIncludedExperiences:
    def _resolve(self, db, payload):
        from app.comms.models import CommunicationEvent
        from app.comms.routing.resolvers.purchases import (
            PurchaseCompletedResolver,
        )

        event = CommunicationEvent(
            id=_uid("ev"), event_type="purchase.completed",
            actor_user_id="u_someone", payload=payload,
        )
        [recipient] = PurchaseCompletedResolver().resolve(db, event)
        return recipient.template_context

    def test_included_reaches_the_template(self, db):
        """The whole of the bug. The emitter computed this list and
        put it in the payload; the resolver dropped it."""
        ctx = self._resolve(db, {
            "first_name": "Sophie",
            "experience_name": "Sunday Slow Down Series",
            "included": [
                {"kind": "event_series", "title": "Sunday Slow Down",
                 "url": "/s", "status": "Your Series pass is active",
                 "starts_at": None},
            ],
        })
        assert len(ctx["included"]) == 1
        assert ctx["included"][0]["title"] == "Sunday Slow Down"

    def test_the_plan_figures_reach_it_too(self, db):
        ctx = self._resolve(db, {
            "payment_mode": "plan",
            "installments_paid": 1, "installments_expected": 2,
            "installment_amount_cents": 4500,
            "total_expected_cents": 9000, "interval": "month",
        })
        assert ctx["installment_amount_cents"] == 4500
        assert ctx["total_expected_cents"] == 9000
        assert ctx["interval"] == "month"

    def test_an_empty_payload_yields_an_empty_list(self, db):
        """Not None — the template iterates it."""
        ctx = self._resolve(db, {"first_name": "Sophie"})
        assert ctx["included"] == []

    def test_the_rendered_email_lists_them(self, db):
        from app.comms.templates.purchases import _included_lines

        lines = _included_lines([
            {"title": "Sunday Slow Down", "status": "Your Series pass is active",
             "starts_at": None, "url": "/spaces/m/gathering-series/ssd"},
            {"title": "A Little Guide to Slowing Down",
             "status": "Already in your collection", "starts_at": None,
             "url": "/spaces/m/pathways/guide"},
        ], "https://freshcollective.au")
        assert len(lines) == 2
        assert "Sunday Slow Down" in lines[0]
        assert "Already in your collection" in lines[1]
        assert "https://freshcollective.au/spaces/m/pathways/guide" in lines[1]


# ===========================================================================
# Issue E — what "already yours" actually means
# ===========================================================================


class TestExistingAccessClassification:
    def _status(self, db, user_id, pathway, purchased_at):
        from app.services.purchase_included_summary import (
            _live_pathway_status,
        )
        return _live_pathway_status(
            db, user_id=user_id, pathway_id=pathway.id,
            purchased_at=purchased_at,
        )

    def test_a_members_only_pathway_was_never_this_purchase_to_unlock(
        self, db, space, make_user,
    ):
        """Sophie's case. She could open both Pathways already — not
        through an entitlement, but because they are open to members.
        So there was no earlier row to compare against and the
        timestamp check concluded "new" about something she had been
        reading for weeks."""
        buyer = make_user()
        pw = _pathway(db, space, access_type="included")
        # The purchase writes the first entitlement, just now.
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pw.id,
            space_id=space.id, source="included",
            status=EntitlementStatus.active,
        ))
        db.flush()

        assert self._status(
            db, buyer.id, pw, datetime.utcnow(),
        ) == "Already in your collection"

    def test_a_free_pathway_likewise(self, db, space, make_user):
        buyer = make_user()
        pw = _pathway(db, space, access_type="free")
        assert self._status(
            db, buyer.id, pw, datetime.utcnow(),
        ) == "Already in your collection"

    def test_an_older_entitlement_still_counts_as_existing(
        self, db, space, make_user,
    ):
        """The Stage 3E.4 rule, which was right as far as it went."""
        buyer = make_user()
        pw = _pathway(db, space)
        ent = PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pw.id,
            space_id=space.id, source="one_time_purchase",
            status=EntitlementStatus.active,
        )
        db.add(ent); db.flush()
        ent.created_at = datetime.utcnow() - timedelta(days=30)
        db.flush()

        assert self._status(
            db, buyer.id, pw, datetime.utcnow(),
        ) == "Already in your collection"

    def test_access_this_purchase_created_reads_as_new(
        self, db, space, make_user,
    ):
        """The distinction has to cut both ways or it is useless."""
        buyer = make_user()
        pw = _pathway(db, space, access_type="included_with_offer")
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pw.id,
            space_id=space.id, source="included",
            status=EntitlementStatus.active,
        ))
        db.flush()

        assert self._status(
            db, buyer.id, pw, datetime.utcnow() - timedelta(seconds=5),
        ) == "Your access is ready"

    def test_no_entitlement_on_a_paid_pathway_is_not_claimed_as_access(
        self, db, space, make_user,
    ):
        buyer = make_user()
        pw = _pathway(db, space, access_type="one_time")
        assert self._status(
            db, buyer.id, pw, datetime.utcnow(),
        ) == "No longer available"


# ===========================================================================
# Issue D — a notification that goes somewhere useful
# ===========================================================================


class TestPurchaseDestination:
    def _dest(self, db, included, space_id=None):
        from app.services.activity_producers import _purchase_destination
        return _purchase_destination(included, space_id, db)

    def test_a_series_purchase_opens_the_series(self, db, space):
        """Sophie's notification said "Sunday Slow Down Series" and
        opened the dashboard."""
        dest = self._dest(db, [
            {"kind": "event_series", "title": "Sunday Slow Down",
             "url": "/spaces/m/gathering-series/ssd"},
            {"kind": "pathway", "title": "A", "url": "/spaces/m/pathways/a"},
            {"kind": "pathway", "title": "B", "url": "/spaces/m/pathways/b"},
        ], space.id)
        assert dest == "/spaces/m/gathering-series/ssd"

    def test_a_gathering_bundle_opens_the_gathering(self, db, space):
        dest = self._dest(db, [
            {"kind": "gathering", "title": "G", "url": "/spaces/m/events/1"},
            {"kind": "pathway", "title": "P", "url": "/spaces/m/pathways/p"},
        ], space.id)
        assert dest == "/spaces/m/events/1"

    def test_a_single_pathway_opens_that_pathway(self, db, space):
        dest = self._dest(db, [
            {"kind": "pathway", "title": "P", "url": "/spaces/m/pathways/p"},
        ], space.id)
        assert dest == "/spaces/m/pathways/p"

    def test_several_pathways_with_no_centre_open_the_collective(
        self, db, space,
    ):
        """§10: do not invent a destination that doesn't exist. A
        Payment Option has no page, so the Collective is where all of
        them are."""
        dest = self._dest(db, [
            {"kind": "pathway", "title": "A", "url": "/spaces/m/pathways/a"},
            {"kind": "pathway", "title": "B", "url": "/spaces/m/pathways/b"},
        ], space.id)
        assert dest == f"/spaces/{space.slug}"

    def test_nothing_identifiable_falls_back_to_the_dashboard(self, db):
        assert self._dest(db, [], None) == "/dashboard"

    def test_the_fallback_is_the_real_route(self):
        """"Your World" is the title; `/dashboard` is the path. Writing
        the first where the second belongs is the mistake this stage
        corrects, so it is named once."""
        from app.services.activity_producers import DASHBOARD_PATH

        assert DASHBOARD_PATH == "/dashboard"
