from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.models.platform import CreatorProfile, Space, SpaceMembership
from app.models.user import User
from app.members.schemas import MemberProfile, PublicProfile
from app.services.creator_eligibility import is_eligible_creator
from app.services.member_identity import display_name as member_display_name
from app.services.member_image import MemberCardArtwork, MemberImagePayload
from app.services.member_visibility import (
    directory_role_filter,
    shared_visible_collective,
    visible_collectives_led,
)
from app.services.space_viewer import require_space_viewer
from app.spaces.area_access import require_area
from app.spaces.area_policies import AREA_MEMBERS

members_router = APIRouter(prefix="/api/spaces", tags=["members"])
profiles_router = APIRouter(prefix="/api/profile", tags=["profiles"])

ROLE_PRIORITY = {"creator": 0, "moderator": 1, "learner": 2}


def _get_space_or_404(slug: str, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _display_name(user: User, creator_profile: CreatorProfile | None) -> str:
    """A name for a member surface, where one must be rendered.

    Delegates to ``member_identity`` rather than deciding again. This
    used to fall back to the local part of the member's email address,
    which handed half of it to every caller of the directory *and* of
    the public profile below. (Spelled out in prose rather than in code,
    so a source-contract test can ban the expression itself.)
    """
    return member_display_name(user, creator_profile)


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

    Member-only. A signed-out visitor, or a signed-in person who
    belongs to some other Collective, is told the Collective does not
    exist rather than handed its membership list.

    Previously this answered any caller and applied directory privacy
    only when ``caller_role == "learner"``. An anonymous caller has no
    role, so the check silently passed them through and any public
    Collective's full membership — learner rows included, directory
    switched off or not — was readable without signing in.

    Inside the Collective the existing rule is unchanged: with
    ``show_member_directory=False`` a learner sees only leaders.
    """
    space = _get_space_or_404(slug, db)
    viewer = require_space_viewer(db, current_user, space)
    # Area policy on top of membership: a Collective may restrict the
    # directory doorway to members holding active access. It can never
    # *open* it — ``show_member_directory`` still decides whether the
    # area exists at all, and ``resolve_area_access`` drops it when
    # that is off regardless of policy.
    require_area(db, space, current_user, AREA_MEMBERS)

    # The directory restriction now lives in ``member_visibility`` so
    # the public profile endpoint can apply the same rule instead of
    # carrying a second, looser one — which is exactly how a profile
    # became a way around this filter.
    visible_roles = directory_role_filter(space, viewer)

    membership_filter = [
        SpaceMembership.space_id == space.id,
        SpaceMembership.status == "active",
    ]
    if visible_roles is not None:
        membership_filter.append(SpaceMembership.role.in_(visible_roles))

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

    # Loaded once for the whole directory rather than per member.
    artwork = MemberCardArtwork.load(db)

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
            # Holding a profile row is not being a Creator. Every member
            # who uploads a photo gets one, so this used to hand out
            # Creator badges for setting a profile picture.
            is_creator=is_eligible_creator(user),
            image=MemberImagePayload.resolve(
                display_name=_display_name(user, cp),
                profile=cp,
                artwork=artwork,
            ),
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
    """Return a user's platform profile, to someone entitled to see it.

    Being signed in used to be the whole rule: any authenticated account
    could read any user id, with no shared context of any kind. That made
    this endpoint a way around the member directory above — a learner in
    a Collective with ``show_member_directory`` switched off could not
    *list* their fellow learners, but could fetch each one's profile
    directly, and ids are easy to come by from post authors, mention
    suggestions and search results.

    Three ways in, checked in order:

      1. yourself;
      2. an eligible Creator who has deliberately made their profile
         public — that profile is their public face, and ``is_public``
         is how they said so;
      3. otherwise, a Collective you share where the directory itself
         would have shown you this person.

    Anything else is 404, not 403: a refusal must not confirm that the
    account exists.
    """
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

    is_self = user.id == current_user.id
    is_creator = is_eligible_creator(user)
    # A public profile row is the deliberate act: an ordinary member who
    # uploads a photo gets a row too, but it is created private.
    is_public_creator = is_creator and cp is not None

    if not (is_self or is_public_creator):
        if shared_visible_collective(db, current_user, user) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found."
            )

    return PublicProfile(
        id=user.id,
        display_name=_display_name(user, cp),
        avatar_url=cp.avatar_url if cp else None,
        bio=cp.bio if cp else None,
        profile_tagline=cp.profile_tagline if cp else None,
        is_creator=is_creator,
        # Account age is not profile data. It was returned for everyone,
        # which told any caller when a member signed up — nothing to do
        # with how that member has chosen to present themselves. Kept for
        # your own profile, where it is your own fact.
        joined_platform=user.created_at if is_self else None,
        # Never the ``link`` or ``private`` Collectives of a Creator whose
        # profile you can see but whose Collectives you cannot.
        spaces_led=visible_collectives_led(db, current_user, user),
        image=MemberImagePayload.resolve(
            display_name=_display_name(user, cp),
            profile=cp,
            artwork=MemberCardArtwork.load(db),
        ),
    )
