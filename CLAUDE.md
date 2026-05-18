# Fresh Collective — Claude Instructions

## Project Identity

Fresh Collective is a membership-based transformation platform for women. It is a structured system with one foundation (REAL Journey), multiple deepening pathways (The Rooms), and a live community layer (The Heart).

Repo: `freshcollective-website` | Stack: Next.js, TypeScript, Tailwind, Supabase, Stripe

## Read Before Building

Always read the relevant docs before writing code:

- `docs/product-brief.md` — what the platform is, priorities, what not to build
- `docs/design-principles.md` — visual style, tone, UX rules
- `docs/platform-structure.md` — pages, platform areas, access model, data model
- `docs/roadmap.md` — which phase we are in and what is in scope

## Standing Product Principles

- **No overwhelm.** Short, digestible, behaviour-shifting. Quality comes from usability, not comprehensiveness.
- **Community is the value.** The live layer is not an add-on. Content is the structure; community is the heart.
- **REAL Journey is the centre.** All pathways, prompts, and live moments should connect back to it.
- **Behaviour change over information delivery.** Every feature should support integration and lived change.
- **The founder is not available 24/7.** The structure holds the community. Do not build features that create burnout.
- **The platform must feel calm, warm, and spacious.** Never cluttered, heavy, or overwhelming.

## Build Rules

- Ask before installing any new package or framework.
- Do not build features outside the current phase (see `docs/roadmap.md`).
- Do not add complexity that is not explicitly in scope.
- Prefer editing existing files to creating new ones.
- Do not create pages not listed in `docs/platform-structure.md`.
- Mark Stripe and Supabase integration points clearly if deferring.
- Reference docs by filename — do not re-explain the brief in prompts.
- Cite the relevant doc section when making product decisions.

## Dev Health Check

If the frontend shows `ECONNREFUSED 127.0.0.1:8000`, the **backend process is not running** — this is never a code bug.

Run the health check script at any time:

```bash
bash /home/lindsey/fc-production/scripts/health-check.sh
```

It checks:
- Backend responding at `http://127.0.0.1:8000`
- Frontend responding at `http://localhost:3000`
- Alembic migration is at head

**To start the backend manually:**
```bash
cd /home/lindsey/fc-production/backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Or use the launcher: `~/.local/bin/fc-run-backend`

**To run pending migrations:**
```bash
cd /home/lindsey/fc-production/backend
.venv/bin/alembic upgrade head
```

## After Code Changes (once the app exists)

- Run `npm run type-check` after TypeScript changes.
- Run `npm run build` before declaring a feature complete.
- Check mobile layout before reporting UI work done.
