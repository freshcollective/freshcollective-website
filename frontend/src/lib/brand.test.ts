import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  BRAND_ROLES,
  BUNDLED_DEFAULTS,
  CHROME_MARK_PX,
  FULL_LOGO_INTRINSIC,
  MIN_LEGIBLE_MARK_PX,
  MIN_LEGIBLE_FULL_LOGO_PX,
  compactRoleFor,
  resolveBrandUrl,
  wordmarkCapHeight,
} from './brand.ts'

describe('resolution order', () => {
  test('an admin override wins', () => {
    assert.equal(
      resolveBrandUrl('primary_light_logo', {
        primary_light_logo: '/api/uploads/platform-artwork/brand/x.png',
      }),
      '/api/uploads/platform-artwork/brand/x.png',
    )
  })

  test('the approved bundled default is used when there is no override', () => {
    assert.equal(
      resolveBrandUrl('primary_light_logo'),
      BUNDLED_DEFAULTS.primary_light_logo,
    )
    assert.equal(resolveBrandUrl('primary_light_logo', {}), BUNDLED_DEFAULTS.primary_light_logo)
  })

  test('a null override falls through rather than blanking the role', () => {
    assert.equal(
      resolveBrandUrl('primary_light_logo', { primary_light_logo: null }),
      BUNDLED_DEFAULTS.primary_light_logo,
    )
  })

  test('a role with no approved artwork resolves to null', () => {
    for (const role of ['social_share_image'] as const) {
      assert.equal(resolveBrandUrl(role), null, role)
    }
  })

  test('the compact marks now resolve to the derived artwork', () => {
    assert.match(resolveBrandUrl('compact_light_mark') ?? '', /-mark-navy-/)
    assert.match(resolveBrandUrl('compact_dark_mark') ?? '', /-mark-white-/)
  })

  test('an upload fills a missing role without any other change', () => {
    // The property that lets World Management switch every header from
    // text to mark at once, with no page-by-page rewrite.
    assert.equal(
      resolveBrandUrl('compact_light_mark', {
        compact_light_mark: '/api/uploads/platform-artwork/brand/mark.png',
      }),
      '/api/uploads/platform-artwork/brand/mark.png',
    )
  })
})

describe('the placeholder is unreachable', () => {
  test('no role resolves to anything but approved artwork or null', () => {
    for (const role of BRAND_ROLES) {
      const url = resolveBrandUrl(role)
      if (url === null) continue
      assert.ok(url.startsWith('/brand/'), role)
      assert.ok(!url.startsWith('data:'), role)
    }
  })

  test('only the share card is still unfilled', () => {
    const empty = BRAND_ROLES.filter((r) => BUNDLED_DEFAULTS[r] === null)
    assert.deepEqual(empty, ['social_share_image'])
  })

  test('no two roles share the same artwork', () => {
    const paths = BRAND_ROLES.map((r) => BUNDLED_DEFAULTS[r]).filter(Boolean)
    assert.equal(new Set(paths).size, paths.length)
  })
})

describe('compact marks by tone', () => {
  test('tone selects the role', () => {
    assert.equal(compactRoleFor('light'), 'compact_light_mark')
    assert.equal(compactRoleFor('dark'), 'compact_dark_mark')
  })

  test('each tone resolves to its own derived mark', () => {
    assert.notEqual(
      resolveBrandUrl(compactRoleFor('light')),
      resolveBrandUrl(compactRoleFor('dark')),
    )
  })
})

describe('artwork geometry', () => {
  test('the wordmark at the old 44px treatment was never readable', () => {
    // 1.3px of cap height. This is the number Phase B exists to fix.
    assert.ok(wordmarkCapHeight(44) < 2)
  })

  test('the sizes the product uses clear the legibility floor', () => {
    assert.ok(wordmarkCapHeight(MIN_LEGIBLE_FULL_LOGO_PX) >= 6.0)
    assert.ok(wordmarkCapHeight(256) >= 7.5)
  })

  test('intrinsic size matches the approved artwork', () => {
    assert.equal(FULL_LOGO_INTRINSIC, 500)
  })
})

describe('compact mark sizing', () => {
  test('chrome renders the mark above the measured legibility floor', () => {
    // At 24px the stroke lands at 0.32 CSS pixels and the dragonfly
    // becomes a grey smudge. 32px is the floor; 36px is where the wing
    // detail separates.
    assert.ok(CHROME_MARK_PX >= MIN_LEGIBLE_MARK_PX)
    assert.ok(MIN_LEGIBLE_MARK_PX >= 32)
  })
})
