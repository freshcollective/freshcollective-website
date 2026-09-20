# Fresh Collective brand artwork

Five approved files, supplied by Lindsey. Each was identified by
reading its pixels — background, dragonfly colour, wordmark colour —
rather than by its name, and each identification is pinned as a test in
`backend/tests/test_brand_assets.py::TestApprovedArtworkContent`.

Filenames here read **ink … on background**, because the previous
naming did not and an earlier pass mapped the marketing lockup to the
wrong file on the strength of its name.

| File | Background | Dragonfly | Wordmark | Role |
|---|---|---|---|---|
| `fresh-collective-logo-navy-gold-on-white.png` | flat white | navy | gold | `primary_light_logo` |
| `fresh-collective-logo-teal-gold-on-white.png` | flat white | teal | gold | `alternate_light_logo` |
| `fresh-collective-logo-white-on-teal.png` | flat teal | white | **white** | `logo_on_teal` |
| `fresh-collective-logo-white-gold-on-navy.png` | flat navy | white | gold | `logo_on_navy` |
| `fresh-collective-logo-white-gold-on-teal-gradient.png` | teal→navy gradient | white | gold | `marketing_hero_logo` |

The two teal treatments are the pair most easily confused: the flat one
sets the wordmark in **white**, the gradient one in **gold**. They are
different roles and are not interchangeable.

Roles are defined in `backend/app/brand/roles.py`; nothing reads this
directory by filename except that module.

## Compact marks — derived, not drawn

| File | Background | Symbol | Role |
|---|---|---|---|
| `fresh-collective-mark-navy-on-transparent.png` | transparent | navy | `compact_light_mark` |
| `fresh-collective-mark-white-on-transparent.png` | transparent | white | `compact_dark_mark` |

These are the dragonfly and broken circle from the approved lockups
above, with the FRESH COLLECTIVE wordmark cropped away. Nothing was
redrawn, re-traced or recoloured: `backend/scripts/derive_compact_marks.py`
recovers each drawing's own alpha by un-compositing its flat
background, crops to the symbol and pads to a square, with no
resampling at any point. Recompositing the result onto the original
background reproduces the source to within 1/255.

Regenerate with `cd backend && .venv/bin/python scripts/derive_compact_marks.py`.
`tests/test_brand_assets.py::TestCompactMarkDerivation` re-runs the
derivation and compares, so these files cannot drift from the artwork
they came from.

**They need room.** The stroke is 1.34% of the mark's width, so a 24px
box renders it at 0.32 CSS pixels and the dragonfly dissolves into a
grey haze. Measured on screen, 32px is the floor and 36px is where the
wing detail separates — which is what `CHROME_MARK_PX` in
`frontend/src/lib/brand.ts` is set to. Anything smaller wants a
heavier-stroke mark drawn for the size, not a smaller copy of this one.

## App icon — composed, not designed separately

| File | Where | Role |
|---|---|---|
| `fresh-collective-app-icon.png` | here, 512px | `favicon_app_icon` |
| `../../src/app/favicon.ico` | Next.js file convention, 16/32/48 | browser tab |
| `../../src/app/icon.png` | Next.js file convention, 512px | modern browsers |
| `../../src/app/apple-icon.png` | Next.js file convention, 180px | iOS home screen |

All four come from one composition: the white dragonfly from
`fresh-collective-mark-white-on-transparent.png` on the teal that
`fresh-collective-logo-white-on-teal.png` already puts behind it, with
6% margin and no wordmark. Generate with
`cd backend && .venv/bin/python scripts/compose_app_icon.py`.

The three files under `src/app/` exist because Next.js resolves icons
from the filesystem at build time and cannot ask the database what the
brand is. They are not a second design — a test regenerates and
compares them against the same composition. An admin override of
`favicon_app_icon` changes every runtime surface immediately and the
browser tab at the next deploy.

At 16px the hairline linework resolves to a soft winged silhouette
rather than a readable dragonfly. That is the stroke's limit, not the
composition's: teal was chosen over navy and 6% over 14% precisely
because they hold up best there. Only a heavier-stroke redraw would do
better, and that is a design decision rather than a build step.

## Superseded — unreferenced, safe to delete

As of Phase B **nothing in the codebase names any of these**. Every
surface resolves artwork through `backend/app/brand/roles.py` and
`frontend/src/lib/brand.ts`, and both name only the five files above.

They are still on disk because deleting brand artwork is its own
decision, not a side-effect of a rendering change. Remove them in a
dedicated cleanup once you are satisfied nothing outside this repo
(a newsletter, a slide deck, a saved link) depends on the URL.

- `fresh-collective-logo-navy-gold-white.png` — byte-identical to
  `…-navy-gold-on-white.png`. Was named by AuthCard, SignupForm and
  PrototypeSignupForm until Phase B moved them onto the shared
  component.
- `fresh-collective-logo-teal-gold-white.png` — byte-identical to
  `…-teal-gold-on-white.png`.
- `fresh-collective-logo-square-teal.png` — byte-identical to
  `…-white-gold-on-teal-gradient.png`.
- `fresh-collective-logo-transparent-gold.png` — white dragonfly, gold
  wordmark, transparent. Not part of the approved set; `logo_on_navy`
  now uses navy-backed artwork.
- `fresh-collective-logo-transparent-teal.png` — white dragonfly, teal
  wordmark, transparent. Matches no approved role.
