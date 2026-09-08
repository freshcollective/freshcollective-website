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
import { parseServerDatetime } from './dateTime.ts'


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
