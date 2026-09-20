"""How a person becomes a member of a Collective.

Two policies, deliberately. ``open`` is what every Collective does
today and what most should keep doing — free joining is a first-class
model here, not a legacy one. ``purchase_required`` closes the
self-service door so membership arrives the only other way it can:
attached to something the person bought.

There is no ``invite_only`` policy, because the platform already says
that twice — ``Space.is_public = False`` plus the invitation flow
(enforced), and ``pricing_type = 'invite_only'`` (displayed). A third
expression of the same idea would be a third thing to keep in step.

What this module does **not** decide: whether a purchase creates
membership. It always does, for every purchase, through
``services.membership_grant`` — a person who buys a term in an open
Collective becomes a member of it just the same. The policy only
governs whether the *free* door is available.
"""

from __future__ import annotations

from typing import Final

JOIN_OPEN: Final = "open"
JOIN_PURCHASE_REQUIRED: Final = "purchase_required"

JOIN_POLICIES: Final[tuple[str, ...]] = (JOIN_OPEN, JOIN_PURCHASE_REQUIRED)

#: Returned to the client when free joining is refused. A stable
#: string the UI can branch on without parsing prose — the human
#: sentence beside it may be reworded at any time.
REASON_PURCHASE_REQUIRED: Final = "join_purchase_required"


class JoinPolicyError(ValueError):
    """An unrecognised join policy was supplied."""


def validate(value: object) -> str:
    """Normalise a creator-supplied join policy, or raise.

    Strict: an unknown value is refused rather than coerced to
    ``open``. Silently widening a Collective's door because a client
    sent a typo is the wrong failure direction.
    """
    if not isinstance(value, str):
        raise JoinPolicyError("Join policy must be a string.")
    cleaned = value.strip()
    if cleaned not in JOIN_POLICIES:
        raise JoinPolicyError(
            f"Join policy must be one of: {', '.join(JOIN_POLICIES)}."
        )
    return cleaned


def resolve(stored: object) -> str:
    """The effective policy for a Space.

    Unreadable or unrecognised stored values resolve to ``open`` —
    the platform default and the behaviour every Collective had before
    this column existed. Read-time is the wrong place to start
    refusing people entry over a bad byte; write-time validation is
    where a bad value is caught.
    """
    if isinstance(stored, str) and stored.strip() in JOIN_POLICIES:
        return stored.strip()
    return JOIN_OPEN


def allows_free_join(stored: object) -> bool:
    return resolve(stored) == JOIN_OPEN
