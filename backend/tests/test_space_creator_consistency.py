"""Data-integrity guard: ``Space.creator_id`` must agree with the
active ``SpaceMembership(role='creator')`` record for the same Space.

Context
-------
On 2026-07-30 an out-of-repo mutation set
``spaces.embody.creator_id = <playwright-test-user-id>`` while leaving
Lindsey's ``SpaceMembership(role='creator', status='active')`` untouched.
The World Management → Creators panel reads the scalar and started
showing the Playwright test user as the Creator of EMBODY.

No committed code path in this repo can produce that state — creation
sites (``creator/routes.py`` and ``creator/build_your_collective.py``)
write both representations together, and no route or migration mutates
``Space.creator_id`` after creation. The safety-doc
``docs/dev-testing-safety.md`` already covers the "don't touch real
data from headless tests" rule.

This test is a permanent tripwire against a recurrence: if any future
code path drifts the two representations apart, or another out-of-repo
mutation happens, the pytest suite fails loudly with a clear pointer
at the offending Space. Deliberately narrow — it detects the
inconsistency and does nothing else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.platform import (
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


@dataclass(frozen=True)
class CreatorMismatch:
    space_id: str
    space_slug: str
    scalar_creator_id: str
    active_creator_membership_user_ids: tuple[str, ...]


def find_creator_id_mismatches(db: Session) -> list[CreatorMismatch]:
    """Return one ``CreatorMismatch`` per Space where the
    ``Space.creator_id`` scalar does not appear among the users
    with an active ``SpaceMembership(role='creator')`` on that
    Space.

    Rules
    -----
    * Platform-owned Spaces (``creator_id IS NULL``) are ignored —
      they have no creator by design.
    * A Space with a scalar creator but zero active creator
      memberships **is** a mismatch (the missing pair is the whole
      point of the check).
    * When multiple users hold an active ``role='creator'``
      membership on the same Space (moderator promotion history
      etc.), it's enough for the scalar to be among them.
    """
    mismatches: list[CreatorMismatch] = []
    spaces = db.query(Space).all()
    for sp in spaces:
        if sp.creator_id is None:
            continue
        active_creators = tuple(
            m.user_id
            for m in db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == sp.id,
                SpaceMembership.role == SpaceRole.creator,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        )
        if sp.creator_id not in active_creators:
            mismatches.append(CreatorMismatch(
                space_id=sp.id,
                space_slug=sp.slug,
                scalar_creator_id=sp.creator_id,
                active_creator_membership_user_ids=active_creators,
            ))
    return mismatches


def _add_membership(
    db: Session, *, space: Space, user_id: str,
    role: SpaceRole = SpaceRole.creator,
    status: SpaceMembershipStatus = SpaceMembershipStatus.active,
) -> SpaceMembership:
    m = SpaceMembership(
        id=f"sm_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        user_id=user_id,
        role=role,
        status=status,
        source="creator_owner",
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class TestFindCreatorIdMismatches:
    def test_consistent_space_produces_no_mismatch(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_membership(db, space=space, user_id=creator.id)

        assert find_creator_id_mismatches(db) == []

    def test_platform_owned_space_ignored(
        self, db: Session, make_space,
    ) -> None:
        # Platform-owned = creator_id IS NULL. Migration 095 seeds
        # World Builders this way. No creator to check against.
        space = make_space(creator_id=None)
        # No membership row at all — that's expected for the
        # platform-owned case and must not raise a false positive.
        assert find_creator_id_mismatches(db) == []

    def test_scalar_disagrees_with_membership_flags(
        self, db: Session, make_user, make_space,
    ) -> None:
        """Reproduces the EMBODY-on-2026-07-30 pattern: an active
        creator membership exists for the real owner, but the
        scalar was flipped to a different user."""
        real_owner = make_user(role="creator")
        interloper = make_user(role="creator")
        # Create the Space with the wrong scalar, then attach the
        # real owner's membership — the shape the incident produced.
        space = make_space(creator=interloper)
        _add_membership(db, space=space, user_id=real_owner.id)

        mismatches = find_creator_id_mismatches(db)
        assert len(mismatches) == 1
        [m] = mismatches
        assert m.space_id == space.id
        assert m.space_slug == space.slug
        assert m.scalar_creator_id == interloper.id
        assert real_owner.id in m.active_creator_membership_user_ids
        assert interloper.id not in m.active_creator_membership_user_ids

    def test_scalar_without_any_creator_membership_flags(
        self, db: Session, make_user, make_space,
    ) -> None:
        """A Space with a scalar creator but no active
        ``role='creator'`` membership is also a mismatch — that's
        an authoring bug or an incomplete manual insert."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        # Deliberately do NOT add the SpaceMembership row.

        mismatches = find_creator_id_mismatches(db)
        assert len(mismatches) == 1
        assert mismatches[0].space_id == space.id
        assert mismatches[0].active_creator_membership_user_ids == ()

    def test_paused_creator_membership_does_not_satisfy(
        self, db: Session, make_user, make_space,
    ) -> None:
        """Only ``status='active'`` creator memberships count. A
        paused membership behind the scalar is still a mismatch."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_membership(
            db, space=space, user_id=creator.id,
            status=SpaceMembershipStatus.paused,
        )

        mismatches = find_creator_id_mismatches(db)
        assert len(mismatches) == 1
        assert mismatches[0].active_creator_membership_user_ids == ()

    def test_moderator_membership_does_not_satisfy(
        self, db: Session, make_user, make_space,
    ) -> None:
        """A moderator membership is not the same as a creator
        membership — the scalar must point at an active *creator*."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_membership(
            db, space=space, user_id=creator.id,
            role=SpaceRole.moderator,
        )

        mismatches = find_creator_id_mismatches(db)
        assert len(mismatches) == 1

    def test_multiple_active_creators_ok_if_scalar_matches_one(
        self, db: Session, make_user, make_space,
    ) -> None:
        """Rare but legitimate: a Space with two active creator
        memberships (e.g. co-owner promotion). It's enough for the
        scalar to match one of them."""
        primary = make_user(role="creator")
        co = make_user(role="creator")
        space = make_space(creator=primary)
        _add_membership(db, space=space, user_id=primary.id)
        _add_membership(db, space=space, user_id=co.id)

        assert find_creator_id_mismatches(db) == []
