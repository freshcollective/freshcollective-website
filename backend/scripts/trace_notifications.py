#!/usr/bin/env python
"""Where did this notification stop? — for any announcement we send.

Generalises ``trace_post_notifications.py``, which answered the
question for Conversations posts and found the preference default that
had been silently swallowing every one of them. The same walk applies
to every announcement; only "what is the subject" differs.

Supported kinds::

    post        a Conversations post               community.post.published
    pathway     a Pathway publication              pathway.published
    gathering   a standalone Gathering publication gathering.published
    series      a Gathering Series publication     series.published

Usage, from the fc-api Render Shell::

    python scripts/trace_notifications.py --kind pathway  --space moonlit-circle
    python scripts/trace_notifications.py --kind gathering --space moonlit-circle
    python scripts/trace_notifications.py --kind series   --space moonlit-circle
    python scripts/trace_notifications.py --kind post     --space moonlit-circle

``--space`` takes the most recent subject of that kind, which is
usually the one being asked about. ``--id`` names one exactly.

The post kind delegates to ``trace_post_notifications.run_trace``
rather than reimplementing channel eligibility — that code is tested
and the duplicate would drift.

Read-only
---------
Writes nothing, sends nothing, opens no network connection, and rolls
back before it closes. It reports existing state: it will not create a
missing event, reprocess a notification, retry a send, or touch a
preference. There is a test asserting the source contains no write
statement at all.

Privacy
-------
Addresses are masked to ``a***@domain``. The domain is the part that
decides delivery — the outbound guard refuses reserved domains — and
the local part is nobody's business here. Message bodies are never
printed; only whether an excerpt exists.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

# Importing ``app.main`` below initialises Sentry, so an unhandled
# crash in a hand-run diagnostic arrives as an application error alert
# — which is how a wrong attribute name in the previous script became
# Sentry FC-API-K, with "0 users affected" because no request was
# involved. Cleared for this process only; it suppresses nothing in
# the application.
os.environ["SENTRY_DSN"] = ""


def mask(address: str | None) -> str:
    if not address:
        return "(none)"
    local, _, domain = address.partition("@")
    if not domain:
        return "(malformed)"
    return f"{local[:1]}***@{domain}"


# ---------------------------------------------------------------------------
# What each kind is
# ---------------------------------------------------------------------------
#
# One row per announcement we send. Adding a kind means adding a row,
# not another script — which is the point of this file.

KINDS: dict[str, dict] = {
    "post": {
        "event_type": "community.post.published",
        "label": "Conversations post",
    },
    "pathway": {
        "event_type": "pathway.published",
        "label": "Pathway publication",
        # ``[pathway-slug]``, hyphenated — not the camelCase the other
        # two use. Caught by the filesystem check rather than by
        # reading, which is the point of checking.
        "route": ("spaces", "[slug]", "pathways", "[pathway-slug]"),
    },
    "gathering": {
        "event_type": "gathering.published",
        "label": "Gathering publication",
        "route": ("spaces", "[slug]", "events", "[eventId]"),
    },
    "series": {
        "event_type": "series.published",
        "label": "Series publication",
        "route": ("spaces", "[slug]", "gathering-series", "[series-slug]"),
    },
}


def _find_subject(db, kind: str, space, subject_id: str | None):
    """The experience being traced, and how to describe it."""
    from app.models.platform import Event, EventSeries, Pathway

    model = {"pathway": Pathway, "gathering": Event, "series": EventSeries}[kind]
    if subject_id:
        return db.get(model, subject_id)
    query = db.query(model).filter(model.space_id == space.id)
    order = getattr(model, "created_at", None) or getattr(model, "id")
    return query.order_by(order.desc()).first()


def _cta_lines(db, kind: str) -> list[str]:
    """The button label as it will render, and any stored override.

    Admin-editable copy is per *slot* and never carries a link — the
    destination is generated — so an override cannot reintroduce a
    broken one. Printed anyway, because "is a saved template still
    rendering the old wording" is otherwise unanswerable without
    opening an inbox.
    """
    from app.comms.templates.editable import (
        get_declaration, load_overrides, resolver_for,
    )

    key = f"{KINDS[kind]['event_type']}.email_transactional"
    out: list[str] = []
    try:
        decl = get_declaration(key)
        if decl is None:
            return [f"cta           (no declaration for {key})"]
        slots = {slot.slot_id for slot in decl.slots}
        labels = [s for s in ("cta_label", "cta_label_paid") if s in slots]
        if not labels:
            out.append("cta           (label is fixed in code)")
        else:
            r = resolver_for(db, key, {})
            for slot_id in labels:
                out.append(f"cta {slot_id:9} {r.text(slot_id)!r}")
        stored = load_overrides(db, key)
        if stored:
            out.append(f"overrides     {', '.join(sorted(stored))}")
        else:
            out.append("overrides     none — rendering the code defaults")
    except Exception as exc:  # a diagnostic must not raise
        out.append(f"cta           (unavailable: {type(exc).__name__}: {exc})")
    return out


def _describe(kind: str, subject, space) -> tuple[list[tuple[str, str]], str, str]:
    """``(rows, dedupe_key, url_path)`` for one subject."""
    from app.services import publication_announcement as pub
    from app.services.pathway_announcement import announcement_dedupe_key

    if kind == "pathway":
        status = getattr(subject.status, "value", subject.status)
        rows = [
            ("id", subject.id),
            ("title", subject.title),
            ("status", str(status)),
            ("access_type", str(
                getattr(subject.access_type, "value", subject.access_type),
            )),
        ]
        return (
            rows,
            announcement_dedupe_key(subject.id, subject.space_id),
            f"/spaces/{space.slug}/pathways/{subject.slug}",
        )
    if kind == "gathering":
        rows = [
            ("id", subject.id),
            ("title", subject.title),
            ("is_published", str(subject.is_published)),
            ("status", str(getattr(subject, "status", "active"))),
            ("notify_members", str(getattr(subject, "notify_members", "?"))),
            ("series_id", str(getattr(subject, "series_id", None))),
            ("recurrence_series_id", str(
                getattr(subject, "recurrence_series_id", None),
            )),
            ("starts_at", str(subject.starts_at)),
        ]
        return (
            rows,
            pub.gathering_dedupe_key(subject.id, subject.space_id),
            f"/spaces/{space.slug}/events/{subject.id}",
        )
    # series
    rows = [
        ("id", subject.id),
        ("title", subject.title),
        ("status", str(getattr(subject.status, "value", subject.status))),
        ("published_at", str(subject.published_at)),
        ("notify_members", str(getattr(subject, "notify_members", "?"))),
    ]
    return (
        rows,
        pub.series_dedupe_key(subject.id, subject.space_id),
        f"/spaces/{space.slug}/gathering-series/{subject.slug}",
    )


def _route_exists(kind: str) -> tuple[bool, str]:
    """Does the URL this announcement links to have a page?

    Reads the frontend tree, because an email carrying a tidy-looking
    URL to a route that was never built is exactly the failure the
    View Conversation button had.
    """
    segments = KINDS[kind].get("route")
    if not segments:
        return (True, "(not applicable)")
    route = (
        BACKEND.parent / "frontend" / "src" / "app" / Path(*segments)
        / "page.tsx"
    )
    return (route.exists(), str(route))


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def run_trace(db, kind: str, subject, space) -> int:
    """Walk one publication through the notification path."""
    from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, TOPIC_TO_CATEGORY
    from app.comms.delivery_guard import outbound_email_block
    from app.comms.models import (
        CommunicationChannelDefault,
        CommunicationEvent,
        CommunicationIntent,
    )
    from app.comms.preferences import get_effective_preference
    from app.comms.registry import get_event_definition
    from app.comms.rollout import is_event_live, resolve_delivery_mode
    from app.comms.routing.resolver import get_resolver_for
    from app.core.config import settings
    from app.models.platform import SpaceMembership, SpaceMembershipStatus
    from app.models.user import User

    spec = KINDS[kind]
    event_type = spec["event_type"]
    rows, dedupe_key, url_path = _describe(kind, subject, space)

    print(f"\n  1. SOURCE EXPERIENCE — {spec['label']}")
    print(f"     collective    {space.slug}")
    print(f"     event_type    {event_type}")
    for name, value in rows:
        print(f"     {name:<20} {value}")

    print("\n  2. COMMUNICATION EVENT")
    print(f"     dedupe_key    {dedupe_key}")
    events = (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == event_type,
            CommunicationEvent.dedupe_key == dedupe_key,
        )
        .all()
    )
    print(f"     events        {len(events)}")
    if not events:
        print("     STOPPED HERE: no event. Either it has not been")
        print("     published yet, the creator turned Notify off, it is a")
        print("     Series occurrence (which never announces), or it was")
        print("     already announced under a different key.")
    for ev in events:
        backfilled = (ev.context or {}).get("backfilled")
        origin = "BACKFILLED (marked announced, never sent)" if backfilled \
            else "emitted by a publication"
        print(f"       {ev.id}  occurred_at={ev.occurred_at}")
        print(f"         origin      {origin}")

    print("\n  3. ROUTING CONFIGURATION")
    definition = get_event_definition(event_type)
    category = TOPIC_TO_CATEGORY.get(definition.topic) if definition else None
    print(f"     app_env       {settings.app_env}")
    print(f"     comms_shadow  {settings.comms_shadow}")
    print(f"     live topics   {settings.comms_live_topics}")
    print(f"     topic         {definition.topic if definition else '?'}")
    print(f"     category      {category}")
    print(f"     event live?   {is_event_live(event_type)}")
    mode = resolve_delivery_mode(event_type)
    print(f"     delivery mode {mode}")
    if mode != "live":
        print("     STOPPED HERE: shadow intents are never dispatched.")

    print("\n  4. PREFERENCES")
    default_row = (
        db.query(CommunicationChannelDefault)
        .filter(
            CommunicationChannelDefault.category_key == category,
            CommunicationChannelDefault.channel == CHANNEL_EMAIL_TRANSACTIONAL,
        )
        .first()
    ) if category else None
    if default_row is None:
        print("     category default  MISSING ROW — the preference lookup")
        print("                       raises UnsupportedChannelError")
    else:
        resolved = "immediate" if default_row.default_enabled else "silent"
        print(f"     category default  default_enabled="
              f"{default_row.default_enabled} → {resolved}  "
              f"locked={default_row.is_locked}")

    members = (
        db.query(User)
        .join(SpaceMembership, SpaceMembership.user_id == User.id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .all()
    )
    actor_id = events[0].actor_user_id if events else None
    for user in members:
        note = " <- creator, excluded" if user.id == actor_id else ""
        if category:
            try:
                priority, locked, origin = get_effective_preference(
                    db, user_id=user.id, category_key=category,
                    channel=CHANNEL_EMAIL_TRANSACTIONAL,
                )
            except Exception as exc:  # noqa: BLE001
                priority, origin = f"ERR {type(exc).__name__}", "-"
                locked = "-"
            silent = "  <- SILENT, nothing sends" if priority == "silent" else ""
            print(f"     {mask(user.email):34} {priority:14} "
                  f"origin={origin:9}{silent}{note}")

    print("\n  5. RECIPIENT RESOLUTION")
    if not events:
        print("     no event, so nothing to resolve")
    for ev in events:
        resolver = get_resolver_for(event_type)
        if resolver is None:
            print(f"     no resolver registered for {event_type}")
            continue
        resolved = resolver.resolve(db, ev)
        print(f"     {ev.id} → {len(resolved)} recipient(s)")
        for recipient in resolved:
            who = db.get(User, recipient.user_id)
            print(f"        {mask(getattr(who, 'email', None))}")
        excluded = {m.id for m in members} - {r.user_id for r in resolved}
        for user_id in sorted(excluded):
            who = db.get(User, user_id)
            why = "creator" if user_id == ev.actor_user_id else "not eligible"
            print(f"        -- {mask(getattr(who, 'email', None)):30} {why}")
        if not resolved:
            print("        STOPPED HERE: nobody resolved. See section 4.")

    print("\n  6. DELIVERY INTENTS")
    intents = (
        db.query(CommunicationIntent)
        .filter(CommunicationIntent.event_id.in_([e.id for e in events]))
        .all()
    ) if events else []
    print(f"     intents       {len(intents)}")
    if events and not intents:
        print("     STOPPED HERE: the event exists and produced no intent.")
        print("     Preference, consent, suppression or a missing template")
        print("     or provider mapping.")
    for intent in intents:
        print(f"       {intent.channel:22} state={intent.state:12} "
              f"mode={intent.delivery_mode:7} to={mask(intent.recipient_address)}")
        print(f"         template    {intent.template_key}")
        print(f"         queued={intent.queued_at} sent={intent.sent_at} "
              f"terminal={intent.terminal_at}")
        if intent.suppression_reason:
            print(f"         suppression {intent.suppression_reason}")
        if intent.scheduled_for:
            print(f"         scheduled_for={intent.scheduled_for}  "
                  "<- deferred (quiet hours or digest)")

    print("\n  7. OUTBOUND DELIVERY")
    print("     (the guard is the last gate before Resend)")
    addresses = {i.recipient_address for i in intents if i.recipient_address}
    if not addresses:
        addresses = {
            m.email for m in members if m.id != actor_id and m.email
        }
        if addresses:
            print("     no intents, so showing the eligible members:")
    if not addresses:
        print("     no addresses to check")
    for address in sorted(addresses):
        block = outbound_email_block(address)
        verdict = "BLOCKED" if block else "would send"
        reason = f"  {block.reason}" if block else ""
        print(f"     {verdict:10} {mask(address)}{reason}")
    reached = [i for i in intents if i.sent_at is not None]
    print(f"     reached the provider: {len(reached)} of {len(intents)}")

    print("\n  8. LINK DIAGNOSTICS")
    print(f"     path          {url_path}")
    # What the email actually carries. A path is not a link: a mail
    # client has no base URL to resolve one against, so the Pathway
    # announcement rendered its CTA with an unresolvable ``href`` and
    # printed the bare path under "or copy this link". Shown as the
    # absolute form so that failure is visible from here.
    from app.comms.templates.base import absolute_email_url

    absolute = absolute_email_url(url_path)
    print(f"     email link    {absolute}")
    if not absolute.startswith(("http://", "https://")):
        print("     STOPPED HERE: the email would carry a relative link.")
        print("     Check PUBLIC_APP_URL — see app/core/public_url.py.")
    for line in _cta_lines(db, kind):
        print(f"     {line}")
    exists, route = _route_exists(kind)
    print(f"     route exists  {exists}")
    if not exists:
        print(f"     STOPPED HERE: no page at {route}")
    print("     auth          Collective pages resolve server-side; a")
    print("                   signed-out visitor to a non-public")
    print("                   Collective is redirected to /login?next=")
    print("                   and returned afterwards.")

    print("\n  Nothing was written.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind", default="post", choices=sorted(KINDS),
        help="which announcement to trace",
    )
    parser.add_argument("--space", default=None, help="Collective slug")
    parser.add_argument(
        "--id", default=None, dest="subject_id",
        help="exact post / pathway / gathering / series id",
    )
    args = parser.parse_args()
    if not args.space and not args.subject_id:
        print("  give --space or --id")
        return 2

    import app.main  # noqa: F401 — registers the mapper graph
    from app.db.session import SessionLocal
    from app.models.platform import Space

    db = SessionLocal()
    try:
        space = None
        if args.space:
            space = db.query(Space).filter(Space.slug == args.space).first()
            if space is None:
                print(f"  no Collective with slug {args.space!r}")
                return 2

        if args.kind == "post":
            # Delegated rather than reimplemented: channel eligibility
            # is the hard part of the post trace and it is already
            # tested.
            from trace_post_notifications import run_trace as post_trace
            from app.models.platform import CommunityPost

            if args.subject_id:
                post = db.get(CommunityPost, args.subject_id)
            else:
                post = (
                    db.query(CommunityPost)
                    .filter(
                        CommunityPost.space_id == space.id,
                        CommunityPost.publication_status == "published",
                    )
                    .order_by(CommunityPost.created_at.desc())
                    .first()
                )
            if post is None:
                print("  no published post found")
                return 2
            return post_trace(db, post)

        subject = _find_subject(db, args.kind, space, args.subject_id)
        if subject is None:
            print(f"  no {args.kind} found")
            return 2
        if space is None:
            space = db.get(Space, subject.space_id)
        return run_trace(db, args.kind, subject, space)
    except Exception as exc:  # noqa: BLE001
        # Handled, not propagated. An unhandled exception here reaches
        # Sentry as an application error with nobody affected — which
        # is exactly what FC-API-K was.
        print(f"\n  the diagnostic failed: {type(exc).__name__}: {exc}")
        print("  nothing was written.")
        return 1
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
