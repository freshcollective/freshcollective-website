"""Who may reach each area of a Collective.

Three policies, deliberately few:

``public``
    Anyone, signed in or not.
``members``
    Anyone with an active membership (plus leaders and admins).
``active_access``
    Members who currently hold access to something in this Collective —
    a term pass, a Pathway entitlement, a complimentary grant. See
    ``services.active_access``.

What this decides and what it does not
--------------------------------------

This is the **doorway**: whether an area appears in navigation, on the
Collective Home, and whether its route and list API answer. It is not
the lock on any individual thing behind that door. Whether a specific
Pathway opens, whether a Gathering can be booked, how many sessions a
pass allows — those stay with ``compute_pathway_access``,
``compute_series_access`` and ``book_event``, untouched. A member can
reach the Gatherings list and still be unable to book the Thursday
session; that is correct and is not this module's business.

Three areas are fixed rather than configurable, each for a reason:

* **About** is always public. It is the joining and purchasing
  surface, and gating it would mean needing access in order to reach
  the page where access is bought.
* **Collective Home** is always members-only. A member whose term has
  ended must still have somewhere to land.
* **Messages** is always members-only, never ``active_access``. The
  most likely reason a lapsed member needs to write to the people
  running the Collective is the very access problem that would lock
  them out.

Defaults preserve what each area does today, including Pathways
staying public — quietly privatising every Collective's Pathway list
would be a far worse regression than the inconsistency it tidies.
"""

from __future__ import annotations

from typing import Any, Final

POLICY_PUBLIC: Final = "public"
POLICY_MEMBERS: Final = "members"
POLICY_ACTIVE_ACCESS: Final = "active_access"

#: Ordered loosest → strictest. Used to pick the safe value when a
#: stored policy cannot be honoured.
POLICY_ORDER: Final[tuple[str, ...]] = (
    POLICY_PUBLIC, POLICY_MEMBERS, POLICY_ACTIVE_ACCESS,
)

AREA_ABOUT: Final = "about"
AREA_HOME: Final = "home"
AREA_GATHERINGS: Final = "gatherings"
AREA_PATHWAYS: Final = "pathways"
AREA_CONVERSATIONS: Final = "conversations"
AREA_MEMBERS: Final = "members"
AREA_MESSAGES: Final = "messages"

#: Every area the platform knows, and what each may be set to. An area
#: whose tuple holds a single value is fixed: a creator cannot change
#: it and the Creator Studio panel does not offer it.
AREA_ALLOWED: Final[dict[str, tuple[str, ...]]] = {
    AREA_ABOUT:         (POLICY_PUBLIC,),
    AREA_HOME:          (POLICY_MEMBERS,),
    AREA_GATHERINGS:    (POLICY_PUBLIC, POLICY_MEMBERS, POLICY_ACTIVE_ACCESS),
    AREA_PATHWAYS:      (POLICY_PUBLIC, POLICY_MEMBERS, POLICY_ACTIVE_ACCESS),
    AREA_CONVERSATIONS: (POLICY_MEMBERS, POLICY_ACTIVE_ACCESS),
    AREA_MEMBERS:       (POLICY_MEMBERS, POLICY_ACTIVE_ACCESS),
    AREA_MESSAGES:      (POLICY_MEMBERS,),
}

#: What each area does today, so ``NULL`` changes nothing.
AREA_DEFAULTS: Final[dict[str, str]] = {
    AREA_ABOUT:         POLICY_PUBLIC,
    AREA_HOME:          POLICY_MEMBERS,
    AREA_GATHERINGS:    POLICY_MEMBERS,
    AREA_PATHWAYS:      POLICY_PUBLIC,
    AREA_CONVERSATIONS: POLICY_MEMBERS,
    AREA_MEMBERS:       POLICY_MEMBERS,
    AREA_MESSAGES:      POLICY_MEMBERS,
}

#: Areas a creator may actually set, in the order the panel shows them.
CONFIGURABLE_AREAS: Final[tuple[str, ...]] = tuple(
    area for area in (
        AREA_GATHERINGS, AREA_PATHWAYS, AREA_CONVERSATIONS, AREA_MEMBERS,
    )
    if len(AREA_ALLOWED[area]) > 1
)


class AreaPolicyError(ValueError):
    """A creator-supplied area policy was refused."""


def _strictest(area: str) -> str:
    """The safest value this area permits — where an unreadable stored
    policy lands, so a corrupt byte closes a door rather than opening
    one."""
    allowed = AREA_ALLOWED[area]
    return max(allowed, key=POLICY_ORDER.index)


def validate(raw: Any) -> dict | None:
    """Normalise a creator-supplied ``{"areas": {...}}`` document.

    Unknown area keys are **ignored**, so a newer client naming an area
    this server has not heard of does not fail the whole save. An
    invalid *policy* for a known area is **refused** — that is a real
    disagreement about access and must not be silently reinterpreted.

    Returns ``None`` when nothing usable remains, so the column holds
    ``NULL`` rather than an empty document meaning the same thing.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise AreaPolicyError("Area policies must be an object.")

    areas = raw.get("areas")
    if areas is None:
        return None
    if not isinstance(areas, dict):
        raise AreaPolicyError("`areas` must be an object.")

    cleaned: dict[str, str] = {}
    for area, policy in areas.items():
        if not isinstance(area, str) or area not in AREA_ALLOWED:
            continue  # unknown area — ignore, do not fail the save
        if not isinstance(policy, str):
            raise AreaPolicyError(f"Policy for '{area}' must be a string.")
        value = policy.strip()
        allowed = AREA_ALLOWED[area]
        if value not in allowed:
            raise AreaPolicyError(
                f"'{area}' may be set to: {', '.join(allowed)}."
            )
        cleaned[area] = value

    return {"areas": cleaned} if cleaned else None


def resolve_policies(stored: Any) -> dict[str, str]:
    """Every area's effective policy for this Collective.

    Always built from :data:`AREA_DEFAULTS` outwards, so an area the
    stored document has never heard of still gets an answer. A stored
    value that is not permitted for its area — which write-time
    validation should have prevented, but a hand-edited row or an older
    vocabulary could still produce — falls closed to the strictest
    value that area allows, never to the default.
    """
    policies = dict(AREA_DEFAULTS)

    areas = stored.get("areas") if isinstance(stored, dict) else None
    if not isinstance(areas, dict):
        return policies

    for area, policy in areas.items():
        if area not in AREA_ALLOWED:
            continue
        if isinstance(policy, str) and policy.strip() in AREA_ALLOWED[area]:
            policies[area] = policy.strip()
        else:
            policies[area] = _strictest(area)

    return policies


def requires_active_access(stored: Any) -> bool:
    """Whether resolving this Collective needs the active-access query
    at all. A Collective using only ``public`` and ``members`` — which
    is every Collective today — costs nothing extra."""
    return POLICY_ACTIVE_ACCESS in resolve_policies(stored).values()
