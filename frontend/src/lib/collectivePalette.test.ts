/**
 * Unit tests for the collective palette storage / resolver.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping — no new dev dependency required:
 *
 *     node --experimental-strip-types --test src/lib/collectivePalette.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import {
  PALETTE_ROLES,
  contrastText,
  darkenHex,
  deriveSoftTint,
  encodeCustomHex,
  encodePaletteRole,
  isValidHex,
  parseStoredColour,
  paletteHex,
  resolveHex,
} from './collectivePalette.ts'

const OCEAN_SAND = {
  key: 'ocean_sand',
  name: 'Ocean & Sand',
  palette: { primary: '#3A6B7A', secondary: '#91B4B9', accent: '#D9BE95', background: '#EEF3F3' },
}

const SUNRISE = {
  key: 'sunrise',
  name: 'Sunrise',
  palette: { primary: '#D97A3F', secondary: '#F1B370', accent: '#C3557F', background: '#FFF5E6' },
}


describe('parseStoredColour', () => {
  test('empty / null / undefined → { kind: "none" }', () => {
    assert.deepEqual(parseStoredColour(null),      { kind: 'none' })
    assert.deepEqual(parseStoredColour(undefined), { kind: 'none' })
    assert.deepEqual(parseStoredColour(''),        { kind: 'none' })
  })

  test('palette:role decodes to palette role', () => {
    for (const role of PALETTE_ROLES) {
      assert.deepEqual(parseStoredColour(`palette:${role}`), { kind: 'palette', role })
    }
  })

  test('palette:<bad role> → { kind: "none" } (no crash)', () => {
    assert.deepEqual(parseStoredColour('palette:mystery'), { kind: 'none' })
  })

  test('custom:#RRGGBB decodes verbatim', () => {
    assert.deepEqual(parseStoredColour('custom:#3A6B7A'), { kind: 'custom', hex: '#3A6B7A' })
  })

  test('custom:<bad hex> → { kind: "none" }', () => {
    assert.deepEqual(parseStoredColour('custom:not-hex'), { kind: 'none' })
    assert.deepEqual(parseStoredColour('custom:'),        { kind: 'none' })
  })

  test('anything else is a legacy key (teal, gold, ...)', () => {
    for (const k of ['teal', 'gold', 'blue', 'rose', 'sage', 'grey', 'lilac', 'orange']) {
      assert.deepEqual(parseStoredColour(k), { kind: 'legacy', key: k })
    }
  })
})


describe('encoders', () => {
  test('encodePaletteRole', () => {
    assert.equal(encodePaletteRole('primary'), 'palette:primary')
    assert.equal(encodePaletteRole('background'), 'palette:background')
  })

  test('encodeCustomHex accepts valid hex only', () => {
    assert.equal(encodeCustomHex('#3A6B7A'), 'custom:#3A6B7A')
    assert.equal(encodeCustomHex('#abc'),    'custom:#abc')
    assert.throws(() => encodeCustomHex('not hex'))
    assert.throws(() => encodeCustomHex('rgb(1,2,3)'))
  })
})


describe('isValidHex', () => {
  test('accepts 3- and 6-digit hex', () => {
    assert.equal(isValidHex('#abc'),      true)
    assert.equal(isValidHex('#ABC'),      true)
    assert.equal(isValidHex('#3A6B7A'),   true)
    assert.equal(isValidHex(' #3A6B7A '), true) // trimmed
  })
  test('rejects everything else', () => {
    assert.equal(isValidHex('3A6B7A'),   false) // missing #
    assert.equal(isValidHex('#12345'),   false) // 5 digits
    assert.equal(isValidHex('rgb(1,2,3)'), false)
    assert.equal(isValidHex(''), false)
  })
})


describe('paletteHex', () => {
  test('looks up each role', () => {
    assert.equal(paletteHex('primary',    OCEAN_SAND), '#3A6B7A')
    assert.equal(paletteHex('secondary',  OCEAN_SAND), '#91B4B9')
    assert.equal(paletteHex('accent',     OCEAN_SAND), '#D9BE95')
    assert.equal(paletteHex('background', OCEAN_SAND), '#EEF3F3')
  })
  test('null palette → null', () => {
    assert.equal(paletteHex('primary', null),      null)
    assert.equal(paletteHex('primary', undefined), null)
  })
})


describe('resolveHex', () => {
  test('palette role resolves against the active palette', () => {
    assert.equal(resolveHex('palette:primary',  OCEAN_SAND), '#3A6B7A')
    assert.equal(resolveHex('palette:primary',  SUNRISE),    '#D97A3F') // flows through!
    assert.equal(resolveHex('palette:accent',   OCEAN_SAND), '#D9BE95')
    assert.equal(resolveHex('palette:accent',   SUNRISE),    '#C3557F')
  })

  test('custom hex is preserved regardless of palette', () => {
    assert.equal(resolveHex('custom:#3A6B7A', OCEAN_SAND), '#3A6B7A')
    assert.equal(resolveHex('custom:#3A6B7A', SUNRISE),    '#3A6B7A') // does NOT flow through
  })

  test('legacy key and empty → null (caller falls back)', () => {
    assert.equal(resolveHex('teal', OCEAN_SAND), null)
    assert.equal(resolveHex('',     OCEAN_SAND), null)
    assert.equal(resolveHex(null,   OCEAN_SAND), null)
  })

  test('palette role with no active palette → null', () => {
    assert.equal(resolveHex('palette:primary', null), null)
  })
})


describe('deriveSoftTint', () => {
  test('produces rgba() with alpha for bg + border', () => {
    const { bg, border } = deriveSoftTint('#3A6B7A')
    assert.equal(bg,     'rgba(58,107,122,0.1)')
    assert.equal(border, 'rgba(58,107,122,0.32)')
  })
  test('accepts #rgb shorthand', () => {
    const { bg } = deriveSoftTint('#abc')
    assert.equal(bg, 'rgba(170,187,204,0.1)')
  })
  test('leaves invalid input alone (safe fallback)', () => {
    const { bg } = deriveSoftTint('not-a-hex')
    assert.equal(bg, 'not-a-hex')
  })
})


describe('darkenHex', () => {
  test('multiplicatively shifts each channel and pads to 6 chars', () => {
    // 13% darker: 0x80 (128) * 0.87 = 111.36 → 111 → 0x6f.
    assert.equal(darkenHex('#808080', 0.13), '#6f6f6f')
    // A saturated warm hex — the classic Sunrise primary.
    assert.equal(darkenHex('#D97A3F', 0.13), '#bd6a37')
  })

  test('amount 0 returns the source unchanged (case-normalised)', () => {
    assert.equal(darkenHex('#3A6B7A', 0),   '#3a6b7a')
  })

  test('amount 1 collapses to black', () => {
    assert.equal(darkenHex('#D97A3F', 1),   '#000000')
  })

  test('clamps out-of-range amounts', () => {
    assert.equal(darkenHex('#D97A3F', -0.5), '#d97a3f')  // clamped to 0
    assert.equal(darkenHex('#D97A3F', 2),    '#000000')  // clamped to 1
  })

  test('accepts #rgb shorthand', () => {
    assert.equal(darkenHex('#f00', 0.5), '#800000')
  })

  test('leaves invalid input alone (safe fallback)', () => {
    assert.equal(darkenHex('not-a-hex', 0.13), 'not-a-hex')
  })
})


describe('contrastText', () => {
  test('picks white on every dark or medium seeded primary', () => {
    // Includes the warm-medium primaries (Sunrise, Terracotta, Honey &
    // Cream) that a pure-WCAG argmax picker would flip to charcoal.
    // The panel design treats these as "dark/medium" surfaces that
    // read best with white text — see the ``contrastText`` docstring
    // in ``collectivePalette.ts`` for the calibration rationale.
    for (const bg of [
      // Unambiguously dark primaries
      '#5C4A33',  // Earth & Moss
      '#3A6B7A',  // Ocean & Sand
      '#3F4A73',  // Midnight
      '#7A4C7C',  // Wildflowers
      '#2C5A3E',  // Forest
      '#6E2B3A',  // Berry & Bark
      '#6B5C8C',  // Lavender & Dusk
      '#2C556E',  // Deep Ocean
      // Warm-medium primaries — the class the M1 fix targets
      '#D97A3F',  // Sunrise — warm orange
      '#B85D3D',  // Terracotta & Fig — The Grove, motivating case
      '#944D32',  // Autumn — rust brown
      '#A64526',  // Ember & Clay — burnt orange
      '#C89B4A',  // Honey & Cream — gold
      '#B87A85',  // Rose & Sage — dusty rose
      '#C67E4E',  // Desert Bloom — tan
      '#DE6E5A',  // Coral & Reef — coral
    ]) {
      assert.equal(contrastText(bg), '#ffffff', `expected white on ${bg}`)
    }
  })

  test('picks dark charcoal on genuinely light backgrounds', () => {
    // Only palettes whose primary is a pale wash, plus obviously light
    // hexes like backgrounds and pure white. Threshold L > 0.42.
    for (const bg of [
      '#A0B4C4',  // Snow & Sky — pale blue-grey primary
      '#F5EFE3',  // Earth & Moss background
      '#ECEDEA',  // Mist & Stone background
      '#FFF5E6',  // Sunrise background
      '#FFFFFF',
    ]) {
      assert.equal(contrastText(bg), '#0f172a', `expected charcoal on ${bg}`)
    }
  })

  test('white on pure black, charcoal on pure white', () => {
    assert.equal(contrastText('#000000'), '#ffffff')
    assert.equal(contrastText('#FFFFFF'), '#0f172a')
  })

  test('accepts #rgb shorthand', () => {
    assert.equal(contrastText('#000'), '#ffffff')
    assert.equal(contrastText('#fff'), '#0f172a')
  })

  test('falls back to charcoal on unparseable input rather than throwing', () => {
    assert.equal(contrastText('not-a-hex'), '#0f172a')
    assert.equal(contrastText(''),          '#0f172a')
  })
})
