/**
 * Which pages Cloudflare Web Analytics is allowed to see.
 *
 * An allow-list, not a deny-list, and that choice is the whole safety
 * story. A deny-list fails open: the next route someone adds is
 * tracked by default, and the day that route carries a token in its
 * path nobody notices. This fails closed — a new page is invisible to
 * analytics until it is named here, which is a missing number rather
 * than a leaked secret.
 *
 * Only pages whose content is the same for every visitor appear below.
 * That is a stricter rule than "unauthenticated visitors can reach
 * it", and it is deliberate: ``/spaces/{slug}/events`` is public in a
 * Collective that publishes its Gatherings and members-only in the
 * next one, so tracking it would mean tracking a members-only page
 * whenever a member opened it. The public-by-design Collective and
 * Pathway surfaces — their About pages — carry no such ambiguity.
 *
 * What is deliberately absent
 * ---------------------------
 *
 * ``/invites/{token}``, ``/reset-password?token=`` and
 * ``/verify-email?token=`` each carry a bearer credential in the URL.
 * Cloudflare records Path as a reportable dimension, so a tracked
 * visit to one of those would put a live token in an analytics
 * dashboard. They are absent from the allow-list *and* named in
 * ``NEVER_TRACKED`` below — two independent reasons they can never be
 * reported, because this is the one mistake with no recovery.
 *
 * The auth pages (``/login``, ``/signup``, ``/forgot-password``) are
 * also absent, though they are harmless public pages. They carry
 * ``?next=`` and would put a destination path into the dashboard for
 * no reason worth the question it raises. Funnel numbers are not worth
 * a query string nobody audited.
 *
 * Area-gated Collective pages are absent for the reason above. If
 * fuller Collective coverage is wanted later, the honest way to get it
 * is a signed-out check at render time, not a longer list here.
 */

/**
 * Pages tracked by exact path.
 *
 * Every entry here renders for an anonymous visitor. That is a
 * stronger requirement than "the middleware does not protect it", and
 * the difference cost three wrong entries on the first pass: a page
 * can gate or redirect itself without the middleware knowing. ``/about``
 * is a body of ``redirect('/')``; ``/build-your-place`` is a legacy
 * alias that redirects; ``/build-your-collective`` is the authenticated
 * creator ritual, which reads creator drafts and sends a signed-out
 * caller to ``/login``. None of them belongs on a public allow-list,
 * and ``/build-your-collective`` would have been reported for a
 * signed-in creator.
 *
 * ``/about`` is simply absent rather than refused below: it is dead,
 * not sensitive, and absence is what a fail-closed allow-list does
 * with a page nobody named.
 *
 * ``analytics.test.ts`` now asserts this property from each page's
 * source, so the next wrong entry fails a test rather than reaching
 * production.
 */
const TRACKED_EXACT: ReadonlySet<string> = new Set([
  // Marketing and orientation
  '/',
  '/for-creators',
  '/real-journey',
  '/membership',
  '/ecosystem-interest',
  '/leadershipbodychart',
  '/tnlbook',
  '/tnlbook123',
  // Public discovery
  '/spaces',
  '/discover-places',
  '/world-guide',
])

/**
 * Pages tracked by shape. Each segment is ``[^/]+`` rather than
 * ``.*`` so a pattern can never widen by a path growing deeper —
 * ``/spaces/x/about`` matches, ``/spaces/x/about/secret`` does not.
 */
const TRACKED_PATTERNS: readonly RegExp[] = [
  /^\/discover-places\/[^/]+$/,
  /^\/world-guide\/[^/]+$/,
  // A Collective's public front door: the page built to explain what
  // it is to someone who has not joined.
  /^\/spaces\/[^/]+\/about$/,
  // The same for one Pathway inside it.
  /^\/spaces\/[^/]+\/pathways\/[^/]+\/about$/,
]

/**
 * Roots that must never be reported, whatever the allow-list says.
 *
 * Redundant by construction — nothing here matches a pattern above —
 * and kept anyway. It states the intent where a reader will look for
 * it, and it means a careless widening of the allow-list still cannot
 * reach a token URL, an admin screen or a private conversation.
 */
const NEVER_TRACKED: readonly string[] = [
  // Bearer credentials in the URL
  '/invites',
  '/reset-password',
  '/verify-email',
  // Authenticated member areas
  '/dashboard',
  '/profile',
  '/settings',
  '/onboarding',
  '/messages',
  '/notifications',
  '/checkout',
  // Internal
  '/admin',
  '/creator',
  '/creator-studio',
  '/creator-onboarding',
  // The creator ritual and its legacy alias. Signed out it redirects
  // to /login, but a signed-in creator renders it — so it is an
  // authenticated surface, not a public one.
  '/build-your-collective',
  '/build-your-place',
  '/dev',
  '/api',
  // Public, but carrying ?next= / ?token=
  '/login',
  '/signup',
  '/forgot-password',
]

function normalize(pathname: string): string {
  const p = pathname.split('?')[0].split('#')[0]
  return p !== '/' && p.endsWith('/') ? p.slice(0, -1) : p
}

/** Segment-boundary match, so ``/creatorstudio`` is not under ``/creator``. */
function isUnder(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(prefix + '/')
}

/**
 * May this page be reported to Cloudflare Web Analytics?
 *
 * Pure, so the rule can be tested directly rather than inferred from
 * a rendered component.
 */
export function isTrackablePath(pathname: string): boolean {
  if (!pathname || !pathname.startsWith('/')) return false
  const p = normalize(pathname)
  // Refusal wins. Checked first so no allow-list entry can override it.
  if (NEVER_TRACKED.some((prefix) => isUnder(p, prefix))) return false
  if (TRACKED_EXACT.has(p)) return true
  return TRACKED_PATTERNS.some((re) => re.test(p))
}

/** Exported for the tests that assert the two lists cannot overlap. */
export const __lists = { TRACKED_EXACT, TRACKED_PATTERNS, NEVER_TRACKED }
