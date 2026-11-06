import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * `pathway_step_blocks.label` is VARCHAR(300), and two of the editor's
 * label inputs did not say so.
 *
 * Found while fixing FC-API-M, which was the identical shape one column
 * over: `caption` at VARCHAR(500) with no API-level length rule and no
 * `maxLength` in the editor, so the column was the only limit and a
 * too-long paste returned HTTP 500 rather than a validation message.
 *
 * `label` keeps its 300 — unlike `caption`, a download button's text
 * and a link's visible text genuinely are label-sized, so the right
 * correction is for the control to agree with the column rather than
 * for the column to grow.
 *
 * Asserted against source: these are React components and the harness
 * is node:test with no DOM. Comment-stripped for absence checks,
 * because the new comments mention both 300 and FC-API-M.
 */

const EDITOR = join(
  process.cwd(), 'src', 'components', 'creator', 'BlockEditorShared.tsx',
)

/** Source with comments removed, so a check reads the code. */
function code(): string {
  return readFileSync(EDITOR, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

/** The JSX of one block type's branch, up to the next branch. */
function branch(blockType: string): string {
  const src = code()
  const start = src.indexOf(`{t === '${blockType}' && (`)
  assert.ok(start > 0, `no editor branch for ${blockType}`)
  const next = src.indexOf("{t === '", start + 10)
  return src.slice(start, next > start ? next : start + 4000)
}

/** The `<input>` element inside `scope` bound to `binding`. */
function inputBoundTo(scope: string, binding: string): string {
  const elements = [...scope.matchAll(/<input[\s\S]*?\/>/g)].map((m) => m[0])
  const found = elements.filter((el) => el.includes(binding))
  assert.equal(
    found.length, 1,
    `expected exactly one input bound to ${binding}, found ${found.length}`,
  )
  return found[0]
}

// ---------------------------------------------------------------------------

describe('the two uncapped label inputs now match their column', () => {
  it('the download button label caps at 300', () => {
    // Labelled "Button label (optional)", but it belongs to the
    // file_download block — it is the download button's text. The
    // `button` block's own text is a different control, covered below.
    const el = inputBoundTo(branch('file_download'), 'setLabel')
    assert.match(el, /maxLength=\{300\}/)
  })

  it('the link label caps at 300', () => {
    const el = inputBoundTo(branch('link'), 'setLabel')
    assert.match(el, /maxLength=\{300\}/)
  })

  it('and neither grew a different limit by accident', () => {
    // 300 exactly — the column's width. A larger number would still
    // 500; a smaller one would silently shorten what creators can
    // write.
    for (const t of ['file_download', 'link']) {
      const el = inputBoundTo(branch(t), 'setLabel')
      const caps = [...el.matchAll(/maxLength=\{(\d+)\}/g)].map((m) => m[1])
      assert.deepEqual(caps, ['300'], `${t}: ${caps}`)
    }
  })

  it('which is enforced on paste, not only on typing', () => {
    // `maxLength` on an input constrains pasted text too — that is the
    // reason it is the right control here rather than an onChange
    // guard, which would have to re-implement truncation and would be
    // the one thing we must not do to a creator's text.
    for (const t of ['file_download', 'link']) {
      const el = inputBoundTo(branch(t), 'setLabel')
      assert.match(el, /maxLength=/)
      assert.ok(
        !/slice\(0,\s*300\)|substring\(/.test(el),
        `${t}: the control truncates in JS instead of declining input`,
      )
    }
  })
})

describe('the styling and behaviour are otherwise untouched', () => {
  it('both keep the shared field styling', () => {
    for (const t of ['file_download', 'link']) {
      const el = inputBoundTo(branch(t), 'setLabel')
      assert.match(el, /className="field-input"/)
    }
  })

  it('both keep their placeholders and their setter', () => {
    const dl = inputBoundTo(branch('file_download'), 'setLabel')
    assert.match(dl, /placeholder="Download workbook"/)
    assert.match(dl, /value=\{label\}/)

    const link = inputBoundTo(branch('link'), 'setLabel')
    assert.match(link, /placeholder="Visit resource"/)
    assert.match(link, /value=\{label\}/)
  })

  it('and neither became a textarea', () => {
    // Unlike `caption`, these are labels. The control type is right;
    // only the missing limit was wrong.
    for (const t of ['file_download', 'link']) {
      const el = inputBoundTo(branch(t), 'setLabel')
      assert.match(el, /^<input/)
    }
  })
})

describe('the label controls that already had limits still do', () => {
  it('the three media heading inputs keep maxLength 300', () => {
    // These bind to `heading`, which is its own VARCHAR(300) column.
    // They were already correct and are the precedent this change
    // follows.
    const src = code()
    const headingInputs = [...src.matchAll(/<input[\s\S]*?\/>/g)]
      .map((m) => m[0])
      .filter((el) => el.includes('value={heading}'))
    assert.equal(headingInputs.length, 3, 'expected three heading inputs')
    for (const el of headingInputs) {
      assert.match(el, /maxLength=\{300\}/)
    }
  })

  it('the button block text keeps its own tighter limit of 80', () => {
    // The `button` block routes to ButtonFields, where the visible
    // text is deliberately capped far below the column — a button
    // with 300 characters on it is not a button. Not widened to 300
    // just for consistency.
    const src = code()
    assert.match(src, /maxLength=\{80\}/)
    const i = src.indexOf('maxLength={80}')
    const el = src.slice(Math.max(0, i - 400), i + 20)
    assert.match(el, /value=\{text\}/)
  })

  it('every maxLength in the editor is now 300 or the button 80', () => {
    // A cheap guard against a stray limit appearing somewhere that
    // does not match a column.
    const caps = [...code().matchAll(/maxLength=\{(\d+)\}/g)].map((m) => m[1])
    assert.deepEqual(caps.sort(), ['300', '300', '300', '300', '300', '80'].sort())
  })
})

describe('nothing else about label handling changed', () => {
  it('the picker-driven label writers are untouched', () => {
    // `label` is overloaded: it carries the heading level on a heading
    // block, the palette key on a callout, and the alt text on an
    // image. None of those is a free-text label input and none should
    // have gained a limit.
    const src = code()
    assert.match(src, /setLabel\(`h\$\{idx \+ 1\}`\)/)
    assert.match(src, /setLabel\(p\.key\)/)
    assert.match(src, /onAltTextChange=\{setLabel\}/)
  })

  it('and the caption control is still the textarea FC-API-M made it', () => {
    const src = code()
    const i = src.indexOf('function CaptionField')
    assert.ok(i > 0, 'CaptionField is gone')
    const body = src.slice(i, i + 1600)
    assert.match(body, /<textarea/)
    assert.ok(!/maxLength/.test(body), 'the caption control gained a limit')
  })
})
