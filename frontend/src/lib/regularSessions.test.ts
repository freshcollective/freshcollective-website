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
import { describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import {
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
