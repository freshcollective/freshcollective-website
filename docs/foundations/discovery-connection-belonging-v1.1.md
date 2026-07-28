# Fresh Collective — Discovery, Connection & Belonging

*A foundational design document.*

*Version 1.1 — 2026*

---

## Preface

This document is not a plan. It is a compass.

It exists so that, in three years, when someone proposes a new feature for the platform's outward or relational surfaces, we can open this document, hold their proposal up to it, and know instantly whether it strengthens Fresh Collective or dilutes it.

The right measure of this document is not how well it describes the next quarter of work. It is how well it prevents the wrong work over the next decade.

**And it exists to name what all of this is for.** Discovery, Places, Shared Experiences, Ways to Connect, Journey Together, Local Circles — every surface named in these pages serves the same deeper purpose: to help people find, over time and in their own way, where they belong. Belonging on Fresh Collective is not a milestone. It can be momentary or enduring, quiet or profound. Our role is to create the conditions in which those experiences can emerge, and then to step back.

Please read it slowly.

---

## Part One — Philosophy

### The deeper purpose

Fresh Collective exists to help people find where they belong.

That sentence carries more weight than it looks like it does. Belonging is not a metric. It is not a status. It is not something Fresh Collective can measure — and it is certainly not something the platform manufactures. Belonging is what happens *to* a person, over time, when the conditions around them are right: real communities to walk into, real places that hold something for them, real fellow travellers on the same path.

Fresh Collective's job is to create those conditions. Nothing more, nothing less.

### The two questions the platform must answer

Every meaningful surface on this platform helps a member answer one of two questions.

The first is **"Where might I belong?"** — the outward question. What communities exist? What places hold something for me? What is happening this week? What pathway could I walk? This is the domain of **Discovery**, and it is held by two of our four destinations: **Explore Collectives** (belonging through purpose) and **Discover Places** (belonging through geography).

The second is **"Who do I belong alongside?"** — the sideways question. Who else is walking this pathway? Who else was at that gathering last Sunday? Who else lives in my city and moves in the same rhythms as I do? This is the domain of **Connection**, and it is held by **Ways to Connect**.

These are not the same question. Discovery is about the world containing me. Connection is about the people beside me. Treated as one, they collapse into a feed. Kept distinct, they become two lenses that a member can pick up separately, at their own pace.

The fourth destination — **Your World** — is neither Discovery nor Connection. It is the *reflection of belonging already established*: everything a member has said yes to. The four destinations together give members multiple meaningful ways to enter the world, without ever prescribing a path.

Fresh Collective's role, in all of this, is to *invite* — never to demand, count, or optimise for return visits.

### What this is not

Naming what a thing is not is often more useful than naming what it is. This vision is not:

- **A feed.** No algorithmic ordering, no "what you missed," no doomscroll surface. What Fresh Collective shows must be *worth being shown*, or it should not be shown.
- **A social network.** No follows, no followers, no friend lists, no "people you may know." Membership of collectives is public; friendship is private and not our concern.
- **A directory of people.** Members are not browsable as objects. The word *profile* describes a page a member owns for themselves, not a card in someone else's search results.
- **A recommendation engine.** No opaque "you might like." Every surface must be able to answer honestly: *why am I seeing this?* — and the answer must be a shared thing or a human decision, not a model.
- **An attention product.** No streaks, no notification bait, no "you haven't opened Fresh Collective in a week" emails. The purpose is not to bring people back to the app; the purpose is to send them into a life richer than the app.

### The core reversal

Most software is built on an *attention* model — capture attention, hold it, extract value from it. Fresh Collective is built on a **release** model — help members find something worth their real-world attention, then step out of the way.

Every design choice on these surfaces should reinforce this reversal. If a decision would work equally well in an attention product, we're probably making the wrong choice.

---

## Part Two — Design Principles

The following eight principles are load-bearing. When they conflict with a feature idea, the feature loses.

### 1. Celebrate meaning, never manipulate attention

A gathering starting tomorrow. A pathway published. A member accepting Journey Together. A Local Circle forming. These are moments worth marking — quietly, once, in the member's own space. **Recent Moments** is the healthy expression of this: it names what happened, honours it, and moves on.

What we never do is engineer the noticing. No unread counts on outward surfaces, no red dots, no "you have 12 new recommendations," no streaks, no re-engagement prompts, no notification bait. The test is intent: are we surfacing something because it matters to the member, or because it serves our metrics? If the latter, we don't do it — no matter how well it would perform.

A member should be able to look at any Discovery or Connection screen for two seconds and close it without feeling behind. That is the whole shape of the promise.

### 2. Show, don't count

Rich shared context beats numeric social proof, always. Prefer *"Emma walked Life in Alignment last winter"* to *"3 people you know completed this."* Prefer *"18 people from EMBODY are in Melbourne"* to *"18 members near you."* Numbers are the crudest social signal available. We use them only when they answer a specific practical question — how many seats remain at a gathering; is a pathway small enough that my presence matters.

### 3. Return people to life

Every screen has a way *out* — into a gathering, into a walk, into a conversation with the person next to them. The best Discovery outcome is not "the member spent nine minutes on the map." It is "the member closed the map, drove to the beach, and met four strangers who now know their name."

### 4. Emergence over engineering

Communities appear when they are ready. The platform's role is to notice conditions, hold them lightly, and offer — never to instantiate. Local Circles are the clearest example: we do not create them, we suggest that they *could* be created, and we let a human decide.

### 5. Trust human curation over automated optimisation

When there is a choice between a person making the call or a system making it, Fresh Collective picks the person. Every Place gets its editorial voice from a human. Every featured position on Explore Collectives is decided, not scored. When a Local Circle forms, a person says yes. Technology's role is to notice conditions, surface options, and make the human decision easy — never to make the decision itself.

Recommender systems, ranking algorithms, and behavioural inference are not the future of Fresh Collective. They are the wrong shape. Members feel — even when they can't name it — the difference between a page a person made and a page an optimiser assembled. The former belongs to a living community. The latter belongs to a product.

### 6. One place, one purpose

Discovery surfaces do not blur into activity feeds. Connection surfaces do not blur into messaging. Discover Places is not a marketplace. Ways to Connect is not a follower graph. Each destination answers exactly one question, and members always know which question they walked into.

### 7. Quiet by default

The tone of every notification, empty state, invitation and moment should be closer to a librarian than to a salesperson. Recent Moments already sets this tone — extend it. When in doubt, remove a word, soften a colour, drop a badge.

### 8. Anonymity is a feature

Recognition does not require full disclosure. A member should be able to be on this platform without a photo, without their real name, without geolocation, and still find their people. Every place we ask for more, we ask ourselves whether the ask is proportional to the value returned.

### Explicitly avoided

Also load-bearing — the mechanisms we will not build, however well they would perform:

- Follow / unfollow / followers, in any form or with any renaming.
- Public activity feeds ("Emma just joined The Grove!").
- View counts, reaction counts, "hot," "trending," any leaderboard-shaped surface.
- "People also joined…" cross-selling.
- Push notifications for anything that isn't time-critical.
- Streaks, badges, levels, XP, any gamified accumulation.
- GPS-level location. Only city-scale, only opt-in.
- Behavioural inference, lookalike models, algorithmic scoring of members or content.
- Onboarding funnels with a defined "success."
- Any feature whose primary metric is DAU or session length.

This list is not the negation of engagement — engagement with the meaningful is the point of the whole platform. This list is the negation of *attention manipulation*: the mechanics that extract engagement from members who would not have given it freely.

---

## Part Three — Information Architecture

### Four peer destinations

Fresh Collective has four top-level destinations. They are peers. No one of them is subordinate to another; none is buried inside a shelf. Each answers a different question, and a member should always know which question they walked into.

```
      ┌────────────┐    ┌───────────────────┐    ┌────────────────┐    ┌─────────────────┐
      │            │    │                   │    │                │    │                 │
      │ Your World │    │ Explore           │    │ Discover       │    │ Ways to         │
      │            │    │ Collectives       │    │ Places         │    │ Connect         │
      │            │    │                   │    │                │    │                 │
      └─────┬──────┘    └─────────┬─────────┘    └───────┬────────┘    └────────┬────────┘
            │                     │                      │                      │
    Belonging already      Belonging through      Belonging through      Belonging alongside
        established             purpose               geography              other people
     (the reflection)       (Discovery door)      (Discovery door)      (Connection door)
```

**Your World** — everything a member has said yes to. Collectives they belong to, pathways they're walking, gatherings they've booked, Recent Moments from all of it. Inward. Present-tense. This destination is settled.

**Explore Collectives** — communities of shared purpose, browsable by what they gather around. The door for members who think in themes. Retained by name for continuity with what members already know.

**Discover Places** — the geography of Fresh Collective. Where collectives live, where gatherings are happening, what exists near me or where I am travelling. The door for members who think in places. Map-first, editorial-second.

**Ways to Connect** — the destination for meaningful relationships that grow through shared experiences. The door for members who think in people. It works through *recognition*: when two members share something real — a pathway walked, a gathering attended, a place lived in — the platform names that quietly, in context, when it matters. Ways to Connect exists as a destination *from day one*, even before a member has accumulated any shared experiences (see Roadmap).

### How the four relate

Not a hierarchy. A constellation.

- **Discover Places contains collectives, but does not own them.** A collective may be tied to one place, several, or none. Places is a *lens* on collectives, not a taxonomy.
- **Explore Collectives contains shared experiences, which create relationships.** A member walks a pathway; a member attends a gathering; those experiences become the substrate that Ways to Connect draws on.
- **Ways to Connect surfaces people, but does not host them.** It never becomes a "profile browser." It always leads back into a shared context — a gathering to book, a message to send inside a collective, a Local Circle to co-found.
- **Your World is fed by all three.** As a member's belonging deepens on any of the outward destinations, Your World grows correspondingly. It is not a source; it is a reflection.

This shape prevents each destination becoming a version of the others. Places is never a "list of members near you." Explore Collectives is never a map. Ways to Connect is never a directory.

### How members move between them

There is no linear path. The IA must support all of the following, without designing any of them explicitly:

1. **Location first.** Discover Places → my city → a collective → a gathering → recognise another attendee → Ways to Connect notices they've walked the same pathway → they meet.
2. **Purpose first.** Explore Collectives → resonates → join → walk a pathway → Ways to Connect surfaces a fellow walker → learn (Discover Places) they're in the same city → coffee.
3. **Person first.** Invited by a friend → their collective → notice its place → Discover Places shows other collectives there → join a second → find the first friend is there too.
4. **Wander first.** No purpose today → open any door → drift → find a place, a theme, a Local Circle, or nothing → close the tab → come back tomorrow.

Every one of these paths must feel natural. None of them are more valid than the others. The role of the IA is to make sure a member on any of these paths never hits a dead end.

---

## Part Four — Conceptual Models

The design vocabulary underneath the surfaces. When these words are used in Fresh Collective documents, meetings, and code, they mean these things.

### Places

A **place** is a real-world location that at least one meaningful thing on Fresh Collective happens inside. Cities are the default granularity — big enough that a member can plausibly travel to one, small enough that the map isn't a slurry of markers. Regions (Northern Beaches, Byron Shire) are used only when a city is too coarse. Countries are used only for the traveller-mode top-level view.

A place is not a taxonomic tag, not an address, not a filter, and not a group. A place is a *shared context* that many things sit inside.

**Every place has a voice.** From day one, every place with meaningful activity carries one honest sentence, written by a person — *"Melbourne is home to communities centred around movement, women's wellbeing, creativity and nature."* This voice is what distinguishes Discover Places from a directory. When there is nothing honest to say about a place, that sentence is absent; it is never filled with generic copy or auto-generated summary. The presence of the voice is the promise; the absence of it is the honesty.

Places are curated, not crowdsourced. The platform decides what constitutes a place; members do not add new ones. This keeps the map calm and prevents the tragedy of a hundred pins in a hundred suburbs.

### Communities (Collectives)

A **collective** is a container of shared purpose. It has a creator, a name, a philosophy, and rituals (pathways, gatherings, conversations, resources). This model is well-defined in the existing product; nothing here changes it.

Two properties matter for these surfaces specifically:

- A collective may inhabit **zero or more places**. Most are single-place today. Some are placeless (a global online-only community). Some will be multi-place as the platform matures.
- A collective has a **kind** — most are creator-led; **Local Circles** are peer-led. This is not a schema distinction, it is a social one. Both are the same object.

### Relationships — two shapes

The most careful distinction in this document. Fresh Collective holds two kinds of relationship, and they are not variants of each other.

#### Recognition (derived, contextual, ephemeral)

**Recognition** is the surface act of noticing that two members share something real — a pathway walked, a gathering attended, a place lived in, a collective belonged to.

Recognition is not stored. There is no "friendship" table, no "following" edge. A recognition is *derived*, at read time, from the shared things two members already have. This is a deliberate architectural choice: it means every recognition is anchored to something real, and it means no one can accumulate recognitions as a status.

Recognition surfaces in context, when relevant, and then subsides:

> *"Emma has walked this pathway too."*
> *"You were both at Thursday's gathering."*
> *"You both belong to Melbourne EMBODY."*

Whether the member does anything about the recognition is entirely up to them. The platform's job is to notice, once, quietly.

The atomic units of recognition are **shared experiences**: pathway enrolments, gathering bookings, collective memberships, city co-residency. The system does not weight or rank these; it presents them plainly, and members decide for themselves what carries meaning.

#### Journey Together (intentional, mutual, persistent)

**Journey Together** is different in kind. It is the one place on Fresh Collective where a relationship is *stored*, because it is the one place where two members have consciously agreed to walk something together.

Two members walking the same pathway may (either of them) offer to journey together. The other accepts, or does not. If both say yes, Fresh Collective records that they are journeying together — for that pathway, for that season. Each can see the other's progress. Each can reach the other. When the pathway is complete, or either party ends it, the record ends too. It never accumulates into a follower count or a friend list.

This is the opposite of a follow. A follow is one click and no consent from the other party. A Journey Together is two consenting yeses and a bounded shape.

Journey Together does not weaken the "no follows" principle — it strengthens it. It shows that we're not afraid of stored relationships; we're afraid of *unearned* ones. Intentional, mutual, bounded human agreement is the most valuable thing on the platform, and it deserves to be persisted.

### Discovery

**Discovery** is not search. Search is what a member does when they know what they want. Discovery is what a member does when they do not — when they open a shelf, glance across it, and let something catch their eye.

Discovery on Fresh Collective is:

- **Editorial** — human decisions inform what is featured, not popularity scores.
- **Local when possible** — nearby places, nearby collectives, nearby gatherings, unless the member signals otherwise.
- **Honest** — every card carries the reason it's there. No opaque personalisation.
- **Finite** — a Discovery surface has an end. You can reach the bottom. There is no infinite scroll.

### Shared Experiences

The atomic unit of Connection, and the substrate of Recognition. A **shared experience** is any event two or more members were both inside — both enrolled in the same pathway; both attending the same gathering; both belonging to the same collective; both in the same Local Circle; both living in the same place.

These are the only signals Ways to Connect draws on. There is no clever behavioural inference, no "you seem to like…" heuristic. If two members haven't been in something together, the platform has nothing to say about their relationship — and stays silent.

### Local Circles

**Local Circles are collectives.** Not a separate feature, not a separate table, not a separate onboarding. They differ only in social shape: peer-led (no single creator, or a rotating one), free, small (dozens, not hundreds), and place-anchored (one city, always).

Because they are collectives, everything Fresh Collective builds for collectives — pathways, gatherings, conversations, resources — is available to Local Circles by default. Because they are peer-led, the *tone* is different: closer to a book club, further from a taught programme.

The platform's role with Local Circles is limited to two things: **naming what they are** so members recognise the shape, and **suggesting when conditions are ripe** for one to form — always as an offer, never as a task.

### Belonging

The deeper purpose these models serve. Belonging is not a schema object; it is not a state; it is not something the platform can grant. It is what a member experiences when the conditions are right around them — a community they recognise themselves in, a place that holds something for them, fellow travellers on the same path.

Belonging can be momentary or enduring, quiet or profound. A member may belong deeply to one collective for years, or lightly to three collectives for a season. Both are legitimate. Fresh Collective's role is not to define what belonging should look like for any member. It is to create the conditions — Places to explore, Collectives to consider, Recognitions to notice, Journeys to walk with another — in which belonging can emerge on its own terms.

---

## Part Five — User Experience

There is no single journey. There are patterns that recur.

### The wandering member

Someone opens Fresh Collective on a Wednesday evening with no goal. They tap Discover Places. The map is quiet — a few soft markers around their city. They tap Melbourne. They read one honest sentence about what Melbourne holds. They see three collectives, described in the collectives' own voices, not marketing copy. They read one that resonates. They don't join. They close the tab.

**This is a success.** The platform did what it was for. It did not measure anything. It did not send them a follow-up email. When they open Fresh Collective again in three weeks, the same page welcomes them with the same tone, and this time they might say yes.

### The pathway walker

A member is halfway through Life in Alignment. On the step page there is a small line, quiet, above the fold: *"Emma is walking this pathway too."* No button, no CTA — just recognition. Below the step content, at the end of the reflection, a second line: *"Would you like to hear from other walkers?"* Yes → they see three other names, in the same collective, on the same step. No → the line does not appear again.

**Recognition is offered once, in context, at a moment of shared vulnerability.** It never becomes a persistent tab, a counter, or a notification.

Later, one of those walkers offers Journey Together. The member accepts. From that point on, both see a small quiet marker on the pathway page — *"You're journeying with Emma"* — and each can reach the other. When either finishes the pathway, or either ends the journey, the marker ends too.

### The traveller

Someone is going to Byron Bay for a week. They open Discover Places, tap the search icon (the only overt search on the discovery surfaces), and type Byron. They see two collectives, one gathering while they'll be there, and a note: *"18 members from your collectives will be here at the same time."* They book the gathering. They message no one. They arrive at the gathering. They recognise a face from Your World.

**The platform surfaced the shared context; the meeting happened in the room.** No app-mediated handshake, no "check in," no post-event "connect" prompt.

### The new arrival at Ways to Connect

A member has just joined Fresh Collective. They have no shared experiences yet. They tap Ways to Connect out of curiosity. The page shows:

> **Meaningful relationships in Fresh Collective grow through shared experiences.**
>
> Attend a gathering. Walk a pathway. Join a conversation. Over time, you'll begin to recognise fellow travellers here — quietly, in context, when it matters.

Nothing on the page is broken. Nothing is empty in a way that feels like a placeholder. **The empty state is the message**, and the message is a promise the platform intends to keep.

Six weeks later, the same page has three or four small quiet lines on it. Each one names a shared thing. The member reads them, follows one, and finds themselves in a conversation.

### The creator

A creator publishes a new pathway. A member of their collective sees a card on Your World: *"A new pathway is available."* A Recent Moment, not a push notification. The member also receives an email if their Stay Connected preferences say so. That is the extent of the creator's amplification tools — no ability to promote, boost, or feature.

**Reach is a function of belonging, not of purchasing.**

Over time, the creator sees which collectives adjacent to theirs appear on Discover Places, and their sense of Fresh Collective as an ecosystem — not a walled garden — grows.

### The Local Circle organiser

Someone opens their collective's page. A small line appears near the footer: *"There are 18 members of EMBODY in Melbourne who haven't met in person yet."* Below it: *"Would you like to start a Melbourne EMBODY circle?"* They tap yes. Fresh Collective creates a **new collective** — free, place-anchored, peer-led — and puts them in as the founding member. It emails the other 17 members with a soft invitation.

Twelve say yes. Six do not. The Local Circle now exists as any other collective. When new EMBODY members appear in Melbourne over the following year, they see the circle in Discover Places and can join.

**Emergence was noticed, held, and released.** The platform did not do the organising work. It made the organising work possible.

### The reflective member

Six months in, a member opens Your World and, in a quiet moment, notices Recent Moments has drifted. It's showing them things that matter less than they used to. They go to Stay Connected. They mute a collective. Nothing on Fresh Collective punishes them for muting. Their journey continues.

**Attention is a gift they give us; we treat it as such.**

---

## Part Six — Future Opportunities

Ideas that align with the philosophy and could be built if and when they earn the space. Deliberately underspecified — this section is a compass reading, not a design brief.

### Traveller Mode

A single toggle in Discover Places: *"I'm visiting somewhere else."* Sets a temporary place-of-interest for a bounded period. Shows the same page, centred elsewhere, with the *"members from your collectives who will be here"* signal amplified. Auto-expires. Does not update the member's home location.

### Deeper editorial Places pages

Every place with meaningful activity already has its one honest sentence from day one. Some places may in time earn richer editorial pages — a photograph, a curated handful of collectives, a rolling list of upcoming gatherings, a short paragraph written by a human. Cadence closer to a slow blog than a content operation. A city with no story to tell keeps the single sentence, or has none.

### Journey Together as a Phase-2 build

The concept is settled (see Part Four). The implementation is a Phase-2 concern: what surfaces host the offer; how offers appear and expire; how progress is shared; how a journey ends gracefully. When we build it, the model in Part Four is the constraint.

### Shared calendars

A member's Your World could contain a quiet weekly view: *"Here's what's happening in the collectives you belong to this week."* Not aggregated across the whole platform — that would tip into a feed. Only across the member's own places of belonging. Optional. Off by default until proven.

### Local Circle patterns library

A curated set of very light templates — a *reading circle*, a *walking group*, a *shared practice* — a would-be organiser can adopt when starting a Local Circle. Not scripts, not gamified paths — just examples of what has worked in other places, told plainly.

### Cross-collective resonance

When a member is deeply engaged in one collective, the platform could quietly note collectives that other members-in-similar-shape belong to, and offer that as a gentle *"you may find kinship here."* Only if the pattern is real. Only when a person has decided the pattern is worth surfacing. Never as a recommendation carousel.

### Away Mode

An explicit *"I'm resting from Fresh Collective for a while"* setting. Silences everything. Doesn't mark the member as unavailable to their collectives — they simply stop being reached. Ends when the member returns. **A rare feature in modern software; deeply aligned with the release model.**

---

## Part Seven — Implementation Roadmap

Four phases, ordered by dependence. Each phase should feel *finished* before the next begins — we would rather ship one calm surface than three anxious ones.

### Phase 0 — Foundation

Work that no member sees, but everything else depends on.

**Data foundations:**
- A canonical **Places** table (curated, editorial, single source of truth for place names and boundaries).
- A **collective ↔ place** relationship (many-to-many, nullable — a collective may be placeless).
- A **kind** attribute on collectives (creator-led vs. peer-led / Local Circle) — a small, honest tag, not a taxonomy explosion.
- A **shared experience** derivation layer — a small set of read-time queries that answer *"what have these two members been in together?"* Draws from existing pathway enrolments, gathering bookings, collective memberships. No new storage.

**IA foundations:**
- The four peer destinations are introduced in nav: Your World, Explore Collectives, Discover Places, Ways to Connect. Ways to Connect exists from this phase — even if its content is entirely the empty-state message (see MVP).

Phase 0 is invisible on purpose. It buys us the vocabulary to build the rest without renaming things later.

### Phase 1 — MVP

Three things visible to members. All must ship together — the empty destinations that come later are what turn the platform from a set of tools into an ecosystem.

**Discover Places (v1):**
- A single map-first page.
- Curated pins for cities where Fresh Collective has ≥1 collective.
- **Every active city carries its one honest editorial sentence, written by a person, from day one.** Cities without a sentence are not shipped; they either get the sentence or they don't appear.
- Tapping a city reveals: the collectives that inhabit it, upcoming gatherings there, the editorial sentence.
- Default centred on the member's stored city (opt-in only, city-granularity only).
- No account of "members near me" — that's a Ways to Connect concern.

**Ways to Connect (v1):**
- The destination exists in nav from the day the platform ships this pillar.
- For new members with no shared experiences: the empty state renders the promise, in the platform's calm voice. This empty state is a first-class design object, not a placeholder — it may sit at the destination for months for new members, and it must be beautiful and honest enough to stand there without apology.
- For members with shared experiences: quiet in-context recognitions appear on the surfaces where they matter most — on a pathway step ("N others are walking this"), on an upcoming gathering ("You know K attendees from other collectives"), on a member's own collective page ("J members from this collective live in your city"). Each surface is a single quiet line. Ways to Connect the *destination* organises these into a page listing recent recognitions, so a member can also arrive at them directly.

**Explore Collectives:** unchanged in this phase from its existing form. Improvements evolve separately from this pillar.

MVP explicitly excludes: Journey Together (its concept is documented in Part Four; the build is Phase 2); Local Circle emergence prompts; Traveller Mode; deeper editorial Places pages.

**How we know MVP is done:** a member can walk into any of the four destinations, understand what it is for within two seconds, and either find something real or read a promise they believe. Not one member on a demo — a real member on their own.

### Phase 2 — Later enhancements

Once MVP is in real hands and has settled, the enhancements below each earn their own consideration:

- **Journey Together (v1).** Building the concept from Part Four into surfaces. Where the offer appears; how it's accepted; how it ends. Small, opt-in, contextual — the specification is deliberately narrow to prevent scope drift.
- **Local Circle emergence prompts.** Notice conditions (N members from a shared collective, in a shared city, none in an existing Local Circle for that combination) and offer once. Do not repeat the offer.
- **Traveller Mode** as a single opt-in in Discover Places.
- **Deeper editorial Places pages** for the busiest handful of cities.
- **Cross-collective resonance** cards on Your World — gentle, honest, dismissible.

Each is a separate design decision, informed by what we learn from MVP.

### Phase 3 — Aspirational

Long-horizon ideas that could be beautiful *if* the platform, the community, and the culture are ready:

- **Away Mode** — full communication silence with grace.
- **Shared calendars** on Your World.
- **A small human Places editorial cadence** — occasional, slow, hand-written.
- **Curated cross-place pieces** — *"Members of EMBODY in Melbourne have also loved these Sydney collectives"* — built on real shared experiences and a human's judgement, not lookalike modelling.

Aspirational items are on the compass, not on the roadmap. They exist here so we recognise them if they surface later, and so we're not tempted to build weaker versions of them earlier.

---

## Part Eight — Design Vocabulary

A short glossary. When these words are used in Fresh Collective documents, meetings, and code, they mean these things. Deviating from these meanings is a signal that we are drifting.

**Belonging** — the deeper purpose Fresh Collective serves. What a member experiences when a community, a place, or a fellow traveller becomes something they recognise themselves in. Can be momentary or enduring, quiet or profound. The platform creates conditions; it does not grant belonging.

**Ecosystem** — many overlapping communities, no single centre, no single funnel. Every member's path is different; every collective's shape is different; every place's culture is different.

**Discovery** — the act of looking outward. What exists? What resonates? What is here that I did not know about? Honest, editorial, finite. Held by two destinations: Explore Collectives and Discover Places.

**Connection** — the act of noticing a fellow traveller. Not networking, not following, not friending. Held by one destination: Ways to Connect.

**Place** — a real-world location that at least one meaningful thing on Fresh Collective happens inside. Curated. City-granularity by default. Every active place has an editorial voice from day one.

**Community / Collective** — a container of shared purpose, with a creator or a peer group, and its own rituals (pathways, gatherings, conversations, resources).

**Local Circle** — a specific *shape* of collective: peer-led, free, small, place-anchored. Not a separate object.

**Fellow traveller** — another member who shares a real experience with you. Not a friend, not a follower. A person the platform can name because you have both been in something.

**Recognition** — the surface act of noticing a fellow traveller in context. Derived. Contextual. Ephemeral. Never persistent, never counted, never ranked.

**Journey Together** — the exception to Recognition's ephemeral rule. An intentional, mutual, bounded agreement between two members to walk something together. The one place on Fresh Collective where a relationship is stored, because it is the one place where both parties have consciously chosen it.

**Shared Experience** — the atomic unit of Recognition. A pathway enrolment, a gathering booking, a collective membership, a shared place of residence.

**Emergence** — the property of communities forming when they are ready. Fresh Collective notices conditions and offers doors; it does not create groups.

**Invitation** — the tone every surface adopts. An invitation implies the recipient may decline, and nothing bad happens if they do. This is different from a notification, a prompt, or a call to action.

**Release** — the opposite of *attention capture*. Our measure of success is that members leave Fresh Collective to live richer lives, and come back on their own terms.

---

## Closing note

When someone in three years' time proposes a new feature under any of these four destinations, this is the test:

**Does it invite? Does it release? Does it recognise something real? Does it help someone belong?**

If the answer to all four is *yes*, build it slowly, calmly, and simply. If the answer to any is *no*, put it down.

The platform's purpose is not to hold members' attention. It is to help them find each other, find their places, and find their paths — and then walk out the door, into the lives they belong in.
