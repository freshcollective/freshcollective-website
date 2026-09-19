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

## Superseded

These predate the approved set and are kept only until Phase B
repoints the three `<img>` tags that still name the first one
(`AuthCard.tsx`, `SignupForm.tsx`, `PrototypeSignupForm.tsx`). No role
resolves to any of them.

- `fresh-collective-logo-navy-gold-white.png` — byte-identical to
  `…-navy-gold-on-white.png`; still referenced by three components.
- `fresh-collective-logo-teal-gold-white.png` — byte-identical to
  `…-teal-gold-on-white.png`.
- `fresh-collective-logo-square-teal.png` — byte-identical to
  `…-white-gold-on-teal-gradient.png`.
- `fresh-collective-logo-transparent-gold.png` — white dragonfly, gold
  wordmark, transparent. Not part of the approved set; the navy role
  now uses navy-backed artwork.
- `fresh-collective-logo-transparent-teal.png` — white dragonfly, teal
  wordmark, transparent. Matches no approved role.
