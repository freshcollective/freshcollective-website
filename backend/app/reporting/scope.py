"""Who is asking, and which Collectives they may be told about.

Reporting has two audiences with the same questions and very different
entitlements. World Management asks "how is the business doing"; a
creator asks "how is *my* Collective doing". The arithmetic is identical
and the permitted rows are not, so the scope is a first-class argument
to every calculation rather than a filter the caller remembers to apply.

That ordering matters. If scoping were the caller's job, a creator-facing
endpoint added in a later release would be one forgotten ``WHERE`` away
from showing somebody another creator's earnings. Here a metric declares
whether a creator may see it at all, the scope carries the Collectives
they manage, and the calculation receives both — so the unsafe version of
the query is the one that is hard to write.

Nothing in this module reads a request. It is resolved by a dependency
(see ``app.reporting.routes``) and passed down, which keeps the registry
testable without a web layer.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from sqlalchemy.orm import Session


class Audience(str, enum.Enum):
    #: A platform administrator. Every Collective, every metric.
    platform = "platform"
    #: A creator, restricted to the Collectives they manage.
    creator = "creator"


class Access(str, enum.Enum):
    """How widely a metric may be shown."""

    #: Commercially sensitive platform-wide information — Fresh
    #: Collective's own revenue, cross-Collective totals, anything that
    #: would tell one creator about another. Admin only, always.
    platform_only = "platform_only"
    #: Safe to show a creator about their own Collectives: their members,
    #: their engagement, their sales, their earnings.
    creator_visible = "creator_visible"


@dataclass(frozen=True)
class ReportScope:
    """The boundary a calculation must stay inside."""

    audience: Audience
    #: The asking user. None only for internal/system calls.
    user_id: str | None = None
    #: For a creator scope: exactly the Collectives they may be told
    #: about. Empty means they manage none, and every scoped metric
    #: correctly returns zero rather than everything.
    space_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_platform(self) -> bool:
        return self.audience is Audience.platform

    @property
    def space_filter(self) -> tuple[str, ...] | None:
        """The Collectives a calculation must stay inside, or None for all.

        Audience and restriction are **different axes**, and reading
        one for the other was a real defect: the daily loader builds a
        per-Collective scope as ``Audience.platform`` with one
        ``space_id`` — platform because the loader is entitled to every
        metric, one Collective because that is the row it is computing.
        Every calculation then asked ``if not scope.is_platform``, saw
        a platform audience, and skipped the restriction entirely, so
        each Collective's stored row held the platform total.

        So entitlement is ``is_platform`` and restriction is this. An
        empty tuple from a creator means they manage nothing, which is
        a filter matching no rows rather than no filter at all — the
        distinction between "all Collectives" and "none" that a bare
        list cannot carry.
        """
        if self.space_ids:
            return self.space_ids
        return None if self.is_platform else ()

    def may_see(self, access: Access) -> bool:
        return self.is_platform or access is Access.creator_visible

    def require(self, access: Access, metric_key: str) -> None:
        """Raise unless this scope may see a metric with that access."""
        if not self.may_see(access):
            raise ScopeDenied(
                f"{metric_key!r} is platform-only and cannot be served to a "
                "creator-scoped request"
            )


class ScopeDenied(PermissionError):
    """A scope asked for something it is not entitled to see."""


def platform_scope(user_id: str | None = None) -> ReportScope:
    return ReportScope(audience=Audience.platform, user_id=user_id)


def creator_scope(db: Session, user_id: str) -> ReportScope:
    """Build a creator's scope from the Collectives they actually manage.

    Derived from ``space_memberships`` with an owning role, which is the
    same basis the Creator Studio routes use — rather than from
    ``spaces.creator_id`` alone, so a moderator-managed Collective is
    included on the same terms the rest of the product grants.

    Deliberately queried here and not passed in: a caller that could
    supply its own ``space_ids`` could supply somebody else's.
    """
    from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole

    rows = (
        db.query(SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
        )
        .distinct()
        .all()
    )
    return ReportScope(
        audience=Audience.creator,
        user_id=user_id,
        space_ids=tuple(sorted(r[0] for r in rows)),
    )
