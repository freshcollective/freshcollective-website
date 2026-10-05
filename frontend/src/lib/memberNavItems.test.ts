import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  CREATOR_STUDIO_HREF,
  CREATOR_STUDIO_ROLES,
  canAccessCreatorStudio,
} from './creatorStudioAccess.ts'
import { isNavItemActive, memberNavItems } from './memberNavItems.ts'

/**
 * The Creator Studio doorway in member navigation.
 *
 * Creators had no persistent way into Creator Studio from the main nav.
 * The risk in adding one is not the link, it is the gate: a second,
 * slightly different idea of "creator access" that drifts from the rule
 * guarding the route. So the access rule and the nav list are both
 * ordinary functions now, tested by running them.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const ALL_ON = { discoveryOn: true, waysToConnectOn: true }
const labels = (audience: Parameters<typeof memberNavItems>[0]) =>
  memberNavItems(audience).map((i) => i.label)

// ---------------------------------------------------------------------------
// Who sees it
// ---------------------------------------------------------------------------

describe('Creator Studio access', () => {
  test('a paid Creator sees it', () => {
    assert.equal(canAccessCreatorStudio({ role: 'creator' }), true)
  })

  test('a Community creator sees it', () => {
    // Community activation is role-only and writes no subscription row,
    // so anything keyed on a plan would lock out the entire free tier.
    assert.equal(canAccessCreatorStudio({ role: 'creator' }), true)
  })

  test('the Platform Owner sees it', () => {
    // An account/platform role, carried by ``admin`` — not a plan, and
    // not covered by a bare ``role === 'creator'`` check.
    assert.equal(canAccessCreatorStudio({ role: 'admin' }), true)
  })

  test('an ordinary member does not', () => {
    assert.equal(canAccessCreatorStudio({ role: 'user' }), false)
  })

  test('a signed-out or unknown visitor does not', () => {
    assert.equal(canAccessCreatorStudio(null), false)
    assert.equal(canAccessCreatorStudio(undefined), false)
    assert.equal(canAccessCreatorStudio({}), false)
    assert.equal(canAccessCreatorStudio({ role: null }), false)
    assert.equal(canAccessCreatorStudio({ role: '' }), false)
  })

  test('a future creator tier arrives with the role, needing no change here', () => {
    // The point of not enumerating plans: a new paid tier is still the
    // creator role, so it is included by construction. This asserts the
    // shape of the rule — a role set, nothing plan-shaped.
    assert.deepEqual([...CREATOR_STUDIO_ROLES], ['creator', 'admin'])
  })

  test('the rule names no plan, tier or slug', () => {
    const src = read('lib/creatorStudioAccess.ts')
    const code = src
      .split('\n')
      .filter((l) => !l.trimStart().startsWith('*') && !l.trimStart().startsWith('/*')
                     && !l.trimStart().startsWith('//'))
      .join('\n')
    for (const forbidden of [
      'founding', 'pro', 'community_plan', 'plan_slug', 'monthly_price',
      'is_purchasable', 'paid_offers_enabled', 'subscription',
    ]) {
      assert.ok(
        !code.toLowerCase().includes(forbidden),
        `creatorStudioAccess must not key on ${forbidden}`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// The list
// ---------------------------------------------------------------------------

describe('member nav items', () => {
  test('a creator-capable user gets Creator Studio after Messages', () => {
    assert.deepEqual(labels({ ...ALL_ON, creatorStudioOn: true }), [
      'Your World',
      'Explore Collectives',
      'Discover Places',
      'Ways to Connect',
      'Messages',
      'Creator Studio',
    ])
  })

  test('an ordinary member gets the list unchanged', () => {
    // The regression half: adding a creator doorway must not alter what
    // anybody else sees.
    assert.deepEqual(labels({ ...ALL_ON, creatorStudioOn: false }), [
      'Your World',
      'Explore Collectives',
      'Discover Places',
      'Ways to Connect',
      'Messages',
    ])
  })

  test('the href is /creator-studio', () => {
    const item = memberNavItems({ ...ALL_ON, creatorStudioOn: true })
      .find((i) => i.label === 'Creator Studio')
    assert.ok(item)
    assert.equal(item.href, '/creator-studio')
    assert.equal(item.href, CREATOR_STUDIO_HREF)
  })

  test('it is the last item, so it lands before the bell and before Notifications', () => {
    const items = memberNavItems({ ...ALL_ON, creatorStudioOn: true })
    assert.equal(items[items.length - 1].href, CREATOR_STUDIO_HREF)
    // Desktop puts the auth cluster after the list; the drawer puts
    // Notifications after it. One position satisfies both.
    assert.equal(items[items.length - 2].href, '/messages')
  })

  test('the two pillar flags still gate their own entries', () => {
    assert.deepEqual(
      labels({ discoveryOn: false, waysToConnectOn: true, creatorStudioOn: true }),
      ['Your World', 'Explore Collectives', 'Ways to Connect', 'Messages',
       'Creator Studio'],
    )
    assert.deepEqual(
      labels({ discoveryOn: true, waysToConnectOn: false, creatorStudioOn: true }),
      ['Your World', 'Explore Collectives', 'Discover Places', 'Creator Studio'],
    )
  })

  test('Creator Studio does not depend on either pillar flag', () => {
    // It is not a pillar. A creator keeps the doorway with both flags
    // off, and a member never gains it with both on.
    const bothOff = { discoveryOn: false, waysToConnectOn: false }
    assert.ok(labels({ ...bothOff, creatorStudioOn: true }).includes('Creator Studio'))
    assert.ok(!labels({ ...bothOff, creatorStudioOn: false }).includes('Creator Studio'))
  })
})

// ---------------------------------------------------------------------------
// Active state
// ---------------------------------------------------------------------------

describe('active state', () => {
  test('Creator Studio is active on its own route and nested routes', () => {
    assert.equal(isNavItemActive('/creator-studio', CREATOR_STUDIO_HREF), true)
    assert.equal(isNavItemActive('/creator-studio/billing', CREATOR_STUDIO_HREF), true)
    assert.equal(
      isNavItemActive('/creator-studio/pathways/the-real-journey', CREATOR_STUDIO_HREF),
      true,
    )
  })

  test('viewing a Collective you created does not mark it active', () => {
    // The explicit requirement. A creator looking at their own
    // Collective is on a member surface; Explore Collectives lights up.
    assert.equal(isNavItemActive('/spaces/embody', CREATOR_STUDIO_HREF), false)
    assert.equal(
      isNavItemActive('/spaces/embody/community/p1', CREATOR_STUDIO_HREF),
      false,
    )
    assert.equal(isNavItemActive('/spaces/embody', '/spaces'), true)
  })

  test('the legacy /creator prefix does not mark it active', () => {
    // ``/creator/...`` renders the same shell but is a different route.
    // A looser ``startsWith('/creator')`` would match it — almost right,
    // which is the kind of coincidence that stops being true later.
    assert.equal(isNavItemActive('/creator/spaces/embody', CREATOR_STUDIO_HREF), false)
    assert.equal(isNavItemActive('/creator-studios', CREATOR_STUDIO_HREF), false)
  })

  test('no other destination is marked active inside Creator Studio', () => {
    for (const href of [
      '/dashboard', '/spaces', '/discover-places', '/ways-to-connect',
      '/messages',
    ]) {
      assert.equal(
        isNavItemActive('/creator-studio/billing', href), false,
        `${href} should not be active inside Creator Studio`,
      )
    }
  })

  test('every other destination keeps the active behaviour it had', () => {
    assert.equal(isNavItemActive('/dashboard', '/dashboard'), true)
    assert.equal(isNavItemActive('/dashboard/anything', '/dashboard'), true)
    assert.equal(isNavItemActive('/discover-places/kew', '/discover-places'), true)
    assert.equal(isNavItemActive('/ways-to-connect/x', '/ways-to-connect'), true)
    assert.equal(isNavItemActive('/messages', '/messages'), true)
    assert.equal(isNavItemActive('/messages/thread-1', '/messages'), false)
    assert.equal(isNavItemActive('/settings/profile', '/dashboard'), false)
  })
})

// ---------------------------------------------------------------------------
// One definition, and one rendering of it
// ---------------------------------------------------------------------------

describe('there is exactly one creator-access rule', () => {
  test('the route guards and the nav all call the same helper', () => {
    for (const file of [
      'app/creator-studio/layout.tsx',
      'app/creator/layout.tsx',
      'components/layout/WorldHeader.tsx',
    ]) {
      const src = read(file)
      assert.ok(
        src.includes('canAccessCreatorStudio'),
        `${file}: must use the shared rule`,
      )
    }
  })

  test('nobody writes the role check out by hand any more', () => {
    for (const file of [
      'app/creator-studio/layout.tsx',
      'app/creator/layout.tsx',
      'components/layout/WorldHeader.tsx',
    ]) {
      const src = read(file)
      assert.ok(
        !src.includes("['creator', 'admin']"),
        `${file}: inlines the role set instead of calling the helper`,
      )
      assert.ok(
        !src.includes("role === 'creator'"),
        `${file}: a bare creator-role check excludes the Platform Owner`,
      )
    }
  })

  test('the header derives the doorway from the user it already has', () => {
    // No new prop, no second fetch, no client-side role guessing — the
    // shell is already given ``user.role``.
    const src = read('components/layout/WorldHeader.tsx')
    assert.ok(src.includes('creatorStudioOn: canAccessCreatorStudio(user)'))
  })
})

describe('both navigation surfaces render the same list', () => {
  // Desktop and drawer each map over ``items``, so the Creator Studio
  // entry cannot appear in one and not the other — which is how the
  // previous four-surface flag duplication went wrong.
  const src = read('components/layout/WorldHeader.tsx')

  test('desktop maps the shared list', () => {
    assert.ok(src.includes('<nav\n          aria-label="Member"'))
    assert.match(src, /aria-label="Member"[\s\S]{0,400}items\.map/)
  })

  test('the drawer maps the same list', () => {
    assert.match(src, /aria-label="Member — mobile"[\s\S]{0,200}items\.map/)
  })

  test('the drawer places it before Notifications', () => {
    // The list is rendered first, then the Notifications link, then the
    // profile link — so the last list item precedes Notifications.
    const listAt = src.indexOf('aria-label="Member — mobile"')
    const notificationsAt = src.indexOf("href=\"/notifications\"", listAt)
    const profileAt = src.indexOf("href=\"/settings/profile\"", notificationsAt)
    assert.ok(listAt > -1 && notificationsAt > listAt && profileAt > notificationsAt)
  })
})

// ---------------------------------------------------------------------------
// Responsive shape
// ---------------------------------------------------------------------------

describe('the header has room for the extra destination', () => {
  const src = read('components/layout/WorldHeader.tsx')

  test('the bar and the drawer swap at the same breakpoint', () => {
    // Exactly one of them is visible at every width. If these drifted
    // apart there would be a band with two navs or none.
    assert.ok(src.includes('lg:flex'), 'desktop nav is not lg:flex')
    assert.ok(src.includes('lg:hidden'), 'drawer is not lg:hidden')
    assert.ok(
      !src.includes('md:flex') && !src.includes('md:hidden'),
      'a md: breakpoint is left over, so the two navs no longer swap together',
    )
  })

  test('labels do not wrap mid-word', () => {
    assert.ok(src.includes('whitespace-nowrap text-[14px]'))
  })

  test('the nav can shrink rather than forcing overflow', () => {
    assert.ok(src.includes('min-w-0 flex-1'))
  })

  test('gaps tighten below the widest breakpoint', () => {
    assert.ok(src.includes('gap-4 lg:flex xl:gap-8'))
    assert.ok(src.includes('justify-between gap-4 xl:gap-8'))
  })
})
