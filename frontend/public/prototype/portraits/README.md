# Ways to Connect — prototype portrait fixtures

**Development-only fixtures.** Replace or remove entirely when
real member profile photos flow through from the introduction
recommendation service.

## The two real product states

Ways to Connect renders exactly two portrait states:

1. **The member's real profile photo** — shown when a photo is
   set and the member's profile visibility settings permit it.
2. **The polished serif-initial fallback** — everything else.

There is no third abstract-graphic state. Any earlier abstract
SVGs have been removed from this folder because they read as
decorative placeholders, not people, and they misrepresented
what will exist in production.

## What lives here

Approved prototype-only image assets (JPG / PNG). Drop them in
this folder and reference them from
`frontend/src/app/ways-to-connect/_prototype/mockIntroductions.ts`
by setting a fixture entry's `avatarUrl` to
`/prototype/portraits/<filename>`.

Each pairing between a mock member's name and an image must be
deliberate and stable — never derived from the mock name and
never regenerated. Do not use external avatar services; do not
attribute real people's photos to fictional members.

Every file in this folder should carry a licence note (either
inline in a `LICENCES.md` here or in the commit that introduces
it) so the provenance is auditable.

Delete this whole folder when the prototype is retired.

## Current state

No prototype photos are checked in right now. Every mock member
in `mockIntroductions.ts` has `avatarUrl: null`, so every card
demonstrates the initial fallback. The photo render state is
implemented in `PortraitCircle` (see
`_prototype/WaysToConnectPrototype.tsx`) and will exercise the
moment a photo URL is added here and referenced from the
fixture.
