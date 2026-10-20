"""The no-subscription fallback must be Community, every time.

Found by chasing an intermittent failure in
``test_creator_grant_expiry::test_repeated_runs_are_idempotent``.

The mechanism
-------------

``resolve_creator_plan`` falls back to "the cheapest active plan" when a
creator has no subscription row, and ``community_is_the_fallback``
separately checked the same thing. Both ran
``ORDER BY monthly_price_cents`` with **no tiebreak**, and three active
plans cost zero: Community, Founding Creator and Organisation. With a
three-way tie the database may return any of them, so the answer was
decided by physical row order — stable only until something rewrote a
row.

Why it is not merely a test problem
-----------------------------------

A free Community creator has **no subscription row at all** — writing
one would break the paid upgrade path — so every Community creator
resolves through this fallback. Landing on Founding Creator would hand
them unrestricted Collectives, unrestricted members, paid Offerings and
a 0% transaction fee.

These tests force the tie to be decided the wrong way if it can be, by
inserting the rival plans first and by rewriting the Community row so it
moves in the heap.
"""

from __future__ import annotations

import uuid

import pytest

from app.creator.plan_config import PLANS_BY_SLUG
from app.creator.plan_guards import fallback_creator_plan, resolve_creator_plan
from app.models.creator_billing import CreatorPlan
from app.services.creator_grant_expiry import community_is_the_fallback


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _plan(db, slug: str, cents: int, *, active: bool = True) -> CreatorPlan:
    row = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if row is None:
        row = CreatorPlan(
            id=_uid("cp"), slug=slug,
            name=PLANS_BY_SLUG[slug].display_name if slug in PLANS_BY_SLUG else slug,
            monthly_price_cents=cents, currency="AUD",
            transaction_fee_basis_points=0, collective_limit=1,
            is_active=active,
        )
        db.add(row)
        db.flush()
    return row


@pytest.fixture
def zero_priced_rivals(db):
    """The production shape: three active plans all costing zero.

    Inserted with the rivals **first**, so that if the resolution
    depended on insertion order it would pick the wrong one.
    """
    _plan(db, "founding-creator", 0)
    _plan(db, "organisation", 0)
    community = _plan(db, "community", 0)
    _plan(db, "creator", 1900)
    _plan(db, "pro", 7900)
    db.flush()
    return community


class TestTheFallbackIsCommunity:

    def test_the_cheapest_plan_resolves_to_community(self, db, zero_priced_rivals):
        chosen = fallback_creator_plan(db)
        assert chosen is not None
        assert chosen.slug == "community", (
            f"a creator with no subscription would land on {chosen.slug}"
        )

    def test_it_is_stable_across_repeated_calls(self, db, zero_priced_rivals):
        slugs = {fallback_creator_plan(db).slug for _ in range(20)}
        assert slugs == {"community"}, f"non-deterministic: {slugs}"

    def test_it_survives_the_community_row_being_rewritten(
        self, db, zero_priced_rivals,
    ):
        """An UPDATE moves a row in the heap, which is exactly what
        would flip a physical-order-dependent answer. An admin editing
        the Community plan in World Management does this."""
        community = zero_priced_rivals
        community.description = "edited by an admin"
        db.flush()
        assert fallback_creator_plan(db).slug == "community"

    def test_a_creator_with_no_subscription_gets_community(
        self, db, zero_priced_rivals, make_user,
    ):
        """The behaviour that actually matters — a free creator's
        capabilities, not the row the query returns."""
        creator = make_user(role="creator")
        capability = resolve_creator_plan(creator, db)
        assert capability is not None
        assert capability.slug == "community"
        # And specifically not the unrestricted one.
        assert capability.paid_offers_enabled is False
        assert capability.active_collective_limit == 1

    def test_the_grant_sweep_agrees_with_the_resolution(
        self, db, zero_priced_rivals,
    ):
        """These were two separate copies of the same query and could
        disagree — one halting the whole sweep while the other resolved
        fine, or the reverse."""
        assert community_is_the_fallback(db) is True
        assert fallback_creator_plan(db).slug == "community"

    def test_a_genuinely_cheaper_plan_still_wins(self, db, zero_priced_rivals):
        """The tiebreak must not become a hard-coded preference for
        Community — it only applies among plans at the same price."""
        _plan(db, "cheaper-trial", -100)
        db.flush()
        assert fallback_creator_plan(db).slug == "cheaper-trial"

    def test_an_inactive_community_plan_is_not_chosen(
        self, db, zero_priced_rivals,
    ):
        community = zero_priced_rivals
        community.is_active = False
        db.flush()
        chosen = fallback_creator_plan(db)
        assert chosen is None or chosen.slug != "community"
        # And the sweep correctly refuses to run in that state.
        assert community_is_the_fallback(db) is False

    def test_no_active_plans_at_all_is_handled(self, db):
        for row in db.query(CreatorPlan).all():
            row.is_active = False
        db.flush()
        assert fallback_creator_plan(db) is None
        assert community_is_the_fallback(db) is False


class TestTheUntiedOrderIsGone:

    def test_no_caller_orders_plans_by_price_without_a_tiebreak(self):
        """A source guard. Both original call sites were a single line,
        and a third copy would reintroduce the same coin flip."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        offenders = []
        for path in root.rglob("*.py"):
            code = re.sub(r"(?m)^\s*#.*$", "", path.read_text())
            for match in re.finditer(
                r"order_by\(\s*CreatorPlan\.monthly_price_cents\s*\)", code,
            ):
                offenders.append(f"{path}:{code[:match.start()].count(chr(10)) + 1}")
        assert offenders == [], (
            "an untie-broken plan ordering is back in: " + ", ".join(offenders)
        )
