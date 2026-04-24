# Fresh Collective — Website & Membership Platform

Fresh Collective is a membership-based transformation platform for women moving from survival, stuckness, and over-functioning into expansion that actually lasts. It is a structured transformation system — not a course library, not a coaching portal, not a content vault.

## What This Repo Contains

At this stage: project documentation only. No framework, no pages, no app code yet.

The `/docs` folder is the source of truth for all product strategy, design direction, platform structure, and build roadmap. Future Claude Code sessions should read the relevant docs before building anything.

## Tech Stack (planned, not yet installed)

- **Framework:** Next.js (App Router)
- **Language:** TypeScript
- **Styling:** Tailwind CSS
- **Auth & Database:** Supabase
- **Payments:** Stripe
- **Architecture:** Component-based, mobile-responsive, accessible

## Documentation

| File | Purpose |
|---|---|
| [docs/product-brief.md](docs/product-brief.md) | What the platform is, who it's for, core principles, entry paths, v1 scope |
| [docs/design-principles.md](docs/design-principles.md) | Brand feel, tone of voice, visual and UX direction |
| [docs/platform-structure.md](docs/platform-structure.md) | Full site map, page inventory, platform areas, access model, data model |
| [docs/roadmap.md](docs/roadmap.md) | Phased build plan from setup through community and payments |
| [docs/prompt-library.md](docs/prompt-library.md) | Reusable Claude prompt templates for future build sessions |

## How to Use the Docs in Claude Sessions

Start each session by telling Claude which phase you are working on and which docs to read. Example:

> "Read CLAUDE.md and docs/platform-structure.md. We are building Phase 3 (member dashboard). Do not start until you have read both files."

## Next Build Step

**Phase 1: Framework Setup**

- Initialise Next.js with TypeScript and Tailwind CSS
- Set up folder structure and design tokens
- No pages yet — foundation only

See [docs/roadmap.md](docs/roadmap.md) for the full phased plan.

## Local Development

_To be completed when Phase 1 is built._

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

## Deployment

_To be documented when deployment is configured._
