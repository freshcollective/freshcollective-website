import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(root, p), 'utf8')

const EDITOR = read('components/creator/BlockEditorShared.tsx')
const STEP = read('components/spaces/BlockList.tsx')
const ABOUT = read('components/spaces/AboutBlockRenderer.tsx')
const PICKER = read('components/creator/CollectivePaletteColourPicker.tsx')
const RESPONSE = read('components/spaces/PrivateResponseArea.tsx')

/** The eligible block types, read out of the source.
 *
 *  BlockEditorShared is a .tsx client component, which node's
 *  type-stripping cannot import, so the set is parsed rather than
 *  imported. Parsing keeps the assertion exact — it is the real
 *  literal, not a restatement of it. */
const CONTAINER_STYLE_BLOCK_TYPES: ReadonlySet<string> = (() => {
  const m = EDITOR.match(
    /CONTAINER_STYLE_BLOCK_TYPES: ReadonlySet<StepBlockType> = new Set\(\[([\s\S]*?)\]\)/,
  )
  assert.ok(m, 'could not find the eligible block type set')
  return new Set(
    [...m[1].matchAll(/'([a-z_]+)'/g)].map((x) => x[1]),
  )
})()

/** Source with comments stripped, so assertions about what the code
 *  DOES are not satisfied or broken by prose explaining what it did. */
function codeOnly(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .split('\n').map((l) => l.replace(/\/\/.*$/, '')).join('\n')
}

function branch(src: string, from: string, to: string): string {
  const a = src.indexOf(from)
  assert.ok(a > 0, `anchor not found: ${from}`)
  const b = src.indexOf(to, a)
  assert.ok(b > a, `end anchor not found: ${to}`)
  return src.slice(a, b)
}

/**
 * Container styling for Exercise blocks.
 *
 * This was never a regression. ``exercise`` had simply never been in
 * CONTAINER_STYLE_BLOCK_TYPES — the set has existed in one form since
 * the platform consolidation, and the Exercise Response Areas work did
 * not touch it. What made it look like one is that everything *except*
 * the editor control was already in place: both member renderers read
 * ``container_style`` on exercise rows and drop the block's own white
 * plate when one is set, and rows with a style saved exist.
 *
 * Which also means the renderers had a latent hole. The step renderer
 * dropped its plate and never called ``withContainer``, so nothing
 * arrived in its place and such a row rendered as bare text. These
 * tests pin the two halves together: a block type that may be tinted
 * must also be a block type that gets a wrapper.
 */

describe('eligibility', () => {
  test('exercise may take a container style', () => {
    assert.ok(CONTAINER_STYLE_BLOCK_TYPES.has('exercise'))
  })

  test('the block types that already had it still do', () => {
    for (const t of ['text', 'video_embed', 'audio', 'embed', 'file_download', 'resource'] as const) {
      assert.ok(CONTAINER_STYLE_BLOCK_TYPES.has(t), t)
    }
  })

  test('the block types that own their own colour are still excluded', () => {
    // callout has a colour + purpose palette, reflection_prompt a
    // journal-quote treatment, image and button their own controls.
    // Adding a generic tint there would double up the choice.
    for (const t of ['callout', 'reflection_prompt', 'image', 'button', 'divider', 'heading', 'link'] as const) {
      assert.ok(!CONTAINER_STYLE_BLOCK_TYPES.has(t), t)
    }
  })

  test('the set is exactly the seven intended types', () => {
    assert.equal(CONTAINER_STYLE_BLOCK_TYPES.size, 7)
  })
})


describe('the creator control', () => {
  test('the exercise editor gets the shared field, not a new picker', () => {
    // One gate, one field. If exercise ever needed its own, this test
    // should be the thing that has to be deleted.
    assert.match(EDITOR, /const supportsContainerStyle = CONTAINER_STYLE_BLOCK_TYPES\.has\(t\)/)
    assert.match(EDITOR, /\{supportsContainerStyle && \(\s*<ContainerStyleField value=\{containerStyle\} onChange=\{setContainerStyle\} \/>/)
    assert.equal((EDITOR.match(/<ContainerStyleField/g) ?? []).length, 1, 'only one render site')
  })

  test('it reuses the collective palette picker', () => {
    const field = branch(EDITOR, 'function ContainerStyleField', 'function EmbedFields')
    assert.match(field, /<CollectivePaletteColourPicker/)
    assert.match(field, /allowClear/)                       // remove a colour
    assert.match(field, /label="Your palette"/)
    assert.match(field, /Container style <span className="text-black">\(optional\)<\/span>/)
    assert.match(field, /Wraps this block in a soft-coloured box on the member page\./)
  })

  test('"More colours…" comes with it', () => {
    assert.match(PICKER, /More colours…/)
    assert.match(PICKER, /type="color"/)
  })

  test('the control sits after Member response and before the actions', () => {
    const toggle = EDITOR.indexOf('Allow members to write a response')
    const field = EDITOR.indexOf('{supportsContainerStyle && (')
    const actions = EDITOR.indexOf('onDeleteRequested && (', field)
    assert.ok(toggle > 0 && field > toggle, 'container style must follow the response toggle')
    assert.ok(actions > field, 'and precede Delete / Save / Cancel')
  })
})


describe('both settings are kept, and kept apart', () => {
  const form = codeOnly(EDITOR.slice(EDITOR.indexOf('export function BlockEditForm')))

  test('they are separate pieces of state', () => {
    assert.match(form, /const \[containerStyle, setContainerStyle\] = useState<string \| null>\(block\.container_style \?\? null\)/)
    assert.match(form, /const \[responseEnabled, setResponseEnabled\] = useState/)
  })

  test('a save carries both, so neither resets the other', () => {
    const patch = branch(form, 'function buildPatch', '\n  }')
    assert.match(patch, /\.\.\.\(t === 'exercise' \? \{ response_enabled: responseEnabled \} : \{\}\)/)
    assert.match(patch, /container_style: isImage/)
  })

  test('an exercise save no longer writes container_style away to null', () => {
    // buildPatch sends ``supportsContainerStyle ? containerStyle : null``.
    // While exercise was outside the set that read as a hard null, so
    // editing an exercise row that already had a style would have
    // silently cleared it.
    assert.ok(CONTAINER_STYLE_BLOCK_TYPES.has('exercise'))
    const patch = branch(form, 'function buildPatch', '\n  }')
    assert.match(patch, /\(supportsContainerStyle \? containerStyle : null\)/)
  })

  test('autosave fires for a change to either one', () => {
    const deps = form.slice(form.indexOf('autosaveTimer.current = setTimeout'))
    assert.match(deps, /\}, \[content, label, caption, heading, responseEnabled, embedUrl, mediaAssetId, resourceId, containerStyle, imageAltUnset\]\)/)
  })
})


describe('the member step renderer', () => {
  const ex = branch(STEP, "if (t === 'exercise' && block.content)", "if (t === 'callout'")

  test('wraps the exercise in the chosen container', () => {
    // The fix. Without this the branch dropped its plate and got
    // nothing back.
    assert.match(ex, /return withContainer\(/)
    assert.match(ex, /<\/div>,\s*block, id,\s*\)/)
  })

  test('drops its own plate when a container is supplying one', () => {
    assert.match(ex, /className=\{wrapped \? '' : 'my-6 rounded-xl border border-slate-200 bg-white px-6 py-5'\}/)
  })

  test('with no colour chosen the plate is exactly what it was', () => {
    assert.match(ex, /'my-6 rounded-xl border border-slate-200 bg-white px-6 py-5'/)
  })

  test('no longer sets its own key, since the wrapper does', () => {
    assert.ok(!/key=\{id\}/.test(ex), 'a duplicate key would fight withContainer')
  })

  test('the response area still sits inside the card, on the same conditions', () => {
    assert.match(ex, /\{exerciseContext && block\.response_enabled !== false && \(/)
    assert.match(ex, /<ExerciseResponse/)
    assert.match(ex, /blockId=\{id\}/)
  })

  test('the label, title and body still render', () => {
    assert.match(ex, /Exercise\s*<\/p>/)
    assert.match(ex, /\{block\.label && \(/)
    assert.match(ex, /\{body && <RichTextRenderer content=\{body\} \/>\}/)
  })
})


describe('the other two surfaces', () => {
  test('the About renderer already wraps generically, and drops its plate', () => {
    assert.match(ABOUT, /const palette = resolveContainerPalette\(block\.container_style, collectivePalette\)/)
    assert.match(ABOUT, /if \(!palette\) return inner/)
    const ex = branch(ABOUT, "if (t === 'exercise')", '\n  if (t ===')
    assert.match(ex, /className=\{wrapped \? '' : 'rounded-xl border border-slate-200 bg-white px-5 py-4'\}/)
  })

  test('the preview wraps generically too', () => {
    const preview = branch(EDITOR, 'export function BlockPreview', 'function renderBlockPreviewInner')
    assert.match(preview, /const palette = resolveContainerPalette\(block\.container_style, collectivePalette\)/)
    assert.match(preview, /if \(!palette\) return inner/)
  })

  test('the preview drops its plate when tinted, so it matches the page', () => {
    // Otherwise the preview shows a card inside a tinted box while the
    // member sees a single tinted box.
    const ex = branch(EDITOR, '// ── Exercise — a warm plate with a serif title', '// ── Callout')
    assert.match(ex, /const wrapped = !!resolveContainerPalette\(block\.container_style, collectivePalette\)/)
    assert.match(ex, /className=\{wrapped \? '' : 'my-6 rounded-xl border border-slate-200 bg-slate-50\/70 px-6 py-5'\}/)
  })

  test('the preview response area still cannot read or write a real response', () => {
    const ex = branch(EDITOR, '// ── Exercise — a warm plate with a serif title', '// ── Callout')
    assert.match(ex, /value=""/)
    assert.match(ex, /onSave=\{async \(\) => false\}/)
    assert.ok(!/fetch\(/.test(ex), 'the preview must not call the response endpoint')
  })
})


describe('the response area stays usable on a tinted card', () => {
  test('the textarea keeps its own white background', () => {
    // So it reads as an input against any palette colour behind it.
    assert.match(RESPONSE, /className="w-full resize-none rounded-xl border bg-white /)
  })

  test('privacy and save behaviour are untouched', () => {
    assert.match(RESPONSE, /Private to you/)
    assert.match(RESPONSE, /onSave: \(\) => Promise<boolean>/)
  })
})
