/**
 * Which pages may be reported to Cloudflare Web Analytics.
 *
 * This is the privacy boundary of the whole feature, so it is tested
 * for what it lets through as well as what it stops — a file that
 * only proved "nothing is tracked" would pass against a predicate
 * that always returned false, and that failure mode is invisible
 * (missing numbers, never an error).
 *
 * The cases that matter most are the URLs carrying a bearer
 * credential. ``/invites/{token}``, ``/reset-password?token=`` and
 * ``/verify-email?token=`` would each put a live secret into an
 * analytics dashboard, and Cloudflare reports Path as a dimension.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import { isTrackablePath, __lists } from './analytics.ts'

// ---------------------------------------------------------------------------
// 1 · What is tracked — the control for everything below
// ---------------------------------------------------------------------------

describe('public pages are tracked', () => {
  for (const path of [
    '/',
    '/about',
    '/for-creators',
    '/real-journey',
    '/membership',
    '/build-your-collective',
    '/ecosystem-interest',
    '/tnlbook',
    '/spaces',
    '/discover-places',
    '/world-guide',
  ]) {
    test(`${path} is tracked`, () => {
      assert.equal(isTrackablePath(path), true)
    })
  }

  test('a Location page is tracked', () => {
    assert.equal(isTrackablePath('/discover-places/misty-harbour'), true)
  })

  test('a World Guide document is tracked', () => {
    assert.equal(isTrackablePath('/world-guide/finding-your-collective'), true)
  })

  test("a Collective's public About page is tracked", () => {
    assert.equal(isTrackablePath('/spaces/moonlit-circle/about'), true)
  })

  test("a Pathway's public About page is tracked", () => {
    assert.equal(
      isTrackablePath('/spaces/moonlit-circle/pathways/slowing-down/about'),
      true,
    )
  })
})

// ---------------------------------------------------------------------------
// 2 · Bearer credentials in URLs — the cases with no recovery
// ---------------------------------------------------------------------------

describe('URLs carrying a secret are never tracked', () => {
  test('an invitation token in the path', () => {
    assert.equal(isTrackablePath('/invites/8f3c1d9e4b7a2056'), false)
    assert.equal(isTrackablePath('/invites'), false)
  })

  test('a password reset token in the query', () => {
    assert.equal(
      isTrackablePath('/reset-password?token=' + 'a'.repeat(64)),
      false,
    )
  })

  test('an email verification token in the query', () => {
    assert.equal(
      isTrackablePath('/verify-email?token=' + 'b'.repeat(64)),
      false,
    )
  })

  test('the auth pages are left out, ?next= and all', () => {
    assert.equal(isTrackablePath('/login?next=%2Fdashboard'), false)
    assert.equal(isTrackablePath('/signup'), false)
    assert.equal(isTrackablePath('/forgot-password'), false)
  })
})

// ---------------------------------------------------------------------------
// 3 · Authenticated and internal surfaces
// ---------------------------------------------------------------------------

describe('member and internal areas are never tracked', () => {
  for (const path of [
    '/dashboard',
    '/profile/usr_123',
    '/settings',
    '/onboarding',
    '/messages/thr_456',
    '/notifications',
    '/checkout',
    '/admin',
    '/admin/collectives/moonlit-circle',
    '/creator-studio',
    '/creator-studio/pathways/slowing-down',
    '/creator/spaces/moonlit-circle',
    '/creator-onboarding',
    '/dev/onboarding-preview',
  ]) {
    test(`${path} is not tracked`, () => {
      assert.equal(isTrackablePath(path), false)
    })
  }

  test('a private conversation is not tracked', () => {
    assert.equal(isTrackablePath('/spaces/moonlit-circle/community'), false)
    assert.equal(
      isTrackablePath('/spaces/moonlit-circle/community/cp_789'),
      false,
    )
  })

  test('a member profile inside a Collective is not tracked', () => {
    assert.equal(
      isTrackablePath('/spaces/moonlit-circle/members/mem_1'),
      false,
    )
  })
})

// ---------------------------------------------------------------------------
// 4 · Area-gated Collective pages stay out
// ---------------------------------------------------------------------------

describe('pages whose audience depends on the Collective stay out', () => {
  // ``/spaces/x/events`` is public in a Collective that publishes its
  // Gatherings and members-only in the next one. Tracking it would
  // mean tracking a members-only page whenever a member opened it, so
  // only the public-by-design About surfaces are allowed.
  for (const path of [
    '/spaces/moonlit-circle',
    '/spaces/moonlit-circle/events',
    '/spaces/moonlit-circle/events/evt_1',
    '/spaces/moonlit-circle/pathways',
    '/spaces/moonlit-circle/pathways/slowing-down',
    '/spaces/moonlit-circle/offers/term-pass',
    '/spaces/moonlit-circle/gathering-series/term-4',
    '/spaces/moonlit-circle/messages',
  ]) {
    test(`${path} is not tracked`, () => {
      assert.equal(isTrackablePath(path), false)
    })
  }
})

// ---------------------------------------------------------------------------
// 5 · The matching itself cannot be widened by accident
// ---------------------------------------------------------------------------

describe('path matching', () => {
  test('a pattern cannot be widened by a deeper path', () => {
    assert.equal(isTrackablePath('/spaces/x/about'), true)
    assert.equal(isTrackablePath('/spaces/x/about/secret'), false)
    assert.equal(isTrackablePath('/world-guide/a/b'), false)
  })

  test('query strings and fragments are stripped before matching', () => {
    assert.equal(isTrackablePath('/about?utm_source=news'), true)
    assert.equal(isTrackablePath('/about#team'), true)
    // ...but stripping must not rescue a refused path.
    assert.equal(isTrackablePath('/invites/abc?x=1'), false)
  })

  test('a trailing slash is the same page', () => {
    assert.equal(isTrackablePath('/about/'), true)
    assert.equal(isTrackablePath('/'), true)
  })

  test('refusal is matched on segment boundaries, not substrings', () => {
    // ``/creator-onboarding`` is not a child of ``/creator`` — both are
    // refused, but for their own reasons, and a substring check here
    // would have hidden a bug in the prefix logic.
    assert.equal(isTrackablePath('/creator-onboarding'), false)
    assert.equal(isTrackablePath('/creator'), false)
  })

  test('an unknown page is not tracked', () => {
    // Fails closed: the next route someone adds is invisible to
    // analytics until it is named, which is a missing number rather
    // than a leaked secret.
    assert.equal(isTrackablePath('/some-new-page'), false)
    assert.equal(isTrackablePath('/aboutus'), false)
  })

  test('a non-path input is refused rather than guessed at', () => {
    assert.equal(isTrackablePath(''), false)
    assert.equal(isTrackablePath('https://evil.test/about'), false)
  })
})

// ---------------------------------------------------------------------------
// 6 · The two lists cannot contradict each other
// ---------------------------------------------------------------------------

describe('the allow-list and the refusal list are disjoint', () => {
  test('no exact entry sits under a refused root', () => {
    for (const path of __lists.TRACKED_EXACT) {
      for (const prefix of __lists.NEVER_TRACKED) {
        assert.ok(
          !(path === prefix || path.startsWith(prefix + '/')),
          `${path} is allowed and refused at once`,
        )
      }
    }
  })

  test('no pattern can match a refused root', () => {
    // Sampled against a realistic path under each refused root, so a
    // future pattern written with ``.*`` would be caught here rather
    // than in production.
    for (const prefix of __lists.NEVER_TRACKED) {
      for (const candidate of [prefix, `${prefix}/abc`, `${prefix}/abc/def`]) {
        for (const re of __lists.TRACKED_PATTERNS) {
          assert.ok(
            !re.test(candidate),
            `${re} matches the refused path ${candidate}`,
          )
        }
      }
    }
  })
})
