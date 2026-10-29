/**
 * Unit tests for the proxy (middleware) routing decision.
 *
 * These tests cover the invariants that keep the login experience
 * reachable: /admin/login must NOT be swallowed by the /admin protected
 * prefix, the admin door must only redirect back to admin URLs, and the
 * standard auth pages must be reachable while signed out.
 *
 * Run with the built-in Node test runner:
 *
 *     node --experimental-strip-types --test src/proxyRouting.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import { decide, extractCreatorSpaceSlug, isAuthRoute, isProtectedRoute, loginPathFor, safeNextFor } from './proxyRouting.ts'


describe('isAuthRoute', () => {
  test('exact matches for every real auth page', () => {
    for (const p of ['/login', '/signup', '/forgot-password', '/reset-password', '/admin/login']) {
      assert.equal(isAuthRoute(p), true, `${p} must be an auth route`)
    }
  })

  test('trailing slash is normalised', () => {
    assert.equal(isAuthRoute('/login/'), true)
    assert.equal(isAuthRoute('/admin/login/'), true)
  })

  test('descendants of an auth route are NOT auth routes', () => {
    // If someone accidentally creates /login/foo it must not inherit the
    // public-access grant — that would leak past the guard.
    assert.equal(isAuthRoute('/login/foo'), false)
    assert.equal(isAuthRoute('/admin/login/extra'), false)
  })

  test('unknown paths are not auth routes', () => {
    assert.equal(isAuthRoute('/'), false)
    assert.equal(isAuthRoute('/admin'), false)
    assert.equal(isAuthRoute('/dashboard'), false)
  })
})


describe('isProtectedRoute', () => {
  test('every real protected top-level root is protected', () => {
    for (const p of [
      '/dashboard', '/admin', '/creator', '/creator-studio',
      '/profile', '/settings', '/onboarding',
    ]) {
      assert.equal(isProtectedRoute(p), true, `${p} must be protected`)
      assert.equal(isProtectedRoute(p + '/anything'), true, `${p}/anything must be protected`)
    }
  })

  test('/admin/login is NOT protected — the door must be reachable', () => {
    assert.equal(isProtectedRoute('/admin/login'), false)
    assert.equal(isProtectedRoute('/admin/login/'), false)
  })

  test('public marketing routes are not protected', () => {
    for (const p of ['/', '/login', '/signup', '/forgot-password', '/reset-password', '/spaces', '/about']) {
      assert.equal(isProtectedRoute(p), false, `${p} must not be protected`)
    }
  })

  test('segment-boundary protection — /creatorstudio is NOT under /creator', () => {
    // Old loose startsWith('/creator') would have false-matched.
    assert.equal(isProtectedRoute('/creatorstudio'), false)
    assert.equal(isProtectedRoute('/administration'), false)
    assert.equal(isProtectedRoute('/dashboards'), false)
  })

  test('/spaces public sub-routes stay public', () => {
    assert.equal(isProtectedRoute('/spaces'), false)
    assert.equal(isProtectedRoute('/spaces/foo'), false)
    assert.equal(isProtectedRoute('/spaces/foo/about'), false)
    assert.equal(isProtectedRoute('/spaces/foo/pathways'), false)
    assert.equal(isProtectedRoute('/spaces/foo/pathways/bar/about'), false)
    assert.equal(isProtectedRoute('/spaces/foo/pathways/bar/checkout'), false)
  })

  test('Collective routes are not decided here any more', () => {
    // The proxy sees only a URL shape, and since area policies the
    // answer depends on the Collective — /spaces/x/events is public
    // for one and members-only for another. Each page resolves its
    // own access server-side and 404s; a second authority guessing
    // from the path is how the tab bar and the Home came to disagree.
    for (const path of [
      '/spaces/foo/pathways/bar',
      '/spaces/foo/pathways/bar/steps/1',
      '/spaces/foo/events',
      '/spaces/foo/community',
      '/spaces/foo/members',
      '/spaces/foo/offerings',
      '/spaces/foo/about',
    ]) {
      assert.equal(isProtectedRoute(path), false, path)
    }
  })

  test('…except messages, which no Collective can open', () => {
    // This list used to include '/spaces/foo/messages'. It is the one
    // Collective route whose answer does not depend on the Collective:
    // the backend fixes it at members-only in a single-element tuple
    // (AREA_MESSAGES: (POLICY_MEMBERS,) in app/spaces/area_policies.py),
    // which that file defines as "a creator cannot change it". So the
    // URL's shape really is the whole answer, and it belongs with
    // /dashboard rather than with /events.
    for (const path of [
      '/spaces/foo/messages',
      '/spaces/foo/messages/',
      '/spaces/foo/messages/mt_123',
    ]) {
      assert.equal(isProtectedRoute(path), true, path)
    }
  })

  test('the guard stops at the segment boundary', () => {
    // A route merely beginning with the same letters is not messages.
    for (const path of [
      '/spaces/foo/messagesfoo',
      '/spaces/foo/messaging',
      '/spaces/messages',
    ]) {
      assert.equal(isProtectedRoute(path), false, path)
    }
  })

  test('unconditionally private roots keep their proxy guard', () => {
    // Where a URL's shape really is the whole answer.
    for (const path of [
      '/dashboard', '/admin/users', '/creator-studio/settings',
      '/settings/stay-connected', '/profile', '/onboarding',
    ]) {
      assert.equal(isProtectedRoute(path), true, path)
    }
  })
})


describe('loginPathFor', () => {
  test('admin paths use the admin login door', () => {
    assert.equal(loginPathFor('/admin'), '/admin/login')
    assert.equal(loginPathFor('/admin/account'), '/admin/login')
    assert.equal(loginPathFor('/admin/users'), '/admin/login')
  })

  test('non-admin paths use the standard login page', () => {
    assert.equal(loginPathFor('/dashboard'), '/login')
    assert.equal(loginPathFor('/creator-studio'), '/login')
    assert.equal(loginPathFor('/settings/security'), '/login')
  })
})


describe('safeNextFor — admin door restricts next to /admin/*', () => {
  test('admin next values pass through unchanged', () => {
    assert.equal(safeNextFor('/admin/login', '/admin'), '/admin')
    assert.equal(safeNextFor('/admin/login', '/admin/account'), '/admin/account')
    assert.equal(safeNextFor('/admin/login', '/admin/users/123'), '/admin/users/123')
  })

  test('non-admin next values are clamped to /admin', () => {
    // Never let the admin door bounce a caller into a non-admin URL.
    assert.equal(safeNextFor('/admin/login', '/dashboard'), '/admin')
    assert.equal(safeNextFor('/admin/login', '/creator-studio'), '/admin')
    assert.equal(safeNextFor('/admin/login', '//evil.example/'), '/admin')
    assert.equal(safeNextFor('/admin/login', '/administration'), '/admin')  // not /admin proper
  })

  test('standard login passes next through unchanged (form validates it)', () => {
    assert.equal(safeNextFor('/login', '/dashboard'), '/dashboard')
    assert.equal(safeNextFor('/login', '/spaces/foo/pathways/bar/steps/1'), '/spaces/foo/pathways/bar/steps/1')
  })
})


describe('decide — signed-out user', () => {
  test('/login → allow', () => {
    assert.deepEqual(decide('/login', false), { action: 'next' })
  })

  test('/admin/login → allow (must not be swallowed by /admin protection)', () => {
    assert.deepEqual(decide('/admin/login', false), { action: 'next' })
  })

  test('/forgot-password and /reset-password → allow', () => {
    assert.deepEqual(decide('/forgot-password', false), { action: 'next' })
    assert.deepEqual(decide('/reset-password', false), { action: 'next' })
  })

  test('/admin → redirect to /admin/login?next=/admin', () => {
    assert.deepEqual(decide('/admin', false), {
      action: 'redirect', to: '/admin/login', next: '/admin',
    })
  })

  test('/admin/account → redirect to /admin/login?next=/admin/account', () => {
    assert.deepEqual(decide('/admin/account', false), {
      action: 'redirect', to: '/admin/login', next: '/admin/account',
    })
  })

  test('/dashboard → redirect to /login?next=/dashboard', () => {
    assert.deepEqual(decide('/dashboard', false), {
      action: 'redirect', to: '/login', next: '/dashboard',
    })
  })

  test('/creator-studio → redirect to /login?next=/creator-studio', () => {
    assert.deepEqual(decide('/creator-studio', false), {
      action: 'redirect', to: '/login', next: '/creator-studio',
    })
  })

  test('public marketing page → allow', () => {
    assert.deepEqual(decide('/', false), { action: 'next' })
    assert.deepEqual(decide('/spaces', false), { action: 'next' })
  })
})


describe('decide — signed-in user (JWT signature valid)', () => {
  // The middleware only ever knows "does this JWT have a valid signature."
  // It cannot verify the user still exists — that's an authoritative DB
  // check that lives in the auth pages (getMe()) and protected layouts
  // (requireAuthenticatedUser). So a signature-valid JWT is NEVER
  // sufficient to bounce a caller away from an auth route: the auth
  // pages do that themselves using authoritative state.

  test('/login → allow (page handles "already signed in → forward" via getMe)', () => {
    assert.deepEqual(decide('/login', true), { action: 'next' })
  })

  test('/signup → allow (page handles "already signed in → forward" via getMe)', () => {
    assert.deepEqual(decide('/signup', true), { action: 'next' })
  })

  test('/admin/login → allow (page handles admin vs non-admin routing)', () => {
    assert.deepEqual(decide('/admin/login', true), { action: 'next' })
  })

  test('/admin → allow (layout does the role check)', () => {
    assert.deepEqual(decide('/admin', true), { action: 'next' })
  })

  test('/dashboard → allow', () => {
    assert.deepEqual(decide('/dashboard', true), { action: 'next' })
  })
})


describe('no redirect loops', () => {
  test('signed-out /admin → /admin/login → allow (single redirect, no loop)', () => {
    const first = decide('/admin', false)
    assert.equal(first.action, 'redirect')
    if (first.action !== 'redirect') return
    assert.equal(first.to, '/admin/login')
    const second = decide(first.to, false)
    assert.deepEqual(second, { action: 'next' })
  })

  test('signed-in admin at /admin/login → allow (page redirects to /admin, no bounce back)', () => {
    // Page-side redirect: /admin/login → /admin
    // Middleware for /admin while signed-in → allow. Layout then verifies admin role.
    const atLogin = decide('/admin/login', true)
    assert.deepEqual(atLogin, { action: 'next' })
    const atAdmin = decide('/admin', true)
    assert.deepEqual(atAdmin, { action: 'next' })
  })

  test('signed-out /dashboard → /login → allow (single redirect, no loop)', () => {
    const first = decide('/dashboard', false)
    assert.equal(first.action, 'redirect')
    if (first.action !== 'redirect') return
    assert.equal(first.to, '/login')
    const second = decide(first.to, false)
    assert.deepEqual(second, { action: 'next' })
  })

  // The stale-but-signed-JWT loop that broke Firefox after a DB rollback.
  //
  // Before the fix, middleware treated JWT-signature-valid as
  // "authenticated" and bounced /login → /dashboard. But the dashboard
  // layout's authoritative getMe() check would then bounce back to
  // /login. Firefox stopped the ping-pong with "The page isn't
  // redirecting properly."
  //
  // The invariant these tests protect: with a valid-signature JWT for a
  // user that no longer exists, the middleware NEVER redirects an auth
  // route. The auth page itself calls getMe(), sees null, and renders.

  test('stale signed JWT: /dashboard is still redirected once to /login', () => {
    // Middleware happily believes the JWT (signature is real). The layout
    // guard is what catches the missing user; middleware's job here is
    // just not to interfere with an unauth'd protected route redirect.
    // Simulated with authenticated=true because the JWT signature IS
    // valid — the caller doesn't yet know the user was deleted.
    assert.deepEqual(decide('/dashboard', true), { action: 'next' })
    // The layout will then redirect to /login?next=/dashboard.
    // Feed that back through the middleware — it must not bounce back.
    assert.deepEqual(decide('/login', true), { action: 'next' })
    // And /signup must also remain reachable for the same session.
    assert.deepEqual(decide('/signup', true), { action: 'next' })
  })

  test('stale signed JWT: no auth route redirects to /dashboard under any circumstance', () => {
    // The exact branch that used to produce the loop. This regression
    // guard makes sure nobody re-adds a JWT-sig-only "authenticated →
    // /dashboard" shortcut to the middleware.
    for (const authRoute of ['/login', '/signup', '/forgot-password', '/reset-password', '/admin/login']) {
      const d = decide(authRoute, true)
      assert.equal(d.action, 'next', `${authRoute} must render, not redirect`)
    }
  })
})


describe('extractCreatorSpaceSlug — URL is authoritative under /creator/spaces/[slug]', () => {
  test('extracts the slug from every valid shape', () => {
    assert.equal(extractCreatorSpaceSlug('/creator/spaces/world-builders'), 'world-builders')
    assert.equal(extractCreatorSpaceSlug('/creator/spaces/world-builders/'), 'world-builders')
    assert.equal(extractCreatorSpaceSlug('/creator/spaces/world-builders/pathways'), 'world-builders')
    assert.equal(extractCreatorSpaceSlug('/creator/spaces/the-grove/pathways/some-pathway/steps/1'), 'the-grove')
    assert.equal(extractCreatorSpaceSlug('/creator/spaces/embody/events/abc-123'), 'embody')
  })

  test('does not match unrelated paths', () => {
    assert.equal(extractCreatorSpaceSlug('/'), null)
    assert.equal(extractCreatorSpaceSlug('/creator'), null)
    assert.equal(extractCreatorSpaceSlug('/creator/spaces'), null)
    assert.equal(extractCreatorSpaceSlug('/creator/support'), null)
    assert.equal(extractCreatorSpaceSlug('/creator-studio'), null)
    assert.equal(extractCreatorSpaceSlug('/creator-studio/pathways'), null)
    assert.equal(extractCreatorSpaceSlug('/spaces/foo'), null)
    assert.equal(extractCreatorSpaceSlug('/admin'), null)
  })

})


// ---------------------------------------------------------------------------
// Following a direct-message link from an email
// ---------------------------------------------------------------------------

describe('a message link reaches the conversation, signed in or not', () => {
  const PRIVATE = '/spaces/moonlit-circle/messages/mt_7f3a19c2'
  const PUBLIC  = '/spaces/embody/messages/mt_7f3a19c2'

  test('anonymous is sent to login, keeping the destination', () => {
    // The whole point: the member clicked a link to one conversation
    // and must land in that conversation, not on a dashboard.
    for (const path of [PRIVATE, PUBLIC]) {
      assert.deepEqual(decide(path, false), {
        action: 'redirect', to: '/login', next: path,
      })
    }
  })

  test('the login door is the member one, never the admin one', () => {
    assert.equal(decide(PRIVATE, false).to, '/login')
  })

  test('an authenticated visitor passes straight through', () => {
    // Whether they may read it is the page's and the API\'s business,
    // not the proxy\'s. A signed-in non-member still meets notFound().
    for (const path of [PRIVATE, PUBLIC]) {
      assert.deepEqual(decide(path, true), { action: 'next' })
    }
  })

  test('private and public Collectives now answer identically', () => {
    // Before this rule they did not: anonymous got a redirect on a
    // public Collective and a 404 on a private one, which told the
    // caller which was which. Nothing is learned before signing in.
    const priv = decide(PRIVATE, false)
    const pub  = decide(PUBLIC, false)
    // Same outcome and same door; only the destination differs, and
    // that is the caller's own URL coming back to them.
    assert.equal(priv.action, pub.action)
    assert.equal(priv.to, pub.to)
    assert.equal(priv.next, PRIVATE)
    assert.equal(pub.next, PUBLIC)
    assert.deepEqual(decide(PRIVATE, true), decide(PUBLIC, true))
  })

  test('no other Collective route changed behaviour', () => {
    // The regression this file exists to prevent: a redirect rule that
    // spreads beyond the one area it was written for.
    for (const path of [
      '/spaces/moonlit-circle',
      '/spaces/moonlit-circle/about',
      '/spaces/moonlit-circle/pathways',
      '/spaces/moonlit-circle/pathways/p/steps/1',
      '/spaces/moonlit-circle/events',
      '/spaces/moonlit-circle/events/e1',
      '/spaces/moonlit-circle/community',
      '/spaces/moonlit-circle/members',
      '/spaces/moonlit-circle/offerings',
      '/spaces/moonlit-circle/gathering-series/s1',
      '/spaces',
    ]) {
      assert.deepEqual(decide(path, false), { action: 'next' }, path)
      assert.deepEqual(decide(path, true), { action: 'next' }, path)
    }
  })
})
