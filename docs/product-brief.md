# Product Brief — Fresh Collective

> **Version history**
> v1 (original): single-creator transformation membership for women, centred on the REAL Journey.
> v2 (current): multi-space experiential learning platform for coaches, educators, facilitators and transformational communities. The REAL Journey remains as the flagship Pathway inside the Fresh Collective Space.

---

## What Fresh Collective Is

Fresh Collective is a creator-enabled experiential learning platform for coaches, educators, facilitators and transformational communities.

It is not a traditional LMS or content vault. It is a platform for **interactive, community-integrated learning experiences** — structured around Spaces, Pathways, and live Events, with community woven through all of it.

The platform is built for **returning learners**, not just sign-up flows. Every design decision should support continuation, depth, and genuine connection over time.

## What Fresh Collective Is NOT

- Not a course library or content vault
- Not a traditional LMS
- Not a social media platform
- Not a coaching marketplace
- Not a productivity tool
- Not a corporate SaaS dashboard

---

## Core Platform Idea

Fresh Collective has three interlocking layers:

**Spaces** — A Space is a creator's home on the platform. It contains Pathways, Community, and Events. The Fresh Collective Space is the flagship. Other creators will have their own Spaces.

**Pathways** — Structured learning journeys inside a Space. Guided, immersive, and designed for behaviour change over information delivery. REAL Journey is one Pathway inside the Fresh Collective Space.

**Community + Events** — Every Space has its own community feed and events calendar. Community is not an add-on — it is central to the learning experience.

The founder's role (and any creator's role) is to be the **architect of experiences**, not the constant presence. The structure holds the community.

---

## Platform Architecture

```
Fresh Collective Platform
 ├── Spaces
 │    ├── Fresh Collective (flagship)
 │    │    ├── Pathways
 │    │    │    ├── REAL Journey (foundation)
 │    │    │    ├── Growth
 │    │    │    ├── Transformation (coming soon)
 │    │    │    └── Essence (coming soon)
 │    │    ├── Community
 │    │    └── Events
 │    └── [Future creator spaces]
 ├── Profiles (learner + creator)
 └── Explore (discover public spaces)
```

---

## The Four Design Principles

### 1. Simple, short, no overwhelm
People do not need more information. They need less, delivered well. Content should be short, digestible, and designed to shift behaviour — not to impress people.

The platform's quality comes from how usable it is, not how comprehensive it is.

### 2. Community is the value
The deepest value is connection: live calls, community posts, shared reflection, and being in it together.

Content is the structure. Community is the heart.

### 3. Behaviour change over information delivery
Every lesson, Pathway, prompt, and live moment should support integration and lived change.

### 4. Optimise for returning, not just signing up
The platform should help learners know where they are, what's next, and what's happening in their community — today.

---

## Brand Feel

The platform should feel:

- Calm
- Immersive
- Intelligent
- Collaborative
- Human
- Alive
- Experiential
- Warm but not soft
- Premium but not cold

NOT:
- Corporate
- Chaotic
- Productivity-obsessed
- Social-media addictive
- Cluttered

_For practical design guidance, see [docs/design-principles.md](design-principles.md)._

## Tone of Copy

**Warm, clear, direct, grounded, emotionally intelligent.**

Speak to one person directly.

Avoid:
- Corporate jargon
- Generic AI language
- Overpromising
- Cold or transactional language

---

## Platform Roles

| Role | Description |
|---|---|
| **Learner** (user) | Joins Spaces, progresses through Pathways, participates in Community and Events |
| **Creator** | Builds and manages one or more Spaces, creates Pathways and Events, moderates Community |
| **Admin** | Platform-level administration, sales pipeline, system management |

A user can be both a Learner in some Spaces and a Creator in others.

---

## Entry Paths

**Path 1 — Space landing page → join Space → begin Pathway**
Someone discovers a Space (e.g. Fresh Collective), joins it, and begins the suggested starting Pathway.

**Path 2 — Direct Pathway entry**
Someone purchases or accesses a specific Pathway directly and is auto-enrolled in its parent Space.

The platform must support both paths.

---

## Version 1 Priorities

1. Space-based architecture in backend (data model, routes, auth)
2. Fresh Collective as the flagship Space with REAL Journey as the foundational Pathway
3. Learner dashboard showing enrolled spaces, current progress, upcoming events, community activity
4. Working auth (login, signup, session, roles: user/creator/admin)
5. Admin sales pipeline (already built)
6. Mobile-responsive design
7. Stripe-ready structure (integration deferred to Phase 8)

## What NOT to Build in v1

- Creator marketplace or creator onboarding flow for third parties
- Complex gamification, badges, streaks
- AI features
- Aggressive social features (likes, reactions, follower graphs)
- Transformation and Essence pathways (Coming Soon only)
- Multi-tenant billing per Space (use platform membership for now)
