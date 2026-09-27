/**
 * Unit tests for the shared datetime helpers, focused on the
 * ``parseServerDatetime`` fix.
 *
 * Backstory: Pydantic v2 serialises TZ-naive ``DateTime(timezone=False)``
 * columns WITHOUT a trailing ``Z``. Per ES2019+, Chrome parses those
 * strings as browser-LOCAL time — which for our app is catastrophically
 * wrong because the storage convention is naive-UTC. The helper appends
 * a ``Z`` before ``new Date()`` so the parse is UTC-anchored.
 *
 * Run with the built-in Node test runner + Node's experimental type
 * stripping:
 *
 *   node --experimental-strip-types --test src/lib/dateTime.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import { parseServerDatetime, formatCalendarDate } from './dateTime.ts'


describe('formatCalendarDate — calendar days do NOT roll into the next day', () => {
  test('YYYY-MM-DDT23:59:59 (end-of-day storage) reads as its calendar day', () => {
    // The Series editor writes ``dateInputToNaiveIso("2026-12-12", true)``
    // which returns "2026-12-12T23:59:59". Under the datetime path
    // that string is UTC 23:59:59 and Melbourne AEDT (+11) is
    // 10:59 the NEXT day — so the buggy banner rendered 13 Dec. The
    // calendar-date helper reads the YYYY-MM-DD prefix directly, so
    // it always renders 12 Dec regardless of viewer timezone.
    const out = formatCalendarDate('2026-12-12T23:59:59')
    assert.equal(out, '12 Dec 2026')
  })

  test('YYYY-MM-DDT00:00:00 (start-of-day storage) reads as its calendar day', () => {
    const out = formatCalendarDate('2026-10-05T00:00:00')
    assert.equal(out, '5 Oct 2026')
  })

  test('Bare YYYY-MM-DD string reads as its calendar day', () => {
    const out = formatCalendarDate('2026-10-05')
    assert.equal(out, '5 Oct 2026')
  })

  test('Empty / invalid string returns empty', () => {
    assert.equal(formatCalendarDate(''), '')
    assert.equal(formatCalendarDate('not a date'), '')
    assert.equal(formatCalendarDate('202X-12-12'), '')
  })

  test('Custom options are honoured', () => {
    const out = formatCalendarDate('2026-12-12T23:59:59', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    })
    // Sat 12 Dec 2026
    assert.ok(out.includes('Saturday'), `expected "Saturday" in ${out}`)
    assert.ok(out.includes('12 December'), `expected "12 December" in ${out}`)
    assert.ok(out.includes('2026'), `expected "2026" in ${out}`)
  })
})


describe('parseServerDatetime — naive strings are treated as UTC', () => {
  test('naive ISO without Z is parsed as UTC', () => {
    // "2026-10-05T07:00:00" in the app's convention = Mon 5 Oct 07:00 UTC
    // = Mon 5 Oct 6 pm AEDT. Under browser-local parsing (the bug this
    // fixes) Chrome would have treated it as browser-local instead.
    const d = parseServerDatetime('2026-10-05T07:00:00')
    assert.equal(d.toISOString(), '2026-10-05T07:00:00.000Z')
  })

  test('naive ISO with fractional seconds is parsed as UTC', () => {
    const d = parseServerDatetime('2026-10-05T07:00:00.123')
    assert.equal(d.toISOString(), '2026-10-05T07:00:00.123Z')
  })
})


describe('parseServerDatetime — strings with a designator pass through', () => {
  test('Z suffix is honoured', () => {
    const d = parseServerDatetime('2026-10-05T07:00:00Z')
    assert.equal(d.toISOString(), '2026-10-05T07:00:00.000Z')
  })

  test('+HH:MM offset is honoured', () => {
    // 07:00 +11:00 = 20:00 UTC on the previous day.
    const d = parseServerDatetime('2026-10-05T07:00:00+11:00')
    assert.equal(d.toISOString(), '2026-10-04T20:00:00.000Z')
  })

  test('-HH:MM offset is honoured', () => {
    const d = parseServerDatetime('2026-10-05T07:00:00-05:00')
    assert.equal(d.toISOString(), '2026-10-05T12:00:00.000Z')
  })

  test('+HHMM (no colon) offset is honoured', () => {
    const d = parseServerDatetime('2026-10-05T07:00:00+1100')
    assert.equal(d.toISOString(), '2026-10-04T20:00:00.000Z')
  })
})


describe('parseServerDatetime — Melbourne wall-clock rendering', () => {
  test('the "Mondays – Term 4" case renders as Mon 6 pm AEDT under the fix', () => {
    // Correct stored value for Mon 5 Oct 2026 6 pm Melbourne (AEDT +11)
    // is 07:00 UTC. Under the buggy naive-parse it displayed as 7 am
    // local. The fix parses it as UTC; Melbourne-timezone Intl format
    // then converts back to 6 pm on the same day.
    const d = parseServerDatetime('2026-10-05T07:00:00')
    const fmt = new Intl.DateTimeFormat('en-AU', {
      timeZone: 'Australia/Melbourne',
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: 'numeric',
      minute: '2-digit',
    }).format(d)
    // en-AU produces "Mon, 5 Oct, 6:00 pm"
    assert.ok(fmt.includes('Mon'), `expected "Mon" in ${fmt}`)
    assert.ok(fmt.includes('5 Oct'), `expected "5 Oct" in ${fmt}`)
    assert.ok(fmt.includes('6:00'), `expected "6:00" in ${fmt}`)
    assert.ok(fmt.includes('pm'), `expected "pm" in ${fmt}`)
  })

  test('the Saturday-morning case renders as Sat 9 am AEDT under the fix', () => {
    // Sat 10 Oct 2026 9 am AEDT (+11 — DST is active from Sun 4 Oct)
    // = Fri 9 Oct 22:00 UTC. Naive stored value: "2026-10-09T22:00:00".
    // Melbourne-timezone rendering must show it as Sat 10 Oct 9 am.
    const d = parseServerDatetime('2026-10-09T22:00:00')
    const fmt = new Intl.DateTimeFormat('en-AU', {
      timeZone: 'Australia/Melbourne',
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: 'numeric',
      minute: '2-digit',
    }).format(d)
    assert.ok(fmt.includes('Sat'), `expected "Sat" in ${fmt}`)
    assert.ok(fmt.includes('10 Oct'), `expected "10 Oct" in ${fmt}`)
    assert.ok(fmt.includes('9:00'), `expected "9:00" in ${fmt}`)
    assert.ok(fmt.includes('am'), `expected "am" in ${fmt}`)
  })
})


// ---------------------------------------------------------------------------
// The Gathering-time sweep — EMBODY Term 4, the cases that were reported
// ---------------------------------------------------------------------------
//
// Every surface below stored the right instant and rendered it wrong: a
// bare ``new Date`` (which parses a naive string as LOCAL) formatted with
// no ``timeZone`` (which renders in the server's zone — UTC in
// production). These pin the canonical helpers the surfaces now call.

// @ts-expect-error - Node-native import path
import {
  formatGatheringDate,
  formatGatheringTimeFriendly,
  gatheringWeekdaySlot,
} from './dateTime.ts'

const MEL = 'Australia/Melbourne'

/** Mon 5 Oct 2026 6:00 pm AEDT — stored naive as 07:00 UTC. */
const MON_6PM = '2026-10-05T07:00:00'
/** Thu 8 Oct 2026 6:00 pm AEDT — stored naive as 07:00 UTC. */
const THU_6PM = '2026-10-08T07:00:00'
/** Sat 10 Oct 2026 9:00 am AEDT — stored naive as FRI 9 Oct 22:00 UTC. */
const SAT_9AM = '2026-10-09T22:00:00'


describe('formatGatheringTimeFriendly — the compact 12-hour style', () => {
  test('a 6 pm Melbourne Gathering reads as 6:00 pm, not 7:00 am', () => {
    // The reported symptom, in one assertion.
    assert.equal(formatGatheringTimeFriendly(MON_6PM, MEL), '6:00 pm')
  })

  test('the Thursday session reads the same way', () => {
    assert.equal(formatGatheringTimeFriendly(THU_6PM, MEL), '6:00 pm')
  })

  test('the Saturday morning session reads as 9:00 am', () => {
    assert.equal(formatGatheringTimeFriendly(SAT_9AM, MEL), '9:00 am')
  })

  test('the timezone argument is genuinely used', () => {
    // Same instant, two zones. If ``timeZone`` were ignored these would
    // match and the whole fix would be inert.
    assert.notEqual(
      formatGatheringTimeFriendly(MON_6PM, MEL),
      formatGatheringTimeFriendly(MON_6PM, 'UTC'),
    )
    assert.equal(formatGatheringTimeFriendly(MON_6PM, 'UTC'), '7:00 am')
  })

  test('a string that already carries Z is not double-shifted', () => {
    assert.equal(formatGatheringTimeFriendly('2026-10-05T07:00:00Z', MEL), '6:00 pm')
  })
})


describe('formatGatheringDate — the calendar date must not roll back', () => {
  test('Melbourne Saturday 9 am stays SATURDAY the 10th', () => {
    // The sharpest case: the stored instant is Friday the 9th in UTC.
    // Your World showed "Fri 9 Oct 10:00 pm".
    const { day, month } = formatGatheringDate(SAT_9AM, MEL)
    assert.equal(day, '10')
    assert.equal(month, 'OCT')
  })

  test('the Monday case keeps its own day', () => {
    const { day, month } = formatGatheringDate(MON_6PM, MEL)
    assert.equal(day, '05')
    assert.equal(month, 'OCT')
  })

  test('without the Collective timezone the Saturday case rolls back to Friday', () => {
    // Pins WHY the timezone has to be threaded: this is the old output.
    const { day } = formatGatheringDate(SAT_9AM, 'UTC')
    assert.equal(day, '09')
  })
})


describe('gatheringWeekdaySlot — grouping follows the Collective, not the runtime', () => {
  test('a Saturday 9 am Melbourne session groups under Saturday', () => {
    // Creator Studio filed this under Friday, because ``d.getDay()``
    // answers in the runtime's zone.
    const slot = gatheringWeekdaySlot(SAT_9AM, MEL)
    assert.equal(slot.weekdayIndex, 6, 'Saturday is 6, Sunday-first')
    assert.equal(slot.time24, '09:00')
  })

  test('the same instant groups under Friday in UTC — the old behaviour', () => {
    const slot = gatheringWeekdaySlot(SAT_9AM, 'UTC')
    assert.equal(slot.weekdayIndex, 5)
    assert.equal(slot.time24, '22:00')
  })

  test('a Monday 6 pm run groups under Monday at 18:00', () => {
    const slot = gatheringWeekdaySlot(MON_6PM, MEL)
    assert.equal(slot.weekdayIndex, 1)
    assert.equal(slot.time24, '18:00')
  })

  test('Monday and Thursday 6 pm sessions land in different groups', () => {
    const mon = gatheringWeekdaySlot(MON_6PM, MEL)
    const thu = gatheringWeekdaySlot(THU_6PM, MEL)
    assert.equal(thu.weekdayIndex, 4)
    assert.notEqual(
      `${mon.weekdayIndex}|${mon.time24}`,
      `${thu.weekdayIndex}|${thu.time24}`,
    )
  })

  test('every occurrence of one weekly run shares a key across a DST boundary', () => {
    // AEDT began Sun 4 Oct 2026. A run that starts in AEST and continues
    // into AEDT must stay ONE group — the stored UTC hour shifts, the
    // Melbourne wall clock does not.
    const beforeDst = '2026-10-01T08:00:00'  // Thu 1 Oct 6 pm AEST (+10)
    const afterDst  = THU_6PM                 // Thu 8 Oct 6 pm AEDT (+11)
    const a = gatheringWeekdaySlot(beforeDst, MEL)
    const b = gatheringWeekdaySlot(afterDst, MEL)
    assert.deepEqual(a, b, 'a weekly 6 pm run must not split at DST')
  })
})


describe('the two live cancelled Term 4 occurrences', () => {
  // Production verification named these exactly. Both kept
  // is_published=true, which is why the Series list needed a status
  // filter rather than a publication check — but they still have to
  // render in Melbourne wherever they are shown.

  test('Sat 31 Oct 2026 9:00 am Melbourne rolls back a day AND a month in UTC', () => {
    // 09:00 AEDT (+11) on Sat 31 Oct = 22:00 UTC on Fri 30 Oct.
    const stored = '2026-10-30T22:00:00'
    const { day, month } = formatGatheringDate(stored, MEL)
    assert.equal(day, '31')
    assert.equal(month, 'OCT')
    assert.equal(formatGatheringTimeFriendly(stored, MEL), '9:00 am')
    // Untreated, it would read as the 30th.
    assert.equal(formatGatheringDate(stored, 'UTC').day, '30')
  })

  test('Mon 2 Nov 2026 6:00 pm Melbourne keeps its day', () => {
    const stored = '2026-11-02T07:00:00'
    const { day, month } = formatGatheringDate(stored, MEL)
    assert.equal(day, '02')
    assert.equal(month, 'NOV')
    assert.equal(formatGatheringTimeFriendly(stored, MEL), '6:00 pm')
  })

  test('both group under their Melbourne weekday, not UTC’s', () => {
    assert.equal(gatheringWeekdaySlot('2026-10-30T22:00:00', MEL).weekdayIndex, 6)  // Sat
    assert.equal(gatheringWeekdaySlot('2026-11-02T07:00:00', MEL).weekdayIndex, 1)  // Mon
    // In UTC the Saturday one would file under Friday.
    assert.equal(gatheringWeekdaySlot('2026-10-30T22:00:00', 'UTC').weekdayIndex, 5)
  })
})
