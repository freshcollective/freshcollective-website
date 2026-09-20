"""The orientation signals the member Collective Home renders.

The Home is an orientation hub, not a feed. That distinction is the
one this file defends: a real member area keeps its place whether or
not it is busy, so the API must answer "how many upcoming gatherings"
with a truthful zero rather than with an absence the client would have
to interpret. A Collective between terms should read "No upcoming
gatherings", not lose the route to its own archive.

Both values ride on ``SpaceResponse`` — the payload the Collective
layout already fetches — rather than on a new overview endpoint. The
Home would otherwise pull a page of event rows to print one number.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.spaces.routes import get_space


class TestUpcomingGatheringContext:
    def test_a_quiet_collective_reports_zero_not_nothing(
        self, db, make_space,
    ):
        space = make_space(is_public=True)
        db.flush()
        resp = get_space(space.slug, db=db, current_user=None)
        assert resp.upcoming_gathering_count == 0
        assert resp.next_gathering_starts_at is None

    def test_it_counts_upcoming_gatherings_and_names_the_next(
        self, db, make_space, make_event,
    ):
        space = make_space(is_public=True)
        soonest = datetime.utcnow() + timedelta(days=2)
        for offset in (2, 9, 16):
            start = datetime.utcnow() + timedelta(days=offset)
            make_event(
                space=space, title=f"Session {offset}",
                starts_at=start, ends_at=start + timedelta(hours=1),
                is_public=True,
            )
        db.flush()

        resp = get_space(space.slug, db=db, current_user=None)
        assert resp.upcoming_gathering_count == 3
        assert resp.next_gathering_starts_at is not None
        # The soonest, not an arbitrary one.
        assert abs(
            (resp.next_gathering_starts_at - soonest).total_seconds()
        ) < 60 * 60 * 24

    @pytest.mark.parametrize("kwargs,label", [
        ({"is_published": False}, "unpublished"),
        ({"status": "cancelled"}, "cancelled"),
    ])
    def test_it_counts_only_what_a_member_can_attend(
        self, db, make_space, make_event, kwargs, label,
    ):
        space = make_space(is_public=True)
        start = datetime.utcnow() + timedelta(days=3)
        make_event(
            space=space, title=label, starts_at=start,
            ends_at=start + timedelta(hours=1), is_public=True, **kwargs,
        )
        db.flush()

        resp = get_space(space.slug, db=db, current_user=None)
        assert resp.upcoming_gathering_count == 0, (
            f"a {label} gathering was counted as upcoming"
        )
        assert resp.next_gathering_starts_at is None

    def test_a_past_gathering_is_not_upcoming(
        self, db, make_space, make_event,
    ):
        space = make_space(is_public=True)
        past = datetime.utcnow() - timedelta(days=3)
        make_event(
            space=space, title="Last week", starts_at=past,
            ends_at=past + timedelta(hours=1), is_public=True,
        )
        db.flush()

        resp = get_space(space.slug, db=db, current_user=None)
        assert resp.upcoming_gathering_count == 0
        assert resp.next_gathering_starts_at is None

    def test_private_gatherings_still_count_for_members(
        self, db, make_space, make_event,
    ):
        """This payload is the *member* Home's context. A members-only
        gathering is something a member can attend, so it belongs in
        their count — unlike the Discover Places surface, which is
        public and filters to public/paid-separately."""
        space = make_space(is_public=True)
        start = datetime.utcnow() + timedelta(days=4)
        make_event(
            space=space, title="Members only", starts_at=start,
            ends_at=start + timedelta(hours=1),
            is_public=False, booking_access_type="included_with_collective",
        )
        db.flush()

        resp = get_space(space.slug, db=db, current_user=None)
        assert resp.upcoming_gathering_count == 1

    def test_counts_do_not_bleed_between_collectives(
        self, db, make_space, make_event,
    ):
        a = make_space(is_public=True)
        b = make_space(is_public=True)
        start = datetime.utcnow() + timedelta(days=5)
        make_event(
            space=a, title="A only", starts_at=start,
            ends_at=start + timedelta(hours=1), is_public=True,
        )
        db.flush()

        assert get_space(a.slug, db=db, current_user=None).upcoming_gathering_count == 1
        assert get_space(b.slug, db=db, current_user=None).upcoming_gathering_count == 0

    def test_the_home_needs_no_extra_request(self, db, make_space):
        """Everything the tiles show comes off this one payload: the
        member counts, the pathway list, the palette and now the
        gathering signals."""
        space = make_space(is_public=True)
        db.flush()
        resp = get_space(space.slug, db=db, current_user=None)
        for field in (
            "upcoming_gathering_count", "next_gathering_starts_at",
            "learner_count", "leader_count", "pathways",
            "show_member_directory", "colour_palette", "cover_image_url",
        ):
            assert hasattr(resp, field), field
