import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  BRAND_ROLES,
  BUNDLED_DEFAULTS,
  FULL_LOGO_INTRINSIC,
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
    for (const role of ['compact_light_mark', 'compact_dark_mark',
      'favicon_app_icon', 'social_share_image'] as const) {
      assert.equal(resolveBrandUrl(role), null, role)
    }
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

  test('the five full-logo roles are filled and the four system roles are not', () => {
    const filled = BRAND_ROLES.filter((r) => BUNDLED_DEFAULTS[r] !== null)
    assert.deepEqual(filled, [
      'primary_light_logo',
      'alternate_light_logo',
      'logo_on_teal',
      'logo_on_navy',
      'marketing_hero_logo',
    ])
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

  test('both are unfilled today, so chrome must cope with null', () => {
    assert.equal(resolveBrandUrl(compactRoleFor('light')), null)
    assert.equal(resolveBrandUrl(compactRoleFor('dark')), null)
  })
})

describe('artwork geometry', () => {
  test('the wordmark at the old 44px treatment was never readable', () => {
    // 1.3px of cap height. This is the number Phase B exists to fix.
    assert.ok(wordmarkCapHeight(44) < 2)
  })

  test('the sizes the product uses clear the legibility floor', () => {
    assert.ok(wordmarkCapHeight(MIN_LEGIBLE_FULL_LOGO_PX) >= 6.9)
    assert.ok(wordmarkCapHeight(256) >= 7.5)
  })

  test('intrinsic size matches the approved artwork', () => {
    assert.equal(FULL_LOGO_INTRINSIC, 500)
  })
})
