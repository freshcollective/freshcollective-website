#!/usr/bin/env python
"""Trace what happened to one post's notification emails.

Answers, for a real post, the question "where did it stop?" — with
evidence from the rows themselves rather than inference:

  1. the post, its channel and the channel's access arrangement
  2. whether a ``community.post.published`` event was written
  3. who the resolver selects now, and why everybody else is excluded
  4. the intents that exist, their state and any suppression reason
  5. whether the outbound guard would refuse each address, and why
  6. what the provider recorded

Read-only. It opens no network connection, sends nothing, and writes
nothing — it re-runs the resolver against the stored event in a
transaction it rolls back.

Usage, from the fc-api Render Shell::

    python scripts/trace_post_notifications.py --space moonlit-circle
    python scripts/trace_post_notifications.py --post <post_id>

With ``--space`` and no ``--post`` it takes that Collective's most
recent published post, which is usually the one being asked about.

Privacy
-------
Addresses are shown as ``a***@domain`` — the domain is the point,
because the outbound guard decides on it, and the local part is not.
Post bodies are never printed; only whether an excerpt exists.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)


def _mask(address: str | None) -> str:
    if not address:
        return "(none)"
    local, _, domain = address.partition("@")
    if not domain:
        return "(malformed)"
    return f"{local[:1]}***@{domain}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post", default=None, help="post id to trace")
    parser.add_argument(
        "--space", default=None,
        help="Collective slug; traces its latest published post",
    )
    args = parser.parse_args()
    if not args.post and not args.space:
        print("  give --post or --space")
        return 2

    import app.main  # noqa: F401 — registers the mapper graph
    from app.comms.delivery_guard import outbound_email_block
    from app.comms.models import CommunicationEvent, CommunicationIntent
    from app.comms.rollout import is_event_live, resolve_delivery_mode
    from app.comms.routing.resolvers.community import NewPostResolver
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.platform import (
        ChannelExperienceLink,
        ChannelMembership,
        CommunityPost,
        ConversationChannel,
        Space,
        SpaceMembership,
        SpaceMembershipStatus,
    )
    from app.models.user import User
    from app.services import channel_permissions as perms

    db = SessionLocal()
    try:
        # ---- 1. the post ------------------------------------------
        if args.post:
            post = db.get(CommunityPost, args.post)
        else:
            space_row = (
                db.query(Space).filter(Space.slug == args.space).first()
            )
            if space_row is None:
                print(f"  no Collective with slug {args.space!r}")
                return 2
            post = (
                db.query(CommunityPost)
                .filter(
                    CommunityPost.space_id == space_row.id,
                    CommunityPost.publication_status == "published",
                )
                .order_by(CommunityPost.created_at.desc())
                .first()
            )
        if post is None:
            print("  no published post found")
            return 2

        space = db.get(Space, post.space_id)
        channel = db.get(ConversationChannel, post.channel_id)
        author = db.get(User, post.author_id)

        print("\n  1. POST")
        print(f"     id            {post.id}")
        print(f"     collective    {space.slug if space else '?'}")
        print(f"     channel       {getattr(channel, 'name', '?')} "
              f"({getattr(channel, 'slug', '?')})")
        print(f"     author        {_mask(getattr(author, 'email', None))}")
        print(f"     published     {post.publication_status} "
              f"at {post.published_at}")
        print(f"     notifications_processed_at {post.notifications_processed_at}")

        if channel is None:
            print("\n     The post has no channel. Nothing to resolve.")
            return 1

        print("\n  2. CHANNEL ARRANGEMENT")
        print(f"     channel_type  {channel.channel_type}")
        print(f"     archived      {channel.is_archived}")
        print(f"     in navigation {channel.show_in_navigation}")
        links = (
            db.query(ChannelExperienceLink)
            .filter(ChannelExperienceLink.channel_id == channel.id)
            .all()
        )
        print(f"     links         {len(links)}")
        for link in links:
            print(f"       - {link.experience_type} {link.experience_id}")
        rows = (
            db.query(ChannelMembership)
            .filter(ChannelMembership.channel_id == channel.id)
            .all()
        )
        active = [r for r in rows if r.status == "active"]
        removed = [r for r in rows if r.status == "removed"]
        print(f"     memberships   {len(active)} active, "
              f"{len(removed)} removed")

        # ---- 3. who qualifies, and why not --------------------------
        print("\n  3. ELIGIBILITY, per active Collective member")
        members = (
            db.query(User)
            .join(SpaceMembership, SpaceMembership.user_id == User.id)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        )
        if not members:
            print("     none — the Collective has no active members")
        for user in members:
            can = perms.can_view_channel(user, channel, space, db)
            why = ""
            if user.id == post.author_id:
                why = "author — never a recipient"
            elif not can:
                row = next((r for r in rows if r.user_id == user.id), None)
                if row is not None and row.status == "removed":
                    why = f"removed by {row.removed_reason}"
                elif channel.channel_type in perms.LINKED_CHANNEL_TYPES:
                    why = "has not joined any linked experience"
                elif channel.channel_type == "private":
                    why = "not added to this private channel"
                else:
                    why = "cannot view the channel"
            print(f"     {'OK ' if can and user.id != post.author_id else '-- '}"
                  f"{_mask(user.email):34} {why}")

        # ---- 4. the event -------------------------------------------
        print("\n  4. COMMUNICATION EVENT")
        events = (
            db.query(CommunicationEvent)
            .filter(
                CommunicationEvent.event_type == "community.post.published",
                CommunicationEvent.subject_id == post.id,
            )
            .all()
        )
        print(f"     events written {len(events)}")
        if not events:
            print("     STOPPED HERE: no event. Either the post was")
            print("     scheduled rather than published immediately, or")
            print("     the emit site did not run.")
        for ev in events:
            print(f"       {ev.id}  occurred_at={ev.occurred_at}")
            ctx = ev.context or {}
            pl = ev.payload or {}
            print(f"         context channel_id={ctx.get('channel_id')} "
                  f"channel_name={ctx.get('channel_name')!r}")
            print(f"         payload author={pl.get('author_name')!r} "
                  f"is_creator_post={pl.get('is_creator_post')} "
                  f"view_url={'yes' if pl.get('view_url') else 'MISSING'} "
                  f"excerpt={'yes' if pl.get('excerpt') else 'no'}")

        # ---- 5. routing configuration -------------------------------
        print("\n  5. ROUTING CONFIGURATION")
        print(f"     app_env             {settings.app_env}")
        print(f"     comms_shadow        {settings.comms_shadow}")
        print(f"     live topics         {settings.comms_live_topics}")
        live = is_event_live("community.post.published")
        mode = resolve_delivery_mode("community.post.published")
        print(f"     event live?         {live}")
        print(f"     delivery mode       {mode}")
        if mode != "live":
            print("     STOPPED HERE: shadow intents are never dispatched.")

        # ---- 5b. preferences ----------------------------------------
        #
        # The decision pipeline consults the member's effective
        # preference first and shortcuts to a *recorded* intent when it
        # is silent — a row, but nothing sent. A category default of
        # silent would do that for everybody at once, which is why the
        # default is printed as well as the per-member answer.
        from app.comms.categories import (
            CATEGORY_COMMUNITY, CHANNEL_EMAIL_TRANSACTIONAL,
        )
        from app.comms.preferences import get_effective_preference

        print("\n  5b. PREFERENCES for (community, email_transactional)")
        from app.comms.models import CommunicationChannelDefault
        default_row = (
            db.query(CommunicationChannelDefault)
            .filter(
                CommunicationChannelDefault.category_key == CATEGORY_COMMUNITY,
                CommunicationChannelDefault.channel
                == CHANNEL_EMAIL_TRANSACTIONAL,
            )
            .first()
        )
        if default_row is None:
            print("     category default  (no row — code fallback applies)")
        else:
            print(f"     category default  {default_row.default_priority} "
                  f"locked={getattr(default_row, 'is_locked', '?')}")
        for user in members:
            if user.id == post.author_id:
                continue
            if not perms.can_view_channel(user, channel, space, db):
                continue
            priority, locked, origin = get_effective_preference(
                db, user_id=user.id, category_key=CATEGORY_COMMUNITY,
                channel=CHANNEL_EMAIL_TRANSACTIONAL,
            )
            consent = "n/a"
            flag = "" if priority != "silent" else "  <- SILENT, nothing sends"
            print(f"     {_mask(user.email):34} {priority:14} "
                  f"origin={origin:9} consent={consent}{flag}")

        # ---- 6. re-resolve ------------------------------------------
        print("\n  6. RESOLVER, re-run against the stored event")
        for ev in events:
            resolved = NewPostResolver().resolve(db, ev)
            print(f"     {ev.id} → {len(resolved)} recipient(s)")
            for r in resolved:
                u = db.get(User, r.user_id)
                print(f"        {_mask(getattr(u, 'email', None))}")
            if not resolved:
                print("        STOPPED HERE: nobody resolved. See step 3.")

        # ---- 7. intents ---------------------------------------------
        print("\n  7. INTENTS")
        intents = (
            db.query(CommunicationIntent)
            .filter(CommunicationIntent.event_id.in_([e.id for e in events]))
            .all()
        ) if events else []
        print(f"     intents created {len(intents)}")
        if events and not intents:
            print("     STOPPED HERE: the event exists but produced no")
            print("     intents. Preference, consent, suppression or a")
            print("     missing template/provider mapping — the decision")
            print("     pipeline records the reason on the intent it")
            print("     would have made, so no row means it stopped")
            print("     before creating one.")
        for i in intents:
            print(f"       {i.channel:22} state={i.state:12} "
                  f"mode={i.delivery_mode:7} "
                  f"to={_mask(i.recipient_address)}")
            print(f"         template={i.template_key}")
            print(f"         queued={i.queued_at} sent={i.sent_at} "
                  f"terminal={i.terminal_at}")
            if i.suppression_reason:
                print(f"         suppression_reason={i.suppression_reason}")
            if i.scheduled_for:
                print(f"         scheduled_for={i.scheduled_for}  "
                      "<- deferred (quiet hours or digest)")

        # ---- 8. the outbound guard ----------------------------------
        print("\n  8. OUTBOUND GUARD, evaluated per address")
        print("     (this is the last gate before Resend)")
        addresses = {
            i.recipient_address for i in intents if i.recipient_address
        }
        if not addresses:
            # Still useful: show what WOULD be blocked for the eligible
            # members, which is the common cause with test accounts.
            addresses = {
                u.email for u in members
                if u.id != post.author_id
                and perms.can_view_channel(u, channel, space, db)
            }
            if addresses:
                print("     no intents, so showing the eligible members:")
        if not addresses:
            print("     no addresses to check")
        for addr in sorted(a for a in addresses if a):
            block = outbound_email_block(addr)
            verdict = "BLOCKED" if block else "would send"
            reason = f"  {block}" if block else ""
            print(f"     {verdict:10} {_mask(addr)}{reason}")

        print("\n  Nothing was written. Rolling back.\n")
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
