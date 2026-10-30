# Fresh Collective — Claude Instructions

## Project Identity

Fresh Collective is a creator-enabled platform for coaches, educators and
facilitators to build **Collectives** — a home containing Pathways, Gatherings,
Conversations and Offerings. Not an LMS or a content vault; built for returning
members rather than sign-up flows.

Stack: Next.js (App Router) + TypeScript + Tailwind v4 · FastAPI + SQLAlchemy +
Alembic on PostgreSQL · Stripe (platform and Connect) · Resend · Cloudflare R2 ·
hosted on Render.

## Repository and Environments

Two applications deploy, and only two: `frontend/` (service `fc-web`) and
`backend/` (service `fc-api`). See `render.yaml` for both, plus the cron services
that also run from `backend/`.

**Active at the repository root**, and important: `render.yaml` (deployment and
configuration), `docs/` (reference documentation), `scripts/` (operational and
seed scripts), `README.md`, `.gitignore`, and this file. `design-reference/` and
`reference/` hold design source material.

**Legacy — the pre-split single-app Next.js + Prisma setup.** Not deployed, not
maintained:

```
src/  prisma/  prisma.config.ts  public/  .env.example
package.json  package-lock.json  next.config.ts  postcss.config.mjs
tsconfig.json  eslint.config.mjs
```

`frontend/` has its own `package.json`, `tsconfig.json`, `next.config.ts`,
`eslint.config.mjs` and `postcss.config.mjs`, so the root copies govern nothing
that ships; Prisma is not used by either deployed app. Do not edit the legacy
files or take guidance from them, and never run the root `build` or
`type-check`: those exercise dead code and tell you nothing about the shipped
app. Always run frontend commands from inside `frontend/`.

Checkouts on this machine are git worktrees of one repository:

| Path | What it is |
|---|---|
| `/home/lindsey/fc-merge` | **The development checkout.** Branch `main`. Work here. |
| `/home/lindsey/fc-production` | An **old worktree on a stale feature branch**, many weeks and many migrations behind. Despite the name it is neither production nor current. |
| `fc-connect`, `fc-review` | Other worktrees on their own branches. |

Production is Render, not any local directory.

> **Never run migrations or development commands from `fc-production`.**
> `alembic upgrade head` there applies a stale branch's migration graph to your
> local database. The launcher scripts and `scripts/health-check.sh` still
> hardcode that path — a known defect, pending correction.

The only Python virtual environment currently lives at
`/home/lindsey/fc-production/backend/.venv`. Until a local environment exists in
`fc-merge`, borrow that interpreter while running code from `fc-merge`:

```bash
cd /home/lindsey/fc-merge/backend
/home/lindsey/fc-production/backend/.venv/bin/python -m pytest
```

`ECONNREFUSED 127.0.0.1:8000` in the frontend means the backend process is not
running. This is never a code bug.

## Hard Rules

- **Never automate login to a real account**, and never reset a real user's
  password to enable testing. See `docs/dev-testing-safety.md`.
- **Never query a local database to answer a question about production data.**
  Local copies lag production. Probe the live API instead.
- **Never add a third notification path.** See *Communications* below.
- **Never rename internal identifiers for UI consistency.** See *Naming*.
- **Secrets must never appear in tracked files, commits, command arguments,
  logs, or any other exposed output.** Approved untracked local environment
  files — `backend/.env` and a local frontend equivalent — are fine when kept
  gitignored and protected; `backend/.env.example` and `frontend/.env.example`
  document the shape without real values. Production values live only in Render.
  Prompt for passwords interactively rather than passing them on a command line,
  and keep them out of command echo and diagnostics.
- Ask before installing any package or framework.
- Prefer editing existing files to creating new ones.
- Scope comes from explicit instruction and agreed priorities — not from the
  historical roadmap.

## Testing

Backend — real PostgreSQL (`fc_test`), so constraints and locking behave
honestly. Requires a copied `backend/.env`.

```bash
cd /home/lindsey/fc-merge/backend
/home/lindsey/fc-production/backend/.venv/bin/python -m pytest
```

Frontend:

```bash
cd /home/lindsey/fc-merge/frontend
npm test            # node --experimental-strip-types --test
npm run type-check
npm run lint
npm run build       # before declaring a feature complete
```

Three traps worth knowing:

- The frontend runner is **node's built-in test runner, not vitest or jest**. A
  test file written for either silently never runs.
- Each backend test is one transaction with savepoints, so `db.begin_nested()`
  is unusable once the session has committed, and `now()` is identical
  throughout a test — don't assert on row ordering by timestamp.
- Alembic's `fileConfig` silences `app.*` loggers under pytest, so naive log
  assertions pass vacuously.

Never `TRUNCATE spaces` in `fc_test` — it is migration-seeded. Leftover
committed rows cause dozens of unrelated failures, so clean before trusting a
red suite.

Run the full suite before shipping; it is expected to be green, so a failure is
a real signal.

## Migrations and Deployment

Migrations live in `backend/alembic/versions/`, named
`NNN_snake_case_summary.py` with a matching string `revision` and a linear
`down_revision` chain. Take the next free number and never renumber an existing
one.

One push to `main` deploys both services. `fc-api` runs `alembic upgrade head`
as its `preDeployCommand`, before traffic cutover, so a migration that fails
blocks the release rather than half-applying it. **Deployment order between the
two services is not guaranteed** — do not infer one from the other.

`render.yaml` is the source of truth for configuration. Entries written as
`value:` are reasserted on blueprint sync and will silently revert a change made
in the Render Dashboard; entries marked `sync: false` are Dashboard-owned. This
has caused two incidents.

### Verifying a deployment

Neither service reports its running version in-band, so verify **each service
independently**, and keep behaviour verification separate from deployment-status
confirmation.

1. **Establish a baseline before deploying.** Choose an observable that this
   release changes and that you can reach without credentials — a route's
   response, a public page, a rendered string — and record how it answers now.
   A new route commonly answers 404 beforehand, but not always: a sibling
   parameterised route can already respond 401 or 405, so capture the actual
   baseline rather than assuming one.
2. **Confirm the expected change afterwards.** Re-check the same observable
   until it answers the way the release intends. Never infer success from
   elapsed time, from the other service, or from a commit SHA in a JavaScript
   bundle — bundles no longer carry one, and a changed chunk set proves only
   that *some* rebuild happened.
3. **Confirm deployment status separately** in the Render Dashboard, which is
   the only authoritative statement of which commit is running.
4. Where the change sits behind authentication there is no unauthenticated
   observable. Confirm deployment status, then say plainly that the
   authenticated walkthrough is still outstanding.

Always report which parts were verified by observed behaviour and which by
deployment status alone.

## Safety

**Authentication.** Dependency ladder in `backend/app/auth/dependencies.py`:
`get_current_user` → `get_verified_current_user` → `get_creator_user` →
`get_verified_creator_user` → `get_admin_user`. Trust actions require a verified
variant.

**Collective scoping.** Creator-side access goes through `_get_managed_space`
(owner, or active creator/moderator) — note that **platform admins get nothing
from it**; admin reach is a separate path. Test member privacy and
cross-Collective isolation per feature. Detail in `docs/permissions-matrix.md`.

**Email, invitations and messages.** Two independent safeguards: a three-layer
delivery guard (`backend/app/comms/delivery_guard.py` — test process,
RFC-reserved domains, non-production unless explicitly allowed) and a Resend
**SDK-level** tripwire in `backend/tests/conftest.py`. Enforcement sits at the
SDK boundary, not in the provider. Test with isolated accounts and mocked
delivery; never send to real members.

**Communications.** `backend/app/comms/` is the current layer (event → resolver
→ template → intent → provider); preferences, consent and suppressions hang off
the event type. A few legacy `notification_service` call sites remain and are
deliberate. Extend one of these two paths — never add a third. Which topics are
live is configuration, not code: check `comms_live_topics` in
`backend/app/core/config.py` before assuming an email sends.

**Payments and entitlements.** Three independent "what does this person own"
tables — `PathwayEntitlement` (pathway content), `AccessPass` (terms, credits,
tickets), `OfferingEntitlement` (downloads) — plus `ManualMember` for people
with no account. `MemberSubscription` is *not* read by the runtime access check,
so a row there grants nothing. Never grant paid access, bypass checkout or touch
billing as a side effect of another feature. Background:
`docs/stripe-implementation-plan.md`, `docs/connect-go-live.md`,
`docs/finite-payment-plans-lifecycle.md`.

**CSV exports.** Escape any leading `=`, `+`, `-`, `@`, tab or carriage return
against spreadsheet formula injection, emit a UTF-8 BOM so Excel opens the file
correctly, and never include credentials, payment details or account internals.

## Naming

Internal identifiers are **deliberately frozen** for database and API
compatibility. The current vocabulary is a presentation-layer rename.

| Internal (tables, models, routes) | Member-facing |
|---|---|
| `space` / `spaces` | Collective |
| `event` / `events` | Gathering |
| `community_posts` | Conversations |
| `colour_stories` / `ColourStory` | Colour Palette |

Member-facing vocabulary: **Collectives, Pathways, Gatherings, Conversations,
Offerings, Colour Palettes.** Use it in all UI copy, emails and user-visible
errors.

Do not propose renaming database structures merely to match the UI. A `spaces` →
`collectives` refactor would break the migration chain and every API route at
once.

## Design

The platform should feel **warm, welcoming, calm, spacious and human** — never
cluttered, heavy or corporate. Every element earns its place.

- `docs/atlas-vol-1-living-world.md` (**The Atlas, v1.2**) is the canonical
  product and design reference. Read it before Collective or World work, flag
  conflicts rather than quietly diverging, and propose additions for genuinely
  new decisions.
- `docs/design-principles.md` holds the brand feel and UX rules.
  `docs/fresh-design-language.md` holds the detailed system.
- Build from the shared components in `frontend/src/components/platform/` rather
  than re-styling one-offs, and use the tokens in
  `frontend/src/styles/fc-tokens.css` and `frontend/src/app/globals.css` instead
  of literal hex.
- **Do not add small uppercase teal eyebrow labels above headings** anywhere in
  the product.
- Responsive: check real layouts at desktop, tablet and phone widths before
  reporting UI work done. Wide content scrolls inside its own container; the
  page body never scrolls sideways.
- Accessibility: label every control, keep a visible `focus-visible` state,
  provide `sr-only` text where an icon carries the meaning, and respect
  `prefers-reduced-motion`.

## Reference

Authoritative for implementation: the deployed code, `backend/alembic/`,
`render.yaml` and application configuration.

Current supporting docs in `docs/`: `atlas-vol-1-living-world.md` ·
`design-principles.md` · `fresh-design-language.md` · `dev-testing-safety.md` ·
`permissions-matrix.md` · `stripe-implementation-plan.md` ·
`connect-go-live.md` · `finite-payment-plans-lifecycle.md` ·
`product-brief.md` (positioning; v1 sections superseded).

**Historical — preserved for reference, not binding:** `docs/roadmap.md` and
`docs/platform-structure.md`. Both predate the current architecture and
vocabulary — the roadmap marks long-shipped phases as pending, and the structure
document describes no Gatherings, Conversations or Offerings. Neither is a gate
on what may be built or which pages may exist.
