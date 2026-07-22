# Grove → Fresh Collective — Rename Plan

*Read-only plan. No code changed.*

## Purpose

"The Grove" is a specific collective inside Fresh Collective (a woman-led
learning + community space owned by Fresh Collective — see `scripts/seed_*_content.py`
and `app/creator-studio/billing/page.tsx:193`). Reusing "Grove" as the
name of the platform-wide design system creates permanent confusion between
the collective and the design language.

The design system should be named after **Fresh Collective** — the platform
it defines.

This document lists every file, folder, symbol, token, import, comment,
and doc reference that currently uses "Grove" for the design system, and
proposes safe new names.

---

## Preferred direction

| Concept | New name |
|---|---|
| Design-system proper noun (docs, headings, comments) | **Fresh Collective Design Language** (may abbreviate to *the design language* in running prose) |
| Short technical prefix (CSS vars, keyframes, class hooks) | **`fc-`** (matches existing `--fc-shadow-*` legacy tokens) |
| Component folder path | **`components/fresh/`** |
| Root-provider symbol | **`FreshProviders`** |
| "The Grove" (the actual collective) | **Unchanged** — remains "The Grove" |

Rationale for `fc-`:
- Explicitly listed by you as an acceptable technical short-form.
- Aligns with the platform's own initials.
- Consistent with existing `--fc-shadow-*` tokens in `styles/tokens.css`
  (which can eventually be absorbed into the new file — see Risk 3).

Rationale for `components/fresh/`:
- `components/ui/` already exists and holds legacy primitives (`Card`,
  `Button`, `OverflowMenu`, `Avatar`, `BrandLabel`, `MarkdownBody`, etc.).
  Merging into `ui/` would collide.
- `fresh/` is unambiguously the design-system folder without a collision.

Rationale for keeping component-level names unchanged (`Card`, `Button`,
`Modal`, `Drawer`, `Toast`, `AppShell`, `useConfirm`, etc.):
- None of them contain "Grove" in the identifier. Only the import path
  and folder change. Zero API-level rename churn for the 21 primitives.

---

## 1. What currently uses "Grove" for the design system

### 1.1 Documentation (3 files)

| Path | Nature |
|---|---|
| `docs/grove-design-language.md` | Normative design contract |
| `docs/grove-audit.md` | Platform-wide audit against the design language |
| `docs/grove-layout-audit.md` | Layout-architecture audit |

Each also contains "The Grove Design Language" and "Grove" in body text
that would need updating.

### 1.2 Design-token file (1 file)

`frontend/src/styles/grove-tokens.css` — CSS custom properties and keyframes.
- 132 `--grove-*` custom-property declarations.
- 6 `@keyframes grove-*` declarations (`grove-fade-in`,
  `grove-fade-in-up`, `grove-drawer-in`, `grove-modal-in`,
  `grove-toast-in`, `grove-spin`).

### 1.3 Component folder (1 folder, 26 files)

`frontend/src/components/grove/` — the primitive set.
Files inside:
```
index.ts             GroveProviders.tsx    useConfirm.tsx
tokens.ts            utils.ts
AppShell.tsx         Badge.tsx             Button.tsx
Card.tsx             Checkbox.tsx          Drawer.tsx
EmptyState.tsx       FormField.tsx         Heading.tsx
Input.tsx            LoadingState.tsx      Modal.tsx
Page.tsx             PageHeader.tsx        SearchInput.tsx
Section.tsx          Select.tsx            StatusBadge.tsx
Switch.tsx           Table.tsx             Tabs.tsx
Text.tsx             TextArea.tsx          Toast.tsx
```
None of the component *identifiers* contain "Grove". The folder name is
the only change here.

### 1.4 Component symbol (1 export)

`GroveProviders` — root-provider composition exported from
`components/grove/GroveProviders.tsx`. Consumed by `app/layout.tsx`.

### 1.5 CSS custom properties in code (425 occurrences across 29 files)

Every primitive references tokens via `var(--grove-*)`. Also used from a
handful of pages that Phase 3 has already migrated:
- `app/creator-studio/resources/ResourcesManager.tsx`
- `app/creator-studio/media/MediaLibraryClient.tsx`
- `app/creator-studio/CreatorStudioShell.tsx` (Phase 3.5 shell migration)

### 1.6 CSS keyframe names (7 files)

The 6 `@keyframes grove-*` are consumed as string names inside `style={{
animation: 'grove-… …' }}` in:
- `components/grove/Modal.tsx`
- `components/grove/Drawer.tsx`
- `components/grove/Toast.tsx`
- `components/grove/LoadingState.tsx`
- `components/grove/Button.tsx`
- `components/grove/AppShell.tsx`
- `styles/grove-tokens.css` (the definitions)

### 1.7 Import paths (10 import statements across 6 files)

Every consumer references `@/components/grove/…`:
- `app/layout.tsx` (imports `GroveProviders`)
- `app/error.tsx`
- `app/not-found.tsx`
- `app/creator-studio/CreatorStudioShell.tsx`
- `app/creator-studio/resources/ResourcesManager.tsx`
- `app/creator-studio/media/MediaLibraryClient.tsx`

### 1.8 Header comments and docstrings

Every primitive begins with a doc comment naming itself "Grove Card",
"Grove Button", "Grove Modal", etc. Also `Page.tsx` says "outermost
application shell wrapper for a route. Applies the Grove …". These are
informational; they should be updated for accuracy but a stale one causes
no functional bug.

### 1.9 Doc cross-references

`grove-layout-audit.md` refers to the "Grove Design Language audit" and
the "Grove audit roadmap". These need to be updated to match the new doc
filenames.

---

## 2. What must NOT be renamed — "The Grove" as a collective

Grep-verified as the actual product, not the design system. All KEEP as-is:

| Path | Occurrence |
|---|---|
| `frontend/src/app/creator-studio/billing/page.tsx:193` | "EMBODY and **The Grove** are owned and operated by Fresh Collective directly." |
| `scripts/seed_lia_content.py` | Space seed for The Grove (space id `80862f54…`) |
| `scripts/seed_lia_week1_content.py` | Life-in-Alignment step content referencing "The Grove community" |
| `scripts/seed_nlh_content.py` | Full content seed for the collective — welcome text, tagline, about page, etc. |

There is **no** overlap between these hits and the design-system hits.
"The Grove" always appears with the article "The"; the design system
always appears bare as "Grove" or as a prefix (`grove-*`). A case-sensitive
rename that respects the article boundary is safe.

---

## 3. Recommended new names

### 3.1 Files and folders

| Current | New | Notes |
|---|---|---|
| `docs/grove-design-language.md` | `docs/design-language.md` | Repo context is implicit; matches `product-brief.md` / `roadmap.md` naming |
| `docs/grove-audit.md` | `docs/design-audit.md` | |
| `docs/grove-layout-audit.md` | `docs/layout-audit.md` | |
| `frontend/src/styles/grove-tokens.css` | `frontend/src/styles/fc-tokens.css` | |
| `frontend/src/components/grove/` | `frontend/src/components/fresh/` | Folder rename via `git mv` |
| `components/grove/GroveProviders.tsx` | `components/fresh/FreshProviders.tsx` | File + symbol rename |

### 3.2 Symbols

| Current | New |
|---|---|
| `GroveProviders` (component) | `FreshProviders` |

All other component names (`Card`, `Button`, `Modal`, `Drawer`, `Toast`,
`AppShell`, `Text`, `Heading`, `FormField`, `Table`, `EmptyState`, etc.)
stay unchanged. Hooks (`useConfirm`, `useToast`) stay unchanged.

### 3.3 CSS custom properties (132 declarations, 425 usages)

`--grove-*` → `--fc-*` mechanical rename. Examples:
- `--grove-surface-page` → `--fc-surface-page`
- `--grove-ink-primary` → `--fc-ink-primary`
- `--grove-accent-500` → `--fc-accent-500`
- `--grove-motion-drawer` → `--fc-motion-drawer`
- `--grove-radius-2xl` → `--fc-radius-2xl`
- `--grove-z-drawer` → `--fc-z-drawer`

### 3.4 CSS keyframes

| Current | New |
|---|---|
| `@keyframes grove-fade-in` | `@keyframes fc-fade-in` |
| `@keyframes grove-fade-in-up` | `@keyframes fc-fade-in-up` |
| `@keyframes grove-drawer-in` | `@keyframes fc-drawer-in` |
| `@keyframes grove-modal-in` | `@keyframes fc-modal-in` |
| `@keyframes grove-toast-in` | `@keyframes fc-toast-in` |
| `@keyframes grove-spin` | `@keyframes fc-spin` |

The `animation: 'grove-… …'` inline strings in six primitives need matching
updates.

### 3.5 Import paths

`@/components/grove/…` → `@/components/fresh/…`
- 10 statements across 6 files (see §1.7).

### 3.6 Comments and docstrings

Rewrite the header comment on each primitive from "Grove [Name]" to
either:
- "Fresh Collective — [Name]" (formal), or
- Just "[Name]" with a `@see docs/design-language.md §…` footer (concise).

Similar sweep in doc bodies:
- "The Grove Design Language" → "The Fresh Collective Design Language"
- "Grove permits …" → "The design language permits …" or "Fresh Collective permits …"
- Section refs like "Grove §12.4" → "§12.4" (context implicit)

---

## 4. Risks

1. **Missed references.** Grep is exhaustive for exact-match strings, but
   dynamic constructions like `` `--grove-${key}` `` would be missed.
   Verified: **no dynamic construction of these tokens exists in the tree.**
   Safe.

2. **`fresh/` folder collision with `ui/`.** Not a collision as long as we
   choose `fresh/` and leave `ui/` alone. The legacy `ui/` folder holds
   pre-design-language components that live alongside the new folder
   until they are migrated. No merge is required for the rename.

3. **CSS var prefix collision with legacy `--fc-shadow-*`.** The existing
   `styles/tokens.css` already defines `--fc-shadow-xs`, `--fc-shadow-sm`,
   `--fc-shadow-card`, etc. These do **not** collide with the new
   `--fc-elev-*`, `--fc-surface-*`, `--fc-ink-*` etc. that Grove's tokens
   will occupy. Both files can coexist as `--fc-*` namespaces. Long-term
   the legacy tokens can be folded into `fc-tokens.css` and the legacy
   file deleted, but that is out of scope for the rename.

4. **Build cache / Next.js chunks.** `.next/dev/static/chunks/src_components_grove_*`
   files reference the old folder. These regenerate on next dev-server
   compile. Nothing to do.

5. **Doc cross-references.** `layout-audit.md` currently says "Grove
   Design Language audit" pointing to `grove-audit.md`. When both files
   are renamed the pointers must be updated in the same pass, or the
   audit will point to a nonexistent file.

6. **Cache-busted imports during rename.** If the folder is renamed
   with `git mv` but imports are updated in a *separate* commit, the
   codebase will not build between commits. All import-path updates
   must land in the same commit as the folder rename.

7. **Editor / IDE indexes.** After the rename, VS Code / TS server may
   need a restart to pick up new paths. No runtime risk.

8. **`GroveProviders` symbol used at the very root.** `app/layout.tsx`
   imports `GroveProviders` from `@/components/grove/GroveProviders`.
   The rename must land as a single atomic change so the root layout
   doesn't half-work.

9. **Nothing outside `frontend/` needs renaming.** Verified: `backend/`
   has 0 hits for "grove". `next.config.ts` has 0 hits. `package.json`
   has 0 hits. No backend/API/config changes are involved.

**None of these risks are load-bearing.** All are addressable with a
disciplined sequence.

---

## 5. Can it be done as a mechanical rename without changing behaviour?

**Yes.** The rename is entirely mechanical. There are no runtime
implications: no imports use string-based dynamic construction; no CSS
selector uses `grove` as a live class; no data attribute encodes `grove`;
no telemetry or analytics depends on component symbol names; nothing in
the backend or database references "Grove".

TypeScript will fail-loudly on any missed import path, and CSS will
fail-visibly if a token or keyframe reference is missed (colours revert
to default). Both are easy to catch in a single sweep + type-check +
manual page load.

---

## 6. Suggested order

Six discrete phases. Each is committable and testable independently
**except** for Phase 4 which must be one atomic commit.

### Phase 1 — Docs (safest, no runtime risk)

1. `git mv docs/grove-design-language.md docs/design-language.md`
2. `git mv docs/grove-audit.md docs/design-audit.md`
3. `git mv docs/grove-layout-audit.md docs/layout-audit.md`
4. In each renamed file, sweep bodies:
   - `The Grove Design Language` → `The Fresh Collective Design Language`
   - Introductory prose that treats "Grove" as a proper noun → "the design language" or "Fresh Collective"
   - Internal cross-references between the three docs updated to new filenames.
5. Also update any references to Grove in this project's other docs
   (`CLAUDE.md` if it mentions the design system — verify).

Runtime impact: none.

### Phase 2 — CSS tokens file (isolated to one file)

6. `git mv frontend/src/styles/grove-tokens.css frontend/src/styles/fc-tokens.css`
7. Inside the new file, mechanical replace `--grove-` → `--fc-` and
   `grove-` (in `@keyframes` names and reduced-motion overrides) → `fc-`.
8. In `frontend/src/app/globals.css`, update the `@import` to point at
   `../styles/fc-tokens.css`.
9. Type-check + visual scan. The site should look identical because none
   of the *consumers* have been renamed yet, but the visuals will break
   because their `var(--grove-*)` refs no longer resolve. So this phase
   must be paired with Phase 3.

**Practical: fold Phase 2 and Phase 3 into a single commit.**

### Phase 3 — Update all consumers of tokens + keyframes

10. In `frontend/src/components/grove/**/*.{ts,tsx}` and any other file
    that references `var(--grove-*)` or the six keyframe names, sweep:
    - `var(--grove-` → `var(--fc-`
    - `'grove-fade-in'` → `'fc-fade-in'` (and the five siblings)
11. Type-check + dev-server smoke test:
    - `/creator-studio/resources` (already migrated to primitives)
    - `/creator-studio/media` (already migrated)
    - `/creator-studio` (Phase 3.5 shell — uses AppShell)
    - Root `/` renders (uses GroveProviders wrapper)

Combined with Phase 2 this is the highest-volume change but is a pure
mechanical find-and-replace.

### Phase 4 — Component folder rename + `GroveProviders` symbol rename (atomic commit)

12. `git mv frontend/src/components/grove frontend/src/components/fresh`
13. `git mv frontend/src/components/fresh/GroveProviders.tsx frontend/src/components/fresh/FreshProviders.tsx`
14. Inside `FreshProviders.tsx`: rename the exported symbol
    `GroveProviders` → `FreshProviders` and update the docstring.
15. In `frontend/src/components/fresh/index.ts`, rewire the re-export
    (`export { FreshProviders } from './FreshProviders'`).
16. Search-and-replace across the tree:
    - `from '@/components/grove'` → `from '@/components/fresh'`
    - `from '@/components/grove/…'` → `from '@/components/fresh/…'`
17. In `frontend/src/app/layout.tsx`, update the import
    (`GroveProviders` → `FreshProviders`) and the JSX tag.
18. Type-check must be **zero errors** for the commit to land.

This is the *only* phase that must be atomic. It's a single, mechanical,
verifiable change.

### Phase 5 — Docstrings + header comments in primitives

19. Sweep each file in `components/fresh/` and update its header
    comment:
    - `Grove <Name>` → `<Name>` (drop the prefix; the `@see` link and the
      folder itself convey context), or
    - `Grove <Name>` → `Fresh Collective — <Name>` (if you prefer the
      full brand mark).
20. Any prose in doc comments that refers to "Grove" as a proper noun
    updated to "the Fresh Collective design language" or reworded.
21. Update `docs/design-language.md` heading from "The Grove Design
    Language" to "The Fresh Collective Design Language" if not already
    done in Phase 1.

Purely cosmetic; safe to defer or split into a smaller PR.

### Phase 6 — Verification sweep

22. Grep the tree for any remaining `grove` that is not "The Grove" (the
    collective):
    ```
    grep -rn "grove" --include="*.ts" --include="*.tsx" --include="*.css" --include="*.md" \
      frontend/src docs \
      | grep -v "The Grove" | grep -v "the Grove"
    ```
23. Every hit should be either a comment we chose to leave or a real
    reference to fix. Expect the list to be short (headers we left alone,
    optional deferred comment updates from Phase 5).
24. Confirm the actual collective seeding scripts still reference "The
    Grove" verbatim (unchanged).
25. Type-check + lint + full dev-server compile of at least one page
    from each area: Creator Studio (Resources, Media, Studio Home),
    marketing (`/`), member portal (`/spaces/[slug]/community`).

---

## 7. Non-goals

- **Do not** consolidate `styles/tokens.css` (legacy) into `fc-tokens.css`
  as part of this rename. That's a follow-up.
- **Do not** rename or restructure any primitive's public API. Only the
  folder path and one symbol (`GroveProviders`) change.
- **Do not** update the `components/ui/` legacy folder (it isn't
  design-system code).
- **Do not** touch anything under `backend/`, `scripts/`, `prisma/`,
  `next.config.ts`, or `package.json`.
- **Do not** delete `docs/grove-layout-audit.md` etc. — rename via `git mv`
  so history is preserved.

---

## Summary

- **Scope:** 3 docs, 1 stylesheet, 1 folder, 26 files, 1 symbol, 132
  token declarations, ~425 token usages, 6 keyframes, 10 import
  statements.
- **Risk:** Low. Entirely mechanical. No runtime behaviour changes.
- **Blast radius:** Confined to `frontend/src/components/grove/`,
  `frontend/src/styles/grove-tokens.css`, `docs/grove-*.md`, and the
  6 files that import from Grove.
- **Sequence:** Six phases; only Phase 4 needs to be one atomic commit.
- **Verification:** TypeScript catches missed imports; visual smoke test
  catches missed tokens; the collective-versus-design-system distinction
  survives because "The Grove" (article + collective) is grep-preserved.

The rename can safely land this week. No code has been changed. Awaiting
approval to begin Phase 1.
