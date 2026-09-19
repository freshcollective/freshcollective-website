import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  acceptAttribute,
  attributionLine,
  missingCount,
  previewAspect,
  previewSurface,
  sourceLabel,
  sourceTone,
  type BrandAsset,
  type BrandAssetGroup,
} from './brandAssets.ts'

function asset(over: Partial<BrandAsset> = {}): BrandAsset {
  return {
    role: 'primary_light_logo',
    title: 'Primary — light background',
    group: 'full_logos',
    intended_use: 'x',
    recommended: 'y',
    accepted_formats: ['PNG', 'WebP'],
    source: 'default',
    image_url: '/brand/a.png',
    public_url: 'https://fc.test/brand/a.png',
    missing_note: null,
    updated_at: null,
    updated_by: null,
    can_reset: true,
    ...over,
  }
}

describe('source badges', () => {
  test('each source has its own label and tone', () => {
    assert.equal(sourceLabel('custom'), 'Custom upload')
    assert.equal(sourceLabel('default'), 'Approved default')
    assert.equal(sourceLabel('missing'), 'Missing')
    assert.notEqual(sourceTone('missing'), sourceTone('default'))
    assert.notEqual(sourceTone('custom'), sourceTone('default'))
  })
})

describe('preview surface', () => {
  test('white-on-transparent artwork previews on a dark surface', () => {
    // The defect this prevents: previewing a white dragonfly on a white
    // card, which shows an empty box and looks like a broken upload.
    assert.equal(previewSurface('logo_on_navy'), 'dark')
    assert.equal(previewSurface('compact_dark_mark'), 'dark')
  })

  test('artwork carrying its own background gets neither card colour', () => {
    // Both teal treatments bake their background in — the marketing
    // lockup sits on a deep teal gradient, so a navy card behind it
    // would misrepresent it.
    assert.equal(previewSurface('logo_on_teal'), 'own')
    assert.equal(previewSurface('marketing_hero_logo'), 'own')
    assert.equal(previewSurface('favicon_app_icon'), 'own')
  })

  test('an unrecognised role falls back to light rather than throwing', () => {
    assert.equal(previewSurface('something_new'), 'light')
  })

  test('only the social card is previewed landscape', () => {
    assert.equal(previewAspect('social_share_image'), '1200 / 630')
    assert.equal(previewAspect('primary_light_logo'), '1 / 1')
  })
})

describe('accept attribute', () => {
  test('is derived from what the role accepts', () => {
    assert.equal(acceptAttribute(['PNG', 'WebP']), 'image/png,image/webp')
    assert.equal(
      acceptAttribute(['PNG', 'WebP', 'JPG']),
      'image/png,image/webp,image/jpeg',
    )
  })

  test('never offers SVG', () => {
    assert.ok(!acceptAttribute(['PNG', 'WebP', 'JPG']).includes('svg'))
  })

  test('ignores a format it does not know', () => {
    assert.equal(acceptAttribute(['PNG', 'TIFF']), 'image/png')
  })
})

describe('attribution', () => {
  test('a custom upload names who replaced it and when', () => {
    const line = attributionLine(asset({
      source: 'custom', updated_at: '2026-09-20T04:30:00', updated_by: 'Lindsey',
    }))
    assert.ok(line?.startsWith('Replaced by Lindsey · '))
    assert.ok(line?.includes('2026'))
  })

  test('falls back gracefully when the uploader is unknown', () => {
    const line = attributionLine(asset({
      source: 'custom', updated_at: '2026-09-20T04:30:00', updated_by: null,
    }))
    assert.ok(line?.startsWith('Replaced '))
    assert.ok(!line?.includes('undefined'))
  })

  test('an approved default claims no edit history', () => {
    assert.equal(attributionLine(asset({ source: 'default' })), null)
    assert.equal(attributionLine(asset({ source: 'missing' })), null)
  })
})

describe('missing count', () => {
  test('counts roles awaiting approved artwork across groups', () => {
    const groups: BrandAssetGroup[] = [
      {
        group: 'full_logos', label: 'Full logos', description: '',
        assets: [asset(), asset({ role: 'b', source: 'custom' })],
      },
      {
        group: 'compact_system', label: 'Compact', description: '',
        assets: [
          asset({ role: 'c', source: 'missing' }),
          asset({ role: 'd', source: 'missing' }),
        ],
      },
    ]
    assert.equal(missingCount(groups), 2)
  })

  test('is zero when everything is filled', () => {
    assert.equal(missingCount([]), 0)
  })
})
