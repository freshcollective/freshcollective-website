import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * A response area inside Exercise blocks, and nowhere else.
 *
 * The interesting assertions here are about absence. An Exercise block
 * renders in three places — the Pathway step, the public About pages
 * and the Creator Studio preview — and only the first of those has an
 * authenticated member and a step to attach a response to. So the
 * tests that matter are the ones proving the other two cannot show an
 * interactive box, and that the preview cannot read or write real
 * member writing.
 *
 * That exclusion is structural rather than conditional:
 * ``renderBlocks`` only renders the area when it is handed an
 * ``ExerciseResponseContext``, and the only caller that passes one is
 * the step page. The Knowledge Guide passes nothing — it has no
 * reflection area of its own either — and ``AboutBlockRenderer`` is a
 * different component that never imports the response area at all.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const BLOCKLIST = 'components/spaces/BlockList.tsx'
const ABOUT = 'components/spaces/AboutBlockRenderer.tsx'
const PREVIEW = 'components/creator/BlockEditorShared.tsx'
const GUIDE = 'components/spaces/KnowledgeGuideView.tsx'
const AREA = 'components/spaces/PrivateResponseArea.tsx'
const EXERCISE = 'components/spaces/ExerciseResponse.tsx'
const STEP_PAGE = 'app/spaces/[slug]/pathways/[pathway-slug]/[step-slug]/page.tsx'

/** Source with comments stripped — the comments in these files discuss
 *  the surfaces that must *not* show the area, by name. */
function code(path: string): string {
  return read(path)
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('the response area renders inside the Exercise card', () => {
  test('the Pathway renderer renders it in the exercise branch', () => {
    const source = code(BLOCKLIST)
    const start = source.indexOf("if (t === 'exercise'")
    assert.ok(start !== -1, 'the exercise branch has moved')
    const branch = source.slice(start, source.indexOf("if (t === 'callout'", start))
    assert.match(branch, /<ExerciseResponse/)
  })

  test('it is inside the card, not a sibling block', () => {
    // The brief: instructions and answer should read as one activity.
    const source = code(BLOCKLIST)
    const start = source.indexOf("if (t === 'exercise'")
    const branch = source.slice(start, source.indexOf("if (t === 'callout'", start))
    // The component appears before the branch's closing </div>, i.e.
    // within the card that holds the instructions.
    assert.ok(
      branch.indexOf('<ExerciseResponse') < branch.lastIndexOf('</div>'),
      'the response area must sit inside the exercise card',
    )
  })

  test('each exercise gets its own textarea id', () => {
    // A step can hold several. A shared id would point every label at
    // the first box.
    assert.match(code(EXERCISE), /textareaId=\{`exercise-response-\$\{blockId\}`\}/)
  })

  test('the placeholder is the agreed wording', () => {
    assert.match(code(EXERCISE), /placeholder="Write your response here\.\.\."/)
  })

  test('it reuses the shared area rather than its own box', () => {
    const source = code(EXERCISE)
    assert.match(source, /import PrivateResponseArea/)
    assert.ok(!source.includes('<textarea'), 'must not build a second text area')
  })

  test('it uses the Collective palette for its divider', () => {
    assert.match(code(EXERCISE), /--fc-accent-line/)
    assert.match(code(AREA), /--fc-accent-line/)
    assert.match(code(AREA), /--fc-accent,/)
  })
})

describe('the area appears only where a member and a step exist', () => {
  test('renderBlocks requires a context to render it', () => {
    const source = code(BLOCKLIST)
    assert.match(source, /exerciseContext\?: ExerciseResponseContext/)
    // Both conditions: a context, and the creator not having opted out.
    assert.match(source, /exerciseContext && block\.response_enabled !== false/)
  })

  test('only the step page passes a context', () => {
    assert.match(code(STEP_PAGE), /renderBlocks\(blocks, collectivePalette, \{/)
    assert.match(code(STEP_PAGE), /stepSlug,/)
  })

  test('the Knowledge Guide passes none, so it stays unchanged', () => {
    const call = code(GUIDE).match(/renderBlocks\([^)]*\)/)
    assert.ok(call, 'the Knowledge Guide no longer renders blocks')
    assert.ok(
      !call[0].includes('{'),
      'the Knowledge Guide must not pass an exercise context in this round',
    )
  })

  test('the About renderer never imports the response area', () => {
    // Public pages: no authenticated member, no step. A different
    // component entirely, so there is nothing to gate.
    const source = code(ABOUT)
    assert.ok(!source.includes('ExerciseResponse'))
    assert.ok(!source.includes('PrivateResponseArea'))
  })

  test('About blocks cannot even carry the setting', () => {
    // The column exists only on pathway_step_blocks, and the shared
    // editor type makes it optional for exactly that reason.
    const types = read('types/platform.ts')
    const about = types.slice(
      types.indexOf('export interface PathwayAboutBlock {'),
      types.indexOf('\n}', types.indexOf('export interface PathwayAboutBlock {')),
    )
    assert.ok(!about.includes('response_enabled'))
  })
})

describe('the Creator Studio preview shows it without touching real data', () => {
  test('the preview renders a read-only area', () => {
    const source = code(PREVIEW)
    const start = source.indexOf("if (t === 'exercise')")
    assert.ok(start !== -1)
    const branch = source.slice(start, start + 2600)
    assert.match(branch, /<PrivateResponseArea/)
    assert.match(branch, /readOnly/)
  })

  test('the preview cannot save', () => {
    const source = code(PREVIEW)
    const start = source.indexOf("if (t === 'exercise')")
    const branch = source.slice(start, start + 2600)
    // Resolves false without a request, so nothing is created and the
    // member-facing failure path is never mistaken for a real save.
    assert.match(branch, /onSave=\{async \(\) => false\}/)
    assert.match(branch, /value=""/)
  })

  test('the preview never fetches a response', () => {
    // It imports the presentational component, not the fetching one.
    const source = code(PREVIEW)
    assert.ok(!source.includes('ExerciseResponse'), 'the preview must not use the fetching component')
    assert.match(source, /import PrivateResponseArea/)
  })

  test('the preview honours the creator’s toggle', () => {
    const source = code(PREVIEW)
    const start = source.indexOf("if (t === 'exercise')")
    const branch = source.slice(start, start + 2600)
    assert.match(branch, /block\.response_enabled !== false/)
  })
})

describe('the creator toggle', () => {
  test('it is labelled as agreed and defaults to on', () => {
    const source = code(PREVIEW)
    assert.match(source, /Allow members to write a response/)
    assert.match(
      source,
      /Members can privately write and save their responses to this\s+exercise\./,
    )
    // NULL reads as on, so existing Exercise blocks need no republishing.
    assert.match(source, /useState\(\s*block\.response_enabled \?\? true,?\s*\)/)
  })

  test('it is presented as a field, like every other control here', () => {
    // It shipped as a bare checkbox with no ``field-label`` — the only
    // control in this editor not following that convention — which made
    // it read as loose body text after the eight-row instructions
    // editor and easy to scan past entirely.
    const source = code(PREVIEW)
    const start = source.indexOf("{t === 'exercise' && (")
    assert.ok(start !== -1, 'the exercise editor branch has moved')
    const branch = source.slice(start, source.indexOf("{t === 'image' && (", start))
    const fieldLabels = branch.match(/className="field-label"/g) ?? []
    assert.equal(
      fieldLabels.length,
      3,
      'Title, Instructions and Member response must each carry a field-label',
    )
    assert.match(branch, /<label className="field-label">Member response<\/label>/)
  })

  test('it follows the house toggle pattern', () => {
    const source = code(PREVIEW)
    const start = source.indexOf("{t === 'exercise' && (")
    const branch = source.slice(start, source.indexOf("{t === 'image' && (", start))
    assert.match(branch, /cursor-pointer/)
    assert.match(branch, /accent-teal-500/)
  })

  test('the checkbox is bound to the toggle state in both directions', () => {
    const source = code(PREVIEW)
    assert.match(source, /checked=\{responseEnabled\}/)
    assert.match(source, /onChange=\{\(e\) => setResponseEnabled\(e\.target\.checked\)\}/)
  })

  test('it is included in the save payload, for exercises only', () => {
    // The About-page editor shares this component and its table has no
    // such column.
    assert.match(
      code(PREVIEW),
      /\.\.\.\(t === 'exercise' \? \{ response_enabled: responseEnabled \} : \{\}\)/,
    )
  })

  test('autosave notices the toggle', () => {
    // Omitting it would make the switch appear to work and silently
    // never persist until some other field was touched.
    const deps = code(PREVIEW).match(/\}, \[content, label, caption, heading,([^\]]*)\]\)/)
    assert.ok(deps, 'the autosave dependency list has moved')
    assert.match(deps[1], /\bresponseEnabled\b/)
  })
})

describe('the shared area serves both surfaces identically', () => {
  test('both callers use it', () => {
    assert.match(code('components/spaces/StepActions.tsx'), /<PrivateResponseArea/)
    assert.match(code(EXERCISE), /<PrivateResponseArea/)
  })

  test('it is controlled, so the step page keeps the reflection value', () => {
    // Pause & Reflect's "Mark complete" posts the current text, so the
    // value cannot live inside the shared component.
    const source = code(AREA)
    assert.match(source, /value: string/)
    assert.match(source, /onChange: \(next: string\) => void/)
    assert.ok(!source.includes('useState(initialValue'), 'the value must stay with the caller')
  })

  test('saving is explicit — there is no autosave here', () => {
    const source = code(AREA)
    assert.ok(!source.includes('setTimeout(() => onSave'))
    assert.ok(!/useEffect\([^)]*onSave/.test(source))
  })

  test('a failed save says so instead of claiming success', () => {
    // The old handler set "Saved." on res.ok and did nothing otherwise,
    // so a failure looked identical to not having pressed the button.
    const source = code(AREA)
    assert.match(source, /const \[failed, setFailed\] = useState\(false\)/)
    assert.match(source, /role="alert"/)
    assert.match(source, /role="status"/)
  })

  test('the privacy promise is shown on both', () => {
    assert.match(code(AREA), /privacyLabel = 'Private to you'/)
  })

  test('read-only mode cannot type or send', () => {
    const source = code(AREA)
    assert.match(source, /readOnly=\{readOnly\}/)
    assert.match(source, /if \(readOnly \|\| saving\) return/)
    assert.match(source, /disabled=\{readOnly \|\| saving \|\| !value\.trim\(\)\}/)
  })
})
