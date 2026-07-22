# The Fresh Collective Design Language

*The Fresh Collective Design System*

Fresh Collective is the single source of truth for every visual and interaction decision
across Fresh Collective. This document is normative, not aspirational: it
describes how the platform must look and behave. Do not deviate without a
written amendment to this document.

---

## Preamble

Fresh Collective is a home for creator-led communities. The interface exists to
carry attention to the content, the members, and the conversations — never to
call attention to itself. Fresh Collective is the discipline that makes that possible.

**A member should never notice the software.**

If they notice the software, it is because it slowed them down, made them
hesitate, or made them second-guess. Fresh Collective exists to make that impossible.

The nearest reference points are Apple, Linear, Notion, Arc, and Framer. The
platform must never resemble Kajabi, Circle, Skool, Discord admin panels, or a
generic SaaS dashboard.

---

## 1. Design Philosophy

Fresh Collective is guided by seven principles. When a decision is unclear, defer to the
principle listed first.

1. **Clarity above all.** The user should always understand what an element
   does, what state it is in, and what happens next. If clarity conflicts with
   density, choose clarity.
2. **Restraint.** Every element must earn its place. A screen is finished when
   there is nothing left to remove, not when there is nothing left to add.
3. **Whitespace is a material.** Space carries hierarchy. If a layout feels
   crowded, the answer is almost never "make it smaller" — it is "give it
   room".
4. **Consistency is calm.** The same shape means the same thing. The same
   spacing means the same relationship. The user's mental model should hold
   from page to page.
5. **Readability is non-negotiable.** Text must be easy to read on the first
   glance. Grey body text is a bug.
6. **Hierarchy is felt, not seen.** Weight, size, spacing and colour arrange
   themselves so the eye lands in the right place without being told.
7. **Human warmth.** Fresh Collective is quiet, but it is not cold. Typography, tone,
   corner radii and easing curves all lean toward warmth.

**Fresh Collective is not.** Fresh Collective is not decorative. It is not gradient-heavy. It is not
badge-heavy. It is not chip-heavy. It is not colourful for the sake of colour.
It is not "playful" in ways that create noise.

---

## 2. Colour System

Fresh Collective uses colour with severe restraint. The palette is small on purpose.
Colour must communicate — it must never decorate.

### 2.1 Surfaces

| Token | Value | Use |
|---|---|---|
| `surface/page` | `#F7FBFA` | The base of every application page. |
| `surface/card` | `#FFFFFF` | Cards, drawers, modals, forms, tables. |
| `surface/canvas-warm` | `#FAFAF8` | Marketing sections and hero-adjacent panels only. |
| `surface/inverse` | `#071824` | Dark cards, dark heroes, footer, CTA panels. |
| `surface/inverse-deep` | `#050B14` | Bottom of dark gradients. |

There are no other surface colours.

### 2.2 Ink (text)

| Token | Value | Use |
|---|---|---|
| `ink/primary` | `#000000` | All body text on light surfaces. |
| `ink/inverse` | `#FFFFFF` | All body text on dark surfaces. |
| `ink/heading` | `#0C1826` | Headings on light surfaces. Near-black, not pure. |
| `ink/heading-inverse` | `#FFFFFF` | Headings on dark surfaces. |
| `ink/disabled` | `#94A3B8` | The **only** grey permitted. Reserved for disabled controls, inactive tab labels, and pending / not-yet-loaded states. |

Grey is not a body text colour. Grey is a semantic state. If text is not
disabled or inactive, it must be `ink/primary` (light bg) or `ink/inverse`
(dark bg).

### 2.3 Structural accent

Teal is the platform accent. It signals identity, focus, and primary action.

| Token | Value | Use |
|---|---|---|
| `accent/teal-500` | `#38A09E` | Primary buttons, links, focus rings, brand mark. |
| `accent/teal-400` | `#55B8B6` | The lighter stop in the primary gradient. |
| `accent/teal-700` | `#246B6A` | Dark-mode teal for legibility on light. |
| `accent/teal-50` | `#EAF7F7` | Soft teal wash for chips and rare highlights. |

Teal is the only decorative colour used on general chrome. Everything else is
neutral.

### 2.4 Semantic status

Status colours only appear inside status badges, dots, and inline validation.
They are never used for decoration.

| Meaning | Token | Value |
|---|---|---|
| Published / Success | `status/success` | `#38A09E` |
| Draft / Pending | `status/pending` | `#94A3B8` |
| Archived / Neutral | `status/neutral` | `#64748B` (badge fill only) |
| Warning | `status/warning` | `#D97706` |
| Error | `status/error` | `#B91C1C` |

`status/neutral` is the sole exception where a slate value is allowed in a
component — always inside a tinted pill, never as loose text.

### 2.5 Pathway identity

Pathways carry their own soft accent used for a **single 6px dot** on cards
and a **3px stripe** on drawers. Pathway colour never fills a surface.

| Pathway | Dot |
|---|---|
| General | `#38A09E` (teal) |
| Life in Alignment | `#3D6289` (navy) |
| Human Design | `#4F7ABE` (blue) |
| EMBODY | `#7C6BB0` (lilac) |
| Home Practice | `#6B8E7F` (sage) |
| Archived | `#94A3B8` (grey) |

Unknown pathway slugs deterministically rotate through blue → sage → lilac →
navy. **Gold is not a pathway colour.**

### 2.6 Content-type identity

Resource type has a soft coloured circular icon container. Nothing else in the
card carries the type colour.

| Type | Fill (@ 10% opacity) | Icon |
|---|---|---|
| Audio | Purple | `#7C6BB0` |
| Video / Replay | Coral | `#DC6F5C` |
| Guide / Template | Blue | `#4F7ABE` |
| File | Navy | `#3D6289` |
| Link | Teal | `#38A09E` |
| Other | Slate | `#64748B` |

### 2.7 Rules

- Gold is reserved. It appears only in the marketing hero and CTA rule
  accents, never in application chrome.
- Never introduce a new colour. If a design needs a new hue, the design is
  wrong — revisit the hierarchy first.
- Never fill a card with a pathway or type colour. Colour is a hint, not a
  background.
- Never place coloured text on a dark accent surface. If a dark surface must
  carry accent text, the accent lightens (e.g. `#7FDAD9`), it does not stay
  saturated.

---

## 3. Typography

### 3.1 Family

- **Sans (default):** system font stack — `-apple-system, BlinkMacSystemFont,
  "SF Pro Display", "SF Pro Text", "Segoe UI", Roboto, Arial, sans-serif`.
- **Serif (display only):** `Georgia, "Times New Roman", Times, serif`. Used
  for hero titles, statistic figures, and drawer eyebrow titles.
- **Mono:** `"SF Mono", "Fira Code", "Roboto Mono", monospace`. Used only for
  file names, URLs, code, and identifiers.

### 3.2 Scale

Fresh Collective uses a compact but expressive scale. Sizes are absolute (pixel-based)
for chrome and clamp-based for hero copy.

| Role | Size | Weight | Letter-spacing | Line-height |
|---|---|---|---|---|
| Display XL (hero) | `clamp(2.375rem, 6vw, 5.5rem)` | 660 | -0.04em | 1.05 |
| Display L | `clamp(2rem, 4.5vw, 4.25rem)` | 660 | -0.04em | 1.08 |
| Display M | `clamp(1.75rem, 2.8vw, 2.75rem)` | 660 | -0.04em | 1.10 |
| Page title (h1) | `22–24px` (serif) | 600 | -0.02em | 1.15 |
| Section (h2) | `17–18px` | 600 | -0.02em | 1.25 |
| Subsection (h3) | `15px` | 600 | -0.02em | 1.30 |
| Body | `14px` | 400 | -0.01em | 1.60 |
| Body-strong | `14px` | 600 | -0.01em | 1.55 |
| Meta | `12–13px` | 500 | 0 | 1.50 |
| Eyebrow | `10–11px` uppercase | 600 | 0.10–0.14em | 1.00 |
| Stat figure | `22–26px` (serif) | 400 | -0.02em | 1.00 |

### 3.3 Rules

- Never use more than two weights on a single screen: 400 (body) and 600
  (heading / strong). 700 is reserved for eyebrows only.
- Never combine serif with a body-sized font. Serif is display-only.
- Never centre paragraph body copy. Only headings and short marketing
  statements centre.
- Never justify text.
- Line-length should sit between 55 and 75 characters. Use `max-width` to
  enforce.

---

## 4. Spacing System

Fresh Collective uses a 4-point base with an 8-point rhythm. All spacing pulls from this
scale — no arbitrary values.

| Token | Value | Typical use |
|---|---|---|
| `space-0` | 0 | Reset |
| `space-1` | 4px | Icon-to-label pairing |
| `space-2` | 8px | Inside pills, chips, tight groups |
| `space-3` | 12px | Grid gaps on mobile |
| `space-4` | 16px | Default card padding baseline |
| `space-5` | 20px | Card / drawer inner padding |
| `space-6` | 24px | Section-to-section gap inside a panel |
| `space-8` | 32px | Card grid gap on desktop, drawer section spacing |
| `space-10` | 40px | Page section top-and-bottom on marketing |
| `space-12` | 48px | Major section separation |
| `space-16` | 64px | Hero vertical rhythm |

### 4.1 Rules

- Cards use `space-5` internal padding (`20px`) as the default. Drawers use
  `space-8` horizontal.
- Group related items with `space-2`. Group unrelated items with `space-6`.
  The gap is the relationship.
- When in doubt, add one step of space, not less.
- Never break the scale. `13px`, `18px`, `22px` are forbidden.

---

## 5. Grid System

### 5.1 Container widths

| Context | Max width | Padding |
|---|---|---|
| Application shell | `1180px` | `32px` desktop, `24px` mobile |
| Marketing content | `1180px` | `32px` desktop, `20px` mobile |
| Reading (About / step content) | `680–720px` | Auto centered |
| Drawer | `520–560px` | Fixed right |

### 5.2 Responsive breakpoints

Fresh Collective is mobile-first. Breakpoints:

- Base (mobile): 0–639px
- `sm`: ≥ 640px
- `md`: ≥ 768px (introduce two-column layouts)
- `lg`: ≥ 1024px (sidebars become persistent)
- `xl`: ≥ 1280px (three-column card grids)

### 5.3 Column model

Grids use `1 / 2 / 3` columns for cards, `1 / 2` for two-panel content
layouts, and `[42fr 58fr]` or `[58fr 42fr]` for asymmetric marketing rows.

Any layout not expressible in these ratios is a deviation and must be
justified.

---

## 6. Border Radius

Fresh Collective uses a small radius scale that maps to purpose. Do not choose radius by
feel.

| Token | Value | Use |
|---|---|---|
| `radius-sm` | 6px | Menu items, small pills |
| `radius-md` | 8px | Inputs, chips, small buttons |
| `radius-lg` | 10–12px | Segmented control containers, secondary panels |
| `radius-xl` | 14–16px | Standard cards, panels |
| `radius-2xl` | 20–24px | Feature cards, hero panels, drawers |
| `radius-full` | 9999px | Circular icons, dots, filter chips, status dots |

### 6.1 Rules

- Cards and drawers must share the same family (`radius-2xl`).
- Inputs and secondary buttons share `radius-md` or `radius-lg`.
- Never mix radii within a component (e.g. rounded card with square input).
- Do not exceed `radius-2xl` in application chrome.

---

## 7. Shadows

Fresh Collective uses shadow, never border, to elevate. Borders in Fresh Collective are hairlines
for structure — shadows communicate elevation.

| Level | Definition | Use |
|---|---|---|
| `elev-0` | `none` | Background surfaces, list rows |
| `elev-1` | `0 1px 2px rgba(15,30,55,0.04), 0 0 0 1px rgba(15,30,55,0.04)` | Resting card |
| `elev-2` | `0 1px 3px rgba(15,30,55,0.05), 0 0 0 1px rgba(15,30,55,0.05)` | Table cells and inputs on hover |
| `elev-3` | `0 10px 28px rgba(15,30,55,0.08), 0 0 0 1px rgba(15,30,55,0.06)` | Card on hover |
| `elev-4` | `0 16px 48px rgba(0,0,0,0.09)` | Popovers, dropdowns |
| `elev-5` | `0 24px 64px rgba(0,0,0,0.20)` | Drawers, modals |
| `elev-dark` | `0 48px 120px rgba(0,0,0,0.30)` | Dark feature cards over marketing |

### 7.1 Rules

- A card at rest is `elev-1`, on hover `elev-3`.
- Drawers use `elev-5` plus a full-height backdrop.
- Never combine visible shadow with a heavy border. Choose one.
- Focus rings do not use shadow — they use `focus-ring` (see §21).

---

## 8. Buttons

Fresh Collective uses three button levels. There is no fourth level.

### 8.1 Hierarchy

1. **Primary.** Filled teal gradient. One primary button per view.
   `linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)`, white label,
   `radius-md`, `elev-1` at rest, `elev-0` when disabled.
2. **Secondary.** Outlined. Slate hairline border, transparent background,
   `ink/primary` label. Hover: navy border darkens.
3. **Tertiary.** Text-only. Teal label, no background, underlines on hover.
   Used for inline actions and "Cancel" adjacent to primary.

### 8.2 Sizes

| Size | Height | Padding X | Text |
|---|---|---|---|
| Small | 32px | 12px | 12px |
| Default | 40px | 16px | 13px |
| Large | 48px | 20px | 14px |

### 8.3 States

- **Hover:** primary reduces opacity to 90%; secondary darkens border to
  navy; tertiary underlines.
- **Focus:** all buttons get a 2px teal focus ring at 40% opacity, offset
  2px from the button.
- **Disabled:** 50% opacity, `cursor: not-allowed`, no hover response.
- **Loading:** replace label with spinner + optional short verb ("Saving…").
  Do not animate the button itself.

### 8.4 Rules

- One primary action per screen. Two primaries is a design smell.
- Destructive actions (Delete) are **not** a fourth button style — they are a
  secondary button with red label (`status/error`).
- Buttons must not carry a bare icon without a label unless the icon is
  universally understood (close ×, menu ⋯, overflow ⋮).
- Button text is a verb ("Save changes", not "Save"). Cancel is the sole
  exception.

---

## 9. Cards

Cards are the fundamental object of the platform. Members and creators spend
most of their time reading and clicking them.

### 9.1 Structure

Every card follows this order:

1. **Marker** — icon, avatar, or coloured type dot. Top-left.
2. **Actions** — overflow menu ⋯ or single button. Top-right.
3. **Title** — the strongest element on the card.
4. **Meta row** — one line of type + status badges.
5. **Identity line** — pathway / owner / date with a coloured dot.
6. **Usage or summary line** — muted, at the bottom.

Cards use `flex flex-col` so the summary line stays pinned to the bottom via a
`flex-1` spacer.

### 9.2 Elevation

- **Rest:** `elev-1`, white background.
- **Hover:** `elev-3`, translateY -1px.
- **Selected / open drawer:** `elev-1` plus a 1px teal halo instead of the
  hairline.
- **Draft variant:** `#FAFBFC` background with slightly muted title
  (`ink/heading` becomes slate). Same elevation.
- **Archived variant:** 72% opacity, same structure.

### 9.3 Rules

- Cards never carry a filled colour background. Pathway and type identity
  live in the marker and dot only.
- Cards do not carry gradients.
- Cards do not carry left-border stripes.
- The entire card is clickable when the click takes the user to a natural
  detail view. Overflow menu clicks must stop propagation.
- Card padding is `space-5` minimum, `space-6` for detail cards.

---

## 10. Forms

### 10.1 Anatomy

Every field has three parts:

1. **Label.** Uppercase eyebrow at 12px, `ink/primary`, weight 600, tracking
   `0.08em`. Above the input. Never inside.
2. **Input.** `radius-md`, `1px solid rgba(15,30,55,0.14)` border, white
   background, `ink/primary` text at 14px.
3. **Helper text.** 12px, `ink/primary` on light bg (never grey). Sits below
   the input. Reserved for guidance, not validation.

### 10.2 States

- **Rest:** hairline border.
- **Hover:** border darkens by ~15%.
- **Focus:** border becomes `accent/teal-400`, plus a 3px teal ring at 25%
  opacity.
- **Error:** border becomes `status/error`, helper text becomes error
  message, error message is `ink/primary` on `rgba(185,28,28,0.06)` background
  pill.
- **Disabled:** background becomes `#F1F5F9`, text becomes `ink/disabled`,
  cursor `not-allowed`.

### 10.3 Rules

- Labels are always visible. Placeholders are never a substitute for a label.
- Required is indicated by a teal asterisk after the label. Do not use the
  word "required".
- Group related fields horizontally (2 columns) only when at desktop width
  and when both fields are short (type + status, first name + last name).
- Two-way validation: validate on blur, not on keystroke. Do not surprise the
  user mid-typing.
- Never colour the field itself for validation. Colour the border and the
  helper text.

---

## 11. Tables

Tables are for scanning many rows of related data. If a member is not scanning,
use cards.

### 11.1 Structure

- Column headers: 11px uppercase eyebrow, `ink/primary`, weight 600.
- Cell content: 14px body, `ink/primary`.
- Row separators: 1px hairline `rgba(15,30,55,0.06)`. No vertical dividers.
- Row hover: `#F8FAFC` background. Cursor pointer only if the row is
  actionable.
- Actions column: right-aligned overflow menu ⋯.

### 11.2 Density

Fresh Collective has two densities:

- **Standard:** 48px row height, 16px horizontal padding.
- **Compact:** 36px row height, 12px horizontal padding. Reserved for
  admin / creator tools with large lists.

### 11.3 Rules

- No zebra striping.
- No coloured cells. Status appears as an inline pill in a dedicated column.
- Tables do not carry left/right borders — they end at the whitespace.
- Numbers right-align. Dates use a fixed short format ("14 Mar 2026").
- Empty cells show an em dash (`—`), not the word "None" or a blank space.

---

## 12. Navigation

### 12.1 Primary navigation

Application uses a persistent top-bar. It carries:

- Brand mark (linked to home).
- Two to five primary destinations, no more.
- A single utility cluster on the right (notifications, profile).

Do not build vertical primary navigation. Fresh Collective is horizontal at the top.

### 12.2 Secondary navigation

Contextual navigation (Space nav, Settings nav) lives below the primary bar
inside the page. Uses text-only tabs with an animated 2px underline in
`accent/teal-500`. Inactive tabs are `ink/primary`; active tabs are
`ink/heading` with the underline.

### 12.3 Overlay header

When the header overlays a dark hero, all header text becomes `ink/inverse`
(pure white). Do not use grey-white opacity variants on overlay headers.

### 12.4 Rules

- Never place more than one primary navigation on a screen.
- Never use icons alone in the primary nav.
- Breadcrumbs appear only when the user is more than two levels deep from a
  primary destination.

---

## 13. Drawers

Drawers are the primary detail / management surface in Fresh Collective. Prefer a drawer
over a modal wherever the interaction is a review-and-adjust flow.

### 13.1 Structure

Right-anchored, full-height, `520–560px` wide on desktop, full-width on
mobile. The drawer has four parts:

1. **Accent stripe.** 3px pathway or teal colour along the very top.
2. **Header.** Eyebrow ("New resource" / "Resource"), display title (serif,
   22px), close button (×) top-right. Close is a text-only button, not an
   icon-only glyph without an aria-label.
3. **Body.** Scrolls independently. Organised into named sections (see 13.2).
4. **Actions.** Sticky bottom bar with primary + secondary actions on the
   left, destructive/utility actions on the right (Duplicate, Archive,
   Delete).

### 13.2 Sections

Drawer body is grouped into logical named sections with an uppercase eyebrow
per group. Standard section names for a resource-style drawer:

- **General** — identity fields (title, type, status).
- **Content** — description, files, URLs.
- **Availability** — pathway or audience assignments.
- **Usage** — where this asset is used elsewhere.

Sections are separated by `space-8` and a hairline top border.

### 13.3 Rules

- Drawer opens with a 240ms slide-in from the right, `cubic-bezier(0.22, 0.61,
  0.36, 1)`. Backdrop fades in over 180ms.
- Escape key closes the drawer. Backdrop click closes the drawer.
- The drawer is not a modal — the page behind it remains scrollable in
  layout but must not accept input while the drawer is open.
- Never nest a drawer inside a drawer.

---

## 14. Modals

Modals are reserved for confirmation, blocking flows, and short focused
decisions. If the interaction is longer than three fields, use a drawer.

### 14.1 Structure

Centred, `max-w-md` (~440px), white background, `radius-2xl`, `elev-5`,
backdrop `bg-black/40`.

- Header row with title and close (×).
- Body with a single clear message or short form.
- Actions right-aligned at the bottom: primary + tertiary Cancel.

### 14.2 Rules

- Use a modal only when the user must respond before continuing.
- Never stack modals. A modal that opens another modal is a design error.
- Destructive confirmations show the entity name in the title
  ("Delete *Week 1 Workbook*?").
- Modals must be dismissable by Escape.

---

## 15. Status indicators

Status appears in one of three forms: a **dot**, a **small pill badge**, or a
**status column value**.

### 15.1 Dot

`h-1.5 w-1.5 rounded-full`. Uses the semantic colour directly. Sits inline
before the label. Preferred form for identity (pathway) and low-noise status
(published).

### 15.2 Small pill

`radius-md`, tinted background at 10% of the status colour, label in the
status colour at 100%, `10px` uppercase text at weight 600, tracking `0.06em`.
Used inside cards and tables where multiple statuses need to be scanned.

### 15.3 Column value

Inside tables, status is a small pill only. Never colour the row or cell
background.

### 15.4 Rules

- Never mix dot and pill for the same status within a screen.
- Never use more than one status pill per card. If more information matters,
  it belongs in the drawer.
- Success is teal. Warning is amber (`#D97706`). Error is red (`#B91C1C`).
  Pending is slate. No exceptions.

---

## 16. Empty States

### 16.1 Structure

Centred within the card or container. Vertical stack:

1. Optional small icon (24–32px, `ink/disabled` colour).
2. Title — sentence case, 16px, weight 600. Something like "No resources yet".
3. Body — one sentence, 14px, `ink/primary`. Explains what will appear here
   and how to make it happen.
4. Single primary action button ("Add first resource").

### 16.2 Rules

- Empty states have exactly one action, never a menu of choices.
- Empty states never use illustration. Fresh Collective does not use illustration
  anywhere.
- Empty states never scold or apologise. They point forward.

---

## 17. Success States

Success is quiet. Fresh Collective does not celebrate CRUD operations.

### 17.1 Form completion

Success closes the drawer or modal, refreshes the list, and shows a subtle
success indicator only if the outcome is not immediately visible:

- Inline banner: teal-tinted background at 6% opacity, teal border at 25%
  opacity, teal text, dismissable.
- Toast: 220ms fade in, 4 second dwell, 200ms fade out. Bottom-right. Never
  more than one toast at a time.

### 17.2 Milestones

For meaningful transitions (payment complete, first resource created), a
dedicated success page with:

- A serif display heading.
- One line of supporting text.
- One primary action (usually "Continue").
- No confetti. No sparkles. No emoji.

### 17.3 Rules

- Never use a modal to say "Saved". Silence is confirmation.
- Never show a green checkmark badge that appears and disappears.

---

## 18. Error States

Errors are handled with the same restraint as success, but with sharper
visibility.

### 18.1 Inline field error

Directly under the input:

- Text: 12px, `ink/primary`, on a `rgba(185,28,28,0.06)` pill background,
  `radius-md`, 8px horizontal padding.
- Border of the field turns `status/error`.

### 18.2 Form-level error

At the top of the form / drawer body:

- Same pill treatment, longer message. Summarises what went wrong and points
  the user to the field.

### 18.3 System error

Full-page or blocking modal:

- Serif heading ("Something went wrong").
- One-line explanation.
- Primary action ("Retry" or "Go back").
- Secondary link to support if the retry is unlikely to succeed.

### 18.4 Rules

- Errors always tell the user what to do next.
- Errors never blame the user ("You entered…" is never used; use "That email
  is already registered" instead of "You already registered").
- Never show a raw error code to the user. Log it in a `data-*` attribute
  for support if needed.

---

## 19. Icons

### 19.1 Style

Icons are line-based, 1.6px stroke, rounded caps and joins. Fresh Collective uses
custom-drawn inline SVGs rather than an icon library so weight and spacing
stay consistent.

### 19.2 Sizes

| Context | Size |
|---|---|
| Inline with body text | 14px |
| Card marker | 18px inside a 40–44px circle |
| Standalone tap target | 20–22px inside a 44px hit area |
| Marketing feature icon | 20px inside a 44px square |

### 19.3 Colour

Icons take their colour from `currentColor`. On light backgrounds, the parent
element sets the colour to `ink/primary` or the semantic accent. Icons are
never coloured for decoration.

### 19.4 Rules

- Never mix line and filled icon styles.
- Never use emoji as an icon.
- An icon-only button must have an `aria-label` describing the action.

---

## 20. Motion and Animation

Fresh Collective favours short, natural motion. Motion communicates state change — it
never entertains.

### 20.1 Duration and easing

| Interaction | Duration | Easing |
|---|---|---|
| Hover / colour transitions | 120ms | `ease-out` |
| Card lift on hover | 220ms | `ease-out` |
| Menu / dropdown fade | 140ms | `ease-out` |
| Drawer slide-in | 240ms | `cubic-bezier(0.22, 0.61, 0.36, 1)` |
| Modal fade-in | 180ms | `ease-out` |
| Page section reveal on scroll | 700ms | `ease` (transform + opacity) |
| Toast fade | 200–220ms | `ease-out` |

### 20.2 Rules

- Motion respects `prefers-reduced-motion`. When set, all non-essential
  animation collapses to 0.01ms.
- Never animate a critical element (button, error message). They must appear
  instantly.
- Never use parallax, scroll-jacking, or auto-playing motion in feature
  cards.
- Never spring, bounce, or overshoot. Fresh Collective uses ease-out and ease-in-out
  only.

---

## 21. Accessibility Rules

Accessibility is not a checklist. It is a floor.

### 21.1 Contrast

- Body text on `surface/page` (`#F7FBFA`) using `ink/primary` (`#000000`)
  achieves 20:1. Fresh Collective targets 7:1 minimum for body text, 4.5:1 minimum for
  incidental UI text (which effectively means grey is disallowed).
- Focus ring: 3:1 against the adjacent surface, minimum.

### 21.2 Focus

Every interactive element must render a visible focus indicator. Fresh Collective uses
a 2px `accent/teal-500` ring at 40% opacity, offset 2px from the element.
`outline: none` without a replacement focus style is forbidden.

### 21.3 Keyboard

- Every action reachable by mouse must be reachable by keyboard.
- `Tab` moves forward, `Shift+Tab` back, `Enter`/`Space` activates,
  `Escape` closes drawers, modals, popovers.
- Trap focus inside modals and drawers while they are open. Restore focus
  to the trigger when they close.

### 21.4 Semantics and ARIA

- Use the correct HTML element first (`<button>`, `<a href>`, `<nav>`).
- Add ARIA only when semantics fall short (`role="dialog"`,
  `aria-expanded`, `aria-current`).
- Icon-only buttons require `aria-label`. Decorative icons require
  `aria-hidden="true"`.

### 21.5 Hit targets

Minimum tap target is `44 × 44px`. Small chips satisfy this via `padding`
rather than shrinking the visual size.

---

## 22. Component Hierarchy

Fresh Collective ranks its components into four tiers. Every component belongs to
exactly one tier.

1. **Primitives.** Type scale, spacing, colours, shadows, radius. Do not
   render on their own.
2. **Elements.** Buttons, inputs, labels, badges, icons, avatars. Render
   alone but rarely alone in production.
3. **Compositions.** Cards, tables, forms, drawers, modals, navigation,
   segmented controls, filter chips, overflow menu. Composed of elements.
4. **Surfaces.** Pages, panels, hero sections, drawers, empty states,
   success/error pages. Composed of compositions.

### 22.1 Elevation ranking

Only one element should feel primary on a given surface:

- The **title** is the strongest thing on a card.
- The **primary button** is the strongest thing in an action row.
- The **selected tab** is the strongest thing in a nav bar.
- If two things compete for attention, one must be lowered until they don't.

### 22.2 Density ranking

Fresh Collective has two densities and never blends them within a single surface:

- **Reading density** — member content, hero pages, About pages.
- **Working density** — Creator Studio, Admin, tables, forms.

Do not use reading typography inside a working table, and do not use
working density inside a member reading page.

---

## 23. Correct and Incorrect Usage

The following pairs illustrate how Fresh Collective is applied. When in doubt, refer
back to them.

### 23.1 Colour

**Correct.** A resource card has a pale purple circular icon marker, a black
title, a black type badge, a black status badge, a small navy dot beside the
pathway name, and the phrase "Linked to 3 lessons" in black.

**Incorrect.** The same resource card with a lilac background wash, a
gradient border, gold "Draft" pill, and grey supporting text.

### 23.2 Typography

**Correct.** A section titled "Pathways" in 17px navy-heading weight 600,
followed by a 14px black paragraph explaining the section.

**Incorrect.** A section titled "Pathways" in bold uppercase teal 12px,
followed by 13px grey italic text.

### 23.3 Cards

**Correct.** A resource card sits on the page bg with `elev-1`, no border, a
40px purple icon well, a bold title, one meta row, and a pathway dot at the
bottom. Hovering lifts the card by 1px.

**Incorrect.** The same card with a dashed amber border, a coloured header
strip, a "NEW!" ribbon in the corner, and a chevron arrow to indicate
"clickable".

### 23.4 Buttons

**Correct.** A form has one filled teal "Save changes" primary and a
text-only "Cancel" tertiary. Delete lives on the right of the sticky footer,
styled as a secondary with red label.

**Incorrect.** The same form has three primaries: "Save", "Save & Publish"
and "Save Draft" — all with teal fills.

### 23.5 Empty state

**Correct.** "No resources yet. Add links, files, guides and tools for your
members." Followed by a single primary "+ Add first resource" button.

**Incorrect.** "It's a bit lonely in here 😢. Get started by adding your
first resource, uploading a file, or connecting an integration." with an
illustration of a person sitting on a box.

### 23.6 Drawer

**Correct.** Opening a resource card slides in a 540px right-hand drawer
with a 3px navy stripe (its pathway colour), the resource title in serif at
the top, four labelled sections (General, Content, Availability, Usage),
and a sticky footer with Save + Cancel on the left and Duplicate / Archive /
Delete on the right.

**Incorrect.** Opening a resource card centres a 720px modal with tabs for
"Details / Availability / Danger Zone", a "Save" button floating at the
top-right corner, and a spinning animation on the outer container.

### 23.7 Motion

**Correct.** The card lifts 1px and its shadow deepens over 220ms on hover.
The drawer slides in from the right over 240ms with a cubic-bezier easing.

**Incorrect.** The card scales to 1.05 and rotates 2° with a spring bounce.
The drawer appears with a flash-then-slide combination.

---

## Amendment Process

Fresh Collective is normative but not frozen. To change it:

1. Propose the change with a description of the pattern that Fresh Collective does not
   currently express and the reasoning.
2. If accepted, this document is updated *before* the pattern ships in code.
3. If the pattern would remove or contradict an existing rule, that rule is
   deprecated in-place with a strikethrough and a date. Nothing is silently
   dropped.

The most valuable design decision is the one that is easy to keep. Fresh Collective
exists to make consistency the easiest path.

---

*This document is the design contract. If a pattern in the codebase disagrees
with it, the codebase is wrong.*
