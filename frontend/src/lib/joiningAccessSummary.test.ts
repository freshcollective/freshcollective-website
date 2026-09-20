import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  additionalPaidTitles,
  buildJoiningAccessSummary,
  listPhrase,
} from './joiningAccessSummary.ts'
import type { JoiningOption } from '../types/platform.ts'

/**
 * What the Access card claims a purchase brings.
 *
 * The bug: on a purchase-required Collective the card described two
 * purchases — "Membership comes with a purchase", then "PAID
 * SEPARATELY: term access and session bookings are paid separately" —
 * when the single joining purchase grants both.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

function door(over: Partial<JoiningOption> = {}): JoiningOption {
  return {
    id: 'po_1', name: 'Awaken', description: null, buyer_note: null,
    price_cents: 18000, currency: 'AUD', payment_type: 'term_pass',
    term_start_date: null, term_end_date: null, schedules: [],
    included_titles: ['Term 4 2026', 'EMBODY In-Person Sessions', 'Home Practice'],
    sessions_per_week: 1, sessions_total: 10,
    ...over,
  } as JoiningOption
}

/** EMBODY's three live doors. */
const EMBODY_DOORS = [
  door({ id: 'a', name: 'Awaken', sessions_per_week: 1, sessions_total: 10 }),
  door({ id: 'b', name: 'Activate', sessions_per_week: 2, sessions_total: 20 }),
  door({ id: 'c', name: 'Empower', sessions_per_week: 3, sessions_total: 30 }),
]

describe('the joining purchase is described as one purchase', () => {
  test('it names membership and what comes with it', () => {
    const s = buildJoiningAccessSummary('EMBODY', EMBODY_DOORS)!
    assert.equal(
      s.sentence,
      'Your purchase brings you membership of EMBODY, plus access to '
      + 'Term 4 2026, EMBODY In-Person Sessions and Home Practice.',
    )
  })

  test('it never implies a second payment', () => {
    const s = buildJoiningAccessSummary('EMBODY', EMBODY_DOORS)!
    for (const phrase of ['paid separately', 'separately', 'additional purchase']) {
      assert.ok(!s.sentence.toLowerCase().includes(phrase), phrase)
    }
  })

  test('session allowance is stated as the range it really is', () => {
    // Claiming any single number would be true of one tier only.
    const s = buildJoiningAccessSummary('EMBODY', EMBODY_DOORS)!
    assert.equal(
      s.allowanceNote,
      'Session bookings range from 1 to 3 a week, depending on the option you choose.',
    )
  })

  test('a single allowance is stated plainly', () => {
    const s = buildJoiningAccessSummary('EMBODY', [door({ sessions_per_week: 1 })])!
    assert.equal(s.allowanceNote, 'Includes 1 session a week.')
  })

  test('no allowance means no allowance sentence', () => {
    const s = buildJoiningAccessSummary('The Grove', [
      door({ included_titles: ['Foundations'], sessions_per_week: null }),
    ])!
    assert.equal(s.allowanceNote, null)
  })

  test('doors granting different things say so rather than generalising', () => {
    const s = buildJoiningAccessSummary('The Grove', [
      door({ id: 'x', included_titles: ['Term 4'] }),
      door({ id: 'y', included_titles: ['Term 4', 'Deep Dive'] }),
    ])!
    assert.ok(s.varies)
    assert.match(s.sentence, /what each option includes is shown with it below/)
  })

  test('doors granting the same things do not', () => {
    assert.equal(buildJoiningAccessSummary('EMBODY', EMBODY_DOORS)!.varies, false)
  })

  test('a door with no grants still says something true', () => {
    const s = buildJoiningAccessSummary('EMBODY', [door({ included_titles: [] })])!
    assert.equal(s.sentence, 'Your purchase brings you into EMBODY.')
  })

  test('no doors means no summary to make', () => {
    assert.equal(buildJoiningAccessSummary('EMBODY', []), null)
  })

  test('titles are de-duplicated across doors, in first-seen order', () => {
    const s = buildJoiningAccessSummary('EMBODY', EMBODY_DOORS)!
    assert.deepEqual(s.includedTitles,
      ['Term 4 2026', 'EMBODY In-Person Sessions', 'Home Practice'])
  })
})

describe('what is genuinely sold on top', () => {
  test('nothing, when the doors already grant it', () => {
    // EMBODY. A "paid separately" line here invents a purchase.
    assert.deepEqual(
      additionalPaidTitles(
        ['EMBODY In-Person Sessions', 'Home Practice'],
        ['Term 4 2026', 'EMBODY In-Person Sessions', 'Home Practice'],
      ),
      [],
    )
  })

  test('a paid pathway outside the doors is still representable', () => {
    assert.deepEqual(
      additionalPaidTitles(
        ['Home Practice', 'Advanced Retreat'],
        ['Term 4 2026', 'Home Practice'],
      ),
      ['Advanced Retreat'],
    )
  })

  test('matching ignores case and surrounding space', () => {
    assert.deepEqual(
      additionalPaidTitles(['  home practice '], ['Home Practice']), [],
    )
  })
})

describe('list phrasing', () => {
  test('one, two and three read naturally', () => {
    assert.equal(listPhrase(['A']), 'A')
    assert.equal(listPhrase(['A', 'B']), 'A and B')
    assert.equal(listPhrase(['A', 'B', 'C']), 'A, B and C')
  })

  test('blanks do not leave dangling punctuation', () => {
    assert.equal(listPhrase(['A', '', '  ', 'B']), 'A and B')
    assert.equal(listPhrase([]), '')
  })
})

describe('the Access card', () => {
  const page = () => read('app/spaces/[slug]/about/page.tsx')

  test('an open Collective keeps Included / Paid separately', () => {
    const src = page()
    assert.match(src, />Included</)
    assert.match(src, />Paid separately</)
    assert.match(src, /effectiveHasPaidContent \? \(/)
  })

  test('a purchase-required Collective gets the joining model instead', () => {
    const src = page()
    assert.match(src, /isPurchaseRequired \? \(/)
    assert.match(src, />\s*Your purchase includes\s*</)
    // And it is checked first, so the old block cannot win.
    assert.ok(src.indexOf('isPurchaseRequired ? (') < src.indexOf('effectiveHasPaidContent ? ('))
  })

  test('the summary is derived from grants, not from the creator summaries', () => {
    const src = page()
    assert.match(src, /buildJoiningAccessSummary\(space\.name, joiningOptions\)/)
  })

  test('creator copy supports the derived list rather than replacing it', () => {
    // included_access_summary describes what comes with membership
    // itself; it is shown beneath, never as the authority.
    const src = page()
    const block = src.slice(src.indexOf('isPurchaseRequired ? ('),
                            src.indexOf('effectiveHasPaidContent ? ('))
    assert.ok(block.includes('included_access_summary'))
    assert.ok(!block.includes('paidSeparatelyCopy'),
      'paid_content_summary must not appear under a joining purchase')
  })

  test('“Also available separately” only when something truly is', () => {
    const src = page()
    assert.match(src, /additionalPaid\.length > 0 &&/)
    assert.match(src, /additionalPaidTitles\(/)
  })
})
