from datetime import datetime

from pydantic import BaseModel, computed_field

from app.services.member_image import MemberImagePayload


class MemberProfile(BaseModel):
    """A user's presence within a Space — safe for public display."""

    id: str
    display_name: str
    avatar_url: str | None
    space_role: str               # learner / moderator / creator
    joined_at: datetime           # when they joined the Space
    bio: str | None               # from CreatorProfile (is_public only)
    profile_tagline: str | None   # short self-description
    is_creator: bool              # holds the Creator role, per creator_eligibility
    image: MemberImagePayload


class PublicProfile(BaseModel):
    """Platform-level public profile — safe for display to other members."""

    id: str
    display_name: str
    avatar_url: str | None
    bio: str | None
    profile_tagline: str | None   # short self-description
    is_creator: bool
    joined_platform: datetime | None  # own profile only — account age is not profile data
    spaces_led: list[str]         # names of spaces where this user is creator
    image: MemberImagePayload
