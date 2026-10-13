/**
 * The About editor must give its blocks what they need to upload.
 *
 * A creator clicked "Upload from your computer" inside an Image block
 * on a Pathway About page and nothing happened at all — no file picker,
 * no spinner, no error. The control was `disabled`, so no code ran.
 *
 * ``AboutPageEditor`` renders ``BlockRow`` directly. The Content editor
 * reaches the same component through ``DraggableBlockList``, which is
 * where ``spaceSlug`` and ``onAssetUploaded`` are threaded through — so
 * the About page never passed either. ``spaceSlug`` is optional on
 * every component in that chain, so nothing failed to compile; the
 * upload button and its hidden file input simply rendered disabled.
 *
 * These are source-contract tests. The project has no DOM renderer
 * (node:test only, no testing-library or jsdom), so what a component
 * commits to is asserted by reading its source. Comments are stripped
 * first: a prop named in a comment is not a prop that is passed, and
 * matching them would let an explanatory note satisfy the test.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

/**
 * Strip comments without touching code.
 *
 * The obvious three-regex version is wrong on this file. JSX contains
 * ``accept="image/*"``, and a naive block-comment rule reads that
 * ``/*`` as a comment opener and deletes everything up to the next
 * ``*\/`` — swallowing the very ``disabled={... !spaceSlug ...}``
 * lines these tests exist to check, and passing them for the wrong
 * reason. So this walks the source and ignores anything inside a
 * string, template or regex-ish literal.
 */
function codeOnly(src: string): string {
  let out = ''
  let i = 0
  let quote: string | null = null
  while (i < src.length) {
    const c = src[i]
    const next = src[i + 1]
    if (quote) {
      out += c
      if (c === '\\') { out += next ?? ''; i += 2; continue }
      if (c === quote) quote = null
      i += 1
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; out += c; i += 1; continue }
    if (c === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2)
      i = end === -1 ? src.length : end + 2
      continue
    }
    if (c === '/' && next === '/') {
      const end = src.indexOf('\n', i)
      i = end === -1 ? src.length : end
      continue
    }
    out += c
    i += 1
  }
  return out
}

const read = (p: string) => codeOnly(readFileSync(p, 'utf8'))

const ABOUT = read('src/app/creator-studio/pathways/[pathwaySlug]/AboutPageEditor.tsx')
const CONTENT = read(
  'src/app/creator-studio/pathways/[pathwaySlug]/steps/[stepSlug]/StepBlockEditor.tsx')
const LIST = read('src/components/creator/DraggableBlockList.tsx')
const SHARED = read('src/components/creator/BlockEditorShared.tsx')

/** The props on the single <BlockRow …> / <DraggableBlockList …> element. */
function elementProps(src: string, tag: string): string {
  const open = src.indexOf(`<${tag}`)
  assert.notEqual(open, -1, `no <${tag}> element found`)
  const end = src.indexOf('/>', open)
  assert.notEqual(end, -1, `<${tag}> element never closes`)
  return src.slice(open, end)
}

// ---------------------------------------------------------------------------
// 1 · The Collective slug reaches the block
// ---------------------------------------------------------------------------

describe('the About editor passes the Collective slug', () => {
  test('BlockRow receives spaceSlug', () => {
    assert.match(
      elementProps(ABOUT, 'BlockRow'),
      /spaceSlug=\{spaceSlug\}/,
      'BlockRow has no spaceSlug — the upload control renders disabled',
    )
  })

  test('the page has a slug to pass', () => {
    assert.match(ABOUT, /spaceSlug: string/)
  })
})

// ---------------------------------------------------------------------------
// 2 · Upload is enabled for Image AND Columns blocks
// ---------------------------------------------------------------------------

describe('uploads are enabled in both block types', () => {
  test('the upload button and its file input are gated on the same slug', () => {
    // Two independent locks: a disabled button fires no onClick, and a
    // disabled input ignores a programmatic .click(). Both must open.
    const gates = SHARED.match(/disabled=\{[^}]*!spaceSlug[^}]*\}/g) ?? []
    assert.ok(
      gates.length >= 2,
      `expected the button and the hidden input to be slug-gated, found ${gates.length}`,
    )
  })

  test('the Image block editor is handed the slug', () => {
    assert.match(SHARED, /<ImageBlockFields[\s\S]{0,600}?spaceSlug=\{spaceSlug\}/)
  })

  test('the Columns editor is handed the same slug and upload handler', () => {
    // Image cells inside Columns upload through the same path, so they
    // were broken in exactly the same way and are fixed by the same prop.
    const columns = SHARED.slice(SHARED.indexOf('onUploadFile={(file, onUploaded)'))
    assert.ok(columns.length > 0, 'the columns upload handler is gone')
    const before = SHARED.slice(0, SHARED.indexOf('onUploadFile={(file, onUploaded)'))
    assert.match(before.slice(-400), /spaceSlug=\{spaceSlug\}/)
  })
})

// ---------------------------------------------------------------------------
// 3 · A new upload appears without a refresh
// ---------------------------------------------------------------------------

describe('a newly uploaded asset appears immediately', () => {
  test('the About editor holds its assets in state', () => {
    assert.match(
      ABOUT,
      /const \[assets, setAssets\] = useState<CreatorMediaAsset\[\]>\(mediaAssets\)/,
      'assets are read straight from the prop, so an upload needs a reload',
    )
  })

  test('the block list renders that state, not the raw prop', () => {
    const props = elementProps(ABOUT, 'BlockRow')
    assert.match(props, /assets=\{assets\}/)
    assert.ok(
      !/assets=\{mediaAssets\}/.test(props),
      'still rendering the static prop',
    )
  })

  test('an upload is prepended to the list', () => {
    assert.match(
      elementProps(ABOUT, 'BlockRow'),
      /onAssetUploaded=\{\(asset\) => setAssets\(\(prev\) => \[asset, \.\.\.prev\]\)\}/,
    )
  })
})

// ---------------------------------------------------------------------------
// 4 · The Content editor is unchanged, and the two now agree
// ---------------------------------------------------------------------------

describe('the Content editor keeps working', () => {
  test('it still passes both props through DraggableBlockList', () => {
    const props = elementProps(CONTENT, 'DraggableBlockList')
    assert.match(props, /spaceSlug=\{spaceSlug\}/)
    assert.match(props, /onAssetUploaded=\{/)
    assert.match(props, /assets=\{assets\}/)
  })

  test('it still holds assets in state', () => {
    assert.match(CONTENT, /const \[assets, setAssets\] = useState<CreatorMediaAsset\[\]>/)
  })

  test('DraggableBlockList still forwards both to BlockRow', () => {
    const props = elementProps(LIST, 'BlockRow')
    assert.match(props, /spaceSlug=\{spaceSlug\}/)
    assert.match(props, /onAssetUploaded=\{onAssetUploaded\}/)
  })

  test('both editors now give a block the same upload props', () => {
    // The divergence was the bug. Pin the agreement rather than each
    // side separately, so they cannot drift apart again.
    for (const prop of ['spaceSlug', 'onAssetUploaded']) {
      assert.match(elementProps(ABOUT, 'BlockRow'), new RegExp(`${prop}=\\{`), `About: ${prop}`)
      assert.match(
        elementProps(CONTENT, 'DraggableBlockList'),
        new RegExp(`${prop}=\\{`),
        `Content: ${prop}`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// 5 · Every consumer of the block primitives, now and later
// ---------------------------------------------------------------------------

describe('no block-list call site omits the slug', () => {
  test('every BlockRow / DraggableBlockList element passes spaceSlug', () => {
    // The guard that would have caught this. It also covers the Series
    // and Event About pages, which render through AboutPageEditor and
    // were broken by the same omission.
    const callSites = [
      ['AboutPageEditor', ABOUT, 'BlockRow'],
      ['StepBlockEditor', CONTENT, 'DraggableBlockList'],
      ['DraggableBlockList', LIST, 'BlockRow'],
    ] as const
    for (const [name, src, tag] of callSites) {
      assert.match(
        elementProps(src, tag),
        /spaceSlug=\{/,
        `${name} renders <${tag}> without spaceSlug — uploads will be disabled there`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// 6 · Saving is untouched
// ---------------------------------------------------------------------------

describe('About page saving is unchanged', () => {
  test('the blocks endpoint is still resolved the same way', () => {
    assert.match(ABOUT, /blocksApiUrl \?\? apiUrl\(/)
    assert.match(ABOUT, /about-blocks/)
  })

  test('blocks are still held separately from assets', () => {
    assert.match(ABOUT, /const \[blocks, setBlocks\] = useState<PathwayAboutBlock\[\]>\(initialBlocks\)/)
  })
})

// ---------------------------------------------------------------------------
// 7 · The stripper itself
//
// Every assertion above reads stripped source, so a wrong stripper
// makes all of them unreliable — and the first version of it was
// wrong in exactly the direction that passes tests by deleting the
// code under test.
// ---------------------------------------------------------------------------

describe('codeOnly strips comments without eating code', () => {
  test('a JSX string containing /* is not read as a comment opener', () => {
    const src = 'const a = <input accept="image/*" />\nconst keep = true\n'
    assert.match(codeOnly(src), /accept="image\/\*"/)
    assert.match(codeOnly(src), /const keep = true/)
  })

  test('real block and line comments go', () => {
    assert.ok(!codeOnly('/* gone */ const a = 1').includes('gone'))
    assert.ok(!codeOnly('const a = 1 // gone').includes('gone'))
    assert.ok(!codeOnly('{/* gone */}\nconst a = 1').includes('gone'))
  })

  test('code survives alongside them', () => {
    const out = codeOnly('/* c */ const a = 1 // c\nconst b = 2')
    assert.match(out, /const a = 1/)
    assert.match(out, /const b = 2/)
  })

  test('a URL in a string keeps its slashes', () => {
    assert.match(codeOnly(`const u = 'https://example.test/a'`), /https:\/\/example\.test\/a/)
  })

  test('the real file keeps its slug gates', () => {
    // The regression the first stripper caused: zero matches here.
    const gates = SHARED.match(/disabled=\{[^}]*!spaceSlug[^}]*\}/g) ?? []
    assert.equal(gates.length, 2, 'the slug gates vanished from the stripped source')
  })
})
