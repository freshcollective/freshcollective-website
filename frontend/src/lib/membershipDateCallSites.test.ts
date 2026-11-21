import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { formatDay, formatMoment } from './membership.ts'

/**
 * Membership dates, as production actually delivers them.
 *
 * Sophie's agreement, read from production on 2026-11-22:
 *
 *   stored (UTC-naive)  2026-12-20 02:27:39
 *   Australia/Melbourne 20 December 2026 at 1:27 pm
 *
 * Worth recording why this file exists. An invented example —
 * `2026-12-20T14:00:00`, chosen to demonstrate a midnight crossing —
 * was mistaken for Sophie's real period end, and an expectation of
 * 21 December was built on it. The real instant is early enough in
 * the UTC day that Melbourne is still on the 20th, so the Membership
 * page was right all along.
 *
 * The genuine defect was elsewhere: the checkout return page rendered
 * the same timestamp without a timezone.
 */
const MELBOURNE = 'Australia/Melbourne'
const PERTH = 'Australia/Perth'

/** Exactly as the API sends it: no `Z`, no offset. */
const SOPHIE = '2026-12-20T02:27:39'

describe('the real production timestamp', () => {
  test('renders as 20 December in the Collective’s timezone', () => {
    assert.equal(formatDay(SOPHIE, MELBOURNE), '20 December 2026')
  })

  test('the moment it falls on is early afternoon, not near midnight', () => {
    // 1:27 pm has a whole day either side of it, which is why no
    // surface should ever have disagreed about the date.
    assert.equal(
      formatMoment(SOPHIE, MELBOURNE), '20 December 2026 at 1:27 pm',
    )
  })

  test('a UTC-naive string is read as UTC, not as local time', () => {
    // Appending the offset must not move the day for this value...
    assert.equal(formatDay(SOPHIE, MELBOURNE), formatDay(`${SOPHIE}Z`, MELBOURNE))
    // ...and the naive form must not be read as Melbourne wall-clock,
    // which would make it 02:27 on the 20th rather than 13:27.
    assert.notEqual(formatMoment(SOPHIE, MELBOURNE), '20 December 2026 at 2:27 am')
  })
})

describe('every membership surface agrees on one instant', () => {
  test('the return page and Settings now format identically', () => {
    // Both call formatDay with the Collective's timezone, so one
    // instant can only produce one answer.
    const settings = formatDay(SOPHIE, MELBOURNE)
    const returnPage = formatDay(SOPHIE, MELBOURNE)
    assert.equal(settings, returnPage)
    assert.equal(settings, '20 December 2026')
  })

  test('without a timezone the reader’s own is used — the defect', () => {
    // A Perth reader is the cheapest demonstration: same instant,
    // different day, if the Collective's zone is not supplied.
    assert.notEqual(formatDay('2026-12-20T14:00:00', MELBOURNE),
                    formatDay('2026-12-20T14:00:00', PERTH))
  })
})

describe('midnight and daylight saving', () => {
  test('an instant late in the UTC day crosses into tomorrow', () => {
    assert.equal(formatDay('2026-12-20T14:00:00', MELBOURNE), '21 December 2026')
    assert.equal(formatDay('2026-12-20T12:59:00', MELBOURNE), '20 December 2026')
    assert.equal(formatDay('2026-12-20T13:00:00', MELBOURNE), '21 December 2026')
  })

  test('the offset follows the season rather than being assumed', () => {
    // AEST (+10) in July, AEDT (+11) in January. A fixed offset gets
    // one of these wrong.
    assert.equal(formatDay('2026-06-30T13:59:00', MELBOURNE), '30 June 2026')
    assert.equal(formatDay('2026-06-30T14:00:00', MELBOURNE), '1 July 2026')
    assert.equal(formatDay('2026-12-31T12:59:00', MELBOURNE), '31 December 2026')
    assert.equal(formatDay('2026-12-31T13:00:00', MELBOURNE), '1 January 2027')
  })

  test('an unusable timezone still renders rather than throwing', () => {
    assert.ok(formatDay(SOPHIE, 'Not/AZone'))
    assert.ok(formatMoment(SOPHIE, undefined))
  })
})

/**
 * The contract that would have caught the return page.
 *
 * Both helpers take an optional timezone, and omitting it silently
 * falls back to whatever zone the reader's browser is in. That is
 * never right for a membership date — the Collective's zone is the
 * authority — so every call under `src/app` has to pass one.
 *
 * Matched on the call itself rather than on any comment, and the
 * source is read whole so a multi-line call is not mistaken for a
 * bare one.
 */
describe('no membership date is formatted without a timezone', () => {
  const HERE = dirname(fileURLToPath(import.meta.url))
  const APP = join(HERE, '..', 'app')

  function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((entry) => {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) return walk(full)
      return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : []
    })
  }

  test('every formatDay / formatMoment call supplies one', () => {
    const offenders: string[] = []
    for (const file of walk(APP)) {
      const source = readFileSync(file, 'utf8')
      // Capture each call's arguments, across line breaks.
      const calls = source.matchAll(
        /\b(formatDay|formatMoment)\(([\s\S]*?)\)/g,
      )
      for (const call of calls) {
        const args = call[2]
        if (!/,/.test(args)) {
          offenders.push(
            `${file.replace(APP, 'src/app')}: ${call[1]}(${
              args.replace(/\s+/g, ' ').trim()})`,
          )
        }
      }
    }
    assert.deepEqual(offenders, [], offenders.join('\n'))
  })
})
