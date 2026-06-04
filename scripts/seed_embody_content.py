#!/usr/bin/env python3
"""
Content seed script: EMBODY collective for Fresh Collective (dev/local).

Creates or updates:
  - EMBODY space identity, description, and guidance panel
  - 3 pathways with steps (EMBODY In-Person Sessions, Home Practice, Nervous System Foundations)
  - General and pathway-specific resources
  - 10-week gathering series (Mon 6pm / Thu 6pm / Sat 9am) for the upcoming term
  - Community starter posts

Idempotent — safe to run multiple times. Existing bookings, attendance,
members, and prior series are never touched.

Usage:
    cd /home/lindsey/fc-production/backend
    .venv/bin/python ../scripts/seed_embody_content.py

TODOs (future platform work):
  1. Plan-based booking limits: Awaken=1 session/week, Activate=2/week, Empower=3/week.
  2. Paid term checkout: Stripe support for EMBODY term access + plan selection.
  3. Make-up session logic: members can book a make-up session where capacity allows.
  4. Online EMBODY: potential future pathway for recorded or live online practices.
"""

import os
import sys
from datetime import datetime, timedelta
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Must import both so SQLAlchemy relationship registry resolves correctly
import app.models.user    # noqa: F401
import app.models.platform  # noqa: F401

from app.core.database import SessionLocal
from app.models.platform import (
    CommunityPost, Event, Pathway, PathwayStep, Space, SpaceResource,
)

# ── Stable identifiers ────────────────────────────────────────────────────────

SPACE_ID   = "e5fae07f-a90e-4d39-a405-5530741f4b59"
CREATOR_ID = "cmoe3ksnb0000uu9pm2ay6vtf"

# These IDs are stable — re-running will upsert, not duplicate.
PATHWAY_IDS = {
    "in-person":   "pa000001-embd-4000-8000-000000000001",
    "home":        "pa000001-embd-4000-8000-000000000002",
    "nervous-sys": "pa000001-embd-4000-8000-000000000003",
}

STEP_IDS = {
    # EMBODY In-Person Sessions
    "ip-welcome":     "st000001-embd-4000-8000-000000000001",
    "ip-rhythm":      "st000001-embd-4000-8000-000000000002",
    "ip-bring":       "st000001-embd-4000-8000-000000000003",
    "ip-journey":     "st000001-embd-4000-8000-000000000004",
    "ip-integration": "st000001-embd-4000-8000-000000000005",
    # Home Practice
    "hp-reset":       "st000001-embd-4000-8000-000000000011",
    "hp-breath":      "st000001-embd-4000-8000-000000000012",
    "hp-mobility":    "st000001-embd-4000-8000-000000000013",
    "hp-strength":    "st000001-embd-4000-8000-000000000014",
    "hp-reflect":     "st000001-embd-4000-8000-000000000015",
}

RESOURCE_IDS = {
    # General
    "timetable":      "rs000001-embd-4000-8000-000000000001",
    "what-to-bring":  "rs000001-embd-4000-8000-000000000002",
    "ses-rhythm":     "rs000001-embd-4000-8000-000000000003",
    "makeup":         "rs000001-embd-4000-8000-000000000004",
    # EMBODY In-Person Sessions pathway
    "archetype-map":  "rs000001-embd-4000-8000-000000000011",
    "ses-notes":      "rs000001-embd-4000-8000-000000000012",
    "reflect-sheet":  "rs000001-embd-4000-8000-000000000013",
    # Home Practice pathway
    "hp-5min":        "rs000001-embd-4000-8000-000000000021",
    "hp-mobility-g":  "rs000001-embd-4000-8000-000000000022",
}

# Stable series IDs for the new upcoming term
SERIES_IDS = {
    "mon": "s0000001-embd-4000-mon0-000000000001",
    "thu": "s0000001-embd-4000-thu0-000000000001",
    "sat": "s0000001-embd-4000-sat0-000000000001",
}

POST_IDS = [
    "po000001-embd-4000-8000-000000000001",
    "po000001-embd-4000-8000-000000000002",
    "po000001-embd-4000-8000-000000000003",
]

# Stable event IDs: series prefix + week index (format: ev000001-embd-4000-XXX0-00000000000N)
def event_id(series_key: str, week: int) -> str:
    prefix = {"mon": "mon0", "thu": "thu0", "sat": "sat0"}[series_key]
    return f"ev000001-embd-4000-{prefix}-{week:012d}"


# ── Content ───────────────────────────────────────────────────────────────────

ARCHETYPE_BODY = """\
The 10-week EMBODY journey moves through seasonal feminine archetypes. Each \
archetype is a session theme — not homework, not a character to perform. Just \
a direction of energy to explore through movement, breath, and presence.

**Week 1 — Foundations**
Gaia (grounded creation) · Artemis (focused freedom) · Selene (reflective flow)

**Week 2 — Emergence**
Athena (strategic strength) · Kali (fierce transformation) · Isis (breath of rebirth)

**Week 3 — Radiance**
Sekhmet (courageous compassion) · Hathor (joyful sensuality) · Saraswati (creative flow)

**Week 4 — Expression**
Freya (liberated love) · Pele (creative fire) · Quan Yin (gentle power)

**Week 5 — Empowerment**
Shakti (primal life force) · Aphrodite (radiant self-love) · Eos (new beginnings)

**Week 6 — Integration**
Brigid (inner flame) · Hera (sacred connection) · Durga (fearless presence)

**Week 7 — Momentum**
Nike (victorious momentum) · Bellona (courage and drive) · Iris (bridge of light)

**Week 8 — Ascension**
Rhea (natural rhythm) · Aura (breath of clarity) · Nyx (night wisdom)

**Week 9 — Transformation**
Hebe (renewal and joy) · Hekate (threshold power) · Demeter (harvest and abundance)

**Week 10 — Completion**
Phoenix (rebirth and embodiment) · Maat (truth and harmony) · Sophia (divine wisdom)

Each session theme sits lightly. You do not need to know anything about these \
archetypes before you arrive. The movement, breath, and your own body will do the rest.\
"""

WEEK_THEMES = [
    "Foundations", "Emergence", "Radiance", "Expression", "Empowerment",
    "Integration", "Momentum", "Ascension", "Transformation", "Completion",
]

BOOKING_NOTE = (
    "Private address details are provided after enrolment. "
    "Bring a water bottle and wear comfortable clothes."
)

# Stable seed timestamp (does not affect runtime behaviour)
SEED_TS = datetime(2026, 6, 4, 10, 0, 0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def upsert(db, model, record_id: str, fields: dict, refresh_fields: list[str] = ()):
    """
    Find-or-create by primary key. When the record exists, refresh_fields are updated.
    Returns (obj, created: bool).
    """
    obj = db.query(model).filter_by(id=record_id).first()
    if obj:
        for f in refresh_fields:
            if f in fields:
                setattr(obj, f, fields[f])
        return obj, False
    obj = model(id=record_id, **fields)
    db.add(obj)
    return obj, True


def upsert_pathway(db, pathway_id: str, slug: str, fields: dict, refresh_fields: list[str] = ()):
    """Upsert by stable pathway ID, falling back to slug lookup if the ID is new."""
    obj = db.query(Pathway).filter_by(id=pathway_id).first()
    if not obj:
        obj = db.query(Pathway).filter_by(space_id=SPACE_ID, slug=slug).first()
    if obj:
        for f in refresh_fields:
            if f in fields:
                setattr(obj, f, fields[f])
        return obj, False
    obj = Pathway(id=pathway_id, space_id=SPACE_ID, slug=slug, **fields)
    db.add(obj)
    return obj, True


def next_weekday(weekday: int) -> datetime:
    """Next occurrence of weekday (0=Mon … 6=Sun) strictly after today (UTC)."""
    today = datetime.utcnow().date()
    days = (weekday - today.weekday()) % 7 or 7
    d = today + timedelta(days=days)
    return datetime(d.year, d.month, d.day)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:  # noqa: C901
    db = SessionLocal()
    try:
        # ── Part 1: Space identity ─────────────────────────────────────────
        print("\n── Part 1: Space identity ──")
        space = db.query(Space).filter_by(id=SPACE_ID).first()
        if not space:
            print("ERROR: EMBODY space not found. Aborting.")
            return

        space.name = "EMBODY"
        space.tagline = "Strength. Somatics. Sisterhood."
        space.description = (
            "## What is EMBODY?\n\n"
            "EMBODY is a 10-week in-person movement experience for women ready to reconnect with their body, breath, and internal power — based in South Croydon, Victoria.\n\n"
            "It is not a gym class or a performance space. EMBODY is a structured, somatic-informed container that blends functional strength, feminine archetypes, breath work, and nervous system recalibration into a single weekly practice.\n\n"
            "Each term runs for 10 weeks, with three sessions per week (Monday, Thursday, Saturday). You book whichever sessions suit your schedule.\n\n"
            "## Who it's for\n\n"
            "EMBODY is for women who:\n"
            "- Feel disconnected from their body or strength\n"
            "- Are done with punishing fitness culture and want something that actually feels good\n"
            "- Want structure without rigidity — a real container, not just classes\n"
            "- Are ready to move, feel, and be witnessed\n\n"
            "You do not need to be fit. You do not need experience. You need to be willing to show up.\n\n"
            "## Session structure\n\n"
            "Each 60-minute session moves through:\n"
            "- **Activation** — waking up the body, breath, and awareness\n"
            "- **Strength** — functional movement patterns, resistance, and power\n"
            "- **Decompression** — floor-based release, somatic discharge, regulation\n"
            "- **Integration** — breath, stillness, and a moment to land\n\n"
            "Each week has a theme aligned to the 10-week arc of the term.\n\n"
            "## Times and location\n\n"
            "**Monday** — 6:00pm – 7:00pm\n"
            "**Thursday** — 6:00pm – 7:00pm\n"
            "**Saturday** — 9:00am – 10:00am\n\n"
            "Location: South Croydon, Victoria (address shared upon booking confirmation)\n\n"
            "## Membership and access\n\n"
            "Joining EMBODY as a community member is free. Access to the EMBODY In-Person Sessions pathway — and the ability to book sessions — requires term enrollment.\n\n"
            "Term pricing is set each term. Payment secures your place in the cohort and grants access to all session bookings, community, resources, and pathway content for that term.\n\n"
            "## What to bring\n\n"
            "- Water bottle\n"
            "- Comfortable, layered clothing you can move in\n"
            "- A mat (provided if you don't have one)\n"
            "- An open mind and a willingness to feel\n\n"
            "## Meet your facilitator\n\n"
            "EMBODY is led by Lindsey — movement facilitator, somatic practitioner, and founder of Fresh Collective.\n\n"
            "Lindsey has spent years exploring the intersection of strength, nervous system safety, and feminine embodiment. EMBODY distils that into a weekly practice that is real, grounded, and built for actual women's lives."
        )
        space.show_member_directory = False
        space.themes = ["Movement", "Wellbeing", "Inner Work"]
        space.is_public = True
        space.status = "active"
        space.pricing_type = "free"
        space.has_paid_internal_content = True
        space.included_access_summary = (
            "Community, updates, resources, and public session information"
        )
        space.paid_content_summary = (
            "10-week EMBODY term access and in-person session bookings are paid separately"
        )
        space.guidance_start_title = "Welcome to EMBODY"
        space.guidance_start_body = (
            "Start by reading the session rhythm and what to bring. EMBODY is about moving "
            "in a way that feels supportive, not punishing. You are welcome exactly as you are."
        )
        space.guidance_focus_title = "Term focus"
        space.guidance_focus_body = (
            "Across the term, we move through strength, breath, feminine archetypes, nervous system "
            "safety, and integration. Each week has its own energy, but the deeper practice is always "
            "the same: come back to your body."
        )
        space.guidance_links_title = "Helpful links"
        space.guidance_links_body = (
            "Visit Resources for the timetable, what to bring, session notes, and practice materials. "
            "Use Gatherings to book your sessions."
        )
        print("  [updated] EMBODY space — identity, description, guidance panel")
        db.flush()

        # ── Part 2: Pathways ───────────────────────────────────────────────
        print("\n── Part 2: Pathways ──")

        # Pathway 1: EMBODY In-Person Sessions (paid, one_time)
        # TODO: plan-based booking limits (Awaken/Activate/Empower) not yet implemented.
        p_inperson, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["in-person"],
            slug="embody-in-person-sessions",
            fields={
                "title": "EMBODY In-Person Sessions",
                "description": (
                    "The core 10-week EMBODY experience. Join live in-person sessions that combine "
                    "movement activation, breath, strength, decompression, and nervous system recalibration.\n\n"
                    "Pricing begins at $200 per term (Awaken — 1 session/week). "
                    "Two-session ($340) and three-session ($420) weekly options are managed manually until "
                    "plan-based booking limits are available on the platform."
                ),
                "status": "active",
                "position": 1,
                "access_type": "one_time",
                "price_cents": 20000,
                "currency": "AUD",
                "is_sequential": True,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type", "price_cents"],
        )
        print(f"  [{'created' if created else 'updated'}] EMBODY In-Person Sessions")

        # Pathway 2: Home Practice (included)
        p_home, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["home"],
            slug="home-practice",
            fields={
                "title": "Home Practice",
                "description": (
                    "Simple practices you can use between sessions to reconnect with your body, "
                    "breath, and nervous system."
                ),
                "status": "active",
                "position": 2,
                "access_type": "included",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": False,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type"],
        )
        print(f"  [{'created' if created else 'updated'}] Home Practice")

        # Pathway 3: Nervous System Foundations (included, coming soon)
        p_nervous, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["nervous-sys"],
            slug="nervous-system-foundations",
            fields={
                "title": "Nervous System Foundations",
                "description": (
                    "A gentle introduction to nervous system safety, regulation, and the "
                    "body-led foundations behind EMBODY."
                ),
                "status": "coming_soon",
                "position": 3,
                "access_type": "included",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": True,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type"],
        )
        print(f"  [{'created' if created else 'updated'}] Nervous System Foundations (coming soon)")
        db.flush()

        # ── Part 3: Steps ──────────────────────────────────────────────────
        print("\n── Part 3: Steps ──")

        inperson_steps = [
            {
                "key": "ip-welcome",
                "title": "Welcome to EMBODY",
                "slug": "welcome-to-embody",
                "content_type": "text",
                "position": 1,
                "estimated_minutes": 3,
                "content_body": (
                    "Welcome. You are in the right place.\n\n"
                    "EMBODY is not a bootcamp. It is not about pushing through, performing, or earning your place. "
                    "It is a space to move in a way that feels good — for your body, your nervous system, and your sense of self.\n\n"
                    "Sessions run Monday evenings, Thursday evenings, and Saturday mornings in South Croydon, Victoria. "
                    "The full address is provided once you are enrolled.\n\n"
                    "You do not need to be fit, experienced, or ready. You just need to show up."
                ),
            },
            {
                "key": "ip-rhythm",
                "title": "Session rhythm",
                "slug": "session-rhythm",
                "content_type": "text",
                "position": 2,
                "estimated_minutes": 4,
                "content_body": (
                    "Every EMBODY session follows the same five-part rhythm. Once you know it, "
                    "your body starts to settle in before we even begin.\n\n"
                    "**Movement activation (10 min)**\n"
                    "We warm the body, wake up the joints, and bring you into the space. "
                    "This is not a performance — it is an arrival.\n\n"
                    "**Breath-led activation (10 min)**\n"
                    "Breath is the thread that runs through all of EMBODY. "
                    "We use it to settle the nervous system before we ask it to work.\n\n"
                    "**Functional strength (25 min)**\n"
                    "The main movement block. Grounded, intentional, and adapted to where you are on the day. "
                    "You are always invited to listen to your body.\n\n"
                    "**Decompression and integration (10 min)**\n"
                    "We slow down deliberately. The body needs time to absorb what it has done.\n\n"
                    "**Nervous system recalibration (5 min)**\n"
                    "A gentle close. Breath, stillness, and a moment to notice how you feel before you walk out the door."
                ),
            },
            {
                "key": "ip-bring",
                "title": "What to bring",
                "slug": "what-to-bring",
                "content_type": "text",
                "position": 3,
                "estimated_minutes": 2,
                "content_body": (
                    "Keep it simple.\n\n"
                    "- A water bottle\n"
                    "- Comfortable clothes you can move in\n"
                    "- Yourself, exactly as you are today\n\n"
                    "Yoga mats are available at the space. Bring your own if you prefer.\n\n"
                    "Arrive a few minutes early for your first session — it gives you time to settle in "
                    "and connect before we begin.\n\n"
                    "The space is in South Croydon, Victoria. "
                    "You will receive the full street address after enrolment."
                ),
            },
            {
                "key": "ip-journey",
                "title": "The 10-week journey",
                "slug": "the-10-week-journey",
                "content_type": "text",
                "position": 4,
                "estimated_minutes": 5,
                "content_body": ARCHETYPE_BODY,
            },
            {
                "key": "ip-integration",
                "title": "Integration between sessions",
                "slug": "integration-between-sessions",
                "content_type": "text",
                "position": 5,
                "estimated_minutes": 3,
                "content_body": (
                    "The work does not end when the session does.\n\n"
                    "Between sessions, your nervous system is integrating. "
                    "Your body is consolidating what it learned. The most useful thing you can do is notice.\n\n"
                    "**Take a moment after each session**\n"
                    "Even five minutes in your car, sitting quietly, noticing how your body feels. "
                    "This is not meditation. It is just attention.\n\n"
                    "**Use the Home Practice pathway**\n"
                    "Short practices for between sessions — breath, grounding, gentle mobility.\n\n"
                    "**Notice what shifts**\n"
                    "Sleep, energy, how you carry yourself, how you respond to stress. "
                    "These are the markers that matter in EMBODY.\n\n"
                    "You do not need to do more. You need to notice more."
                ),
            },
        ]

        for s in inperson_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_inperson.id,
                "slug": s["slug"],
                "title": s["title"],
                "content_type": s["content_type"],
                "content_body": s["content_body"],
                "estimated_minutes": s["estimated_minutes"],
                "is_required": True,
                "position": s["position"],
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "content_body", "estimated_minutes"])
            print(f"  [{'created' if created else 'updated'}] {s['title']}")

        home_steps = [
            {
                "key": "hp-reset",
                "title": "Five-minute reset",
                "slug": "five-minute-reset",
                "content_type": "text",
                "position": 1,
                "estimated_minutes": 5,
                "content_body": (
                    "A short grounding practice for between sessions.\n\n"
                    "Find a comfortable position — standing, sitting, or lying down.\n\n"
                    "1. Take three slow breaths. Let the exhale be a little longer than the inhale.\n"
                    "2. Soften your jaw. Soften your shoulders.\n"
                    "3. Feel the ground beneath you.\n"
                    "4. Ask your body: what do I need right now?\n"
                    "5. Stay for a few more breaths, without needing to answer.\n\n"
                    "That is enough. Return to your day."
                ),
            },
            {
                "key": "hp-breath",
                "title": "Breath and grounding",
                "slug": "breath-and-grounding",
                "content_type": "text",
                "position": 2,
                "estimated_minutes": 5,
                "content_body": (
                    "The breath is always available to you. Use it at your desk, in your car, before bed.\n\n"
                    "**Box breath**\n"
                    "Inhale for 4 counts · Hold for 4 · Exhale for 4 · Hold for 4. "
                    "Repeat three to five times.\n\n"
                    "**Grounding breath**\n"
                    "Inhale, and on the exhale, imagine roots growing from the base of your spine into the ground. "
                    "Repeat until you feel settled.\n\n"
                    "Use these when you feel scattered, activated, or simply disconnected from your body."
                ),
            },
            {
                "key": "hp-mobility",
                "title": "Gentle mobility flow",
                "slug": "gentle-mobility-flow",
                "content_type": "text",
                "position": 3,
                "estimated_minutes": 10,
                "content_body": (
                    "A 10-minute flow in your own space. No equipment needed. Move slowly — this is not a workout.\n\n"
                    "1. Neck rolls — 5 each direction, very slowly\n"
                    "2. Shoulder circles — 5 forward, 5 back\n"
                    "3. Chest opener — arms wide, breathe into the front of your body\n"
                    "4. Hip circles — 5 each direction\n"
                    "5. Side stretch — reach one arm overhead, bend gently each way\n"
                    "6. Forward fold — soft knees, let your upper body hang\n"
                    "7. Cat-cow — 5 slow rounds on hands and knees\n"
                    "8. Child's pose — stay as long as feels good\n\n"
                    "Notice how your body feels before and after."
                ),
            },
            {
                "key": "hp-strength",
                "title": "Strength without pressure",
                "slug": "strength-without-pressure",
                "content_type": "text",
                "position": 4,
                "estimated_minutes": 10,
                "content_body": (
                    "Strength is not about pushing harder. It is about meeting your body where it is.\n\n"
                    "A short, gentle sequence:\n\n"
                    "1. Glute bridges — 10 reps, slow and intentional\n"
                    "2. Wall push-ups — 10 reps, breathe through each one\n"
                    "3. Bodyweight squats — 10 reps, feet hip-width, soft landing\n"
                    "4. Dead bug hold — 5 breaths each side\n\n"
                    "Rest between exercises. You are not racing.\n\n"
                    "This sequence is here when your body wants to move and you are not sure what to do. "
                    "It is not compulsory."
                ),
            },
            {
                "key": "hp-reflect",
                "title": "Integration reflection",
                "slug": "integration-reflection",
                "content_type": "reflection",
                "position": 5,
                "estimated_minutes": 5,
                "content_body": (
                    "After each session, take a moment to reflect. "
                    "You can write here, in a journal, or simply notice quietly.\n\n"
                    "- What word describes how your body feels right now?\n"
                    "- What did you notice during today's session?\n"
                    "- Is there anything your body is asking for in the next few days?\n\n"
                    "There are no right answers. This practice is for you."
                ),
            },
        ]

        for s in home_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_home.id,
                "slug": s["slug"],
                "title": s["title"],
                "content_type": s["content_type"],
                "content_body": s["content_body"],
                "estimated_minutes": s["estimated_minutes"],
                "is_required": False,
                "position": s["position"],
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "content_body", "estimated_minutes"])
            print(f"  [{'created' if created else 'updated'}] {s['title']}")

        db.flush()

        # ── Part 4: Resources ──────────────────────────────────────────────
        print("\n── Part 4: Resources ──")

        general_resources = [
            {
                "id": RESOURCE_IDS["timetable"],
                "title": "Term timetable",
                "description": (
                    "Monday 6–7pm · Thursday 6–7pm · Saturday 9–10am. "
                    "Sessions run for 10 weeks. Location: South Croydon, Victoria "
                    "(private residence — address provided after enrolment)."
                ),
                "sort_order": 1,
            },
            {
                "id": RESOURCE_IDS["what-to-bring"],
                "title": "What to bring",
                "description": (
                    "Bring a water bottle, comfortable clothes, and yourself. "
                    "Yoga mats are available, but bring your own if you prefer."
                ),
                "sort_order": 2,
            },
            {
                "id": RESOURCE_IDS["ses-rhythm"],
                "title": "EMBODY session rhythm",
                "description": (
                    "Each 60-minute session: movement activation (10 min) · "
                    "breath-led activation (10 min) · functional strength (25 min) · "
                    "decompression and integration (10 min) · nervous system recalibration (5 min)."
                ),
                "sort_order": 3,
            },
            {
                "id": RESOURCE_IDS["makeup"],
                "title": "Make-up session guide",
                "description": (
                    "If you miss a session, you may attend another session during the 10-week term "
                    "where space allows. Contact your facilitator to arrange."
                ),
                "sort_order": 4,
            },
        ]

        for r in general_resources:
            obj, created = upsert(db, SpaceResource, r["id"], {
                "space_id": SPACE_ID,
                "created_by_id": CREATOR_ID,
                "title": r["title"],
                "description": r["description"],
                "resource_type": "guide",
                "scope": "general",
                "status": "published",
                "sort_order": r["sort_order"],
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "description"])
            print(f"  [{'created' if created else 'updated'}] (general) {r['title']}")

        pathway_resources = [
            # EMBODY In-Person Sessions
            {
                "id": RESOURCE_IDS["archetype-map"],
                "title": "Term archetype map",
                "description": "A simple guide to the 10-week EMBODY archetype journey and weekly session themes.",
                "pathway_id": p_inperson.id,
                "sort_order": 1,
            },
            {
                "id": RESOURCE_IDS["ses-notes"],
                "title": "Session notes",
                "description": "Notes and reminders for live in-person session participants.",
                "pathway_id": p_inperson.id,
                "sort_order": 2,
            },
            {
                "id": RESOURCE_IDS["reflect-sheet"],
                "title": "Integration reflection sheet",
                "description": "A short reflection to complete after each session.",
                "pathway_id": p_inperson.id,
                "sort_order": 3,
            },
            # Home Practice
            {
                "id": RESOURCE_IDS["hp-5min"],
                "title": "Five-minute reset",
                "description": "A short grounding practice for between sessions.",
                "pathway_id": p_home.id,
                "sort_order": 1,
            },
            {
                "id": RESOURCE_IDS["hp-mobility-g"],
                "title": "Gentle mobility guide",
                "description": "Simple movements to help you reconnect with your body without pressure.",
                "pathway_id": p_home.id,
                "sort_order": 2,
            },
        ]

        for r in pathway_resources:
            obj, created = upsert(db, SpaceResource, r["id"], {
                "space_id": SPACE_ID,
                "created_by_id": CREATOR_ID,
                "title": r["title"],
                "description": r["description"],
                "resource_type": "guide",
                "scope": "pathway",
                "pathway_id": r["pathway_id"],
                "status": "published",
                "sort_order": r["sort_order"],
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "description"])
            print(f"  [{'created' if created else 'updated'}] (pathway) {r['title']}")

        db.flush()

        # ── Part 5: Gatherings — 10-week term ─────────────────────────────
        print("\n── Part 5: Gatherings ──")
        print("  Existing series (preserved, not modified):")

        # Report existing series
        from sqlalchemy import func as sa_func
        existing = (
            db.query(Event.recurrence_series_id, sa_func.count(Event.id).label("n"))
            .filter(Event.space_id == SPACE_ID, Event.recurrence_series_id.isnot(None))
            .group_by(Event.recurrence_series_id)
            .all()
        )
        for sid, n in existing:
            if sid not in SERIES_IDS.values():
                sample = (
                    db.query(Event)
                    .filter(Event.recurrence_series_id == sid)
                    .order_by(Event.starts_at)
                    .first()
                )
                day = sample.starts_at.strftime("%A") if sample else "?"
                print(f"    series {sid[:8]}…  {n} events  first={sample.starts_at.date() if sample else '?'}  ({day})")

        # Create new series (idempotent: skip if series already seeded)
        def seed_series(series_key: str, title_prefix: str, weekday: int, hour: int, label: str):
            series_id = SERIES_IDS[series_key]
            existing_count = (
                db.query(Event).filter(Event.recurrence_series_id == series_id).count()
            )
            if existing_count >= 10:
                print(f"  [skipped] {label} — already seeded ({existing_count} events)")
                return
            if 0 < existing_count < 10:
                # Partial seed — delete incomplete set and recreate cleanly
                db.query(Event).filter(Event.recurrence_series_id == series_id).delete()
                db.flush()
                print(f"  [reset]   {label} — removed {existing_count} partial events")

            start = next_weekday(weekday)
            for i in range(10):
                week_start = start + timedelta(weeks=i)
                starts_at = week_start.replace(hour=hour, minute=0, second=0)
                ends_at   = week_start.replace(hour=hour + 1, minute=0, second=0)
                theme = WEEK_THEMES[i]
                eid = event_id(series_key, i + 1)
                e = Event(
                    id=eid,
                    space_id=SPACE_ID,
                    created_by_id=CREATOR_ID,
                    title=f"{title_prefix} — {theme}",
                    description=(
                        f"Week {i + 1}: {theme}. A 60-minute EMBODY in-person session — "
                        "movement activation, breath, strength, decompression, and "
                        "nervous system recalibration."
                    ),
                    starts_at=starts_at,
                    ends_at=ends_at,
                    location_type="in_person",
                    is_published=True,
                    is_public=True,
                    requires_booking=True,
                    capacity=7,
                    booking_note=BOOKING_NOTE,
                    booking_access_type="pathway_required",
                    booking_required_pathway_id=PATHWAY_IDS["in-person"],
                    recurrence_series_id=series_id,
                    recurrence_label=f"{label} — 10-week term",
                    recurrence_index=i + 1,
                    recurrence_total=10,
                    status="active",
                    created_at=SEED_TS,
                    updated_at=SEED_TS,
                )
                db.add(e)
            first_date = (start).strftime("%d %b %Y")
            print(f"  [created] {label} — 10 events from {first_date}")

        seed_series("sat", "Saturday EMBODY Session", weekday=5, hour=9,  label="Saturday EMBODY sessions")
        seed_series("mon", "Monday EMBODY Session",   weekday=0, hour=18, label="Monday EMBODY sessions")
        seed_series("thu", "Thursday EMBODY Session", weekday=3, hour=18, label="Thursday EMBODY sessions")

        db.flush()

        # ── Part 6: Community posts ────────────────────────────────────────
        print("\n── Part 6: Community posts ──")

        posts = [
            {
                "id": POST_IDS[0],
                "title": "Welcome to EMBODY",
                "body": (
                    "Welcome to EMBODY. This is a space for strength, somatics, sisterhood, and "
                    "nervous system safety. Use this community to ask questions, share reflections, "
                    "and stay connected between sessions."
                ),
                "post_type": "announcement",
                "is_pinned": True,
            },
            {
                "id": POST_IDS[1],
                "title": "Introduce yourself",
                "body": (
                    "Share your name, what brought you to EMBODY, and one thing your body is "
                    "asking for this term."
                ),
                "post_type": "prompt",
                "is_pinned": True,
            },
            {
                "id": POST_IDS[2],
                "title": "After-session reflections",
                "body": (
                    "After each session, you are invited to share one word, one feeling, or one "
                    "small noticing from your body."
                ),
                "post_type": "prompt",
                "is_pinned": False,
            },
        ]

        for p in posts:
            obj, created = upsert(db, CommunityPost, p["id"], {
                "space_id": SPACE_ID,
                "author_id": CREATOR_ID,
                "title": p["title"],
                "body": p["body"],
                "post_type": p["post_type"],
                "is_pinned": p["is_pinned"],
                "is_visible": True,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "body", "is_pinned"])
            print(f"  [{'created' if created else 'updated'}] {p['title']}")

        # ── Commit ─────────────────────────────────────────────────────────
        db.commit()

        print("\n✓  EMBODY content seeded successfully.\n")
        print("── TODOs (future platform improvements) ──────────────────────")
        print("  1. Plan-based booking limits:")
        print("       Awaken  → 1 session/week ($200/term)")
        print("       Activate → 2 sessions/week ($340/term)")
        print("       Empower  → 3 sessions/week ($420/term)")
        print("  2. Paid term checkout: Stripe support for EMBODY term + plan selection.")
        print("  3. Make-up session logic: book a make-up where capacity allows.")
        print("  4. Online EMBODY: potential future pathway for recorded/live online sessions.")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
