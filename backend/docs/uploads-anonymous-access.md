# Anonymous access to `/api/uploads/*`

## What changed, and why

`serve_upload` used to depend on `get_current_user`, so every request
from a logged-out visitor answered **401** before any authorisation
ran. Three pages are reachable without an account and render images
from that route, which meant each of them carried broken images for
exactly the audience it was written for:

| Page | Image it needs |
|---|---|
| Explore — `/spaces` | the Collective cover, `covers/…` |
| Collective About — `/spaces/{slug}/about` | the logo, `logos/{slug}/…` |
| Pathway About — `/spaces/{slug}/pathways/{p}/about` | the Pathway cover, `pathway-covers/…` or `media/{slug}/…` |

Two of those were confirmed broken against production before the fix.
The Pathways *list* (`/spaces/{slug}/pathways`) is **not** affected —
it answers 404 to a logged-out visitor by design, so it has no
anonymous audience to serve.

The route now depends on `get_optional_user`. Anonymous callers reach
`authorize_upload`, which hands them to `_anonymous_may_read` — a
deliberately small matrix in `backend/app/uploads/authorization.py`.

## What an anonymous caller may read

Four things, and only when the Collective they belong to is **public
and active**:

* `covers/…` — the Collective's own cover
* `logos/{slug}/…` — its logo
* `pathway-covers/…` — a Pathway cover
* `media/{slug}/…` — the same four when chosen from the Asset Library
  rather than uploaded directly, and only where a cover field actually
  points at the key

Everything else is refused: avatars, island artwork, Gathering
thumbnails, step resources, Offering files and covers, community
images, World Guide help content, and any Asset Library image not in
use as one of those covers.

`island-artwork` is worth naming. It shares a resolver with `logos` in
the signed-in dispatch table, so a grant written per *resolver* rather
than per *prefix* would have let it through. No public payload exposes
it.

## Every anonymous refusal is the same 401

The signed-in matrix distinguishes **403** ("exists, not yours") from
**404** ("resolves to no row"). That distinction is useful to someone
who has already proved who they are, and it is deliberately withheld
from anonymous callers: handing it over would create an enumeration
oracle that did not exist before, since previously every anonymous
request was a flat 401 and revealed nothing. `_authorise_anonymous`
collapses all of it back to one 401, and a test asserts the three
shapes are indistinguishable.

## Caching, and why two different numbers

An anonymous public-cover response carries
`Cache-Control: public, max-age=86400` and `Vary: Cookie`, so a repeat
visit does not mint a fresh pre-signed URL.

In R2 mode the response is a 302 to a pre-signed URL, so **the cache
lifetime and the signature lifetime are coupled**. Caching the
redirect for a day while the signature lasts the default five minutes
would serve a dead link for 23h55m — strictly worse than not caching
at all. So an anonymous public-cover grant signs for
`_PUBLIC_COVER_URL_EXPIRY_SECONDS` (25 hours) while the cache header
allows 24, leaving an hour of headroom: a redirect served at the last
moment of its cache lifetime still has time left on it.

A day-long signature is acceptable **for this subset and no other**.
The 300-second default exists because a leaked private URL is a
disclosure; these are cover images on public, indexed pages, already
fetchable by anyone with no session. Nothing else gets the longer
lifetime — the flag is set only by an anonymous public-cover grant,
and `authorize_upload` returns `False` for every signed-in answer.

## Follow-up: rate limiting

**Not done, and worth doing.** `/api/uploads/*` has no rate limiter.
Until this change it was implicitly protected by requiring a session;
it is now an unauthenticated endpoint that mints an R2 pre-signed URL
per uncached request.

The exposure is bounded — only images already linked from public
pages, and the 24-hour cache header removes most repeat traffic — but
an unauthenticated caller ignoring the cache can still drive presign
calls and egress. Shipping without a limiter was a deliberate call to
keep the fix small, not an oversight.

If it is added, the shape that fits: a per-IP limit on the anonymous
branch only, leaving signed-in traffic alone, using the `slowapi`
limiter the app already configures. The thing to avoid is a global
limit that throttles a signed-in member loading a Collective full of
images.
