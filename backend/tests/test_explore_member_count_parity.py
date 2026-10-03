"""Explore and About must count members the same way.

The production report
---------------------
On the live site EMBODY showed "1 member" on the Explore Collectives
card and "4 members" on its own public About page. Both numbers were
correct about what they measured; only one was measuring membership.

  * About      — ``COUNT(SpaceMembership WHERE active AND role=learner)``
  * Admin      — the same predicate, independently
  * **Explore** — ``COUNT(DISTINCT Enrollment.user_id)`` joined through
    the Collective's Pathways

Enrolment is not how most people belong. EMBODY's Pathways are
``included_with_offer``: access arrives with a pass, so a member holds a
SpaceMembership and may never create an Enrollment row. The Explore
count therefore reported on whoever had started a Pathway, and drifted
further from the truth the more access was sold that way.

Explore was the outlier of three surfaces, so it moved. The semantics
themselves are unchanged — this file pins the agreement rather than the
new number, because a count that two surfaces derive separately is a
count that can diverge again.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.platform import (
    Enrollment,
    Pathway,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces.routes import get_space, hydrate_public_space_cards


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _member(db, space, user, *, role=SpaceRole.learner,
            status=SpaceMembershipStatus.active) -> SpaceMembership:
    m = SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _pathway(db, space, *, title="Included Pathway") -> Pathway:
    """A Pathway whose access arrives with an offer — the EMBODY shape,
    where members need no Enrollment row to belong."""
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status="active",
        access_type="included_with_offer",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy",
        currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def embody_shaped(db, make_user, make_space):
    """EMBODY as production holds it: four active learners, one leader,
    two offer-included Pathways, and only ONE person who ever started a
    Pathway."""
    creator = make_user(role="creator")
    space = make_space(creator=creator, status="active", is_public=True,
                       auto_grant_role=None)
    db.flush()

    _member(db, space, creator, role=SpaceRole.creator)
    learners = [make_user() for _ in range(4)]
    for learner in learners:
        _member(db, space, learner)

    first, second = _pathway(db, space), _pathway(db, space, title="Home Practice")
    # Exactly one of the four has an Enrollment — the old count's answer.
    db.add(Enrollment(
        id=_uid("en"), user_id=learners[0].id, pathway_id=first.id,
    ))
    db.flush()
    return space, creator, learners, (first, second)


def _card(db, space):
    [card] = hydrate_public_space_cards([space], db)
    return card


def _about(db, space):
    return get_space(space.slug, db=db, current_user=None)


# ---------------------------------------------------------------------------
# The reported bug
# ---------------------------------------------------------------------------


class TestTheReportedMismatch:
    def test_explore_shows_four_members_not_one(self, db, embody_shaped):
        """The headline. Four active learners, one enrolled, and Explore
        says four."""
        space, _creator, _learners, _pathways = embody_shaped

        assert _card(db, space).member_count == 4

    def test_about_still_shows_four(self, db, embody_shaped):
        """The surface that was already right must not move."""
        space, _creator, _learners, _pathways = embody_shaped

        assert _about(db, space).learner_count == 4

    def test_the_two_surfaces_agree(self, db, embody_shaped):
        """Stated as an equivalence rather than two constants, so a
        future change to either definition fails here."""
        space, _creator, _learners, _pathways = embody_shaped

        assert _card(db, space).member_count == _about(db, space).learner_count

    def test_enrolment_no_longer_decides_the_count(self, db, embody_shaped):
        """The root cause, pinned. Enrolling two more of the existing
        members changes nothing: they already belonged."""
        space, _creator, learners, pathways = embody_shaped
        before = _card(db, space).member_count

        for learner in learners[1:3]:
            db.add(Enrollment(
                id=_uid("en"), user_id=learner.id, pathway_id=pathways[1].id,
            ))
        db.flush()

        assert _card(db, space).member_count == before == 4

    def test_a_collective_with_no_pathways_still_counts_members(
        self, db, make_user, make_space,
    ):
        """The old query joined through Pathway, so a Collective with no
        Pathways reported zero members however many it had."""
        space = make_space(status="active", is_public=True, auto_grant_role=None)
        db.flush()
        for _ in range(3):
            _member(db, space, make_user())

        assert _card(db, space).member_count == 3
        assert _about(db, space).learner_count == 3


# ---------------------------------------------------------------------------
# Leaders stay separate
# ---------------------------------------------------------------------------


class TestLeadersAreNotFoldedIn:
    def test_the_leader_is_not_counted_as_a_member(self, db, embody_shaped):
        """"4 members · 1 leader" is two facts. The creator holds an
        active membership too, and must not inflate the member count."""
        space, _creator, _learners, _pathways = embody_shaped

        assert _card(db, space).member_count == 4
        assert _about(db, space).leader_count == 1

    def test_leader_count_is_unchanged_by_this_fix(self, db, embody_shaped):
        space, _creator, _learners, _pathways = embody_shaped
        assert _about(db, space).leader_count == 1

    def test_a_moderator_counts_as_a_leader_not_a_member(
        self, db, embody_shaped, make_user,
    ):
        space, _creator, _learners, _pathways = embody_shaped
        _member(db, space, make_user(), role=SpaceRole.moderator)

        assert _card(db, space).member_count == 4
        assert _about(db, space).leader_count == 2


# ---------------------------------------------------------------------------
# Membership status is respected
# ---------------------------------------------------------------------------


class TestOnlyActiveMembershipsCount:
    @pytest.mark.parametrize("status", [
        SpaceMembershipStatus.paused,
        SpaceMembershipStatus.removed,
    ])
    def test_a_non_active_membership_is_not_a_member(
        self, db, embody_shaped, make_user, status,
    ):
        """Same status rule the About page applies. Someone paused, or
        removed, is not a member on either surface."""
        space, _creator, _learners, _pathways = embody_shaped
        _member(db, space, make_user(), status=status)

        assert _card(db, space).member_count == 4
        assert _about(db, space).learner_count == 4

    def test_a_member_of_another_collective_is_not_counted(
        self, db, embody_shaped, make_user, make_space,
    ):
        """The old query filtered by ``Pathway.space_id``; the new one
        filters by ``SpaceMembership.space_id``. Scoping must hold."""
        space, _creator, _learners, _pathways = embody_shaped
        other = make_space(status="active", is_public=True, auto_grant_role=None)
        db.flush()
        for _ in range(5):
            _member(db, other, make_user())

        assert _card(db, space).member_count == 4
        assert _card(db, other).member_count == 5


# ---------------------------------------------------------------------------
# Nothing else about the card moved
# ---------------------------------------------------------------------------


class TestTheRestOfTheCardIsUnchanged:
    def test_pathway_count_is_untouched(self, db, embody_shaped):
        space, _creator, _learners, _pathways = embody_shaped

        assert _card(db, space).pathway_count == 2

    def test_a_collective_with_no_members_reports_zero(
        self, db, make_space,
    ):
        """``.get(space_id, 0)`` — a Collective absent from the mapping
        is zero, not a KeyError, and the card hides the label at zero."""
        space = make_space(status="active", is_public=True, auto_grant_role=None)
        db.flush()

        assert _card(db, space).member_count == 0

    def test_many_collectives_are_counted_in_one_query(
        self, db, make_user, make_space,
    ):
        """The listing hydrates every public Collective at once. The new
        count is still one grouped query, not one per Collective."""
        from sqlalchemy import event

        spaces = []
        for n in range(4):
            s = make_space(status="active", is_public=True, auto_grant_role=None)
            db.flush()
            for _ in range(n + 1):
                _member(db, s, make_user())
            spaces.append(s)

        db.expire_all()
        n_queries = 0

        def _count(*_a, **_k):
            nonlocal n_queries
            n_queries += 1

        event.listen(db.get_bind(), "before_cursor_execute", _count)
        try:
            cards = hydrate_public_space_cards(spaces, db)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _count)

        assert [c.member_count for c in cards] == [1, 2, 3, 4]
        # Generous bound: the point is that it does not scale with the
        # number of Collectives, not the exact constant.
        assert n_queries < 20, f"{n_queries} queries for 4 Collectives"


# ---------------------------------------------------------------------------
# Privacy is unchanged
# ---------------------------------------------------------------------------


class TestNoPrivacyRuleIsWeakened:
    def test_the_count_was_already_public_on_both_surfaces(
        self, db, embody_shaped,
    ):
        """This fix changes WHICH number is public, not WHETHER one is.
        Both endpoints already published a member count to signed-out
        callers, and both still do."""
        space, _creator, _learners, _pathways = embody_shaped

        assert _card(db, space).member_count == 4
        assert _about(db, space).learner_count == 4

    def test_no_member_identity_is_exposed(self, db, embody_shaped):
        """A count, not a roster. The card carries no user ids, names or
        emails — the member directory stays behind its own endpoint and
        its own ``show_member_directory`` gate."""
        space, _creator, learners, _pathways = embody_shaped
        card = _card(db, space)

        dumped = card.model_dump()
        assert 'members' not in dumped
        blob = str(dumped)
        for learner in learners:
            assert learner.id not in blob
            if learner.email:
                assert learner.email not in blob

    def test_the_directory_setting_does_not_change_the_count(
        self, db, embody_shaped,
    ):
        """``show_member_directory`` gates the member LIST, never the
        aggregate — that separation is why the About page reads counts
        from the DB rather than from the privacy-filtered list. Flipping
        it must not move either number."""
        space, _creator, _learners, _pathways = embody_shaped
        space.show_member_directory = False
        db.flush()

        assert _card(db, space).member_count == 4
        assert _about(db, space).learner_count == 4
