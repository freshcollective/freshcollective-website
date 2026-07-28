"""
Regression: members of a non-active collective (draft / coming-soon /
archived) must still be able to load and save their own notification
preferences.

The bug: both notification-settings handlers funnelled every request
through ``_get_space_or_404`` — a slug lookup that filters by
``Space.status == 'active'``. World Builders is a draft collective; a
member of it would see a 404 from ``GET /api/spaces/world-builders/
notification-settings`` even though their SpaceMembership was fully
valid. The Stay Connected page surfaced this as "We couldn't load your
preferences for this collective."

The fix: the two notification-settings handlers now use
``_get_space_by_slug_or_404`` (no public-status filter) and let
``_require_membership`` gate access. Public read paths still use
``_get_space_or_404`` and must continue to 404 for draft collectives.

These tests lock in both halves of that contract.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces.routes import (
    _get_space_by_slug_or_404,
    _get_space_or_404,
    get_notification_settings,
    update_notification_settings,
)
from app.spaces.schemas import NotificationPrefsUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_member(
    db,
    *,
    user,
    space,
    role: SpaceRole = SpaceRole.learner,
    status: SpaceMembershipStatus = SpaceMembershipStatus.active,
) -> SpaceMembership:
    m = SpaceMembership(
        id=f"sm_{uuid.uuid4().hex[:10]}",
        user_id=user.id,
        space_id=space.id,
        role=role,
        status=status,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# GET — regression: members of non-active collectives
# ---------------------------------------------------------------------------


def test_get_prefs_returns_200_for_member_of_draft_collective(db, make_user, make_space):
    """Regression for World Builders. A draft collective with a valid
    active membership must load prefs, not 404."""
    user = make_user()
    space = make_space(status="draft")
    _add_member(db, user=user, space=space)

    resp = get_notification_settings(
        slug=space.slug,
        current_user=user,
        db=db,
    )
    assert resp.space_slug == space.slug
    # No prefs row yet — endpoint returns defaults.
    assert resp.weekly_digest_email is True


def test_get_prefs_returns_200_for_member_of_archived_collective(db, make_user, make_space):
    """Reminders for previously-scheduled gatherings may still fire
    against archived collectives — preferences must remain editable."""
    user = make_user()
    space = make_space(status="archived")
    _add_member(db, user=user, space=space)

    resp = get_notification_settings(slug=space.slug, current_user=user, db=db)
    assert resp.space_slug == space.slug


# ---------------------------------------------------------------------------
# PATCH — same fix applies
# ---------------------------------------------------------------------------


def test_patch_prefs_returns_200_and_persists_for_member_of_draft_collective(
    db, make_user, make_space,
):
    user = make_user()
    space = make_space(status="draft")
    _add_member(db, user=user, space=space)

    # Flip one field off (defaults to True).
    payload = NotificationPrefsUpdate(gathering_reminder_email=False)
    resp = update_notification_settings(
        slug=space.slug,
        payload=payload,
        current_user=user,
        db=db,
    )
    assert resp.gathering_reminder_email is False

    # Second read confirms it stuck.
    resp2 = get_notification_settings(slug=space.slug, current_user=user, db=db)
    assert resp2.gathering_reminder_email is False


# ---------------------------------------------------------------------------
# Security — existing behaviour preserved
# ---------------------------------------------------------------------------


def test_get_prefs_returns_403_for_non_member_of_active_collective(db, make_user, make_space):
    """Non-member of an active collective must still be 403 — the
    fix must not weaken security for anonymous prying at active
    collectives."""
    space = make_space(status="active")
    intruder = make_user()  # no membership row

    with pytest.raises(HTTPException) as excinfo:
        get_notification_settings(slug=space.slug, current_user=intruder, db=db)
    assert excinfo.value.status_code == 403


def test_get_prefs_returns_403_for_non_member_of_draft_collective(db, make_user, make_space):
    """A stranger to a draft collective must also be rejected — the
    404-vs-403 semantics change (from status-hiding to membership-based
    gating), but non-members must never see prefs regardless of status."""
    space = make_space(status="draft")
    intruder = make_user()

    with pytest.raises(HTTPException) as excinfo:
        get_notification_settings(slug=space.slug, current_user=intruder, db=db)
    assert excinfo.value.status_code == 403


def test_get_prefs_returns_403_for_removed_member(db, make_user, make_space):
    user = make_user()
    space = make_space(status="active")
    _add_member(db, user=user, space=space, status=SpaceMembershipStatus.removed)

    with pytest.raises(HTTPException) as excinfo:
        get_notification_settings(slug=space.slug, current_user=user, db=db)
    assert excinfo.value.status_code == 403


def test_get_prefs_returns_404_for_unknown_slug(db, make_user):
    user = make_user()
    with pytest.raises(HTTPException) as excinfo:
        get_notification_settings(slug="does-not-exist", current_user=user, db=db)
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# Helper semantics — lock in the difference between the two lookups so a
# future engineer doesn't converge them.
# ---------------------------------------------------------------------------


def test_get_space_by_slug_or_404_returns_draft_that_status_variant_would_hide(
    db, make_space,
):
    space = make_space(status="draft")

    # Public variant hides draft:
    with pytest.raises(HTTPException) as excinfo:
        _get_space_or_404(space.slug, db)
    assert excinfo.value.status_code == 404

    # Slug-only variant returns it — the caller is responsible for
    # gating access with a membership check.
    got = _get_space_by_slug_or_404(space.slug, db)
    assert got.id == space.id


def test_get_space_by_slug_or_404_still_404s_on_unknown_slug(db):
    with pytest.raises(HTTPException) as excinfo:
        _get_space_by_slug_or_404("does-not-exist", db)
    assert excinfo.value.status_code == 404
