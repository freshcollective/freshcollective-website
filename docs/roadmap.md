# Roadmap — Fresh Collective

Phases are ordered by dependency, not by date. No timelines are set. Build each phase in order and do not skip ahead.

---

## Phase 0 — Repo Setup & Documentation ✓

**Status:** Complete

- Project documentation created
- Product brief, design principles, platform structure, roadmap, and prompt library in place
- CLAUDE.md and README.md set up
- No app code yet

---

## Phase 1 — Framework Setup ✓

**Status:** Complete (includes brand styling and layout system)

**Goal:** A working Next.js project with the right configuration. No pages yet.

- Initialise Next.js with TypeScript
- Install and configure Tailwind CSS
- Set up folder structure (see below)
- Define design tokens (colours, spacing, typography) in Tailwind config
- Set up path aliases (`@/components`, `@/lib`, etc.)
- Configure ESLint and Prettier
- Set up `npm run type-check` and `npm run build` scripts
- Commit clean baseline

**Folder structure (suggested):**
```
/src
  /app             — Next.js App Router pages
  /components      — Reusable UI components
    /ui            — Primitive components (Button, Card, Input, etc.)
    /layout        — Layout components (Header, Footer, Sidebar, etc.)
    /sections      — Page-level section components
  /lib             — Utilities, helpers, constants
  /types           — TypeScript type definitions
  /styles          — Global styles
```

---

## Phase 2 — Public Site

**Goal:** The public-facing pages a visitor sees before logging in.

- Home page (`/`)
- About page (`/about`)
- REAL Journey sales page (`/real-journey`)
- Membership sales page (`/membership`)
- Login page (`/login`)
- Sign up page (`/signup`)

All pages should be fully responsive and match design principles. No auth or payments wired yet — use placeholder buttons and Stripe-ready structure comments.

---

## Phase 3 — Member Area Foundation

**Goal:** A secure, navigable member area with a working dashboard shell.

- Supabase authentication integration (login, signup, session management)
- Protected route middleware (redirect to login if unauthenticated)
- Member layout (sidebar or top nav, consistent across member pages)
- Member dashboard page (welcome message, placeholder cards for next step, live call, prompts)
- Profile / account page (basic account info, membership status)
- Navigation linking all member pages

No content yet — structure and shell only.

---

## Phase 4 — REAL Journey

**Goal:** A working, navigable REAL Journey experience for members.

- Start Here overview page
- Four phase pages: Recognise, Explore, Align, Lead
- Each phase: short description, lessons/steps (even if placeholder), reflection prompt, integration action
- Simple progress tracking (which phases completed)
- "Return to REAL" flow — accessible from dashboard and navigation
- Connect to dashboard "Continue REAL Journey" button

Keep it bite-sized. Do not overbuild lesson content structure.

---

## Phase 5 — The Heart (Live Layer)

**Goal:** A clear, welcoming Live Layer area.

- The Heart overview page
- Current monthly theme display
- Upcoming live call card (date, time, Zoom link placeholder)
- Live call calendar / list
- Integration thread area (async post-call discussion)
- Latest community prompt card

The Heart should feel central. Build it as a first-class area, not an add-on.

---

## Phase 6 — The Rooms (Pathways)

**Goal:** The Rooms overview and the Growth Pathway fully built.

- The Rooms overview page (three pathways: Growth live, Transformation + Essence as Coming Soon)
- Growth Pathway overview page
- Three room pages: Self-awareness, Self-trust, Uniqueness
- Each room: description, content placeholder, suggested next steps
- Transformation and Essence: visible but clearly marked Coming Soon

Navigation should feel simple. Do not expose the full depth upfront.

---

## Phase 7 — Community

**Goal:** A simple, clean community area.

- Community feed (most recent posts first)
- Prompt cards (founder-created prompts)
- Member reflection responses
- Discussion threads (tied to live calls and REAL phases)
- Clean posting UI (text post, reply)

Keep it simple. No complex social graph, no likes/reactions in v1.

---

## Phase 8 — Payments

**Goal:** Stripe integration for both entry paths.

- Stripe product and price setup (REAL Journey standalone, Membership)
- Checkout flow for REAL Journey purchase
- Checkout flow for Membership purchase
- Webhooks to update Supabase on successful payment
- Post-purchase redirect and account creation
- Membership status checks on protected routes

Mark all Stripe integration points clearly in the codebase during earlier phases so this is a clean drop-in.

---

## Deferred — Post v1

These are intentionally excluded from the initial build:

- Transformation pathway (full content build)
- Essence pathway (full content build)
- Gamification, streaks, or achievement systems
- Badges
- Complex admin systems
- Advanced analytics or reporting
- Native mobile app
- Multi-contributor content (the founder is the sole architect for now)
