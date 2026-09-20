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
