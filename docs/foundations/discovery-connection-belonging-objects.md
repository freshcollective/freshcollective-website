# Discovery, Connection & Belonging — Discovery Objects

Companion to the philosophy doc
(`discovery-connection-belonging-v1.1.md`), the Phase 0 status doc
(`discovery-connection-belonging-status.md`), and the location
capture model (`discovery-connection-belonging-location-model.md`).

This document names the core things people can discover within
Fresh Collective. It is architectural intent, not an implementation
plan — every discovery experience should be composed from these
objects, and no new discovery experience should invent new
first-class concepts without a return here.

---

## Purpose

This document defines the core things that people can discover
within Fresh Collective.

These are not UI components or database entities. They are the
living parts of the Fresh Collective world that members encounter
as they explore, belong and connect.

Every discovery experience should be built by combining these
discovery objects, rather than inventing new concepts.

---

## Design principles

### Discovery should feel human

Members should feel like they are discovering people, places and
opportunities — not navigating a directory.

### Every object should have a purpose

If something can be discovered, it should answer:

> "Why would someone want to find this?"

### Discovery should create belonging

The goal is not exposure.

The goal is helping the right people find the right communities.

### Discovery should reveal a living world

Members should feel like Fresh Collective is alive.

They should discover activity, growth and people — not static
pages.

---

## Discovery Objects

### Places

Represents a real-world location where community exists.

**Examples**

- Melbourne
- Hobart
- Vancouver
- Edinburgh

**Purpose**

Places help members discover communities near them and understand
where activity is happening.

**Relationships**

- Contains: Collectives, Gatherings
- May contain (future): stories, recommendations, editorial content

**Has its own page?** Yes.

**Discoverable?** Yes.

---

### Collectives

The heart of Fresh Collective. Represents a community united around
a shared purpose.

**Examples**

- The Grove
- EMBODY
- Brush Collective

**Purpose**

Collectives are where belonging happens.

**Relationships**

- Belongs to: one Place (or Online)
- Contains: Pathways, Gatherings, Conversations, Resources, Members

**Has its own page?** Yes.

**Discoverable?** Yes.

---

### Gatherings

Moments where people come together.

**Examples**

- Yoga session
- Retreat
- Workshop
- Community lunch

**Purpose**

Gatherings create real moments of connection.

**Relationships**

- Belongs to: one Collective
- Occurs: Online, In person, or Hybrid

**Has its own page?** Yes.

**Discoverable?** Yes.

---

### Pathways

Guided learning and personal journeys.

**Purpose**

Help members grow.

**Relationships**

- Belongs to: one Collective

**Has its own page?** Yes.

**Discoverability**

Limited. Members may discover that a Pathway exists before joining
a Collective, but its content remains protected unless intentionally
made public.

---

### Creators

People who steward communities.

**Purpose**

Help members understand who is holding the space.

**Relationships**

- May steward multiple Collectives

**Has profile?** Yes.

**Discoverable?** Yes.

---

### Themes

Shared interests that connect otherwise unrelated communities.

**Examples**

- Wellbeing
- Creativity
- Leadership
- Nature

**Purpose**

Help members navigate the world through interests rather than
geography.

**Relationships**

- Connects: Places, Collectives, Gatherings

**Own page?** Eventually.

**Discoverable?** Yes.

---

## Future Discovery Objects

Not required for MVP.

Possible future additions:

- Experiences
- Challenges
- Causes
- Organisations
- Partnerships

These should only become Discovery Objects if they genuinely help
members find meaningful connection.

---

## Discovery Matrix

| Object     | Discoverable | Own Page   | Belongs To         |
|------------|--------------|------------|--------------------|
| Place      | Yes          | Yes        | World              |
| Collective | Yes          | Yes        | Place / Online     |
| Gathering  | Yes          | Yes        | Collective         |
| Pathway    | Limited      | Yes        | Collective         |
| Creator    | Yes          | Yes        | World              |
| Theme      | Yes          | Eventually | World              |

---

## What is NOT a Discovery Object

Some parts of Fresh Collective exist only to support communities.
They should not appear as first-class discovery destinations.

Examples include:

- Resources
- Conversations
- Member profiles (outside appropriate contexts)
- Notifications
- Commerce
- Administration
- Settings

These remain important platform features but are not intended to be
explored independently.

---

## Success

Members should eventually feel like they are exploring a living
world where every discovery naturally leads to another.

    Place    → Collective → Gathering
    Theme    → Collective → Creator
    Creator  → Collective → Place

Rather than reaching dead ends, discovery should continually open
new opportunities for belonging.
