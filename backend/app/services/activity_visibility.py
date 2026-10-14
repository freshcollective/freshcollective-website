"""Everything a member may see, resolved once instead of per row.

Phase 1 answers "may this member see this activity?" one row at a
time, in Python. That is right for a twenty-row feed and wrong for
counting, which asks the same question about every Collective a member
belongs to on every page load. ``can_view_channel`` alone issues
several queries *per channel*, so a member in ten Collectives with
fifteen channels each would cost hundreds of queries to render a
number.

This module resolves the same rules in bulk: a fixed number of
set-based queries, independent of how many Collectives the member
belongs to, producing plain id sets the caller can filter against.

It is deliberately a *restatement in bulk*, not a second opinion.
Every rule below names the function it mirrors, and the paired tests
assert the two agree. Where they could drift, the test is the thing
that notices — a divergence here would quietly show a member activity
about content they cannot open, which is the one failure this whole
feature must not have.

What it does not decide
-----------------------
Liveness (is the Pathway still published?) stays in SQL next to the
count, because it is a property of the content rather than of the
member, and a join expresses it better than a set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from sqlalchemy.orm import Session

from app.spaces import area_policies as ap

#: The activity categories a member-facing indicator may show, and the
#: Area each one lives behind.
CATEGORY_AREA: Mapping[str, str] = {
    "conversations": ap.AREA_CONVERSATIONS,
    "pathways": ap.AREA_PATHWAYS,
    "gatherings": ap.AREA_GATHERINGS,
}


@dataclass(frozen=True)
class MemberScope:
    """One member's reach, as id sets.

    ``joined_at`` matters as much as the rest: a member with no cursor
    has seen nothing since they joined, and that is where counting
    starts for them.
    """

    user_id: str
    space_ids: frozenset[str]
    joined_at: Mapping[str, datetime]
    caretaker_space_ids: frozenset[str]
    #: space_id -> the categories whose Area this member can reach.
    reachable_categories: Mapping[str, frozenset[str]]
    #: Channels whose posts this member may read, across every space.
    accessible_channel_ids: frozenset[str]
    #: Pathways this member may actually open. Used only to decide
    #: whether a *step* counts — a Pathway's own publication counts on
    #: listing visibility, which is a different and looser question.
    accessible_pathway_ids: frozenset[str]

    def categories_for(self, space_id: str) -> frozenset[str]:
        return self.reachable_categories.get(space_id, frozenset())


def resolve_member_scope(
    db: Session,
    user,
    *,
    collective_id: str | None = None,
    now: datetime | None = None,
) -> MemberScope:
    """Resolve the member's reach in a fixed number of queries.

    ``collective_id`` narrows the work to one Collective; omitted, it
    covers every Collective the member belongs to at the same cost.
    """
    from app.models.access_pass import AccessPass, AccessPassStatus
    from app.models.payment_option import PaymentOption, PaymentOptionStatus
    from app.models.payment_option_grant import PaymentOptionGrant
    from app.models.platform import (
        BookingStatus,
        ChannelMembership,
        ConversationChannel,
        EntitlementStatus,
        EventBooking,
        Pathway,
        PathwayEntitlement,
        PathwayStatus,
        Space,
        SpaceMembership,
        SpaceMembershipStatus,
    )

    at = now or datetime.utcnow()
    empty = MemberScope(
        user_id=getattr(user, "id", "") or "",
        space_ids=frozenset(),
        joined_at={},
        caretaker_space_ids=frozenset(),
        reachable_categories={},
        accessible_channel_ids=frozenset(),
        accessible_pathway_ids=frozenset(),
    )
    if user is None or not getattr(user, "id", None):
        return empty

    is_admin = getattr(user, "role", None) == "admin"

    # 1 — memberships. Active only; a paused or removed member reaches
    #     nothing, which is the Phase 1 rule.
    mq = db.query(
        SpaceMembership.space_id, SpaceMembership.joined_at, SpaceMembership.role,
    ).filter(
        SpaceMembership.user_id == user.id,
        SpaceMembership.status == SpaceMembershipStatus.active,
    )
    if collective_id is not None:
        mq = mq.filter(SpaceMembership.space_id == collective_id)
    memberships = mq.all()
    if not memberships:
        return empty

    joined_at = {m[0]: m[1] for m in memberships}
    caretaker_roles = {"creator", "moderator"}
    caretaker = {
        m[0] for m in memberships
        if getattr(m[2], "value", m[2]) in caretaker_roles
    }

    # 2 — the spaces themselves. An archived or draft Collective shows
    #     nothing, as in Phase 1.
    spaces = (
        db.query(Space.id, Space.creator_id, Space.area_policies)
        .filter(Space.id.in_(joined_at.keys()), Space.status == "active")
        .all()
    )
    space_ids = {s[0] for s in spaces}
    if not space_ids:
        return empty
    caretaker |= {s[0] for s in spaces if s[1] == user.id}
    if is_admin:
        caretaker |= space_ids

    # 3 — durable access records, two queries rather than two per
    #     space. These answer active-access, paid Pathways and
    #     Series-linked Channels alike.
    passes = (
        db.query(
            AccessPass.space_id,
            AccessPass.payment_option_id,
            AccessPass.eligible_series_id,
        )
        .filter(
            AccessPass.user_id == user.id,
            AccessPass.space_id.in_(space_ids),
            AccessPass.status == AccessPassStatus.active,
            (AccessPass.valid_until.is_(None) | (AccessPass.valid_until > at)),
        )
        .all()
    )
    entitlements = (
        db.query(PathwayEntitlement.space_id, PathwayEntitlement.pathway_id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.space_id.in_(space_ids),
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None)
             | (PathwayEntitlement.ends_at > at)),
        )
        .all()
    )
    entitled_pathway_ids = {e[1] for e in entitlements if e[1]}
    pass_option_ids = {p[1] for p in passes if p[1]}
    pass_series_ids = {p[2] for p in passes if p[2]}
    # Mirrors ``active_access.has_active_access``: either record counts.
    active_access_spaces = (
        {p[0] for p in passes} | {e[0] for e in entitlements}
    )

    # 4 — Area policies. One resolve per space from data already held,
    #     no further queries.
    reachable: dict[str, frozenset[str]] = {}
    for sid, _creator, policies_doc in spaces:
        policies = ap.resolve_policies(policies_doc)
        is_leader = sid in caretaker
        has_access = is_leader or sid in active_access_spaces
        ok: set[str] = set()
        for category, area in CATEGORY_AREA.items():
            policy = policies.get(area, ap.AREA_DEFAULTS.get(area))
            if policy == ap.POLICY_PUBLIC:
                ok.add(category)
            elif policy == ap.POLICY_MEMBERS:
                ok.add(category)          # membership is already established
            elif policy == ap.POLICY_ACTIVE_ACCESS:
                if has_access:
                    ok.add(category)
        reachable[sid] = frozenset(ok)

    # 5 — which Pathways this member may actually open. Mirrors
    #     ``pathway_access.compute_pathway_access``; the paired test
    #     asserts the two agree rather than trusting this restatement.
    pathways = (
        db.query(
            Pathway.id, Pathway.space_id, Pathway.status, Pathway.access_type,
        )
        .filter(Pathway.space_id.in_(space_ids))
        .all()
    )
    # Options that unlock a Pathway, for the ``included_with_offer``
    # and paid arms — one query instead of one per Pathway.
    unlocked_by_pass: set[str] = set()
    if pass_option_ids:
        grants = (
            db.query(PaymentOptionGrant.pathway_id)
            .join(
                PaymentOption,
                PaymentOption.id == PaymentOptionGrant.payment_option_id,
            )
            .filter(
                PaymentOptionGrant.grant_kind == "pathway",
                PaymentOptionGrant.payment_option_id.in_(pass_option_ids),
                PaymentOption.status.in_([
                    PaymentOptionStatus.published,
                    PaymentOptionStatus.archived,
                ]),
            )
            .all()
        )
        unlocked_by_pass = {g[0] for g in grants if g[0]}

    accessible_pathways: set[str] = set()
    for pid, sid, status, access_type in pathways:
        if sid in caretaker:
            accessible_pathways.add(pid)
            continue
        status_v = getattr(status, "value", status)
        if status_v != PathwayStatus.active.value:
            # draft, archived and coming_soon are not openable, which
            # is why a step inside them never counts.
            continue
        at_v = getattr(access_type, "value", access_type) or "free"
        if at_v in ("free", "included"):
            accessible_pathways.add(pid)
        elif at_v == "included_with_offer":
            if pid in unlocked_by_pass or pid in entitled_pathway_ids:
                accessible_pathways.add(pid)
        else:  # one_time, subscription
            if pid in entitled_pathway_ids:
                accessible_pathways.add(pid)

    # 6 — Channels. Mirrors ``channel_permissions.can_view_channel``,
    #     resolved from sets rather than a query per channel.
    channels = (
        db.query(
            ConversationChannel.id,
            ConversationChannel.space_id,
            ConversationChannel.channel_type,
            ConversationChannel.pathway_id,
            ConversationChannel.gathering_id,
            ConversationChannel.series_id,
        )
        .filter(ConversationChannel.space_id.in_(space_ids))
        .all()
    )
    private_ids = {
        c[0] for c in channels if c[2] == "private"
    }
    member_of_private: set[str] = set()
    if private_ids:
        member_of_private = {
            r[0] for r in db.query(ChannelMembership.channel_id).filter(
                ChannelMembership.user_id == user.id,
                ChannelMembership.channel_id.in_(private_ids),
            ).all()
        }
    gathering_ids = {c[4] for c in channels if c[2] == "gathering" and c[4]}
    attended: set[str] = set()
    if gathering_ids:
        attended = {
            r[0] for r in db.query(EventBooking.event_id).filter(
                EventBooking.user_id == user.id,
                EventBooking.event_id.in_(gathering_ids),
                EventBooking.status == BookingStatus.confirmed,
            ).all()
        }

    accessible_channels: set[str] = set()
    for cid, sid, ctype, pw_id, ev_id, series_id in channels:
        if sid in caretaker:
            accessible_channels.add(cid)
            continue
        if ctype in ("start_here", "general", "open"):
            accessible_channels.add(cid)
        elif ctype == "private":
            if cid in member_of_private:
                accessible_channels.add(cid)
        elif ctype == "pathway":
            if pw_id and pw_id in accessible_pathways:
                accessible_channels.add(cid)
        elif ctype == "gathering":
            if ev_id and ev_id in attended:
                accessible_channels.add(cid)
        elif ctype == "series":
            # Mirrors ``compute_series_access``: an active pass whose
            # eligible_series_id matches. A booking on one session of
            # the term is deliberately not an unlock.
            if series_id and series_id in pass_series_ids:
                accessible_channels.add(cid)

    return MemberScope(
        user_id=user.id,
        space_ids=frozenset(space_ids),
        joined_at={k: v for k, v in joined_at.items() if k in space_ids},
        caretaker_space_ids=frozenset(caretaker),
        reachable_categories=reachable,
        accessible_channel_ids=frozenset(accessible_channels),
        accessible_pathway_ids=frozenset(accessible_pathways),
    )
