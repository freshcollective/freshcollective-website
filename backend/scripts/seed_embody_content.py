"""
Idempotent seed script for EMBODY pathway content.

Inserts or updates:
  - PathwayAboutBlock records for embody-in-person-sessions
  - PathwayStepBlock records for all 10 EMBODY steps

Run from the backend directory:
    .venv/bin/python scripts/seed_embody_content.py

Safe to run multiple times — checks for existing blocks before inserting.
Does NOT update payment options or event records (managed via creator UI).
"""
import sys
import uuid
sys.path.insert(0, '.')

from app.db.session import SessionLocal
from app.models.user import User  # noqa: F401 — registers mapper before platform models
from app.models import platform

PATHWAY_SLUG = "embody-in-person-sessions"

# ── About blocks ─────────────────────────────────────────────────────────────
ABOUT_BLOCKS = [
    # (position, block_type, content)
    (0, "heading", "An in-person movement and somatic practice for women."),
    (1, "text",
     "EMBODY is not a bootcamp. It is not about pushing through, performing, or earning your place.\n\n"
     "Each session blends movement activation, breathwork, strength, decompression and nervous system recalibration. "
     "You will be guided the whole way. You can modify, pause, or rest at any point — this is your practice.\n\n"
     "You do not need to be fit, experienced, or ready. You just need to show up."),
    (2, "heading", "Sessions"),
    (3, "text",
     "Sessions run **Monday evenings, Thursday evenings and Saturday mornings** in South Croydon, Victoria.\n\n"
     "Each session is 60 minutes and runs in a small group to keep the space intimate. "
     "The full address is shared directly after enrolment."),
    (4, "heading", "Term dates"),
    (5, "text", "The current term runs from **13 July to 19 September 2026**."),
    (6, "heading", "Choose your pass"),
    (7, "text",
     "**Awaken** — 1 session per week · 10 sessions · $200 AUD ($20 per session)\n\n"
     "**Activate** — 2 sessions per week · 20 sessions · $340 AUD ($17 per session)\n\n"
     "**Empower** — 3 sessions per week · 30 sessions · $420 AUD ($14 per session)\n\n"
     "Pay in full only. Payment plans are not available for this term."),
    (8, "heading", "After joining"),
    (9, "text",
     "Once your pass is active, you can book sessions yourself from the Gatherings page, "
     "or message Lindsey with your preferred regular session day/s and she will book your regular sessions for the term.\n\n"
     "You are not locked into a specific day or time. You can attend on whichever days suit you each week."),
]

# ── Step blocks ───────────────────────────────────────────────────────────────
STEP_BLOCKS = {
    "welcome": [
        ("heading", "Welcome to EMBODY."),
        ("text",
         "This pathway is your guide to everything you need to know as an EMBODY member — "
         "how sessions work, how to book, what to bring, and how to get the most from your term.\n\n"
         "Take a read through when you are ready. You do not need to complete this in one sitting."),
    ],
    "what-embody-is": [
        ("heading", "What EMBODY is."),
        ("text",
         "EMBODY is an in-person movement and somatic practice for women.\n\n"
         "Each session blends movement activation, breathwork, strength, decompression and nervous system recalibration. "
         "The work is layered — physical and felt, structured and responsive.\n\n"
         "This is not a fitness class. This is not performance. This is your body, your practice, your pace.\n\n"
         "You are guided every step of the way. Modifications are always available. "
         "You can rest, pause, or move in a way that feels right for your body on the day."),
    ],
    "what-to-expect": [
        ("heading", "What to expect in a session."),
        ("text",
         "Sessions run for 60 minutes in a small group setting.\n\n"
         "You can expect a blend of:\n"
         "- Movement activation and warm-up\n"
         "- Strength and embodied movement\n"
         "- Breathwork\n"
         "- Decompression and nervous system recalibration\n"
         "- A few minutes of stillness or reflection at the close\n\n"
         "The group is intentionally small to keep the space intimate and supportive. "
         "There is no competition, no comparison. Just your practice."),
    ],
    "what-to-bring": [
        ("heading", "What to bring."),
        ("text",
         "Wear comfortable clothes you can move in — stretchy, breathable, whatever feels good.\n\n"
         "Bring:\n"
         "- A water bottle\n"
         "- Grip socks or bare feet (you will not need shoes during the session)\n"
         "- A small towel if you like\n\n"
         "Everything else is provided. You do not need to bring a mat.\n\n"
         "Arrive a few minutes early if you can, especially for your first session."),
    ],
    "how-to-book": [
        ("heading", "How to book your sessions."),
        ("text",
         "Once your pass is active, you have two options:\n\n"
         "**Book yourself** — Go to the Gatherings page and book the sessions that suit you each week. "
         "You can book as many sessions per week as your pass allows.\n\n"
         "**Message Lindsey** — If you would like to lock in the same session/s each week for the full term, "
         "message Lindsey with your preferred day/s and she will book your regular sessions for you.\n\n"
         "You are not locked into a specific day or time. You can mix and match each week based on what works for you.\n\n"
         "**Your location** — The full address and any session-specific details will be sent directly by Lindsey "
         "after your first booking is confirmed."),
    ],
    "how-your-pass-works": [
        ("heading", "How your term pass works."),
        ("text",
         "Your pass gives you a set number of sessions to use across the term — "
         "13 July to 19 September 2026.\n\n"
         "**Awaken** — 1 session per week, 10 sessions total\n"
         "**Activate** — 2 sessions per week, 20 sessions total\n"
         "**Empower** — 3 sessions per week, 30 sessions total\n\n"
         "Your sessions are valid until **19 September 2026**. Unused sessions do not roll over to the next term "
         "unless agreed separately with Lindsey.\n\n"
         "Your weekly allowance resets each week — you cannot carry unused sessions forward week to week beyond your pass total."),
    ],
    "cancellation-policy": [
        ("heading", "Cancellation policy."),
        ("text",
         "**Cancelling a booking** — Cancel at least 12 hours before the session and your session will be "
         "restored to your pass so you can rebook.\n\n"
         "**Late cancellations and no-shows** — Cancellations within 12 hours of the session, or not showing up, "
         "will use your session. We are not able to restore sessions in these cases.\n\n"
         "**If Lindsey cancels** — If a session is cancelled by Lindsey, your session will always be restored to your pass.\n\n"
         "If something unexpected comes up, please reach out as soon as you can. "
         "Lindsey will always do her best to work with you where possible."),
    ],
    "home-practice": [
        ("heading", "Between sessions."),
        ("text",
         "Your in-person sessions are the foundation. What happens between them matters too.\n\n"
         "The **Home Practice** pathway is available to you as part of your membership. "
         "It includes movement sequences, breathwork practices and somatic exercises you can do in your own time and space — "
         "no equipment needed, no set schedule.\n\n"
         "Home practice is not compulsory. It is here when you want it, and it builds on what you explore in sessions.\n\n"
         "Find it in the Pathways section of your EMBODY space."),
    ],
    "health-and-injury": [
        ("heading", "Health and injuries."),
        ("text",
         "Your wellbeing is the priority.\n\n"
         "If you have an injury, a health condition, or anything that might affect how you move, "
         "please let Lindsey know before your first session. A quick message is enough — "
         "you do not need a full medical history, just anything relevant to how you move and feel in your body.\n\n"
         "Modifications are always available. You can pause, rest, or skip any part of any session at any time. "
         "There is no expectation to push through.\n\n"
         "If something comes up during a session, let Lindsey know and she will adjust.\n\n"
         "By attending sessions, you acknowledge that you are responsible for your own body and will communicate anything "
         "relevant to your safety and participation."),
    ],
    "questions-and-contact": [
        ("heading", "Questions or need to reach out?"),
        ("text",
         "Lindsey is the best person to contact for anything EMBODY-related — bookings, questions, feedback, or anything personal.\n\n"
         "You can message her directly through the platform, or reach out however feels right to you.\n\n"
         "Response times may vary, but she will always get back to you.\n\n"
         "See you in the space."),
    ],
}


def seed():
    db = SessionLocal()
    try:
        Pathway = platform.Pathway
        PathwayAboutBlock = platform.PathwayAboutBlock
        PathwayStep = platform.PathwayStep
        PathwayStepBlock = platform.PathwayStepBlock

        pathway = db.query(Pathway).filter(Pathway.slug == PATHWAY_SLUG).first()
        if not pathway:
            print(f"ERROR: Pathway '{PATHWAY_SLUG}' not found.")
            return

        print(f"Pathway: {pathway.title} (id={pathway.id})")

        # ── About blocks ──────────────────────────────────────────────────────
        existing_about = db.query(PathwayAboutBlock).filter(
            PathwayAboutBlock.pathway_id == pathway.id
        ).count()

        if existing_about == len(ABOUT_BLOCKS):
            print(f"About blocks: {existing_about} already exist — skipping.")
        else:
            # Delete and recreate (idempotent replacement)
            db.query(PathwayAboutBlock).filter(
                PathwayAboutBlock.pathway_id == pathway.id
            ).delete()
            for pos, block_type, content in ABOUT_BLOCKS:
                block = PathwayAboutBlock(
                    id=str(uuid.uuid4()),
                    pathway_id=pathway.id,
                    position=pos,
                    block_type=block_type,
                    content=content,
                )
                db.add(block)
            db.commit()
            print(f"About blocks: inserted {len(ABOUT_BLOCKS)}.")

        # ── Step blocks ───────────────────────────────────────────────────────
        steps = db.query(PathwayStep).filter(
            PathwayStep.pathway_id == pathway.id
        ).all()
        step_by_slug = {s.slug: s for s in steps}

        total_inserted = 0
        total_skipped = 0

        for slug, blocks in STEP_BLOCKS.items():
            step = step_by_slug.get(slug)
            if not step:
                print(f"  WARN: step '{slug}' not found — skipping.")
                continue

            existing = db.query(PathwayStepBlock).filter(
                PathwayStepBlock.step_id == step.id
            ).count()

            if existing == len(blocks):
                total_skipped += 1
                continue

            # Replace blocks for this step
            db.query(PathwayStepBlock).filter(
                PathwayStepBlock.step_id == step.id
            ).delete()
            for pos, (block_type, content) in enumerate(blocks):
                block = PathwayStepBlock(
                    id=str(uuid.uuid4()),
                    step_id=step.id,
                    position=pos,
                    block_type=block_type,
                    content=content,
                )
                db.add(block)
            db.commit()
            total_inserted += 1
            print(f"  Step '{slug}': inserted {len(blocks)} blocks.")

        if total_skipped:
            print(f"  {total_skipped} step(s) already had correct block count — skipped.")

        print("\nSeed complete.")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
