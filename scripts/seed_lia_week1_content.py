#!/usr/bin/env python3
"""
Seed Week 1 content for Life in Alignment from LIA_Week1_Foundation.docx.

Source: /home/lindsey/Downloads/LIA_Week1_Foundation.docx
Pathway: pa000001-lia0-4000-8000-000000000001 (Life in Alignment) — preserved
Section: se000001-lia0-4000-8000-000000000001 (Week 1) — preserved

Creates 6 learning-experience steps with rich content blocks (TipTap JSON).
Idempotent — safe to re-run; deletes prior Week 1 step blocks for the 6
deterministic step IDs and re-inserts them.

Does NOT touch:
  - Other weeks
  - Milestones (Recognise, Explore, Align, Lead, Final Integration)
  - Section metadata (title, position, banner)
  - Pathway record
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app.models.user      # noqa: F401
import app.models.platform  # noqa: F401

from app.core.database import SessionLocal
from app.models.platform import PathwaySection, PathwayStep, PathwayStepBlock

PATHWAY_ID = "pa000001-lia0-4000-8000-000000000001"
SECTION_ID = "se000001-lia0-4000-8000-000000000001"
SEED_TS = datetime(2026, 6, 21, 15, 0, 0)


# ── TipTap JSON helpers ───────────────────────────────────────────────────────

def t(s, *marks):
    n = {"type": "text", "text": s}
    if marks:
        n["marks"] = [{"type": m} for m in marks]
    return n

def b(s): return t(s, "bold")
def i(s): return t(s, "italic")

def p(*inlines):
    return {"type": "paragraph", "content": list(inlines)} if inlines else {"type": "paragraph"}

def h(level, s):
    return {"type": "heading", "attrs": {"level": level}, "content": [t(s)]}

def ul(*items):
    """Items: each may be a string OR a list of inline nodes."""
    li = []
    for item in items:
        inlines = [t(item)] if isinstance(item, str) else list(item)
        li.append({"type": "listItem", "content": [p(*inlines)]})
    return {"type": "bulletList", "content": li}

def doc(*nodes):
    return json.dumps({"type": "doc", "content": list(nodes)})


# ── Step IDs (deterministic) ──────────────────────────────────────────────────

def step_id(n: int) -> str:
    return f"st000001-w1a0-4000-8000-{n:012d}"

def block_id(step_n: int, pos: int) -> str:
    return f"bl000001-w1a0-4000-{step_n:04d}-{pos:012d}"


# ── Step + block definitions ──────────────────────────────────────────────────

NEUTRINO_URL = "https://www.neutrinohumandesign.com/get-your-free-chart-now/"

STEPS = [
    # ─────────────────────────────────────────────────────────────────────────
    # Step 1 — Welcome to Life in Alignment
    # ─────────────────────────────────────────────────────────────────────────
    {
        "n": 1,
        "slug": "welcome-to-life-in-alignment",
        "title": "Welcome to Life in Alignment",
        "content_type": "text",
        "estimated_minutes": 8,
        "blocks": [
            # Week 1 at a glance
            ("heading", {"content": "Week 1 at a Glance", "label": "h2"}),
            ("callout", {
                "label": "tip",
                "content": doc(
                    p(b("Videos: "), t("Welcome video (3–4 min) · R.E.A.L. orientation (5–6 min) — to be added")),
                    p(b("Reading: "), t("The R.E.A.L. Framework: why the order matters")),
                    p(b("Tool: "), t("Pull your Human Design chart + read the HD orientation guide")),
                    p(b("Daily practice: "), t("Coming Home audio — 5 minutes every day (audio to be added)")),
                    p(b("Community: "), t("Introduce yourself in The Grove")),
                    p(b("Time needed: "), t("60–90 minutes total this week + 5 minutes daily")),
                    p(b("This week's intention: "), t("Arrive. Orient. Begin listening.")),
                ),
            }),
            # Intention
            ("heading", {"content": "Your intention this week", "label": "h2"}),
            ("text", {"content": doc(
                p(t("This week has one job: help you arrive. There is nothing to fix, analyse, or figure out yet. Your only tasks are to orient yourself, pull your Human Design chart, and begin one simple daily practice. That's it. The work starts next week. This week you land.")),
            )}),
            # Welcome
            ("heading", {"content": "Welcome", "label": "h2"}),
            ("text", {"content": doc(
                p(t("If you're anything like most of the women who arrive here, you're carrying a lot.")),
                p(t("Maybe you're exhausted in a way that sleep doesn't fix. Maybe you've tried things before — read the books, done the courses, had moments of real clarity — and something still hasn't shifted. Maybe you just know, somewhere in your body, that the way you've been living isn't sustainable. And you're quietly hoping this might be the thing that actually helps.")),
                p(t("I want you to know: that hope is not naive. It's information. It's your body telling you something true.")),
                p(t("Life in Alignment exists because I needed it. Not as a concept. As a lived experience. I spent years in patterns I could see clearly but couldn't seem to break — even when I understood them, even when I knew better, even when I'd had every insight available to me. What eventually changed wasn't a new strategy or a better framework. It was working with the right things in the right order. And doing the one thing most programmes skip: actually involving my body in the process.")),
                p(t("That's what this programme is built on. And over the next 14 weeks, that's what we're going to do together.")),
                p(t("But not yet. This week you arrive. That's enough.")),
            )}),
            # Video placeholder
            ("callout", {
                "label": "warning",
                "content": doc(
                    p(b("[ VIDEO PLACEHOLDER ]")),
                    p(t("Welcome video (3–4 min) — Lindsey speaking directly to camera. Warm, direct, meeting her where she is. Replace this placeholder when recorded.")),
                ),
            }),
        ],
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2 — The R.E.A.L. Framework
    # ─────────────────────────────────────────────────────────────────────────
    {
        "n": 2,
        "slug": "the-real-framework",
        "title": "The R.E.A.L. Framework",
        "content_type": "text",
        "estimated_minutes": 15,
        "blocks": [
            ("heading", {"content": "Why the order matters — and how it came to be", "label": "h2"}),
            ("text", {"content": doc(
                p(t("I want to tell you where this framework came from before I explain what it is. Because it didn't come from research. It came from my own life.")),
                p(t("For years, I was the woman who held everything together. A demanding corporate career. A business I was building on the side. Responsibilities I took seriously. Standards I held myself to. And underneath all of it — a level of exhaustion that never really lifted, no matter what I did.")),
                p(t("The frustrating part wasn't the exhaustion. It was that I could see the patterns. I knew I was overriding myself. I knew I was saying yes when I meant no. I had enough self-awareness to write a book about it — and I did. But knowing and actually living differently? For a long time, those were completely separate things.")),
                p(t("What eventually shifted wasn't another insight. It was learning to work with things in a different order. To stop trying to lead my way out of patterns I hadn't yet looked at honestly. To stop trying to change before I understood how I was actually designed to work. And to stop skipping the part where my body felt safe enough to hold something new.")),
                p(t("That sequence is R.E.A.L. And the order is not optional — because each stage creates the foundation the next one needs.")),
            )}),
            ("callout", {
                "label": "warning",
                "content": doc(
                    p(b("[ VIDEO PLACEHOLDER ]")),
                    p(t("R.E.A.L. orientation video (5–6 min) — Lindsey walking through the framework grounded in her own story. Replace this placeholder when recorded.")),
                ),
            }),
            ("heading", {"content": "The four stages", "label": "h2"}),

            # R
            ("callout", {
                "label": "info",
                "content": doc(
                    p(b("R — RECOGNISE")),
                    p(i("See clearly what's actually happening — without self-blame.")),
                    p(t("Most of us live in patterns we can't fully see because they feel like reality. The way we work, the things we take on, the ways we override ourselves — these don't feel like choices. They feel like just the way things are.")),
                    p(t("Recognise is about creating enough distance to see the pattern. To name what's actually happening in your life, your body, and your behaviour — not through a lens of blame or shame, but with honest, clear-eyed curiosity.")),
                    p(t("This is where we start. Not because it's easy. Because without it, everything else is built on ground that isn't solid.")),
                ),
            }),
            # E
            ("callout", {
                "label": "info",
                "content": doc(
                    p(b("E — EXPLORE")),
                    p(i("Understand how you actually work — through your design, not someone else's map.")),
                    p(t("Once you can see what's happening, the next question is why. Not in a blaming, fault-finding way. But genuinely — where did these patterns come from, and how are you actually designed to work?")),
                    p(t("This is where Human Design comes in. Not as a rigid system or a personality label, but as a mirror. A way of understanding your own energy, your decision-making, your natural rhythms, and the specific ways you've been conditioned away from them.")),
                    p(t("Explore is the stage where you stop trying to fix yourself against someone else's template and start understanding your own.")),
                ),
            }),
            # A
            ("callout", {
                "label": "info",
                "content": doc(
                    p(b("A — ALIGN")),
                    p(i("Create the internal safety that makes real change possible.")),
                    p(t("This is the stage most programmes skip entirely. And it's the reason most change doesn't last.")),
                    p(t("You can recognise your patterns and understand your design — and still find yourself unable to sustain anything different. Not because you lack commitment or discipline. Because your nervous system doesn't yet feel safe enough to live in a new way. Change that bypasses the body doesn't stick. It might work on pure effort for a while. But eventually the system pulls you back to what feels familiar — even when familiar means exhausted and out of alignment.")),
                    p(t("Align is the bridge between knowing and living differently. It's the phase most people need most and get least.")),
                ),
            }),
            # L
            ("callout", {
                "label": "info",
                "content": doc(
                    p(b("L — LEAD")),
                    p(i("Lead your own life — from the inside out.")),
                    p(t("Lead is where everything comes together. Not as a performance or a set of strategies to implement. But as the natural expression of a woman who knows herself, trusts herself, and has built a life that actually fits.")),
                    p(t("This looks different for every woman who arrives here. But it always has the same quality: it comes from the inside out, not the outside in. From your own authority, not from external pressure or expectation.")),
                    p(t("This is where we're headed. Everything that comes before it is how we get there.")),
                ),
            }),
            ("divider", {}),
            ("callout", {
                "label": "tip",
                "content": doc(
                    p(b("Before you move on — one thing to know")),
                    p(t("The urge to rush will come. Especially in the early weeks, when the content feels like preparation and you're ready to get to the \u201Creal stuff\u201D.")),
                    p(t("Name that urge now, so you can recognise it when it arrives.")),
                    p(b("The preparation is the real stuff. Trust the sequence.")),
                ),
            }),
        ],
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3 — Your Human Design Chart
    # ─────────────────────────────────────────────────────────────────────────
    {
        "n": 3,
        "slug": "your-human-design-chart",
        "title": "Your Human Design Chart",
        "content_type": "text",
        "estimated_minutes": 25,
        "blocks": [
            ("text", {"content": doc(
                p(t("Your Human Design chart is one of the most important tools in this programme. It is not a personality test or a label to slot yourself into. It is a map — of how you're designed to make decisions, where you're most susceptible to conditioning, and how you're meant to move through the world with less resistance.")),
                p(t("You'll begin working with it in Week 2. This week, your job is to pull it and get familiar with what you're looking at.")),
            )}),

            # Step 1 — pull your chart
            ("heading", {"content": "Step 1 — Pull your chart", "label": "h2"}),
            ("text", {"content": doc(
                p(t("You'll need three things:")),
                ul(
                    "Your date of birth",
                    "Your exact time of birth (check your birth certificate if you're not sure — the time matters)",
                    "Your place of birth",
                ),
                p(t("If you genuinely can't find your birth time, use midday as a placeholder — but note that some elements of your chart, particularly your Authority, may not be fully accurate without it. It's worth trying to find it.")),
            )}),
            ("callout", {
                "label": "warning",
                "content": doc(
                    p(b("[ TOOL PLACEHOLDER ]")),
                    p(t("Neutrino Human Design chart tool — embedded here on the platform page (allowlisted embed pending). For now, use the button below.")),
                ),
            }),
            ("button", {
                "label": "Open Human Design Chart Tool",
                "embed_url": NEUTRINO_URL,
                "caption": "primary",
                "content": "new_tab",
            }),

            # Step 2 — read the orientation guide
            ("heading", {"content": "Step 2 — Read the HD orientation guide", "label": "h2"}),
            ("text", {"content": doc(
                p(t("Once you have your chart, read through the guide below before watching anything else. It gives you the vocabulary you need to make sense of what you're looking at.")),
            )}),

            ("heading", {"content": "Human Design — Orientation Guide", "label": "h2"}),
            ("heading", {"content": "What Human Design actually is", "label": "h3"}),
            ("text", {"content": doc(
                p(t("Human Design is a system that maps how you're designed to operate — your energy type, how you're meant to make decisions, where you're consistent and where you're susceptible to outside influence. It draws on elements of astrology, the I Ching, the Kabbalah, and the chakra system, but you don't need to know any of that. What matters is the practical layer: how does this help you understand yourself?")),
            )}),

            ("heading", {"content": "The four things to find on your chart this week", "label": "h3"}),
            ("text", {"content": doc(
                p(t("You don't need to understand your whole chart right now. Find these four things and write them down somewhere accessible — you'll need them from Week 2 onward.")),
                ul(
                    [b("Your Type "), t("— one of five: Generator, Manifesting Generator, Projector, Manifestor, or Reflector")],
                    [b("Your Strategy "), t("— the sentence that describes how your type is designed to move through life")],
                    [b("Your Authority "), t("— your internal decision-making system")],
                    [b("Your Not-Self theme "), t("— the emotional signal that tells you you're off track")],
                ),
            )}),

            ("heading", {"content": "A brief guide to the five Types", "label": "h3"}),
            ("text", {"content": doc(
                p(b("Generator")),
                p(t("The most common type — around 37% of people. Generators have a defined Sacral centre, which means they have consistent, sustainable life-force energy. Their strategy is to respond — to wait for something in the external world to light them up before committing. Their not-self theme is frustration, which shows up when they're initiating rather than responding, or saying yes to things that don't genuinely light them up.")),
                p(b("Manifesting Generator")),
                p(t("Also common — around 33% of people. Manifesting Generators are a hybrid type: they have the Sacral energy of a Generator combined with a motor connected to the Throat, giving them a faster, more multi-passionate energy. Their strategy is to respond and then inform before acting. Their not-self theme is also frustration (and sometimes anger). They often struggle with being told to slow down or focus on one thing — because they're genuinely designed for breadth and speed.")),
                p(b("Projector")),
                p(t("Around 20% of people. Projectors do not have consistent access to the Sacral energy of Generators — they're designed to work in focused bursts and then genuinely rest. Their strategy is to wait for recognition and invitation before sharing their guidance or taking on major roles. Their not-self theme is bitterness, which shows up when they're pushing to be seen or working without invitation. Projectors often over-function because they're surrounded by Generator energy and have learned to match it — at great cost.")),
                p(b("Manifestor")),
                p(t("Around 9% of people. Manifestors are the only type truly designed to initiate — to start things without waiting for external cues. Their strategy is to inform the people who will be affected by their actions before they act. Their not-self theme is anger, which shows up when they feel controlled or have to ask permission. Manifestors often carry a deep sense of needing to do things their own way — because they actually do.")),
                p(b("Reflector")),
                p(t("The rarest type — around 1% of people. Reflectors have no defined centres, which means they're highly sensitive to the people and environments around them. Their strategy is to wait a full lunar cycle (28 days) before making major decisions, giving themselves time to experience a situation from all its angles. Their not-self theme is disappointment. Reflectors are often deeply wise about the communities they're part of — they can sense the health of a group in a way no other type can.")),
            )}),

            ("heading", {"content": "A brief guide to Authority", "label": "h3"}),
            ("text", {"content": doc(
                p(t("Your Authority is your internal decision-making system — the part of you that actually knows, beneath the noise of your mind. Here are the main Authorities:")),
                ul(
                    [b("Emotional Authority"), t(" — you need time before deciding. The emotional wave moves through you and clarity comes after the peak and the valley. Never decide in the high or the low. Wait until you feel neutral.")],
                    [b("Sacral Authority"), t(" — you have an immediate gut response. A full-body yes feels like expansion or a sound from the belly. A no feels flat or like contraction. This is fast and visceral, not mental.")],
                    [b("Splenic Authority"), t(" — a quiet, instant knowing in the moment. It speaks once and doesn't repeat itself. Often described as a whisper or a subtle body sensation. It won't remind you.")],
                    [b("Ego / Heart Authority"), t(" — decisions land when you can feel your heart in them. You know when something is genuinely worth your will and resources, and when it isn't.")],
                    [b("Self-Projected Authority"), t(" — you find clarity by talking things through out loud. The truth emerges in the speaking, not in the thinking. Talk to people you trust.")],
                    [b("Mental / Environmental Authority"), t(" — you need to move through different environments and talk things through with others. Clarity comes from observing how you respond across contexts, not from an internal signal.")],
                    [b("Lunar Authority (Reflectors only)"), t(" — you wait a full lunar cycle before major decisions, sampling how something feels across 28 days and different environments.")],
                ),
                p(t("You don't need to fully understand your Authority yet. Just find yours on your chart and keep it in mind. We'll work with it properly in Week 4.")),
            )}),

            # Step 3 — watch HD basics video
            ("heading", {"content": "Step 3 — Watch the HD basics overview", "label": "h2"}),
            ("text", {"content": doc(
                p(t("Once you've read the guide above and found your four key elements, watch the video below for a visual walkthrough of the chart itself — what the shapes mean, where to find things, and how to read the basic layout.")),
            )}),
            ("callout", {
                "label": "warning",
                "content": doc(
                    p(b("[ VIDEO PLACEHOLDER ]")),
                    p(t("Existing HD basics video — link or embed here. Lindsey's walkthrough of how to read a Human Design chart.")),
                ),
            }),
        ],
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4 — Coming Home Practice
    # ─────────────────────────────────────────────────────────────────────────
    {
        "n": 4,
        "slug": "coming-home-practice",
        "title": "Coming Home Practice",
        "content_type": "exercise",
        "estimated_minutes": 10,
        "blocks": [
            ("text", {"content": doc(
                p(b("This is your anchor for the entire 14 weeks.")),
                p(t("Not because it's complicated. Because it's consistent. One of the things this programme asks of you — gently, from the very first week — is that you begin to treat your body as a source of information rather than an obstacle to manage. The Coming Home practice is how you start doing that, five minutes at a time.")),
                p(t("It is a simple body check-in. A practice of arriving in your own body, noticing what's there, and asking what you need. That's it.")),
            )}),
            ("callout", {
                "label": "warning",
                "content": doc(
                    p(b("[ AUDIO PLACEHOLDER ]")),
                    p(t("Coming Home guided audio — embed here. Lindsey's existing body check-in practice.")),
                ),
            }),

            ("heading", {"content": "How to use this practice", "label": "h2"}),
            ("exercise", {"content": doc(
                ul(
                    "Listen once through before you begin using it daily, so you know what to expect",
                    "From Day 2 onward, press play each morning or evening — whichever works better for your life",
                    "You don't need a special space. Your desk, your car, your bed. Wherever you can have five minutes",
                    "If you miss a day, don't make it mean anything. Just come back the next day",
                ),
            )}),

            ("heading", {"content": "What you're building", "label": "h2"}),
            ("text", {"content": doc(
                p(t("Right now this might feel like a small, simple thing. It is. That's intentional.")),
                p(t("What you're building, five minutes at a time, is a relationship with your own body's signals. By the time you reach the Align phase in Week 6, that relationship becomes one of your most important tools. You'll understand your own nervous system, your own patterns of tension and release, your own early warning signals — because you've been paying attention to them since Day 1.")),
                p(t("That doesn't happen through one big practice. It happens through a small, consistent one.")),
                p(b("Begin today.")),
            )}),

            ("heading", {"content": "The three questions", "label": "h2"}),
            ("text", {"content": doc(
                p(t("If you ever do the practice without the audio — or want to carry it with you in daily life — these are the three questions at the heart of it:")),
            )}),
            ("reflection_prompt", {"content": doc(
                ul(
                    "Where am I holding tension right now?",
                    "What is my body saying today?",
                    "What do I need — and am I giving it to myself?",
                ),
                p(t("You don't need to fix what you notice. You just need to notice.")),
            )}),
        ],
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5 — Your First Step in The Grove
    # ─────────────────────────────────────────────────────────────────────────
    {
        "n": 5,
        "slug": "your-first-step-in-the-grove",
        "title": "Your First Step in The Grove",
        "content_type": "text",
        "estimated_minutes": 5,
        "blocks": [
            ("text", {"content": doc(
                p(t("The Grove is your community space throughout Life in Alignment. It's where you'll share, ask questions, connect with other women on the same journey, and find Lindsey for live Q&A sessions.")),
                p(t("This week, there's one simple thing to do there.")),
            )}),

            ("heading", {"content": "Week 1 Community Prompt", "label": "h2"}),
            ("callout", {
                "label": "tip",
                "content": doc(
                    p(t("Head to The Grove and introduce yourself with the following prompt:")),
                    p(t("Share your name, where you're joining from, and finish this sentence:")),
                    p(b("\u201CI joined Life in Alignment because…\u201D")),
                ),
            }),
            ("text", {"content": doc(
                p(t("A few honest sentences is perfect. No need to write an essay. You're not performing — you're just arriving, the same as everyone else here.")),
            )}),
            ("callout", {
                "label": "info",
                "content": doc(
                    p(t("Lindsey will post her own response first, so you'll have a sense of the tone before you write yours.")),
                ),
            }),
            ("text", {"content": doc(
                p(t("The Grove is not a place to show how together you are. It is a place to be honest about where you actually are. The more real you are from Day 1, the more you'll get from this community throughout the programme.")),
            )}),
            ("button", {
                "label": "Open The Grove community",
                "embed_url": "/spaces/the-natural-leader-hub/community",
                "caption": "primary",
                "content": "same_tab",
            }),
        ],
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Step 6 — Before You Move to Week 2
    # ─────────────────────────────────────────────────────────────────────────
    {
        "n": 6,
        "slug": "before-you-move-to-week-2",
        "title": "Before You Move to Week 2",
        "content_type": "reflection",
        "estimated_minutes": 5,
        "blocks": [
            ("text", {"content": doc(
                p(t("Check that you've done these five things before moving on. None of them need to be perfect. They just need to be done.")),
            )}),
            ("exercise", {"content": doc(
                ul(
                    "Read the programme overview and the R.E.A.L. orientation (this document)",
                    "Pulled your Human Design chart and noted your Type, Strategy, Authority, and Not-Self theme",
                    "Watched the HD basics video",
                    "Listened to the Coming Home audio at least once, and begun your daily practice",
                    "Introduced yourself in The Grove",
                ),
            )}),

            ("heading", {"content": "A note before you begin Week 2", "label": "h2"}),
            ("text", {"content": doc(
                p(t("Week 2 is where the real work begins. You're going to be asked to look honestly at what's actually happening in your life — not what should be happening, not what you hope is happening. What's actually happening.")),
                p(t("That can feel confronting. It can also feel like the biggest relief you've had in years. For most women it's both.")),
                p(b("Come as you are. That's always been enough.")),
            )}),
        ],
    },
]


# ── Seeding ───────────────────────────────────────────────────────────────────

def main():
    db = SessionLocal()
    try:
        # Sanity
        section = db.query(PathwaySection).filter_by(id=SECTION_ID).first()
        if not section:
            print(f"ERROR: section {SECTION_ID} not found. Aborting.")
            return
        print(f"Section: {section.title}  ({section.id})")
        print(f"Pathway: {PATHWAY_ID}")
        print()

        # For idempotency: delete any existing rows under our deterministic IDs
        # (does not touch milestones or other sections).
        our_step_ids = [step_id(s["n"]) for s in STEPS]
        deleted_blocks = (
            db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id.in_(our_step_ids))
            .delete(synchronize_session=False)
        )
        deleted_steps = (
            db.query(PathwayStep)
            .filter(PathwayStep.id.in_(our_step_ids))
            .delete(synchronize_session=False)
        )
        if deleted_blocks or deleted_steps:
            print(f"Cleared previous run: {deleted_steps} steps, {deleted_blocks} blocks")
        db.flush()

        # Insert steps + blocks
        for s in STEPS:
            sid = step_id(s["n"])
            step = PathwayStep(
                id=sid,
                pathway_id=PATHWAY_ID,
                section_id=SECTION_ID,
                slug=s["slug"],
                title=s["title"],
                content_type=s["content_type"],
                content_body=None,                  # all content lives in blocks
                content_url=None,
                estimated_minutes=s["estimated_minutes"],
                is_required=False,
                position=s["n"],                    # 1..6 — Week 1 lives at the top
                section_position=s["n"],            # 1..6 inside the section
                reflection_enabled=True,
                discussion_enabled=True,
                created_at=SEED_TS,
                updated_at=SEED_TS,
            )
            db.add(step)
            print(f"  [step {s['n']}] {s['title']}")

            for pos, (btype, fields) in enumerate(s["blocks"]):
                block = PathwayStepBlock(
                    id=block_id(s["n"], pos),
                    step_id=sid,
                    block_type=btype,
                    position=pos,
                    content=fields.get("content"),
                    label=fields.get("label"),
                    caption=fields.get("caption"),
                    embed_url=fields.get("embed_url"),
                    media_asset_id=None,
                    created_at=SEED_TS,
                    updated_at=SEED_TS,
                )
                db.add(block)
            print(f"    + {len(s['blocks'])} blocks")

        db.commit()

        print()
        print("✓ Week 1 content seeded successfully.")
        print()
        print("── Final Week 1 step list ─────────────────────────────────────")
        for s in STEPS:
            print(f"  {s['n']}. {s['title']:<40}  ({s['content_type']:<10}, ~{s['estimated_minutes']} min, {len(s['blocks'])} blocks)")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
