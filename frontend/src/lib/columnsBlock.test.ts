import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  type ColumnsCell,
  type ColumnsPayload,
  MAX_COLUMNS_CELLS,
  activeCells,
  cellImageAlt,
  cellIsPopulated,
  cellKind,
  decodeColumns,
  emptyColumnsPayload,
  encodeColumns,
  parkedCells,
  resizeColumns,
  setCellContent,
  setCellImage,
  setCellKind,
} from './columnsBlock.ts'

/**
 * Columns blocks hold creators' published writing, and now their
 * images, in a JSON envelope that is decoded and re-encoded on every
 * edit and every 700ms autosave tick. That round trip is the risk: the
 * previous implementation rebuilt each cell as ``{ content }`` and so
 * discarded any other key it found. Adding image fields on top of that
 * would have deleted a creator's images the next time they opened the
 * editor, with no error and nothing in the logs.
 *
 * So most of what follows is loss tests rather than feature tests. They
 * assert that text survives switching to Image, that an image survives
 * switching back to Text, that both survive a layout change, and that
 * none of it depends on the creator doing things in a particular order.
 *
 * The legacy case is first and is the one that must never go red: a
 * columns block written before any of this existed has to decode, and
 * re-encode, exactly as it was. There is no migration and no backfill,
 * so this test is the whole of the compatibility guarantee.
 */

const LEGACY_TWO_COL =
  '{"layout":{"kind":"columns","variant":"50-50"},' +
  '"cells":[{"content":"<p>Left</p>"},{"content":"<p>Right</p>"}]}'

/** A stored image cell payload in its canonical, decoded shape — every
 *  optional field present, which is what decodeColumns normalises to. */
function image(url: string, extra: Record<string, unknown> = {}) {
  return { assetId: 'asset-1', url, alt: null, assetTitle: null, caption: null, ...extra }
}


describe('legacy compatibility — no migration, no backfill', () => {
  test('a pre-image columns block decodes to the same two text cells', () => {
    const payload = decodeColumns(LEGACY_TWO_COL)
    assert.equal(payload.layout.variant, '50-50')
    assert.equal(payload.cells.length, 2)
    assert.equal(payload.cells[0].content, '<p>Left</p>')
    assert.equal(payload.cells[1].content, '<p>Right</p>')
  })

  test('absent kind means text', () => {
    const payload = decodeColumns(LEGACY_TWO_COL)
    assert.equal(payload.cells[0].kind, undefined)
    assert.equal(cellKind(payload.cells[0]), 'text')
    assert.equal(cellKind(payload.cells[1]), 'text')
  })

  test('decode then encode leaves a legacy row byte-identical', () => {
    // The strongest form of "existing content keeps working": opening an
    // old block and letting autosave fire must not rewrite the row at
    // all, let alone add fields to it.
    assert.equal(encodeColumns(decodeColumns(LEGACY_TWO_COL)), LEGACY_TWO_COL)
  })

  test('every variant survives a legacy decode/encode round trip', () => {
    for (const variant of ['50-50', '66-33', '33-66', '33-33-33', '25-25-25-25'] as const) {
      const cells = Array.from({ length: 4 }, (_, i) => ({ content: `<p>c${i}</p>` }))
        .slice(0, variant === '25-25-25-25' ? 4 : variant === '33-33-33' ? 3 : 2)
      const raw = JSON.stringify({ layout: { kind: 'columns', variant }, cells })
      assert.equal(encodeColumns(decodeColumns(raw)), raw, variant)
    }
  })

  test('new columns blocks default to all-text cells', () => {
    const fresh = emptyColumnsPayload()
    assert.equal(fresh.cells.length, 2)
    for (const cell of fresh.cells) {
      assert.equal(cellKind(cell), 'text')
      assert.equal(cell.image, undefined)
    }
  })
})


describe('images survive encoding and decoding', () => {
  test('a text + image payload round-trips intact', () => {
    const payload: ColumnsPayload = {
      layout: { kind: 'columns', variant: '50-50' },
      cells: [
        { content: '<p>Words</p>' },
        { content: '', kind: 'image', image: image('/uploads/media/s/a.jpg', { alt: 'A view', caption: 'By the sea' }) },
      ],
    }
    const back = decodeColumns(encodeColumns(payload))
    assert.equal(cellKind(back.cells[0]), 'text')
    assert.equal(cellKind(back.cells[1]), 'image')
    assert.equal(back.cells[1].image?.url, '/uploads/media/s/a.jpg')
    assert.equal(back.cells[1].image?.assetId, 'asset-1')
    assert.equal(back.cells[1].image?.alt, 'A view')
    assert.equal(back.cells[1].image?.caption, 'By the sea')
  })

  test('all four requested combinations round-trip', () => {
    const text = (s: string): ColumnsCell => ({ content: `<p>${s}</p>` })
    const img = (u: string): ColumnsCell => ({ content: '', kind: 'image', image: image(u) })
    const combos: Array<[string, ColumnsCell[]]> = [
      ['text + text', [text('a'), text('b')]],
      ['text + image', [text('a'), img('/x.jpg')]],
      ['image + text', [img('/x.jpg'), text('b')]],
      ['image + image', [img('/x.jpg'), img('/y.jpg')]],
    ]
    for (const [name, cells] of combos) {
      const back = decodeColumns(
        encodeColumns({ layout: { kind: 'columns', variant: '50-50' }, cells }),
      )
      assert.deepEqual(back.cells.map(cellKind), cells.map(cellKind), name)
      assert.deepEqual(
        back.cells.map((c) => c.image?.url ?? null),
        cells.map((c) => c.image?.url ?? null),
        name,
      )
    }
  })

  test('mixed three- and four-column layouts round-trip', () => {
    for (const [variant, n] of [['33-33-33', 3], ['25-25-25-25', 4]] as const) {
      const cells: ColumnsCell[] = Array.from({ length: n }, (_, i) =>
        i % 2 === 0
          ? { content: `<p>col ${i}</p>` }
          : { content: '', kind: 'image', image: image(`/i${i}.jpg`) },
      )
      const back = decodeColumns(encodeColumns({ layout: { kind: 'columns', variant }, cells }))
      assert.equal(back.cells.length, n, variant)
      assert.deepEqual(back.cells.map(cellKind), cells.map(cellKind), variant)
      for (let i = 1; i < n; i += 2) {
        assert.equal(back.cells[i].image?.url, `/i${i}.jpg`, `${variant} cell ${i}`)
      }
    }
  })

  test('alt text keeps all three states distinct', () => {
    // '' is decorative and must not be normalised away to null, which
    // would make the image inherit its asset title instead of being
    // announced as decorative.
    const cells = [
      { content: '', kind: 'image' as const, image: image('/a.jpg', { alt: 'Explicit' }) },
      { content: '', kind: 'image' as const, image: image('/b.jpg', { alt: '' }) },
    ]
    const back = decodeColumns(
      encodeColumns({ layout: { kind: 'columns', variant: '50-50' }, cells }),
    )
    assert.equal(back.cells[0].image?.alt, 'Explicit')
    assert.equal(back.cells[1].image?.alt, '')

    // A cell whose alt key never existed inherits the asset title.
    const noAlt = decodeColumns(
      '{"layout":{"kind":"columns","variant":"50-50"},"cells":' +
      '[{"kind":"image","content":"","image":{"url":"/c.jpg"}},{"content":""}]}',
    )
    assert.equal(noAlt.cells[0].image?.alt, null)
  })

  test('cellImageAlt resolves all three states like an image block does', () => {
    // Explicit alt wins.
    assert.equal(cellImageAlt(image('/a.jpg', { alt: 'A heron', assetTitle: 'heron.jpg' })), 'A heron')
    // Decorative: '' must NOT fall through to the asset title.
    assert.equal(cellImageAlt(image('/a.jpg', { alt: '', assetTitle: 'heron.jpg' })), '')
    // No decision recorded: inherit the asset title.
    assert.equal(cellImageAlt(image('/a.jpg', { alt: null, assetTitle: 'heron.jpg' })), 'heron.jpg')
    // Nothing to inherit either.
    assert.equal(cellImageAlt(image('/a.jpg', { alt: null, assetTitle: null })), '')
    assert.equal(cellImageAlt(undefined), '')
  })

  test('the asset title is carried so the inherit state can resolve', () => {
    const back = decodeColumns(encodeColumns({
      layout: { kind: 'columns', variant: '50-50' },
      cells: [
        { content: '', kind: 'image', image: image('/a.jpg', { alt: null, assetTitle: 'Morning light' }) },
        { content: '' },
      ],
    }))
    assert.equal(back.cells[0].image?.assetTitle, 'Morning light')
    assert.equal(cellImageAlt(back.cells[0].image), 'Morning light')
  })
})


describe('images survive editing and autosaving', () => {
  test('typing in one column does not disturb an image in another', () => {
    // Reproduces the autosave path: mutate, encode, decode, mutate again.
    let payload = decodeColumns(LEGACY_TWO_COL)
    payload = setCellKind(payload, 1, 'image')
    payload = setCellImage(payload, 1, image('/uploads/media/s/pic.jpg'))

    for (const text of ['<p>One</p>', '<p>One two</p>', '<p>One two three</p>']) {
      payload = setCellContent(payload, 0, text)
      payload = decodeColumns(encodeColumns(payload)) // autosave tick
      assert.equal(payload.cells[1].image?.url, '/uploads/media/s/pic.jpg')
      assert.equal(cellKind(payload.cells[1]), 'image')
    }
    assert.equal(payload.cells[0].content, '<p>One two three</p>')
  })

  test('reopening the editor after an autosave shows the same payload', () => {
    let payload = emptyColumnsPayload('33-33-33')
    payload = setCellContent(payload, 0, '<p>Intro</p>')
    payload = setCellKind(payload, 1, 'image')
    payload = setCellImage(payload, 1, image('/m.jpg', { caption: 'Cap' }))
    payload = setCellContent(payload, 2, '<p>Outro</p>')

    const stored = encodeColumns(payload)
    const reopened = decodeColumns(stored)
    assert.deepEqual(reopened, payload)
    assert.equal(reopened.cells[1].image?.caption, 'Cap')

    // Decoding is idempotent, so an open block does not churn through
    // autosave just because it was re-serialised in a different order.
    assert.equal(encodeColumns(decodeColumns(encodeColumns(reopened))), encodeColumns(reopened))
  })
})


describe('switching content types preserves both forms', () => {
  test('text is preserved when a column switches to image', () => {
    let payload = decodeColumns(LEGACY_TWO_COL)
    payload = setCellKind(payload, 0, 'image')
    assert.equal(payload.cells[0].content, '<p>Left</p>')
    payload = setCellImage(payload, 0, image('/p.jpg'))
    // ...and still after a save.
    payload = decodeColumns(encodeColumns(payload))
    assert.equal(payload.cells[0].content, '<p>Left</p>')
    assert.equal(cellKind(payload.cells[0]), 'image')
  })

  test('the image reference is preserved when switching back to text', () => {
    let payload = decodeColumns(LEGACY_TWO_COL)
    payload = setCellImage(setCellKind(payload, 0, 'image'), 0, image('/p.jpg'))
    payload = decodeColumns(encodeColumns(payload))

    payload = setCellKind(payload, 0, 'text')
    assert.equal(cellKind(payload.cells[0]), 'text')
    assert.equal(payload.cells[0].image?.url, '/p.jpg', 'image kept while inactive')
    assert.equal(payload.cells[0].content, '<p>Left</p>')
  })

  test('switching back and forth repeatedly erases neither form', () => {
    let payload = decodeColumns(LEGACY_TWO_COL)
    payload = setCellImage(setCellKind(payload, 0, 'image'), 0, image('/p.jpg', { alt: 'Alt' }))

    for (let i = 0; i < 6; i++) {
      payload = setCellKind(payload, 0, i % 2 === 0 ? 'text' : 'image')
      payload = decodeColumns(encodeColumns(payload))
      assert.equal(payload.cells[0].content, '<p>Left</p>', `text at pass ${i}`)
      assert.equal(payload.cells[0].image?.url, '/p.jpg', `image at pass ${i}`)
      assert.equal(payload.cells[0].image?.alt, 'Alt', `alt at pass ${i}`)
    }
  })

  test('explicitly removing an image clears it but stays in image mode', () => {
    let payload = setCellImage(setCellKind(emptyColumnsPayload(), 0, 'image'), 0, image('/p.jpg'))
    payload = setCellImage(payload, 0, null)
    assert.equal(payload.cells[0].image, undefined)
    assert.equal(cellKind(payload.cells[0]), 'image', 'controls stay visible')
  })

  test('an image cell with no image chosen stays an image cell across a save', () => {
    // Otherwise a creator who switches to Image, gets distracted and
    // reloads finds the column back on the text editor.
    const payload = setCellKind(emptyColumnsPayload(), 1, 'image')
    const back = decodeColumns(encodeColumns(payload))
    assert.equal(cellKind(back.cells[1]), 'image')
    assert.equal(back.cells[1].image, undefined)
  })
})


describe('changing layout variants does not destroy populated cells', () => {
  test('widening keeps existing cells by position and adds empty text', () => {
    const payload = resizeColumns(decodeColumns(LEGACY_TWO_COL), '33-33-33')
    assert.equal(payload.cells.length, 3)
    assert.equal(payload.cells[0].content, '<p>Left</p>')
    assert.equal(payload.cells[1].content, '<p>Right</p>')
    assert.equal(payload.cells[2].content, '')
    assert.equal(cellKind(payload.cells[2]), 'text')
  })

  test('images survive widening and narrowing', () => {
    let payload = emptyColumnsPayload('33-33-33')
    payload = setCellImage(setCellKind(payload, 1, 'image'), 1, image('/mid.jpg'))
    payload = resizeColumns(payload, '25-25-25-25')
    assert.equal(payload.cells[1].image?.url, '/mid.jpg', 'after widening')
    payload = resizeColumns(payload, '66-33')
    assert.equal(payload.cells[1].image?.url, '/mid.jpg', 'after narrowing')
  })

  test('narrowing parks the extra columns instead of discarding them', () => {
    let payload = emptyColumnsPayload('25-25-25-25')
    payload = setCellContent(payload, 2, '<p>Third</p>')
    payload = setCellImage(setCellKind(payload, 3, 'image'), 3, image('/fourth.jpg'))

    const narrowed = resizeColumns(payload, '50-50')
    assert.equal(activeCells(narrowed).length, 2, 'only two columns are shown')
    assert.equal(parkedCells(narrowed).length, 2, 'the other two are held')

    // And they come back, through a save, when the layout widens again.
    const widened = resizeColumns(decodeColumns(encodeColumns(narrowed)), '25-25-25-25')
    assert.equal(widened.cells[2].content, '<p>Third</p>')
    assert.equal(widened.cells[3].image?.url, '/fourth.jpg')
  })

  test('parked cells never leak into the rendered columns', () => {
    const narrowed = resizeColumns(emptyColumnsPayload('25-25-25-25'), '50-50')
    assert.equal(activeCells(narrowed).length, 2)
    assert.equal(activeCells(resizeColumns(narrowed, '33-33-33')).length, 3)
  })

  test('a payload can never grow past the widest variant', () => {
    let payload = emptyColumnsPayload('25-25-25-25')
    for (const v of ['50-50', '25-25-25-25', '33-66', '33-33-33', '25-25-25-25'] as const) {
      payload = resizeColumns(payload, v)
      assert.ok(payload.cells.length <= MAX_COLUMNS_CELLS, `${v}: ${payload.cells.length}`)
    }
    assert.equal(MAX_COLUMNS_CELLS, 4)
  })

  test('cellIsPopulated distinguishes real content from an empty editor', () => {
    assert.equal(cellIsPopulated({ content: '' }), false)
    assert.equal(cellIsPopulated({ content: '<p></p>' }), false)
    assert.equal(cellIsPopulated({ content: '<p>&nbsp;</p>' }), false)
    assert.equal(cellIsPopulated({ content: '<p>Hi</p>' }), true)
    assert.equal(cellIsPopulated({ content: '<hr>' }), true)
    assert.equal(cellIsPopulated({ content: '', kind: 'image', image: image('/a.jpg') }), true)
    assert.equal(cellIsPopulated({ content: '', kind: 'image' }), false)
    assert.equal(cellIsPopulated(undefined), false)
  })
})


describe('malformed payloads are handled safely', () => {
  test('an unrecognised cell kind falls back to text', () => {
    const payload = decodeColumns(
      '{"layout":{"kind":"columns","variant":"50-50"},"cells":' +
      '[{"content":"<p>a</p>","kind":"carousel"},{"content":"<p>b</p>","kind":7}]}',
    )
    assert.equal(cellKind(payload.cells[0]), 'text')
    assert.equal(cellKind(payload.cells[1]), 'text')
    assert.equal(payload.cells[0].content, '<p>a</p>', 'content still readable')

    // And the junk is not written back into the creator's row: only a
    // kind we understand is ever persisted.
    assert.equal(payload.cells[0].kind, undefined)
    assert.equal(payload.cells[1].kind, undefined)
    assert.ok(!encodeColumns(payload).includes('carousel'))
  })

  test('an image with no usable url is dropped, and the cell still opens', () => {
    for (const bad of ['{"assetId":"a"}', '{"url":""}', '{"url":"   "}', '{"url":42}', 'null', '"/a.jpg"', '[]']) {
      const payload = decodeColumns(
        '{"layout":{"kind":"columns","variant":"50-50"},"cells":' +
        `[{"kind":"image","content":"<p>kept</p>","image":${bad}},{"content":""}]}`,
      )
      assert.equal(payload.cells[0].image, undefined, bad)
      assert.equal(cellKind(payload.cells[0]), 'image', bad)
      assert.equal(payload.cells[0].content, '<p>kept</p>', bad)
    }
  })

  test('garbage cell entries become empty text cells rather than throwing', () => {
    const payload = decodeColumns(
      '{"layout":{"kind":"columns","variant":"33-33-33"},"cells":[null,"nope",5]}',
    )
    assert.equal(payload.cells.length, 3)
    for (const cell of payload.cells) {
      assert.equal(cell.content, '')
      assert.equal(cellKind(cell), 'text')
    }
  })

  test('non-string assetId and caption are normalised, not trusted', () => {
    const payload = decodeColumns(
      '{"layout":{"kind":"columns","variant":"50-50"},"cells":' +
      '[{"kind":"image","content":"","image":{"url":"/a.jpg","assetId":9,"caption":{"x":1}}},{"content":""}]}',
    )
    assert.equal(payload.cells[0].image?.assetId, null)
    assert.equal(payload.cells[0].image?.caption, null)
    assert.equal(payload.cells[0].image?.url, '/a.jpg')
  })

  test('a wholly unparseable or foreign envelope yields an empty text layout', () => {
    for (const bad of ['', '   ', 'not json', '{}', '{"layout":{"kind":"cards","variant":"50-50"}}',
                       '{"layout":{"kind":"columns","variant":"80-20"}}', 'null', '[]']) {
      const payload = decodeColumns(bad)
      assert.equal(payload.layout.variant, '50-50', JSON.stringify(bad))
      assert.equal(payload.cells.length, 2, JSON.stringify(bad))
      assert.ok(payload.cells.every((c) => cellKind(c) === 'text'), JSON.stringify(bad))
    }
  })

  test('too many cells are capped rather than accumulating', () => {
    const cells = Array.from({ length: 40 }, (_, i) => ({ content: `<p>${i}</p>` }))
    const payload = decodeColumns(JSON.stringify({ layout: { kind: 'columns', variant: '50-50' }, cells }))
    assert.equal(payload.cells.length, MAX_COLUMNS_CELLS)
  })

  test('cell mutators ignore out-of-range indexes', () => {
    const base = emptyColumnsPayload()
    assert.equal(setCellKind(base, 9, 'image'), base)
    assert.equal(setCellContent(base, -1, 'x'), base)
    assert.equal(setCellImage(base, 2, image('/a.jpg')), base)
  })
})
