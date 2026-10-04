"""One answer to "what picture goes next to this member's name?".

Every member-bearing surface used to decide this for itself — read
``CreatorProfile.avatar_url``, maybe gate it on ``is_public``, then
leave the frontend to invent initials. Six places, six chances to
disagree, and the disagreements were real: the mention-search endpoint
read ``avatar_url`` off ``User``, which has no such column, so it
silently showed nothing forever.

So there is one resolver, and it returns one object. Callers hand it
what they already have and render what comes back.


The ladder
----------

1. **The member's own photo**, when they have uploaded one and made
   their profile public.
2. **A Fresh Collective alphabet card** for the first letter of their
   effective display name.
3. **The neutral card**, when no usable A–Z letter can be derived —
   a name that starts with a digit, an emoji, a CJK character, or no
   name at all. Permanent and ordinary, not an edge case.
4. **A plain one-letter initial**, only when the artwork itself is
   missing.

Tiers 2 and 3 are artwork Fresh Collective owns, not member data. They
are identical for everybody sharing a letter and disclose nothing, so
they are **not** gated by the member's profile-visibility setting: a
member who keeps their profile private still gets a designed square
rather than a bare glyph. Only tier 1 is personal and only tier 1 is
gated.

The artwork is not installed yet, so today every member resolves to
tier 4 and the surface looks exactly as it did. Tier 2 and 3 switch on
by themselves the moment the images exist — see ``MemberCardArtwork``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.platform import CreatorProfile, PlatformArtwork


class MemberImageKind(str, Enum):
    """Which rung of the ladder this member landed on.

    Surfaced to the frontend so it can render each state properly —
    a photo is cropped, a card is not, and an initial needs its own
    typography — rather than inferring the state from which fields
    happen to be null.
    """

    PHOTO = "photo"
    ALPHABET = "alphabet"
    NEUTRAL = "neutral"
    INITIAL = "initial"


@dataclass(frozen=True)
class MemberImage:
    """What to draw, and what to label it.

    ``initial`` is present for every kind, not just ``INITIAL``: it is
    the alt text for a card, and it lets a client fall back on its own
    if an image 404s mid-render.

    ``fallback_url`` is the rung *below* this one, and is set only for a
    photo. A member's own photo is the only tier that can fail after the
    server has chosen it — it is member-supplied, it can be deleted from
    storage, and a client-side block or a 404 is discovered in the
    browser, long after this decision was made. Without the next rung
    travelling alongside it, that failure skipped straight to a bare
    glyph: the client had nothing else to try, so a member with a broken
    photo got worse treatment than a member with no photo at all, who
    gets a designed card. Carrying it keeps the ladder a ladder all the
    way down, on every surface, without a second resolver.
    """

    kind: MemberImageKind
    url: str | None
    initial: str | None
    #: The card to draw if ``url`` cannot be loaded. Photos only.
    fallback_url: str | None = None


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

#: Platform-artwork keys for the member cards: ``member_card_a`` …
#: ``member_card_z``, plus ``member_card_neutral``.
#:
#: The cards are not registered in ``PLATFORM_ARTWORK_KEYS`` yet,
#: because registering them would add twenty-seven empty slots to the
#: admin artwork page before any image exists to put in them. Adding
#: those entries is the single step that switches tiers 2 and 3 on —
#: this module needs no change when it happens, because it looks rows
#: up by key.
MEMBER_CARD_KEY_PREFIX = "member_card_"
NEUTRAL_CARD_KEY = "member_card_neutral"


def member_card_key(letter: str) -> str:
    """``'S'`` → ``'member_card_s'``."""
    return f"{MEMBER_CARD_KEY_PREFIX}{letter.lower()}"


@dataclass(frozen=True)
class MemberCardArtwork:
    """The installed member-card artwork, loaded once per request.

    Loaded in one query and passed down, because the alternative is a
    lookup per member and Ways to Connect resolves several at a time.
    ``MemberCardArtwork.none()`` is the honest empty case and is what
    callers without a session should use.
    """

    urls: dict[str, str]

    @classmethod
    def none(cls) -> "MemberCardArtwork":
        return cls(urls={})

    @classmethod
    def load(cls, db: Session) -> "MemberCardArtwork":
        rows = (
            db.query(PlatformArtwork)
            .filter(PlatformArtwork.key.like(f"{MEMBER_CARD_KEY_PREFIX}%"))
            .all()
        )
        return cls(
            urls={
                r.key: r.image_url
                for r in rows
                if r.image_url
            }
        )

    def for_letter(self, letter: str | None) -> str | None:
        if letter is None:
            return None
        return self.urls.get(member_card_key(letter))

    @property
    def neutral(self) -> str | None:
        return self.urls.get(NEUTRAL_CARD_KEY)


# ---------------------------------------------------------------------------
# Deriving the letter
# ---------------------------------------------------------------------------

def alphabet_letter(display_name: str | None) -> str | None:
    """The single A–Z letter a member's card is drawn from, or None.

    Derived rather than stored. A stored key drifts the moment somebody
    renames themselves, and a card showing ``S`` for a member now called
    Rachel is stranger than a card that simply changed with her name.

    Accents are folded, because ``Émile`` is an E to everybody except a
    byte comparison. Anything that still is not A–Z after folding — a
    digit, an emoji, Cyrillic, Han — returns None and takes the neutral
    card. That is a permanent category, not a failure: the alphabet is
    Latin and the membership is not.

    One letter, never two. ``Sarah Jones`` is an S. The two-initial
    form that ``Avatar`` has used until now cannot address a
    twenty-six-card set.
    """
    if not display_name:
        return None

    # NFD splits an accented character into base + combining mark, so
    # dropping the marks leaves the base letter behind.
    folded = unicodedata.normalize("NFD", display_name.strip())
    for char in folded:
        if unicodedata.combining(char):
            continue
        upper = char.upper()
        if "A" <= upper <= "Z":
            return upper
        # A leading digit, quote or emoji means this name has no Latin
        # initial to take — stop rather than hunting for a letter
        # deeper in the string, which would give "7 Wonders" a W and
        # surprise its owner.
        if not char.isspace():
            return None
    return None


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

def visible_photo_url(profile: CreatorProfile | None) -> str | None:
    """The member's uploaded photo, if they have one and have chosen to
    be visible.

    The single place the profile-visibility rule is applied to imagery.
    Safe to call with a row that a query has already filtered on
    ``is_public`` — a private profile arrives as ``None`` either way.
    """
    if profile is None or not profile.is_public:
        return None
    return profile.avatar_url or None


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def resolve_member_image(
    *,
    display_name: str | None,
    profile: CreatorProfile | None,
    artwork: MemberCardArtwork,
) -> MemberImage:
    """Walk the ladder once and return what to draw."""
    letter = alphabet_letter(display_name)

    card = artwork.for_letter(letter)

    photo = visible_photo_url(profile)
    if photo:
        # Resolved now rather than on failure, because the artwork is
        # loaded here and the browser that discovers the failure has no
        # way to ask for it.
        return MemberImage(
            kind=MemberImageKind.PHOTO,
            url=photo,
            initial=letter,
            fallback_url=card or artwork.neutral,
        )

    if card:
        return MemberImage(
            kind=MemberImageKind.ALPHABET, url=card, initial=letter
        )

    neutral = artwork.neutral
    if neutral:
        return MemberImage(
            kind=MemberImageKind.NEUTRAL, url=neutral, initial=letter
        )

    return MemberImage(kind=MemberImageKind.INITIAL, url=None, initial=letter)


# ---------------------------------------------------------------------------
# Wire shape
# ---------------------------------------------------------------------------

class MemberImagePayload(BaseModel):
    """``MemberImage`` as it crosses the API boundary.

    Defined beside the resolver on purpose: the shape and the rule that
    produces it are one thing, and keeping them together is what stops
    a second surface inventing a third representation.
    """

    kind: str
    url: str | None = None
    initial: str | None = None
    #: Only ever set on a photo. See ``MemberImage.fallback_url``.
    fallback_url: str | None = None

    @classmethod
    def of(cls, image: MemberImage) -> "MemberImagePayload":
        return cls(
            kind=image.kind.value,
            url=image.url,
            initial=image.initial,
            fallback_url=image.fallback_url,
        )

    @classmethod
    def resolve(
        cls,
        *,
        display_name: str | None,
        profile: CreatorProfile | None,
        artwork: MemberCardArtwork,
    ) -> "MemberImagePayload":
        """Resolve and serialise in one step — what routes actually want."""
        return cls.of(
            resolve_member_image(
                display_name=display_name, profile=profile, artwork=artwork
            )
        )
