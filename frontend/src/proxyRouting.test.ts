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

  test('/spaces private sub-routes are protected', () => {
    assert.equal(isProtectedRoute('/spaces/foo/pathways/bar'), true)
    assert.equal(isProtectedRoute('/spaces/foo/pathways/bar/steps/1'), true)
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


describe('decide — signed-in user', () => {
  test('/login → redirect to /dashboard', () => {
    assert.deepEqual(decide('/login', true), { action: 'redirect', to: '/dashboard' })
  })

  test('/signup → redirect to /dashboard', () => {
    assert.deepEqual(decide('/signup', true), { action: 'redirect', to: '/dashboard' })
  })

  test('/admin/login → allow (page handles admin vs non-admin routing)', () => {
    // Middleware cannot tell admin from non-admin (DB role check lives
    // in the layout / API). Let the page's own guard route accordingly.
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
