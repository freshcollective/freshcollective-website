# Roadmap — Fresh Collective

> **Version history**
> v1 roadmap (original): single-creator platform — REAL Journey, Rooms, Heart.
> v2 roadmap (current): Space-based multi-creator platform. Phases 0–2 are complete. Phase 3 onward is reframed around the Space architecture.

Phases are ordered by dependency, not by date. No timelines are set. Build each phase in order and do not skip ahead.

---

## Phase 0 — Repo Setup & Documentation ✓

**Status:** Complete

- Project documentation created
- Product brief, design principles, platform structure, roadmap, prompt library in place
- CLAUDE.md and README.md set up

---

## Phase 1 — Framework Setup ✓

**Status:** Complete

- Next.js with TypeScript, Tailwind CSS, path aliases, ESLint
- Design tokens (colours, spacing, typography) in Tailwind config
- Folder structure: `/app`, `/components/ui`, `/components/layout`, `/components/sections`, `/lib`, `/types`

---

## Phase 2 — Public Site ✓

**Status:** Complete

- Home page (`/`)
- About page (`/about`)
- REAL Journey sales page (`/real-journey`) — legacy, will evolve to Space landing
- Membership sales page (`/membership`) — legacy, will evolve
- Login, signup, forgot-password, reset-password pages
- Multiple visual iterations toward calm, transformation-led aesthetic

---

## Phase 2b — Auth System ✓

**Status:** Complete

- Local PostgreSQL authentication (fc_prod database)
- FastAPI backend: bcrypt passwords, JWT sessions (httpOnly cookies, 7-day expiry)
- Frontend route protection via `src/proxy.ts`
- Login, signup, logout, forgot-password, reset-password flows
- Password reset URL logged to console in dev (TODO: email in production)
- User roles: `user` | `admin`
- Admin sales pipeline: leads, opportunities, activities, tasks, subscription plans

---

## Phase 2c — Frontend/Backend Separation ✓

**Status:** Complete

- Repo split into `frontend/` (Next.js) and `backend/` (FastAPI)
- SQLAlchemy ORM + Alembic migrations
- All DB operations through FastAPI backend

---

## Phase 3 — Space Architecture Foundation ← CURRENT

**Status:** In progress

**Goal:** Evolve the platform foundation to support the Space-based multi-creator architecture. No major UI changes yet — focus on correct structure, models, and routes.

### 3a — Documentation update ✓
- Product brief, platform structure, and roadmap updated to reflect Space architecture
- REAL Journey repositioned as one Pathway within the Fresh Collective Space
- Rooms → Pathways, The Heart → Community + Events

### 3b — Backend domain model
- Add `creator` to user roles (extend CHECK constraint via Alembic)
- Add new platform entities: `spaces`, `space_memberships`, `pathways`, `pathway_steps`, `enrollments`, `step_progress`, `events`, `community_posts`, `post_comments`, `creator_profiles`
- Alembic migration 003 (additive, no data loss)
- Seed: Fresh Collective Space + 4 Pathways (REAL Journey, Growth, Transformation/Essence as coming_soon)

### 3c — Auth role extension
- Add `get_creator_user` dependency
- Update `get_admin_user` to remain admin-only
- Frontend proxy updated to protect `/spaces` and `/creator` routes

### 3d — API route stubs
- Space routes: `GET /api/spaces`, `GET /api/spaces/{slug}`
- Creator routes: `GET /api/creator/spaces`
- Pathway routes: `GET /api/spaces/{slug}/pathways`

### 3e — Frontend route placeholders
- `/spaces/[slug]` — placeholder page
- `/spaces/[slug]/pathways` — placeholder
- `/spaces/[slug]/community` — placeholder
- `/spaces/[slug]/events` — placeholder
- `/creator` — placeholder

---

## Phase 4 — Learner Experience (Pathways)

**Goal:** A working, navigable Pathway experience inside a Space.

- Space overview page (home tab: progress, next step, community highlights, upcoming events)
- Pathway overview page (step list with progress indicators)
- Step page (content rendering, reflection input, mark complete)
- Progress tracking (enrollment, step_progress records)
- "Continue where you left off" deep link from dashboard
- REAL Journey fully built as the first Pathway in the FC Space (4 phases as step groups)

Keep it bite-sized. One clear next step at all times.

---

## Phase 5 — Community + Events

**Goal:** A clear, welcoming Community and Events experience within a Space.

- Community feed (posts, prompts, reflections, discussions)
- Founder/creator prompt posts
- Event listing (upcoming live calls)
- Event detail (date, time, Zoom link placeholder)
- Recording archive (past events)

Community should feel central — not an add-on.

---

## Phase 6 — Creator Studio (Internal, Lindsey only for v1)

**Goal:** A working creator studio for managing the FC Space.

- Creator dashboard (`/creator`)
- Pathway management (create/edit pathways and steps)
- Event management (create/edit events)
- Community management (post prompts, pin posts)
- Space settings (name, description, cover image)
- Member view (who is enrolled, progress summary)

This validates the creator tooling before opening to third-party creators.

---

## Phase 7 — Dashboard Evolution

**Goal:** Update the learner dashboard to reflect the Space architecture.

- Show enrolled Spaces
- "Continue where you left off" (most recent Pathway, deep link to next Step)
- Upcoming Events across all enrolled Spaces
- Recent Community activity from enrolled Spaces
- Onboarding state for new learners (direct to REAL Journey)

---

## Phase 8 — Payments

**Goal:** Stripe integration for Space/Pathway access.

- Stripe product and price setup
- Space membership checkout (join FC Space)
- Individual Pathway purchase (if applicable)
- Webhooks to update access on successful payment
- Post-purchase redirect and enrollment creation
- Membership status checks on protected routes

Mark all Stripe integration points clearly in the codebase during earlier phases.

---

## Phase 9 — Growth Pathway (Full Content)

**Goal:** Growth Pathway fully built with content.

- Self-awareness, Self-trust, Uniqueness rooms as Step groups within the Growth Pathway
- Each Step: description, content placeholder, reflection prompt, suggested next steps
- Navigation within the Pathway

---

## Deferred — Post v1

These are intentionally excluded from the initial build:

- Third-party creator onboarding and Space creation flow
- Transformation and Essence Pathways (full content)
- Public creator profiles and discovery
- Cross-Space community feed
- Per-Space subscription billing (separate from platform membership)
- Native mobile app
- Gamification, streaks, badges
- AI features
- Advanced analytics
- Multi-contributor content within a Space
