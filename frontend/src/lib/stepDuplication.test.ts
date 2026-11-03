import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  STEP_DUPLICATE_LIVE_WARNING,
  STEP_DUPLICATE_SUCCESS,
  stepDuplicateEndpoint,
  stepDuplicateErrorMessage,
  stepDuplicateNeedsConfirmation,
  stepEditorHref,
} from './stepDuplication.ts'

const SRC = join(process.cwd(), 'src')
const EDITOR = join(
  SRC, 'app', 'creator-studio', 'pathways', '[pathwaySlug]',
  'PathwayContentClient.tsx',
)
const editor = () => readFileSync(EDITOR, 'utf8')

describe('the endpoint and the destination', () => {
  it('posts to the step duplicate route', () => {
    assert.equal(
      stepDuplicateEndpoint('moonlit-circle', 'know-yourself', 'patterns'),
      '/api/creator/spaces/moonlit-circle/pathways/know-yourself'
      + '/steps/patterns/duplicate',
    )
  })

  it('knows where the new step is edited', () => {
    assert.equal(
      stepEditorHref('know-yourself', 'patterns-copy'),
      '/creator-studio/pathways/know-yourself/steps/patterns-copy',
    )
  })
})

describe('the published-Pathway warning', () => {
  it('warns on an active Pathway', () => {
    // A step has no draft state of its own — visibility is the
    // Pathway's — so the copy is visible to members the moment it
    // exists, carrying the original's words.
    assert.equal(stepDuplicateNeedsConfirmation('active'), true)
  })

  it('does not warn on a draft or coming-soon Pathway', () => {
    for (const status of ['draft', 'coming_soon', 'archived', null, undefined]) {
      assert.equal(stepDuplicateNeedsConfirmation(status), false, String(status))
    }
  })

  it('says what will happen and asks', () => {
    assert.ok(/published/i.test(STEP_DUPLICATE_LIVE_WARNING))
    assert.ok(/visible to members/i.test(STEP_DUPLICATE_LIVE_WARNING))
    assert.ok(/\?$/.test(STEP_DUPLICATE_LIVE_WARNING.trim()))
  })
})

describe('feedback', () => {
  it('has the agreed success wording', () => {
    assert.equal(
      STEP_DUPLICATE_SUCCESS,
      'Step duplicated. You can now edit your new step.',
    )
  })

  it('shows our own 400 text verbatim', () => {
    assert.equal(stepDuplicateErrorMessage(400, 'A specific reason.'),
      'A specific reason.')
    assert.equal(stepDuplicateErrorMessage(409, 'A conflict.'), 'A conflict.')
  })

  it('never leaks a bare framework message', () => {
    for (const [status, detail] of [
      [404, 'Not Found'], [500, 'Internal Server Error'], [0, null],
    ] as [number, unknown][]) {
      const message = stepDuplicateErrorMessage(status, detail)
      assert.ok(!/Internal Server Error/.test(message), message)
      assert.ok(!/^Not Found$/.test(message), message)
    }
  })

  it('names permission and missing-step failures plainly', () => {
    assert.ok(/permission/i.test(stepDuplicateErrorMessage(403, null)))
    assert.ok(/could not be found/i.test(stepDuplicateErrorMessage(404, 'x')))
  })
})

/**
 * The editor itself is a React client component and this harness is
 * node:test with no DOM, so the wiring is asserted against the source.
 * These are shape checks, not behaviour: they fail loudly if the
 * control is removed, renamed, nested wrongly or stops refetching,
 * which is what a regression here would look like.
 */
describe('the control in the Pathway editor', () => {
  it('is labelled Duplicate step', () => {
    assert.ok(/Duplicating…' : 'Duplicate step'/.test(editor()))
  })

  it('sits with the other step actions, between Edit and Delete', () => {
    const source = editor()
    const edit = source.indexOf('Edit →')
    const duplicate = source.indexOf("'Duplicate step'")
    const del = source.indexOf("{deleting ? '…' : 'Delete'}")
    assert.ok(edit > -1 && duplicate > -1 && del > -1)
    assert.ok(edit < duplicate, 'Duplicate is above Edit')
    assert.ok(duplicate < del, 'Duplicate is below Delete')
  })

  it('is a button, not a link inside the row', () => {
    // The row already contains an <a> for Edit; an interactive control
    // nested in another would be invalid markup.
    const source = editor()
    const block = source.slice(
      source.indexOf('{onDuplicate && ('),
      source.indexOf('{onDelete && ('),
    )
    assert.ok(/type="button"/.test(block))
    assert.ok(!/<Link/.test(block))
    assert.ok(!/<a /.test(block))
  })

  it('is keyboard reachable and announces its busy state', () => {
    const source = editor()
    const block = source.slice(
      source.indexOf('{onDuplicate && ('),
      source.indexOf('{onDelete && ('),
    )
    // A real <button> is focusable and Enter/Space-activated with no
    // extra handlers; aria-busy is what a screen reader reads while
    // the request is in flight.
    assert.ok(/aria-busy=\{duplicating\}/.test(block))
    assert.ok(/disabled=\{duplicating\}/.test(block))
  })

  it('appears on every step list — sectioned, unsectioned and flat', () => {
    // Three call sites render StepRow. Missing one would leave the
    // action absent from some Pathways and not others.
    const source = editor()
    const wired = source.split('onDuplicate={() => handleStepDuplicate(step)}').length - 1
    assert.equal(wired, 3, `only ${wired} of 3 step lists offer Duplicate`)
  })

  it('calls the endpoint helper rather than building a URL', () => {
    assert.ok(
      /stepDuplicateEndpoint\(spaceSlug, pathway\.slug, step\.slug\)/
        .test(editor()),
    )
    assert.ok(/method: 'POST'/.test(editor()))
  })

  it('cannot be double-submitted', () => {
    const source = editor()
    assert.ok(/if \(duplicatingStepId\) return/.test(source))
    assert.ok(/duplicating=\{duplicatingStepId === step\.id\}/.test(source))
  })

  it('confirms first on a published Pathway', () => {
    assert.ok(
      /stepDuplicateNeedsConfirmation\(pathway\.status\)[\s\S]{0,80}confirm\(STEP_DUPLICATE_LIVE_WARNING\)/
        .test(editor()),
      'the published-Pathway confirmation is gone',
    )
  })

  it('refetches the step list rather than patching it', () => {
    // The server shifted every step below the source, so local state
    // would be wrong about their positions.
    const source = editor()
    const handler = source.slice(
      source.indexOf('async function handleStepDuplicate'),
      source.indexOf('async function handleStepDelete'),
    )
    assert.ok(/setSteps\(await fresh\.json\(\)\)/.test(handler))
    assert.ok(/router\.refresh\(\)/.test(handler))
    assert.ok(
      !/setSteps\(\[\.\.\.steps/.test(handler),
      'the list is being patched locally, which cannot know the new positions',
    )
  })

  it('surfaces errors in the existing step-action banner', () => {
    const source = editor()
    assert.ok(/setStepActionError\(stepDuplicateErrorMessage\(/.test(source))
    assert.ok(
      /\{stepActionError && \(/.test(source),
      'the error banner is gone',
    )
  })
})

describe('the row stays usable on a narrow screen', () => {
  it('the actions wrap rather than overflowing', () => {
    // The row is `flex flex-wrap`, so adding a third action wraps on a
    // phone instead of pushing Delete off the edge.
    const source = editor()
    const row = source.slice(
      source.indexOf('function StepRow('),
      source.indexOf('function PathwayStructure('),
    )
    const container = row.match(/<div className="([^"]*)"/)
    assert.ok(container, 'no container element found in StepRow')
    assert.ok(
      /flex-wrap/.test(container![1]),
      `the step row no longer wraps: ${container![1]}`,
    )
  })
})
