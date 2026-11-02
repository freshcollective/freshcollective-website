#!/usr/bin/env python
"""Materialise membership for channels that predate migration 177.

Why this is not in the migration
--------------------------------
Who currently qualifies for a Pathway or Series channel is decided by
``compute_pathway_access`` and ``compute_series_access`` — status
rules, access types, caretaker privilege, entitlements, passes, grants.
Reimplementing that in migration SQL would risk silently admitting or
excluding real members, which is the one outcome a migration over
production data must not produce. This calls the real functions.

Why it is needed at all
-----------------------
After 177, a linked channel's membership is authoritative: it is what
keeps somebody in the conversation once the Gathering has finished or
the pass has expired. Existing members have no membership row yet —
they were reaching their channels through a live recomputation.

Nobody is locked out in the meantime: the permission service still
admits anyone who qualifies *today*. But until a row exists, that
access would end when their experience access ends, which is exactly
the behaviour 177 was written to stop. This closes that window.

Safety
------
Read-mostly, and additive where it writes. It only ever calls
``admit``, which:

  * is idempotent — running twice adds nobody twice,
  * refuses anybody a creator has removed, so it cannot undo a
    decision,
  * never removes, downgrades or reassigns an existing row.

It does not touch entitlements, bookings, payments, posts, polls or
Collective membership.

Usage
-----
From the fc-api Render Shell, where ``DATABASE_URL`` is production::

    python scripts/backfill_channel_memberships.py            # report only
    python scripts/backfill_channel_memberships.py --apply    # write

Default is a dry run. ``--apply`` is required to commit anything, so a
misremembered command reports instead of writing.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ``backend/`` — this file's grandparent. fc-api builds with
# ``rootDir: backend``, so every operational script addresses the app
# from here; see scripts/audit_creator_plans.py for the longer note.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="commit the memberships (default is a dry run)",
    )
    parser.add_argument(
        "--space", default=None,
        help="limit to one Collective, by slug",
    )
    parser.add_argument(
        "--impact", action="store_true",
        help="report who could open each linked channel under the old "
             "viewability rule but is not admitted under the current "
             "'must have joined' rule, and holds no membership row. "
             "Read-only; writes nothing even with --apply.",
    )
    parser.add_argument(
        "--explain", action="store_true",
        help="list every considered member and why they were included "
             "or skipped",
    )
    args = parser.parse_args()

    import app.main  # noqa: F401 — registers the whole mapper graph;
    #                   without it SpaceMembership's relationship to
    #                   User cannot resolve and every query raises.
    from app.db.session import SessionLocal
    from app.models.platform import (
        ChannelExperienceLink,
        ConversationChannel,
        Space,
    )
    from app.services import channel_membership as chm
    from app.services.channel_types import LINKED_TYPES

    def _describe_links(session, channel_id: str) -> list[str]:
        """Name each linked experience and its status.

        The status matters for reading the proposal: a ``draft``
        Pathway admits nobody but a caretaker, so a channel linked only
        to one should contribute zero additions.
        """
        from app.models.platform import Event, EventSeries, Pathway

        out: list[str] = []
        rows = (
            session.query(ChannelExperienceLink)
            .filter(ChannelExperienceLink.channel_id == channel_id)
            .all()
        )
        for row in rows:
            if row.pathway_id:
                pw = session.get(Pathway, row.pathway_id)
                status = getattr(pw, "status", None)
                access = getattr(pw, "access_type", None)
                out.append(
                    f"pathway  {getattr(pw, 'title', row.pathway_id)!r} "
                    f"status={getattr(status, 'value', status)} "
                    f"access={getattr(access, 'value', access)}"
                )
            elif row.event_id:
                ev = session.get(Event, row.event_id)
                out.append(
                    f"gathering {getattr(ev, 'title', row.event_id)!r} "
                    f"published={getattr(ev, 'is_published', '?')}"
                )
            elif row.series_id:
                sr = session.get(EventSeries, row.series_id)
                out.append(
                    f"series   {getattr(sr, 'title', row.series_id)!r} "
                    f"status={getattr(sr, 'status', '?')}"
                )
        return out

    def _report_impact(session, channels) -> None:
        """Who loses access when "may view" stops meaning "joined".

        Compares the two predicates directly rather than estimating.
        The old one is still in the codebase — it is what the mention
        audience was built from — so the affected set is computable
        exactly instead of guessed at.

        Anyone with a membership row is unaffected by construction:
        ``can_access_linked_channel`` reads the row before it asks any
        question about experiences. That includes the EMBODY
        memberships.
        """
        from app.models.platform import (
            ChannelMembership, Space, SpaceMembership, SpaceMembershipStatus,
        )
        from app.models.user import User
        from app.services import channel_permissions as perms

        print("\n  IMPACT REPORT — read-only, writes nothing\n")
        total_losing = 0
        for channel in channels:
            space = session.get(Space, channel.space_id)
            if space is None:
                continue
            held = {
                r.user_id for r in session.query(ChannelMembership.user_id)
                .filter(ChannelMembership.channel_id == channel.id)
            }
            members = (
                session.query(User)
                .join(SpaceMembership, SpaceMembership.user_id == User.id)
                .filter(
                    SpaceMembership.space_id == space.id,
                    SpaceMembership.status == SpaceMembershipStatus.active,
                )
                .all()
            )
            losing = []
            for user in members:
                if user.id in held:
                    continue
                if perms.is_caretaker_here(user, space, session):
                    continue
                could = perms.qualifies_through_any_linked_experience(
                    user, channel, space, session,
                )
                joined = perms.acquisition_for_linked_channel(
                    user, channel, space, session,
                ) is not None
                if could and not joined:
                    losing.append(user.email)
            if losing:
                total_losing += len(losing)
                print(f"    {space.slug}/{channel.slug:28} "
                      f"{len(losing)} would lose access")
                for ref in _describe_links(session, channel.id):
                    print(f"        link: {ref}")
                for email in losing[:15]:
                    print(f"        - {email}")
                if len(losing) > 15:
                    print(f"        … and {len(losing) - 15} more")
        if total_losing == 0:
            print("    nobody loses access.")
        else:
            print(f"\n  {total_losing} member-channel pair(s) affected.")
            print("  Each is somebody who could open the channel because a")
            print("  linked experience was viewable to them, and who never")
            print("  joined it. Nobody with a membership row is listed.")

    db = SessionLocal()
    try:
        q = (
            db.query(ConversationChannel)
            .filter(ConversationChannel.channel_type.in_(tuple(LINKED_TYPES)))
        )
        if args.space:
            space_row = (
                db.query(Space).filter(Space.slug == args.space).first()
            )
            if space_row is None:
                print(f"  no Collective with slug {args.space!r}")
                return 2
            q = q.filter(ConversationChannel.space_id == space_row.id)

        channels = q.order_by(ConversationChannel.space_id).all()
        if not channels:
            print("  no linked-experience channels found")
            return 0

        if args.impact:
            _report_impact(db, channels)
            db.rollback()
            return 0

        mode = "APPLYING" if args.apply else "DRY RUN — nothing will be written"
        print(f"\n  {mode}")
        print(f"  {len(channels)} linked-experience channel(s) across "
              f"{len({c.space_id for c in channels})} Collective(s)")
        archived = sum(1 for c in channels if c.is_archived)
        hidden = sum(1 for c in channels if not c.show_in_navigation)
        if archived or hidden:
            # The count here is every linked channel in the database.
            # A Channels page shows one Collective, and the member-side
            # navigation hides channels a creator unticked — so "the
            # script says 10 and I can see 8" usually means these.
            print(f"  of which {archived} archived and {hidden} hidden "
                  f"from navigation")
        print()

        totals = {"added": 0, "already_member": 0,
                  "blocked_by_creator_removal": 0, "readmitted": 0,
                  "considered": 0, "skipped_caretaker": 0,
                  "skipped_no_acquisition": 0}
        unlinked: list[str] = []

        for channel in channels:
            space = db.get(Space, channel.space_id)
            if space is None:
                continue
            link_count = (
                db.query(ChannelExperienceLink)
                .filter(ChannelExperienceLink.channel_id == channel.id)
                .count()
            )
            if link_count == 0:
                # The channel names an experience that no longer
                # exists, so 177's backfill skipped it. Nothing to
                # qualify through; a caretaker should re-link or
                # archive it. Reported, never altered.
                unlinked.append(f"{space.slug}/{channel.slug}")
                continue

            explain: list[dict] | None = [] if args.explain else None
            counts = chm.backfill_channel(
                db, channel=channel, space=space, explain=explain,
            )
            for key in totals:
                totals[key] += counts.get(key, 0)

            interesting = (
                counts.get("added") or counts.get("readmitted") or args.explain
            )
            if interesting:
                flags = []
                if channel.is_archived:
                    flags.append("archived")
                if not channel.show_in_navigation:
                    flags.append("hidden")
                suffix = f"  [{', '.join(flags)}]" if flags else ""
                print(
                    f"    {space.slug}/{channel.slug:28} "
                    f"type={channel.channel_type:9} "
                    f"+{counts.get('added', 0)} added, "
                    f"{counts.get('already_member', 0)} already in, "
                    f"{link_count} link(s){suffix}"
                )
                for ref in _describe_links(db, channel.id):
                    print(f"        link: {ref}")
            if explain:
                for row in explain:
                    mark = "+" if row["outcome"] in ("added", "readmitted") else "-"
                    print(f"        {mark} {row['email']:42} {row['reason']}")

        if args.apply:
            db.commit()
            print("\n  committed")
        else:
            db.rollback()
            print("\n  rolled back — re-run with --apply to write")

        print(f"\n  considered                 {totals.get('considered', 0)}")
        print(f"  added                      {totals['added']}")
        print(f"  already a member           {totals['already_member']}")
        print(f"  re-admitted after revoke   {totals['readmitted']}")
        print(
            f"  left out by creator removal {totals['blocked_by_creator_removal']}"
            "   <- intentional"
        )
        print(
            f"  skipped, caretaker         {totals.get('skipped_caretaker', 0)}"
            "   <- reach every channel by role"
        )
        print(
            f"  skipped, never joined      "
            f"{totals.get('skipped_no_acquisition', 0)}"
            "   <- keep access, no permanent row"
        )
        if unlinked:
            print(
                f"\n  {len(unlinked)} channel(s) name an experience that no "
                "longer exists, so nobody can qualify through them:"
            )
            for name in unlinked[:20]:
                print(f"    {name}")
            print("  Re-link or archive them; this script changes nothing.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
