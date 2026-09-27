"""What do we call this member, when something must be rendered?

One ladder, shared by every surface that shows a member's name, so that
none of them invents its own answer. Two callers want different things
at the bottom of the ladder, and both are legitimate:

``optional_display_name`` returns ``None`` when there is no name. Use it
where the surface can choose to say nothing — Ways to Connect drops an
unnamed person from its cards rather than showing a placeholder, because
three cards all reading "Member" would be worse than three fewer cards.

``display_name`` returns ``NEUTRAL_DISPLAY_NAME`` instead. Use it where a
label must exist: a post, a comment or a message has to name its author,
and there is no option to omit the row.

What the ladder deliberately does **not** do is fall back to the local
part of the email address, which is what most of these surfaces used to
do. ``someone@example.com`` became "someone", so a member who had never
set a name had half of their email address shown to everyone who could
read a post, search a directory, or fetch a profile — and, because the
same expression fed ``member_image``, their initial too. An email
address is account data. A signed-in account is not a licence to derive
another member's identity from it.

The ``is_public`` check on the profile is applied here rather than
trusted to the caller's query, for the same reason
``member_image.visible_photo_url`` re-applies it: a row that reaches
this function unfiltered must still be handled correctly.
"""

from __future__ import annotations

from app.models.platform import CreatorProfile
from app.models.user import User

#: Shown where a name must appear and there is none. Deliberately the
#: plainest true thing we can say about somebody.
NEUTRAL_DISPLAY_NAME = "Member"


def optional_display_name(
    user: User, profile: CreatorProfile | None = None
) -> str | None:
    """A public profile's display name, else the member's own, else None."""
    if profile is not None and profile.is_public and profile.display_name:
        name = profile.display_name.strip()
        if name:
            return name
    return (user.name or "").strip() or None


def display_name(user: User, profile: CreatorProfile | None = None) -> str:
    """``optional_display_name``, with a neutral label rather than None."""
    return optional_display_name(user, profile) or NEUTRAL_DISPLAY_NAME
