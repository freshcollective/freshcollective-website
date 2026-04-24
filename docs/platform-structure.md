# Platform Structure — Fresh Collective

## Site Map

### Public Pages (no login required)

| Page | Purpose |
|---|---|
| `/` — Home | Brand entry point. Communicates the transformation promise. Drives to REAL Journey and Membership. |
| `/about` — About Fresh Collective | The founder's story, the platform's mission, who it is for. |
| `/real-journey` — REAL Journey Sales Page | Positions REAL Journey as a low-cost standalone entry product. Leads to purchase or membership. |
| `/membership` — Membership Sales Page | Full membership offer. What members get, how it works, pricing. |
| `/login` — Login | Existing member login. |
| `/signup` — Sign Up | New member registration (linked from purchase flow). |

### Member Area Pages (login required)

| Page | Purpose |
|---|---|
| `/dashboard` — Member Dashboard | Central hub. Welcome message, current progress, next step, upcoming live call, community prompt. |
| `/start-here` — Start Here / REAL Journey | Overview of REAL Journey. Entry point for new members. |
| `/start-here/[phase]` — REAL Phase | Individual phase view (Recognise, Explore, Align, Lead). Lessons, prompts, progress. |
| `/the-heart` — The Heart | Live Layer home. Monthly call card, current theme, integration threads. |
| `/the-heart/calls` — Live Calls | Call calendar, upcoming call card, Zoom link, past call archive. |
| `/the-rooms` — The Rooms | Pathway overview. Growth (live), Transformation and Essence (Coming Soon). |
| `/the-rooms/growth` — Growth Pathway | Growth pathway overview. Three rooms: Self-awareness, Self-trust, Uniqueness. |
| `/the-rooms/growth/[room]` — Growth Room | Individual room view. Description, lessons, next steps. |
| `/community` — Community | Feed, prompts, member reflections, discussion threads. |
| `/profile` — Profile / Account | Member account settings, membership status, notification preferences. |

---

## Platform Areas in Detail

### 1. START HERE — REAL Journey

The foundational experience. Every member begins here regardless of entry path.

**REAL stands for:**
- **Recognise** — seeing clearly what is true right now
- **Explore** — getting curious about patterns, needs, and desires
- **Align** — connecting with values and what matters
- **Lead** — moving forward from a grounded place

**Structure per phase:**
- Short overview (not a long module)
- Bite-sized lessons or steps
- Reflection prompt(s)
- Integration action
- Progress tracking (simple — not gamified)

**Key rule:** Members can return to REAL Journey at any time. It is not a one-time course.

---

### 2. THE HEART — Live Layer

The primary value of the membership. Must feel central, not like an add-on.

**Components:**
- Monthly live call (one per month, Zoom)
- Integration threads (async discussion after each call)
- Community prompts (push notification + in-app)
- Current monthly theme
- Community group chat / space

**Founder boundaries (build to support these):**
- Not available 24/7
- Not a 1:1 coaching relationship
- The platform structure holds the community, not the founder's constant presence

---

### 3. THE ROOMS — Pathways

Where members go deeper after REAL Journey. Based on **The Natural Leader Model**.

**Three top-level pathways:**

| Pathway | Rooms | v1 Status |
|---|---|---|
| **Growth** | Self-awareness, Self-trust, Uniqueness | Build fully |
| **Transformation** | Embodiment, Vision, Purpose | Coming Soon |
| **Essence** | Harmony, Creativity, Manifestation | Coming Soon |

**Growth Pathway — v1 structure:**
- Pathway overview page
- Three room pages (Self-awareness, Self-trust, Uniqueness)
- Each room: description, content placeholder, suggested next steps
- Early structure only — content to be added progressively

---

### 4. COMMUNITY

Makes members feel part of something alive, not just logging into a content library.

**Components:**
- Simple feed (most recent first)
- Prompt cards (structured prompts from the founder)
- Member reflections (responses to prompts)
- Discussion threads (tied to live calls and REAL phases)
- Clean posting UI

**Rule:** Keep it simple. Do not overbuild. No complex social features in v1.

---

## Member Dashboard — Final Spec

The dashboard is the member's home. It should be calm, uncluttered, and action-oriented.

**Required elements:**
- Welcome message (personalised with member's name)
- Current journey progress (REAL Journey phase indicator)
- Next step card (one clear action)
- Upcoming live call card (date, time, Zoom link when available)
- Latest community prompt
- "Continue REAL Journey" button
- Pathway cards (Growth: active, Transformation + Essence: Coming Soon)

**Layout rules:**
- Uncluttered — not everything at once
- Calm visual hierarchy
- Mobile-responsive

---

## Access Model

| Content | Public | Member |
|---|---|---|
| Home, About, Sales pages | Yes | Yes |
| REAL Journey (full platform) | No | Yes |
| The Heart (Live Layer) | No | Yes |
| The Rooms / Pathways | No | Yes |
| Community | No | Yes |
| Dashboard | No | Yes |
| REAL Journey (standalone product) | Purchasable separately | Included |

---

## Entry Path Logic

**Path 1 — REAL Journey first:**
1. User lands on `/real-journey` sales page
2. Purchases REAL Journey standalone
3. Gets access to `/start-here` only
4. On completion, invited to join full membership
5. On joining, gains access to full member area

**Path 2 — Membership first:**
1. User lands on `/membership` sales page
2. Joins full membership
3. Lands on dashboard → directed to Start Here (REAL Journey)
4. Completes REAL Journey, then moves to The Rooms and The Heart

The platform must support both paths from day one.

---

## Technical Stack

| Layer | Technology |
|---|---|
| Framework | Next.js (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Auth & Database | Supabase |
| Payments | Stripe |
| Architecture | Component-based, mobile-responsive, accessible |

**Notes:**
- Supabase auth and database should be architected from Phase 3 onwards, even if not fully implemented
- Stripe integration should be clearly marked in the codebase even if deferred
- All placeholder integration points should be clearly commented

---

## Future Data Model

The following entities will eventually exist. Note for architects: do not build the full schema in v1 — but structure the codebase so these can be added without major refactoring.

| Entity | Purpose |
|---|---|
| `users` | Member accounts |
| `memberships` | Membership tier and status |
| `journeys` | REAL Journey definition |
| `phases` | REAL Journey phases (R, E, A, L) |
| `lessons` | Content within each phase |
| `reflections` | Member-written reflections |
| `pathways` | Growth, Transformation, Essence |
| `rooms` | Individual rooms within pathways |
| `live_calls` | Call records, dates, Zoom links |
| `community_posts` | Member posts in community feed |
| `comments` | Replies to posts or threads |
| `progress` | Per-member progress tracking |
