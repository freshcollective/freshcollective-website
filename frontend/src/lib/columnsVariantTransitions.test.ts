import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  type ColumnsCell,
  type ColumnsPayload,
  activeCells,
  cellCountForVariant,
  cellKind,
  decodeColumns,
  encodeColumns,
  parkedCells,
  resizeColumns,
} from './columnsBlock.ts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const GRID = readFileSync(join(root, 'components/spaces/ColumnsGrid.tsx'), 'utf8')
const EDITOR = readFileSync(join(root, 'components/creator/BlockEditorShared.tsx'), 'utf8')

/**
 * The reported sequence: four columns, down to two, back up to three.
 *
 * Creator Studio showed three columns and the published step showed all
 * four. Since both surfaces render through the same ``activeCells``,
 * they can only disagree if they are holding different payloads — which
 * made this a question about what reached the database, not about
 * resizing or rendering. These tests pin the half that was already
 * correct, so that if this ever regresses it is obvious which half
 * moved.
 *
 * The transitions are asserted on three separate numbers, because they
 * legitimately differ and conflating them is how a bug like this hides:
 *
 *   - how many cells are STORED   (4 throughout — parking is the point)
 *   - how many the VARIANT allows (2, then 3)
 *   - how many are RENDERED       (must always equal the variant's)
 */

const IMG = (tag: string) => ({
  assetId: `asset-${tag}`,
  url: `/uploads/media/s/${tag}.jpg`,
  alt: `Alt ${tag}`,
  assetTitle: `Title ${tag}`,
  caption: `Caption ${tag}`,
})

/** Image, Text, Image, Text — exactly the block in the report. */
function fourColumnBlock(): ColumnsPayload {
  return {
    layout: { kind: 'columns', variant: '25-25-25-25' },
    cells: [
      { content: '', kind: 'image', image: IMG('one') },
      { content: '<p>Column two text</p>' },
      { content: '', kind: 'image', image: IMG('three') },
      { content: '<p>Column four text</p>' },
    ],
  }
}

/** A save followed by reopening the editor. */
const roundTrip = (p: ColumnsPayload) => decodeColumns(encodeColumns(p))

/** Source with comments removed, so an assertion about what the code
 *  DOES is not tripped by a comment explaining what it no longer does.
 *  The comments here deliberately name the old stale-autosave prop. */
function codeOnly(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n')
}

function shape(p: ColumnsPayload) {
  return {
    variant: p.layout.variant,
    stored: p.cells.length,
    allowed: cellCountForVariant(p.layout.variant),
    rendered: activeCells(p).length,
    renderedKinds: activeCells(p).map(cellKind),
  }
}


describe('Test A — four columns to two', () => {
  const two = resizeColumns(fourColumnBlock(), '50-50')

  test('exactly two columns are active', () => {
    assert.equal(shape(two).rendered, 2)
    assert.deepEqual(shape(two).renderedKinds, ['image', 'text'])
  })

  test('all four cells remain stored', () => {
    assert.equal(two.cells.length, 4)
    assert.equal(parkedCells(two).length, 2)
  })

  test('the parked cells keep their content', () => {
    assert.equal(two.cells[2].image?.url, '/uploads/media/s/three.jpg')
    assert.equal(two.cells[3].content, '<p>Column four text</p>')
  })

  test('the stored variant is the one the creator chose', () => {
    assert.equal(two.layout.variant, '50-50')
    assert.equal(roundTrip(two).layout.variant, '50-50')
  })
})


describe('Test B — two columns to three', () => {
  const three = resizeColumns(resizeColumns(fourColumnBlock(), '50-50'), '33-33-33')

  test('exactly three columns are active, not four', () => {
    // The reported defect, stated as a number.
    assert.equal(shape(three).rendered, 3)
    assert.deepEqual(shape(three).renderedKinds, ['image', 'text', 'image'])
  })

  test("column 3's original content is restored", () => {
    assert.equal(cellKind(three.cells[2]), 'image')
    assert.equal(three.cells[2].image?.url, '/uploads/media/s/three.jpg')
    assert.equal(three.cells[2].image?.alt, 'Alt three')
    assert.equal(three.cells[2].image?.caption, 'Caption three')
  })

  test('column 4 stays stored but hidden', () => {
    assert.equal(three.cells.length, 4)
    assert.equal(parkedCells(three).length, 1)
    assert.equal(parkedCells(three)[0].content, '<p>Column four text</p>')
    assert.ok(!activeCells(three).includes(three.cells[3]))
  })

  test('the stored variant is three columns', () => {
    assert.equal(three.layout.variant, '33-33-33')
    assert.equal(cellCountForVariant(three.layout.variant), 3)
  })
})


describe('Test C — three columns back to four', () => {
  const four = resizeColumns(
    resizeColumns(resizeColumns(fourColumnBlock(), '50-50'), '33-33-33'),
    '25-25-25-25',
  )

  test('all four original columns reappear', () => {
    assert.equal(shape(four).rendered, 4)
    assert.deepEqual(shape(four).renderedKinds, ['image', 'text', 'image', 'text'])
  })

  test('every original value survived the whole round trip', () => {
    const original = fourColumnBlock()
    assert.deepEqual(four.cells, original.cells)
  })

  test('images keep their references, captions and alt text', () => {
    for (const i of [0, 2]) {
      const tag = i === 0 ? 'one' : 'three'
      assert.equal(four.cells[i].image?.assetId, `asset-${tag}`)
      assert.equal(four.cells[i].image?.url, `/uploads/media/s/${tag}.jpg`)
      assert.equal(four.cells[i].image?.alt, `Alt ${tag}`)
      assert.equal(four.cells[i].image?.assetTitle, `Title ${tag}`)
      assert.equal(four.cells[i].image?.caption, `Caption ${tag}`)
    }
  })

  test('nothing was parked once the layout is wide enough again', () => {
    assert.equal(parkedCells(four).length, 0)
  })
})


describe('Test D — the same sequence with a save and reload between each step', () => {
  test('the active count follows the selected layout at every step', () => {
    const steps: Array<[string, number]> = [
      ['25-25-25-25', 4], ['50-50', 2], ['33-33-33', 3], ['25-25-25-25', 4],
    ]
    let p = roundTrip(fourColumnBlock())
    assert.equal(shape(p).rendered, 4)

    for (const [variant, expected] of steps.slice(1)) {
      p = roundTrip(resizeColumns(p, variant as never))
      const s = shape(p)
      assert.equal(s.variant, variant)
      assert.equal(s.rendered, expected, `${variant} should render ${expected}`)
      assert.equal(s.stored, 4, `${variant} should still store all four cells`)
    }
  })

  test('the full original block is intact after the whole journey', () => {
    let p: ColumnsPayload = fourColumnBlock()
    for (const v of ['50-50', '33-33-33', '25-25-25-25'] as const) {
      p = roundTrip(resizeColumns(p, v))
    }
    assert.deepEqual(p.cells, fourColumnBlock().cells)
  })

  test('a reload cannot widen the layout on its own', () => {
    // Decoding pads up to the variant's count and keeps the rest; it
    // must never promote stored cells into visible ones.
    const three = resizeColumns(fourColumnBlock(), '33-33-33')
    for (let i = 0; i < 5; i++) {
      const reloaded = roundTrip(three)
      assert.equal(activeCells(reloaded).length, 3, `reload ${i}`)
      assert.equal(reloaded.cells.length, 4, `reload ${i}`)
    }
  })

  test('every variant renders its own column count with four cells stored', () => {
    const stored: ColumnsCell[] = fourColumnBlock().cells
    for (const v of ['50-50', '66-33', '33-66', '33-33-33', '25-25-25-25'] as const) {
      const p = roundTrip({ layout: { kind: 'columns', variant: v }, cells: stored })
      assert.equal(activeCells(p).length, cellCountForVariant(v), v)
      assert.equal(p.cells.length, 4, `${v} keeps all four stored`)
    }
  })
})


describe('Test E — the published renderer honours the variant, not the cell count', () => {
  test('a three-column layout holding four cells renders exactly three', () => {
    const three = resizeColumns(fourColumnBlock(), '33-33-33')
    assert.equal(three.cells.length, 4, 'four cells are stored')
    assert.equal(activeCells(three).length, 3, 'three are rendered')
    assert.equal(cellCountForVariant(three.layout.variant), 3, 'and the grid has three tracks')
  })

  test('ColumnsGrid iterates activeCells and sizes the grid from the variant', () => {
    assert.match(GRID, /const cells = activeCells\(payload\)/)
    assert.match(GRID, /\{cells\.map\(\(cell, i\) =>/)
    assert.ok(!/payload\.cells\.map/.test(GRID), 'must not iterate stored cells')
    assert.match(GRID, /data-cols=\{cellCountForVariant\(variant\)\}/)
    assert.match(GRID, /gridTemplateForVariant\(variant\)/)
  })

  test('the preview iterates activeCells too, so it cannot disagree', () => {
    const preview = EDITOR.slice(
      EDITOR.indexOf('function ColumnsPreview'),
      EDITOR.indexOf('function ColumnsEditor'),
    )
    assert.match(preview, /activeCells\(payload\)\.map/)
    assert.ok(!/payload\.cells\.map/.test(preview))
  })

  test('the editor shows the active columns only', () => {
    const editor = EDITOR.slice(EDITOR.indexOf('function ColumnsEditor'))
    assert.match(editor, /const cells = activeCells\(payload\)/)
    assert.ok(!/payload\.cells\.map/.test(editor))
  })
})


describe('Test F — one save path, never a stale one', () => {
  const editor = codeOnly(EDITOR.slice(EDITOR.indexOf('function ColumnsEditor')))

  test('the columns editor runs no autosave timer of its own', () => {
    // It used to. The effect closed over the render it ran in, which
    // still held the onAutosave prop built before onContentChange
    // updated the parent — so its buildPatch read the PREVIOUS content.
    // Every layout change fired two PATCHes microseconds apart, one
    // correct and one carrying the layout just moved away from, with
    // nothing to order them. When the stale one landed last the block
    // was persisted with the old variant, so the published step showed
    // columns the creator had already hidden.
    assert.ok(!/setTimeout/.test(editor), 'ColumnsEditor schedules its own save again')
    assert.ok(!/debounce/.test(editor), 'a debounce ref is back')
    assert.ok(!/\bonAutosave\b/.test(editor), 'ColumnsEditor takes an autosave callback again')
  })

  test('the call site passes the editor no autosave callback', () => {
    const from = EDITOR.indexOf('<ColumnsEditor')
    const callSite = codeOnly(EDITOR.slice(from, from + EDITOR.slice(from).indexOf('/>') + 2))
    assert.ok(callSite.includes('onContentChange={setContent}'), 'slice bounds')
    assert.ok(!callSite.includes('onAutosave'), 'the stale closure is being bound again')
  })

  test('the editor still hands every payload change up to the form', () => {
    // This call is what schedules the save now, so losing it would stop
    // columns saving altogether.
    assert.match(editor, /useEffect\(\(\) => \{\s*onContentChange\(encodeColumns\(payload\)\)/)
    assert.match(editor, /\}, \[payload\]\)/)
  })

  test("the form's autosave is keyed on content, so it covers columns", () => {
    // And because it re-runs when content changes, its buildPatch is
    // always the current one — which is why it was never the stale
    // writer.
    const form = codeOnly(EDITOR.slice(EDITOR.indexOf('export function BlockEditForm')))
    assert.match(form, /autosaveTimer\.current = setTimeout\(\(\) => \{\s*onAutosave\(buildPatch\(\)\)/)
    const deps = form.slice(form.indexOf('autosaveTimer.current = setTimeout'))
    assert.match(deps, /\}, \[content, label, caption/)
  })

  test('a layout change therefore persists exactly the chosen variant', () => {
    // The end-to-end property the two tests above protect, stated on
    // the data: whatever the editor shows is what a save would carry.
    let p: ColumnsPayload = fourColumnBlock()
    for (const v of ['50-50', '33-33-33', '25-25-25-25'] as const) {
      p = resizeColumns(p, v)
      const persisted = decodeColumns(encodeColumns(p))   // the one PATCH
      assert.equal(persisted.layout.variant, v)
      assert.equal(activeCells(persisted).length, activeCells(p).length)
      assert.equal(activeCells(persisted).length, cellCountForVariant(v))
    }
  })
})


describe('Test G — compatibility', () => {
  test('a legacy text-only block still round-trips byte-identically', () => {
    const legacy =
      '{"layout":{"kind":"columns","variant":"50-50"},' +
      '"cells":[{"content":"<p>Left</p>"},{"content":"<p>Right</p>"}]}'
    assert.equal(encodeColumns(decodeColumns(legacy)), legacy)
    assert.equal(activeCells(decodeColumns(legacy)).length, 2)
  })

  test('text-only blocks survive the same transition sequence', () => {
    let p: ColumnsPayload = {
      layout: { kind: 'columns', variant: '25-25-25-25' },
      cells: [1, 2, 3, 4].map((n) => ({ content: `<p>Cell ${n}</p>` })),
    }
    p = roundTrip(resizeColumns(p, '50-50'))
    assert.equal(activeCells(p).length, 2)
    p = roundTrip(resizeColumns(p, '33-33-33'))
    assert.equal(activeCells(p).length, 3)
    assert.equal(activeCells(p)[2].content, '<p>Cell 3</p>')
    p = roundTrip(resizeColumns(p, '25-25-25-25'))
    assert.deepEqual(p.cells.map((c) => c.content),
      ['<p>Cell 1</p>', '<p>Cell 2</p>', '<p>Cell 3</p>', '<p>Cell 4</p>'])
  })

  test('all five variants remain selectable and render their own count', () => {
    for (const v of ['50-50', '66-33', '33-66', '33-33-33', '25-25-25-25'] as const) {
      const p = resizeColumns(fourColumnBlock(), v)
      assert.equal(p.layout.variant, v)
      assert.equal(activeCells(p).length, cellCountForVariant(v), v)
    }
  })
})
