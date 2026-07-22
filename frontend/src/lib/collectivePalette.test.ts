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
