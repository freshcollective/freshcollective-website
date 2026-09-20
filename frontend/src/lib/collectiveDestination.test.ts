import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { activeJoinedSlugs, collectiveCardHref } from './collectiveDestination.ts'

/**
 * Where a Collective card sends you.
 *
 * The regression these guard: Explore stopped resolving membership in
 * June 2026 while fixing a genuine signed-out problem, and every
 * member was sent to the joining page for their own Collective. The
 * signed-out half of that fix was right and is preserved here as its
 * own property — no membership request when there is no session.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const embody = { slug: 'embody', isReal: true }

describe('the destination rule', () => {
  test('a member is taken into the Collective', () => {
    assert.equal(collectiveCardHref(embody, true), '/spaces/embody')
  })

  test('someone who is not a member is taken to the page that explains it', () => {
    assert.equal(collectiveCardHref(embody, false), '/spaces/embody/about')
  })

  test('a signed-out visitor gets the same public page', () => {
    // Signed out is just "not a member" — there is no third branch,
    // which is why the card needs no login state to decide.
    assert.equal(collectiveCardHref(embody, false), '/spaces/embody/about')
  })

  test('a placeholder Collective invites a signup instead', () => {
    assert.equal(collectiveCardHref({ slug: 'someday', isReal: false }, false), '/signup')
    assert.equal(collectiveCardHref({ slug: 'someday', isReal: false }, true), '/signup')
  })

  test('the slug is carried through untouched', () => {
    assert.equal(collectiveCardHref({ slug: 'the-natural-leader-hub', isReal: true }, true),
      '/spaces/the-natural-leader-hub')
  })
})

describe('which Collectives count as joined', () => {
  test('active memberships do', () => {
    assert.deepEqual(
      activeJoinedSlugs([{ space_slug: 'embody', status: 'active' }]),
      ['embody'],
    )
  })

  test('a Collective you own but have no membership row for does too', () => {
    // /api/auth/me/memberships appends creator-owned Collectives with
    // role 'creator' and status 'active', so ownership needs no
    // special case on this side — but it must not be filtered out.
    assert.deepEqual(
      activeJoinedSlugs([
        { space_slug: 'world-builders', status: 'active', role: 'creator' } as never,
      ]),
      ['world-builders'],
    )
  })

  test('lapsed or pending membership does not', () => {
    assert.deepEqual(
      activeJoinedSlugs([
        { space_slug: 'embody', status: 'active' },
        { space_slug: 'nourish', status: 'pending' },
        { space_slug: 'gone', status: 'removed' },
      ]),
      ['embody'],
    )
  })

  test('no memberships is not an error', () => {
    assert.deepEqual(activeJoinedSlugs([]), [])
  })
})

describe('the signed-out property', () => {
  const helper = () => read('lib/joinedCollectives.ts')

  test('a signed-out visitor triggers no membership request', () => {
    // The good half of the commit that caused the regression. The
    // early return must come before the fetch, not after it.
    const src = helper()
    const guard = src.indexOf('if (!cookieStore.get(SESSION_COOKIE))')
    const fetchCall = src.indexOf('await getMyMemberships()')
    assert.ok(guard > 0, 'the session check exists')
    assert.ok(fetchCall > guard, 'and it short-circuits before the request')
    assert.match(src, /return \{ isLoggedIn: false, joinedSlugs: \[\] \}/)
  })

  test('signed in with nothing joined is not the same as signed out', () => {
    // A surface that greets people must not read an empty membership
    // list as "stranger".
    const src = helper()
    assert.match(src, /isLoggedIn: true/)
    assert.ok(!src.includes('joinedSlugs.length > 0'), 'login is never inferred from memberships')
  })

  test('a failed membership lookup degrades to the public page', () => {
    // getMyMemberships already swallows failures and returns []; the
    // point is that nothing downstream turns that into an error.
    const api = read('lib/serverApi.ts')
    assert.match(api, /getMyMemberships = cache\(async \(\) => \{\s*\n\s*const res = await fetchWithSession\('\/api\/auth\/me\/memberships'\)\s*\n\s*if \(!res\.ok\) return \[\]/)
  })
})

describe('Explore Collectives', () => {
  const page = () => read('app/spaces/page.tsx')

  test('it no longer hardcodes an empty membership list', () => {
    const src = page()
    assert.ok(!/joinedSlugs=\{\[\]\}/.test(src), 'the regression itself')
    assert.match(src, /joinedSlugs=\{joinedSlugs\}/)
  })

  test('membership comes from the shared server helper', () => {
    assert.match(page(), /getViewerCollectives\(\)/)
  })

  test('the public dataset stays public', () => {
    // Fixing this must not make the cacheable, unauthenticated spaces
    // endpoint user-specific.
    const src = page()
    assert.match(src, /getPublicSpaces\(\)/)
    assert.ok(!src.includes('/api/public/spaces?'), 'no per-user query')
  })

  test('the Joined badge, ordering and grouping all read the same set', () => {
    const exp = read('components/explore/ExploreCollectivesExperience.tsx')
    assert.match(exp, /joinedSet = useMemo\(\(\) => new Set\(joinedSlugs\)/)
    assert.ok(exp.includes('joinedSet.has(a.slug)'), 'joined-first sorting')
    assert.ok(exp.includes('joinedSet.size > 0'), 'the "Your collectives" label')
    assert.ok(exp.includes('isJoined={joinedSet.has(space.slug)}'), 'the card')
    assert.ok(read('components/explore/CollectiveCard.tsx').includes('Joined'), 'the badge')
  })

  test('desktop and mobile cannot disagree', () => {
    // One card, one responsive grid — there is no second code path to
    // keep in step.
    const exp = read('components/explore/ExploreCollectivesExperience.tsx')
    assert.equal((exp.match(/<CollectiveCard/g) ?? []).length, 1)
    assert.match(exp, /grid-cols-1 items-stretch gap-6 sm:grid-cols-2 lg:grid-cols-3/)
  })
})

describe('Discover Places', () => {
  const view = () => read('app/discover-places/[slug]/PlaceDetailView.tsx')
  const page = () => read('app/discover-places/[slug]/page.tsx')

  test('Collective cards there are membership-aware too', () => {
    const src = view()
    assert.ok(!/isJoined=\{false\}/.test(src), 'the hardcoded value is gone')
    assert.ok(!/isLoggedIn=\{false\}/.test(src))
    assert.equal((src.match(/isJoined=\{joined\.has\(/g) ?? []).length, 2,
      'both the solo card and the grid')
  })

  test('membership is resolved on the server, not per card', () => {
    assert.match(page(), /getViewerCollectives\(\)/)
    assert.match(page(), /joinedSlugs=\{viewer\.joinedSlugs\}/)
    // No client-side fetching crept into the view.
    assert.ok(!view().includes('getMyMemberships'))
    assert.ok(!view().includes("fetch('/api"))
  })

  test('signed-out Place browsing stays public and quiet', () => {
    // Same helper, same early return — one property, proven once.
    assert.ok(page().includes('getViewerCollectives'))
    assert.ok(!page().includes('redirect('), 'no auth gate was added')
  })

  test('Gathering and Series links are untouched', () => {
    const src = view()
    // The two deep links this page owns, unchanged: a Series and a
    // single Gathering both point straight at the thing, not at the
    // Collective that hosts it.
    assert.ok(src.includes('/gathering-series/${series.slug}'), 'Series link')
    assert.ok(src.includes('/events/${gathering.id}'), 'Gathering link')
    // The membership set is consulted for Collective cards only.
    assert.equal((src.match(/joined\.has\(/g) ?? []).length, 2)
  })
})
