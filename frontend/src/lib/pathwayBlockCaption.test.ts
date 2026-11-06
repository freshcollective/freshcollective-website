import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

/**
 * FC-API-M — the caption editor, and what a long caption looks like to
 * a reader.
 *
 * The database half of this fix is covered by
 * `backend/tests/test_pathway_block_caption_length.py`. What only the
 * frontend can answer is whether a creator is given somewhere to write
 * a paragraph, and whether the paragraph they wrote survives being
 * rendered.
 *
 * Asserted against source, for the reason the other creator-surface
 * tests give: these are React components and the harness is node:test
 * with no DOM. Absence checks read comment-stripped source — the
 * component's own docstring describes the single-line `<input>` it
 * replaced and the 500-character column it outgrew, so a blunt search
 * would find both and prove nothing.
 */

const SRC = join(process.cwd(), 'src')
const EDITOR = join(SRC, 'components', 'creator', 'BlockEditorShared.tsx')
const BLOCK_LIST = join(SRC, 'components', 'spaces', 'BlockList.tsx')

const read = (p: string) => readFileSync(p, 'utf8')

/** Source with comments removed, so an absence check reads the code. */
function code(p: string): string {
  return read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

/** The JSX of one `<CaptionField … />` call, by its id. */
function captionField(id: string): string {
  const src = code(EDITOR)
  const i = src.indexOf(`id="block-caption-${id}"`)
  assert.ok(i > 0, `no caption field for ${id}`)
  const open = src.lastIndexOf('<CaptionField', i)
  const close = src.indexOf('/>', i)
  assert.ok(open > 0 && close > i, `malformed caption field for ${id}`)
  return src.slice(open, close + 2)
}

// ---------------------------------------------------------------------------

describe('the caption control is built for paragraphs', () => {
  it('is a textarea, not a single-line field', () => {
    const src = code(EDITOR)
    const i = src.indexOf('function CaptionField')
    assert.ok(i > 0, 'CaptionField is gone')
    const body = src.slice(i, i + 1600)
    assert.match(body, /<textarea/)
    assert.ok(!/<input/.test(body), 'CaptionField renders an input')
  })

  it('imposes no character limit of its own', () => {
    // The whole defect was a limit nobody could see. Re-adding one in
    // the editor would reproduce it with a nicer error.
    const src = code(EDITOR)
    const i = src.indexOf('function CaptionField')
    const body = src.slice(i, i + 1600)
    assert.ok(!/maxLength/.test(body), 'the caption control caps its length')
  })

  it('grows with its content, from a compact floor', () => {
    const src = code(EDITOR)
    assert.match(src, /const CAPTION_MIN_HEIGHT_PX = \d+/)
    const i = src.indexOf('function CaptionField')
    const body = src.slice(i, i + 1600)
    // The autosizing pattern the reflection-prompt editor already uses.
    assert.match(body, /style\.height = 'auto'/)
    assert.match(body, /scrollHeight/)
    assert.match(body, /CAPTION_MIN_HEIGHT_PX/)
  })

  it('can still be resized by hand', () => {
    // A transcript is longer than any sensible automatic ceiling.
    const src = code(EDITOR)
    const i = src.indexOf('function CaptionField')
    assert.match(src.slice(i, i + 1600), /resize: 'vertical'/)
  })

  it('is labelled for assistive technology', () => {
    const src = code(EDITOR)
    const i = src.indexOf('function CaptionField')
    const body = src.slice(i, i + 1600)
    assert.match(body, /htmlFor=\{id\}/)
    assert.match(body, /id=\{id\}/)
  })

  it('uses the shared field styling rather than a one-off', () => {
    const src = code(EDITOR)
    const i = src.indexOf('function CaptionField')
    assert.match(src.slice(i, i + 1600), /className="field-input"/)
  })

  it('is plain text — no rich-text editor was introduced', () => {
    const src = code(EDITOR)
    const i = src.indexOf('function CaptionField')
    const body = src.slice(i, i + 1600)
    for (const banned of ['contentEditable', 'RichText', 'TipTap', 'Quill']) {
      assert.ok(!body.includes(banned), `${banned} in the caption control`)
    }
  })
})

describe('every free-text caption uses it', () => {
  // `caption` is shared across block types, so a conversion that
  // covered only the audio block would leave the same cramped control
  // on five other editors.
  for (const id of ['audio', 'video', 'image', 'link', 'embed', 'resource']) {
    it(`the ${id} block`, () => {
      const field = captionField(id)
      assert.match(field, /<CaptionField/)
      assert.match(field, /value=\{/)
      assert.match(field, /onChange=\{/)
    })
  }

  it('and no caption is edited through a single-line input', () => {
    // Narrowed to the control type rather than the handler shape: the
    // reflection prompt keeps the inline `onChange` form on its own
    // `<textarea>`, which is correct. What must be gone is any
    // `<input>` writing a caption.
    const src = code(EDITOR)
    const offenders: string[] = []
    for (const match of src.matchAll(/<input[\s\S]{0,400}?\/>/g)) {
      const el = match[0]
      if (/setCaption|onCaptionChange|onDescriptionOverrideChange/.test(el)) {
        offenders.push(el.replace(/\s+/g, ' ').slice(0, 90))
      }
    }
    assert.deepEqual(offenders, [])
  })

  it('the reflection prompt context is multiline too', () => {
    // Keeps its own styling — that editor is deliberately its own
    // visual thing — but it is still free text in the same column.
    const src = code(EDITOR)
    const i = src.indexOf('Supporting context')
    assert.ok(i > 0, 'the supporting-context field is gone')
    const block = src.slice(i, i + 700)
    assert.match(block, /<textarea/)
    assert.ok(!/<input/.test(block), 'supporting context is still an input')
    assert.match(block, /resize-y/)
  })
})

describe('the controls that merely share the column are untouched', () => {
  it('a callout keeps its palette picker', () => {
    // `caption` carries the palette token on a callout. A textarea
    // there would be the wrong control and a way to corrupt it.
    const src = code(EDITOR)
    assert.match(src, /resolveCalloutPalette\(/)
    assert.ok(
      !src.includes('id="block-caption-callout"'),
      'the callout palette became a caption textarea',
    )
  })

  it('a button keeps its encoded style', () => {
    const src = code(EDITOR)
    assert.match(src, /encodeButtonCaption\(/)
    assert.match(src, /parseButtonCaption\(/)
    assert.ok(
      !src.includes('id="block-caption-button"'),
      'the button style became a caption textarea',
    )
  })
})

describe('the other block controls still work', () => {
  it('media headings keep their own cap, matching their column', () => {
    // `heading` is VARCHAR(300) and the editor says so. Unchanged —
    // this fix is about `caption`.
    const src = code(EDITOR)
    assert.ok(
      (src.match(/maxLength=\{300\}/g) ?? []).length >= 3,
      'the heading inputs lost their limit',
    )
  })

  it('the media pickers are untouched', () => {
    const src = code(EDITOR)
    assert.match(src, /<MediaPicker/)
    assert.match(src, /accept=\{\['audio'\]\}/)
  })

  it('the coloured container control is untouched', () => {
    const src = read(EDITOR)
    assert.match(src, /container_style|containerStyle/)
    assert.match(src, /CollectivePaletteColourPicker/)
  })
})

describe('a long caption reads correctly and does not break the page', () => {
  it('member-facing captions preserve the line breaks as written', () => {
    // `pre-wrap` rather than `pre-line`, matching what this file
    // already does for block content and the reflection context: it
    // preserves pasted indentation as well as newlines, and still
    // wraps long lines normally.
    const src = read(BLOCK_LIST)
    const captionLines = src
      .split('\n')
      .filter((l) => l.includes('block.caption') && l.includes('className'))
    assert.ok(captionLines.length >= 3, 'no caption renderers found')
    for (const line of captionLines) {
      assert.ok(
        /whitespace-pre-line|whitespace-pre-wrap/.test(line),
        `a caption renderer collapses line breaks: ${line.trim()}`,
      )
    }
  })

  it('and wrap rather than pushing the page sideways', () => {
    const src = read(BLOCK_LIST)
    const captionLines = src
      .split('\n')
      .filter((l) => l.includes('block.caption') && l.includes('whitespace-pre-wrap'))
    for (const line of captionLines) {
      assert.match(line, /break-words/)
    }
  })

  it('the editor preview shows what the reader will see', () => {
    // Creator and member must not disagree about whether a line break
    // is a line break. Prose contexts only — a `<figcaption>` or a
    // `<p>`. The collapsed summary rows are covered separately below.
    // Matched as elements, not lines: the figcaption form wraps across
    // four lines, so its className and its `{block.caption}` are never
    // on the same one.
    const src = read(EDITOR)
    const elements = [
      ...src.matchAll(/<(figcaption|p)\s[^>]*>[\s\S]{0,120}?<\/\1>/g),
    ]
      .map((m) => m[0])
      .filter((el) => el.includes('block.caption'))
    assert.ok(elements.length >= 2, 'no caption previews found')
    for (const el of elements) {
      assert.ok(
        /whitespace-pre-wrap/.test(el),
        `a preview collapses line breaks: ${el.replace(/\s+/g, ' ').slice(0, 90)}`,
      )
    }
  })

  it('and a collapsed summary row truncates instead of growing', () => {
    // A caption is now potentially a transcript. The one-line block
    // summary in the editor list must not become its height.
    const src = read(EDITOR)
    const summaries = src
      .split('\n')
      .filter((l) => l.includes('· {block.caption}'))
    assert.ok(summaries.length >= 1, 'no summary row found')
    for (const line of summaries) {
      assert.match(line, /truncate/)
    }
  })

  it('captions are rendered as text, never as markup', () => {
    const src = code(BLOCK_LIST)
    assert.ok(
      !/dangerouslySetInnerHTML[^}]*caption/.test(src),
      'a caption is being rendered as HTML',
    )
  })

  it('the control is full-width, so it works on a phone', () => {
    const src = code(EDITOR)
    const i = src.indexOf('function CaptionField')
    const body = src.slice(i, i + 1600)
    // `field-input` is width:100%; what must not appear is a fixed size.
    assert.ok(!/\bw-\[\d+px\]/.test(body))
    assert.ok(!/cols=/.test(body), 'a fixed column count breaks narrow screens')
  })
})
