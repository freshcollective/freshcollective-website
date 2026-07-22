#!/usr/bin/env python3
"""
Content seed script: Life in Alignment pathway — The Grove, Fresh Collective.

Creates or updates:
  - 1 pathway: Life in Alignment (slug: life-in-alignment)
  - 6 sections: Phase 0–5
  - 75 steps: 14 weeks × 5 steps + 5 phase milestones
  - 5 resources scoped to this pathway

Idempotent — safe to run multiple times.
Does NOT touch: R.E.A.L. Journey, Human Design pathways, EMBODY, any other space.

Step structure per week (× 14 weeks):
  1. Video          — content_type: video
  2. Workbook       — content_type: text   (PDF placeholder)
  3. Practice       — content_type: exercise
  4. Reflection     — content_type: reflection
  5. Community Prompt — content_type: text

Milestones (× 5, one per phase 1–5):
  - content_type: text, placed at end of each phase section

Usage:
    cd /home/lindsey/fc-production/backend
    .venv/bin/python ../scripts/seed_lia_content.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app.models.user      # noqa: F401
import app.models.platform  # noqa: F401

from app.core.database import SessionLocal
from app.models.platform import (
    Pathway, PathwaySection, PathwayStep, Space, SpaceResource,
)

# ── Stable identifiers ────────────────────────────────────────────────────────

SPACE_ID    = "80862f54-d95f-4b3b-83ab-cf926014441d"  # The Grove
PATHWAY_ID  = "pa000001-lia0-4000-8000-000000000001"

SECTION_IDS = {
    "phase-0": "se000001-lia0-4000-8000-000000000001",
    "phase-1": "se000001-lia0-4000-8000-000000000002",
    "phase-2": "se000001-lia0-4000-8000-000000000003",
    "phase-3": "se000001-lia0-4000-8000-000000000004",
    "phase-4": "se000001-lia0-4000-8000-000000000005",
    "phase-5": "se000001-lia0-4000-8000-000000000006",
}

# Steps numbered 001–075 (global sequential, also used for section_position logic)
def _step_id(n: int) -> str:
    return f"st000001-lia0-4000-8000-{n:012d}"

RESOURCE_IDS = {
    "nl-book":        "rs000001-lia0-4000-8000-000000000001",
    "hd-chart-guide": "rs000001-lia0-4000-8000-000000000002",
    "healing-vortex": "rs000001-lia0-4000-8000-000000000003",
    "fem-archetypes": "rs000001-lia0-4000-8000-000000000004",
    "qna-replays":    "rs000001-lia0-4000-8000-000000000005",
}

SEED_TS = datetime(2026, 6, 19, 10, 0, 0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def upsert(db, model, record_id: str, fields: dict, refresh_fields: list = ()):
    obj = db.query(model).filter_by(id=record_id).first()
    if obj:
        for f in refresh_fields:
            if f in fields:
                setattr(obj, f, fields[f])
        return obj, False
    obj = model(id=record_id, **fields)
    db.add(obj)
    return obj, True


def upsert_section(db, section_id: str, pathway_id: str, title: str, position: int):
    obj = db.query(PathwaySection).filter_by(id=section_id).first()
    if obj:
        obj.title = title
        obj.position = position
        return obj, False
    obj = PathwaySection(
        id=section_id,
        pathway_id=pathway_id,
        title=title,
        position=position,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    )
    db.add(obj)
    return obj, True


def make_step(
    n: int,
    pathway_id: str,
    section_id: str,
    section_position: int,
    slug: str,
    title: str,
    content_type: str,
    content_body: str,
    estimated_minutes: int,
    is_required: bool = False,
    content_url: str | None = None,
) -> dict:
    return {
        "id": _step_id(n),
        "fields": {
            "pathway_id": pathway_id,
            "section_id": section_id,
            "section_position": section_position,
            "slug": slug,
            "title": title,
            "content_type": content_type,
            "content_body": content_body,
            "content_url": content_url,
            "estimated_minutes": estimated_minutes,
            "is_required": is_required,
            "position": n,
            "created_at": SEED_TS,
            "updated_at": SEED_TS,
        },
    }


REFRESH = ["title", "content_body", "estimated_minutes", "section_id", "section_position", "position"]


# ── Week step factory ─────────────────────────────────────────────────────────

def week_steps(
    start_n: int,
    pathway_id: str,
    section_id: str,
    section_start: int,
    week_num: int,
    week_slug: str,
    week_title: str,
    theme: str,
    video_minutes: int,
    workbook_minutes: int,
    reflection_prompts: str,
    community_prompt: str,
) -> list[dict]:
    n = start_n
    sp = section_start
    steps = []

    # 1. Video
    steps.append(make_step(
        n=n, pathway_id=pathway_id, section_id=section_id, section_position=sp,
        slug=f"week-{week_num:02d}-video",
        title=f"Week {week_num} — Video",
        content_type="video",
        content_body=(
            f"*[Placeholder: Week {week_num} teaching video — {week_title}. Upload to replace this placeholder.]*\n\n"
            f"**Theme:** {theme}"
        ),
        estimated_minutes=video_minutes,
        content_url=None,
    ))
    n += 1; sp += 1

    # 2. Workbook
    steps.append(make_step(
        n=n, pathway_id=pathway_id, section_id=section_id, section_position=sp,
        slug=f"week-{week_num:02d}-workbook",
        title=f"Week {week_num} Workbook",
        content_type="text",
        content_body=(
            f"*[Placeholder: Week {week_num} workbook PDF — {week_title}. Add download link or embed when ready.]*\n\n"
            f"Download the workbook and complete it before moving to the practice for this week.\n\n"
            f"**What to bring:** Your responses from the video and any observations from the past week."
        ),
        estimated_minutes=workbook_minutes,
    ))
    n += 1; sp += 1

    # 3. Practice
    steps.append(make_step(
        n=n, pathway_id=pathway_id, section_id=section_id, section_position=sp,
        slug=f"week-{week_num:02d}-practice",
        title=f"Week {week_num} Practice",
        content_type="exercise",
        content_body=(
            f"*[Placeholder: Week {week_num} practice — {week_title}. Add practice instructions when ready.]*\n\n"
            f"**This week's practice:** {theme}\n\n"
            f"Use this practice daily or as often as feels right this week. "
            f"Notice what arises and bring it to the reflection and community discussion."
        ),
        estimated_minutes=10,
    ))
    n += 1; sp += 1

    # 4. Reflection
    steps.append(make_step(
        n=n, pathway_id=pathway_id, section_id=section_id, section_position=sp,
        slug=f"week-{week_num:02d}-reflection",
        title=f"Week {week_num} Reflection",
        content_type="reflection",
        content_body=reflection_prompts,
        estimated_minutes=15,
    ))
    n += 1; sp += 1

    # 5. Community prompt
    steps.append(make_step(
        n=n, pathway_id=pathway_id, section_id=section_id, section_position=sp,
        slug=f"week-{week_num:02d}-community",
        title=f"Week {week_num} — Community Discussion",
        content_type="text",
        content_body=(
            f"**Community Discussion — Week {week_num}: {week_title}**\n\n"
            f"{community_prompt}\n\n"
            f"*Share as much or as little as feels right. There is no right answer — "
            f"just what is true for you right now.*"
        ),
        estimated_minutes=5,
    ))
    n += 1; sp += 1

    return steps


def milestone_step(
    n: int,
    pathway_id: str,
    section_id: str,
    section_position: int,
    phase_name: str,
    phase_slug: str,
    celebration: str,
    reflection_prompt: str,
) -> dict:
    return make_step(
        n=n, pathway_id=pathway_id, section_id=section_id, section_position=section_position,
        slug=f"milestone-{phase_slug}",
        title=f"✦ {phase_name} Milestone",
        content_type="text",
        content_body=(
            f"## You have completed Phase — {phase_name}\n\n"
            f"{celebration}\n\n"
            f"---\n\n"
            f"**Milestone reflection:**\n\n"
            f"{reflection_prompt}\n\n"
            f"---\n\n"
            f"*Take your time here before moving to the next phase. "
            f"The pause between phases is part of the work.*"
        ),
        estimated_minutes=10,
        is_required=False,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():  # noqa: C901
    db = SessionLocal()
    try:
        from app.models.user import User
        admin = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        if not admin:
            print("ERROR: No admin user found. Aborting.")
            return
        CREATOR_ID = admin.id
        print(f"Admin user: {admin.email} ({CREATOR_ID})")

        space = db.query(Space).filter_by(id=SPACE_ID).first()
        if not space:
            print("ERROR: The Grove space not found. Aborting.")
            return
        print(f"Space: {space.name} ({space.slug})")

        # ── Part 1: Pathway ────────────────────────────────────────────────
        print("\n── Part 1: Pathway ──")

        pathway, created = upsert(
            db, Pathway, PATHWAY_ID,
            fields={
                "space_id": SPACE_ID,
                "slug": "life-in-alignment",
                "title": "Life in Alignment",
                "description": (
                    "Life in Alignment is a self-paced journey for women who are done living in "
                    "survival mode and ready to lead their own life with greater clarity, "
                    "self-trust and alignment.\n\n"
                    "Built on the R.E.A.L. Framework, grounded in Human Design, and supported by "
                    "somatic practices, this pathway helps women understand how they are uniquely "
                    "designed to operate, regulate their nervous system, make aligned decisions, "
                    "and create a life that feels more honest, sustainable and true.\n\n"
                    "Move at your own pace. Return whenever you need. The work is yours for life."
                ),
                "status": "active",
                "position": 1,
                "access_type": "one_time",
                "price_cents": None,
                "currency": "AUD",
                "is_sequential": True,
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            },
            refresh_fields=["title", "description", "status", "position"],
        )
        print(f"  [{'created' if created else 'updated'}] Life in Alignment (life-in-alignment)")

        db.flush()
        PID = pathway.id

        # ── Part 2: Sections ───────────────────────────────────────────────
        print("\n── Part 2: Sections ──")

        section_defs = [
            ("phase-0", "Phase 0 — Foundation",   1),
            ("phase-1", "Phase 1 — Recognise",    2),
            ("phase-2", "Phase 2 — Explore",      3),
            ("phase-3", "Phase 3 — Align",        4),
            ("phase-4", "Phase 4 — Lead",         5),
            ("phase-5", "Phase 5 — Integration",  6),
        ]

        sections = {}
        for key, title, position in section_defs:
            sec, created = upsert_section(db, SECTION_IDS[key], PID, title, position)
            sections[key] = sec
            print(f"  [{'created' if created else 'updated'}] {title}")

        db.flush()

        # ── Part 3: Steps ──────────────────────────────────────────────────
        print("\n── Part 3: Steps ──")

        all_steps: list[dict] = []
        n = 1  # global step counter (also used as position)

        # ── Phase 0 — Foundation ──
        sec0 = SECTION_IDS["phase-0"]

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec0, section_start=1,
            week_num=1, week_slug="foundation",
            week_title="Welcome + Orientation",
            theme="What Life in Alignment is and how to move through it",
            video_minutes=15,
            workbook_minutes=20,
            reflection_prompts=(
                "Take a few minutes to settle before writing.\n\n"
                "**Reflection prompts — Week 1:**\n\n"
                "* What brought you here? What are you hoping shifts?\n"
                "* What does 'aligned' feel like to you right now — even if you can only describe what it is not?\n"
                "* What do you need from yourself to move through this pathway with care?\n\n"
                "*Write without editing. There is no right answer.*"
            ),
            community_prompt=(
                "Introduce yourself to the Life in Alignment community.\n\n"
                "Share:\n"
                "* Your name and a little about where you are right now\n"
                "* One word for how you feel stepping into this pathway\n"
                "* What you are quietly hoping for on the other side of this work"
            ),
        )
        n += 5

        # ── Phase 1 — Recognise ──
        sec1 = SECTION_IDS["phase-1"]

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec1, section_start=1,
            week_num=2, week_slug="the-pattern",
            week_title="The Pattern",
            theme="Seeing clearly what keeps repeating — without judgment",
            video_minutes=20,
            workbook_minutes=30,
            reflection_prompts=(
                "**Reflection prompts — Week 2: The Pattern**\n\n"
                "* What is the pattern you keep returning to? Describe it as honestly as you can.\n"
                "* Where does it show up most? (Work, relationships, your own inner world?)\n"
                "* What has this pattern cost you? What has it, perhaps, protected?\n"
                "* When do you first remember meeting this pattern in yourself?\n\n"
                "*Stay curious, not critical. The Recognise step is not about fixing — it is about seeing.*"
            ),
            community_prompt=(
                "This week we are practising the Recognise step — naming what is actually happening.\n\n"
                "**Share (as much as feels right):**\n"
                "* One pattern you are willing to name out loud this week\n"
                "* One place it shows up in your daily life\n\n"
                "*You don't need to explain it fully or have answers. Just name it.*"
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec1, section_start=6,
            week_num=3, week_slug="the-conditioning",
            week_title="The Conditioning",
            theme="Where the pattern came from — and what it has been protecting",
            video_minutes=20,
            workbook_minutes=30,
            reflection_prompts=(
                "**Reflection prompts — Week 3: The Conditioning**\n\n"
                "* What messages did you absorb about how to be, how to lead, how to show up?\n"
                "* Whose expectations are you still carrying that were never yours to carry?\n"
                "* What did you learn to override — in yourself — to get approval or stay safe?\n"
                "* What would you have done differently if you had not been conditioned this way?\n\n"
                "*Go gently here. Conditioning is not a failure — it was adaptation. The question is: is it still useful?*"
            ),
            community_prompt=(
                "**Week 3 — The Conditioning**\n\n"
                "We all carry messages we absorbed without choosing them.\n\n"
                "Share one conditioning pattern you are becoming aware of this week — "
                "a message about leadership, worthiness, or how you 'should' be that no longer fits. "
                "You don't need to have released it. Just naming it is enough."
            ),
        )
        n += 5

        # Recognise Milestone
        all_steps.append(milestone_step(
            n=n, pathway_id=PID, section_id=sec1, section_position=11,
            phase_name="Recognise",
            phase_slug="recognise",
            celebration=(
                "You have done the quiet, honest work of the Recognise phase.\n\n"
                "You named the pattern. You traced the conditioning. You looked at what has been "
                "running in the background — not to shame it, but to see it clearly.\n\n"
                "That is the hardest part. And you did it."
            ),
            reflection_prompt=(
                "* What is the most significant thing you recognised in this phase?\n"
                "* What shifted — even slightly — in how you see yourself or your patterns?\n"
                "* What are you carrying into the Explore phase?"
            ),
        ))
        n += 1

        # ── Phase 2 — Explore ──
        sec2 = SECTION_IDS["phase-2"]

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec2, section_start=1,
            week_num=4, week_slug="your-energy",
            week_title="Your Energy",
            theme="How your Human Design Type and Strategy reveal the truth about how you are built",
            video_minutes=25,
            workbook_minutes=30,
            reflection_prompts=(
                "**Reflection prompts — Week 4: Your Energy**\n\n"
                "* What is your Human Design Type, and what does its Strategy ask of you?\n"
                "* Where in your life are you living your Strategy? Where are you overriding it?\n"
                "* What does your 'signature' (alignment feeling) actually feel like in your body?\n"
                "* What does your 'not-self theme' (misalignment signal) feel like — and when does it show up most?\n\n"
                "*If you are new to Human Design, use the chart guide in the Resources section first.*"
            ),
            community_prompt=(
                "**Week 4 — Your Energy**\n\n"
                "Share your Human Design Type (if you know it) and one thing that feels true about it — "
                "or one thing you are still questioning.\n\n"
                "Alternatively: where this week have you been living in alignment with your natural energy? "
                "And where have you been overriding it?"
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec2, section_start=6,
            week_num=5, week_slug="not-self-open-centres",
            week_title="Your Not-Self + Open Centres",
            theme="Understanding where you absorb pressure — and what it costs you",
            video_minutes=25,
            workbook_minutes=30,
            reflection_prompts=(
                "**Reflection prompts — Week 5: Your Not-Self + Open Centres**\n\n"
                "* Which of your centres are undefined (white in your chart)?\n"
                "* Where do you most often take on other people's energy, urgency, or expectations?\n"
                "* What does it feel like when you are operating from your not-self? "
                "What triggers usually precede it?\n"
                "* If you removed the pressure you are absorbing from others, what would remain as yours?\n\n"
                "*Use the Human Design Chart Guide and Open Centres resources to support this week's reflection.*"
            ),
            community_prompt=(
                "**Week 5 — Not-Self + Open Centres**\n\n"
                "This week is about noticing what is not yours.\n\n"
                "Share one moment this week where you caught yourself absorbing someone else's pressure, "
                "urgency, or expectation — and what it felt like when you noticed it."
            ),
        )
        n += 5

        # Explore Milestone
        all_steps.append(milestone_step(
            n=n, pathway_id=PID, section_id=sec2, section_position=11,
            phase_name="Explore",
            phase_slug="explore",
            celebration=(
                "You have moved through the Explore phase.\n\n"
                "You looked beneath the pattern — at your energy design, your conditioning, and the places "
                "where you have been absorbing what was never yours to carry.\n\n"
                "This is the phase where understanding deepens. Where the 'why' starts to emerge. "
                "That understanding is the foundation of everything that follows."
            ),
            reflection_prompt=(
                "* What did you discover in the Explore phase that surprised you?\n"
                "* What feels clearer about how your energy is designed to work?\n"
                "* What are you ready to release — or at least hold more lightly — as you move into Align?"
            ),
        ))
        n += 1

        # ── Phase 3 — Align ──
        sec3 = SECTION_IDS["phase-3"]

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec3, section_start=1,
            week_num=6, week_slug="nervous-system",
            week_title="Understanding the Nervous System",
            theme="Why regulation is the foundation of aligned leadership",
            video_minutes=25,
            workbook_minutes=25,
            reflection_prompts=(
                "**Reflection prompts — Week 6: Understanding the Nervous System**\n\n"
                "* What are your most common nervous system states? (Fight, flight, freeze, fawn — or settled?)\n"
                "* What typically triggers dysregulation for you?\n"
                "* What helps you return to a regulated, settled state?\n"
                "* How does nervous system dysregulation show up in your leadership and decision-making?\n\n"
                "*There is no ideal state to perform here. Just honesty about what is actually true.*"
            ),
            community_prompt=(
                "**Week 6 — The Nervous System**\n\n"
                "What does dysregulation look and feel like for you — in your body, in your behaviour, "
                "in your relationships?\n\n"
                "And: what is one thing you already do — or have done — that helps you come back to yourself?"
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec3, section_start=6,
            week_num=7, week_slug="reconditioning",
            week_title="Reconditioning",
            theme="The deliberate practice of releasing old patterns and choosing something truer",
            video_minutes=25,
            workbook_minutes=30,
            reflection_prompts=(
                "**Reflection prompts — Week 7: Reconditioning**\n\n"
                "* What is one pattern you are actively choosing to decondition?\n"
                "* What does the conditioned response look like? What would an aligned response feel like?\n"
                "* What gets in the way of choosing differently in the moment?\n"
                "* What support, structure, or practice would help you experiment with a new response?\n\n"
                "*Reconditioning is not about willpower. It is about noticing, pausing, and choosing — one moment at a time.*"
            ),
            community_prompt=(
                "**Week 7 — Reconditioning**\n\n"
                "Reconditioning happens in small, real moments — not in dramatic transformations.\n\n"
                "Share one small experiment you tried this week: a moment where you caught a conditioned "
                "response and chose something slightly different. What happened?"
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec3, section_start=11,
            week_num=8, week_slug="sustainable-container",
            week_title="A Sustainable Container",
            theme="Designing a life structure that fits your energy, rhythm and design",
            video_minutes=20,
            workbook_minutes=35,
            reflection_prompts=(
                "**Reflection prompts — Week 8: A Sustainable Container**\n\n"
                "* What does a sustainable week actually look like for your energy type?\n"
                "* Where are you currently saying yes to things that cost more than they return?\n"
                "* What boundaries, rhythms, or structures would protect your energy?\n"
                "* What would need to change — in your schedule, commitments, or environment — "
                "for your life to feel more sustainable?\n\n"
                "*Think practically. Sustainability is not a luxury — it is a prerequisite for aligned leadership.*"
            ),
            community_prompt=(
                "**Week 8 — A Sustainable Container**\n\n"
                "What is one structural change — however small — you are considering making to create "
                "more space, more rhythm, or more sustainability in your life right now?\n\n"
                "Or: what is one thing you are currently doing that costs more energy than it returns?"
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec3, section_start=16,
            week_num=9, week_slug="integration-rest",
            week_title="Integration + Rest",
            theme="A week to slow down, integrate, and prepare for the Lead phase",
            video_minutes=10,
            workbook_minutes=20,
            reflection_prompts=(
                "**Reflection prompts — Week 9: Integration + Rest**\n\n"
                "This is a slower week by design. There is no new content to consume — only space to integrate.\n\n"
                "* What has shifted since you began this pathway?\n"
                "* What is still feeling unresolved or unclear?\n"
                "* What does your body need right now — rest, movement, stillness, connection?\n"
                "* What do you want to carry consciously into the Lead phase?\n\n"
                "*You do not need to have everything figured out. Integration is not a destination — it is a practice.*"
            ),
            community_prompt=(
                "**Week 9 — Integration + Rest**\n\n"
                "This is our integration week — a pause before the Lead phase.\n\n"
                "Share one thing that has genuinely shifted for you in the Recognise, Explore, or Align phases. "
                "It might be a perspective, a feeling, a decision, a habit. Large or small — all of it counts."
            ),
        )
        n += 5

        # Align Milestone
        all_steps.append(milestone_step(
            n=n, pathway_id=PID, section_id=sec3, section_position=21,
            phase_name="Align",
            phase_slug="align",
            celebration=(
                "You have moved through the Align phase — the deepest and most challenging part of this pathway.\n\n"
                "You explored your nervous system. You began reconditioning. You looked honestly at "
                "what you need to sustain yourself.\n\n"
                "You rested. You integrated. You arrived here.\n\n"
                "The Lead phase is what all of this has been preparing you for."
            ),
            reflection_prompt=(
                "* What is the most significant shift that happened in the Align phase?\n"
                "* What does 'aligned' feel like in your body now, compared to when you started?\n"
                "* What are you most ready to lead — in your decisions, your life, your relationships — "
                "as you move into the Lead phase?"
            ),
        ))
        n += 1

        # ── Phase 4 — Lead ──
        sec4 = SECTION_IDS["phase-4"]

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec4, section_start=1,
            week_num=10, week_slug="leading-decisions",
            week_title="Leading Your Decisions",
            theme="Applying your Human Design Authority to real decisions — the pause, the signal, the choice",
            video_minutes=20,
            workbook_minutes=25,
            reflection_prompts=(
                "**Reflection prompts — Week 10: Leading Your Decisions**\n\n"
                "* What is one decision you are currently sitting with?\n"
                "* What does your Authority (Human Design inner compass) say — when you get quiet enough to listen?\n"
                "* What is the pressure or urgency around this decision? Is it genuinely yours?\n"
                "* What would it look like to make this decision from alignment rather than from pressure?\n\n"
                "*The goal is not the perfect decision. The goal is a decision made from your own signal.*"
            ),
            community_prompt=(
                "**Week 10 — Leading Your Decisions**\n\n"
                "Share a decision you are practising — or have recently made — using your inner authority "
                "rather than pressure, urgency, or what you think you 'should' choose.\n\n"
                "What did it feel like to wait for your own signal? What happened?"
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec4, section_start=6,
            week_num=11, week_slug="leading-your-life",
            week_title="Leading Your Life",
            theme="What an aligned life actually looks like — vision, honesty, and deliberate design",
            video_minutes=25,
            workbook_minutes=35,
            reflection_prompts=(
                "**Reflection prompts — Week 11: Leading Your Life**\n\n"
                "* If you were genuinely living in alignment with your design, what would be different?\n"
                "* What parts of your life feel most misaligned right now?\n"
                "* What do you want to be true about your life in 12 months — honestly, not aspirationally?\n"
                "* What is one small, concrete step toward that life you could take this week?\n\n"
                "*This is not a manifestation exercise. It is an honest reckoning with what is true and what you want.*"
            ),
            community_prompt=(
                "**Week 11 — Leading Your Life**\n\n"
                "What does an aligned life feel like — or look like — for you?\n\n"
                "Share one honest thing about how you want your life to be different "
                "from how it is right now. Not how it 'should' look — how you actually want it to feel."
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec4, section_start=11,
            week_num=12, week_slug="leading-others",
            week_title="Leading Others",
            theme="How your natural leadership style shows up in relationships, work and community",
            video_minutes=25,
            workbook_minutes=30,
            reflection_prompts=(
                "**Reflection prompts — Week 12: Leading Others**\n\n"
                "* What is your natural leadership style — the way you lead when you are most yourself?\n"
                "* Where do you over-function for others? What does that cost you — and them?\n"
                "* What boundaries or boundaries-adjacent practices would allow you to lead with more ease?\n"
                "* Who are you leading — formally or informally — and what do they most need from you right now?\n\n"
                "*Natural leadership is not about having authority over others. It is about being genuinely yourself — and letting that be enough.*"
            ),
            community_prompt=(
                "**Week 12 — Leading Others**\n\n"
                "Where do you find yourself over-functioning for others — taking on more than is yours, "
                "or leading from obligation rather than choice?\n\n"
                "What would it look like to lead from your actual design instead?"
            ),
        )
        n += 5

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec4, section_start=16,
            week_num=13, week_slug="leading-creativity-flow",
            week_title="Leading from Creativity + Flow",
            theme="Accessing your creative energy, expressing your voice, and finding your rhythm",
            video_minutes=20,
            workbook_minutes=25,
            reflection_prompts=(
                "**Reflection prompts — Week 13: Leading from Creativity + Flow**\n\n"
                "* When do you feel most creative, most alive, most in flow?\n"
                "* What conditions support that state — and what kills it?\n"
                "* What creative expression has been dormant or suppressed in you?\n"
                "* What would you create, build, or begin if you trusted your own creative signal?\n\n"
                "*Creativity is not a personality trait. It is what emerges when you are sufficiently regulated and aligned.*"
            ),
            community_prompt=(
                "**Week 13 — Leading from Creativity + Flow**\n\n"
                "When do you feel most in flow — most yourself, most alive, most naturally creative?\n\n"
                "Share what that state feels like, and one condition that helps you access it. "
                "It might be a time of day, a physical environment, a relationship, a practice."
            ),
        )
        n += 5

        # Lead Milestone
        all_steps.append(milestone_step(
            n=n, pathway_id=PID, section_id=sec4, section_position=21,
            phase_name="Lead",
            phase_slug="lead",
            celebration=(
                "You have completed the Lead phase.\n\n"
                "Four weeks of application. Of bringing the understanding from the earlier phases "
                "into real decisions, real relationships, and real creative expression.\n\n"
                "This is the work the other phases were preparing you for. "
                "And you showed up for it.\n\n"
                "One phase remains: Integration."
            ),
            reflection_prompt=(
                "* What is the most significant thing that shifted for you in the Lead phase?\n"
                "* Where did you lead more naturally — and where did old patterns pull you back?\n"
                "* What are you most proud of from this phase?\n"
                "* What do you want to carry consciously into the final Integration phase?"
            ),
        ))
        n += 1

        # ── Phase 5 — Integration ──
        sec5 = SECTION_IDS["phase-5"]

        all_steps += week_steps(
            start_n=n, pathway_id=PID, section_id=sec5, section_start=1,
            week_num=14, week_slug="manifestation-declaration",
            week_title="Manifestation + Declaration",
            theme="Bringing it all together — naming what has shifted and declaring what you are choosing",
            video_minutes=20,
            workbook_minutes=30,
            reflection_prompts=(
                "**Reflection prompts — Week 14: Manifestation + Declaration**\n\n"
                "* Who are you now, compared to who you were when you began this pathway?\n"
                "* What has genuinely shifted — in how you see yourself, how you lead, how you make decisions?\n"
                "* What are you declaring for the next season of your life?\n"
                "* What practice, rhythm, or commitment will you carry forward?\n"
                "* What do you want to return to — in this pathway, in the community, in yourself?\n\n"
                "*This is not an ending. It is a declaration of the life you are choosing — made with more clarity, more trust, more yourself.*"
            ),
            community_prompt=(
                "**Week 14 — Declaration**\n\n"
                "You made it through Life in Alignment.\n\n"
                "Share your declaration — one or two sentences about what you are choosing, "
                "committing to, or stepping into as you close this cycle.\n\n"
                "It might be big. It might be quiet. Both are exactly right."
            ),
        )
        n += 5

        # Final Integration Milestone
        all_steps.append(milestone_step(
            n=n, pathway_id=PID, section_id=sec5, section_position=6,
            phase_name="Final Integration",
            phase_slug="final-integration",
            celebration=(
                "## You have completed Life in Alignment.\n\n"
                "Fourteen weeks. Five phases. The full cycle of the R.E.A.L. Framework.\n\n"
                "You recognised what was running. You explored where it came from. "
                "You aligned with what was truer. You led — your decisions, your life, "
                "your relationships, your creativity.\n\n"
                "And now you integrate.\n\n"
                "This pathway does not close — it opens. The work you did here is yours for life. "
                "Come back to any phase, any week, any reflection whenever a new season asks it of you.\n\n"
                "**Welcome to the other side of survival mode.**"
            ),
            reflection_prompt=(
                "* What is the most important thing you learned about yourself in this pathway?\n"
                "* What does 'alignment' mean to you now — in your own words?\n"
                "* What are you returning to the world with, that you did not have when you began?\n"
                "* What is the next cycle — the next question — you are ready to bring to the R.E.A.L. Framework?"
            ),
        ))
        n += 1

        total_steps = n - 1
        print(f"  Total steps to seed: {total_steps}")

        for s in all_steps:
            obj, created = upsert(
                db, PathwayStep, s["id"], s["fields"],
                refresh_fields=REFRESH,
            )
            title = s["fields"]["title"]
            print(f"  [{'created' if created else 'updated'}] (pos {s['fields']['position']}) {title}")

        db.flush()

        # ── Part 4: Resources ──────────────────────────────────────────────
        print("\n── Part 4: Resources ──")

        from app.models.user import User as _User
        resources = [
            {
                "id": RESOURCE_IDS["nl-book"],
                "title": "The Natural Leader — Book",
                "description": (
                    "Lindsey's foundational book on natural leadership, the R.E.A.L. Framework, "
                    "and leading from alignment rather than performance. "
                    "A companion read for the full Life in Alignment pathway."
                ),
                "sort_order": 1,
            },
            {
                "id": RESOURCE_IDS["hd-chart-guide"],
                "title": "Human Design Chart Guide",
                "description": (
                    "A step-by-step guide to reading and understanding your Human Design BodyGraph. "
                    "Covers Type, Strategy, Authority, Profile, and how to use your chart "
                    "without overthinking it. Essential for Weeks 4 and 5."
                ),
                "sort_order": 2,
            },
            {
                "id": RESOURCE_IDS["healing-vortex"],
                "title": "Healing Vortex Meditation",
                "description": (
                    "A guided somatic meditation for nervous system regulation and coming back to yourself. "
                    "Use it during Week 6 (Nervous System) or any time you need to regulate and reset."
                ),
                "sort_order": 3,
            },
            {
                "id": RESOURCE_IDS["fem-archetypes"],
                "title": "Feminine Archetypes Guidebook",
                "description": (
                    "A guidebook exploring the feminine archetypes as a lens for understanding "
                    "your natural leadership style, your cycles, and your creative energy. "
                    "Supports Weeks 12 and 13."
                ),
                "sort_order": 4,
            },
            {
                "id": RESOURCE_IDS["qna-replays"],
                "title": "Monthly Q&A Replays",
                "description": (
                    "Recordings of the monthly live Q&A sessions for Life in Alignment members. "
                    "New replays are added each month. Watch in your own time."
                ),
                "sort_order": 5,
            },
        ]

        for r in resources:
            obj, created = upsert(db, SpaceResource, r["id"], {
                "space_id": SPACE_ID,
                "created_by_id": CREATOR_ID,
                "pathway_id": PID,
                "title": r["title"],
                "description": r["description"],
                "resource_type": "guide",
                "scope": "pathway",
                "status": "published",
                "sort_order": r["sort_order"],
                "created_at": SEED_TS,
                "updated_at": SEED_TS,
            }, refresh_fields=["title", "description", "sort_order"])
            print(f"  [{'created' if created else 'updated'}] {r['title']}")

        # ── Commit ─────────────────────────────────────────────────────────
        db.commit()

        print(f"""
✓  Life in Alignment pathway seeded successfully.

── Summary ────────────────────────────────────────────────────────────
  Pathway:    Life in Alignment (slug: life-in-alignment)
  Space:      The Grove ({SPACE_ID})
  Sections:   6  (Phase 0–5)
  Steps:      {total_steps}  (14 weeks × 5 + 5 milestones)
  Resources:  5

── Sections ───────────────────────────────────────────────────────────
  Phase 0 — Foundation      Week 1              (5 steps)
  Phase 1 — Recognise       Weeks 2–3 + milestone (11 steps)
  Phase 2 — Explore         Weeks 4–5 + milestone (11 steps)
  Phase 3 — Align           Weeks 6–9 + milestone (21 steps)
  Phase 4 — Lead            Weeks 10–13 + milestone (21 steps)
  Phase 5 — Integration     Week 14 + final milestone (6 steps)

── Step types ─────────────────────────────────────────────────────────
  Per week: Video · Workbook · Practice · Reflection · Community Prompt
  Per phase end: Milestone (text)

── Resources ──────────────────────────────────────────────────────────
  1. The Natural Leader — Book           [needs upload]
  2. Human Design Chart Guide            [needs upload]
  3. Healing Vortex Meditation           [needs upload]
  4. Feminine Archetypes Guidebook       [needs upload]
  5. Monthly Q&A Replays                 [add as replays are recorded]

── Placeholders requiring manual content ──────────────────────────────
  • 14 × teaching videos (video steps)
  • 14 × workbook PDFs (workbook steps)
  • 14 × practice instructions (exercise steps)
  • 5 × resource files (book, chart guide, meditation, archetypes, replays)

── Price ──────────────────────────────────────────────────────────────
  price_cents = None — set when Stripe checkout is ready.

── What was NOT changed ───────────────────────────────────────────────
  R.E.A.L. Journey, Human Design pathways, EMBODY, all other spaces.
""")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
