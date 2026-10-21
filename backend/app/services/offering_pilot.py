"""Which Collectives may use Offerings while the pilot is running.

Two switches, and they do different jobs:

``OFFERINGS_ENABLED``
    The master switch. Off means the feature does not exist — every
    route 404s, every surface disappears. Unchanged by this module.

``OFFERINGS_PILOT_COLLECTIVES``
    The *scope*. With the master switch on, this decides **which
    Collectives** Offerings works in. One nominated Collective can
    create, publish, sell and be browsed; every other Collective
    behaves exactly as it does with the feature off.

Both must say yes. Neither alone is enough.

Why empty means nothing, not everything
---------------------------------------

An empty list allows **no Collective**. That is deliberate and it is
the opposite of what most allow-lists do.

The reason is the failure we are protecting against. If empty meant
"everywhere", then a cleared value — an operator mistake, or a
blueprint sync overwriting a Dashboard entry, which has happened on
this platform twice — would silently turn a controlled pilot into a
public launch. Fail the other way and a cleared value turns the pilot
off: visible, harmless, and fixed by putting the slug back.

It matches the stance ``area_policies._strictest`` already takes: a
corrupt byte should close a door rather than open one.

For a genuine general release, set the value to ``*``. That is an
explicit act, which is the point.

Slugs or ids, and why both
--------------------------

A token matches a Collective's **slug** or its **id**. Slugs are what
an operator can actually type into a Render environment variable, so
they are the expected form — ``moonlit-circle``, not a UUID.

But a slug is mutable: ``creator.routes`` lets an owner change it from
Collective settings (``space.slug = body.slug``). If the pilot
Collective were renamed, a slug-only list would stop matching and the
pilot would quietly switch off. Accepting ids as well means an operator
who wants the entry to survive a rename can use one. Both forms live in
the same list; no second setting.

Slug comparison is case-insensitive and whitespace-trimmed, because the
value is typed by hand. Ids are compared exactly.

What this does NOT gate
-----------------------

**Downloads.** ``uploads.authorization._authorise_offering_file`` does
not consult the feature flag and must not consult this either. A
Collective leaving the pilot, like the feature being switched off, must
never reach into what somebody already acquired. There is a test for
it.

**Your Collection**, and **the detail page of an Offering the caller
owns**. Both are handled in ``_offering_member_routes``, and for the
same reason: a member's own acquisition must not become unreachable
because an operator edited a config value.

So the line this module draws is not "Offerings is off outside the
pilot" but the more precise one:

    public visibility and new acquisitions   →  pilot-gated
    existing ownership and access to it      →  never pilot-gated

The catalogue 404s, acquiring 404s and checkout 409s for a Collective
outside the pilot. An owner still reaches their downloads, and still
reaches the page those downloads are listed on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from app.models.platform import Space

logger = logging.getLogger(__name__)

#: The token that opens the pilot to every Collective. Spelled out
#: rather than inferred from an empty value, so a general release is
#: something somebody typed on purpose.
ALLOW_ALL = "*"


@dataclass(frozen=True)
class PilotScope:
    """The parsed allow-list.

    ``tokens`` holds lower-cased slugs and exact ids together — a
    Collective matches if either of its identifiers is present.
    """

    tokens: frozenset[str]
    allow_all: bool

    @property
    def is_restricted(self) -> bool:
        """True when the pilot is scoping the feature at all.

        ``False`` only for ``*``. An empty list is restricted — to
        nothing.
        """
        return not self.allow_all

    @property
    def is_closed(self) -> bool:
        """True when no Collective can use Offerings."""
        return not self.allow_all and not self.tokens

    def admits(self, *, slug: str | None, space_id: str | None) -> bool:
        if self.allow_all:
            return True
        if slug and slug.strip().lower() in self.tokens:
            return True
        if space_id and space_id in self.tokens:
            return True
        return False


@lru_cache(maxsize=8)
def _parse(raw: str) -> PilotScope:
    """Parse the setting. Cached on the raw string, so repeated reads in
    one request cost nothing and a changed value (a restart, or a test
    monkeypatching it) produces a different cache key."""
    parts = [p.strip() for p in (raw or "").split(",")]
    parts = [p for p in parts if p]
    if ALLOW_ALL in parts:
        return PilotScope(tokens=frozenset(), allow_all=True)
    # Slugs lower-cased for case-insensitive matching; ids are
    # lower-case hex or cuid already, so lowering is harmless for them.
    return PilotScope(
        tokens=frozenset(p.lower() for p in parts), allow_all=False,
    )


def current_scope() -> PilotScope:
    """The scope right now.

    Reads ``settings`` at call time rather than at import, because the
    value comes from the environment and the test suite replaces it.
    """
    from app.core.config import settings
    return _parse(getattr(settings, "offerings_pilot_collectives", "") or "")


def space_in_pilot(space: Space | None) -> bool:
    """Whether Offerings is available in this Collective.

    Answers the scope question **only**. Callers that also need the
    master switch use :func:`offerings_available_for`, which is what
    nearly all of them want.
    """
    if space is None:
        return False
    return current_scope().admits(
        slug=getattr(space, "slug", None),
        space_id=getattr(space, "id", None),
    )


def offerings_available_for(space: Space | None) -> bool:
    """Both switches, in the order they are cheapest to check.

    This is the predicate every surface should ask. It is deliberately
    not called ``is_enabled`` — the answer depends on *which*
    Collective, and a name that hid that would invite a cached global.
    """
    from app.core.config import settings
    if not settings.offerings_enabled:
        return False
    return space_in_pilot(space)


def require_pilot_space(space: Space | None) -> None:
    """Refuse with 404 when this Collective is outside the pilot.

    **404, not 403**, matching ``require_offerings_enabled`` and
    ``_get_space_visible_to``: a refusal must not confirm that a
    feature exists for Collectives that cannot see it. For a creator
    outside the pilot, Offerings should look exactly as it does with
    the feature switched off — because for them, it is.
    """
    from fastapi import HTTPException, status as http_status

    if space_in_pilot(space):
        return
    scope = current_scope()
    logger.info(
        "offering_pilot: refused space=%s slug=%s (pilot %s)",
        getattr(space, "id", None), getattr(space, "slug", None),
        "is closed" if scope.is_closed else f"admits {sorted(scope.tokens)}",
    )
    raise HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND, detail="Not found.",
    )


def describe() -> str:
    """One line for a startup log or an operator check."""
    from app.core.config import settings
    scope = current_scope()
    if not settings.offerings_enabled:
        return "Offerings: disabled (OFFERINGS_ENABLED=false)"
    if scope.allow_all:
        return "Offerings: enabled for ALL Collectives (pilot list = '*')"
    if scope.is_closed:
        return (
            "Offerings: enabled but NO Collective is in the pilot "
            "(OFFERINGS_PILOT_COLLECTIVES is empty — nothing will work)"
        )
    return (
        "Offerings: enabled for pilot Collectives "
        f"{sorted(scope.tokens)}"
    )


__all__ = [
    "ALLOW_ALL",
    "PilotScope",
    "current_scope",
    "describe",
    "offerings_available_for",
    "require_pilot_space",
    "space_in_pilot",
]
