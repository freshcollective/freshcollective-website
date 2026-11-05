import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  DEFAULT_PREFERENCE,
  bannerIsActive,
  bannerSelectionUnavailable,
  headerImageFor,
  normalisePreference,
  selectCollectiveHeaderImage,
} from './collectiveHeaderImage.ts'

const SRC = join(process.cwd(), 'src')
const BANNER = '/api/uploads/covers/x/banner.png'
const HERO = '/atlas/moon-lagoon-hero.png'
const THUMB = '/atlas/moon-lagoon-thumb.png'

describe('the rule', () => {
  it('shows the banner when the creator chose it', () => {
    assert.equal(
      selectCollectiveHeaderImage({
        preference: 'banner', bannerUrl: BANNER,
        locationHeroUrl: HERO, locationThumbnailUrl: THUMB,
      }),
      BANNER,
    )
  })

  it('shows Location artwork when the creator chose that', () => {
    assert.equal(
      selectCollectiveHeaderImage({
        preference: 'location', bannerUrl: BANNER,
        locationHeroUrl: HERO, locationThumbnailUrl: THUMB,
      }),
      HERO,
    )
  })

  it('defaults to Location artwork', () => {
    // Every existing Collective reads as this, so deploying the
    // feature changes nothing about how they look.
    assert.equal(DEFAULT_PREFERENCE, 'location')
    for (const preference of [null, undefined, '', 'nonsense']) {
      assert.equal(
        selectCollectiveHeaderImage({
          preference, bannerUrl: BANNER, locationHeroUrl: HERO,
        }),
        HERO,
        String(preference),
      )
    }
  })

  it('falls back from hero to thumbnail', () => {
    assert.equal(
      selectCollectiveHeaderImage({
        preference: 'location', locationThumbnailUrl: THUMB,
      }),
      THUMB,
    )
  })

  it('keeps the pre-existing legacy fallback to the banner', () => {
    // A Collective with no Location showed its banner before this
    // rule existed, and still does.
    assert.equal(
      selectCollectiveHeaderImage({ preference: 'location', bannerUrl: BANNER }),
      BANNER,
    )
  })

  it('shows nothing when there is nothing', () => {
    assert.equal(selectCollectiveHeaderImage({ preference: 'banner' }), null)
    assert.equal(selectCollectiveHeaderImage({}), null)
  })
})

describe('the safe fallback', () => {
  it('a chosen banner that has gone shows Location artwork', () => {
    // Not a broken image. A storage failure, or a file deleted out
    // from under the row.
    assert.equal(
      selectCollectiveHeaderImage({
        preference: 'banner', bannerUrl: null, locationHeroUrl: HERO,
      }),
      HERO,
    )
  })

  it('whitespace is not an image', () => {
    assert.equal(
      selectCollectiveHeaderImage({
        preference: 'banner', bannerUrl: '   ', locationHeroUrl: HERO,
      }),
      HERO,
    )
  })

  it('the fallback does not change the stored choice', () => {
    // The display falls back; the preference does not. This is the
    // property that stops a temporary image failure silently
    // rewriting what the creator asked for — so `normalisePreference`
    // still reports 'banner' even when nothing can be shown for it.
    assert.equal(normalisePreference('banner'), 'banner')
    assert.equal(
      bannerSelectionUnavailable({ preference: 'banner', bannerUrl: null }),
      true,
    )
    assert.equal(
      bannerSelectionUnavailable({ preference: 'banner', bannerUrl: BANNER }),
      false,
    )
    assert.equal(
      bannerSelectionUnavailable({ preference: 'location', bannerUrl: null }),
      false,
    )
  })

  it('reports whether the banner is the image actually in use', () => {
    assert.equal(bannerIsActive({ preference: 'banner', bannerUrl: BANNER }), true)
    assert.equal(bannerIsActive({ preference: 'banner', bannerUrl: null }), false)
    assert.equal(bannerIsActive({ preference: 'location', bannerUrl: BANNER }), false)
  })
})

describe('headerImageFor prefers the server answer', () => {
  it('uses header_image_url when present', () => {
    assert.equal(
      headerImageFor({
        header_image_url: BANNER,
        header_image_preference: 'location',
        location_hero_artwork_url: HERO,
      }),
      BANNER,
      'the server answer was recomputed instead of used',
    )
  })

  it('computes from the parts for an older payload', () => {
    // An endpoint not yet carrying the field, or a response fetched
    // before this shipped, must still render as it always did.
    assert.equal(
      headerImageFor({
        header_image_preference: 'banner',
        cover_image_url: BANNER,
        location_hero_artwork_url: HERO,
      }),
      BANNER,
    )
    assert.equal(
      headerImageFor({
        cover_image_url: BANNER, location_hero_artwork_url: HERO,
      }),
      HERO,
    )
  })

  it('an empty payload is null, not undefined', () => {
    assert.equal(headerImageFor({}), null)
  })
})

describe('the Python side agrees', () => {
  it('both have the same rule, written once each', () => {
    // Two implementations of one small rule, deliberately — the
    // server resolves it for its payloads and the client needs it for
    // components holding the parts. If one is changed the shape of
    // the other should look wrong here.
    const py = readFileSync(
      join(process.cwd(), '..', 'backend', 'app', 'services',
        'collective_header_image.py'),
      'utf8',
    )
    assert.ok(/PREFER_LOCATION = "location"/.test(py))
    assert.ok(/PREFER_BANNER = "banner"/.test(py))
    assert.ok(/DEFAULT_PREFERENCE = PREFER_LOCATION/.test(py))
    assert.ok(
      /return hero or thumbnail or banner/.test(py),
      'the Python fallback chain changed',
    )
  })
})

describe('location surfaces keep Location artwork', () => {
  it('the About page island card still reads the Location', () => {
    // The deliberate distinction: the big header follows the creator's
    // choice, the small card stays the Collective's home in the world.
    // Phase 2 turns it into a gateway; Phase 1 must not move it.
    const about = readFileSync(
      join(SRC, 'app', 'spaces', '[slug]', 'about', 'page.tsx'), 'utf8',
    )
    assert.ok(
      /sidebarArtworkUrl = resolveMediaUrl\(\s*\n?\s*space\.location\?\.thumbnail_artwork_url/
        .test(about),
      'the island card no longer reads Location artwork first',
    )
    assert.ok(
      !/headerImageFor|selectCollectiveHeaderImage/.test(about),
      'the About page island card now follows the header choice',
    )
  })

  it('Discover Places is untouched', () => {
    for (const path of [
      join(SRC, 'app', 'discover-places', 'DiscoverPlacesLive.tsx'),
      join(SRC, 'app', 'discover-places', '[slug]', 'PlaceDetailView.tsx'),
    ]) {
      const source = readFileSync(path, 'utf8')
      assert.ok(
        !/collectiveHeaderImage/.test(source),
        `${path} was rewired — Places are about the Location`,
      )
    }
  })

  it('the Atlas admin is untouched', () => {
    // World Artwork: its editing, upload and selection must not change.
    for (const path of [
      join(SRC, 'app', 'admin', 'atlas', 'page.tsx'),
      join(SRC, 'app', 'admin', 'atlas', '[key]', 'LocationDetailClient.tsx'),
    ]) {
      const source = readFileSync(path, 'utf8')
      assert.ok(
        !/collectiveHeaderImage/.test(source),
        `${path} was rewired — this is World Artwork`,
      )
    }
  })
})

describe('Explore keeps the location identity', () => {
  const card = () => readFileSync(
    join(SRC, 'components', 'explore', 'CollectiveCard.tsx'), 'utf8',
  )

  it('the image follows the creator choice', () => {
    const source = card()
    assert.ok(/headerImageFor\(space\)/.test(source))
    assert.ok(
      !/space\.location_thumbnail_artwork_url\s*\n?\s*\?\? space\.location_hero_artwork_url/
        .test(source),
      'the unconditional Location-first chain is back',
    )
  })

  it('the Location is still named on the card', () => {
    const source = card()
    assert.ok(/space\.location_name && \(/.test(source))
    // The name carries its own icon — Atlas Locations store it inside
    // ``name`` ("🌿 Sanctuary Springs"). Phase 1 put a hardcoded 🌙
    // in front of it, which printed two emoji on every card and the
    // wrong one on every island that is not a lagoon.
    assert.ok(/\{' · '\}\{space\.location_name\}/.test(source))
    assert.ok(
      !/🌙/.test(source.replace(/\{\/\*[\s\S]*?\*\/\}/g, '')),
      'the hardcoded moon is back',
    )
  })

  it('it sits in the metadata line rather than becoming a badge', () => {
    const source = card()
    const label = source.indexOf('{space.location_name && (')
    const metaStart = source.indexOf('{space.pathway_count > 0 && (')
    const pricing = source.indexOf('!space.creator_only && (')
    assert.ok(metaStart > -1 && label > metaStart, 'the label left the metadata line')
    assert.ok(label < pricing, 'the label became a badge below the metadata')
  })

  it('membership and pricing information is retained', () => {
    const source = card()
    assert.ok(/member_count/.test(source))
    assert.ok(/pathway_count/.test(source))
    assert.ok(/formatCollectivePricingSummary/.test(source))
  })
})
