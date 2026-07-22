/**
 * Unit tests for the pure helpers in ``columnsBlock.ts``.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping — no new dev dependency required:
 *
 *     node --experimental-strip-types --test src/lib/columnsBlock.test.ts
 *
 * Locks the JSON envelope shape, variant→cell-count / →grid mapping,
 * and the resize behaviour that preserves per-cell content when the
 * writer switches variants.
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
// @ts-expect-error - Node-native import path
import {
  COLUMNS_VARIANTS,
  cellCountForVariant,
  decodeColumns,
  emptyColumnsPayload,
  encodeColumns,
  gridTemplateForVariant,
  labelForVariant,
  resizeColumns,
} from './columnsBlock.ts'


describe('cellCountForVariant', () => {
  test('returns 2 for 50-50', () => {
    assert.equal(cellCountForVariant('50-50'), 2)
  })
  test('returns 3 for 33-33-33', () => {
    assert.equal(cellCountForVariant('33-33-33'), 3)
  })
  test('returns 4 for 25-25-25-25', () => {
    assert.equal(cellCountForVariant('25-25-25-25'), 4)
  })
  test('returns 2 for 66-33 and 33-66', () => {
    assert.equal(cellCountForVariant('66-33'), 2)
    assert.equal(cellCountForVariant('33-66'), 2)
  })
})


describe('gridTemplateForVariant', () => {
  test('50-50 → 1fr 1fr', () => {
    assert.equal(gridTemplateForVariant('50-50'), '1fr 1fr')
  })
  test('33-33-33 → 1fr 1fr 1fr', () => {
    assert.equal(gridTemplateForVariant('33-33-33'), '1fr 1fr 1fr')
  })
  test('25-25-25-25 → 1fr 1fr 1fr 1fr', () => {
    assert.equal(gridTemplateForVariant('25-25-25-25'), '1fr 1fr 1fr 1fr')
  })
  test('66-33 → 2fr 1fr', () => {
    assert.equal(gridTemplateForVariant('66-33'), '2fr 1fr')
  })
  test('33-66 → 1fr 2fr', () => {
    assert.equal(gridTemplateForVariant('33-66'), '1fr 2fr')
  })
})


describe('labelForVariant', () => {
  test('every declared variant has a non-empty label', () => {
    for (const v of COLUMNS_VARIANTS) {
      assert.ok(labelForVariant(v).length > 0, `missing label for ${v}`)
    }
  })
})


describe('emptyColumnsPayload', () => {
  test('defaults to 50-50 with two empty cells', () => {
    const p = emptyColumnsPayload()
    assert.equal(p.layout.kind, 'columns')
    assert.equal(p.layout.variant, '50-50')
    assert.equal(p.cells.length, 2)
    assert.ok(p.cells.every((c) => c.content === ''))
  })
  test('honours requested variant', () => {
    const p = emptyColumnsPayload('25-25-25-25')
    assert.equal(p.cells.length, 4)
  })
})


describe('encode/decode round trip', () => {
  test('preserves cell contents verbatim', () => {
    const payload = {
      layout: { kind: 'columns' as const, variant: '50-50' as const },
      cells: [
        { content: '<p>Left column HTML</p>' },
        { content: '<p><strong>Right</strong></p>' },
      ],
    }
    const encoded = encodeColumns(payload)
    const decoded = decodeColumns(encoded)
    assert.deepEqual(decoded, payload)
  })

  test('empty/null content decodes to a fresh 50-50 payload', () => {
    assert.deepEqual(decodeColumns(null), emptyColumnsPayload())
    assert.deepEqual(decodeColumns(''), emptyColumnsPayload())
    assert.deepEqual(decodeColumns('   '), emptyColumnsPayload())
  })

  test('malformed JSON decodes to a fresh 50-50 payload (no crash)', () => {
    assert.deepEqual(decodeColumns('{not json'), emptyColumnsPayload())
    assert.deepEqual(decodeColumns('null'), emptyColumnsPayload())
    assert.deepEqual(decodeColumns('42'), emptyColumnsPayload())
  })

  test('unknown variant falls back to fresh 50-50 payload', () => {
    const s = JSON.stringify({
      layout: { kind: 'columns', variant: 'made-up-variant' },
      cells: [{ content: 'x' }, { content: 'y' }],
    })
    assert.deepEqual(decodeColumns(s), emptyColumnsPayload())
  })

  test('decoded payload always has exactly the wanted number of cells', () => {
    for (const v of COLUMNS_VARIANTS) {
      const raw = JSON.stringify({
        layout: { kind: 'columns', variant: v },
        cells: [{ content: 'only one' }],
      })
      const decoded = decodeColumns(raw)
      assert.equal(decoded.cells.length, cellCountForVariant(v))
      assert.equal(decoded.cells[0].content, 'only one')
      for (let i = 1; i < decoded.cells.length; i++) {
        assert.equal(decoded.cells[i].content, '')
      }
    }
  })
})


describe('resizeColumns', () => {
  test('growing 50-50 → 25-25-25-25 preserves the first two cells and pads', () => {
    const src = {
      layout: { kind: 'columns' as const, variant: '50-50' as const },
      cells: [{ content: 'A' }, { content: 'B' }],
    }
    const dst = resizeColumns(src, '25-25-25-25')
    assert.equal(dst.cells.length, 4)
    assert.equal(dst.cells[0].content, 'A')
    assert.equal(dst.cells[1].content, 'B')
    assert.equal(dst.cells[2].content, '')
    assert.equal(dst.cells[3].content, '')
  })

  test('shrinking 33-33-33 → 50-50 drops the trailing cell', () => {
    const src = {
      layout: { kind: 'columns' as const, variant: '33-33-33' as const },
      cells: [{ content: 'A' }, { content: 'B' }, { content: 'C' }],
    }
    const dst = resizeColumns(src, '50-50')
    assert.equal(dst.cells.length, 2)
    assert.equal(dst.cells[0].content, 'A')
    assert.equal(dst.cells[1].content, 'B')
  })

  test('switching between 66-33 and 33-66 preserves cells in order', () => {
    const src = {
      layout: { kind: 'columns' as const, variant: '66-33' as const },
      cells: [{ content: 'wide' }, { content: 'narrow' }],
    }
    const dst = resizeColumns(src, '33-66')
    assert.equal(dst.cells[0].content, 'wide')
    assert.equal(dst.cells[1].content, 'narrow')
  })
})
