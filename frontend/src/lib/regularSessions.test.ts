/**
 * The sentences a member reads before and after reserving a term.
 *
 * This feature's promise is that nothing is skipped quietly. That
 * promise lives in the copy as much as in the booking logic: a preview
 * that says "Reserve 12 sessions" while three are full, or a result
 * that says "Done" after the world moved, breaks it just as
 * effectively as a server that silently dropped them.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/regularSessions.test.ts
 */

import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import {
  ACCESS_POLL_INTERVAL_MS,
  ACCESS_POLL_MAX_ATTEMPTS,
  accessWaitCopy,
  accessWaitPhase,
  confirmLabel,
  patternDescription,
  previewHeadline,
  previewNotes,
  resultHeadline,
  resultNeedsAttention,
  sessionCount,
  type OccurrenceOutcome,
  type ReservationPreview,
  type ReservationResult,
  type SchedulePattern,
} from './regularSessions.ts'

function occurrence(overrides: Partial<OccurrenceOutcome> = {}): OccurrenceOutcome {
  return {
    event_id: 'e1',
    title: 'Session',
    starts_at: '2027-03-01T07:00:00',
    ends_at: '2027-03-01T08:00:00',
    pattern_key: '0-18:00-19:00',
    reason: null,
    message: null,
    ...overrides,
  }
}

function preview(overrides: Partial<ReservationPreview> = {}): ReservationPreview {
  const base: ReservationPreview = {
    timezone: 'Australia/Melbourne',
    selected_keys: ['0-18:00-19:00'],
    new_reservation_count: 0,
    will_reserve: [],
    already_booked: [],
    unavailable: [],
  }
  const merged = { ...base, ...overrides }
  // Keep the count honest unless a test overrides it deliberately.
  if (overrides.new_reservation_count === undefined) {
    merged.new_reservation_count = merged.will_reserve.length
  }
  return merged
}

function result(overrides: Partial<ReservationResult> = {}): ReservationResult {
  const base: ReservationResult = {
    timezone: 'Australia/Melbourne',
    reserved_count: 0,
    reserved: [],
    already_booked: [],
    unavailable: [],
    changed_since_preview: [],
  }
  const merged = { ...base, ...overrides }
  if (overrides.reserved_count === undefined) {
    merged.reserved_count = merged.reserved.length
  }
  return merged
}

describe('sessionCount', () => {
  test('one session is singular', () => {
    assert.equal(sessionCount(1), '1 session')
  })

  test('anything else is plural, including zero', () => {
    assert.equal(sessionCount(0), '0 sessions')
    assert.equal(sessionCount(12), '12 sessions')
  })
})

describe('the preview headline', () => {
  test('leads with the number the member is agreeing to', () => {
    const p = preview({ will_reserve: [occurrence(), occurrence()] })
    assert.equal(previewHeadline(p), 'Reserve 2 sessions.')
  })

  test('an already-complete schedule says so rather than showing a zero', () => {
    const p = preview({ already_booked: [occurrence()] })
    assert.equal(
      previewHeadline(p),
      'You have already reserved every session in this schedule.',
    )
  })

  test('nothing available reads as nothing to do, not as a failure', () => {
    const p = preview({ unavailable: [occurrence({ reason: 'full' })] })
    assert.equal(previewHeadline(p), 'Nothing new to reserve in this schedule.')
  })
})

describe('the preview notes', () => {
  test('a clean preview adds nothing', () => {
    assert.deepEqual(previewNotes(preview({ will_reserve: [occurrence()] })), [])
  })

  test('already-reserved sessions are named and left alone', () => {
    const notes = previewNotes(preview({
      will_reserve: [occurrence()],
      already_booked: [occurrence({ event_id: 'e2' })],
    }))
    assert.equal(notes.length, 1)
    assert.match(notes[0], /1 session already reserved/)
    assert.match(notes[0], /left as they are/)
  })

  test('unavailable sessions are never implied away', () => {
    // The sentence that keeps the promise: the member is told the
    // count, told they are listed, and told they will stay unreserved.
    const notes = previewNotes(preview({
      will_reserve: [occurrence()],
      unavailable: [
        occurrence({ event_id: 'e2', reason: 'full' }),
        occurrence({ event_id: 'e3', reason: 'full' }),
      ],
    }))
    assert.equal(notes.length, 1)
    assert.match(notes[0], /2 sessions cannot be reserved/)
    assert.match(notes[0], /listed below/)
    assert.match(notes[0], /left unreserved/)
  })

  test('both conditions are reported, not just the first', () => {
    const notes = previewNotes(preview({
      will_reserve: [occurrence()],
      already_booked: [occurrence({ event_id: 'e2' })],
      unavailable: [occurrence({ event_id: 'e3', reason: 'full' })],
    }))
    assert.equal(notes.length, 2)
  })
})

describe('the confirm button', () => {
  test('says what it will do', () => {
    assert.equal(
      confirmLabel(preview({ will_reserve: [occurrence(), occurrence()] })),
      'Reserve 2 sessions',
    )
  })

  test('says "the available" when some dates cannot be reserved', () => {
    // So the member is agreeing to a partial action knowingly — the
    // brief's "let the member confirm reservation of the available
    // dates", in the one place they are actually deciding.
    const label = confirmLabel(preview({
      will_reserve: [occurrence(), occurrence()],
      unavailable: [occurrence({ event_id: 'e9', reason: 'full' })],
    }))
    assert.equal(label, 'Reserve the available 2 sessions')
  })
})

describe('the result headline', () => {
  test('a clean run reports the count', () => {
    assert.equal(
      resultHeadline(result({ reserved: [occurrence(), occurrence()] })),
      'Reserved 2 sessions.',
    )
  })

  test('a changed world leads with the change, not with success', () => {
    const r = result({
      reserved: [occurrence(), occurrence()],
      changed_since_preview: [occurrence({ event_id: 'e9', reason: 'full' })],
    })
    assert.equal(
      resultHeadline(r),
      'Reserved 2 sessions. 1 became unavailable while you were deciding.',
    )
  })

  test('losing everything says so plainly', () => {
    const r = result({
      changed_since_preview: [occurrence({ event_id: 'e9', reason: 'cancelled' })],
    })
    assert.equal(
      resultHeadline(r),
      'Nothing was reserved — 1 session became unavailable while you were deciding.',
    )
  })

  test('a repeated action reports the existing state, not a failure', () => {
    const r = result({ already_booked: [occurrence(), occurrence()] })
    assert.equal(resultHeadline(r), 'Those sessions were already reserved.')
  })

  test('nothing at all is still an answer', () => {
    assert.equal(resultHeadline(result()), 'Nothing was reserved.')
  })
})

describe('whether the detail list opens itself', () => {
  test('a clean success does not need it', () => {
    assert.equal(resultNeedsAttention(result({ reserved: [occurrence()] })), false)
  })

  for (const [label, r] of [
    ['a change since the preview', result({
      reserved: [occurrence()],
      changed_since_preview: [occurrence({ event_id: 'e9' })],
    })],
    ['an unavailable date', result({
      reserved: [occurrence()],
      unavailable: [occurrence({ event_id: 'e9', reason: 'full' })],
    })],
  ] as [string, ReservationResult][]) {
    test(`${label} opens it`, () => {
      assert.equal(resultNeedsAttention(r), true)
    })
  }
})

describe('the pattern description', () => {
  function pattern(overrides: Partial<SchedulePattern> = {}): SchedulePattern {
    return {
      key: '0-18:00-19:00',
      weekday: 0,
      weekday_label: 'Mondays',
      time_label: '6:00–7:00 pm',
      label: 'Mondays — 6:00–7:00 pm',
      start_time: '18:00',
      end_time: '19:00',
      occurrence_count: 8,
      already_booked_count: 0,
      shares_weekday: false,
      first_starts_at: '2027-03-01T07:00:00',
      last_starts_at: '2027-04-19T07:00:00',
      ...overrides,
    }
  }

  test('a fresh slot reports what is remaining', () => {
    assert.equal(patternDescription(pattern()), '8 sessions remaining')
  })

  test('a partly-booked slot separates what is left from what is held', () => {
    assert.equal(
      patternDescription(pattern({ already_booked_count: 3 })),
      '5 sessions to reserve · 3 already yours',
    )
  })

  test('one remaining session reads as singular', () => {
    assert.equal(
      patternDescription(pattern({ occurrence_count: 4, already_booked_count: 3 })),
      '1 session to reserve · 3 already yours',
    )
  })
})

// ---------------------------------------------------------------------------
// The window between paying and having access
// ---------------------------------------------------------------------------
//
// The AccessPass arrives on a webhook, so a member can return from
// Stripe before they have access. The page used to fall through to
// "Ways to join" in that window and offer to sell them the term they
// had just bought. These assertions are mostly about what the copy
// must never say.

describe('waiting for access after a purchase', () => {
  test('the first few polls read as a brief confirmation', () => {
    assert.equal(accessWaitPhase(1), 'confirming')
    assert.equal(accessWaitPhase(5), 'confirming')
  })

  test('a longer wait is acknowledged rather than hidden', () => {
    assert.equal(accessWaitPhase(6), 'slow')
    assert.equal(accessWaitPhase(ACCESS_POLL_MAX_ATTEMPTS - 1), 'slow')
  })

  test('waiting stops being honest after the limit', () => {
    assert.equal(accessWaitPhase(ACCESS_POLL_MAX_ATTEMPTS), 'timed_out')
    assert.equal(accessWaitPhase(ACCESS_POLL_MAX_ATTEMPTS + 10), 'timed_out')
  })

  test('the wait is bounded at roughly two minutes', () => {
    const totalMs = ACCESS_POLL_INTERVAL_MS * ACCESS_POLL_MAX_ATTEMPTS
    assert.ok(totalMs >= 60_000, 'too short for a slow webhook')
    assert.ok(totalMs <= 180_000, 'too long to leave someone watching')
  })

  for (const phase of ['confirming', 'slow', 'timed_out'] as const) {
    test(`${phase} never suggests paying again`, () => {
      // The whole point. The member has paid; the only thing missing
      // is a webhook.
      const { heading, body } = accessWaitCopy(phase)
      const text = `${heading} ${body}`.toLowerCase()
      for (const forbidden of ['buy', 'purchase', 'checkout', 'pay now']) {
        assert.ok(!text.includes(forbidden), `${phase} copy says "${forbidden}"`)
      }
    })

    test(`${phase} tells the member their payment is safe`, () => {
      const { heading, body } = accessWaitCopy(phase)
      const text = `${heading} ${body}`.toLowerCase()
      assert.ok(
        /payment|paid/.test(text),
        `${phase} copy does not mention the payment at all`,
      )
    })
  }

  test('only the longest wait asks the member to do something', () => {
    assert.equal(accessWaitCopy('confirming').showReload, false)
    assert.equal(accessWaitCopy('slow').showReload, false)
    assert.equal(accessWaitCopy('timed_out').showReload, true)
  })

  test('the longest wait ends with reassurance and a way out', () => {
    const copy = accessWaitCopy('timed_out')
    assert.match(copy.body, /do not need to pay again/i)
    assert.match(copy.body, /reload/i)
  })
})

// ---------------------------------------------------------------------------
// The page's branch order
// ---------------------------------------------------------------------------

describe('the Series page never sells a term twice', () => {
  // A source contract, because this is a fact about branch *order* in
  // a server component that no unit test of the copy can see. The
  // failure it guards against is specific: a member returns from
  // Stripe before the webhook lands, falls past the access branch, and
  // is shown the purchase CTA for the thing they just bought.
  const PAGE = new URL(
    '../app/spaces/[slug]/gathering-series/[series-slug]/page.tsx',
    import.meta.url,
  ).pathname

  test('the just-purchased branch comes before ways-to-join', () => {
    const source = readFileSync(PAGE, 'utf8')
    const pending = source.indexOf('<AccessPending')
    const waysToJoin = source.indexOf('<SidebarWaysToJoin')
    assert.ok(pending > 0, 'the pending-access state is not rendered at all')
    assert.ok(waysToJoin > 0, 'ways-to-join is no longer rendered')
    assert.ok(
      pending < waysToJoin,
      'a member who has just paid would be offered the purchase again',
    )
  })

  test('the reserve card is offered on the same page, not a new one', () => {
    // "Immediately after purchase" and "still there later" are the
    // same surface deliberately: this page is the Stripe return
    // destination, so one component covers both.
    const source = readFileSync(PAGE, 'utf8')
    assert.ok(source.includes('<RegularSessions'))
    assert.ok(source.includes("=== 'success'"), 'the return flag is not read')
  })
})
