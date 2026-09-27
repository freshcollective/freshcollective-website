/**
 * Creator Studio → Collective Overview, against the live EMBODY shape.
 *
 * Production kept showing "Upcoming Gatherings: 31" and "Next gathering:
 * Test1" after a release that fixed exactly this on a sibling page. The
 * Overview is a different route — ``app/creator-studio/home/page.tsx`` —
 * and it had its own copy of the defect: an unscoped fetch filtered
 * client-side on start time alone, no status check. Both numbers came
 * from one array, so one missing filter was wrong twice.
 *
 * The live composition these tests use: 28 active upcoming Term 4
 * occurrences, 2 cancelled Term 4 occurrences, and one cancelled
 * standalone named "Test1" whose start time is the earliest of all —
 * which is how a cancelled Gathering became "Next gathering".
 *
 *   node --experimental-strip-types --test src/lib/collectiveOverview.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
// @ts-expect-error - Node-native import path
import { formatMomentWhen, orderGatheringsByStart, overviewGatherings } from './collectiveOverview.ts'

const MEL = 'Australia/Melbourne'

interface Ev { id: string; title: string; starts_at: string; status: string }

/** Term 4: Mondays and Thursdays 6 pm Melbourne = 07:00 UTC, from Mon
 *  5 Oct 2026. Dates are computed rather than written out so the fixture
 *  cannot drift into a day that does not exist — an earlier version
 *  generated 2026-11-31 and sorted as NaN. */
function term4Active(): Ev[] {
  const out: Ev[] = []
  const start = Date.UTC(2026, 9, 5, 7, 0, 0)   // Mon 5 Oct 2026, 07:00 UTC
  for (let i = 0; i < 28; i++) {
    // Alternating Mon → Thu (+3 days) → Mon (+4 days).
    const offsetDays = Math.floor(i / 2) * 7 + (i % 2 === 0 ? 0 : 3)
    const d = new Date(start + offsetDays * 86_400_000)
    out.push({
      id: `t4_${i}`, title: `Term 4 session ${i + 1}`,
      starts_at: d.toISOString().replace('Z', '').replace('.000', ''),
      status: 'active',
    })
  }
  return out
}

/** The two live cancellations, plus the cancelled standalone. */
const CANCELLED_SAT: Ev = {
  id: 'c1', title: 'Cancelled Sat 31 Oct',
  starts_at: '2026-10-30T22:00:00', status: 'cancelled',
}
const CANCELLED_MON: Ev = {
  id: 'c2', title: 'Cancelled Mon 2 Nov',
  starts_at: '2026-11-02T07:00:00', status: 'cancelled',
}
/** Earliest of everything — which is exactly why it surfaced. */
const TEST1: Ev = {
  id: 'c3', title: 'Test1',
  starts_at: '2026-10-01T07:00:00', status: 'cancelled',
}


describe('what the API scope must exclude before the page ever sees it', () => {
  // scope=upcoming applies status=='active' AND not-yet-ended server-side.
  // These assert the page's behaviour GIVEN that scope, and given the old
  // unscoped response, so the difference is visible rather than assumed.

  test('scoped response of 28 gives a Snapshot count of 28', () => {
    const { count } = overviewGatherings(term4Active())
    assert.equal(count, 28)
  })

  test('the unscoped response is what produced 31', () => {
    // 28 active + 2 cancelled Term 4 + 1 cancelled standalone.
    const unscoped = [...term4Active(), CANCELLED_SAT, CANCELLED_MON, TEST1]
    assert.equal(unscoped.length, 31)
    // The old page counted this array verbatim after a start-time filter.
    assert.equal(overviewGatherings(unscoped).count, 31)
  })

  test('Test1 cannot become Next gathering once the scope excludes it', () => {
    // The reported symptom. With the scope applied, Test1 is simply not
    // in the array the page receives.
    const { next } = overviewGatherings(term4Active())
    assert.notEqual(next?.title, 'Test1')
  })

  test('the genuine earliest active Term 4 occurrence is Next gathering', () => {
    const { next } = overviewGatherings(term4Active())
    assert.equal(next?.title, 'Term 4 session 1')
    assert.equal(next?.starts_at, '2026-10-05T07:00:00')  // Mon 5 Oct, 6 pm Melbourne
  })

  test('and unscoped, Test1 WOULD win — pinning why the scope matters', () => {
    const unscoped = [...term4Active(), CANCELLED_SAT, CANCELLED_MON, TEST1]
    assert.equal(overviewGatherings(unscoped).next?.title, 'Test1')
  })
})


describe('ordering', () => {
  test('earliest first, regardless of input order', () => {
    const shuffled = [...term4Active()].reverse()
    const ordered = orderGatheringsByStart(shuffled)
    assert.equal(ordered[0].title, 'Term 4 session 1')
    assert.equal(ordered[ordered.length - 1].title, 'Term 4 session 28')
  })

  test('the input array is not mutated', () => {
    const input = [...term4Active()].reverse()
    const first = input[0]
    orderGatheringsByStart(input)
    assert.equal(input[0], first)
  })

  test('naive strings are ordered as UTC instants, not local', () => {
    // A Saturday 9 am Melbourne Gathering is stored on the Friday in UTC.
    // Ordered by true instant it precedes a Monday 6 pm two days later.
    const sat = { id: 's', title: 'Sat 9am', starts_at: '2026-10-30T22:00:00' }
    const mon = { id: 'm', title: 'Mon 6pm', starts_at: '2026-11-02T07:00:00' }
    assert.deepEqual(
      orderGatheringsByStart([mon, sat]).map((e) => e.title),
      ['Sat 9am', 'Mon 6pm'],
    )
  })

  test('an empty list yields no next gathering', () => {
    const { count, next } = overviewGatherings([])
    assert.equal(count, 0)
    assert.equal(next, null)
  })
})


describe('Recent moments renders dates in the Collective timezone', () => {
  // Beyond a week the label falls back to a date, and that date was
  // rendered from a bare `new Date` with no timeZone.
  const farPast = new Date('2027-06-01T00:00:00Z')

  test('the Saturday 9 am Melbourne Gathering shows 31 Oct, not 30', () => {
    assert.equal(formatMomentWhen('2026-10-30T22:00:00', MEL, farPast), '31 Oct')
  })

  test('the same instant in UTC shows 30 Oct — the old output', () => {
    assert.equal(formatMomentWhen('2026-10-30T22:00:00', 'UTC', farPast), '30 Oct')
  })

  test('a Monday 6 pm Melbourne Gathering keeps its day', () => {
    assert.equal(formatMomentWhen('2026-11-02T07:00:00', MEL, farPast), '2 Nov')
  })

  test('relative labels are computed from the true instant', () => {
    // 07:00 UTC; three hours later is "3h ago", not offset-shifted.
    const now = new Date('2026-11-02T10:00:00Z')
    assert.equal(formatMomentWhen('2026-11-02T07:00:00', MEL, now), '3h ago')
  })

  test('a future moment reads as "in"', () => {
    const now = new Date('2026-11-02T04:00:00Z')
    assert.equal(formatMomentWhen('2026-11-02T07:00:00', MEL, now), 'in 3h')
  })

  test('an empty or unparseable stamp renders nothing', () => {
    assert.equal(formatMomentWhen('', MEL), '')
    assert.equal(formatMomentWhen('not-a-date', MEL), '')
  })
})


describe('the Overview route asks the API for the right scope', () => {
  // The page is a server component, so the fetch itself cannot be
  // exercised here. What CAN be pinned is the call — this is the line
  // whose absence caused the production symptom.
  const source = readFileSync(
    new URL('../app/creator-studio/home/page.tsx', import.meta.url),
    'utf8',
  )

  test("getCreatorEvents is called with the 'upcoming' scope", () => {
    assert.match(source, /getCreatorEvents\([^)]*,\s*'upcoming'\s*\)/)
  })

  test('no unscoped getCreatorEvents call remains on this page', () => {
    const calls = source.match(/getCreatorEvents\([^)]*\)/g) ?? []
    assert.ok(calls.length > 0, 'expected at least one call')
    for (const call of calls) {
      assert.match(call, /'upcoming'/, `unscoped call: ${call}`)
    }
  })

  test('the page no longer filters Gatherings by start time itself', () => {
    // The client-side filter is what let a cancelled Gathering through.
    assert.doesNotMatch(source, /\.filter\(\s*\(e\)\s*=>\s*new Date\(e\.starts_at\)/)
  })
})
