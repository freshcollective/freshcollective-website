# Fresh Collective Design Language — Platform Audit

*Read-only report. No code was modified.*

This audit measures the current Fresh Collective frontend against
`docs/fresh-design-language.md`. Findings are organised by **component**,
deduplicated across pages, and prioritised as **Critical / High / Medium /
Low**. Numbers in "Affected" refer to occurrences returned by grep on the
active `frontend/src` tree.

Priority key:
- **Critical** — breaks a normative Fresh Collective rule that affects legibility,
  accessibility, or brand identity. Ship-blocking for new features.
- **High** — visible inconsistency that a member or creator will feel.
- **Medium** — inconsistency that will accumulate but is not immediately
  visible.
- **Low** — polish; safe to defer without impact.

---

## Executive summary

The platform is broadly aligned with Fresh Collective on colour (post the recent
grey-to-black sweep), spacing, and radius. Where Fresh Collective is not yet enforced:

1. **Typography weights are unruly.** 2,466 occurrences of non-standard
   `fontWeight` values (`350, 500, 540, 580, 620, 630, 640, 650, 660, 700,
   800`) across 140 files. Fresh Collective permits `400 / 600 / 700` only.
2. **Modals are ad-hoc.** No shared `Modal` primitive. Six files use native
   `alert()` and 13 use `confirm()`. Fresh Collective requires a system modal for any
   confirmation.
3. **Gold accent still leaks** into two Resources info banners and several
   marketing mock panels. Fresh Collective reserves gold for the marketing hero.
4. **No shared `Card`, `Button`, or `FormField` primitive** — every page
   renders bespoke variants. Shared primitives are the pre-requisite for
   any further page-level Fresh Collective work.
5. **Focus rings are inconsistent.** 31 files declare `focus:ring` variants;
   the rest rely on browser defaults. Fresh Collective requires a visible focus
   indicator on every interactive element.

---

## Typography

### T-1 · Weight scale violated everywhere · **Critical**

- **Where.** 140 files with 2,466 occurrences across marketing pages,
  Creator Studio pages, Admin pages, Resources drawer, Members drawer, and
  most shared components. Repeat offenders include
  `src/app/creator-studio/create-collective/CreateCollectiveFlow.tsx`,
  `src/app/creator-studio/pathways/[pathwaySlug]/EditPathwayClient.tsx` (149
  occurrences), `src/app/creator-studio/people/PeopleClient.tsx` (283), and
  the landing page (`src/app/page.tsx`, 6).
- **Fresh Collective rule.** §3.2 permits weights `400 / 600 / 700` only. §3.3 forbids
  more than two weights on a single screen.
- **Why it matters.** Weight is the strongest hierarchy signal Fresh Collective has
  after size. Bespoke weights (`580`, `630`, `640`, `650`, `660`) make
  hierarchy feel arbitrary and defeat the "hierarchy is felt" principle.
- **Recommended fix.** Introduce two shared typography primitives —
  `<Heading level=...>` and `<Text variant=...>` — that hard-code the scale
  and forbid `fontWeight` overrides at the prop level. Migrate pages to use
  them.
- **Priority.** Critical (foundation).

### T-2 · Non-scale font sizes on marketing pages · **Medium**

- **Where.** `src/app/page.tsx` (27 occurrences), `src/app/for-creators/page.tsx`
  (1). Sizes such as `10.5px`, `13.5px`, `15.5px`, `9.5px`.
- **Fresh Collective rule.** §3.2 defines an absolute scale; §4.1 forbids off-scale
  values.
- **Why it matters.** The marketing page will be Fresh Collective's ambassador. Off-scale
  sizes here undermine consistency claims.
- **Recommended fix.** Round every marketing size to the nearest scale step
  during marketing typography pass (§3.2 table).
- **Priority.** Medium (limited surface area).

### T-3 · Serif used outside display context · **Low**

- **Where.** 61 files carry `font-serif`. Most are legitimate display use
  (page titles, hero H1, stat figures). Suspect uses:
  `src/app/settings/membership/page.tsx` (13),
  `src/app/creator-studio/create-collective/CreateCollectiveFlow.tsx` (2),
  `src/app/creator-studio/setup/page.tsx` (3),
  `src/app/onboarding/OnboardingFlow.tsx` (6).
- **Fresh Collective rule.** §3.1: "Serif — display only".
- **Why it matters.** Serif at body sizes reads dated on modern surfaces.
- **Recommended fix.** Audit each `font-serif` occurrence for size — retain
  ≥ 20px, replace < 20px with sans.
- **Priority.** Low (visual only).

### T-4 · `text-navy-500/600/700` used for body text · **Medium**

- **Where.** 54 occurrences across 29 files. Notable:
  `src/components/spaces/CollectiveSwitcher.tsx` (5),
  `src/app/creator/page.tsx` (3),
  `src/app/spaces/[slug]/layout.tsx` (2), settings/membership pages.
- **Fresh Collective rule.** §2.2 `ink/primary` is `#000000` for body. Navy shades are
  reserved for headings (`ink/heading` = `#0C1826`).
- **Why it matters.** Muted navy body text produces the same problem as
  grey — it fails Fresh Collective's 7:1 contrast floor and misapplies hierarchy.
- **Recommended fix.** Replace body uses with `text-black`; retain navy on
  headings only.
- **Priority.** Medium.

### T-5 · Italic used for emphasis outside quotation · **Low**

- **Where.** 18 files. Most are quotations (reflection prompts, block
  editor preview text). Suspects:
  `src/components/spaces/ImportantPanel.tsx` (2),
  `src/components/spaces/MemberCard.tsx` (1),
  `src/app/creator-studio/resources/ResourcesManager.tsx` "Unused" hint
  (1).
- **Fresh Collective rule.** §3.3 (implied — Fresh Collective uses weight, not italic, for
  emphasis).
- **Why it matters.** Italic body reads as marketing copy; not a Fresh Collective tone.
- **Recommended fix.** Keep italic only for genuine quotations and block
  editor placeholder previews.
- **Priority.** Low.

---

## Colour

### C-1 · Gold pathway/resource info banners · **High**

- **Where.**
  `src/app/creator-studio/resources/page.tsx` (gold border and body),
  `src/app/spaces/[slug]/resources/page.tsx`,
  `src/app/creator-studio/pathways/PathwaysClient.tsx`,
  `src/app/creator-studio/gatherings/page.tsx`,
  `src/components/spaces/PathwayCard.tsx`,
  `src/components/spaces/EventCard.tsx`,
  `src/app/creator-studio/CreatorStudioLiteMobile.tsx`. Values include
  `rgba(214,177,63,0.4)`, `rgba(226,193,79,0.07)`, colour `#7A5A00`,
  `#D6B13F`.
- **Fresh Collective rule.** §2.7: "Gold is reserved. It appears only in the marketing
  hero and CTA rule accents, never in application chrome."
- **Why it matters.** Gold has been rejected across five design iterations.
  Any residual gold in a member or creator surface contradicts the current
  brand direction.
- **Recommended fix.** Replace each gold-tinted panel with the Fresh Collective
  neutral info banner (soft teal wash `#EAF7F7` + hairline).
- **Priority.** High (visible on top-level pages).

### C-2 · Grey text on interactive-only surfaces · **Medium**

- **Where.** Post-sweep, ~127 `text-slate-{300..700}` remain across 42
  files. On inspection: most are legitimate (icon-only wrappers,
  `hover:` and `disabled:` variants, badge internals like
  `bg-slate-100 text-slate-500`). A minority are still body text —
  candidates for audit:
  `src/components/community/CreatePostForm.tsx:133`
  (`hover:text-slate-600` on a link),
  `src/components/spaces/GatheringsView.tsx:166` (same pattern).
- **Fresh Collective rule.** §2.2: `ink/disabled` is the only permitted grey; §2.7
  disallows grey body text.
- **Why it matters.** Small pockets of grey undo the recent readability
  sweep.
- **Recommended fix.** Sweep once more with a stricter allow-list of
  legitimate greys (icon svgs, disabled state, badge internals).
- **Priority.** Medium.

### C-3 · Coloured icon-well backgrounds on member cards · **Low**

- **Where.** `src/components/spaces/PathwayCard.tsx`,
  `src/components/spaces/EventCard.tsx`,
  `src/components/spaces/MemberCard.tsx`, resource cards inside
  `ResourcesManager` (allowed — it is Fresh Collective-compliant).
- **Fresh Collective rule.** §9.3: "Cards never carry a filled colour background."
  §2.6 permits type-based coloured icon container only on resource cards.
- **Why it matters.** The distinction between "icon container" (allowed) and
  "card fill" (not allowed) is thin — several member cards accidentally fill
  the whole card corner with the icon well's tint.
- **Recommended fix.** Standardise the icon-well pattern
  (`h-11 w-11 rounded-full`, 10% opacity of accent).
- **Priority.** Low.

### C-4 · Non-palette accent colours in creator marketing mockups · **Low**

- **Where.** `src/app/page.tsx` mockup panels still use `#B8891A`,
  `#C4981A`, `#D4B048` inside decorative UI screenshots.
- **Fresh Collective rule.** §2.7 — no palette additions.
- **Why it matters.** Mockups are decorative but read as design examples.
- **Recommended fix.** Replace mockup gold accents with neutral slate.
- **Priority.** Low.

---

## Spacing & Grid

### S-1 · Off-scale spacing values · **Medium**

- **Where.** Ad-hoc `px-3.5`, `py-2.5`, `mt-1.5`, `p-4.5` are common. Not
  strictly against Fresh Collective — Tailwind's `-3.5` maps to 14px, which is not a
  multiple of 4 or 8.
- **Fresh Collective rule.** §4: 4-point base, 8-point rhythm. Odd 14px steps are
  tolerated for form-field internals but should not appear at section-level
  spacing.
- **Why it matters.** Small deviations accumulate into "why does this feel
  slightly off" perceptions.
- **Recommended fix.** Publish a Fresh Collective spacing linter config that flags
  non-scale margin/padding classes at layout scope.
- **Priority.** Medium.

### S-2 · Container widths inconsistent · **Low**

- **Where.** Application uses `max-w-[1180px]` (Fresh Collective-compliant); some
  admin pages use `max-w-6xl` (1152px) or `max-w-7xl` (1280px).
- **Fresh Collective rule.** §5.1 — one container width per context.
- **Why it matters.** Alignment across nav to page content drifts.
- **Recommended fix.** Introduce `<AppContainer>` and `<ReadingContainer>`
  wrappers.
- **Priority.** Low.

---

## Border radius

### R-1 · Radius inconsistency on inputs vs. cards · **Low**

- **Where.** Some forms use `rounded-lg` (8px) for inputs; others use
  `rounded-xl` (12px). Cards use `rounded-2xl` (16px). No egregious
  deviations, but the "same family" rule (§6.1) is not enforced.
- **Fresh Collective rule.** §6.1 — cards and drawers same family; inputs and
  secondary buttons same family.
- **Why it matters.** Radius consistency is what makes surfaces feel
  designed rather than assembled.
- **Recommended fix.** Codify in the shared primitives (see B-1, F-1).
- **Priority.** Low.

---

## Shadows

### SH-1 · Cards use borders instead of shadow for elevation · **High**

- **Where.** Most cards in Creator Studio and Admin use
  `border border-slate-100` at rest with no shadow, and hover simply
  darkens the border. Resource cards use Fresh Collective elevation correctly; almost
  nothing else does.
- **Fresh Collective rule.** §7: "Shadow elevates, borders structure." Cards at rest
  should carry `elev-1` (soft two-layer shadow), hover `elev-3`.
- **Why it matters.** Borders make surfaces feel "wireframe". Fresh Collective's
  premium feel depends on quiet shadow.
- **Recommended fix.** Introduce `<Card>` primitive using Fresh Collective elevation
  tokens; migrate.
- **Priority.** High (visible on every listing).

---

## Buttons

### B-1 · No shared `Button` primitive · **Critical**

- **Where.** A `src/components/ui/Button.tsx` exists but is used only in a
  handful of places. Most buttons are inline Tailwind class strings.
  Notable duplication:
  `const tealBtn = 'inline-flex items-center rounded-xl px-4 py-2 …'` recurs
  in `ResourcesManager.tsx`, `MediaLibraryClient.tsx`,
  `PeopleClient.tsx`, `PassesClient.tsx`, `CreateCollectiveForm.tsx`,
  `CreateCollectiveFlow.tsx`, and elsewhere.
- **Fresh Collective rule.** §8: three-level hierarchy with fixed sizes and states.
  §22.1 — "one primary per surface".
- **Why it matters.** Without a shared primitive Fresh Collective cannot be enforced.
  Every future page will invent slight variations.
- **Recommended fix.** Rebuild `<Button variant="primary|secondary|tertiary|danger" size="sm|md|lg">`
  as the single source. Ban inline button styles via ESLint rule.
- **Priority.** Critical.

### B-2 · Multiple primary buttons per view · **High**

- **Where.** `CreateCollectiveFlow.tsx`, `EditPathwayClient.tsx`, member
  space page footers with side-by-side "Explore Collectives" +
  "Build a Collective" (justified on marketing).
- **Fresh Collective rule.** §8.4 — "one primary action per screen".
- **Why it matters.** Two primaries force the user to choose, defeating the
  purpose of visual hierarchy.
- **Recommended fix.** Downgrade the secondary intent to a secondary button
  or tertiary link.
- **Priority.** High.

### B-3 · Filled coloured buttons scattered across surfaces · **Medium**

- **Where.** 47 files apply the teal gradient
  `linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)` inline. Ideally that
  value lives in one place.
- **Fresh Collective rule.** §8.1 primary uses the same gradient definition.
- **Why it matters.** If Fresh Collective ever tunes the gradient, 47 files must
  change.
- **Recommended fix.** Publish a CSS variable `--primary-fill` and reference
  it from the `<Button>` primitive.
- **Priority.** Medium.

### B-4 · Icon-only buttons missing `aria-label` · **Medium**

- **Where.** Random spot check on `PostCard.tsx`, `PathwayStepNav.tsx`,
  `CollectiveSwitcher.tsx`. `aria-label` is present on 31 icon buttons —
  many more are unlabelled.
- **Fresh Collective rule.** §19.4, §21.4 — icon-only buttons must carry
  `aria-label`.
- **Why it matters.** Keyboard and screen-reader users lose access.
- **Recommended fix.** Sweep icon buttons; add labels or replace with
  labelled variants.
- **Priority.** Medium.

---

## Cards

### CD-1 · No shared `Card` primitive · **Critical**

- **Where.** Everywhere. Every listing implements its own card. Repeat
  patterns include the Resources card (Fresh Collective-compliant), the Pathway card
  (partial), the Event card (mostly OK), Member card, Post card, Notification
  card, and each Admin table's card fallback.
- **Fresh Collective rule.** §9 defines the canonical structure. §22.3 groups Card
  into "Compositions" and mandates a single source of truth per
  composition.
- **Why it matters.** Every future consistency effort must edit N files
  instead of 1.
- **Recommended fix.** Introduce `<Card>` composition with slots for
  marker, title, meta, identity, and footer. Use in one page as reference;
  migrate rest gradually.
- **Priority.** Critical.

### CD-2 · Coloured left-border stripes still present · **High**

- **Where.**
  `src/components/RichTextRenderer.tsx` (blockquote stripes — legitimate),
  `src/app/spaces/[slug]/pathways/[pathway-slug]/[step-slug]/page.tsx`,
  `src/app/spaces/[slug]/pathways/[pathway-slug]/about/page.tsx`.
- **Fresh Collective rule.** §9.3 — "Cards do not carry left-border stripes."
- **Why it matters.** The recent Resources redesign removed the stripe on
  purpose; other member surfaces still have them.
- **Recommended fix.** Replace with the small coloured dot pattern (§2.5,
  §15.1).
- **Priority.** High.

### CD-3 · Dashed borders around empty and upload states · **Medium**

- **Where.** 31 files. Consistent pattern:
  `border border-dashed border-slate-200` around empty states and file
  uploaders.
- **Fresh Collective rule.** §16 empty states — Fresh Collective empty states use surface
  elevation, not dashed borders. §7 — shadow over border.
- **Why it matters.** Dashed borders read as "under construction" which is
  the opposite of Fresh Collective's premium tone.
- **Recommended fix.** Replace with a subtle `elev-1` panel and centred
  content.
- **Priority.** Medium.

---

## Forms

### F-1 · No shared `FormField` primitive · **Critical**

- **Where.** Ubiquitous inline form-field markup:
  ```
  const inputCls = 'w-full rounded-xl border border-border bg-white px-3.5 py-2.5 …'
  ```
  Present in `CreatePostForm`, `CreateCommentForm`, `MembersView`,
  `SignupForm`, `LoginForm`, `ForgotPasswordForm`, `ResetPasswordForm`,
  `ProfileForm`, `PathwayForm`, `EventForm`, `SpaceSettingsForm`,
  `CollectiveSettingsForm`, `ResourceManager`, `MediaLibraryClient`,
  `ResourcesManager`, and many more. At least 25 distinct
  copy-pasted string constants.
- **Fresh Collective rule.** §10 defines a canonical anatomy (label / input / helper /
  states).
- **Why it matters.** Focus rings, error states, disabled state, spacing —
  each of these is different in every form.
- **Recommended fix.** Publish `<FormField>`, `<Label>`, `<Input>`,
  `<Textarea>`, `<Select>`, `<Checkbox>`, `<Radio>`, `<HelperText>` and
  `<FieldError>`. Migrate all forms.
- **Priority.** Critical.

### F-2 · Labels sometimes replaced by placeholders · **Medium**

- **Where.** Community `CreatePostForm.tsx`, `CreateCommentForm.tsx`,
  search inputs in `MembersView.tsx` and `ResourcesManager.tsx` search bar
  (search is legitimate; discussion inputs are not).
- **Fresh Collective rule.** §10.3 — "Labels are always visible. Placeholders are
  never a substitute for a label."
- **Why it matters.** Accessibility and cognitive load — placeholder
  labels disappear on focus.
- **Recommended fix.** Add visible labels above every input in
  non-search forms.
- **Priority.** Medium.

### F-3 · Validation timing mixed · **Medium**

- **Where.** Some forms validate on keystroke (`title` field in
  `ResourcesManager` on save), others on submit only. No forms validate on
  blur.
- **Fresh Collective rule.** §10.3 — "Validate on blur, not on keystroke."
- **Why it matters.** Fresh Collective's "no surprises" tone.
- **Recommended fix.** Standardise inside the `FormField` primitive using
  a `useValidation` hook.
- **Priority.** Medium.

### F-4 · Native `alert()` / `confirm()` used for feedback · **High**

- **Where.**
  `alert()` in: `EditPathwayClient.tsx`, `AboutRichTextEditor.tsx`,
  `admin/sales/tasks/page.tsx`, `admin/sales/leads/[id]/page.tsx`,
  `admin/sales/leads/page.tsx`, `admin/sales/pricing/page.tsx`.
  `confirm()` in: 13 files including `ResourcesManager.tsx`,
  `MediaLibraryClient.tsx`, `PeopleClient.tsx`, and several admin pages.
- **Fresh Collective rule.** §14 — "Modals are reserved for confirmation … must be
  dismissable by Escape … destructive confirmations show the entity name".
- **Why it matters.** Native browser dialogs cannot be styled, break on
  mobile, and violate Fresh Collective's tone.
- **Recommended fix.** Introduce a `<ConfirmDialog>` primitive and a
  `useConfirm()` hook (returns a promise, replaces `confirm()`).
- **Priority.** High.

---

## Tables

### TB-1 · No shared `Table` primitive · **High**

- **Where.** Every Admin page (`overview`, `creators`, `collectives`,
  `payments`, `pricing`, `sales/*`, `revenue`, `users`, etc.) implements
  its own table markup. Creator Studio `PeopleClient` and `PassesClient`
  do the same.
- **Fresh Collective rule.** §11 defines canonical structure, densities, and rules
  (no zebra, no vertical dividers, right-aligned numbers).
- **Why it matters.** Admin tables are the most repetitive UI in the
  platform.
- **Recommended fix.** Introduce `<DataTable>` with columns config,
  standard and compact density, and slot-based cell rendering.
- **Priority.** High.

### TB-2 · Numbers left-aligned in payment/pricing tables · **Low**

- **Where.** `admin/payments/page.tsx`, `admin/pricing/page.tsx`,
  `admin/revenue/page.tsx`.
- **Fresh Collective rule.** §11.3 — "Numbers right-align."
- **Why it matters.** Scanning columns of currency is harder when they
  don't align on the decimal.
- **Recommended fix.** Right-align in the shared `<DataTable>`.
- **Priority.** Low.

### TB-3 · Empty cells rendered as blank space · **Low**

- **Where.** Same admin pages.
- **Fresh Collective rule.** §11.3 — "Empty cells show an em dash".
- **Why it matters.** Blank cells look like missing data (bug) instead of
  intentional (feature).
- **Recommended fix.** Cell renderer emits `—` when value is null/empty.
- **Priority.** Low.

---

## Navigation

### N-1 · Multiple parallel primary navigation implementations · **High**

- **Where.**
  `src/components/layout/PublicHeader.tsx` (marketing header),
  `src/app/spaces/[slug]/layout.tsx` (member space nav),
  `src/app/creator-studio/CreatorStudioShell.tsx` (creator nav),
  `src/components/admin/AdminShell.tsx` (admin nav).
- **Fresh Collective rule.** §12 defines primary navigation once, horizontal at the
  top, with a utility cluster on the right.
- **Why it matters.** Members moving between areas experience three
  different nav shapes.
- **Recommended fix.** Extract `<AppShell>` component with slots for
  `title`, `sections`, and `utility` — configure per area.
- **Priority.** High.

### N-2 · Vertical primary sidebar in Admin · **Medium**

- **Where.** `AdminShell.tsx` uses a left sidebar for primary nav.
- **Fresh Collective rule.** §12.4 — "Never build vertical primary navigation."
- **Why it matters.** Admin currently feels like a separate product.
- **Recommended fix.** Move to horizontal top nav with grouped
  subsections. Discuss with product before touching.
- **Priority.** Medium (requires product sign-off).

### N-3 · Secondary tabs use pills instead of underline · **Medium**

- **Where.** `SettingsNav.tsx`, `SpaceNav.tsx`, filter chips in
  `ResourcesManager.tsx` (top-level "All / Recent / Published" etc).
- **Fresh Collective rule.** §12.2 — "text-only tabs with an animated 2px underline".
- **Why it matters.** Pills are heavier than Fresh Collective's tab pattern.
- **Recommended fix.** Introduce `<Tabs>` primitive. Reserve pill filters
  for search/filter chips only.
- **Priority.** Medium.

---

## Drawers

### D-1 · No shared `Drawer` primitive · **Critical**

- **Where.** `ResourcesManager.tsx` implements Fresh Collective-compliant drawer
  inline (~200 LOC). Other detail flows (`MembersView.tsx`,
  `PeopleClient.tsx`, `EditPathwayClient.tsx`) use inline expanded panels
  or modals instead of drawers.
- **Fresh Collective rule.** §13 — drawer is the primary detail surface; four
  standardised parts.
- **Why it matters.** Drawers should replace at least six current inline
  edit flows.
- **Recommended fix.** Extract `<Drawer>`, `<DrawerSection>`,
  `<DrawerFooter>` from `ResourcesManager` and reuse.
- **Priority.** Critical.

### D-2 · Ad-hoc backdrop implementations · **Low**

- **Where.** Backdrop opacity varies: `bg-black/40` (`MediaLibraryClient`
  modals), `bg-slate-950/25` (Resources drawer), `bg-black/25` (community
  modal).
- **Fresh Collective rule.** §13.3, §14.1 — drawer backdrop and modal backdrop have
  fixed values.
- **Why it matters.** Consistency in backdrop weight is felt.
- **Recommended fix.** Fold into shared primitives (D-1, M-1).
- **Priority.** Low.

---

## Modals

### M-1 · Two competing modal implementations · **High**

- **Where.** `src/components/admin/Modal.tsx` (admin-only, simple),
  inline modals in `MediaLibraryClient.tsx` (Upload, Edit),
  `CollectiveSettingsModal.tsx`, `EmojiPicker.tsx`.
- **Fresh Collective rule.** §14 defines the canonical modal.
- **Why it matters.** Modal is a first-class Fresh Collective component; three
  variants is two too many.
- **Recommended fix.** Extract `<Modal>` in `components/ui/`; deprecate
  the admin version.
- **Priority.** High.

### M-2 · Modal stacking possible · **Medium**

- **Where.** Media Library "Edit asset" modal can open from within the
  drawer flow; no guard prevents a modal-inside-modal in `admin/*` sales
  pages.
- **Fresh Collective rule.** §14.2 — "Never stack modals."
- **Why it matters.** Escape key behaviour becomes ambiguous.
- **Recommended fix.** Track modal open state in a context; refuse to
  render a second modal.
- **Priority.** Medium.

---

## Status indicators

### ST-1 · Two badge styles co-exist · **Medium**

- **Where.** `<StatusBadge>` in `src/components/admin/StatusBadge.tsx` uses
  filled slate pills; Resource / Media badges use tinted `10% opacity`
  pills; community `PostTypeTag` uses another variant.
- **Fresh Collective rule.** §15.2 — tinted 10% opacity pill with 10px uppercase
  label.
- **Why it matters.** Three ways to say the same thing.
- **Recommended fix.** Ship `<StatusBadge status="published|draft|…">` in
  the primitives layer; migrate.
- **Priority.** Medium.

### ST-2 · Coloured dot and status pill mixed on the same card · **Low**

- **Where.** Resource cards (Fresh Collective-compliant), Event card (pill only).
- **Fresh Collective rule.** §15.4 — "Never mix dot and pill for the same status
  within a screen."
- **Why it matters.** Visual inconsistency.
- **Recommended fix.** Standardise via `<StatusBadge>` + `<StatusDot>`.
- **Priority.** Low.

---

## Empty states

### E-1 · Dashed border + illustrations in empty states · **High**

- **Where.** `MediaLibraryClient.tsx` (dashed border + centred
  arrow-up icon in a circle), `ResourcesManager.tsx` (dashed border),
  `PathwaysClient.tsx` (dashed border),
  `PassesClient.tsx`, `PeopleClient.tsx`, `CommunityManager.tsx`, and
  most creator-studio pages.
- **Fresh Collective rule.** §16.2 — "Empty states never use illustration."
  §9.3 — cards don't carry dashed borders.
- **Why it matters.** Fresh Collective's empty-state pattern is deliberately quiet.
- **Recommended fix.** Publish `<EmptyState icon? title body action />`
  and migrate.
- **Priority.** High.

### E-2 · Two or more actions in empty states · **Medium**

- **Where.** `MediaLibraryClient.tsx` empty state offers both "Upload
  first asset" and a link to Resources.
- **Fresh Collective rule.** §16.2 — "exactly one action".
- **Why it matters.** Empty states are a decision point — Fresh Collective picks
  the primary path for the user.
- **Recommended fix.** Move the secondary link into an inline info
  banner separate from the empty state.
- **Priority.** Medium.

---

## Success states

### SU-1 · Modal-based "Saved" acknowledgments · **Low**

- **Where.** Occasional `alert('Saved')` (see F-4). Otherwise the
  platform is quiet — mostly Fresh Collective-compliant.
- **Fresh Collective rule.** §17.3 — "Never use a modal to say 'Saved'."
- **Why it matters.** Interrupts flow.
- **Recommended fix.** Silent close-and-refresh; toast when the outcome
  isn't immediately visible.
- **Priority.** Low.

### SU-2 · No shared `<Toast>` primitive · **Medium**

- **Where.** Nowhere. Toasts don't exist; the platform swallows all
  positive feedback.
- **Fresh Collective rule.** §17.1 — toast contract exists.
- **Why it matters.** For actions with delayed side-effects (email
  invite, payment processing), silence feels broken.
- **Recommended fix.** Publish `<Toast>` and `useToast()` hook.
- **Priority.** Medium.

---

## Error states

### ER-1 · Errors displayed as red text with no container · **High**

- **Where.** `LoginForm.tsx`, `SignupForm.tsx`, `ForgotPasswordForm.tsx`,
  `ResetPasswordForm.tsx` — errors are bare `text-red-500` beneath the
  form.
- **Fresh Collective rule.** §18.2 — form-level errors sit in a tinted pill
  container.
- **Why it matters.** Errors need to be findable; bare red text lacks a
  hit box for `role="alert"`.
- **Recommended fix.** `<FormError>` primitive (part of Forms migration).
- **Priority.** High.

### ER-2 · Raw error codes leak to UI · **Medium**

- **Where.** `MediaLibraryClient.tsx`, `ResourcesManager.tsx`,
  `PeopleClient.tsx` fall back to `Save failed (${res.status})` on
  unexpected response.
- **Fresh Collective rule.** §18.4 — "Never show a raw error code to the user."
- **Why it matters.** Erodes trust.
- **Recommended fix.** Translate to friendly messages, log the code via
  `data-error-code` for support.
- **Priority.** Medium.

### ER-3 · No global system-error page · **Medium**

- **Where.** No route-level `error.tsx` or `not-found.tsx` seen in
  `frontend/src/app`.
- **Fresh Collective rule.** §18.3 — system error page exists.
- **Why it matters.** Runtime errors surface as browser defaults.
- **Recommended fix.** Add Fresh Collective-styled `app/error.tsx` and
  `app/not-found.tsx`.
- **Priority.** Medium.

---

## Icons

### I-1 · Icon primitive not standardised · **Medium**

- **Where.** Inline SVGs everywhere. Same icon (chevron, plus, close, ⋯)
  drawn slightly differently across files.
- **Fresh Collective rule.** §19.1 — "custom-drawn inline SVGs" with 1.6px stroke,
  rounded caps.
- **Why it matters.** Stroke width and end-cap drift; visual noise.
- **Recommended fix.** Publish an `<Icon name="chevron|close|…">` set in
  `components/ui/icons/`. One SVG per icon, referenced everywhere.
- **Priority.** Medium.

### I-2 · Emoji used as icon glyph · **Low**

- **Where.** `src/components/creator/BlockEditorShared.tsx:333` uses
  `🖼` inside a placeholder tile.
- **Fresh Collective rule.** §19.4 — "Never use emoji as an icon."
- **Why it matters.** Emoji rendering varies across OSes; not Fresh Collective
  tone.
- **Recommended fix.** Replace with the image icon SVG.
- **Priority.** Low.

---

## Motion & animation

### MO-1 · Ad-hoc animation timings · **Medium**

- **Where.** Inline `animation: fcCardFade 220ms ease-out` and similar
  scattered across ~15 files with slightly different durations
  (`180ms`, `200ms`, `220ms`, `240ms`).
- **Fresh Collective rule.** §20.1 defines fixed durations per interaction.
- **Why it matters.** Motion is one of the strongest "feel" signals.
- **Recommended fix.** Add motion tokens to `globals.css`
  (`--motion-fast: 140ms`, `--motion-drawer: 240ms`) and reference.
- **Priority.** Medium.

### MO-2 · `prefers-reduced-motion` handled at page level only · **Low**

- **Where.** `globals.css` collapses `.fc-ribbon`, `.fc-cycle`, and
  `.reveal` animations. Inline `<style jsx>` keyframes in components
  (Resource card, drawer, hub card) do not honour the media query.
- **Fresh Collective rule.** §20.2 — motion respects `prefers-reduced-motion`.
- **Why it matters.** Accessibility.
- **Recommended fix.** Wrap component-scoped keyframes in
  `@media (prefers-reduced-motion: no-preference)`.
- **Priority.** Low.

---

## Accessibility

### A-1 · Focus rings inconsistent · **High**

- **Where.** Only ~89 occurrences of `focus:ring` / `focus-visible:ring`
  across 47 files. Interactive elements outside those files rely on
  browser defaults or nothing.
- **Fresh Collective rule.** §21.2 — "Every interactive element must render a
  visible focus indicator."
- **Why it matters.** Keyboard users are lost.
- **Recommended fix.** Focus tokens in `globals.css`
  (`--ring: 0 0 0 2px rgba(56,160,158,0.4)`) and apply from primitives.
- **Priority.** High.

### A-2 · Missing `aria-label` on icon-only controls · **High**

- **Where.** Overflow menu triggers (fixed), close buttons (mostly fixed),
  chevron toggles (many missing), like/reaction buttons in community
  (missing), notification bell (fixed).
- **Fresh Collective rule.** §21.4 — icon-only buttons require `aria-label`.
- **Why it matters.** Screen readers announce nothing.
- **Recommended fix.** Sweep after `<IconButton>` primitive exists.
- **Priority.** High.

### A-3 · Hit-target size not enforced · **Medium**

- **Where.** Small close ✕ buttons at 24×24 (community modal, mobile nav
  drawer), small "×" tag removers in `PostTypeTag`.
- **Fresh Collective rule.** §21.5 — 44×44 minimum via padding.
- **Why it matters.** Mobile usability.
- **Recommended fix.** Add invisible padding to bring hit area up to
  44px.
- **Priority.** Medium.

### A-4 · Colour-only meaning · **Low**

- **Where.** Status dots on `PathwayCard`, `ResourceCard`, `EventCard`
  convey status by colour alone.
- **Fresh Collective rule.** §21 (implied). Fresh Collective already labels alongside dots in
  Resources ("Life in Alignment") — needs to become universal.
- **Why it matters.** Colour-blind users.
- **Recommended fix.** Always pair a dot with a visible text label.
- **Priority.** Low.

---

## Component hierarchy

### H-1 · Primitive layer effectively missing · **Critical**

- **Where.** `components/ui/` contains only `Card`, `Button`,
  `Avatar`, `BrandLabel`, `MarkdownBody`, `SectionHeading`, `PathwayCover`,
  `AboutRichTextEditor`, `OverflowMenu`, `AnimatedTypeRibbon`. Notably
  absent: `Modal`, `Drawer`, `Toast`, `FormField`, `Label`, `Input`,
  `Textarea`, `Select`, `Checkbox`, `Radio`, `Tabs`, `Table`, `EmptyState`,
  `Badge`, `StatusDot`, `Heading`, `Text`, `Icon`.
- **Fresh Collective rule.** §22.1 — Primitives are the foundation. Compositions
  build on them.
- **Why it matters.** Fresh Collective cannot be enforced page by page — it must be
  enforced primitive by primitive. This gap is the single biggest reason
  the audit above is so long.
- **Recommended fix.** Ship the missing primitives before any further
  page work. See implementation order.
- **Priority.** Critical.

---

## Quick wins *(under one day each)*

1. **Replace two gold info banners** (`resources/page.tsx`,
   `spaces/[slug]/resources/page.tsx`) with the neutral teal banner. Kills
   the most visible gold leak. *[C-1 subset]*
2. **Add missing `aria-label`s to visible icon-only buttons** by sweeping
   the seven repeat offenders. *[A-2 subset]*
3. **Replace all `alert()` calls** with a temporary `<InlineNotice>` while
   the Toast/Modal primitives are being built. *[F-4, ER-1 partial]*
4. **Remove decorative dashed borders** from Resources, Media, Pathways,
   Passes, People empty-state containers — swap for a plain white panel
   with `elev-1`. *[E-1, CD-3 subset]*
5. **Fix left-align numbers** in Admin payments / pricing / revenue
   tables. *[TB-2, TB-3]*
6. **Sweep italic body copy** in `MemberCard`, `ImportantPanel`, resource
   "Unused" hint — replace with weight 500. *[T-5]*
7. **Publish motion tokens** in `globals.css` so downstream primitives can
   reference them. *[MO-1 prerequisite]*
8. **Add `<AppContainer>` and `<ReadingContainer>` wrappers.** Cheap; sets
   the container standard for later work. *[S-2]*

---

## Medium improvements *(one to five days each)*

1. **`<Card>` composition + migration of Resources, Media, People,
   Passes, Pathways to it.** Standardises elevation everywhere Fresh Collective is
   most visible. *[CD-1, SH-1]*
2. **`<Button>` primitive with variants + ESLint rule blocking inline
   button strings.** Retire the `tealBtn` constant everywhere. *[B-1,
   B-3]*
3. **`<FormField>` + input primitives + migration of member-facing forms
   first** (`ProfileForm`, `SignupForm`, `LoginForm`, `CreatePostForm`).
   *[F-1, F-2, F-3, ER-1]*
4. **`<Drawer>` primitive extracted from `ResourcesManager`** — use in
   Media, People, Members detail, Pathway settings. *[D-1, D-2]*
5. **`<Modal>` primitive with global open-state context** — replace
   `admin/Modal`, `MediaLibraryClient` upload/edit, `CollectiveSettingsModal`,
   community moderation confirmations. *[M-1, M-2, F-4 completion]*
6. **`<StatusBadge>` and `<StatusDot>`** — consolidates ST-1 and CD-2.
7. **`<Toast>` + `useToast()`** — enables success state consistency
   (SU-2).
8. **`<EmptyState>`** — completes E-1, E-2 sweep.
9. **`<DataTable>`** — migrate Admin pages one at a time; retire
   duplicate table markup. *[TB-1, TB-2, TB-3]*
10. **`<Heading>` and `<Text>` primitives** — kills the T-1 weight
    problem at the root.
11. **`<Icon>` set** — consolidates I-1; unblocks I-2 fix.

---

## Major refactors *(one to three weeks each)*

1. **`<AppShell>`** replacing `PublicHeader`, `CreatorStudioShell`,
   `AdminShell`, `spaces/[slug]/layout.tsx`, `settings/layout.tsx`. Slot
   architecture: `title / sections / utility`. Enables N-1, N-2, N-3, and
   sets the container discipline for the whole platform.
2. **Admin sidebar → horizontal nav migration.** Product decision
   required. *[N-2]*
3. **Global error boundary + Fresh Collective system-error page + not-found page.**
   *[ER-3]*
4. **Motion audit and token migration** — replace inline `<style jsx>`
   keyframes with tokenised classes that honour `prefers-reduced-motion`.
   *[MO-1, MO-2]*

---

## Suggested implementation order

The order below builds shared primitives first, then migrates the highest-
traffic pages, then sweeps the tail. Reordering will cause rework.

### Phase 1 · Foundation (week 1)

1. Fresh Collective tokens: colour, spacing, radius, shadow, motion, focus ring — all
   as CSS variables in `globals.css`. No component code yet.
2. `<Heading>`, `<Text>` (T-1 fix at the root — everything downstream
   uses these).
3. `<Icon>` set (chevron, close, plus, overflow, search, upload, arrow,
   check, warning, info, spinner). Every subsequent primitive uses these.
4. `<Button>` and `<IconButton>` — because every primitive after this
   needs a button.
5. Quick wins list — batched into a single PR while primitives are being
   reviewed.

### Phase 2 · Interaction primitives (week 2)

6. `<Modal>` (global open-state context).
7. `<Drawer>` extracted from `ResourcesManager`.
8. `<Toast>` + `useToast()`.
9. `<ConfirmDialog>` + `useConfirm()` — retires every `confirm()` call.
10. `<Tabs>` for secondary navigation.

### Phase 3 · Form + data primitives (week 3)

11. `<FormField>` / `<Label>` / `<Input>` / `<Textarea>` / `<Select>` /
    `<Checkbox>` / `<Radio>` / `<HelperText>` / `<FormError>`.
12. `<Card>` composition with slots.
13. `<StatusBadge>` and `<StatusDot>`.
14. `<EmptyState>` (depends on `<Button>` and `<Icon>`).
15. `<DataTable>` (depends on `<StatusBadge>` and `<Text>`).

### Phase 4 · Shell + navigation (week 4–5)

16. `<AppContainer>` / `<ReadingContainer>`.
17. `<AppShell>` prototype, integrated first in Creator Studio (the area
    with the most inconsistent nav today).
18. Rework `PublicHeader`, member `spaces/[slug]/layout.tsx`,
    `AdminShell`, `SettingsNav` to consume `<AppShell>`.

### Phase 5 · Page migrations (weeks 5–8)

Migrate in the following order — each page proves the primitives work at a
higher density level before moving to the next:

19. Creator Studio Resources (already closest to Fresh Collective — use as reference).
20. Creator Studio Media Library.
21. Creator Studio People, Passes.
22. Creator Studio Pathways list + Edit Pathway + Step editor.
23. Creator Studio Community, Settings, Billing.
24. Member Space Resources, Events, Pathways, Community, Members, Profile.
25. Auth flow (Login, Signup, Forgot, Reset, Invites).
26. Settings pages (Profile, Security, Preferences, Membership).
27. Admin pages (in the order: `overview`, `creators`, `collectives`,
    `payments`, `sales/*`, `pricing`, `revenue`, `users`, `moderation`,
    `access`, `audit`, `settings`, `billing`).
28. Marketing pages (already close — polish for T-2, C-4).

### Phase 6 · Sweep and codify (week 9)

29. ESLint rule: forbid inline `text-slate-*`, `text-navy-500|600|700`,
    inline `fontWeight`, inline button strings.
30. Fresh Collective component gallery in `docs/`.
31. Final grey / italic / gold sweep.

---

## Closing note

The single most important insight is **H-1**. Nothing in this audit is
individually hard; the difficulty is compounded because Fresh Collective has no
primitives layer to enforce it. **Ship primitives first, migrate pages
second.** If pages are migrated before the primitives exist, every
migration will need to be redone once the primitives arrive.

The Fresh Collective design language is normative. This audit is a snapshot at
2026-07-04 and should be regenerated after each phase.
