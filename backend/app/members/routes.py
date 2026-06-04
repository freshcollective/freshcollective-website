from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.models.platform import CreatorProfile, Space, SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.models.user import User
from app.members.schemas import MemberProfile, PublicProfile

members_router = APIRouter(prefix="/api/spaces", tags=["members"])
profiles_router = APIRouter(prefix="/api/profile", tags=["profiles"])

ROLE_PRIORITY = {"creator": 0, "moderator": 1, "learner": 2}


def _get_space_or_404(slug: str, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _display_name(user: User, creator_profile: CreatorProfile | None) -> str:
    if creator_profile and creator_profile.display_name:
        return creator_profile.display_name
    return user.name or user.email.split("@")[0]


# ---------------------------------------------------------------------------
# Space members
# ---------------------------------------------------------------------------

@members_router.get("/{slug}/members", response_model=list[MemberProfile])
def list_members(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[MemberProfile]:
    """Return active Space members — creators/moderators first, then learners.

    When show_member_directory=False and the caller is a learner, only
    creators and moderators are returned (learners remain hidden).
    """
    space = _get_space_or_404(slug, db)
    if not space.is_public and current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    # Determine the caller's role to apply directory privacy
    caller_role: str | None = None
    if current_user:
        caller_membership = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
        if caller_membership:
            caller_role = (
                caller_membership.role.value
                if hasattr(caller_membership.role, "value")
                else str(caller_membership.role)
            )

    hide_learners = (
        not getattr(space, 'show_member_directory', True)
        and caller_role == "learner"
    )

    membership_filter = [
        SpaceMembership.space_id == space.id,
        SpaceMembership.status == "active",
    ]
    if hide_learners:
        membership_filter.append(SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]))

    rows = (
        db.query(SpaceMembership, User, CreatorProfile)
        .join(User, User.id == SpaceMembership.user_id)
        .outerjoin(
            CreatorProfile,
            and_(
                CreatorProfile.user_id == User.id,
                CreatorProfile.is_public.is_(True),
            ),
        )
        .filter(*membership_filter)
        .all()
    )

    members = [
        MemberProfile(
            id=user.id,
            display_name=_display_name(user, cp),
            avatar_url=cp.avatar_url if cp else None,
            space_role=(
                membership.role.value
                if hasattr(membership.role, "value")
                else str(membership.role)
            ),
            joined_at=membership.joined_at,
            bio=cp.bio if cp else None,
            profile_tagline=cp.profile_tagline if cp else None,
            is_creator=cp is not None,
        )
        for membership, user, cp in rows
    ]

    # Sort: creators first, then moderators, then learners; within group by joined_at
    members.sort(key=lambda m: (ROLE_PRIORITY.get(m.space_role, 9), m.joined_at))
    return members


# ---------------------------------------------------------------------------
# Public profiles
# ---------------------------------------------------------------------------

@profiles_router.get("/{user_id}", response_model=PublicProfile)
def get_profile(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicProfile:
    """Return a user's public platform profile."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    cp = (
        db.query(CreatorProfile)
        .filter(
            CreatorProfile.user_id == user.id,
            CreatorProfile.is_public.is_(True),
        )
        .first()
    )

    spaces_led: list[str] = []
    if cp:
        spaces_led = [
            s.name
            for s in db.query(Space.name)
            .filter(Space.creator_id == user.id, Space.status == "active")
            .all()
        ]

    return PublicProfile(
        id=user.id,
        display_name=_display_name(user, cp),
        avatar_url=cp.avatar_url if cp else None,
        bio=cp.bio if cp else None,
        profile_tagline=cp.profile_tagline if cp else None,
        is_creator=cp is not None,
        joined_platform=user.created_at,
        spaces_led=spaces_led,
    )
