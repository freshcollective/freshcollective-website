import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const CSS = readFileSync(join(root, 'app/globals.css'), 'utf8')
const GRID = readFileSync(join(root, 'components/spaces/ColumnsGrid.tsx'), 'utf8')
const EDITOR = readFileSync(join(root, 'components/creator/BlockEditorShared.tsx'), 'utf8')

/**
 * When columns stop stacking, by column count.
 *
 * A single 640px breakpoint was fine while columns held only text in
 * two halves. It is not fine for four columns: 640px gives each one
 * about 150px, which is too narrow to read a sentence in and too small
 * to show a picture. Three columns now wait for 768px and four for
 * 900px, which is roughly where each clears 200px.
 *
 * These assertions are the rules, not the rendering. The rendering was
 * measured in headless Chromium against the built stylesheet at 375,
 * 640, 767, 768, 899, 900, 1024, 1280 and 1440px: the flips land
 * exactly between 767 and 768 and between 899 and 900, no width
 * produces horizontal document overflow, and images hold their
 * intrinsic aspect ratio (2.000 for an 800x400 source) at every width.
 * What a unit test can protect is that the rules stay in the
 * stylesheet, that they stay unlayered, and that every surface keeps
 * emitting the attribute they key off.
 */

/** The declaration block of the first `@media (min-width: Npx)` whose
 *  body mentions `needle`. */
function mediaBlockFor(minWidth: number, needle: string): string {
  const open = `@media (min-width: ${minWidth}px) {`
  let from = -1
  for (let i = CSS.indexOf(open); i !== -1; i = CSS.indexOf(open, i + 1)) {
    const end = CSS.indexOf('\n}', i)
    if (CSS.slice(i, end).includes(needle)) { from = i; break }
  }
  assert.notEqual(from, -1, `no @media (min-width: ${minWidth}px) containing ${needle}`)
  return CSS.slice(from, CSS.indexOf('\n}', from))
}

describe('the stacking breakpoints', () => {
  test('a grid with no column count keeps the original 640px behaviour', () => {
    // Nothing should rely on this now, but it is the safe default for
    // any caller that forgets the attribute.
    const at640 = mediaBlockFor(640, '.fc-columns-grid {')
    assert.match(at640, /\.fc-columns-grid \{\s*grid-template-columns: var\(--fc-cols, 1fr 1fr\);/)
  })

  test('two columns still go side by side at 640px', () => {
    // Explicitly unchanged: this is the common case and the brief asked
    // for no unnecessary movement here.
    const at640 = mediaBlockFor(640, '.fc-columns-grid {')
    assert.ok(!at640.includes('[data-cols="2"]'), 'two columns need no special rule')
  })

  test('three and four columns are held back past 640px', () => {
    const at640 = mediaBlockFor(640, '[data-cols="3"]')
    assert.match(
      at640,
      /\.fc-columns-grid\[data-cols="3"\],\s*\.fc-columns-grid\[data-cols="4"\] \{\s*grid-template-columns: 1fr;/,
    )
  })

  test('three columns arrive at 768px', () => {
    const at768 = mediaBlockFor(768, '[data-cols="3"]')
    assert.match(
      at768,
      /\.fc-columns-grid\[data-cols="3"\] \{\s*grid-template-columns: var\(--fc-cols, 1fr 1fr 1fr\);/,
    )
    assert.ok(!at768.includes('[data-cols="4"]'), 'four columns must not arrive at 768')
  })

  test('four columns arrive at 900px', () => {
    const at900 = mediaBlockFor(900, '[data-cols="4"]')
    assert.match(
      at900,
      /\.fc-columns-grid\[data-cols="4"\] \{\s*grid-template-columns: var\(--fc-cols, 1fr 1fr 1fr 1fr\);/,
    )
  })

  test('the later rules come after the 640px hold-back so they win', () => {
    // Same specificity, so source order decides. If these were
    // reordered, three and four columns would never unstack.
    const holdBack = CSS.indexOf('Held back past the point')
    const at768 = CSS.indexOf('@media (min-width: 768px)')
    const at900 = CSS.indexOf('@media (min-width: 900px)')
    assert.ok(holdBack > 0 && at768 > holdBack, '768px rule must follow the hold-back')
    assert.ok(at900 > at768, '900px rule must follow the 768px rule')
  })

  test('the rules stay unlayered', () => {
    // Tailwind's utilities live in @layer utilities, so an unlayered
    // rule wins regardless of specificity. Moving these into a layer
    // would silently hand the grid back to whatever utility class is
    // on the element.
    const start = CSS.indexOf('.fc-columns-grid {')
    const layerBefore = CSS.lastIndexOf('@layer', start)
    if (layerBefore !== -1) {
      // There must be a closing brace between that layer and our rule.
      const between = CSS.slice(layerBefore, start)
      assert.ok(between.includes('\n}'), 'columns rules appear to sit inside an @layer')
    }
  })
})

describe('every surface emits the column count', () => {
  test('the member renderers do, through the shared grid', () => {
    assert.match(GRID, /data-cols=\{cellCountForVariant\(variant\)\}/)
  })

  test('the Creator Studio preview does, so it stacks where the page stacks', () => {
    const preview = EDITOR.slice(
      EDITOR.indexOf('function ColumnsPreview'),
      EDITOR.indexOf('function ColumnsEditor'),
    )
    assert.match(preview, /data-cols=\{cellCountForVariant\(variant\)\}/)
  })

  test('the editor does for its text-only side-by-side grid', () => {
    const editor = EDITOR.slice(EDITOR.indexOf('function ColumnsEditor'))
    assert.match(editor, /data-cols=\{anyImage \? undefined : cellCountForVariant\(/)
  })
})

describe('stacked columns stay usable', () => {
  test('the grid keeps a gap, so stacked cells do not touch', () => {
    // When the grid collapses to one column the same gap becomes the
    // vertical rhythm between cells.
    assert.match(GRID, /'fc-columns-grid grid items-start gap-6'/)
  })

  test('cells cannot be forced wider than their track', () => {
    // min-w-0 is what stops a long word or a wide image from pushing
    // the grid past the viewport.
    assert.match(GRID, /\['min-w-0', cellClassName\]/)
  })

  test('images scale to the column rather than their intrinsic size', () => {
    assert.match(GRID, /className="h-auto w-full rounded-xl/)
  })
})
