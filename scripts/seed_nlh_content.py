#!/usr/bin/env python3
"""
Content seed script: The Grove collective for Fresh Collective (dev/local).

Creates or updates:
  - The Grove space identity, description, about page, guidance panel, access model
  - 7 pathways (3 new + 4 repurposed) with placeholder steps
  - General and pathway-specific resources
  - Community starter posts

Idempotent — safe to run multiple times. Existing enrollments, step progress,
member records, payment records, bookings, and all EMBODY data are never touched.

Usage:
    cd /home/lindsey/fc-production/backend
    .venv/bin/python ../scripts/seed_nlh_content.py

Pathway mapping (existing → new):
  - Essence        (c81e4617) → Human Design Foundations
  - Growth         (e99be637) → Trust Yourself
  - Transformation (e835d32d) → Embodied Leadership Practices
  - REAL Journey   (b0bd060b) → The R.E.A.L. Journey (updated, steps preserved)

TODOs (future platform work — do not build yet):
  1. Pathway bundles: sell multiple pathways together
     (e.g. R.E.A.L. Journey + Human Design Foundations + Trust Yourself).
  2. Paid-member shared resources: bonus resources available to any paid pathway
     member, not tied to one specific pathway.
  3. Interactive quiz builder: Self-Awareness Quiz with branching logic and results.
  4. Creator colour themes: curated palette presets per collective
     (NLH: navy / gold / soft aqua; EMBODY: teal / aqua / gold).
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Both model modules must be imported so SQLAlchemy relationship registry resolves correctly
import app.models.user      # noqa: F401
import app.models.platform  # noqa: F401

from app.core.database import SessionLocal
from app.models.platform import (
    CommunityPost, Pathway, PathwayStep, Space, SpaceResource,
)

# ── Stable identifiers ────────────────────────────────────────────────────────

SPACE_ID = "80862f54-d95f-4b3b-83ab-cf926014441d"

PATHWAY_IDS = {
    # New pathways
    "start-here":          "pa000001-nlhb-4000-8000-000000000001",
    "tools-templates":     "pa000001-nlhb-4000-8000-000000000006",
    "live-replays":        "pa000001-nlhb-4000-8000-000000000007",
    # Existing pathway IDs repurposed (originally seeded in migration 003)
    "real-journey":        "b0bd060b-1c83-41ef-8055-1870b258b75a",  # was REAL Journey
    "human-design":        "c81e4617-c625-484c-adcc-23c195ab7059",  # was Essence
    "trust-yourself":      "e99be637-12d2-4e8a-b4b3-89028d6a8ace",  # was Growth
    "embodied-leadership": "e835d32d-78c7-4a49-a16b-535aa56b8b41",  # was Transformation
}

STEP_IDS = {
    # Start Here
    "sh-welcome":          "st000001-nlhb-4000-8000-000000000001",
    "sh-journey":          "st000001-nlhb-4000-8000-000000000002",
    "sh-getmost":          "st000001-nlhb-4000-8000-000000000003",
    # R.E.A.L. Journey — only step 7 (steps 1–6 already seeded in migration 004)
    "rj-reflection":       "st000001-nlhb-4000-8000-000000000010",
    # Human Design Foundations
    "hd-what":             "st000001-nlhb-4000-8000-000000000021",
    "hd-overview":         "st000001-nlhb-4000-8000-000000000022",
    "hd-type":             "st000001-nlhb-4000-8000-000000000023",
    "hd-authority":        "st000001-nlhb-4000-8000-000000000024",
    "hd-profile":          "st000001-nlhb-4000-8000-000000000025",
    "hd-centres":          "st000001-nlhb-4000-8000-000000000026",
    "hd-chart":            "st000001-nlhb-4000-8000-000000000027",
    # Trust Yourself
    "ty-why":              "st000001-nlhb-4000-8000-000000000031",
    "ty-authority":        "st000001-nlhb-4000-8000-000000000032",
    "ty-body":             "st000001-nlhb-4000-8000-000000000033",
    "ty-pressure":         "st000001-nlhb-4000-8000-000000000034",
    "ty-practise":         "st000001-nlhb-4000-8000-000000000035",
    "ty-reflection":       "st000001-nlhb-4000-8000-000000000036",
    # Embodied Leadership Practices
    "el-meditations":      "st000001-nlhb-4000-8000-000000000041",
    "el-catch-choose":     "st000001-nlhb-4000-8000-000000000042",
    "el-coming-home":      "st000001-nlhb-4000-8000-000000000043",
    "el-checkin":          "st000001-nlhb-4000-8000-000000000044",
    "el-daily":            "st000001-nlhb-4000-8000-000000000045",
    # Tools & Templates
    "tt-quiz":             "st000001-nlhb-4000-8000-000000000051",
    "tt-chart":            "st000001-nlhb-4000-8000-000000000052",
    "tt-type":             "st000001-nlhb-4000-8000-000000000053",
    "tt-authority":        "st000001-nlhb-4000-8000-000000000054",
    "tt-reconditioning":   "st000001-nlhb-4000-8000-000000000055",
    "tt-90day":            "st000001-nlhb-4000-8000-000000000056",
    "tt-reset":            "st000001-nlhb-4000-8000-000000000057",
    "tt-fieldguide":       "st000001-nlhb-4000-8000-000000000058",
    # Live Replays
    "lr-how":              "st000001-nlhb-4000-8000-000000000061",
    "lr-circle":           "st000001-nlhb-4000-8000-000000000062",
    "lr-call":             "st000001-nlhb-4000-8000-000000000063",
}

RESOURCE_IDS = {
    # General — visible to all collective members
    "welcome-guide":          "rs000001-nlhb-4000-8000-000000000001",
    "how-to-use":             "rs000001-nlhb-4000-8000-000000000002",
    "community-guidelines":   "rs000001-nlhb-4000-8000-000000000003",
    # Paid — scoped to R.E.A.L. Journey pathway only (not free)
    "gift-ebook":             "rs000001-nlhb-4000-8000-000000000011",
    # Tools & Templates pathway resources
    "quiz-placeholder":       "rs000001-nlhb-4000-8000-000000000021",
    "hd-chart-download":      "rs000001-nlhb-4000-8000-000000000022",
    "type-cheat-sheets":      "rs000001-nlhb-4000-8000-000000000023",
    "authority-cheat-sheets": "rs000001-nlhb-4000-8000-000000000024",
    "reconditioning-map":     "rs000001-nlhb-4000-8000-000000000025",
    "90day-plan":             "rs000001-nlhb-4000-8000-000000000026",
    "alignment-reset":        "rs000001-nlhb-4000-8000-000000000027",
    "field-guide":            "rs000001-nlhb-4000-8000-000000000028",
}

POST_IDS = {
    # Existing welcome post from migration 006 — title/body refreshed for NLH
    "welcome":    "po000001-0000-4000-8000-000000000001",
    # New NLH community posts
    "introduce":  "po000001-nlhb-4000-8000-000000000001",
    "edge":       "po000001-nlhb-4000-8000-000000000002",
    "action":     "po000001-nlhb-4000-8000-000000000003",
}

SEED_TS = datetime(2026, 6, 6, 10, 0, 0)

# ── About page content ────────────────────────────────────────────────────────

ABOUT_CONTENT = """\
## 🌿 What is The Grove?

The Grove is a learning and community space for women who are ready to lead \
with more self-trust, authenticity, and alignment — not by doing more, but by coming \
back to who they already are.

This is not a rigid monthly membership or a content-heavy course library. It is a \
growing collection of guided pathways, reflective practices, Human Design tools, and \
a community of women doing the same quiet, real work.

The Hub is built around one central idea: that the most effective leadership is \
natural leadership — the kind that comes from alignment rather than performance.

---

## ✨ Who it's for

The Grove is for women who:

* Feel like they are constantly over-functioning, over-giving, or running on empty
* Know they are capable but keep second-guessing themselves
* Want to lead — in their work, their relationships, their own lives — without performing
* Are curious about Human Design as a practical self-awareness tool
* Are ready to move from efforting and forcing to something that actually feels like them

You don't need to have your life figured out. You just need to be willing to pay attention.

---

## 🧭 The R.E.A.L. Framework

Everything in the Hub connects back to the R.E.A.L. Framework — a simple, repeatable \
process for noticing what is happening, understanding it more honestly, and experimenting \
with something different.

**R — Recognise** what is actually happening, beneath the surface\
**E — Explore** where the pattern comes from and what it has been protecting\
**A — Align** with what feels more true — not perfect, just truer\
**L — Lead** your leadership in a real, small, experimental way

You will move through this framework in different seasons, with different questions. \
Each cycle adds a layer. Each time, the shift becomes a little less effortful.

---

## 🌙 Human Design and self-trust

Human Design is a self-awareness tool that maps how your energy works — how you \
make decisions, where you are naturally strong, and where you are most likely to \
absorb pressure or conditioning from others.

Inside the Hub, Human Design is used as a practical lens for the R.E.A.L. Framework \
— not as a fixed identity or a label, but as a way to understand your own patterns \
more clearly.

There is a foundational Human Design pathway, a library of type and authority guides, \
and tools to help you apply your chart to everyday leadership decisions.

---

## 🔥 What you'll find inside

**Free for all members:**
* Community — prompts, reflections, and connection with other women in the Hub
* Start Here — an orientation pathway to help you find your footing
* Selected introductory resources and guides

**Paid pathways (available separately):**
* **The R.E.A.L. Journey** — the core guided pathway through the framework
* **Human Design Foundations** — a practical HD library for self-awareness and alignment
* **Trust Yourself** — decision-making, inner authority, and nervous system safety
* **Embodied Leadership Practices** — a practice library for integration through body and rhythm
* **Tools & Templates** — worksheets, templates, and planning tools
* **Live Replays** — recordings of live calls and integration sessions

More pathways are being added over time. The Hub grows with you.

---

## 💛 Membership and access

Joining The Grove is free. You get immediate access to the community, \
introductory content, and selected free resources.

Paid pathways can be added at any time, separately or together. You choose the \
depth and pace that fits your season.

This is not a subscription with a monthly theme or a new module every week. \
It is a library you return to — in your own time, with your own questions.

---

## 🦋 A note from Lindsey

I built The Grove because I spent years performing a version of \
leadership that was exhausting me. It looked fine from the outside. It felt hollow \
on the inside.

The work that actually changed things was quieter. It was learning to notice my \
patterns without shame. To trust my own authority. To stop over-functioning for \
people and situations that weren't asking for it.

That is what this space is for. Not a complete overhaul. Not a dramatic transformation. \
Just the slow, patient, real work of becoming more yourself.

You are welcome here, exactly as you are.

— Lindsey\
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def upsert(db, model, record_id: str, fields: dict, refresh_fields: list = ()):
    """Find-or-create by primary key. refresh_fields are updated if record exists."""
    obj = db.query(model).filter_by(id=record_id).first()
    if obj:
        for f in refresh_fields:
            if f in fields:
                setattr(obj, f, fields[f])
        return obj, False
    obj = model(id=record_id, **fields)
    db.add(obj)
    return obj, True


def upsert_pathway(db, pathway_id: str, slug: str, fields: dict, refresh_fields: list = ()):
    """Find by ID, falling back to slug. Updates slug if record was found by ID with old slug."""
    obj = db.query(Pathway).filter_by(id=pathway_id).first()
    if not obj:
        obj = db.query(Pathway).filter_by(space_id=SPACE_ID, slug=slug).first()
    if obj:
        for f in refresh_fields:
            if f in fields:
                setattr(obj, f, fields[f])
        if obj.slug != slug:
            obj.slug = slug
        return obj, False
    obj = Pathway(id=pathway_id, space_id=SPACE_ID, slug=slug, **fields)
    db.add(obj)
    return obj, True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():  # noqa: C901
    db = SessionLocal()
    try:
        # Resolve admin user ID at runtime
        from app.models.user import User
        admin = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        if not admin:
            print("ERROR: No admin user found. Aborting.")
            return
        CREATOR_ID = admin.id
        print(f"Admin user: {admin.email} ({CREATOR_ID})")

        # ── Part 1: Space identity ─────────────────────────────────────────
        print("\n── Part 1: Space identity ──")
        space = db.query(Space).filter_by(id=SPACE_ID).first()
        if not space:
            print("ERROR: The Grove space not found. Aborting.")
            return

        space.name = "The Grove"
        space.tagline = "A collective for women choosing a more aligned way to live, lead and grow."
        space.description = (
            "The Grove is a women's collective inside Fresh Collective for those ready to live, "
            "lead and grow in a more aligned way. Through guided pathways, live experiences, "
            "reflection and community, The Grove supports women to reconnect with themselves, "
            "trust their natural rhythm, and create a life that feels more honest, grounded and true."
        )
        space.about_content = ABOUT_CONTENT
        space.is_public = True
        space.status = "active"
        space.pricing_type = "free"
        space.pricing_amount_cents = None
        space.has_paid_internal_content = True
        space.included_access_summary = (
            "Community, free resources, pathway previews, and introductory content"
        )
        space.paid_content_summary = (
            "Deeper guided pathways, Human Design library, integration practices, and bonus resources"
        )
        space.themes = ["Leadership", "Inner Work", "Wellbeing", "Reflection", "Spirituality"]
        space.show_member_directory = False
        space.guidance_start_title = "Start here"
        space.guidance_start_body = (
            "Begin with the Start Here pathway — it will orient you to the Hub, explain how "
            "the R.E.A.L. Framework works, and help you choose where to go next."
        )
        space.guidance_focus_title = "The R.E.A.L. Framework"
        space.guidance_focus_body = (
            "Recognise · Explore · Align · Lead. This four-phase framework is the through-line "
            "of everything in the Hub. You will return to it in different seasons and with "
            "different questions."
        )
        space.guidance_links_title = "Find your way around"
        space.guidance_links_body = (
            "Visit Pathways for guided journeys. Visit Resources for tools, templates, and guides. "
            "Visit Community to connect, reflect, and share what is alive for you."
        )
        print("  [updated] The Grove — name, tagline, about, guidance panel, access model")
        db.flush()

        # ── Part 2: Pathways ───────────────────────────────────────────────
        print("\n── Part 2: Pathways ──")

        # Pathway 1: Start Here (free/included, active)
        p_start, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["start-here"],
            slug="start-here",
            fields={
                "title": "Start Here",
                "description": (
                    "New to The Grove? Start here. This short orientation "
                    "pathway introduces how the Hub works, how to use the R.E.A.L. Framework, "
                    "and how to choose where to begin."
                ),
                "status": "active",
                "position": 1,
                "access_type": "included",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": True,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] Start Here")

        # Pathway 2: The R.E.A.L. Journey (paid one_time, active — steps 1–6 already exist)
        # price_cents left null: no final price set yet (TODO: set when Stripe checkout is ready)
        p_real, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["real-journey"],
            slug="real-journey",
            fields={
                "title": "The R.E.A.L. Journey",
                "description": (
                    "The core pathway of The Grove. A guided journey to help you "
                    "recognise old patterns, explore what is really happening, align with your "
                    "natural design, and live your leadership in practical, everyday ways.\n\n"
                    "Moves through four phases: Recognise · Explore · Align · Lead."
                ),
                "status": "active",
                "position": 2,
                "access_type": "one_time",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": True,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "access_type", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] The R.E.A.L. Journey")

        # Pathway 3: Human Design Foundations (paid, coming_soon — repurposed from Essence)
        p_hd, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["human-design"],
            slug="human-design-foundations",
            fields={
                "title": "Human Design Foundations",
                "description": (
                    "A practical Human Design library to support the Explore and Align phases "
                    "of the R.E.A.L. Framework. Covers Type, Strategy, Authority, Profile, "
                    "Centres, and how to use your chart without overthinking it."
                ),
                "status": "coming_soon",
                "position": 3,
                "access_type": "one_time",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": False,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] Human Design Foundations (coming soon)")

        # Pathway 4: Trust Yourself (paid, coming_soon — repurposed from Growth)
        p_trust, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["trust-yourself"],
            slug="trust-yourself",
            fields={
                "title": "Trust Yourself",
                "description": (
                    "A pathway about decision-making, inner authority, nervous system safety, "
                    "and self-trust. For the moments when you know what is right but can't "
                    "seem to choose it."
                ),
                "status": "coming_soon",
                "position": 4,
                "access_type": "one_time",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": True,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] Trust Yourself (coming soon)")

        # Pathway 5: Embodied Leadership Practices (paid, coming_soon — repurposed from Transformation)
        p_embodied, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["embodied-leadership"],
            slug="embodied-leadership-practices",
            fields={
                "title": "Embodied Leadership Practices",
                "description": (
                    "A practice library for integrating leadership through the body, energy, "
                    "and daily rhythm. Meditations, somatic practices, and simple daily tools "
                    "for women who want to lead from the inside out."
                ),
                "status": "coming_soon",
                "position": 5,
                "access_type": "one_time",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": False,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] Embodied Leadership Practices (coming soon)")

        # Pathway 6: Tools & Templates (free/included, active)
        p_tools, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["tools-templates"],
            slug="tools-templates",
            fields={
                "title": "Tools & Templates",
                "description": (
                    "A library of practical tools, worksheets, and templates to support your "
                    "R.E.A.L. Journey and Human Design exploration. Some tools are free; "
                    "deeper resources are available with paid pathways."
                ),
                "status": "active",
                "position": 6,
                "access_type": "included",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": False,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] Tools & Templates")

        # Pathway 7: Live Replays (paid, coming_soon)
        p_replays, created = upsert_pathway(
            db,
            pathway_id=PATHWAY_IDS["live-replays"],
            slug="live-replays",
            fields={
                "title": "Live Replays",
                "description": (
                    "Recordings of live calls, integration circles, and community sessions. "
                    "Watch in your own time and catch up on what you missed."
                ),
                "status": "coming_soon",
                "position": 7,
                "access_type": "one_time",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": False,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "access_type", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] Live Replays (coming soon)")
        db.flush()

        # ── Part 3: Steps ──────────────────────────────────────────────────
        print("\n── Part 3: Steps ──")

        # --- Start Here (3 steps) ---
        start_steps = [
            {
                "key": "sh-welcome",
                "title": "👋 Welcome from Lindsey",
                "slug": "welcome-from-lindsey",
                "content_type": "text",
                "position": 1,
                "estimated_minutes": 3,
                "is_required": True,
                "content_body": (
                    "Welcome to The Grove.\n\n"
                    "If you are here, something in you is ready — ready to lead in a way that "
                    "feels more like you, and less like the version you have been performing.\n\n"
                    "This is a space for that work.\n\n"
                    "It is not about doing more. It is about coming back to what is already true "
                    "— about your energy, your patterns, your natural way of being in the world.\n\n"
                    "This short orientation will introduce you to the Hub, explain how the pathways "
                    "work, and help you choose where to begin.\n\n"
                    "*[Placeholder — a welcome video or audio from Lindsey will be added here.]*"
                ),
            },
            {
                "key": "sh-journey",
                "title": "🧭 Your Journey Starts Here",
                "slug": "your-journey-starts-here",
                "content_type": "text",
                "position": 2,
                "estimated_minutes": 5,
                "is_required": True,
                "content_body": (
                    "The Grove is organised into guided **pathways** — each one focused "
                    "on a different aspect of aligned, natural leadership.\n\n"
                    "**How pathways work:**\n"
                    "Each pathway is a sequence of steps — reading, reflection, practice, or video. "
                    "You move through them at your own pace. Some pathways are free to start; "
                    "others are paid and can be added whenever you are ready.\n\n"
                    "**The through-line: The R.E.A.L. Framework**\n"
                    "Everything in the Hub connects back to four phases:\n\n"
                    "* **R — Recognise** the pattern\n"
                    "* **E — Explore** what is underneath it\n"
                    "* **A — Align** with something truer\n"
                    "* **L — Lead** your leadership in a real, everyday way\n\n"
                    "You will find this framework woven through every pathway.\n\n"
                    "**Where to begin:**\n"
                    "If you are new, start with **The R.E.A.L. Journey** — it is the core pathway and "
                    "the best foundation for everything else.\n\n"
                    "If you are curious about Human Design, go to **Human Design Foundations**.\n\n"
                    "If you prefer to explore tools first, visit **Tools & Templates**.\n\n"
                    "*[Placeholder — a short explainer on navigating the Hub will be added here.]*"
                ),
            },
            {
                "key": "sh-getmost",
                "title": "💛 How to Get the Most Out of This Space",
                "slug": "how-to-get-the-most-out",
                "content_type": "text",
                "position": 3,
                "estimated_minutes": 4,
                "is_required": True,
                "content_body": (
                    "A few principles that will make this space more useful.\n\n"
                    "**Go slowly.**\n"
                    "This is not a course to complete. It is a practice to return to. "
                    "Reading quickly and doing slowly will always work better than rushing through.\n\n"
                    "**Use the community.**\n"
                    "The posts, prompts, and discussions in the community tab are part of the practice. "
                    "Sharing what you are noticing — even a small thing — often makes it more real.\n\n"
                    "**Trust your pace.**\n"
                    "There is no timeline here. Some people move through a pathway in a week. "
                    "Others return to the same step over months. Both are fine.\n\n"
                    "**Experiment, don't perform.**\n"
                    "The practices and reflections in this Hub are experiments. "
                    "They are not tests. You cannot get them wrong.\n\n"
                    "**Come back.**\n"
                    "The most valuable thing about the R.E.A.L. Framework is that you can return "
                    "to it in different seasons. Something that felt stuck last year may feel "
                    "different now. Come back with new questions.\n\n"
                    "*[Placeholder — a short note from Lindsey on pacing and community will be added here.]*"
                ),
            },
        ]

        for s in start_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_start.id,
                "slug": s["slug"],
                "title": s["title"],
                "content_type": s["content_type"],
                "content_body": s["content_body"],
                "estimated_minutes": s["estimated_minutes"],
                "is_required": s["is_required"],
                "position": s["position"],
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "content_body", "estimated_minutes"])
            print(f"  [{'created' if created else 'updated'}] (Start Here) {s['title']}")

        # --- R.E.A.L. Journey: step 7 only (steps 1–6 seeded in migration 004) ---
        obj, created = upsert(db, PathwayStep, STEP_IDS["rj-reflection"], {
            "pathway_id": p_real.id,
            "slug": "reflection-what-changed",
            "title": "Reflection: What Changed?",
            "content_type": "reflection",
            "estimated_minutes": 10,
            "is_required": False,
            "position": 7,
            "content_body": (
                "You have completed a cycle of the R.E.A.L. Journey.\n\n"
                "Before you move on, take a moment to close this loop deliberately.\n\n"
                "**Reflection prompts:**\n\n"
                "* What did you notice in yourself that you hadn't seen clearly before?\n"
                "* What shifted — even slightly — in how you see this pattern?\n"
                "* What feels different now compared to when you began?\n"
                "* What do you want to carry forward into the next cycle?\n\n"
                "Write here, in a journal, or simply sit with it quietly. "
                "There is no right answer. What matters is that you pause long enough to notice.\n\n"
                "*[Placeholder — a closing reflection video or audio from Lindsey will be added here.]*"
            ),
            "created_at": SEED_TS,
            "updated_at": SEED_TS,
        }, refresh_fields=["title", "content_body", "estimated_minutes"])
        print(f"  [{'created' if created else 'updated'}] (R.E.A.L. Journey) Reflection: What Changed?")

        # --- Human Design Foundations (7 steps) ---
        hd_steps = [
            {
                "key": "hd-what",
                "title": "🌞 What is Human Design?",
                "slug": "what-is-human-design",
                "content_type": "text",
                "position": 1,
                "estimated_minutes": 8,
                "content_body": (
                    "Human Design is a self-knowledge system that combines elements of the I Ching, "
                    "astrology, Kabbalah, the Chakra system, and quantum physics into a map of how "
                    "your energy works.\n\n"
                    "It produces a **BodyGraph** — a chart unique to your birth date, time, and place "
                    "— that shows your energy Type, how you are designed to make decisions (Authority), "
                    "your natural role (Profile), and which energy centres are consistent or open in you.\n\n"
                    "Inside the Hub, we use Human Design as a practical lens rather than a fixed identity. "
                    "It is one more way to understand your patterns — to see where you might be "
                    "absorbing pressure from others, where your natural strengths live, and how to "
                    "make decisions that feel genuinely aligned.\n\n"
                    "*[Placeholder — introductory Human Design content will be added here.]*"
                ),
            },
            {
                "key": "hd-overview",
                "title": "Self-Awareness Overview",
                "slug": "self-awareness-overview",
                "content_type": "text",
                "position": 2,
                "estimated_minutes": 6,
                "content_body": (
                    "Before we go into the specifics of your chart, it helps to understand "
                    "the overall purpose of Human Design in the context of the R.E.A.L. Framework.\n\n"
                    "Human Design is most useful in the **Explore** and **Align** phases. "
                    "It gives language to patterns you may already sense but struggle to articulate. "
                    "It helps you understand why certain strategies consistently drain you, and why "
                    "others feel effortless.\n\n"
                    "This pathway is not about memorising your chart. It is about using it as a "
                    "practical reference for your own experience.\n\n"
                    "*[Placeholder — self-awareness overview content will be added here.]*"
                ),
            },
            {
                "key": "hd-type",
                "title": "Type, Strategy and Alignment Themes",
                "slug": "type-strategy-alignment",
                "content_type": "text",
                "position": 3,
                "estimated_minutes": 10,
                "content_body": (
                    "There are five Human Design Types: Manifestor, Generator, Manifesting Generator, "
                    "Projector, and Reflector. Each has its own natural Strategy — the way it "
                    "interacts with life most effectively — and a signature feeling that indicates alignment.\n\n"
                    "Understanding your Type is a starting point, not a ceiling. The goal is not "
                    "to perform your Type but to notice where its themes show up in your actual life.\n\n"
                    "*[Placeholder — Type overview content for all 5 Types will be added here. "
                    "Individual Type deep-dives may be added as separate steps or resources.]*"
                ),
            },
            {
                "key": "hd-authority",
                "title": "Authority and Aligned Decisions",
                "slug": "authority-aligned-decisions",
                "content_type": "text",
                "position": 4,
                "estimated_minutes": 10,
                "content_body": (
                    "Your Authority is how you are designed to make decisions that feel genuinely "
                    "aligned — not just logically sound.\n\n"
                    "There are several Authorities: Sacral, Emotional/Solar Plexus, Splenic, "
                    "Ego/Heart, Self-Projected, Mental Projector, and Lunar (Reflector). "
                    "Each has a different timing and body-based signal.\n\n"
                    "Understanding your Authority is one of the most practical applications of "
                    "Human Design. It shifts decision-making from pressure and urgency into "
                    "something more trustworthy.\n\n"
                    "*[Placeholder — Authority overview content will be added here.]*"
                ),
            },
            {
                "key": "hd-profile",
                "title": "Profile and Natural Leadership Style",
                "slug": "profile-leadership-style",
                "content_type": "text",
                "position": 5,
                "estimated_minutes": 8,
                "content_body": (
                    "Your Profile is a two-number combination (e.g. 2/4, 3/5, 6/2) that describes "
                    "your natural role in life and how you interact with others.\n\n"
                    "Profiles often map closely to leadership style — how you naturally teach, "
                    "connect, influence, or set boundaries. Understanding your Profile can "
                    "clarify why certain leadership roles feel easy and others feel like a costume.\n\n"
                    "*[Placeholder — Profile overview content will be added here.]*"
                ),
            },
            {
                "key": "hd-centres",
                "title": "Defined and Undefined Centres",
                "slug": "defined-undefined-centres",
                "content_type": "text",
                "position": 6,
                "estimated_minutes": 10,
                "content_body": (
                    "Your BodyGraph has nine energy Centres — similar to chakras. "
                    "A **defined** Centre (coloured) is consistent and reliable in you. "
                    "An **undefined** Centre (white) is open — you take in and amplify energy "
                    "from others there, which can be a gift or a source of conditioning.\n\n"
                    "Understanding your undefined Centres is often where the most significant "
                    "pattern work happens. They are the places where you are most likely to "
                    "absorb expectations, pressure, or other people's urgency as your own.\n\n"
                    "*[Placeholder — Centres overview content will be added here.]*"
                ),
            },
            {
                "key": "hd-chart",
                "title": "How to Use Your Chart Without Overthinking It",
                "slug": "use-your-chart-without-overthinking",
                "content_type": "text",
                "position": 7,
                "estimated_minutes": 6,
                "content_body": (
                    "The most common trap with Human Design is over-intellectualising it.\n\n"
                    "You do not need to memorise every gate and channel. You do not need a "
                    "specialist to read your chart before you can use it. Start with three things:\n\n"
                    "1. **Know your Type and Strategy** — and notice where you override it\n"
                    "2. **Know your Authority** — and practise using it for one decision at a time\n"
                    "3. **Notice your undefined Centres** — and ask: is this pressure mine, "
                    "or am I amplifying someone else's?\n\n"
                    "That is enough to begin. The chart will deepen as you live it.\n\n"
                    "*[Placeholder — a practical 'first steps with your chart' guide will be added here.]*"
                ),
            },
        ]

        for s in hd_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_hd.id,
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
            print(f"  [{'created' if created else 'updated'}] (Human Design) {s['title']}")

        # --- Trust Yourself (6 steps) ---
        trust_steps = [
            {
                "key": "ty-why",
                "title": "Why Self-Trust Matters in Leadership",
                "slug": "why-self-trust-matters",
                "content_type": "text",
                "position": 1,
                "estimated_minutes": 6,
                "content_body": (
                    "Self-trust is not a personality trait. It is a practice.\n\n"
                    "Most women who struggle with self-trust are not lacking confidence in a "
                    "general sense. They are often highly capable and deeply perceptive. "
                    "What they struggle with is trusting their own inner signal — especially "
                    "when it conflicts with what others expect, or what seems logical, or what "
                    "has always been done before.\n\n"
                    "This pathway is about rebuilding that trust — not through affirmations or "
                    "willpower, but through understanding how your decision-making actually works "
                    "and practising using it.\n\n"
                    "*[Placeholder — introductory content will be added here.]*"
                ),
            },
            {
                "key": "ty-authority",
                "title": "Your Authority as a Decision-Making Compass",
                "slug": "authority-decision-making-compass",
                "content_type": "text",
                "position": 2,
                "estimated_minutes": 8,
                "content_body": (
                    "In Human Design, your Authority is the inner compass you are designed to "
                    "follow when making decisions. It is body-based, not mind-based.\n\n"
                    "This step explores how to identify your Authority and what it actually "
                    "feels like to use it — rather than overriding it with logic, urgency, "
                    "or the need to please others.\n\n"
                    "*[Placeholder — Authority and decision-making content will be added here.]*"
                ),
            },
            {
                "key": "ty-body",
                "title": "The Body as Feedback",
                "slug": "the-body-as-feedback",
                "content_type": "text",
                "position": 3,
                "estimated_minutes": 8,
                "content_body": (
                    "Before we learn to trust ourselves, we need to learn to read ourselves.\n\n"
                    "The body holds signals that the mind often overrides. A tightness in the "
                    "chest. A sense of heaviness when you agree to something you shouldn't. "
                    "A sudden ease or expansion when something is genuinely aligned.\n\n"
                    "This step introduces a simple practice of reading body-based feedback "
                    "as information — not as emotion to manage, but as data to notice.\n\n"
                    "*[Placeholder — somatic feedback content will be added here.]*"
                ),
            },
            {
                "key": "ty-pressure",
                "title": "Noticing Pressure, Urgency, and Overthinking",
                "slug": "noticing-pressure-urgency-overthinking",
                "content_type": "text",
                "position": 4,
                "estimated_minutes": 8,
                "content_body": (
                    "The three most common things that override self-trust:\n\n"
                    "**Pressure** — the feeling that you need to decide now, respond now, "
                    "or fix this now, even when you don't.\n\n"
                    "**Urgency** — often absorbed from others (especially if you have an "
                    "undefined Root or Solar Plexus in Human Design).\n\n"
                    "**Overthinking** — using the mind to try to solve something that needs "
                    "the body to answer.\n\n"
                    "This step helps you recognise these states before you act from them.\n\n"
                    "*[Placeholder — content on pressure, urgency, and overthinking will be added here.]*"
                ),
            },
            {
                "key": "ty-practise",
                "title": "Practise: Pause Before You Decide",
                "slug": "practise-pause-before-you-decide",
                "content_type": "exercise",
                "position": 5,
                "estimated_minutes": 5,
                "content_body": (
                    "A simple, repeatable practice for building self-trust one decision at a time.\n\n"
                    "Before making any decision — large or small — try this:\n\n"
                    "1. **Notice the pressure.** Is there urgency here? Does it feel like it needs "
                    "to be decided right now?\n"
                    "2. **Ask: is this mine?** Is this urgency actually yours, or are you absorbing "
                    "someone else's timeline?\n"
                    "3. **Check your body.** What does a yes feel like in your body right now? "
                    "What does a no feel like?\n"
                    "4. **Give yourself permission to wait.** You are allowed to say: I need a moment "
                    "with this. I will come back to you.\n\n"
                    "Use this practice on a decision you are sitting with right now. Write what you notice.\n\n"
                    "*[Placeholder — guided audio or video for this practice will be added here.]*"
                ),
            },
            {
                "key": "ty-reflection",
                "title": "Integration Reflection",
                "slug": "trust-yourself-integration",
                "content_type": "reflection",
                "position": 6,
                "estimated_minutes": 10,
                "content_body": (
                    "Before you leave this pathway, take a moment to integrate.\n\n"
                    "**Reflection prompts:**\n\n"
                    "* Where in your life are you most likely to override your own signal?\n"
                    "* What does pressure or urgency typically feel like in your body?\n"
                    "* What is one decision you have been sitting with that could benefit "
                    "from slowing down?\n"
                    "* What would it mean to actually trust yourself in that decision?\n\n"
                    "Write here, or in your own notebook. There is no right answer.\n\n"
                    "*[Placeholder — a closing reflection prompt video will be added here.]*"
                ),
            },
        ]

        for s in trust_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_trust.id,
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
            print(f"  [{'created' if created else 'updated'}] (Trust Yourself) {s['title']}")

        # --- Embodied Leadership Practices (5 steps) ---
        embodied_steps = [
            {
                "key": "el-meditations",
                "title": "🧘 Type Meditations",
                "slug": "type-meditations",
                "content_type": "audio",
                "position": 1,
                "estimated_minutes": 15,
                "content_body": (
                    "A short meditation for each Human Design Type — designed to help you connect "
                    "with your natural energy, settle your nervous system, and arrive in your body "
                    "before the demands of the day.\n\n"
                    "Find your Type and listen when you need to come back to yourself.\n\n"
                    "*[Placeholder — Type meditation audio files will be added here.]*"
                ),
            },
            {
                "key": "el-catch-choose",
                "title": "Practice: Catch and Choose",
                "slug": "practice-catch-and-choose",
                "content_type": "exercise",
                "position": 2,
                "estimated_minutes": 5,
                "content_body": (
                    "A micro-practice for the moments when you notice yourself slipping into "
                    "an old pattern.\n\n"
                    "**Catch** — name it, without judgment: *I'm doing the thing.*\n\n"
                    "**Pause** — take one breath. You don't need to understand it right now.\n\n"
                    "**Choose** — ask: what is one small, different thing I could do in this moment?\n\n"
                    "That is the whole practice. Catch. Pause. Choose.\n\n"
                    "Use it in meetings, conversations, in your own head. "
                    "The more you practise it, the shorter the gap becomes between the pattern "
                    "and the choice.\n\n"
                    "*[Placeholder — a short instructional video for this practice will be added here.]*"
                ),
            },
            {
                "key": "el-coming-home",
                "title": "Practice: Coming Home",
                "slug": "practice-coming-home",
                "content_type": "audio",
                "position": 3,
                "estimated_minutes": 10,
                "content_body": (
                    "A short practice for when you feel scattered, over-extended, or far from yourself.\n\n"
                    "This practice brings you back into your body, your breath, and your centre. "
                    "It is not meditation. It is a return.\n\n"
                    "Use it at your desk, in your car, before a difficult conversation, "
                    "or any time you need to come back to yourself.\n\n"
                    "*[Placeholder — a 10-minute guided audio practice will be added here.]*"
                ),
            },
            {
                "key": "el-checkin",
                "title": "Inner Leadership Check-In",
                "slug": "inner-leadership-check-in",
                "content_type": "reflection",
                "position": 4,
                "estimated_minutes": 5,
                "content_body": (
                    "A short weekly check-in to stay connected to your own energy and direction.\n\n"
                    "**Five questions:**\n\n"
                    "1. What is my energy like right now — steady, scattered, depleted, open?\n"
                    "2. Where am I over-functioning this week?\n"
                    "3. What am I avoiding that deserves attention?\n"
                    "4. What is one thing I could stop doing, or do differently?\n"
                    "5. What does aligned feel like for me this week?\n\n"
                    "Use this check-in as a regular practice — weekly, or whenever you feel out of step.\n\n"
                    "*[Placeholder — a check-in audio guide will be added here.]*"
                ),
            },
            {
                "key": "el-daily",
                "title": "Daily Integration Practices",
                "slug": "daily-integration-practices",
                "content_type": "text",
                "position": 5,
                "estimated_minutes": 5,
                "content_body": (
                    "Small, daily practices that support embodied leadership over time.\n\n"
                    "These are not a protocol or a non-negotiable morning routine. "
                    "They are a menu — choose what fits your season.\n\n"
                    "**Morning:** One minute of stillness before checking your phone. "
                    "Ask: what do I need to lead well today?\n\n"
                    "**Transition:** Before switching contexts (work to home, meeting to meeting), "
                    "take three slow breaths and reset.\n\n"
                    "**Evening:** One thing you aligned with today. One thing you want to do "
                    "differently tomorrow.\n\n"
                    "**Weekly:** The Inner Leadership Check-In (previous step).\n\n"
                    "None of these are mandatory. The one that matters is the one you do.\n\n"
                    "*[Placeholder — a daily practices guide (PDF or text) will be added here.]*"
                ),
            },
        ]

        for s in embodied_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_embodied.id,
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
            print(f"  [{'created' if created else 'updated'}] (Embodied) {s['title']}")

        # --- Tools & Templates (8 steps) ---
        tools_steps = [
            {
                "key": "tt-quiz",
                "title": "Self-Awareness Quiz",
                "slug": "self-awareness-quiz",
                "content_type": "text",
                "position": 1,
                "estimated_minutes": 2,
                "content_body": (
                    "**Coming later: Self-Awareness Quiz**\n\n"
                    "An interactive quiz to help you identify your current leadership patterns, "
                    "energy style, and where you are most likely to over-function or override yourself.\n\n"
                    "The quiz will ask a short series of questions and point you toward the "
                    "pathways and tools most relevant to where you are right now.\n\n"
                    "*Interactive quiz functionality is coming later.*\n\n"
                    "In the meantime, explore the pathways directly — Start Here is a good "
                    "first step if you are not sure where to begin."
                ),
            },
            {
                "key": "tt-chart",
                "title": "Human Design Chart Download",
                "slug": "human-design-chart-download",
                "content_type": "text",
                "position": 2,
                "estimated_minutes": 3,
                "content_body": (
                    "To use the Human Design content in this Hub, you will need your BodyGraph chart.\n\n"
                    "Your chart is generated from your birth date, exact birth time, and birth location.\n\n"
                    "**How to get your chart:**\n\n"
                    "Visit a free Human Design chart generator (such as Jovian Archive, "
                    "My Bodygraph, or a similar service) and enter your birth details.\n\n"
                    "Once you have your chart, note your:\n\n"
                    "* **Type** (Manifestor, Generator, MG, Projector, or Reflector)\n"
                    "* **Strategy**\n"
                    "* **Authority**\n"
                    "* **Profile** (two numbers)\n\n"
                    "These four pieces of information are the foundation of the Human Design "
                    "content in this Hub.\n\n"
                    "*[Placeholder — a guide or direct link for chart generation will be added here.]*"
                ),
            },
            {
                "key": "tt-type",
                "title": "Type Cheat Sheets",
                "slug": "type-cheat-sheets",
                "content_type": "text",
                "position": 3,
                "estimated_minutes": 5,
                "content_body": (
                    "A quick reference guide for each of the five Human Design Types.\n\n"
                    "Includes: natural Strategy, signature (alignment feeling), not-self theme "
                    "(misalignment signal), and key leadership considerations.\n\n"
                    "*[Placeholder — Type cheat sheet resources (PDF or structured text) "
                    "will be added here.]*"
                ),
            },
            {
                "key": "tt-authority",
                "title": "Authority Cheat Sheets",
                "slug": "authority-cheat-sheets",
                "content_type": "text",
                "position": 4,
                "estimated_minutes": 5,
                "content_body": (
                    "A quick reference guide for each Human Design Authority.\n\n"
                    "Includes: what it feels like to use your Authority well, common traps, "
                    "and a simple practice for each.\n\n"
                    "*[Placeholder — Authority cheat sheet resources will be added here.]*"
                ),
            },
            {
                "key": "tt-reconditioning",
                "title": "Reconditioning Map",
                "slug": "reconditioning-map",
                "content_type": "text",
                "position": 5,
                "estimated_minutes": 10,
                "content_body": (
                    "A structured tool for mapping the patterns and conditioning you are "
                    "working to release — and what you are moving toward.\n\n"
                    "Designed to support the Recognise and Explore phases of the R.E.A.L. Framework.\n\n"
                    "*[Placeholder — the Reconditioning Map worksheet will be added here.]*"
                ),
            },
            {
                "key": "tt-90day",
                "title": "90-Day Leadership Integration Plan",
                "slug": "90-day-leadership-integration-plan",
                "content_type": "text",
                "position": 6,
                "estimated_minutes": 10,
                "content_body": (
                    "A simple 90-day planning template for integrating what you are learning "
                    "in the Hub into your real life — at work, at home, in your relationships.\n\n"
                    "Designed to work with the Lead phase of the R.E.A.L. Framework.\n\n"
                    "*[Placeholder — the 90-Day Integration Plan template will be added here.]*"
                ),
            },
            {
                "key": "tt-reset",
                "title": "Alignment Reset Kit",
                "slug": "alignment-reset-kit",
                "content_type": "text",
                "position": 7,
                "estimated_minutes": 5,
                "content_body": (
                    "A short collection of practices and prompts for when you feel off-track, "
                    "over-extended, or disconnected from yourself.\n\n"
                    "The Alignment Reset Kit is not about fixing yourself. "
                    "It is about returning — to your own signal, your own rhythm, your own knowing.\n\n"
                    "*[Placeholder — Alignment Reset Kit content will be added here.]*"
                ),
            },
            {
                "key": "tt-fieldguide",
                "title": "Field Guide",
                "slug": "field-guide",
                "content_type": "text",
                "position": 8,
                "estimated_minutes": 5,
                "content_body": (
                    "The Natural Leader Field Guide — a compact reference for key concepts, "
                    "frameworks, and practices from across the Hub.\n\n"
                    "Use it as a quick reference when you are in the middle of a situation "
                    "and need a prompt, a reframe, or a reminder of what you already know.\n\n"
                    "*[Placeholder — the Field Guide (PDF or structured content) will be added here.]*"
                ),
            },
        ]

        for s in tools_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_tools.id,
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
            print(f"  [{'created' if created else 'updated'}] (Tools) {s['title']}")

        # --- Live Replays (3 steps) ---
        replay_steps = [
            {
                "key": "lr-how",
                "title": "How to Use the Replay Library",
                "slug": "how-to-use-replays",
                "content_type": "text",
                "position": 1,
                "estimated_minutes": 2,
                "content_body": (
                    "This pathway is the home for recordings of live calls, integration circles, "
                    "and community sessions from The Grove.\n\n"
                    "Replays are added after each live event. You can watch them in your own time, "
                    "at your own pace.\n\n"
                    "**A note on replays:**\n"
                    "Live calls are always the richest experience. But replays carry something real too. "
                    "Pause when something lands. Rewatch sections that are relevant to where you are. "
                    "Use them as reference, not just content.\n\n"
                    "*[Placeholder — replay library instructions will be updated as content is added.]*"
                ),
            },
            {
                "key": "lr-circle",
                "title": "Integration Circle Replay",
                "slug": "integration-circle-replay",
                "content_type": "video",
                "position": 2,
                "estimated_minutes": 60,
                "content_body": (
                    "A recording of a live Integration Circle — a group session focused on "
                    "bringing the R.E.A.L. Journey work into real life.\n\n"
                    "Integration Circles include sharing, reflection prompts, and guided "
                    "discussion. They are not lectures — they are community.\n\n"
                    "*[Placeholder — Integration Circle replay will be added here once available.]*"
                ),
            },
            {
                "key": "lr-call",
                "title": "Live Call Replay",
                "slug": "live-call-replay",
                "content_type": "video",
                "position": 3,
                "estimated_minutes": 60,
                "content_body": (
                    "A recording of a live community call or teaching session.\n\n"
                    "Topics vary — this placeholder will be updated with specific call information "
                    "as recordings are added to the library.\n\n"
                    "*[Placeholder — Live Call replay will be added here once available.]*"
                ),
            },
        ]

        for s in replay_steps:
            obj, created = upsert(db, PathwayStep, STEP_IDS[s["key"]], {
                "pathway_id": p_replays.id,
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
            print(f"  [{'created' if created else 'updated'}] (Replays) {s['title']}")

        db.flush()

        # ── Part 4: Resources ──────────────────────────────────────────────
        print("\n── Part 4: Resources ──")

        # General resources — visible to all collective members
        general_resources = [
            {
                "id": RESOURCE_IDS["welcome-guide"],
                "title": "Welcome to The Grove",
                "description": (
                    "A short welcome guide to help you orient in the Hub — what it is, "
                    "how the pathways work, and where to begin. A good first read."
                ),
                "sort_order": 1,
            },
            {
                "id": RESOURCE_IDS["how-to-use"],
                "title": "How to Use This Space",
                "description": (
                    "A practical guide to navigating the Hub — pathways, community, resources, "
                    "and how to set your own pace. Includes tips for reflection and integration."
                ),
                "sort_order": 2,
            },
            {
                "id": RESOURCE_IDS["community-guidelines"],
                "title": "Community Guidelines",
                "description": (
                    "How we show up for each other in The Grove. "
                    "Short, warm, and grounded in the same principles we practise in the pathways."
                ),
                "sort_order": 3,
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

        # Paid resource — scoped to R.E.A.L. Journey pathway only
        # Not available to free members. See TODO #2 for future shared-resource logic.
        obj, created = upsert(db, SpaceResource, RESOURCE_IDS["gift-ebook"], {
            "space_id": SPACE_ID,
            "created_by_id": CREATOR_ID,
            "title": "My Gift to You — The Natural Leader",
            "description": (
                "A bonus ebook for members of The R.E.A.L. Journey pathway. "
                "A companion guide to the framework — designed to be read alongside "
                "the pathway and returned to as a reference."
            ),
            "resource_type": "guide",
            "scope": "pathway",
            "pathway_id": p_real.id,
            "status": "published",
            "sort_order": 1,
            "created_at": SEED_TS,
            "updated_at": SEED_TS,
        }, refresh_fields=["title", "description"])
        print(f"  [{'created' if created else 'updated'}] (pathway/paid) My Gift to You — ebook")

        # Tools & Templates pathway resources
        tools_resources = [
            {
                "id": RESOURCE_IDS["quiz-placeholder"],
                "title": "Self-Awareness Quiz",
                "description": (
                    "Interactive quiz coming later. In the meantime, use the Start Here "
                    "pathway to orient, or explore the Human Design Foundations pathway "
                    "for a practical self-awareness starting point."
                ),
                "sort_order": 1,
            },
            {
                "id": RESOURCE_IDS["hd-chart-download"],
                "title": "Human Design Chart — How to Get Yours",
                "description": (
                    "Instructions for generating your free Human Design BodyGraph chart. "
                    "You will need your birth date, exact birth time, and birth location."
                ),
                "sort_order": 2,
            },
            {
                "id": RESOURCE_IDS["type-cheat-sheets"],
                "title": "Type Cheat Sheets",
                "description": (
                    "Quick reference guides for all five Human Design Types — Strategy, "
                    "signature, not-self theme, and key leadership considerations."
                ),
                "sort_order": 3,
            },
            {
                "id": RESOURCE_IDS["authority-cheat-sheets"],
                "title": "Authority Cheat Sheets",
                "description": (
                    "Quick reference guides for each Human Design Authority — how to use it, "
                    "common traps, and a simple practice for each."
                ),
                "sort_order": 4,
            },
            {
                "id": RESOURCE_IDS["reconditioning-map"],
                "title": "Reconditioning Map",
                "description": (
                    "A structured worksheet for mapping the patterns and conditioning you are "
                    "working to release — and what you are moving toward. Supports the "
                    "Recognise and Explore phases of the R.E.A.L. Framework."
                ),
                "sort_order": 5,
            },
            {
                "id": RESOURCE_IDS["90day-plan"],
                "title": "90-Day Leadership Integration Plan",
                "description": (
                    "A planning template for integrating what you are learning in the Hub into "
                    "your real life over 90 days. Supports the Lead phase of the R.E.A.L. Framework."
                ),
                "sort_order": 6,
            },
            {
                "id": RESOURCE_IDS["alignment-reset"],
                "title": "Alignment Reset Kit",
                "description": (
                    "A short collection of practices and prompts for when you feel off-track, "
                    "over-extended, or disconnected from yourself. A return, not a fix."
                ),
                "sort_order": 7,
            },
            {
                "id": RESOURCE_IDS["field-guide"],
                "title": "The Natural Leader Field Guide",
                "description": (
                    "A compact reference for key concepts, frameworks, and practices from "
                    "across the Hub. Use it as a quick reference in real situations."
                ),
                "sort_order": 8,
            },
        ]

        for r in tools_resources:
            obj, created = upsert(db, SpaceResource, r["id"], {
                "space_id": SPACE_ID,
                "created_by_id": CREATOR_ID,
                "title": r["title"],
                "description": r["description"],
                "resource_type": "guide",
                "scope": "pathway",
                "pathway_id": p_tools.id,
                "status": "published",
                "sort_order": r["sort_order"],
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "description"])
            print(f"  [{'created' if created else 'updated'}] (tools pathway) {r['title']}")

        db.flush()

        # ── Part 5: Community posts ────────────────────────────────────────
        print("\n── Part 5: Community posts ──")

        # Update the existing welcome post (seeded in migration 006) with NLH-specific content
        welcome_post = db.query(CommunityPost).filter_by(id=POST_IDS["welcome"]).first()
        if welcome_post:
            welcome_post.title = "Welcome to The Grove"
            welcome_post.body = (
                "Welcome to The Grove.\n\n"
                "This is a space for women ready to lead with more self-trust, authenticity, "
                "and alignment — not by doing more, but by coming back to who they already are.\n\n"
                "**To get started:**\n\n"
                "1. Visit the **Start Here** pathway — a short orientation to the Hub and "
                "how to find your footing.\n"
                "2. Explore the **Pathways** tab to see what is available, free and paid.\n"
                "3. Introduce yourself in the community (see the pinned post below).\n\n"
                "There is no right way to move through this space. Come back in your own time, "
                "with your own questions. The structure holds; the pace is yours.\n\n"
                "We are glad you are here."
            )
            welcome_post.post_type = "announcement"
            welcome_post.is_pinned = True
            print("  [updated] Welcome to The Grove (existing post refreshed)")
        else:
            print("  [skipped] Welcome post not found — may not have been seeded yet")

        # New community posts
        new_posts = [
            {
                "id": POST_IDS["introduce"],
                "title": "Introduce yourself",
                "body": (
                    "We would love to know who you are.\n\n"
                    "Share:\n\n"
                    "* Your name, and something about where you are in life right now\n"
                    "* What brought you to The Grove\n"
                    "* Something you are learning to trust in yourself\n\n"
                    "There is no right answer. Even a few words is enough. "
                    "You are welcome here exactly as you are."
                ),
                "post_type": "prompt",
                "is_pinned": True,
            },
            {
                "id": POST_IDS["edge"],
                "title": "Your current leadership edge",
                "body": (
                    "A question to sit with this week:\n\n"
                    "**Where are you noticing old patterns, pressure, or over-functioning right now?**\n\n"
                    "It might be at work, at home, in a relationship, or in your own head. "
                    "It might be subtle. It might be very loud.\n\n"
                    "You do not need to have answers. Just name what you are noticing — "
                    "that is the Recognise step, and it is enough to begin."
                ),
                "post_type": "prompt",
                "is_pinned": False,
            },
            {
                "id": POST_IDS["action"],
                "title": "One small aligned action",
                "body": (
                    "The R.E.A.L. Framework asks us to Live — to try one small, real experiment "
                    "rather than waiting for the perfect moment or the complete plan.\n\n"
                    "**What is one small aligned action you are experimenting with this week?**\n\n"
                    "It might be a boundary you practised naming. A conversation you had. "
                    "A moment you chose to pause instead of react. A decision you made from "
                    "your own knowing rather than the pressure around you.\n\n"
                    "Share it here. Even small things, named out loud, become more real."
                ),
                "post_type": "prompt",
                "is_pinned": False,
            },
        ]

        for p in new_posts:
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

        print("\n✓  The Grove content seeded successfully.\n")
        print("── Pathways ──────────────────────────────────────────────────")
        print("  1. Start Here              — included (free), active")
        print("  2. The R.E.A.L. Journey    — one_time (paid), active | steps 1–6 preserved from migration 004")
        print("  3. Human Design Foundations — one_time (paid), coming_soon")
        print("  4. Trust Yourself          — one_time (paid), coming_soon")
        print("  5. Embodied Leadership     — one_time (paid), coming_soon")
        print("  6. Tools & Templates       — included (free), active")
        print("  7. Live Replays            — one_time (paid), coming_soon")
        print("\n── Pricing notes ─────────────────────────────────────────────")
        print("  price_cents = None for all paid pathways.")
        print("  Set prices manually when Stripe checkout is ready.")
        print("\n── TODOs (future platform improvements) ──────────────────────")
        print("  1. Pathway bundles:")
        print("       R.E.A.L. Journey + Human Design Foundations + Trust Yourself")
        print("  2. Paid-member shared resources:")
        print("       My Gift to You ebook should be accessible to any paid pathway member,")
        print("       not just R.E.A.L. Journey. Awaiting shared-resource scope feature.")
        print("  3. Interactive quiz builder:")
        print("       Self-Awareness Quiz with branching logic and results.")
        print("  4. Creator colour themes (curated presets):")
        print("       NLH:    navy / gold / soft aqua")
        print("       EMBODY: teal / aqua / gold")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
