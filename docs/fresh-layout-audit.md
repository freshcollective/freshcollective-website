# Layout Architecture Audit — Mobile Navigation Overlap

*Read-only report. No code changed.*

## TL;DR

**No component in the codebase renders `SpaceNav` on a Creator Studio route
via imports.** But the platform runs **five independent shells with five
different mobile-navigation strategies**, and the only fixed-position mobile
nav (`SpaceNav`'s `fixed bottom-0 left-0 right-0 md:hidden`) persists across
the frame boundary during Next.js soft navigation. That is why creators
report seeing both navigations at once on mobile.

The correct fix is architectural: **migrate every shell to consume Fresh Collective's
`<AppShell>`**, so a single mobile-nav contract exists across the app and
no fixed nav can leak from one shell into another. Patching individual
pages will not solve the class of bug.

---

## 1. Full layout hierarchy

The hierarchy is the sum of every `app/**/layout.tsx` plus the shell each
layout composes.

### 1.1 Root

**`app/layout.tsx`** — server component. Renders `<html>` + `<body>` and
wraps everything in `<Fresh CollectiveProviders>` (Toast + Confirm). **No navigation
chrome at this level.**

### 1.2 Marketing (`/`, `/about`, `/for-creators`, `/real-journey`, `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/membership`, `/spaces` list only)

There is **no marketing layout file.** Each page manually wraps itself in
`<SiteShell>`, which is:

```
<SiteShell heroHeader?>
  <PublicHeader overlay? />       ← top bar, includes <MobileNav>
  <main>{children}</main>
  <PublicFooter />
</SiteShell>
```

Mobile nav here is `<MobileNav>` (hamburger button + full-screen drawer,
`md:hidden`). It is **not fixed** — it is a burger + slide-in panel.

### 1.3 Member portal (`/spaces/[slug]/*`)

**`app/spaces/[slug]/layout.tsx`** — the *only* route that mounts
`<SpaceNav>`. Structure:

```
<div>
  <header> collective-switcher + Settings / Dashboard links </header>
  <div>   collective banner + hero image                  </div>
  <SpaceNav ... />
  <main>{children}</main>
</div>
```

`<SpaceNav>` has two rendered nav elements:
- Desktop (`hidden md:block`): horizontal underline tabs.
- Mobile (`md:hidden`): **`nav.fixed bottom-0 left-0 right-0 z-40`** — the
  fixed-position bar creators are seeing leak.

### 1.4 Creator Studio (`/creator-studio/*` **AND** `/creator/*`)

Two layout files, both mount the same shell:

- **`app/creator-studio/layout.tsx`** — server component, does auth + role
  check + pre-fetches every mobile-Lite tab's data, renders
  `<CreatorStudioShell>`.
- **`app/creator/layout.tsx`** — same auth gate, renders
  `<CreatorStudioShell>` without the Lite pre-fetch.

`<CreatorStudioShell>` diverges by breakpoint:

```
<>
  <div className="md:hidden">
    <CreatorStudioLiteMobile ... />       ← 3,132-line mobile replacement
  </div>
  <div className="hidden md:flex">
    <aside>desktop sidebar</aside>
    <main>{children}</main>               ← actual page content
  </div>
</>
```

On mobile, `<CreatorStudioLiteMobile>` **replaces** `{children}`
(children is mounted inside a `display: none` container, so the resource
page you navigated to is never visible on mobile). Its top nav is a
`sticky top-0` tab strip inside its own layout — **it is not fixed**.

**`app/creator/spaces/[slug]/layout.tsx`** is a thin padding wrapper only
(`<div class="mx-auto max-w-6xl px-6 py-10 md:px-10">{children}</div>`)
and inherits the CreatorStudioShell from `app/creator/layout.tsx`. No
nav here.

### 1.5 Admin (`/admin/*`)

**`app/admin/layout.tsx`** renders `<AdminShell>` which is a
**left-sidebar layout** with no dedicated mobile pattern. The sidebar is
always on the left even on mobile — Fresh Collective §12.4 forbids vertical primary
nav.

### 1.6 Settings (`/settings/*`)

**`app/settings/layout.tsx`** renders its own header + a two-column grid
with `<SettingsNav>` on the left. On mobile the sidebar collapses via
`md:grid-cols-...`.

### 1.7 Dashboard / Profile / Notifications

**`app/dashboard/layout.tsx`** is auth-only, no chrome. Individual
pages self-render their own back link / header.

---

## 2. Where navigation is duplicated

### 2.1 Duplication via imports — **NONE**

`SpaceNav` is grepped exhaustively. It is imported only by
`app/spaces/[slug]/layout.tsx`. No Creator Studio page, no Creator Studio
shell, and no Creator Studio subcomponent imports it. There is no direct
mount path from a `/creator-studio/*` route to `<SpaceNav>`.

### 2.2 Duplication via transient state — **YES**

`<SpaceNav>` on mobile is `position: fixed`. Fixed positioning takes the
element out of the normal document flow. During Next.js soft navigation
between `/spaces/[slug]/*` and `/creator-studio/*`:

1. Router intercepts the click.
2. Next.js begins rendering the new layout tree while the old tree is
   still in the DOM (streaming / suspense).
3. Old layout (`spaces/[slug]/layout.tsx`) has not yet been unmounted —
   `<SpaceNav>` with `position: fixed` remains visible over the viewport.
4. New layout (`creator-studio/layout.tsx`) begins to render;
   `<CreatorStudioLiteMobile>` appears at the top of the viewport with its
   own sticky tab strip.
5. For as long as the old tree stays mounted (data fetch, waterfall),
   the user sees **two navigations simultaneously**.

The `position: fixed` is what turns a transient mount overlap into a
visible bug. `<CreatorStudioLiteMobile>`'s `sticky top-0` doesn't cause
this because sticky elements respect their parent's normal flow, so
they disappear the moment the parent is removed from the layout tree.

### 2.3 Related contributing factors

- **Five separate shells, five separate mobile strategies.**
  `SiteShell → burger drawer`, `SpaceLayout → fixed bottom bar`,
  `CreatorStudioShell → full replacement`, `AdminShell → left sidebar`,
  `SettingsLayout → collapsed sidebar`. No single component owns the
  mobile-nav contract, so each shell has to be defensive about the
  others (and none are).
- **`<CreatorStudioLiteMobile>` shows `Browse as member` pill links to
  `/spaces/[slug]/*`** (lines 1078–1100). Clicking these is the most
  common way to trigger the two-shell transition described above.
- **`{children}` is mounted-but-hidden on mobile inside
  `CreatorStudioShell`.** The actual page (e.g. `ResourcesManager`) is in
  the DOM but `display: none`. If any of those `{children}` ever included
  a `position: fixed` element, it would also leak — right now none do.
- **`<CollectiveSwitcher>` inside the `spaces/[slug]/layout.tsx` header
  can navigate away to `/dashboard`, `/settings`, or any other collective.**
  Every such navigation is a shell-boundary crossing that gives the
  transient-overlap bug an opportunity.

---

## 3. Has `<AppShell>` exposed the overlap?

**No — `<AppShell>` has not been consumed anywhere yet.** It was built in
Phase 2 as infrastructure; the existing shells all pre-date it and are
still in place. The overlap is a pre-existing platform-level defect that
Phase 2 has **not** introduced or exposed. It is what `<AppShell>` was
designed to prevent.

To be explicit: no route currently renders `<AppShell>`, so no route can
gain or lose the bug because of Phase 2. The Fresh Collective Design Language audit
(§N-1) already called this out — the recommendation to consolidate onto
a single shell exists because the fragmentation causes exactly this class
of overlap.

---

## 4. What should change

### 4.1 The wrong fix: patch each page

Adding `md:hidden` to `<SpaceNav>` on Creator Studio routes, or resetting
scroll on shell change, or defensively unmounting the old shell earlier —
all of these are page-level patches. They will each work for one route
pair and fail for the next. The number of routes involved is unbounded.

### 4.2 The right fix: migrate every shell onto `<AppShell>`

Fresh Collective's `<AppShell>` is the single source of navigation chrome for the
platform. When every route renders through the same shell component, the
DOM node identity of the mobile nav is **stable** across navigations —
Next.js re-parents rather than re-mounts, and there is no transient
overlap window. Additionally:

- Only one mobile-nav pattern exists (no five-shell inconsistency).
- Fixed positioning stops being necessary — Fresh Collective's shell places nav in
  normal flow with `sticky` where appropriate.
- The five bespoke shell files can be deleted once each area is migrated,
  removing ~4,000 lines.

Recommended migration order (unchanged from the Fresh Collective audit roadmap):

1. **Wire `<AppShell>` into `SettingsLayout` first** — smallest surface,
   proves the shell composition works end-to-end without user-visible
   risk.
2. **Migrate `AdminShell` next** — retires the vertical-sidebar Fresh Collective
   §12.4 violation at the same time.
3. **Migrate `PublicHeader` (marketing) onto `<AppShell overlay>`** —
   removes the `<MobileNav>` hamburger drawer duplicated in the site
   shell.
4. **Migrate `CreatorStudioShell`** — the big one; involves retiring the
   3,132-line `<CreatorStudioLiteMobile>` and replacing it with the same
   `<AppShell>` used elsewhere plus responsive page content. This is the
   change that fixes the reported bug directly, because it removes the
   Creator Studio side of the transition.
5. **Migrate `spaces/[slug]/layout.tsx`** — removes `<SpaceNav>`'s fixed
   bottom bar and replaces it with `<AppShell>`'s sticky top nav. Fixes
   the *other* side of the transition and eliminates the fixed positioning
   that caused the leak.

Only after step 4 or step 5 will the "two navigations on top of each
other" bug be structurally impossible. Any earlier step is preparatory.

### 4.3 If a stopgap is needed before the shell migration

If the bug is visible enough to warrant an interim patch, the smallest
safe change is:

Change `<SpaceNav>`'s mobile nav from
`fixed bottom-0 left-0 right-0 md:hidden`
to
`sticky bottom-0 z-40 md:hidden`.

Sticky nav will unmount cleanly with its parent layout during route
transitions, closing the visible overlap window. This trades a small
scroll-behavior difference (the bar disappears when the page runs out of
content) for correctness during shell boundaries. It is a stopgap only —
the correct fix remains the `<AppShell>` migration.

---

## 5. Recommended next step

**Do not migrate another page.** Do not patch individual routes.

Start the shell-consolidation work with **`SettingsLayout` → `<AppShell>`**
as a pilot. It has:

- One primary nav area (`SettingsNav`) — small, safe.
- No fixed-position mobile nav — no visual regression risk.
- No data-fetching complexity — server layout with static children.
- Both a header and a sidebar to prove that `<AppShell>`'s `brand`,
  `primary`, and `utility` slots are enough (or discover they aren't).

If the Settings pilot works, promote to `AdminShell`, then `PublicHeader`,
then the two heavy hitters (`CreatorStudioShell`, `spaces/[slug]/layout.tsx`).

At the end of that sequence, this bug is architecturally impossible and
the platform has a single shell contract.

---

*Snapshot as of 2026-07-05.*
