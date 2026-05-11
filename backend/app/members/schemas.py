from datetime import datetime
from pydantic import BaseModel, computed_field


class MemberProfile(BaseModel):
    """A user's presence within a Space — safe for public display."""

    id: str
    display_name: str
    avatar_url: str | None
    space_role: str          # learner / moderator / creator
    joined_at: datetime      # when they joined the Space
    bio: str | None          # from CreatorProfile (is_public only)
    is_creator: bool         # has a public CreatorProfile


class PublicProfile(BaseModel):
    """Platform-level public profile — safe for display to other members."""

    id: str
    display_name: str
    avatar_url: str | None
    bio: str | None
    is_creator: bool
    joined_platform: datetime
    spaces_led: list[str]    # names of spaces where this user is creator
