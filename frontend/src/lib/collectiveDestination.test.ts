import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  BECOME_A_CREATOR_HREF,
  BECOME_A_CREATOR_LABEL,
  CREATOR_ONLY_BADGE,
  CREATOR_STATUS_HREF,
  CREATOR_STATUS_LABEL,
  activeJoinedSlugs,
  collectiveCardAction,
  collectiveCardHref,
} from './collectiveDestination.ts'

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

  test('a signed-out visitor triggers no request at all', () => {
    // The good half of the commit that caused the regression: the
    // early return must come before every fetch, not after it.
    //
    // Asserted against EVERY call site rather than one hardcoded
    // `await getMyMemberships()` string. That literal broke the moment
    // the helper gained a second request, even though the property it
    // protects was intact — and a test that fails on a refactor which
    // preserves its own guarantee teaches people to edit the test.
    // This version also covers the new call, which the old one did not.
    const src = helper()
    const guard = src.indexOf('if (!cookieStore.get(SESSION_COOKIE))')
    assert.ok(guard > 0, 'the session check exists')
    for (const call of ['getMyMemberships(', 'getMe(']) {
      let at = src.indexOf(call)
      // Skip the import line, which legitimately precedes the guard.
      while (at !== -1) {
        const lineStart = src.lastIndexOf('\n', at) + 1
        const line = src.slice(lineStart, src.indexOf('\n', at))
        if (!line.trimStart().startsWith('import')) {
          assert.ok(at > guard, `${call} must sit after the session check`)
        }
        at = src.indexOf(call, at + 1)
      }
    }
    // And the signed-out answer is a complete value, not a partial one.
    assert.match(src, /isLoggedIn: false/)
    assert.match(src, /joinedSlugs: \[\]/)
    assert.match(src, /isCreator: false/)
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


// ---------------------------------------------------------------------------
// Creator-only Collectives
// ---------------------------------------------------------------------------

describe('a creator-only Collective card', () => {
  const wb = {
    slug: 'world-builders',
    name: 'World Builders',
    isReal: true,
    creator_only: true,
  }
  const viewer = (over: Partial<{
    isJoined: boolean; isLoggedIn: boolean; isCreator: boolean
  }> = {}) => ({
    isJoined: false, isLoggedIn: false, isCreator: false, ...over,
  })

  // The journey these three pin:
  //
  //   Explore Collectives → World Builders About → For Creators
  //
  // The card used to jump straight to ``/for-creators``, correctly at
  // the time, because the About page answered 401 to an anonymous
  // caller and would have been a dead end. It is public and indexable
  // now, and it is the better first stop — it explains what World
  // Builders is before anybody is asked to become a creator, and it
  // carries ``Explore Becoming a Creator →`` itself.

  test('a logged-out visitor is sent to the public About page', () => {
    const a = collectiveCardAction(wb, viewer())
    assert.equal(a.label, 'Explore →')
    assert.equal(a.href, '/spaces/world-builders/about')
  })

  test('a signed-in non-creator is sent to the same page', () => {
    // Signing up is not becoming a creator — the backend is explicit
    // that the role, not an account, is what grants membership — so
    // these two viewers get the same answer.
    const a = collectiveCardAction(wb, viewer({ isLoggedIn: true }))
    assert.equal(a.label, 'Explore →')
    assert.equal(a.href, '/spaces/world-builders/about')
  })

  test('the card no longer shortcuts past the About page', () => {
    for (const v of [viewer(), viewer({ isLoggedIn: true })]) {
      assert.notEqual(collectiveCardAction(wb, v).href, BECOME_A_CREATOR_HREF)
    }
  })

  test('neither is sent into the Collective itself', () => {
    // The About page is public; everything behind it is not. The card
    // must never point at the member entrance for somebody who cannot
    // open it.
    for (const v of [viewer(), viewer({ isLoggedIn: true })]) {
      assert.notEqual(collectiveCardAction(wb, v).href, '/spaces/world-builders')
    }
  })

  test('the become-a-creator invitation still exists, on the About page', () => {
    // Moved rather than removed: the wording is unchanged and lives
    // where the visitor now meets it.
    assert.equal(BECOME_A_CREATOR_LABEL, 'Explore Becoming a Creator →')
    assert.equal(BECOME_A_CREATOR_HREF, '/for-creators')
  })

  test('a member enters the Collective', () => {
    const a = collectiveCardAction(wb, viewer({ isLoggedIn: true, isJoined: true, isCreator: true }))
    assert.equal(a.label, 'Enter World Builders →')
    assert.equal(a.href, '/spaces/world-builders')
  })

  test('the entry label is built from the name, not hardcoded', () => {
    // So the rule reads as a rule. "Enter World Builders →" is what it
    // produces for the one Collective carrying the flag today.
    const other = { ...wb, slug: 'makers', name: 'Makers' }
    assert.equal(
      collectiveCardAction(other, viewer({ isJoined: true })).label,
      'Enter Makers →',
    )
  })

  test('a membership is all the eligibility signal the card needs', () => {
    // Membership is derived from creator eligibility and reconciled on
    // every authenticated request, so an active membership means
    // eligible. The card asks for no separate eligibility check — and
    // a member who somehow lacked the role still enters, because the
    // server already decided they belong.
    const a = collectiveCardAction(wb, viewer({ isLoggedIn: true, isJoined: true, isCreator: false }))
    assert.equal(a.label, 'Enter World Builders →')
  })

  test('there is no Join action for anybody', () => {
    // ``join_space`` answers 403 for an auto-grant Collective
    // unconditionally. A Join button would have nothing to call.
    for (const v of [
      viewer(),
      viewer({ isLoggedIn: true }),
      viewer({ isLoggedIn: true, isCreator: true }),
      viewer({ isLoggedIn: true, isCreator: true, isJoined: true }),
    ]) {
      assert.ok(!/join/i.test(collectiveCardAction(wb, v).label))
    }
  })

  test('a creator whose access has lapsed is sent to their account', () => {
    // Suspended or cancelled: the role is still ``creator`` but the
    // membership is paused or removed, so they are not joined. They
    // must not be invited to become something they already are.
    const a = collectiveCardAction(wb, viewer({ isLoggedIn: true, isCreator: true }))
    assert.equal(a.label, CREATOR_STATUS_LABEL)
    assert.equal(a.href, CREATOR_STATUS_HREF)
    assert.notEqual(a.label, BECOME_A_CREATOR_LABEL)
    // And they are not offered entry.
    assert.ok(!a.href.startsWith('/spaces/'))
  })

  test('the badge says For Creators Only', () => {
    assert.equal(CREATOR_ONLY_BADGE, 'For Creators Only')
  })

  test('the old shorter wording is gone', () => {
    // "For Creators" alone read as a category rather than a
    // restriction. The badge has to say the restriction.
    assert.notEqual(CREATOR_ONLY_BADGE, 'For Creators')
    assert.match(CREATOR_ONLY_BADGE, /Only$/)
  })
})

describe('ordinary Collective cards are unchanged', () => {
  const embodyCard = { slug: 'embody', name: 'EMBODY', isReal: true }
  const viewer = (over = {}) => ({
    isJoined: false, isLoggedIn: false, isCreator: false, ...over,
  })

  test('a member still gets Continue', () => {
    const a = collectiveCardAction(embodyCard, viewer({ isJoined: true }))
    assert.equal(a.label, 'Continue →')
    assert.equal(a.href, '/spaces/embody')
  })

  test('everyone else still gets Explore and the About page', () => {
    for (const v of [viewer(), viewer({ isLoggedIn: true }), viewer({ isCreator: true })]) {
      const a = collectiveCardAction(embodyCard, v)
      assert.equal(a.label, 'Explore →')
      assert.equal(a.href, '/spaces/embody/about')
    }
  })

  test('the creator role changes nothing for an ordinary Collective', () => {
    assert.deepEqual(
      collectiveCardAction(embodyCard, viewer({ isCreator: true })),
      collectiveCardAction(embodyCard, viewer()),
    )
  })

  test('a placeholder still invites a signup', () => {
    const a = collectiveCardAction({ slug: 'someday', isReal: false }, viewer())
    assert.equal(a.href, '/signup')
  })

  test('it delegates to the one destination rule rather than restating it', () => {
    // Two rules for where a card goes is how Explore and the dashboard
    // disagreed about the same person before.
    for (const isJoined of [true, false]) {
      assert.equal(
        collectiveCardAction(embodyCard, viewer({ isJoined })).href,
        collectiveCardHref(embodyCard, isJoined),
      )
    }
  })
})

describe('the Explore card renders both', () => {
  const card = () => read('components/explore/CollectiveCard.tsx')

  test('the badge is the existing pill, not a new component', () => {
    const src = card()
    // Same class string the Joined badge uses — one visual language.
    const pill = /rounded-full px-2\.5 py-0\.5 text-\[10px\] font-semibold uppercase tracking-wide/g
    assert.ok((src.match(pill) ?? []).length >= 2, 'both badges share the pill')
    assert.match(src, /CREATOR_ONLY_BADGE/)
    assert.match(src, /space\.creator_only/)
  })

  test('label and destination come from the shared rule', () => {
    const src = card()
    assert.match(src, /collectiveCardAction\(/)
    assert.ok(!/isJoined \? 'Continue →' : 'Explore →'/.test(src),
      'the card must not keep its own copy of the label rule')
  })

  test('Explore passes the viewer role through', () => {
    assert.match(read('app/spaces/page.tsx'), /isCreator=\{isCreator\}/)
    assert.match(
      read('components/explore/ExploreCollectivesExperience.tsx'),
      /isCreator=\{isCreator\}/,
    )
  })
})
