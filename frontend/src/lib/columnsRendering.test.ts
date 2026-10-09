import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(root, p), 'utf8')

const GRID = read('components/spaces/ColumnsGrid.tsx')
const STEP = read('components/spaces/BlockList.tsx')
const ABOUT = read('components/spaces/AboutBlockRenderer.tsx')

/**
 * Columns blocks render on three surfaces: the member Pathway step, the
 * public About page, and the Creator Studio preview. The recurring
 * failure in this backlog has been a change landing on two of the three
 * and nobody noticing until a creator reported it, so these tests pin
 * the two member-facing ones to a single shared component rather than
 * checking that two copies happen to agree today.
 *
 * They are source-contract tests. There is no DOM in this suite, and
 * the properties worth protecting here are structural — that a parked
 * column can't reach a member's page, that an image can't be stretched
 * to match the text beside it, that alt text goes through the one
 * resolver that understands decorative images. Actual rendered geometry
 * is measured separately in Chromium.
 */

describe('both member renderers delegate to the shared grid', () => {
  test('the step renderer uses ColumnsGrid', () => {
    assert.ok(GRID.length > 0)
    assert.match(STEP, /import ColumnsGrid from '@\/components\/spaces\/ColumnsGrid'/)
    assert.match(STEP, /<ColumnsGrid payload=\{decodeColumns\(block\.content\)\}/)
  })

  test('the About renderer uses ColumnsGrid', () => {
    assert.match(ABOUT, /import ColumnsGrid from '@\/components\/spaces\/ColumnsGrid'/)
    assert.match(ABOUT, /<ColumnsGrid\s/)
  })

  test('neither renderer still builds its own columns grid', () => {
    // The old inline markup. If this comes back, the two surfaces can
    // drift again.
    for (const [name, src] of [['step', STEP], ['about', ABOUT]] as const) {
      assert.ok(!src.includes('fc-columns-grid'), `${name} still has inline grid markup`)
      assert.ok(!src.includes('gridTemplateForVariant'), `${name} still computes its own template`)
    }
  })

  test('neither renderer iterates raw cells, which would show parked columns', () => {
    for (const [name, src] of [['step', STEP], ['about', ABOUT]] as const) {
      assert.ok(!/payload\.cells/.test(src), `${name} iterates payload.cells directly`)
    }
  })

  test('the About page keeps its prose typography on text cells', () => {
    assert.match(ABOUT, /cellClassName="prose prose-sm max-w-none text-black"/)
  })

  test('the step renderer keeps its vertical rhythm around the block', () => {
    assert.match(STEP, /<ColumnsGrid[^>]*className="my-1\.5"/)
  })
})

describe('the shared grid', () => {
  test('renders only the active cells, never the parked ones', () => {
    assert.match(GRID, /activeCells\(payload\)/)
    assert.ok(!/payload\.cells\.map/.test(GRID), 'maps raw cells instead of active ones')
  })

  test('top-aligns cells so an image is not stretched by its neighbour', () => {
    assert.match(GRID, /className=\{\['fc-columns-grid grid items-start gap-6'/)
  })

  test('publishes the column count to CSS for the stacking breakpoints', () => {
    assert.match(GRID, /data-cols=\{cellCountForVariant\(variant\)\}/)
  })

  test('sets the grid template from the variant', () => {
    assert.match(GRID, /'--fc-cols' as string\]: gridTemplateForVariant\(variant\)/)
  })
})

describe('image cells', () => {
  const cellImage = GRID.slice(GRID.indexOf('function CellImage'))

  test('render nothing when no image has been chosen yet', () => {
    // A column switched to Image but left empty must look empty, not
    // broken.
    assert.match(cellImage, /if \(!image\?\.url\) return null/)
  })

  test('resolve the media URL the same way image blocks do', () => {
    assert.match(cellImage, /resolveMediaUrl\(image\.url\) \?\? image\.url/)
  })

  test('keep their natural aspect ratio and cannot overflow the column', () => {
    assert.match(cellImage, /className="h-auto w-full rounded-xl/)
    // object-cover would crop or distort once any height is imposed.
    assert.ok(!cellImage.includes('object-cover'), 'object-cover can distort')
    assert.ok(!cellImage.includes('object-fill'))
    assert.ok(!/\bh-full\b/.test(cellImage), 'h-full would stretch to the row height')
  })

  test('use the existing rounded-corner and shadow treatment', () => {
    assert.match(cellImage, /rounded-xl/)
    assert.match(cellImage, /shadow-\[0_1px_3px_rgba\(15,30,55,0\.08\)/)
  })

  test('opt out of prose typography so both surfaces match', () => {
    assert.match(cellImage, /<figure className="not-prose">/)
  })

  test('go through the one alt resolver, not a hand-rolled fallback', () => {
    assert.match(cellImage, /alt=\{cellImageAlt\(image\)\}/)
    // A local ``image.alt || …`` here would silently re-announce
    // decorative images.
    assert.ok(!/image\.alt \|\|/.test(cellImage))
    assert.ok(!/image\.alt \?\?/.test(cellImage))
  })

  test('show a caption only when there is one', () => {
    assert.match(cellImage, /image\.caption\?\.trim\(\) &&/)
    assert.match(cellImage, /<figcaption className="mt-2 text-center text-\[12px\] text-black">/)
  })
})

describe('text cells', () => {
  const cellText = GRID.slice(GRID.indexOf('function CellText'), GRID.indexOf('function CellImage'))

  test('still render through RichTextRenderer, unchanged', () => {
    assert.match(cellText, /<RichTextRenderer content=\{cell\.content\} \/>/)
  })

  test('still render nothing when empty', () => {
    assert.match(cellText, /if \(!cell\.content\?\.trim\(\)\) return null/)
  })
})

describe('the grid stays usable on the server', () => {
  test('ColumnsGrid is not a client component', () => {
    // BlockList renders inside a server component; adding 'use client'
    // here would pull the whole step render onto the client.
    assert.ok(!GRID.includes("'use client'"), "ColumnsGrid must not be a client component")
    assert.ok(!/\buseState\b|\buseEffect\b/.test(GRID), 'no hooks')
  })
})
