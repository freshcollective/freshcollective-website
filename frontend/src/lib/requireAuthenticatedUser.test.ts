/**
 * Unit tests for the pure auth-decision function.
 *
 * The runtime wrapper `requireAuthenticatedUser` collects three inputs
 * (cookie present, JWT signature valid, live user profile) and passes
 * them to `resolveAuthAction`. All the branching lives in the pure
 * function so this test file can exercise every path without mocking
 * `next/headers` or `next/navigation`.
 *
 * Run with the built-in Node test runner:
 *
 *     node --experimental-strip-types --test src/lib/requireAuthenticatedUser.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import { resolveAuthAction } from './resolveAuthAction.ts'
// @ts-expect-error - Node-native import path
import type { UserProfile } from '../types/platform.ts'

const FAKE_USER: UserProfile = {
  id: 'user_abc123',
  email: 'test@example.com',
  name: 'Test Name',
  role: 'user',
  bio: null,
  display_name: null,
  profile_tagline: null,
  avatar_url: null,
  is_public: true,
  has_completed_onboarding: false,
  has_completed_creator_onboarding: false,
  interests: [],
}


describe('resolveAuthAction — the four failure modes all redirect', () => {
  test('no cookie → redirect with next preserved', () => {
    const out = resolveAuthAction({
      hasToken: false, signatureValid: false, user: null,
      pathname: '/dashboard', loginPath: '/login',
    })
    assert.deepEqual(out, {
      action: 'redirect',
      to: '/login?next=%2Fdashboard',
    })
  })

  test('cookie present but JWT signature invalid → redirect with next preserved', () => {
    const out = resolveAuthAction({
      hasToken: true, signatureValid: false, user: null,
      pathname: '/dashboard', loginPath: '/login',
    })
    assert.deepEqual(out, {
      action: 'redirect',
      to: '/login?next=%2Fdashboard',
    })
  })

  test('valid JWT signature but backend returned no user (the R2B bug) → redirect', () => {
    // This is the exact case that produced "Welcome back, friend." —
    // signature was signed with AUTH_SECRET and unexpired, but the
    // user row it points to no longer exists (deleted / test rollback).
    // The middleware alone cannot catch this; the guard must.
    const out = resolveAuthAction({
      hasToken: true, signatureValid: true, user: null,
      pathname: '/dashboard', loginPath: '/login',
    })
    assert.deepEqual(out, {
      action: 'redirect',
      to: '/login?next=%2Fdashboard',
    })
  })

  test('valid session + live user → render (never redirect)', () => {
    const out = resolveAuthAction({
      hasToken: true, signatureValid: true, user: FAKE_USER,
      pathname: '/dashboard', loginPath: '/login',
    })
    assert.deepEqual(out, { action: 'render', user: FAKE_USER })
  })
})


describe('resolveAuthAction — next parameter is preserved across every protected pathname', () => {
  for (const pathname of [
    '/dashboard',
    '/profile',
    '/settings/notifications',
    '/creator-studio',
    '/creator-studio/collective',
    '/creator-studio/pathways',
    '/onboarding',
    '/creator-onboarding',
    '/notifications',
    '/world',
    '/build-your-collective',
  ]) {
    test(`redirects preserve next=${pathname}`, () => {
      const out = resolveAuthAction({
        hasToken: false, signatureValid: false, user: null,
        pathname, loginPath: '/login',
      })
      assert.equal(out.action, 'redirect')
      if (out.action !== 'redirect') return
      assert.equal(
        out.to,
        `/login?next=${encodeURIComponent(pathname)}`,
      )
    })
  }

  test('pathnames with query-shaped characters are encoded', () => {
    const out = resolveAuthAction({
      hasToken: false, signatureValid: false, user: null,
      pathname: '/spaces/foo/pathways/bar/steps/1',
      loginPath: '/login',
    })
    assert.deepEqual(out, {
      action: 'redirect',
      to: '/login?next=%2Fspaces%2Ffoo%2Fpathways%2Fbar%2Fsteps%2F1',
    })
  })
})


describe('resolveAuthAction — admin login door is honoured for /admin/* paths', () => {
  test('admin path with no cookie → /admin/login?next=/admin/…', () => {
    const out = resolveAuthAction({
      hasToken: false, signatureValid: false, user: null,
      pathname: '/admin/users/abc',
      loginPath: '/admin/login',
    })
    assert.deepEqual(out, {
      action: 'redirect',
      to: '/admin/login?next=%2Fadmin%2Fusers%2Fabc',
    })
  })

  test('admin path with stale-user-JWT → /admin/login?next=/admin/…', () => {
    // The R2B bug repeated on /admin — a stale valid JWT for a deleted
    // admin cannot be allowed to render admin chrome. Layout must
    // bounce through /admin/login, not through /login.
    const out = resolveAuthAction({
      hasToken: true, signatureValid: true, user: null,
      pathname: '/admin/dashboard',
      loginPath: '/admin/login',
    })
    assert.deepEqual(out, {
      action: 'redirect',
      to: '/admin/login?next=%2Fadmin%2Fdashboard',
    })
  })
})


describe('resolveAuthAction — happy path returns the user for every role', () => {
  for (const role of ['user', 'creator', 'admin']) {
    test(`role=${role} is returned unchanged (role-based gating is a layer above)`, () => {
      const user = { ...FAKE_USER, role }
      const out = resolveAuthAction({
        hasToken: true, signatureValid: true, user,
        pathname: '/dashboard', loginPath: '/login',
      })
      assert.deepEqual(out, { action: 'render', user })
    })
  }
})
