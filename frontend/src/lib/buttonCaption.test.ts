/**
 * Unit tests for the button caption codec.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping:
 *
 *     node --experimental-strip-types --test src/lib/buttonCaption.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import {
  defaultButtonCaption,
  encodeButtonCaption,
  parseButtonCaption,
} from './buttonCaption.ts'


describe('parseButtonCaption', () => {
  test('empty / null / undefined → legacy primary (safe default)', () => {
    assert.deepEqual(parseButtonCaption(null),      { kind: 'legacy', style: 'primary' })
    assert.deepEqual(parseButtonCaption(undefined), { kind: 'legacy', style: 'primary' })
    assert.deepEqual(parseButtonCaption(''),        { kind: 'legacy', style: 'primary' })
  })

  test('each legacy string decodes verbatim', () => {
    for (const s of ['primary', 'secondary', 'outline', 'subtle']) {
      assert.deepEqual(parseButtonCaption(s), { kind: 'legacy', style: s })
    }
  })

  test('new JSON envelope decodes to modern shape', () => {
    const r = parseButtonCaption('{"style":"filled","colour":"palette:primary"}')
    assert.deepEqual(r, { kind: 'modern', style: 'filled', colour: 'palette:primary' })
  })

  test('custom hex colour round-trips', () => {
    const r = parseButtonCaption('{"style":"outline","colour":"custom:#3A6B7A"}')
    assert.deepEqual(r, { kind: 'modern', style: 'outline', colour: 'custom:#3A6B7A' })
  })

  test('unknown style within JSON falls back to filled (safe)', () => {
    const r = parseButtonCaption('{"style":"weird","colour":"palette:accent"}')
    assert.equal(r.kind, 'modern')
    if (r.kind === 'modern') {
      assert.equal(r.style, 'filled')
      assert.equal(r.colour, 'palette:accent')
    }
  })

  test('missing colour within JSON defaults to palette:primary', () => {
    const r = parseButtonCaption('{"style":"outline"}')
    assert.deepEqual(r, { kind: 'modern', style: 'outline', colour: 'palette:primary' })
  })

  test('malformed JSON falls back to legacy primary', () => {
    assert.deepEqual(parseButtonCaption('{not json'), { kind: 'legacy', style: 'primary' })
  })
})


describe('encodeButtonCaption', () => {
  test('round-trips through parse for every combination', () => {
    const styles = ['filled', 'outline', 'text'] as const
    const colours = ['palette:primary', 'palette:accent', 'custom:#3A6B7A']
    for (const s of styles) {
      for (const c of colours) {
        const encoded = encodeButtonCaption(s, c)
        const decoded = parseButtonCaption(encoded)
        assert.deepEqual(decoded, { kind: 'modern', style: s, colour: c })
      }
    }
  })
})


describe('defaultButtonCaption', () => {
  test('is a Filled + palette:primary envelope', () => {
    const r = parseButtonCaption(defaultButtonCaption())
    assert.deepEqual(r, { kind: 'modern', style: 'filled', colour: 'palette:primary' })
  })
})
