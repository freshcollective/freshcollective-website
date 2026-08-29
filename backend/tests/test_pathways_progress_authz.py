"""SEC-004 — pathway-progress authorisation regression tests.

Locks in the authorisation model for
``GET /api/spaces/{slug}/pathways-progress``:

- Unauthenticated → dependency rejects (verified in the callers, not here;
  ``get_current_user`` is exercised by the route dispatcher, not the
  handler under test).
- Authenticated non-member → 404 (matches the privacy stance of
  ``_get_space_visible_to``; refuses to acknowledge the Space's
  existence).
- Regular active member → 200 with published pathways only
  (``status in ('active', 'coming_soon')``).
- Space owner / Space moderator / platform admin / platform-role
  creator → 200 with every pathway (draft and archived included) — the
  "manager" visibility the existing ``list_pathways`` already grants.
- Completion counts remain scoped to ``current_user.id``; another
  user's ``StepProgress`` is never surfaced in the response.

Route is exercised directly (as other tests in this suite do); the
authorisation logic lives in the handler + ``_get_member_space``, so
we don't need TestClient / cookie plumbing.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

# Ensure User's community_care FKs resolve in isolation, matching the
# pattern used by test_places_routes.py.
import app.models.community_care  # noqa: F401
from app.models.platform import (
    Pathway,
    PathwayStatus,
    PathwayStep,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepProgress,
)
from app.spaces.routes import list_pathways_progress


# ---------------------------------------------------------------------------
# Helpers scoped to this file
# ---------------------------------------------------------------------------

def _mk_pathway(db, *, space, slug, title, status, position):
    p = Pathway(
        id=f"pw_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        slug=slug,
        title=title,
        status=status,
        position=position,
        access_type="free",
    )
    db.add(p)
    db.flush()
    return p


def _mk_step(db, *, pathway, slug="step-a", position=0):
    s = PathwayStep(
        id=f"st_{uuid.uuid4().hex[:12]}",
        pathway_id=pathway.id,
        slug=slug,
        title="Step",
        position=position,
    )
    db.add(s)
    db.flush()
    return s


def _add_membership(db, *, user, space, role=SpaceRole.learner,
                    status=SpaceMembershipStatus.active):
    m = SpaceMembership(
        id=f"sm_{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        space_id=space.id,
        role=role,
        status=status,
        joined_at=datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def space_with_pathways(db, make_space):
    """A Space with one active + one coming_soon + one draft + one
    archived pathway. Owned by a distinct creator user (space.creator)
    who is different from any test caller."""
    space = make_space()
    active = _mk_pathway(db, space=space, slug="p-active",
                         title="Active Pathway", status=PathwayStatus.active,
                         position=0)
    coming = _mk_pathway(db, space=space, slug="p-coming",
                         title="Coming Soon Pathway",
                         status=PathwayStatus.coming_soon, position=1)
    draft = _mk_pathway(db, space=space, slug="p-draft",
                        title="Draft Pathway", status=PathwayStatus.draft,
                        position=2)
    archived = _mk_pathway(db, space=space, slug="p-archived",
                           title="Archived Pathway",
                           status=PathwayStatus.archived, position=3)
    return {"space": space, "active": active, "coming": coming,
            "draft": draft, "archived": archived}


def _slugs(rows) -> set[str]:
    return {r.slug for r in rows}


# ---------------------------------------------------------------------------
# Non-member paths — SEC-004's original leak
# ---------------------------------------------------------------------------

class TestNonMemberDenial:
    def test_authenticated_non_member_gets_404(self, db, make_user,
                                                space_with_pathways):
        """The exploit that motivated SEC-004: a signed-in user with
        zero relationship to the Space could enumerate every pathway
        including drafts and archives. Post-fix: 404."""
        stranger = make_user(role="user")
        with pytest.raises(HTTPException) as exc:
            list_pathways_progress(
                slug=space_with_pathways["space"].slug,
                db=db,
                current_user=stranger,
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Space not found."

    def test_non_member_of_private_link_only_space_gets_404(
        self, db, make_user, make_space,
    ):
        """Private / link-only Collectives (is_public=False, e.g. the
        auto-grant World Builders row) must not be enumerable by slug
        guessing through this endpoint."""
        private = make_space(is_public=False)
        _mk_pathway(db, space=private, slug="p-secret",
                    title="Secret Draft", status=PathwayStatus.draft,
                    position=0)
        stranger = make_user(role="user")
        with pytest.raises(HTTPException) as exc:
            list_pathways_progress(
                slug=private.slug, db=db, current_user=stranger,
            )
        assert exc.value.status_code == 404

    def test_bad_slug_returns_404_not_information_leak(
        self, db, make_user,
    ):
        """A guessed slug that does not resolve at all must be
        indistinguishable from 'slug exists but you cannot see it'."""
        stranger = make_user(role="user")
        with pytest.raises(HTTPException) as exc:
            list_pathways_progress(
                slug="definitely-does-not-exist-xyz",
                db=db,
                current_user=stranger,
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Regular member — sees only published pathways
# ---------------------------------------------------------------------------

class TestRegularMember:
    def test_member_sees_active_and_coming_soon_only(
        self, db, make_user, space_with_pathways,
    ):
        member = make_user(role="user")
        _add_membership(db, user=member, space=space_with_pathways["space"])

        rows = list_pathways_progress(
            slug=space_with_pathways["space"].slug,
            db=db,
            current_user=member,
        )
        got = _slugs(rows)
        assert "p-active" in got
        assert "p-coming" in got
        # Draft and archived MUST be hidden from a regular member.
        assert "p-draft" not in got
        assert "p-archived" not in got

    def test_member_of_private_space_sees_only_published(
        self, db, make_user, make_space,
    ):
        """Regression against SEC-004's private-space leak: even a
        legitimate member of a private space should see only the
        published pathways."""
        private = make_space(is_public=False)
        _mk_pathway(db, space=private, slug="p-published",
                    title="Published", status=PathwayStatus.active,
                    position=0)
        _mk_pathway(db, space=private, slug="p-draft",
                    title="Draft", status=PathwayStatus.draft,
                    position=1)
        member = make_user(role="user")
        _add_membership(db, user=member, space=private)

        got = _slugs(list_pathways_progress(
            slug=private.slug, db=db, current_user=member,
        ))
        assert got == {"p-published"}

    def test_member_progress_counts_scope_to_caller_only(
        self, db, make_user, space_with_pathways,
    ):
        """Completion counts must reflect only current_user.id — never
        another user's StepProgress."""
        alice = make_user(role="user")
        bob = make_user(role="user")
        _add_membership(db, user=alice, space=space_with_pathways["space"])
        _add_membership(db, user=bob, space=space_with_pathways["space"])

        # Give the active pathway two steps.
        step_a = _mk_step(db, pathway=space_with_pathways["active"],
                          slug="s-a", position=0)
        step_b = _mk_step(db, pathway=space_with_pathways["active"],
                          slug="s-b", position=1)

        # Bob completes both steps. Alice completes only one.
        for s in (step_a, step_b):
            db.add(StepProgress(
                id=f"sp_{uuid.uuid4().hex[:12]}",
                user_id=bob.id, step_id=s.id,
                completed_at=datetime.utcnow(),
            ))
        db.add(StepProgress(
            id=f"sp_{uuid.uuid4().hex[:12]}",
            user_id=alice.id, step_id=step_a.id,
            completed_at=datetime.utcnow(),
        ))
        db.flush()

        # Alice's response must show her own single completion, never
        # Bob's two.
        rows = list_pathways_progress(
            slug=space_with_pathways["space"].slug, db=db, current_user=alice,
        )
        active_row = next(r for r in rows if r.slug == "p-active")
        assert active_row.step_count == 2
        assert active_row.completed_count == 1


# ---------------------------------------------------------------------------
# Managers — space owner, space creator/moderator, platform admin,
# platform-role creator (existing model bypass — see helper docstring).
# ---------------------------------------------------------------------------

class TestManagerVisibility:
    def test_space_owner_sees_every_pathway_including_draft_archived(
        self, db, space_with_pathways,
    ):
        # ``make_space`` created the Space with a dedicated creator
        # (space.creator_id). That user is the owner.
        owner_id = space_with_pathways["space"].creator_id
        from app.models.user import User
        owner = db.query(User).filter(User.id == owner_id).one()

        got = _slugs(list_pathways_progress(
            slug=space_with_pathways["space"].slug, db=db, current_user=owner,
        ))
        assert got == {"p-active", "p-coming", "p-draft", "p-archived"}

    def test_space_creator_membership_role_sees_all(
        self, db, make_user, space_with_pathways,
    ):
        """SpaceMembership.role='creator' (space-level) grants manager
        visibility even when the caller is not the space owner and has
        no platform-level role."""
        mod = make_user(role="user")
        _add_membership(db, user=mod, space=space_with_pathways["space"],
                        role=SpaceRole.creator)

        got = _slugs(list_pathways_progress(
            slug=space_with_pathways["space"].slug, db=db, current_user=mod,
        ))
        assert "p-draft" in got and "p-archived" in got

    def test_space_moderator_membership_role_sees_all(
        self, db, make_user, space_with_pathways,
    ):
        mod = make_user(role="user")
        _add_membership(db, user=mod, space=space_with_pathways["space"],
                        role=SpaceRole.moderator)

        got = _slugs(list_pathways_progress(
            slug=space_with_pathways["space"].slug, db=db, current_user=mod,
        ))
        assert "p-draft" in got and "p-archived" in got

    def test_platform_admin_sees_all_without_membership(
        self, db, make_user, space_with_pathways,
    ):
        """Platform admin has no SpaceMembership in this test — the
        manager visibility comes solely from user.role='admin'."""
        admin = make_user(role="admin")
        got = _slugs(list_pathways_progress(
            slug=space_with_pathways["space"].slug, db=db, current_user=admin,
        ))
        assert got == {"p-active", "p-coming", "p-draft", "p-archived"}

    def test_platform_role_creator_sees_all_without_membership(
        self, db, make_user, space_with_pathways,
    ):
        """DOCUMENTED EXISTING BEHAVIOUR — reported to the operator.
        The surrounding code (``_check_pathway_access`` and
        ``_compute_pathway_access``) treats any user with
        ``role='creator'`` as having platform-wide pathway access.
        SEC-004 fix mirrors that model — deliberately not narrowed
        here to avoid drift between the two boundaries. If the
        product decides to narrow this later, all three sites should
        change together and be governed by a new test that pins the
        stricter rule."""
        platform_creator = make_user(role="creator")
        got = _slugs(list_pathways_progress(
            slug=space_with_pathways["space"].slug, db=db,
            current_user=platform_creator,
        ))
        assert got == {"p-active", "p-coming", "p-draft", "p-archived"}


# ---------------------------------------------------------------------------
# Removed / non-active membership does NOT count as membership
# ---------------------------------------------------------------------------

class TestMembershipStatusEnforcement:
    def test_removed_membership_gets_404(
        self, db, make_user, space_with_pathways,
    ):
        """A member whose status is not 'active' must not be treated
        as a member."""
        former = make_user(role="user")
        _add_membership(
            db, user=former, space=space_with_pathways["space"],
            status=SpaceMembershipStatus.removed,
        )
        with pytest.raises(HTTPException) as exc:
            list_pathways_progress(
                slug=space_with_pathways["space"].slug, db=db,
                current_user=former,
            )
        assert exc.value.status_code == 404

    def test_paused_membership_gets_404(
        self, db, make_user, space_with_pathways,
    ):
        paused = make_user(role="user")
        _add_membership(
            db, user=paused, space=space_with_pathways["space"],
            status=SpaceMembershipStatus.paused,
        )
        with pytest.raises(HTTPException) as exc:
            list_pathways_progress(
                slug=space_with_pathways["space"].slug, db=db,
                current_user=paused,
            )
        assert exc.value.status_code == 404
