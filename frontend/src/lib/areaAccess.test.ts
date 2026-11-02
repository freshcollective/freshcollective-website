import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { canReachArea } from './collectiveAreas.ts'
import { isProtectedRoute } from '../proxyRouting.ts'

/**
 * One resolved answer, read everywhere.
 *
 * The Members tab and the Members Home tile once disagreed, and
 * Explore and the dashboard disagreed about membership, both because
 * two places worked the same rule out for themselves. Area policies
 * multiply that risk by four surfaces and three states, so the client
 * derives nothing: it reads ``area_access`` and reports.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

describe('reading the resolved set', () => {
  test('an area in the set is reachable', () => {
    assert.equal(canReachArea({ area_access: ['about', 'gatherings'] }, 'gatherings'), true)
  })

  test('an area absent from it is not', () => {
    assert.equal(canReachArea({ area_access: ['about'] }, 'pathways'), false)
  })

  test('an empty set closes everything', () => {
    assert.equal(canReachArea({ area_access: [] }, 'about'), false)
  })

  test('an older payload without the field behaves as before', () => {
    // The API guards independently, so a stale client renders an empty
    // page rather than leaking anything.
    assert.equal(canReachArea({}, 'conversations'), true)
    assert.equal(canReachArea(null, 'conversations'), true)
  })
})

describe('every surface reads that one set', () => {
  test('the tab bar filters from it and decides nothing itself', () => {
    const nav = read('components/spaces/SpaceNav.tsx')
    assert.match(nav, /reachableAreas/)
    assert.match(nav, /AREA_FOR_TAB/)
    // No second interpretation of who may see what.
    assert.ok(!nav.includes('active_access'), 'nav must not re-derive policy')
    assert.ok(!nav.includes('AccessPass'), 'nav must not consult entitlements')
  })

  test('the layout hands it the server’s answer', () => {
    assert.match(
      read('app/spaces/[slug]/layout.tsx'),
      /reachableAreas=\{space\.area_access\}/,
    )
  })

  test('the Home tiles are filtered server-side, not in the component', () => {
    // home_config.resolve takes the reachable set; the tile component
    // renders what it is given.
    const tiles = read('lib/collectiveHomeTiles.ts')
    assert.ok(!tiles.includes('area_access'), 'tiles must not re-filter')
  })

  test('each member-area page guards itself server-side', () => {
    const expected: Record<string, string> = {
      'events/page.tsx': 'gatherings',
      'pathways/page.tsx': 'pathways',
      'community/page.tsx': 'conversations',
      'members/page.tsx': 'members',
      'events/[eventId]/page.tsx': 'gatherings',
      'events/archive/page.tsx': 'gatherings',
      'gathering-series/[series-slug]/page.tsx': 'gatherings',
      'community/[postId]/page.tsx': 'conversations',
      'members/[memberId]/page.tsx': 'members',
    }
    for (const [file, area] of Object.entries(expected)) {
      const src = read(`app/spaces/[slug]/${file}`)
      assert.ok(
        src.includes(`requireArea(space, '${area}')`),
        `${file} does not guard ${area}`,
      )
    }
  })

  test('a refusal is a 404, not a login redirect', () => {
    // Matching the API, so a refusal never confirms an area exists —
    // and nothing paints before disappearing.
    const helper = read('lib/areaAccess.ts')
    assert.match(helper, /notFound\(\)/)
    assert.ok(!helper.includes('redirect('), 'no client-side bounce')
  })
})

describe('the proxy no longer competes', () => {
  const proxy = () => read('proxyRouting.ts')

  test('no CONFIGURABLE Collective area is decided from a URL shape', () => {
    // This used to pin ``isSpacesRouteProtected`` as literally
    // ``return false``. It no longer is: ``/spaces/x/messages`` is
    // gated there, because it is the one Collective area a creator
    // cannot open — the backend fixes it at members-only in a
    // single-element tuple (AREA_MESSAGES in area_policies.py).
    //
    // The invariant the old assertion was protecting is unchanged and
    // is now checked by behaviour rather than by source text: every
    // area whose access *does* depend on the Collective is still left
    // entirely to the server.
    for (const area of [
      'about', 'home', 'pathways', 'events',
      'members', 'offerings', 'gathering-series',
    ]) {
      const path = `/spaces/any-collective/${area}`
      assert.equal(isProtectedRoute(path), false, path)
    }
  })

  test('the proxy gates messages and conversations, and nothing else', () => {
    for (const path of [
      '/spaces/any-collective/messages',
      '/spaces/any-collective/messages/mt_1',
      '/spaces/any-collective/community',
      '/spaces/any-collective/community/cp_1',
    ]) {
      assert.equal(isProtectedRoute(path), true, path)
    }
  })

  test('both gated areas are closed to anonymous visitors by policy', () => {
    // The real criterion, and the reason `community` moved out of the
    // list above.
    //
    // It is not "fixed vs configurable" — conversations IS
    // configurable. It is whether a *signed-out* visitor could ever be
    // allowed in. ``AREA_ALLOWED`` offers conversations only
    // POLICY_MEMBERS and POLICY_ACTIVE_ACCESS, so no creator can open
    // it to anonymous visitors, and requiring a session decides
    // nothing that depends on the Collective. Authorisation is still
    // entirely the server's.
    //
    // Read from the backend so the justification is enforced: if
    // conversations ever becomes publicly configurable, this fails and
    // the proxy rule has to be revisited rather than quietly
    // outliving its reason.
    const policies = readFileSync(
      join(SRC, '..', '..', 'backend', 'app', 'spaces', 'area_policies.py'),
      'utf8',
    )
    const allowed = policies.slice(policies.indexOf('AREA_ALLOWED'))
    for (const area of ['AREA_MESSAGES', 'AREA_CONVERSATIONS']) {
      const line = allowed
        .split('\n')
        .find((l) => l.trimStart().startsWith(area + ':'))
      assert.ok(line, `${area} missing from AREA_ALLOWED`)
      assert.ok(
        !line!.includes('POLICY_PUBLIC'),
        `${area} can be made public — the proxy must not gate it on URL shape`,
      )
    }
  })

  test('but unconditionally private roots keep their guard', () => {
    const src = proxy()
    for (const root of ['/dashboard', '/admin', '/creator', '/settings']) {
      assert.ok(src.includes(`'${root}'`), `${root} lost its proxy guard`)
    }
  })

  test('the stale route comment is gone', () => {
    // It claimed /spaces/[slug] redirects to /pathways, which stopped
    // being true when the Collective Home shipped.
    assert.ok(!proxy().includes('redirects to /pathways'))
  })
})

describe('the Creator Studio control', () => {
  const form = () => read('app/creator-studio/settings/AreaPolicyForm.tsx')

  test('it offers only the areas the server says are configurable', () => {
    // The vocabulary lives in area_policies.py, not retyped in TSX.
    const src = form()
    assert.match(src, /area_policy_options/)
    assert.ok(!src.includes("'about'"), 'About is fixed')
    assert.ok(!src.includes("'home'"), 'Collective Home is fixed')
    assert.ok(!src.includes("'messages'"), 'Messages is fixed')
  })

  test('it explains doorway versus lock', () => {
    const src = form()
    assert.match(src, /booking a paid session still depends/i)
    assert.match(src, /purchase pages stay publicly reachable/i)
  })

  test('it names the Member directory dependency', () => {
    assert.match(form(), /Member directory switched on/i)
  })

  test('it shows the defaults in force, not a blank', () => {
    assert.match(form(), /area_policies \?\? \{\}/)
  })

  test('it saves the whole map in one request', () => {
    // A half-applied set of doorways is not a state to leave a
    // Collective in.
    assert.match(form(), /area_policies: \{ areas: \{ \.\.\.policies, \[area\]: next \} \}/)
  })

  test('it sits on Access & Visibility beside the joining policy', () => {
    const shell = read('app/creator-studio/settings/SettingsTabbedShell.tsx')
    assert.match(shell, /<AreaPolicyForm/)
    assert.match(shell, /<JoinPolicyForm/)
  })
})
