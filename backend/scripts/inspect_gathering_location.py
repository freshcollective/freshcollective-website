#!/usr/bin/env python
"""What does a Gathering actually store in its location fields?

Written for a reported defect: a creator changed **Public location** on
a published Gathering three times and the previous value kept coming
back. The editor's box is populated from the creator detail endpoint,
which did not return ``venue_locality`` at all — so the box was always
blank on load and a save that left it alone sent ``null``. The
question this script answers is the one that cannot be answered from
the code: given that, *what is in the row right now*.

Usage, from the fc-api Render Shell::

    python scripts/inspect_gathering_location.py <event-id> [<event-id> …]
    python scripts/inspect_gathering_location.py --space nourish-connect-thrive

With ``--space`` it lists every Gathering in that Collective whose
location fields are worth a look, newest first. With ids it reports
those rows exactly, which is the form to use for a specific report.

Read-only
---------
Writes nothing and rolls back before closing. It issues SELECTs only;
there is a test asserting the source contains no write statement. It
does not repair, normalise or backfill anything — a correction, if one
is needed, is a separate decision with its own command.

Privacy
-------
``venue_address`` and ``access_instructions`` are attendee-only, so
they are reported as a length and a first-line hint rather than
printed. The question here is "is the creator's text in the wrong
column", which a shape answers; the full address does not need to be
in a terminal or a bug report.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

# A hand-run diagnostic must not raise into Sentry as an application
# alert — see FC-API-K. Cleared for this process only; it suppresses
# nothing in the application.
os.environ["SENTRY_DSN"] = ""

# The fields that decide what a viewer sees, in the order the editor
# shows them. ``public`` marks the ones any visitor may read, which is
# what makes the "is the address in a public column" question answerable.
FIELDS = (
    ("venue_locality", True,  "Public location"),
    ("venue_name", True,  "Venue name"),
    ("venue_address", False, "Venue address"),
    ("access_instructions", False, "Arrival instructions"),
    ("location_url", False, "Meeting link"),
)


def shape(value: str | None) -> str:
    """A withheld field described without being disclosed."""
    if value is None:
        return "NULL"
    text = value.strip()
    if not text:
        return "'' (empty)"
    first = text.splitlines()[0]
    head = first[:12] + ("…" if len(first) > 12 else "")
    return f"{len(text)} chars, starts {head!r}"


def report(db, event) -> None:
    from app.spaces import venue_projection

    print(f"\n  {event.title}")
    print(f"  id              {event.id}")
    print(f"  created_at      {event.created_at}")
    print(f"  updated_at      {getattr(event, 'updated_at', None)}")
    print(f"  is_published    {event.is_published}")
    print(f"  is_public       {event.is_public}")
    print(f"  status          {event.status}")
    print(f"  attendance_fmt  {getattr(event, 'attendance_format', None)!r}")
    print(f"  location_type   {getattr(event.location_type, 'value', event.location_type)!r}")
    print(f"  series_id       {getattr(event, 'series_id', None)}")
    print(f"  recurrence_sid  {getattr(event, 'recurrence_series_id', None)}")

    print("  location fields")
    for name, is_public, label in FIELDS:
        value = getattr(event, name, None)
        if is_public:
            shown = repr(value) if value is not None else "NULL"
        else:
            shown = shape(value)
        gate = "public " if is_public else "attendee"
        print(f"    {gate}  {name:20} {shown}")
        print(f"              {'':20} ({label})")

    # The one line a visitor reads, computed by the same helper the
    # Gathering page, the Series page and Discover Places all use.
    label = venue_projection.public_venue_label(event)
    print(f"  public label    {label!r}")
    if label is None:
        print("                  (nothing is said about where this is)")
    elif (event.venue_locality or "").strip():
        print("                  (from venue_locality)")
    else:
        print("                  (fallback: venue_name — venue_locality is unset)")

    # The creator editor's box is filled from the creator detail
    # endpoint. Reported here because a value present in the row and
    # absent from that payload is precisely the defect.
    from app.creator.routes import _event_to_dict

    payload = _event_to_dict(event)
    on_wire = payload.get("venue_locality", "<<key absent>>")
    print(f"  editor receives {on_wire!r}")
    if on_wire != event.venue_locality:
        print("    MISMATCH: the row holds a Public location the editor")
        print("    is never shown, so its box loads blank and a save that")
        print("    leaves it alone sends null.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_ids", nargs="*", help="Gathering ids")
    parser.add_argument("--space", default=None, help="Collective slug")
    parser.add_argument(
        "--limit", type=int, default=10,
        help="with --space, how many Gatherings to report (newest first)",
    )
    args = parser.parse_args()
    if not args.event_ids and not args.space:
        print("  give one or more event ids, or --space <slug>")
        return 2

    import app.main  # noqa: F401 — registers the mapper graph
    from app.db.session import SessionLocal
    from app.models.platform import Event, Space

    db = SessionLocal()
    try:
        rows = []
        if args.event_ids:
            for event_id in args.event_ids:
                event = db.get(Event, event_id)
                if event is None:
                    print(f"  no Gathering with id {event_id}")
                    continue
                rows.append(event)
        else:
            space = db.query(Space).filter(Space.slug == args.space).first()
            if space is None:
                print(f"  no Collective with slug {args.space!r}")
                return 2
            rows = (
                db.query(Event)
                .filter(Event.space_id == space.id)
                .order_by(Event.created_at.desc())
                .limit(args.limit)
                .all()
            )
            print(f"  {space.name} — {len(rows)} most recent Gatherings")

        for event in rows:
            report(db, event)

        print("\n  Nothing was written.\n")
        return 0
    except Exception as exc:
        print(f"\n  the diagnostic failed: {type(exc).__name__}: {exc}\n")
        return 1
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
