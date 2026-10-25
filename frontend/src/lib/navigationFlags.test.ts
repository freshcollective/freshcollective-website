import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * Navigation visibility under the two pillar flags.
 *
 * The nav helpers live inside `.tsx` components, which the Node test
 * runner cannot import (it strips types, not JSX). So this asserts on
 * the source — the same approach the brand suite uses, and for the
 * same reason: the failure being guarded against is textual and
 * repeated across files. Four separate nav surfaces each had the two
 * entries gated on one shared flag, and the way that regresses is
 * somebody adding the fifth by copying the fourth.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

// WorldHeader's list moved into ``lib/memberNavItems.ts`` when the
// Creator Studio doorway was added, so that the list could be tested by
// running it rather than by reading it — see memberNavItems.test.ts.
// The source check follows it there; the other three surfaces still
// build their lists inline.
const NAV_SURFACES = [
  'components/layout/PublicHeader.tsx',
  'lib/memberNavItems.ts',
  'components/layout/MobileNav.tsx',
  'app/dashboard/page.tsx',
]

describe('every nav surface gates the two pillars separately', () => {
  for (const file of NAV_SURFACES) {
    test(file, () => {
      const src = read(file)
      const discoverLine = src
        .split('\n')
        .find((l) => l.includes("'/discover-places'") && l.includes('push'))
      const waysLine = src
        .split('\n')
        .find((l) => l.includes("'/ways-to-connect'") && l.includes('push'))

      if (discoverLine || waysLine) {
        // A nav list: each entry must be guarded by its own flag.
        assert.ok(discoverLine?.includes('discoveryOn'), `${file}: Discover Places not on discoveryOn`)
        assert.ok(waysLine?.includes('waysToConnectOn'), `${file}: Ways to Connect not on waysToConnectOn`)
        assert.ok(!waysLine?.includes('discoveryOn'), `${file}: Ways to Connect still keyed off discoveryOn`)
      } else {
        // The dashboard renders tiles rather than a list.
        assert.ok(src.includes('waysToConnectOn'), `${file}: no separate Ways to Connect gate`)
        assert.ok(src.includes('{discoveryOn && ('), `${file}: no Discover Places gate`)
      }
    })
  }
})

describe('route guards name the flag they depend on', () => {
  test('/discover-places is gated by the Discovery flag', () => {
    const src = read('app/discover-places/page.tsx')
    assert.ok(src.includes('if (!isDiscoveryPillarEnabled()) notFound()'))
    assert.ok(!src.includes('isWaysToConnectEnabled'))
  })

  test('/discover-places/[slug] is gated by the Discovery flag', () => {
    const src = read('app/discover-places/[slug]/page.tsx')
    assert.ok(src.includes('if (!isDiscoveryPillarEnabled()) notFound()'))
  })

  test('/ways-to-connect is gated by its own flag, not Discovery', () => {
    const src = read('app/ways-to-connect/page.tsx')
    // ``waysToConnectVisible`` is the Ways to Connect flag plus the
    // Platform Owner preview — still its own gate, still nothing to do
    // with Discovery.
    assert.ok(src.includes('if (!(await waysToConnectVisible())) notFound()'))
    assert.ok(
      !src.includes('isDiscoveryPillarEnabled'),
      'Ways to Connect must no longer import the Discovery flag',
    )
  })
})

describe('Discover Places artwork degrades instead of going blank', () => {
  // A CSS background cannot report a load failure, so the gradient is
  // layered underneath rather than swapped in by an onError handler.
  // Before this, a 403 left a blank band on every Place with artwork.
  for (const file of [
    'app/discover-places/DiscoverPlacesLive.tsx',
    'app/discover-places/[slug]/PlaceDetailView.tsx',
  ]) {
    test(file, () => {
      const src = read(file)
      // The artwork and the gradient are declared as two layers of one
      // `background` shorthand, artwork on top.
      assert.ok(
        src.includes('/ cover no-repeat'),
        `${file}: artwork is not declared as a background layer`,
      )
      assert.ok(
        src.includes('atmosphereBackground(atmosphereForSlug(place.slug, false)),'),
        `${file}: no gradient layered beneath the artwork`,
      )
      assert.ok(
        !src.includes('backgroundImage: `url('),
        `${file}: still sets a bare backgroundImage, which cannot fall back`,
      )
    })
  }
})


// ---------------------------------------------------------------------------
// Ways to Connect needs a signed-in viewer, where the other two do not
// ---------------------------------------------------------------------------

/**
 * ``/spaces`` and ``/discover-places`` are genuinely public and return
 * useful pages to a stranger. ``/ways-to-connect`` carries no auth
 * redirect of its own, so a signed-out visitor who follows the link
 * reaches the page, ``getWaysToConnect`` 401s, and they are shown the
 * unavailable state. The LINK was the only thing promising them
 * something, so the link is what changed — the route, its eligibility
 * rules and its access checks are untouched.
 *
 * Both public surfaces build this list inline, so both are checked.
 * They were identical and both wrong; the last test here fails if one
 * is fixed and the other is not.
 */
const PUBLIC_NAV_SURFACES = [
  'components/layout/PublicHeader.tsx',
  'components/layout/MobileNav.tsx',
]

describe('Ways to Connect is hidden from signed-out visitors', () => {
  for (const file of PUBLIC_NAV_SURFACES) {
    const src = read(file)
    const line = (needle: string) =>
      src.split('\n').find((l) => l.includes(needle) && l.includes('push'))

    test(`${file}: the Ways to Connect entry requires a signed-in viewer`, () => {
      const ways = line("'/ways-to-connect'")
      assert.ok(ways, `${file}: no Ways to Connect entry found`)
      assert.ok(
        /isLoggedIn/.test(ways),
        `${file}: Ways to Connect is not gated on isLoggedIn`,
      )
    })

    test(`${file}: the genuinely public entries are NOT gated on auth`, () => {
      // Hiding these would be a regression, not a fix — a logged-out
      // visitor is exactly who Explore Collectives is for.
      const explore = line("'/spaces'")
      const discover = line("'/discover-places'")
      assert.ok(explore && !/isLoggedIn/.test(explore),
        `${file}: Explore Collectives must stay public`)
      assert.ok(discover && !/isLoggedIn/.test(discover),
        `${file}: Discover Places must stay public`)
    })

    test(`${file}: the auth state is passed in, not read at render`, () => {
      // No flash. PublicHeader is an async server component that awaits
      // the user before building the list; MobileNav receives the
      // answer as a prop from it. Neither resolves auth in the browser,
      // so there is no frame in which the link exists and should not.
      assert.ok(
        /peerNavItems\([^)]*isLoggedIn[^)]*\)|peerNavItems\([^)]*!!user[^)]*\)/.test(src),
        `${file}: the nav builder is not given the auth state`,
      )
    })
  }

  test('both surfaces agree — one cannot be fixed without the other', () => {
    // The duplication is what allowed the same bug to exist twice.
    const gated = PUBLIC_NAV_SURFACES.map((f) => {
      const ways = read(f)
        .split('\n')
        .find((l) => l.includes("'/ways-to-connect'") && l.includes('push'))
      return /isLoggedIn/.test(ways ?? '')
    })
    assert.deepEqual(gated, [true, true], 'the two nav surfaces disagree')
  })

  test('PublicHeader resolves the user server-side before the nav is built', () => {
    const src = read('components/layout/PublicHeader.tsx')
    assert.match(src, /export default async function PublicHeader/)
    const userAt = src.indexOf('await getCurrentUser()')
    const navAt = src.indexOf('peerNavItems(')
    const callAt = src.indexOf('peerNavItems(discoveryOn')
    assert.ok(userAt > -1 && callAt > userAt,
      'the user must be resolved before the nav list is built')
    assert.ok(navAt > -1)
  })

  test('the route itself is unchanged — no auth redirect was added', () => {
    // The fix is the link, not the page. Adding a redirect here would
    // change access behaviour, which was explicitly out of scope.
    const page = read('app/ways-to-connect/page.tsx')
    assert.ok(
      !/redirect\(['"`]\/login/.test(page),
      'a login redirect was added to the route; only the nav should change',
    )
    assert.match(page, /waysToConnectVisible\(\)/)
  })
})
