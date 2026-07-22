#!/usr/bin/env python3
"""
Restructures Life in Alignment pathway: 6 phase-based sections → 14 week-based sections.

What this script does:
  1. Renames existing 6 phase sections → Week 1–6 titles
  2. Creates 8 new sections for Weeks 7–14
  3. Reassigns every step's section_id and section_position
  4. Updates Week 5 video step to use 'Your Body's Feedback System' framing
  5. Updates Week 5 community prompt to match new framing

What this script does NOT do:
  - Delete any steps
  - Modify any step IDs, slugs, global position values, or content_body (except Week 5 video/community)
  - Touch any other pathway, space, or user data

Milestones are placed at the END of their phase's final week:
  ✦ Recognise Milestone  → Week 3, section_position 6
  ✦ Explore Milestone    → Week 5, section_position 6
  ✦ Align Milestone      → Week 9, section_position 6
  ✦ Lead Milestone       → Week 13, section_position 6
  ✦ Final Integration    → Week 14, section_position 6 (unchanged)

Usage:
    cd /home/lindsey/fc-production/backend
    .venv/bin/python ../scripts/restructure_lia_sections.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app.models.user      # noqa: F401
import app.models.platform  # noqa: F401

from app.core.database import SessionLocal
from app.models.platform import PathwaySection, PathwayStep

PATHWAY_ID = "pa000001-lia0-4000-8000-000000000001"
SEED_TS    = datetime(2026, 6, 19, 10, 0, 0)

# ── Section definitions ───────────────────────────────────────────────────────
# (id, title, position, action)  action: "rename" | "create"

SECTIONS = [
    ("se000001-lia0-4000-8000-000000000001", "Week 1 — Foundation: Start Where You Are",          1,  "rename"),
    ("se000001-lia0-4000-8000-000000000002", "Week 2 — Recognise: The Pattern",                    2,  "rename"),
    ("se000001-lia0-4000-8000-000000000003", "Week 3 — Recognise: The Conditioning",               3,  "rename"),
    ("se000001-lia0-4000-8000-000000000004", "Week 4 — Explore: Your Energy",                      4,  "rename"),
    ("se000001-lia0-4000-8000-000000000005", "Week 5 — Explore: Your Body's Feedback System",      5,  "rename"),
    ("se000001-lia0-4000-8000-000000000006", "Week 6 — Align: Understanding the Nervous System",   6,  "rename"),
    ("se000001-lia0-4000-8000-000000000007", "Week 7 — Align: Reconditioning",                     7,  "create"),
    ("se000001-lia0-4000-8000-000000000008", "Week 8 — Align: A Sustainable Container",            8,  "create"),
    ("se000001-lia0-4000-8000-000000000009", "Week 9 — Align: Integration & Rest",                 9,  "create"),
    ("se000001-lia0-4000-8000-000000000010", "Week 10 — Lead: Leading Your Decisions",             10, "create"),
    ("se000001-lia0-4000-8000-000000000011", "Week 11 — Lead: Leading Your Life",                  11, "create"),
    ("se000001-lia0-4000-8000-000000000012", "Week 12 — Lead: Leading Others",                     12, "create"),
    ("se000001-lia0-4000-8000-000000000013", "Week 13 — Lead: Leading from Creativity & Flow",     13, "create"),
    ("se000001-lia0-4000-8000-000000000014", "Week 14 — Integration: Manifestation & Declaration", 14, "create"),
]

# ── Step assignments ──────────────────────────────────────────────────────────
# Each entry: (global_position_range_or_single, section_index_1_14)
# section_position within each week: 1–5 for lesson steps, 6 for milestone

def _step_id(n: int) -> str:
    return f"st000001-lia0-4000-8000-{n:012d}"

def _sec_id(week: int) -> str:
    return f"se000001-lia0-4000-8000-{week:012d}"

# Build the full assignment table: step_id → (section_id, section_position)
ASSIGNMENTS: dict[str, tuple[str, int]] = {}

# Week 1 (steps 1–5), no milestone
for i, pos in enumerate(range(1, 6), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(1), i)

# Week 2 (steps 6–10), no milestone
for i, pos in enumerate(range(6, 11), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(2), i)

# Week 3 (steps 11–15) + Recognise Milestone (step 16)
for i, pos in enumerate(range(11, 16), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(3), i)
ASSIGNMENTS[_step_id(16)] = (_sec_id(3), 6)

# Week 4 (steps 17–21), no milestone
for i, pos in enumerate(range(17, 22), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(4), i)

# Week 5 (steps 22–26) + Explore Milestone (step 27)
for i, pos in enumerate(range(22, 27), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(5), i)
ASSIGNMENTS[_step_id(27)] = (_sec_id(5), 6)

# Week 6 (steps 28–32), no milestone
for i, pos in enumerate(range(28, 33), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(6), i)

# Week 7 (steps 33–37), no milestone
for i, pos in enumerate(range(33, 38), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(7), i)

# Week 8 (steps 38–42), no milestone
for i, pos in enumerate(range(38, 43), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(8), i)

# Week 9 (steps 43–47) + Align Milestone (step 48)
for i, pos in enumerate(range(43, 48), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(9), i)
ASSIGNMENTS[_step_id(48)] = (_sec_id(9), 6)

# Week 10 (steps 49–53), no milestone
for i, pos in enumerate(range(49, 54), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(10), i)

# Week 11 (steps 54–58), no milestone
for i, pos in enumerate(range(54, 59), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(11), i)

# Week 12 (steps 59–63), no milestone
for i, pos in enumerate(range(59, 64), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(12), i)

# Week 13 (steps 64–68) + Lead Milestone (step 69)
for i, pos in enumerate(range(64, 69), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(13), i)
ASSIGNMENTS[_step_id(69)] = (_sec_id(13), 6)

# Week 14 (steps 70–74) + Final Integration Milestone (step 75)
for i, pos in enumerate(range(70, 75), start=1):
    ASSIGNMENTS[_step_id(pos)] = (_sec_id(14), i)
ASSIGNMENTS[_step_id(75)] = (_sec_id(14), 6)

assert len(ASSIGNMENTS) == 75, f"Expected 75 assignments, got {len(ASSIGNMENTS)}"


# ── Week 5 content updates ────────────────────────────────────────────────────

WEEK5_VIDEO_BODY = (
    "*[Placeholder: Week 5 teaching video — Your Body's Feedback System. Upload to replace this placeholder.]*\n\n"
    "**Theme:** How your body signals alignment and misalignment — understanding your not-self themes, "
    "open centres, and conditioning signals so you can recognise when you are on or off track."
)

WEEK5_COMMUNITY_BODY = (
    "**Community Discussion — Week 5: Your Body's Feedback System**\n\n"
    "This week is about noticing what your body is actually telling you — and what is not yours.\n\n"
    "Share one moment this week where you caught yourself absorbing someone else's pressure, "
    "urgency, or expectation — and what it felt like when you noticed it.\n\n"
    "Or: what does misalignment feel like in your body for you? And what does alignment feel like?\n\n"
    "*Share as much or as little as feels right. There is no right answer — "
    "just what is true for you right now.*"
)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db = SessionLocal()
    try:
        print("── Step 1: Sections ──────────────────────────────────────────")

        section_renamed = 0
        section_created = 0

        for sec_id, title, position, action in SECTIONS:
            if action == "rename":
                sec = db.query(PathwaySection).filter_by(id=sec_id).first()
                if not sec:
                    print(f"  ERROR: Section {sec_id} not found — expected to exist. Aborting.")
                    db.rollback()
                    return
                old_title = sec.title
                sec.title = title
                sec.position = position
                print(f"  [renamed] {old_title!r} → {title!r}")
                section_renamed += 1
            else:  # create
                existing = db.query(PathwaySection).filter_by(id=sec_id).first()
                if existing:
                    existing.title = title
                    existing.position = position
                    print(f"  [exists]  {title!r} (already present, updated)")
                else:
                    sec = PathwaySection(
                        id=sec_id,
                        pathway_id=PATHWAY_ID,
                        title=title,
                        position=position,
                        created_at=SEED_TS,
                        updated_at=SEED_TS,
                    )
                    db.add(sec)
                    print(f"  [created] {title!r}")
                    section_created += 1

        db.flush()
        print(f"\n  Sections renamed: {section_renamed} | created: {section_created}")

        print("\n── Step 2: Step assignments ──────────────────────────────────")

        steps_updated = 0
        steps_unchanged = 0

        for step_id, (new_sec_id, new_sp) in ASSIGNMENTS.items():
            step = db.query(PathwayStep).filter_by(id=step_id).first()
            if not step:
                print(f"  ERROR: Step {step_id} not found. Aborting.")
                db.rollback()
                return

            changed = step.section_id != new_sec_id or step.section_position != new_sp
            if changed:
                step.section_id = new_sec_id
                step.section_position = new_sp
                steps_updated += 1
            else:
                steps_unchanged += 1

        db.flush()
        print(f"  Steps updated: {steps_updated} | already correct: {steps_unchanged}")

        print("\n── Step 3: Week 5 content rename ─────────────────────────────")

        # Video step (global pos 22 = _step_id(22))
        w5_video = db.query(PathwayStep).filter_by(id=_step_id(22)).first()
        if w5_video:
            w5_video.content_body = WEEK5_VIDEO_BODY
            print(f"  [updated] Week 5 Video — content_body updated to 'Your Body's Feedback System'")
        else:
            print("  WARNING: Week 5 video step not found")

        # Community prompt step (global pos 26 = _step_id(26))
        w5_community = db.query(PathwayStep).filter_by(id=_step_id(26)).first()
        if w5_community:
            w5_community.content_body = WEEK5_COMMUNITY_BODY
            print(f"  [updated] Week 5 Community Discussion — content_body updated")
        else:
            print("  WARNING: Week 5 community step not found")

        db.flush()

        # ── Verification ───────────────────────────────────────────────────
        print("\n── Step 4: Verification ──────────────────────────────────────")

        sections = (
            db.query(PathwaySection)
            .filter_by(pathway_id=PATHWAY_ID)
            .order_by(PathwaySection.position)
            .all()
        )

        for sec in sections:
            step_count = (
                db.query(PathwayStep)
                .filter_by(section_id=sec.id)
                .count()
            )
            print(f"  {sec.position:>2}. {sec.title:<55} ({step_count} steps)")

        total_steps = db.query(PathwayStep).filter_by(pathway_id=PATHWAY_ID).count()
        total_sections = len(sections)

        # Sanity: all steps should have a section_id
        unsectioned = (
            db.query(PathwayStep)
            .filter(
                PathwayStep.pathway_id == PATHWAY_ID,
                PathwayStep.section_id == None,  # noqa: E711
            )
            .count()
        )
        if unsectioned:
            print(f"\n  WARNING: {unsectioned} steps have no section_id!")
        else:
            print(f"\n  ✓ All {total_steps} steps have a section_id")

        db.commit()

        print(f"""
✓  Life in Alignment pathway restructured successfully.

── Final state ────────────────────────────────────────────────────────
  Sections:  {total_sections} (week-based)
  Steps:     {total_steps} (all preserved, zero deleted)
  Sections renamed:  {section_renamed}
  Sections created:  {section_created}
  Steps reassigned:  {steps_updated}
  Steps unchanged:   {steps_unchanged}

── What changed ───────────────────────────────────────────────────────
  Section titles:    All 6 renamed from Phase → Week format
  New sections:      8 created (Weeks 7–14)
  Step section_id:   Updated where needed
  Step section_pos:  Updated to 1–5 per week, 6 for milestones
  Week 5 video:      Placeholder text updated to 'Your Body's Feedback System'
  Week 5 community:  Discussion prompt updated to match new framing

── What was NOT changed ───────────────────────────────────────────────
  Step IDs:          Unchanged — zero impact on progress tracking
  Step slugs:        Unchanged
  Step global pos:   Unchanged (1–75)
  Step content:      Unchanged (except Week 5 video + community placeholders)
  R.E.A.L. Journey:  Untouched
  EMBODY:            Untouched
  All other spaces:  Untouched
""")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
