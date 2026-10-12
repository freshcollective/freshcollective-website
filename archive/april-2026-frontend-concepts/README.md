# April 2026 frontend concepts — archive

**Historical reference only. Nothing in this directory is active
application code.** Nothing here is imported, built, linted, type-checked
or deployed. Render builds only `frontend/` and `backend/`
(`rootDir:` in `render.yaml`), so this directory is outside every build
root by design.

## Where this came from

These two files were the only unique, unrecoverable work inside a git
stash that had been carried on this repository for 169 days:

```
stash  87a752c082cd53a9a186d9744c6af07edacf4e1d
       "On main: WIP frontend redesign and auth page changes"
created 2026-04-26
base    7e7bdd6 "Improve admin sales form lookup fields"
```

They were *untracked* files inside that stash, so they had never been
committed anywhere and existed in exactly one place: the stash itself.
A stash is a poor home for work you want to keep — it is invisible in
normal history, survives no clone, and one careless `git stash clear`
destroys it. They are committed here so that stops being true.

The stash was dropped once these files were verified byte-identical to
the originals. The rest of its contents were deliberately not kept:

* ten application files (auth pages, dashboard, `next.config.ts`) that
  main had independently rewritten across the 773 commits since —
  superseded;
* `components/auth/AuthSplitShell.tsx` — superseded by
  `components/layout/AuthPageShell`, which does the same job and is what
  the live auth pages use;
* edits to five shared primitives (`Container`, `Button`, `Card`,
  `SectionHeading`, `LogoutButton`). Deliberately **not** archived as a
  patch: `Container` is imported by 34 files and the change alters its
  max-width and padding scale, so reviving it is a site-wide visual
  decision, not a file to restore;
* a junk file created by a mistyped `git stash push` whose contents were
  captured `git log` output.

## What is here

Both files keep their original repository-relative paths under this
directory, so where they came from is readable without consulting this
README.

### `frontend/src/components/sections/HeroPlatformVisual.tsx`

A self-contained marketing hero visual — a mocked product surface built
from pure JSX, no imports and no data dependencies. It was never
referenced by any page, and no equivalent exists in the application
today: `components/home/HomeHero.tsx` does not use it and nothing
imports the name. Kept because ~7 KB of hand-built visual is cheap to
store and expensive to recreate from memory.

### `frontend/.qa-screenshots/AUDIT.md`

A manual responsive audit at 390px / 768px / 1280px from the April
rebuild, written because screenshot tooling would not run on the
machine at the time. Its instructions reference
`frontend/scripts/visual-qa.cjs`, **which no longer exists** — so treat
this as a record of what was checked and concluded, not as a procedure
to follow.

## If you want to use any of this again

Copy the file into the application yourself and review it as new code.
It predates 773 commits of change: the design language, the colour
tokens and the component conventions have all moved since. Do not
restore it by patch.
