import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  isInteractive,
  modeIsTappable,
  modeShowsBar,
  nextSelection,
  pollRowMode,
  showsClearVote,
  showsResults,
} from './pollInteraction.ts'

/**
 * Poll voting was reported as impossible: members could not select an
 * option or submit.
 *
 * The API was never the problem (see
 * ``backend/tests/test_conversation_poll_voting.py``). ``PollRow``
 * returned a static ``<div>`` whenever the server said results were
 * visible — and the server says that in three situations, only one of
 * which means voting is over:
 *
 *     show_results = show_results_before_vote OR user_has_voted OR is_closed
 *
 * So a poll set to show results early had no tap-target from creation,
 * and any poll became read-only the moment somebody voted.
 *
 * These tests pin the two questions apart. The three cases named
 * ``_the_reported_bug`` are the ones that were broken.
 */

const SRC = dirname(fileURLToPath(import.meta.url))
const component = readFileSync(
  join(SRC, '..', 'components', 'community', 'PollView.tsx'), 'utf8',
)

const poll = (over: Partial<{ show_results: boolean; is_closed: boolean }> = {}) => ({
  show_results: false,
  is_closed: false,
  ...over,
})

describe('the two questions are independent', () => {
  test('results visibility is the server’s answer, unmodified', () => {
    assert.equal(showsResults(poll({ show_results: true })), true)
    assert.equal(showsResults(poll({ show_results: false })), false)
  })

  test('interactivity does not depend on results visibility', () => {
    // The crux. Results on screen must not mean "voting is over".
    assert.equal(isInteractive(poll({ show_results: true }), false), true)
    assert.equal(isInteractive(poll({ show_results: false }), false), true)
  })

  test('only closing stops interaction', () => {
    assert.equal(isInteractive(poll({ is_closed: true }), false), false)
  })

  test('a request in flight stops it too', () => {
    assert.equal(isInteractive(poll(), true), false)
  })
})

describe('row mode', () => {
  test('a fresh poll offers plain choices', () => {
    assert.equal(pollRowMode(poll(), false), 'choice')
  })

  test('show-results-before-vote keeps the options tappable — the reported bug', () => {
    // Previously: bars, no handler, no way to vote at all.
    const mode = pollRowMode(poll({ show_results: true }), false)
    assert.equal(mode, 'bar-interactive')
    assert.equal(modeIsTappable(mode), true)
    assert.equal(modeShowsBar(mode), true)
  })

  test('after voting the options stay tappable — the reported bug', () => {
    // ``user_has_voted`` makes the server set show_results, which used
    // to freeze the poll and make changing a vote impossible.
    const mode = pollRowMode(poll({ show_results: true }), false)
    assert.equal(modeIsTappable(mode), true)
  })

  test('a closed poll is bars only', () => {
    const mode = pollRowMode(poll({ show_results: true, is_closed: true }), false)
    assert.equal(mode, 'bar-static')
    assert.equal(modeIsTappable(mode), false)
    assert.equal(modeShowsBar(mode), true)
  })

  test('mid-request on a results-hidden poll is inert but shows no bars', () => {
    const mode = pollRowMode(poll(), true)
    assert.equal(mode, 'choice-static')
    assert.equal(modeIsTappable(mode), false)
    assert.equal(modeShowsBar(mode), false)
  })

  test('every mode is either tappable or not, and either barred or not', () => {
    for (const sr of [true, false]) {
      for (const closed of [true, false]) {
        for (const busy of [true, false]) {
          const m = pollRowMode({ show_results: sr, is_closed: closed }, busy)
          assert.equal(modeShowsBar(m), sr)
          assert.equal(modeIsTappable(m), !closed && !busy)
        }
      }
    }
  })
})

describe('single-choice selection', () => {
  test('a tap selects that option', () => {
    assert.deepEqual(nextSelection([], 'a', false), ['a'])
  })

  test('tapping another option replaces the first', () => {
    assert.deepEqual(nextSelection(['a'], 'b', false), ['b'])
  })

  test('it never accumulates', () => {
    let sel = nextSelection([], 'a', false)
    sel = nextSelection(sel, 'b', false)
    sel = nextSelection(sel, 'c', false)
    assert.deepEqual(sel, ['c'])
  })

  test('re-tapping the chosen option keeps it', () => {
    // Not a toggle: a single-choice poll has no "no answer" state the
    // member can reach by tapping, and the API would read [] as a
    // retraction.
    assert.deepEqual(nextSelection(['a'], 'a', false), ['a'])
  })
})

describe('multiple-choice selection', () => {
  test('a tap adds', () => {
    assert.deepEqual(nextSelection([], 'a', true), ['a'])
  })

  test('taps accumulate', () => {
    assert.deepEqual(nextSelection(['a'], 'b', true), ['a', 'b'])
  })

  test('tapping a selected option deselects it', () => {
    assert.deepEqual(nextSelection(['a', 'b'], 'a', true), ['b'])
  })

  test('deselecting everything is possible before submitting', () => {
    let sel = ['a', 'b']
    sel = nextSelection(sel, 'a', true)
    sel = nextSelection(sel, 'b', true)
    assert.deepEqual(sel, [])
  })

  test('order of selection is preserved', () => {
    let sel = nextSelection([], 'c', true)
    sel = nextSelection(sel, 'a', true)
    assert.deepEqual(sel, ['c', 'a'])
  })

  test('it does not mutate the array it is given', () => {
    const before = ['a']
    nextSelection(before, 'b', true)
    assert.deepEqual(before, ['a'])
  })
})

describe('the component uses the shared rule', () => {
  test('it no longer early-returns a static row on results', () => {
    // The defect, in one line: ``if (showResults) return <div>``.
    assert.ok(!/if \(showResults\)\s*\{?\s*return/.test(component))
  })

  test('the row mode comes from pollRowMode', () => {
    assert.match(component, /const rowMode = pollRowMode\(poll, busy\)/)
  })

  test('tappability is checked before acting', () => {
    assert.match(component, /if \(!modeIsTappable\(rowMode\)\) return/)
  })

  test('one tap handler serves both poll kinds', () => {
    assert.match(component, /function onOptionTap/)
    assert.ok(!/function onSingleChoiceClick/.test(component))
    assert.ok(!/function toggleMulti/.test(component))
  })

  test('selection goes through nextSelection', () => {
    assert.match(
      component,
      /nextSelection\(selectedIds, id, poll\.allow_multiple\)/,
    )
  })

  test('single choice submits on tap, multiple choice waits', () => {
    assert.match(component, /if \(!poll\.allow_multiple\) submit\(next\)/)
  })
})

describe('accessibility and mobile', () => {
  test('a tappable row is a real button', () => {
    const row = component.slice(component.indexOf('function PollRow'))
    assert.match(row, /<button\s+type="button"/)
  })

  test('a closed row is not a button', () => {
    const row = component.slice(component.indexOf('function PollRow'))
    assert.match(row, /if \(!tappable\) \{[\s\S]{0,200}<div/)
  })

  test('multiple choice exposes its pressed state', () => {
    const row = component.slice(component.indexOf('function PollRow'))
    assert.match(row, /aria-pressed=\{allowMultiple \? selected : undefined\}/)
  })

  test('the tap target has a comfortable minimum height', () => {
    const row = component.slice(component.indexOf('function PollRow'))
    assert.match(row, /min-h-\[40px\]/)
  })

  test('the bar is decorative, not announced', () => {
    const row = component.slice(component.indexOf('function PollRow'))
    assert.match(row, /aria-hidden="true"\s*\n?\s*className="absolute inset-y-0/)
  })

  test('a long option label cannot break the row', () => {
    const row = component.slice(component.indexOf('function PollRow'))
    assert.match(row, /truncate/)
    assert.match(row, /min-w-0/)
  })
})

describe('feedback and failure', () => {
  test('a failed vote surfaces the server’s message', () => {
    assert.match(component, /typeof data\.detail === 'string' \? data\.detail/)
    assert.match(component, /\{error && <p/)
  })

  test('a failure does not leave the row stuck busy', () => {
    assert.match(component, /finally \{\s*\n\s*setBusy\(false\)/)
  })

  test('the view is replaced by what the server returned', () => {
    // Not optimistically patched — the server owns counts and
    // visibility.
    assert.match(component, /setPoll\(updated\)/)
    assert.match(
      component,
      /setSelectedIds\(updated\.options\.filter\(\(o\) => o\.voted\)/,
    )
  })

  test('the multi-choice button is disabled while saving', () => {
    assert.match(component, /disabled=\{busy\}/)
  })
})

describe('clear vote', () => {
  const p = (over: Partial<{ is_closed: boolean; user_has_voted: boolean }> = {}) => ({
    is_closed: false,
    user_has_voted: false,
    ...over,
  })

  test('offered once there is a vote to clear', () => {
    assert.equal(showsClearVote(p({ user_has_voted: true })), true)
  })

  test('not offered on an unanswered poll', () => {
    // It would do nothing, and only add noise.
    assert.equal(showsClearVote(p()), false)
  })

  test('not offered on a closed poll', () => {
    // The record stands; the control must be absent rather than
    // present-and-refused.
    assert.equal(showsClearVote(p({ is_closed: true, user_has_voted: true })), false)
  })

  test('not offered on a closed poll the member never answered', () => {
    assert.equal(showsClearVote(p({ is_closed: true })), false)
  })

  test('the rule is the same for both poll kinds', () => {
    // It takes no ``allow_multiple`` — single and multiple choice get
    // the same answer, which is the point of sharing the predicate.
    const fn = showsClearVote.toString()
    assert.ok(!/allow_multiple/.test(fn))
  })
})

describe('the clear-vote control in the component', () => {
  test('it goes through the shared predicate', () => {
    assert.match(component, /const clearable = showsClearVote\(poll\)/)
  })

  test('single choice reaches the action row through it', () => {
    // Previously the row was gated on ``allow_multiple`` alone, so a
    // single-choice voter had no retraction at all.
    assert.match(component, /\{\(poll\.allow_multiple \|\| clearable\) && !closed &&/)
  })

  test('it submits an empty selection', () => {
    // The API reads that as "remove my vote" — no new endpoint.
    assert.match(component, /onClick=\{\(\) => submit\(\[\]\)\}/)
  })

  test('the submit button stays multiple-choice only', () => {
    // Single choice submits on tap; a Cast button there would be a
    // second way to do the same thing.
    const row = component.slice(
      component.indexOf('The action row'),
      component.indexOf('{error &&'),
    )
    assert.match(row, /\{poll\.allow_multiple && \(\s*\n\s*<button/)
  })

  test('it is disabled rather than removed while saving', () => {
    const row = component.slice(
      component.indexOf('The action row'),
      component.indexOf('{error &&'),
    )
    const clearBlock = row.slice(row.indexOf('{clearable && ('))
    assert.match(clearBlock, /disabled=\{busy\}/)
  })

  test('it gives feedback while saving', () => {
    const row = component.slice(
      component.indexOf('The action row'),
      component.indexOf('{error &&'),
    )
    const clearBlock = row.slice(row.indexOf('{clearable && ('))
    assert.match(clearBlock, /busy \? 'Saving…' : 'Clear vote'/)
  })

  test('the tap target is comfortable and the row wraps on mobile', () => {
    const row = component.slice(
      component.indexOf('The action row'),
      component.indexOf('{error &&'),
    )
    assert.match(row, /flex-wrap/)
    assert.match(row, /min-h-\[32px\]/)
  })

  test('styling stays consistent with the existing control', () => {
    // Same muted-to-red treatment multiple choice already used.
    const row = component.slice(
      component.indexOf('The action row'),
      component.indexOf('{error &&'),
    )
    assert.match(row, /text-slate-500[^"]*hover:text-red-500/)
  })
})
