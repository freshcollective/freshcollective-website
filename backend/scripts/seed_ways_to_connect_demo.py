"""Local-only demo data for looking at Ways to Connect in a browser.

Recognition is derived, never stored, so there is nothing to "seed"
directly — the only way to see the surface populated is to create the
real substrate underneath it: Collectives with the member directory
open, Gatherings with confirmed bookings and finalised attendance,
Pathways with active enrolments and completed steps. This script
builds exactly that and then gets out of the way, so what you see in
the browser has come through ``RecognitionService`` and the real API
rather than a fixture pretending to be them.

Everything it creates is tagged and nothing it creates touches an
existing row:

    users    email ends with  @wtc-demo.local
    spaces   slug starts with wtc-demo-

Cleanup deletes exactly those and lets the schema's own cascades
remove the Gatherings, Pathways, bookings, enrolments, memberships
and progress hanging off them. Spaces go first: ``spaces.creator_id``
is ON DELETE RESTRICT, so the demo creator cannot be removed while a
demo Collective still points at them.

Usage
-----

    python scripts/seed_ways_to_connect_demo.py            # dry run
    python scripts/seed_ways_to_connect_demo.py --apply    # create
    python scripts/seed_ways_to_connect_demo.py --cleanup  # remove

``--apply`` is idempotent: it clears any previous demo data first, so
re-running gives the same world rather than a second copy of it.

Safety
------

Refuses to run against anything but a local database, and refuses on
sight of a hostname that looks managed. It writes only to the tables
listed above, sends no email, touches no Stripe object, enqueues no
notification and changes no feature flag. It is a developer tool for
looking at a screen; it has no business anywhere but a laptop.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Safety — resolved before any application import touches an engine
# ---------------------------------------------------------------------------

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}

#: Substrings that mean "this is somebody's real database". Checked
#: against the whole URL, not just the host, because a managed
#: provider can hide in a query parameter too.
REMOTE_MARKERS = (
    "render.com", "rds.amazonaws", "neon.tech", "supabase",
    "heroku", "azure", "googleapis", "digitalocean", "planetscale",
    "elephantsql", "cockroachlabs", "timescale",
)

#: Local-only, and obviously so. Never a password any real person has.
DEMO_PASSWORD = "wtc-demo-local-only"

USER_MARKER = "@wtc-demo.local"
SPACE_MARKER = "wtc-demo-"


def _database_url() -> str:
    env_file = BACKEND_ROOT / ".env"
    if not env_file.exists():
        raise SystemExit("ERROR: backend/.env not found — cannot resolve DATABASE_URL")
    for line in env_file.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ERROR: DATABASE_URL not set in backend/.env")


def _describe(url: str) -> tuple[str, str, str]:
    """(host, port, database) — never the credentials."""
    body = url.split("://", 1)[1] if "://" in url else url
    hostportdb = body.rpartition("@")[2]
    hostport, _, database = hostportdb.partition("/")
    host, _, port = hostport.partition(":")
    return host, port or "5432", database.split("?")[0]


def _assert_local(url: str) -> tuple[str, str, str]:
    host, port, database = _describe(url)

    lowered = url.lower()
    for marker in REMOTE_MARKERS:
        if marker in lowered:
            raise SystemExit(
                f"REFUSING: database URL contains {marker!r} — this looks like a "
                f"managed or production database. This script is local-only."
            )

    if host not in LOCAL_HOSTS:
        raise SystemExit(
            f"REFUSING: database host is {host!r}. Only {sorted(LOCAL_HOSTS - {''})} "
            f"(or a local unix socket) are allowed."
        )

    return host, port, database


# ---------------------------------------------------------------------------

def _register_models() -> None:
    """Import every model module before touching the ORM.

    ``User`` carries FKs into ``community_care_actions``, so a partial
    import leaves SQLAlchemy unable to resolve the relationship and
    the first flush fails with NoReferencedTableError. ``alembic/env.py``
    solves this the same way and for the same reason; the list is kept
    deliberately identical to it.
    """
    import app.models.user            # noqa: F401
    import app.models.platform        # noqa: F401
    import app.models.community_care  # noqa: F401
    import app.models.place           # noqa: F401
    import app.models.payment         # noqa: F401
    import app.models.payment_option  # noqa: F401
    import app.models.payment_option_schedule  # noqa: F401
    import app.models.payment_option_grant     # noqa: F401
    import app.models.access_pass     # noqa: F401
    import app.models.access_grant_record      # noqa: F401
    import app.models.creator_billing # noqa: F401
    import app.models.notification    # noqa: F401
    import app.models.activity        # noqa: F401
    import app.models.purchase_intent # noqa: F401
    import app.models.purchase_plan   # noqa: F401
    import app.models.webhook_event   # noqa: F401
    import app.models.refund_operation         # noqa: F401
    import app.models.creator_payout_batch     # noqa: F401
    import app.models.sales           # noqa: F401
    import app.comms.models           # noqa: F401


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _cleanup(db) -> dict[str, int]:
    """Remove every tagged row. Deterministic: only the markers match.

    Issued as direct DELETEs rather than ``session.delete()`` so the
    database's own ON DELETE CASCADE does the work. The ORM's default
    is to null out a child's foreign key before removing the parent,
    which on ``event_bookings.event_id`` (NOT NULL) fails the whole
    transaction — the relationships here are not mapped with
    ``passive_deletes``, and teaching a demo script to care about that
    would be the wrong place to fix it. The schema already knows what
    depends on what; this just asks it.

    Spaces go first: ``spaces.creator_id`` is ON DELETE RESTRICT, so
    the demo host cannot be removed while a demo Collective still
    points at them.
    """
    from sqlalchemy import text

    removed: dict[str, int] = {}

    # Cascades from spaces: events -> event_bookings, pathways ->
    # pathway_steps -> step_progress, pathways -> enrollments, and
    # space_memberships.
    result = db.execute(
        text("DELETE FROM spaces WHERE slug LIKE :p"),
        {"p": f"{SPACE_MARKER}%"},
    )
    removed["collectives"] = result.rowcount or 0

    # Cascades from users: anything they hold elsewhere. In practice
    # nothing, since demo members only ever join demo Collectives.
    result = db.execute(
        text("DELETE FROM users WHERE email LIKE :p"),
        {"p": f"%{USER_MARKER}"},
    )
    removed["members"] = result.rowcount or 0

    # The session may still hold identity-map copies of rows the
    # database has just removed; expire them so nothing stale is
    # flushed back on commit.
    db.expire_all()
    return removed


def _seed(db, now: datetime) -> dict:
    from app.core.security import hash_password
    from app.models.platform import (
        BookingStatus, Enrollment, EnrollmentStatus, Event, EventBooking,
        Pathway, PathwayStatus, PathwayStep, Space, SpaceMembership,
        SpaceMembershipStatus, SpaceRole, StepProgress,
    )
    from app.models.user import User

    created = {
        "members": [], "collectives": [], "gatherings": [],
        "pathways": [], "bookings": 0, "enrolments": 0, "progress": 0,
        "memberships": 0,
    }
    pw_hash = hash_password(DEMO_PASSWORD)

    def member(handle: str, name: str | None, **kw) -> User:
        u = User(
            id=_uid("u_wtc"),
            email=f"{handle}{USER_MARKER}",
            name=name,
            password_hash=pw_hash,
            role=kw.pop("role", "user"),
            # Verified so the surface is not obscured by the
            # verify-your-email banner.
            email_verified_at=now,
            onboarding_completed_at=now,
            **kw,
        )
        db.add(u)
        created["members"].append((u.email, name))
        return u

    def collective(slug: str, name: str, creator: User) -> Space:
        s = Space(
            id=_uid("s_wtc"),
            slug=f"{SPACE_MARKER}{slug}",
            name=name,
            status="active",
            creator_id=creator.id,
            timezone="Australia/Melbourne",
            # Recognition's privacy gate. A Collective with the member
            # directory closed produces nothing, by design — so a demo
            # of the populated surface must have it open.
            show_member_directory=True,
            tagline="Local demo data for reviewing Ways to Connect.",
        )
        db.add(s)
        created["collectives"].append((s.slug, s.name))
        return s

    def join(user: User, space: Space, role=SpaceRole.learner) -> None:
        db.add(SpaceMembership(
            id=_uid("sm_wtc"), user_id=user.id, space_id=space.id,
            role=role, status=SpaceMembershipStatus.active,
        ))
        created["memberships"] += 1

    def gathering(space: Space, title: str, *, days: int, finalised=False,
                  status="active") -> Event:
        starts = now + timedelta(days=days)
        e = Event(
            id=_uid("e_wtc"), space_id=space.id, title=title,
            starts_at=starts, ends_at=starts + timedelta(hours=1),
            status=status, is_published=True, requires_booking=True,
            capacity=20, location_type="zoom", gathering_type="circle",
            attendance_format="online", booking_access_type="free",
            # Non-NULL is what "the creator finished the roster" means;
            # without it a past Gathering is unknown, not attended.
            attendance_completed_at=(
                starts + timedelta(hours=2) if finalised else None
            ),
        )
        db.add(e)
        created["gatherings"].append((e.title, starts.isoformat(timespec="minutes")))
        return e

    def book(user: User, event: Event, attendance: str | None = None) -> None:
        db.add(EventBooking(
            id=_uid("bk_wtc"), event_id=event.id, user_id=user.id,
            status=BookingStatus.confirmed, attendance_status=attendance,
        ))
        created["bookings"] += 1

    def pathway(space: Space, slug: str, title: str) -> tuple[Pathway, PathwayStep]:
        p = Pathway(
            id=_uid("pw_wtc"), space_id=space.id,
            slug=f"{SPACE_MARKER}{slug}", title=title,
            status=PathwayStatus.active,
        )
        db.add(p)
        db.flush()
        step = PathwayStep(
            id=_uid("pst_wtc"), pathway_id=p.id, slug="opening",
            title="Opening reflection", position=0, content_type="text",
        )
        db.add(step)
        created["pathways"].append((p.slug, p.title))
        return p, step

    def walk(user: User, p: Pathway, step: PathwayStep, *, started=True) -> None:
        db.add(Enrollment(
            id=_uid("en_wtc"), user_id=user.id, pathway_id=p.id,
            status=EnrollmentStatus.active,
        ))
        created["enrolments"] += 1
        if started:
            # completed_at non-NULL is the whole rule: a draft
            # reflection writes a row too, and must not count.
            db.add(StepProgress(
                id=_uid("sp_wtc"), user_id=user.id, step_id=step.id,
                completed_at=now - timedelta(days=2),
            ))
            created["progress"] += 1

    # -- people --------------------------------------------------------
    host    = member("host",    "Demo Host", role="creator")
    viewer  = member("viewer",  "Demo Viewer")
    empty   = member("empty",   "Demo Empty")
    alone   = member("alone",   "Demo Alone")
    sarah   = member("sarah",   "Sarah")
    james   = member("james",   "James")
    maya    = member("maya",    "Maya")
    emma    = member("emma",    "Emma")
    # No name set, and no public creator profile. Ordinary, not broken:
    # the API returns display_name: null and the surface counts them.
    quiet_a = member("quiet-a", None)
    quiet_b = member("quiet-b", None)
    # Would qualify through the Thursday Circle, and must not appear.
    optout  = member("optout",  "Demo Opted Out", ways_to_connect_enabled=False)
    db.flush()

    # -- collectives ---------------------------------------------------
    embody = collective("embody",    "[WTC DEMO] EMBODY",    host)
    grove  = collective("the-grove", "[WTC DEMO] The Grove", host)
    db.flush()

    join(host, embody, SpaceRole.creator)
    join(host, grove,  SpaceRole.creator)
    for u in (viewer, empty, sarah, james, maya, quiet_a, quiet_b, optout):
        join(u, embody)
    for u in (viewer, emma):
        join(u, grove)
    db.flush()

    # ------------------------------------------------------------------
    # Every person card needs TWO shared signals. One Gathering is a
    # coincidence; a card built on it reads as arbitrary. So each
    # candidate below carries at least two, and a few carry exactly one
    # on purpose — they should stay out of the cards while still being
    # named on the Gathering's own page.
    # ------------------------------------------------------------------

    # -- Sarah: two attended + two upcoming. Tier 1 (history leads),
    #    and the upcoming pair proves the reason sentence does not get
    #    hijacked by the diary.
    for title, days in (("Autumn Circle", -18), ("Late Summer Circle", -52)):
        past = gathering(embody, title, days=days, finalised=True)
        for u in (viewer, sarah):
            book(u, past, attendance="attended")
    thursday = gathering(embody, "Thursday Circle", days=3)
    full_moon = gathering(embody, "Full Moon Gathering", days=10)
    for ev in (thursday, full_moon):
        for u in (viewer, sarah):
            book(u, ev)
    # Unnamed members ride the Full Moon booking so the in-context line
    # still has somebody to count. They never earn a card either way.
    for u in (quiet_a, quiet_b):
        book(u, full_moon)
    # Opted out, and would otherwise qualify on this pair alone.
    for title, days in (("Quiet Sitting", -22), ("Quieter Sitting", -60)):
        past = gathering(embody, title, days=days, finalised=True)
        for u in (viewer, optout):
            book(u, past, attendance="attended")

    # -- James: two attended, one of them recent. Tier 1.
    for title, days in (("Morning Practice", -10), ("Evening Practice", -38)):
        past = gathering(embody, title, days=days, finalised=True)
        for u in (viewer, james):
            book(u, past, attendance="attended")

    # -- Maya: repeated co-attendance, both outside the 90-day
    #    single-occurrence window. Two signals, and the decay rule
    #    keeps them because there are two.
    for title, days in (("Winter Session", -120), ("Spring Session", -150)):
        past = gathering(embody, title, days=days, finalised=True)
        for u in (viewer, maya):
            book(u, past, attendance="attended")

    # -- Emma: one attended Gathering plus a shared Pathway. Tier 1
    #    via the Gathering, and the card names both.
    alignment, step = pathway(grove, "life-in-alignment", "Life in Alignment")
    for u in (viewer, emma):
        walk(u, alignment, step)
    grove_sit = gathering(grove, "Grove Sitting", days=-30, finalised=True)
    for u in (viewer, emma):
        book(u, grove_sit, attendance="attended")

    # -- Lena: a fourth pair with repeated attendance, so category 1
    #    holds four people for three slots and the daily rotation is
    #    actually visible on this viewer.
    lena = member("lena", "Lena")
    db.flush()
    join(lena, embody)
    for title, days in (("Candle Sitting", -26), ("Candle Sitting II", -64)):
        past = gathering(embody, title, days=days, finalised=True)
        for u in (viewer, lena):
            book(u, past, attendance="attended")

    # -- Otto: exactly one signal. Must never receive a card, and must
    #    still be named on that Gathering's own page.
    otto = member("otto", "Otto")
    db.flush()
    join(otto, embody)
    once = gathering(embody, "One-Off Workshop", days=14)
    for u in (viewer, otto):
        book(u, once)

    # ------------------------------------------------------------------
    # Exact-count viewers.
    #
    # The rich viewer above has four eligible candidates for three
    # slots, so which three appear rotates by the day — good for seeing
    # the rotation, useless for reviewing a fixed card count. These own
    # their own Gatherings and peers, so their candidate set is exactly
    # the size named, every day.
    # ------------------------------------------------------------------

    # Three cards, one per evidence tier, deterministic.
    viewer_three = member("viewer-three", "Demo Viewer Three")
    vera = member("vera", "Vera")   # two attended        -> tier 1
    wren = member("wren", "Wren")   # attended + pathway  -> tier 1
    tara = member("tara", "Tara")   # pathway + upcoming  -> tier 2
    db.flush()
    for u in (viewer_three, vera, wren, tara):
        join(u, embody)

    for title, days in (("Harvest Sitting", -16), ("Midwinter Sitting", -70)):
        past = gathering(embody, title, days=days, finalised=True)
        for u in (viewer_three, vera):
            book(u, past, attendance="attended")

    wren_sit = gathering(embody, "Dawn Sitting", days=-40, finalised=True)
    for u in (viewer_three, wren):
        book(u, wren_sit, attendance="attended")
    coming_home, ch_step = pathway(embody, "coming-home", "Coming Home")
    for u in (viewer_three, wren):
        walk(u, coming_home, ch_step)

    tending, t_step = pathway(embody, "tending-the-fire", "Tending the Fire")
    for u in (viewer_three, tara):
        walk(u, tending, t_step)
    sunrise = gathering(embody, "Sunrise Circle", days=5)
    for u in (viewer_three, tara):
        book(u, sunrise)

    # Two cards, from opposite ends of the category list — plus Pia,
    # who has two confirmed bookings for two future Gatherings and
    # therefore no card at all. Two signals, nothing realised: the
    # stricter rule, visible on the same page as the people it lets
    # through.
    viewer_two = member("viewer-two", "Demo Viewer Two")
    nina = member("nina", "Nina")   # two attended        -> category 1
    ravi = member("ravi", "Ravi")   # pathway + upcoming  -> category 5
    pia  = member("pia",  "Pia")    # two upcoming        -> NOT eligible
    db.flush()
    for u in (viewer_two, nina, ravi, pia):
        join(u, embody)

    for title, days in (("Stillness Sitting", -12), ("Stillness Sitting II", -48)):
        past = gathering(embody, title, days=days, finalised=True)
        for u in (viewer_two, nina):
            book(u, past, attendance="attended")

    keeping, k_step = pathway(embody, "keeping-the-thread", "Keeping the Thread")
    for u in (viewer_two, ravi):
        walk(u, keeping, k_step)
    ravi_next = gathering(embody, "Riverside Circle", days=9)
    for u in (viewer_two, ravi):
        book(u, ravi_next)

    for title, days in (("Evening Practice II", 6), ("Evening Practice III", 20)):
        ev = gathering(embody, title, days=days)
        for u in (viewer_two, pia):
            book(u, ev)

    # One card, plus two single-signal people who must stay out of it.
    viewer_one = member("viewer-one", "Demo Viewer One")
    rosa = member("rosa", "Rosa")   # attended + upcoming -> tier 1
    iris = member("iris", "Iris")   # one upcoming only   -> no card
    finn = member("finn", "Finn")   # one attended only   -> no card
    db.flush()
    for u in (viewer_one, rosa, iris, finn):
        join(u, embody)
    rosa_past = gathering(embody, "Morning Sit", days=-9, finalised=True)
    for u in (viewer_one, rosa):
        book(u, rosa_past, attendance="attended")
    rosa_next = gathering(embody, "Morning Sit (next)", days=7)
    for u in (viewer_one, rosa):
        book(u, rosa_next)
    iris_ev = gathering(embody, "Drop-in Circle", days=11)
    for u in (viewer_one, iris):
        book(u, iris_ev)
    finn_ev = gathering(embody, "Past Drop-in", days=-25, finalised=True)
    for u in (viewer_one, finn):
        book(u, finn_ev, attendance="attended")

    db.flush()
    return created


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local-only Ways to Connect demo data.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="Create the demo world (clears any previous run first).")
    mode.add_argument("--cleanup", action="store_true",
                      help="Remove every tagged demo record and nothing else.")
    args = parser.parse_args()

    url = _database_url()
    host, port, database = _assert_local(url)

    print("Ways to Connect — local demo seed")
    print(f"  database : {database}")
    print(f"  host     : {host or '(unix socket)'}:{port}")
    print(f"  mode     : {'cleanup' if args.cleanup else 'apply' if args.apply else 'DRY RUN'}")
    print(f"  tags     : users {USER_MARKER!r} · collectives {SPACE_MARKER!r}*")
    print()

    if not (args.apply or args.cleanup):
        print("Dry run — nothing written. Re-run with --apply to create the demo")
        print("world, or --cleanup to remove it.")
        return 0

    _register_models()
    from app.core.database import SessionLocal

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        removed = _cleanup(db)
        if args.cleanup:
            db.commit()
            print(f"Removed {removed['collectives']} demo Collective(s) "
                  f"and {removed['members']} demo member(s).")
            print("Cascades took their Gatherings, Pathways, bookings, "
                  "enrolments and progress with them.")
            return 0

        if removed["collectives"] or removed["members"]:
            print(f"Cleared previous run: {removed['collectives']} Collective(s), "
                  f"{removed['members']} member(s).\n")

        created = _seed(db, now)
        db.commit()

        print(f"Created {len(created['members'])} members, "
              f"{len(created['collectives'])} Collectives, "
              f"{len(created['gatherings'])} Gatherings, "
              f"{len(created['pathways'])} Pathway(s),")
        print(f"        {created['memberships']} memberships, "
              f"{created['bookings']} bookings, "
              f"{created['enrolments']} enrolments, "
              f"{created['progress']} completed steps.\n")

        print("Sign in locally with any of these — password is the same for all:")
        print(f"    password: {DEMO_PASSWORD}\n")
        print(f"    three cards, rotating : viewer{USER_MARKER}")
        print(f"      four named candidates, so which three appear moves by the day")
        print(f"    three cards, fixed    : viewer-three{USER_MARKER}")
        print(f"      imminent Gathering (Tara) + repeated attendance (Vera) + Pathway (Wren)")
        print(f"    two cards             : viewer-two{USER_MARKER}")
        print(f"    one card              : viewer-one{USER_MARKER}")
        print(f"    empty, belongs        : empty{USER_MARKER}")
        print(f"    empty, belongs nowhere: alone{USER_MARKER}")
        print(f"    opted out             : optout{USER_MARKER}")
        print()
        print("Then open  http://localhost:3000/ways-to-connect")
        print()
        print("Remove it all again with:")
        print("    python scripts/seed_ways_to_connect_demo.py --cleanup")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
