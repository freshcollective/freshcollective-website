import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * Pause & Reflect — the member's own words, and nothing else.
 *
 * The section used to print three stock questions ("What stood out?"
 * …) under the creator's prompt. A member who had just been asked
 * something specific was then asked three generic things, and the
 * creator's question was the one that looked optional. The questions
 * are gone; the invitation to pause is not.
 *
 * What must survive, because it is the part members would actually
 * lose: the text area, the save round-trip, and the promise that the
 * writing is private. Those are asserted here in their own right so
 * that trimming copy from this section can never quietly take the
 * saving with it.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/** StepActions plus the shared component it now delegates the text area
 *  to.
 *
 *  The box, the save button, the "Saved." dwell and the privacy line
 *  moved into ``PrivateResponseArea`` so Exercise blocks could offer the
 *  same thing without a second copy. These assertions care that a
 *  member still gets them, not which file they live in — so they read
 *  both. What stayed in StepActions is the part that is specific to
 *  reflections: the endpoint, the field name, and the step-completion
 *  flow that also persists the text. */
const reflectionSurface = () =>
  code('components/spaces/StepActions.tsx') +
  '\n' +
  code('components/spaces/PrivateResponseArea.tsx')

/** The component source with JSX comments stripped.
 *
 * The removal is explained in a comment that names the questions it
 * removed, so a blunt substring search would match the explanation and
 * report the questions as still present. */
function code(path = 'components/spaces/StepActions.tsx'): string {
  return read(path)
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('the stock reflection questions are gone', () => {
  for (const question of [
    'What stood out?',
    'What challenged you?',
    'What feels important enough to remember?',
  ]) {
    test(`"${question}" is no longer rendered`, () => {
      assert.ok(
        !code().includes(question),
        'a stock question is still being displayed to members',
      )
    })
  }

  test('no list of prompts is rendered in the reflect section', () => {
    // Catches the questions coming back in a different wording.
    const source = code()
    const start = source.indexOf('Pause &amp; Reflect')
    assert.ok(start !== -1, 'the Pause & Reflect section has moved')
    const section = source.slice(start, source.indexOf('</section>', start))
    assert.ok(!section.includes('<ul'), 'the reflect section lists prompts again')
    assert.ok(!section.includes('<li>'), 'the reflect section lists prompts again')
  })
})

describe('the invitation to pause stays', () => {
  test('the lead-in line is still there', () => {
    // Not a question — it is what stops the heading sitting directly on
    // the text area.
    assert.ok(code().includes('Take a moment before moving on.'))
  })

  test('the section is still headed Pause & Reflect', () => {
    assert.ok(code().includes('Pause &amp; Reflect'))
  })
})

describe('reflection still saves, persists and stays private', () => {
  test('the text area is still rendered and still bound to notes', () => {
    const surface = reflectionSurface()
    assert.match(surface, /<textarea/)
    // StepActions still names the element and still owns the value —
    // ``handleComplete`` posts the same text, so moving the state into
    // the shared component would have stopped completion persisting it.
    assert.match(code('components/spaces/StepActions.tsx'), /textareaId="step-notes"/)
    assert.match(code('components/spaces/StepActions.tsx'), /value=\{notes\}/)
    assert.match(surface, /id=\{textareaId\}/)
  })

  test('the save round-trip is unchanged', () => {
    const source = code()
    assert.match(source, /reflection_text/)
    assert.match(source, /\/notes/)
    assert.match(source, /Save reflection/)
  })

  test('previously saved writing is still loaded back', () => {
    // Persistence across visits: without this the member reopens the
    // step to a blank box and believes the save failed.
    assert.match(code(), /initialNotes/)
  })

  test('the privacy promise is still shown', () => {
    assert.ok(reflectionSurface().includes('Private to you'))
  })

  test('the per-step reflection toggle still gates the section', () => {
    assert.match(code(), /reflectionEnabled/)
  })

  test('marking the step complete still persists the reflection', () => {
    // ``handleComplete`` sends the current text alongside completion.
    // This is why the shared component is controlled rather than owning
    // the value, and it is the quietest thing the extraction could have
    // broken.
    const source = code()
    const complete = source.slice(source.indexOf('async function handleComplete'))
    assert.match(complete.slice(0, 400), /reflection_text: notes \|\| null/)
  })

  test('the save request itself is unchanged', () => {
    // Same endpoint, same field, same credentials — the extraction
    // moved presentation, not storage.
    const source = code()
    const save = source.slice(source.indexOf('async function handleSaveNotes'))
    assert.match(save.slice(0, 500), /\$\{base\}\/notes/)
    assert.match(save.slice(0, 500), /reflection_text: notes/)
    assert.match(save.slice(0, 500), /credentials: 'include'/)
  })
})
