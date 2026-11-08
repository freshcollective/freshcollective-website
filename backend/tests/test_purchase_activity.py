"""Stage 3E.2 — a purchase shows up in the member's own Your World.

The reported gap: Sophie gained access to a Pathway through her
purchase, and Recent Moments showed that Pathway only because the
creator had published it five days earlier. Two different events were
being read as one.

What this adds is one personal activity per purchase — not one per
grant, which would fill a feed with four unlock notices for a
four-Pathway programme — carrying its own timestamp, visible only to
the person who bought it.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.activity import (
    Activity, ActivityType, CATEGORY_OF, DEFAULT_PRIORITY_OF, RECENT_MOMENTS,
)
from app.services.activity_producers import record_purchase_fulfilled


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def space(make_space):
    return make_space()


def _included(*kinds):
    return [
        {"kind": k, "title": f"{k.title()} {i}", "url": f"/x/{i}",
         "status": "Your access is now available", "starts_at": None}
        for i, k in enumerate(kinds)
    ]


def _rows(db, user_id):
    return (
        db.query(Activity)
        .filter(
            Activity.recipient_user_id == user_id,
            Activity.event_type == ActivityType.purchase_fulfilled.value,
        )
        .all()
    )


class TestTheEventExists:
    def test_the_type_is_registered_everywhere(self):
        """The model asserts these maps cover every type; this says
        the new one is also a Recent Moment, which is what makes it
        appear."""
        assert ActivityType.purchase_fulfilled in CATEGORY_OF
        assert ActivityType.purchase_fulfilled in DEFAULT_PRIORITY_OF
        assert ActivityType.purchase_fulfilled in RECENT_MOMENTS

    def test_a_purchase_creates_one_entry(self, db, space, make_user):
        buyer = make_user()
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Test Gathering Experience",
            included=_included("gathering", "pathway"),
            dedupe_id=_uid("txn"),
        )
        [row] = _rows(db, buyer.id)
        assert row.payload["title"] == "Test Gathering Experience"
        assert row.collective_id == space.id

    def test_one_entry_per_purchase_not_per_grant(
        self, db, space, make_user,
    ):
        """A four-Pathway programme is one thing somebody bought, not
        four notices."""
        buyer = make_user()
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Natural Leader Experience",
            included=_included(
                "pathway", "pathway", "pathway", "pathway", "gathering",
            ),
            dedupe_id=_uid("txn"),
        )
        rows = _rows(db, buyer.id)
        assert len(rows) == 1
        assert rows[0].payload["counts"] == {"pathway": 4, "gathering": 1}

    def test_the_included_experiences_are_discoverable(
        self, db, space, make_user,
    ):
        buyer = make_user()
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Bundle", included=_included("pathway", "gathering"),
            dedupe_id=_uid("txn"),
        )
        [row] = _rows(db, buyer.id)
        assert len(row.payload["included"]) == 2
        assert all(i.get("url") for i in row.payload["included"])
        assert row.payload["url"], "nowhere to go"


class TestItIsPrivateAndIdempotent:
    def test_a_redelivered_webhook_adds_nothing(
        self, db, space, make_user,
    ):
        """Stripe redelivers. A second entry for one purchase is the
        failure to avoid."""
        buyer = make_user()
        txn_id = _uid("txn")
        for _ in range(3):
            record_purchase_fulfilled(
                db, member_user_id=buyer.id, space_id=space.id,
                option_name="Bundle", included=_included("pathway"),
                dedupe_id=txn_id,
            )
        assert len(_rows(db, buyer.id)) == 1

    def test_two_different_purchases_each_get_one(
        self, db, space, make_user,
    ):
        buyer = make_user()
        for _ in range(2):
            record_purchase_fulfilled(
                db, member_user_id=buyer.id, space_id=space.id,
                option_name="Bundle", included=_included("pathway"),
                dedupe_id=_uid("txn"),
            )
        assert len(_rows(db, buyer.id)) == 2

    def test_the_entry_belongs_to_the_buyer_alone(
        self, db, space, make_user,
    ):
        """Privacy is structural: the feed filters on
        ``recipient_user_id``, so another member's query cannot reach
        this row."""
        buyer = make_user()
        other = make_user()
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Bundle", included=_included("pathway"),
            dedupe_id=_uid("txn"),
        )
        assert len(_rows(db, buyer.id)) == 1
        assert _rows(db, other.id) == []

    def test_the_buyer_is_the_recipient_not_the_actor(
        self, db, space, make_user,
    ):
        """``create_for_recipients`` skips a self-notify when the actor
        is also the recipient — right for "X replied to you", wrong
        here, where the member is exactly who should be told."""
        buyer = make_user()
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Bundle", included=_included("pathway"),
            dedupe_id=_uid("txn"),
        )
        [row] = _rows(db, buyer.id)
        assert row.recipient_user_id == buyer.id
        assert row.actor_user_id is None


class TestPurchaseIsNotPublication:
    def test_it_carries_its_own_timestamp(self, db, space, make_user):
        """§10: do not backdate a purchase to the day an included
        experience was published."""
        from datetime import datetime, timedelta

        buyer = make_user()
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Bundle", included=_included("pathway"),
            dedupe_id=_uid("txn"),
        )
        [row] = _rows(db, buyer.id)
        assert row.created_at >= datetime.utcnow() - timedelta(minutes=5)

    def test_publication_activity_is_a_different_event_type(self):
        """Both exist, and neither is rewritten to look like the
        other."""
        assert ActivityType.purchase_fulfilled != ActivityType.pathway_published
        assert ActivityType.pathway_published in RECENT_MOMENTS

    def test_a_publication_entry_is_untouched_by_a_purchase(
        self, db, space, make_user,
    ):
        """The Pathway's own moment keeps its date and its audience."""
        from app.services.activity_service import ActivityService

        buyer = make_user()
        before = (
            db.query(Activity)
            .filter(Activity.event_type == ActivityType.pathway_published.value)
            .count()
        )
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Bundle", included=_included("pathway"),
            dedupe_id=_uid("txn"),
        )
        after = (
            db.query(Activity)
            .filter(Activity.event_type == ActivityType.pathway_published.value)
            .count()
        )
        assert before == after


class TestExistingAccessIsNotCalledNew:
    def test_the_entry_carries_the_statuses_the_summary_produced(
        self, db, space, make_user,
    ):
        """§11: a Pathway the member already owned is listed as
        included, not announced as unlocked. The wording comes from
        the Stage 3E.1 summary, so there is one place that decides
        it."""
        buyer = make_user()
        included = [
            {"kind": "pathway", "title": "Know Yourself", "url": "/a",
             "status": "Already in your collection", "starts_at": None},
            {"kind": "pathway", "title": "Embrace Yourself", "url": "/b",
             "status": "Your access is now available", "starts_at": None},
        ]
        record_purchase_fulfilled(
            db, member_user_id=buyer.id, space_id=space.id,
            option_name="Personal Leadership Collection",
            included=included, dedupe_id=_uid("txn"),
        )
        [row] = _rows(db, buyer.id)
        statuses = {i["status"] for i in row.payload["included"]}
        assert "Already in your collection" in statuses
        assert "Your access is now available" in statuses

    def test_a_failure_never_blocks_the_purchase(
        self, db, space, make_user,
    ):
        """Activity is a nicety; fulfilment is not. A broken entry must
        not cost somebody the thing they paid for."""
        record_purchase_fulfilled(
            db, member_user_id="nobody", space_id=space.id,
            option_name="Bundle", included=None, dedupe_id=_uid("txn"),
        )
        # Swallowed, not raised.
        assert True
