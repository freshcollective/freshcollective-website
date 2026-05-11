# Platform Structure — Fresh Collective

> **Version history**
> v1 (original): single-creator platform with REAL Journey, The Rooms, The Heart.
> v2 (current): Space-based multi-creator architecture. REAL Journey is now one Pathway inside the Fresh Collective Space. The Rooms → Pathways. The Heart → Community + Events within a Space.

---

## Site Map

### Public Pages (no login required)

| Page | Purpose |
|---|---|
| `/` — Home | Platform entry point. Communicates the transformation promise. Drives to the FC Space and membership. |
| `/about` — About | The platform's mission, who it is for, the founder's story. |
| `/explore` — Explore | Browse public Spaces and creators. _(v1: shows FC Space only)_ |
| `/spaces/[slug]` — Space Landing | Public-facing Space page. Description, Pathways, Events, join CTA. |
| `/login` — Login | Existing member login. |
| `/signup` — Sign Up | New member registration. |
| `/forgot-password` | Password reset request. |
| `/reset-password` | Password reset form. |

> **Legacy routes (kept during transition):**
> `/real-journey` and `/membership` remain as marketing pages. They will be gradually replaced by `/spaces/fresh-collective` and Space-level purchase flows.

---

### Learner Area Pages (login required)

| Page | Purpose |
|---|---|
| `/dashboard` | Central hub. Enrolled spaces, current progress, next step, upcoming events, community activity. |
| `/spaces` | My Spaces overview. |
| `/spaces/[slug]` | Inside a Space. Home tab: current activity, next step, community highlights. |
| `/spaces/[slug]/pathways` | All Pathways in this Space. |
| `/spaces/[slug]/pathways/[pathway-slug]` | Pathway overview. Step list, progress, description. |
| `/spaces/[slug]/pathways/[pathway-slug]/[step-slug]` | Individual Step. Content, reflection, mark complete. |
| `/spaces/[slug]/community` | Space community feed. Posts, prompts, member reflections. |
| `/spaces/[slug]/events` | Space events. Upcoming live calls, recordings, calendar. |
| `/spaces/[slug]/events/[id]` | Event detail. Description, Zoom link, recording. |
| `/events` | All upcoming events across enrolled Spaces. |
| `/profile` | My profile and account settings. |
| `/profile/[username]` | Public profile view. _(v2 / post-v1)_ |

---

### Creator Area Pages (login required, creator role)

| Page | Purpose |
|---|---|
| `/creator` | Creator studio home. My spaces, quick stats. |
| `/creator/spaces` | Manage my Spaces. |
| `/creator/spaces/new` | Create a new Space. _(post-v1)_ |
| `/creator/spaces/[slug]` | Space management overview. |
| `/creator/spaces/[slug]/pathways` | Create and manage Pathways and Steps. |
| `/creator/spaces/[slug]/community` | Moderate community feed, post prompts. |
| `/creator/spaces/[slug]/events` | Create and manage Events. |
| `/creator/spaces/[slug]/members` | View Space members and enrollments. |
| `/creator/spaces/[slug]/settings` | Space settings (name, description, visibility). |

---

### Admin Pages (login required, admin role — existing)

| Page | Purpose |
|---|---|
| `/admin` | Admin dashboard. |
| `/admin/sales/*` | Sales pipeline: leads, opportunities, subscriptions, pricing, tasks. |

---

## Platform Areas in Detail

### 1. Spaces

A Space is a creator's home on the platform. It is the primary container for all learning content, community, and events.

**Structure:**
- One creator owns a Space (though moderators can be added)
- A Space contains: Pathways, Community feed, Events
- A Space can be public (discoverable) or private (invite/purchase only)
- The Fresh Collective Space is the platform's flagship, owned by the platform admin

**V1 constraint:** Only the Fresh Collective Space is active. Creator space creation for third parties is post-v1.

---

### 2. Pathways

Pathways are structured learning journeys inside a Space. They replace what was previously called "The Rooms" and also encompass the REAL Journey.

**REAL Journey** is now one Pathway within the Fresh Collective Space — the foundational, recommended starting point.

**Fresh Collective Space Pathways (v1):**

| Pathway | v1 Status | Description |
|---|---|---|
| **REAL Journey** | Active | Foundation pathway. Four phases: Recognise, Explore, Align, Lead. |
| **Growth** | Active | Self-awareness, Self-trust, Uniqueness. |
| **Transformation** | Coming Soon | Embodiment, Vision, Purpose. |
| **Essence** | Coming Soon | Harmony, Creativity, Manifestation. |

**Pathway structure:**
- Overview and description
- Ordered Steps (or unordered, creator-configurable)
- Each Step: content (text, video, reflection, exercise, audio), estimated time
- Progress tracking per learner (simple, not gamified)
- Reflections attached to Steps

**Key rule:** Pathways should feel guided and immersive, not like a content library to browse. Surface one clear next step at all times.

---

### 3. Community

Every Space has its own Community feed. This replaces what was previously called "The Heart."

**Components:**
- Posts (prompts, reflections, discussions, announcements)
- Comments/replies on posts
- Pinned posts from creators
- Clean, calm feed (chronological or creator-curated)

**Rules:**
- No complex social graph (no followers, no likes/reactions in v1)
- Creator is not available 24/7 — the structure holds the community
- Do not build features that create creator burnout

---

### 4. Events

Every Space has its own Events area. Live experiences were previously called "The Heart" (monthly live calls). Now they are a first-class Space feature.

**Components:**
- Upcoming Events list (live calls, workshops, sessions)
- Event detail (description, date/time, Zoom link when available)
- Recording archive (past events with recording URL)
- Calendar view _(post-v1)_

---

### 5. Profiles

**Learner profile:** Name, avatar, bio, enrolled Spaces.
**Creator profile:** Display name, bio, avatar, website, public Space listings.

Profiles are post-v1 for the public-facing view but the data structure is built from the start.

---

## Member Dashboard — Spec (v2)

The dashboard is the learner's home. It should show them exactly what to do next and make re-engagement effortless.

**Required elements:**
- Welcome message (personalised with name)
- Continue where you left off (most recent Pathway progress, deep link to next Step)
- My Spaces (enrolled Spaces, with status indicators)
- Upcoming Events (next event across all enrolled Spaces)
- Community highlights (recent activity from enrolled Spaces)

**Layout rules:**
- One clear call to action at the top
- Uncluttered — not everything at once
- Mobile-responsive
- Optimise for returning users, not first-time onboarding

---

## Access Model

| Content | Public | Learner | Creator | Admin |
|---|---|---|---|---|
| Home, About, Explore | Yes | Yes | Yes | Yes |
| Space landing pages (public Spaces) | Yes | Yes | Yes | Yes |
| Space content (Pathways, Community, Events) | No | If enrolled | If owns Space | Yes |
| Dashboard | No | Yes | Yes | Yes |
| Creator studio | No | No | Yes | Yes |
| Admin panel | No | No | No | Yes |

---

## Entry Path Logic

**Path 1 — Space landing → join → begin Pathway:**
1. User lands on `/spaces/fresh-collective`
2. Joins the Space (free or paid)
3. Lands on dashboard → directed to REAL Journey Pathway
4. Progresses through Steps, then moves to other Pathways

**Path 2 — Direct Pathway access:**
1. User purchases or is granted access to a specific Pathway
2. Auto-enrolled in the parent Space
3. Begins at Step 1 of that Pathway

The platform must support both paths.

---

## Technical Stack

| Layer | Technology |
|---|---|
| Framework | Next.js (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Auth | JWT sessions (httpOnly cookies), bcrypt, jose |
| Backend API | FastAPI (Python) |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Database | PostgreSQL (local: fc_prod) |
| Payments | Stripe (integration deferred to Phase 8) |

---

## Data Model

### Core entities

| Entity | Purpose |
|---|---|
| `users` | All platform accounts (learners, creators, admins) |
| `creator_profiles` | Extended profile data for creator-role users |
| `password_resets` | Password reset tokens |

### Space entities

| Entity | Purpose |
|---|---|
| `spaces` | A creator's Space on the platform |
| `space_memberships` | User access relationship to a Space (role: learner/moderator/creator) |

### Learning entities

| Entity | Purpose |
|---|---|
| `pathways` | Structured learning journeys within a Space |
| `pathway_steps` | Individual steps/units within a Pathway |
| `enrollments` | A learner's relationship to a Pathway |
| `step_progress` | Completion records for individual Steps |

### Experience entities

| Entity | Purpose |
|---|---|
| `events` | Live experiences within a Space |
| `community_posts` | Posts in a Space's community feed |
| `post_comments` | Replies to community posts |

### Business entities (existing, unchanged)

| Entity | Purpose |
|---|---|
| `subscription_plans` | Membership product records |
| `subscription_prices` | Versioned pricing |
| `member_subscriptions` | Per-user subscription records |
| `sales_leads` | Sales pipeline prospects |
| `sales_opportunities` | Individual deals |
| `sales_activities` | Interaction log |
| `sales_tasks` | Follow-up tasks |
