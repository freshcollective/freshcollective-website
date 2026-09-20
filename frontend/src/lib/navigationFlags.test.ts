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

const NAV_SURFACES = [
  'components/layout/PublicHeader.tsx',
  'components/layout/WorldHeader.tsx',
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
    assert.ok(src.includes('if (!isWaysToConnectEnabled()) notFound()'))
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
