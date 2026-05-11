"""Seed REAL Journey steps and make step_progress.completed_at nullable.

Revision ID: 004
Revises: 003
Create Date: 2026-05-11

Changes:
  1. ALTER step_progress.completed_at to allow NULL.
     NULL = notes saved but step not yet marked complete.
     NOT NULL = step completed. This lets learners save reflections
     before they are ready to mark a step done.

  2. Seed six pathway steps for the REAL Journey pathway.
     All INSERTs use ON CONFLICT (id) DO NOTHING — safe to re-run.
"""

from alembic import op

PATHWAY_REAL_JOURNEY_ID = "b0bd060b-1c83-41ef-8055-1870b258b75a"
NOW = "2026-05-11 00:00:00"

# Stable step IDs
STEP_WELCOME_ID         = "aa000001-0000-4000-8000-000000000001"
STEP_RECOGNISE_ID       = "aa000001-0000-4000-8000-000000000002"
STEP_EXPLORE_ID         = "aa000001-0000-4000-8000-000000000003"
STEP_ALIGN_ID           = "aa000001-0000-4000-8000-000000000004"
STEP_LEAD_ID            = "aa000001-0000-4000-8000-000000000005"
STEP_INTEGRATION_ID     = "aa000001-0000-4000-8000-000000000006"

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Make completed_at nullable ─────────────────────────────────────
    op.execute("""
        ALTER TABLE step_progress
            ALTER COLUMN completed_at DROP NOT NULL;
    """)

    # ── 2. Seed REAL Journey steps ────────────────────────────────────────
    op.execute(f"""
        INSERT INTO pathway_steps
            (id, pathway_id, slug, title, content_type, content_body,
             estimated_minutes, is_required, position, created_at, updated_at)
        VALUES (
            '{STEP_WELCOME_ID}',
            '{PATHWAY_REAL_JOURNEY_ID}',
            'welcome',
            'Welcome to the REAL Journey',
            'text',
            $body$
The REAL Journey is not a course. It is an invitation.

It begins with a simple premise: that real, lasting change doesn't come from information alone. It comes from experience — from noticing, questioning, and practising something new.

REAL stands for four phases you will move through, not once but in cycles:

**Recognise** — what is actually happening, beneath the surface
**Explore** — where the pattern comes from
**Align** — what a different choice could look like
**Lead** — what it feels like to act from that new place

This first step is simply about arriving. There is nothing to fix and nothing to prove. Just a willingness to pay attention.

Take a breath. You are in the right place.
            $body$,
            5, true, 1, '{NOW}', '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO pathway_steps
            (id, pathway_id, slug, title, content_type, content_body,
             estimated_minutes, is_required, position, created_at, updated_at)
        VALUES (
            '{STEP_RECOGNISE_ID}',
            '{PATHWAY_REAL_JOURNEY_ID}',
            'recognise',
            'Recognise — Notice the Pattern',
            'reflection',
            $body$
The first phase of the REAL Journey is Recognise.

Before we can change anything, we need to see it clearly. Not with judgment, but with genuine curiosity.

This week, choose one area of your life where something feels stuck, heavy, or out of alignment. It doesn't need to be dramatic. It might be a relationship that drains you, a habit you keep returning to, a feeling that rises at certain moments.

Just one thing. Something quiet enough to hold.

---

**Your reflection prompt:**

What is the pattern you keep noticing? Describe it as honestly as you can — not what you think it means yet, just what you observe.

Write here, or in your own notebook. There is no right answer.
            $body$,
            15, true, 2, '{NOW}', '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO pathway_steps
            (id, pathway_id, slug, title, content_type, content_body,
             estimated_minutes, is_required, position, created_at, updated_at)
        VALUES (
            '{STEP_EXPLORE_ID}',
            '{PATHWAY_REAL_JOURNEY_ID}',
            'explore',
            'Explore — Understand the Pattern',
            'reflection',
            $body$
The second phase is Explore.

Now that you have named the pattern, we slow down and look underneath it.

Most patterns that feel stuck are not character flaws. They are strategies — things we learned to do at some point because they worked, or because they kept us safe, or because we didn't know another way.

Understanding a pattern isn't the same as excusing it. It is getting honest about what need it has been serving.

Some gentle questions to sit with:

- When did this pattern first show up in your life?
- What was it protecting you from at the time?
- What has it cost you since then?

---

**Your reflection prompt:**

What do you think this pattern has been trying to do for you? What might be underneath it, if you look with compassion rather than frustration?

Take your time with this one. There is no rush.
            $body$,
            20, true, 3, '{NOW}', '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO pathway_steps
            (id, pathway_id, slug, title, content_type, content_body,
             estimated_minutes, is_required, position, created_at, updated_at)
        VALUES (
            '{STEP_ALIGN_ID}',
            '{PATHWAY_REAL_JOURNEY_ID}',
            'align',
            'Align — Choose the Next Experiment',
            'exercise',
            $body$
The third phase is Align.

Align is not about creating the perfect plan. It is about choosing one small experiment — something you could try this week that moves even slightly in a different direction.

Not a resolution. Not a commitment to transform. Just an experiment.

The word experiment is important. Experiments aren't meant to succeed or fail. They are meant to teach you something.

Your experiment might be:
- A conversation you have been avoiding
- A boundary you practise naming, even internally
- A habit you shift by five minutes
- A moment you choose to pause instead of react

---

**Your task:**

Write down one experiment you are willing to try before you return to this pathway. Keep it specific and small. The smaller, the better.

What will you try? When? What would tell you it happened?
            $body$,
            20, true, 4, '{NOW}', '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO pathway_steps
            (id, pathway_id, slug, title, content_type, content_body,
             estimated_minutes, is_required, position, created_at, updated_at)
        VALUES (
            '{STEP_LEAD_ID}',
            '{PATHWAY_REAL_JOURNEY_ID}',
            'lead',
            'Lead — Practise the Shift',
            'reflection',
            $body$
The fourth phase is Lead.

Lead does not mean authority over others. It means taking the lead in your own life — choosing how you show up, rather than simply responding to what arrives.

You tried your experiment. That alone is significant.

Now we close the loop.

---

**Your reflection prompt:**

What happened when you tried your experiment? What did you notice — in yourself, in others, in the situation?

It doesn't matter whether it went well. What matters is what you learned. Even a failed experiment teaches something real.

Write as honestly as you can. This is for you.
            $body$,
            15, true, 5, '{NOW}', '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO pathway_steps
            (id, pathway_id, slug, title, content_type, content_body,
             estimated_minutes, is_required, position, created_at, updated_at)
        VALUES (
            '{STEP_INTEGRATION_ID}',
            '{PATHWAY_REAL_JOURNEY_ID}',
            'integration',
            'Integration — What Comes Next',
            'text',
            $body$
You have completed your first cycle of the REAL Journey.

Recognise. Explore. Align. Lead.

One small loop, walked with intention.

This is how real change happens — not in a single revelation but in repeated, patient cycles of attention and choice. Each time you move through, you see a little more clearly. Each time, the shift becomes a little less effortful.

What you did here matters. Even if it felt small. Especially if it felt small.

The REAL Journey is designed to be returned to — in different seasons, with different patterns, as you grow. Each cycle you complete adds a layer. Each time, you arrive somewhere new.

Your next step is simply this: bring what you noticed into the rest of your life. Let it settle. Then come back when you are ready for the next cycle.

You are doing the work. That is everything.
            $body$,
            10, true, 6, '{NOW}', '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM pathway_steps WHERE pathway_id = '{PATHWAY_REAL_JOURNEY_ID}';
    """)
    op.execute("""
        ALTER TABLE step_progress
            ALTER COLUMN completed_at SET NOT NULL;
    """)
