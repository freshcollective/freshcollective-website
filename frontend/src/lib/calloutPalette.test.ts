import { describe, it } from 'node:test'
import assert from 'node:assert/strict'

import {
  resolveCalloutPalette,
  resolveContainerPalette,
} from './calloutPalette.ts'
import type { CollectivePaletteMeta } from './collectivePalette.ts'

// Small fixture — same shape ``CollectiveThemeProvider`` produces
// from the API response. Sunrise-ish; keeps the test independent of
// whatever palettes happen to be seeded in the DB.
const SUNRISE: CollectivePaletteMeta = {
  key: 'sunrise',
  name: 'Sunrise',
  palette: {
    primary:    '#D97A3F', // strong warm orange
    secondary:  '#F1B370', // soft warm gold
    accent:     '#C3557F', // magenta accent
    background: '#FFF5E6', // pale cream
  },
}


describe('resolveContainerPalette — accent hex', () => {
  it('returns the raw palette hex as the accent for palette:<role>', () => {
    // A container styled ``palette:primary`` gives the child blockquote
    // the full-strength palette primary — so a quote inside a soft
    // Sunrise container gets Sunrise's strong colour, not the platform
    // default teal.
    const r = resolveContainerPalette('palette:primary', SUNRISE)!
    assert.equal(r.accent, '#D97A3F')

    const r2 = resolveContainerPalette('palette:accent', SUNRISE)!
    assert.equal(r2.accent, '#C3557F')
  })

  it('returns the source hex as the accent for custom:#RRGGBB', () => {
    const r = resolveContainerPalette('custom:#3A6B7A', SUNRISE)!
    assert.equal(r.accent, '#3A6B7A')
  })

  it('derives a darker accent from the legacy chip border', () => {
    // Legacy chips ship a mid-strength border. Darkening it 35% keeps
    // the accent in the same colour family without introducing a
    // per-chip lookup table.
    const r = resolveContainerPalette('teal', SUNRISE)!
    // Chip teal has border '#B8E0DE' — darkened 35% is smaller channels.
    // We don't assert an exact hex (the derivation is a pure function
    // covered in collectivePalette tests) — just that the accent is
    // present and differs from the border.
    assert.ok(r.accent)
    assert.notEqual(r.accent, r.border)
  })

  it('returns null when no container style is set', () => {
    assert.equal(resolveContainerPalette(null, SUNRISE), null)
    assert.equal(resolveContainerPalette(undefined, SUNRISE), null)
    assert.equal(resolveContainerPalette('', SUNRISE), null)
  })

  it('returns null for palette:<role> with no active palette', () => {
    // No palette threaded through → nothing to resolve against.
    assert.equal(resolveContainerPalette('palette:primary', null), null)
  })

  it('returns null for unknown legacy keys', () => {
    assert.equal(resolveContainerPalette('made_up_key', SUNRISE), null)
  })

  it('bg + border remain the same soft tint they used to be', () => {
    // Guard against a regression that silently changes container
    // background/border while adding the accent field.
    const r = resolveContainerPalette('palette:primary', SUNRISE)!
    // 10% alpha bg, 32% alpha border — same as before.
    assert.match(r.bg, /rgba\(\d+,\d+,\d+,0\.1\)/)
    assert.match(r.border, /rgba\(\d+,\d+,\d+,0\.32\)/)
  })
})


describe('resolveCalloutPalette — untouched behaviour', () => {
  it('still returns a callout palette for legacy keys', () => {
    const r = resolveCalloutPalette('teal', null, undefined, SUNRISE)
    assert.equal(r.key, 'teal')
    assert.ok(r.bg)
    assert.ok(r.border)
  })
})
