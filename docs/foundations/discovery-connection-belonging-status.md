# Discovery, Connection & Belonging — Implementation Status

Companion to `discovery-connection-belonging-v1.1.md`. That document
sets the philosophy and information architecture; this one records
what has actually shipped, phase by phase, so anyone picking up the
pillar can see the delivered surface at a glance.

The pillar as a whole is gated by a single feature flag,
`discovery_pillar_enabled` (backend) and its mirror
`NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED` (frontend). Nothing user-facing
in the pillar renders until that flag is on.

---

## Phase 0 — Foundation ✓

**Status:** Complete.

Phase 0 lands the pillar's architectural surface: the schema, the
Recognition domain, the gated navigation, and the placeholder rooms.
Nothing in Phase 0 ships a user-facing feature — it is the ground the
later phases build on.

### Delivered

**Data foundation**

- Canonical geographic `Place` architecture — deliberately separate
  from Atlas `Location` (the mythic worldview layer used for
  Collective aesthetics).
- `space_places` join — many-to-many Collective ↔ Place. No
  primary / secondary ordering; a pure join.
- `Space.kind` column with values `standard` (default) and
  `local_circle`. Schema only in Phase 0 — no behavioural branching
  yet. Existing rows backfilled to `standard`.
- `User.home_place_id` — nullable, opt-in FK. `SET NULL` on Place
  delete: a person is not deleted when an editorial Place is retired.
  Schema only; no profile UI yet.
- Alembic migration `091_places_scaffolding.py`, verified in both
  directions (`upgrade 091 → downgrade 090 → upgrade 091`).
- Idempotent seed script `backend/scripts/seed_initial_places.py` —
  empty by design: no current Collective or Gathering has a real
  Place attached, so aspirational cities do not belong here yet.

**Recognition domain**

- `app/services/recognition_service.py` — read-time derivation of
  what two people share, with the public API in the language of the
  product (`Recognition`, `SharedCollective`, `SharedPathway`,
  `SharedGathering`, `RecognitionService.between()`,
  `RecognitionService.for_user()`) and private helpers in the
  language of the substrate (`_active_shared_memberships`,
  `_active_shared_enrolments`, `_confirmed_shared_bookings`).
- Privacy & eligibility guards baked in from the start:
    - Suspended or cancelled accounts on either side yield an empty
      Recognition.
    - Only `active` memberships / `active` enrolments / `confirmed`
      bookings count.
    - Collectives excluded when `status != 'active'`, `closed_at` is
      set, or `show_member_directory` is `False` — the exclusion
      cascades to that Collective's pathways and gatherings too.
- Returns focused result objects, not ORM rows.

**Gated public read surface**

- `GET /api/places` — active Places only, ordered by name, minimal
  shape (`id, slug, name, country_code, region`). No member data, no
  Recognition data, no personalisation, no filtering, no search, no
  recommendations. Returns 503 when the flag is off, matching the
  Community Care precedent.

**Gated navigation + placeholder rooms**

- Four-peer-destination navigation scaffolding on both desktop
  (`PublicHeader`) and mobile (`MobileNav`):
    1. Your World
    2. Explore Collectives
    3. Discover Places
    4. Ways to Connect
  Rendered when the flag is on; existing single-item behaviour
  preserved exactly when it is off.
- `/discover-places` and `/ways-to-connect` placeholder pages —
  calm, intentional Fresh Collective voice; empty rooms in a living
  world, not "coming soon" software placeholders. Both call
  `notFound()` when the flag is off so the routes are not
  discoverable.

**Feature-flag handling**

- Backend flag `discovery_pillar_enabled` on `Settings` (default
  `False`). Wired through `/api/places` and available to future
  Discovery endpoints.
- Frontend mirror `NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED` (default
  `false`) — read via `frontend/src/lib/featureFlags.ts` so the
  surface stays in one place. Documented in
  `frontend/.env.example`. Inlined at build time; flipping requires
  rebuild + redeploy, which is the intended grain for a whole-pillar
  toggle.

### Deliberately not in Phase 0

- Discover Places feature itself (real editorial content, listing
  UI, per-Place pages).
- Ways to Connect feature itself.
- Journey Together (intentional, mutual, persistent relationship
  graph).
- Local Circle behavioural branching.
- Profile UI for `User.home_place_id`.
- Any personalisation or place-based Recognition dimension (needs
  opt-in mechanism first).

### Commits

- Commit 1 — data foundation: `dfab439`
- Commit 2 — Recognition service: `b7d1ee6`
- Commit 3 — gated navigation + `/api/places` + placeholder pages:
  `9e00c14`

### Verified baseline at Phase 0 completion

- Backend: **546 tests passed** (`pytest --tb=no -p no:warnings`)
- Frontend: **132 tests passed** (`npm test`)
- Type-check: **clean** (`npm run type-check`)
- Production build: **passed** (`npm run build`) — `/discover-places`
  and `/ways-to-connect` both build as static routes.
- Working tree: **clean** at commit `9e00c14`.

---

## Phase 1 — not yet started

To be scoped when product decides which surface opens first.
