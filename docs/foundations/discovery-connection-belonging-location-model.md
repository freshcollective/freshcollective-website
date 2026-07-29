# Discovery, Connection & Belonging — Location Capture Model

Companion to the philosophy doc
(`discovery-connection-belonging-v1.1.md`) and the implementation
status doc (`discovery-connection-belonging-status.md`).

This document names *how location arrives in the system* — from a
Creator's input at Collective publication, and from the location
entered on each Gathering. It supersedes any earlier proposals that
involved manual Place administration, separate City / State /
Country field trios, or an admin approval queue for new Places.

This is architectural intent, not an implementation plan. Nothing
in the codebase changes until a Phase-1 delivery brief is written
against this document.

---

## Design principle

> Creators should think in terms of places, not geographic data.
> Fresh Collective is responsible for collecting and storing
> structured location information behind the scenes while
> presenting the simplest possible experience to Creators.

Every decision below flows from this principle. If a proposed
change would require a Creator to reason about states, provinces,
regions, coordinates or country codes, it is the wrong change.

---

## Design philosophy

Keep location capture as simple as possible for Creators, while the
platform stores structured location data behind the scenes.

The Creator experience is a single field.

The underlying data model still carries city, region, country and
coordinates so Discover Places and future Discovery features can
work on real geography without the Creator ever having to think
about it.

The goal is to remove unnecessary fields and workflows.

---

## Collective Settings

The prior proposal (manual location fields, per-field entry) is
retired.

A Collective has a single setting for how it connects:

**How does your Collective connect?**

- Online
- In person
- Both

### If *Online* is selected

- No primary location is required.
- The Collective does not create a geographic Place.
- The Collective does not appear on Discover Places.

### If *In person* or *Both* is selected

A single field appears:

**Primary location**

This is a searchable place picker (autocomplete), similar to the
location selectors used by travel sites or Human Design birth
location tools.

Example — the Creator types `Melbourne` and sees:

- Melbourne, Victoria, Australia
- Melbourne, Florida, United States
- Melbourne, Derbyshire, United Kingdom

The Creator selects one option and is done. The system captures the
structured data (city, region/state, country, coordinates and any
provider-specific canonical id) behind the scenes.

No separate City, State or Country fields are ever shown to the
Creator.

---

## Gatherings

Gatherings also use a single searchable location picker.

The following fields are **not** collected:

- venue name
- street address
- postcode

Rationale: many Gatherings will occur in private homes or informal
locations. Precise addresses would place a privacy burden on the
Creator and the host, and rarely add value at discovery time.

A simple place selector (for example "Richmond, Victoria,
Australia") is sufficient. Members who need meeting-instruction
detail receive it through the Gathering's description or a separate
private message flow that already exists.

---

## Place creation

Places are not manually created. They emerge as Collectives
publish.

When a Collective with a primary location is published:

1. Check whether a Place matching the picker's structured data
   already exists.
2. If it exists, link the Collective (a `space_places` row) — no
   new Place is created.
3. If it does not exist, automatically create the Place from the
   picker's structured data, then link.

There is no manual Place creation workflow. There is no admin
approval queue. The first version assumes Places are created
automatically as the world grows.

Draft Collectives do not create Places — the creation only happens
at publish time, so unpublished experiments don't populate the map.

### Deduplication

Places are deduplicated using the location provider's unique place
id, not the display name.

If two Creators independently select "Melbourne, Victoria,
Australia" through the picker, both selections resolve to the same
provider place id and therefore link to the same Place record. No
name-matching, no fuzzy comparison, no manual reconciliation.

This makes `provider_place_id` a load-bearing column on the Place
schema (see *Reconciliation with earlier decisions* below): it is
how the system knows two picks are the same city.

If the provider ever changes (see open questions), a one-time
backfill maps existing rows to the new provider's ids — the
principle survives the provider swap.

---

## Place Management (admin surface)

Place Management is not a place-creation workflow. It is the
surface where administrators can, over time, refine the identity of
a Place that already exists:

- Upload editorial artwork
- Adjust the Place's palette / atmosphere
- Edit the Place's description (the `blurb` field already exists on
  the Phase 0 schema)
- Archive a Place if ever required (the model already supports
  `active` and `hidden` status)

No admin action is required for a Place to appear. Discover Places
can render a newly-created Place using derived defaults (its name,
region, country, and — once Phase 1 lands — a generated colour
atmosphere) until an administrator invests editorial time in it.

---

## Reconciliation with earlier decisions

**Editorial curation** — the philosophy doc frames Places as
"editorial, curated by hand." Under this model, the editorial gate
moves upstream: a Creator's decision to publish an in-person
Collective *is* the curation. The platform is not scraping event
metadata; each Place exists because a real Collective declared
itself there. Admin editorial work continues in Place Management
(artwork, description, palette).

**Phase 0 seed emptiness** — the Phase 0 seed script was empty by
design because no current Collective had a real Place attached.
Under this model the seed remains empty; Places appear naturally as
Creators use the new setting. The script stays checked in as a
manual fallback if an administrator ever needs to introduce a Place
ahead of Collective activity (e.g. seeding an anticipated launch
city).

**Existing Place schema** — the Phase 0 `Place` model (id, slug,
name, country_code, region, blurb, status) supports this flow but
does not yet carry the fields the picker returns. Before Phase 1,
the schema will likely need:

- `latitude` and `longitude` (for later "near you" surfaces)
- `timezone` (derived from the picker; used by Collectives that
  don't override it)
- `provider_place_id` (e.g. Google Place ID / Mapbox feature id) —
  the deduplication key. Two Creators picking the same city
  resolve to the same id and therefore the same Place.

These are additive columns; the Phase 0 migration does not need to
change.

---

## Open questions

Small, high-leverage decisions that remain open for Phase 1
delivery:

1. **Autocomplete provider.** Google Places, Mapbox, OpenCage and
   Nominatim / OpenStreetMap each have different cost, coverage,
   licensing and privacy tradeoffs. The choice affects the shape
   of `provider_place_id` and whether we can cache picker results
   indefinitely. Whatever provider is chosen, the deduplication
   rule above still applies — same provider, same id, same Place.

2. **Gathering vs Collective granularity.** A Collective's primary
   location is city-level ("Byron Bay"). A Gathering might happen
   in a suburb ("Suffolk Park"). Two possibilities:
   - Gatherings use the *same* Place picker and roll up to the
     nearest Place. A Gathering in Suffolk Park is recorded
     against "Byron Bay."
   - Gatherings can pick finer locales that are not themselves
     Places, stored as structured location data on the Gathering
     without creating a Place record.

   Both preserve privacy (no address). The first keeps the Place
   graph clean at city level; the second lets Gatherings carry
   sub-city context.

3. **Changing a Collective's primary location.** If a Creator
   moves the Collective, does the old `space_places` link stay
   (historical) or disappear (only current)? Discover Places
   counts will differ. Probably: replace on change, don't retain
   history — but call this out explicitly at delivery time.

### Resolved during planning

- **Deduplication key** — the location provider's unique place id.
  See *Deduplication* above.
