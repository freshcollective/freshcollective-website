/**
 * Pathway checkout copy — generic, and provably so.
 *
 * The payment-options branch of the checkout page used to hard-code
 * EMBODY's own particulars (a ten-week term, Monday/Thursday/Saturday,
 * South Croydon) and show them on every Pathway that reached that mode,
 * including a bare Test Pathway. These tests cover both halves: the copy
 * that replaced it is driven by the payload, and the banned strings
 * cannot reappear in either the helper or the page that renders it.
 *
 * The source scan strips comments first. The prose above names the very
 * strings being banned, and a blunt match over the raw files would fail
 * on its own documentation.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
// @ts-expect-error - Node-native import
import { includedLines, paymentCardCopy } from './pathwayCheckoutCopy.ts'

const _here = dirname(fileURLToPath(import.meta.url))

function codeOf(path: string): string {
  return readFileSync(path, 'utf-8')
    .replace(/\/\*[^]*?\*\//g, '')
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n')
}

const HELPER = codeOf(join(_here, 'pathwayCheckoutCopy.ts'))
const PAGE = codeOf(join(
  _here, '..', 'app', 'spaces', '[slug]', 'pathways', '[pathway-slug]',
  'checkout', 'page.tsx',
))

const option = (overrides: Record<string, unknown> = {}) => ({
  id: 'po_1',
  name: '$2 Option',
  description: null,
  payment_type: 'one_time',
  status: 'published',
  term_start_date: null,
  term_end_date: null,
  sessions_per_week: null,
  total_sessions: null,
  price_per_session_cents: null,
  calculated_total_cents: 200,
  override_total_cents: null,
  effective_price_cents: 200,
  currency: 'AUD',
  buyer_note: null,
  position: 0,
  schedules: [],
  ...overrides,
})

const schedule = (overrides: Record<string, unknown> = {}) => ({
  id: 'pos_1',
  name: 'Pay in full',
  description: null,
  schedule_type: 'pay_in_full',
  total_amount_cents: 200,
  installment_amount_cents: null,
  installment_count: null,
  interval: null,
  currency: 'AUD',
  buyer_note: null,
  position: 0,
  is_member_checkoutable: true,
  ...overrides,
})


describe('no EMBODY particulars survive anywhere on this surface', () => {
  const BANNED = [
    'term pass',
    '10-week',
    'ten-week',
    'South Croydon',
    'Monday',
    'Thursday',
    'Saturday',
    'In-person sessions',
    'enrolment',
    'EMBODY',
  ]

  for (const phrase of BANNED) {
    test(`the helper never says "${phrase}"`, () => {
      assert.ok(
        !HELPER.toLowerCase().includes(phrase.toLowerCase()),
        `"${phrase}" is one collective's particular, not a fact about payment options`,
      )
    })

    test(`the checkout page never says "${phrase}"`, () => {
      assert.ok(
        !PAGE.toLowerCase().includes(phrase.toLowerCase()),
        `"${phrase}" must come from the creator's configured Payment Options`,
      )
    })
  }

  test('the page no longer builds its own included list', () => {
    assert.match(
      PAGE,
      /includedLines\(pathway\)\.map/,
      'the list must come from the shared helper, not an inline array',
    )
  })
})


describe('paymentCardCopy — driven by the payload', () => {
  test('a legacy pathway is told it pays once, with no term language', () => {
    const copy = paymentCardCopy('legacy', [])
    assert.equal(copy.title, 'Pay in full')
    assert.match(copy.blurb, /unlock this pathway/)
  })

  test('a payment-options pathway points at the selector', () => {
    const copy = paymentCardCopy('payment_options', [option()])
    assert.equal(copy.title, 'Payment options')
    assert.match(copy.blurb, /Choose the option/)
  })

  test('instalments are mentioned only when a schedule offers them', () => {
    const without = paymentCardCopy('payment_options', [
      option({ schedules: [schedule()] }),
    ])
    assert.ok(!without.blurb.toLowerCase().includes('instalment'))

    const withPlan = paymentCardCopy('payment_options', [
      option({
        schedules: [schedule({
          schedule_type: 'recurring_installments', installment_count: 4,
        })],
      }),
    ])
    assert.match(withPlan.blurb, /instalments/)
  })

  test('the old copy asserted pay-in-full on pathways that have plans', () => {
    // "Pay in full to lock in your term" was shown regardless.
    const withPlan = paymentCardCopy('payment_options', [
      option({ schedules: [schedule({ installment_count: 3 })] }),
    ])
    assert.ok(!withPlan.blurb.toLowerCase().includes('pay in full'))
  })

  test('no options yet matches the selector’s own empty state', () => {
    const copy = paymentCardCopy('payment_options', [])
    assert.match(copy.blurb, /coming soon/)
  })

  test('a missing options array is not a crash', () => {
    assert.ok(paymentCardCopy('payment_options', undefined).blurb.length > 0)
    assert.ok(paymentCardCopy(undefined, undefined).title.length > 0)
  })
})


describe('includedLines — pathway-level facts only', () => {
  test('the step count is used when there is one', () => {
    assert.deepEqual(includedLines({ step_count: 7 })[0], 'Access to all 7 pathway steps')
  })

  test('zero steps reads as a sentence, not a gap', () => {
    // The old string produced "Access to all  pathway steps".
    const first = includedLines({ step_count: 0 })[0]
    assert.ok(!first.includes('  '), `double space in: ${first}`)
    assert.match(first, /every step in this pathway/)
  })

  test('the same list serves both pricing modes', () => {
    // A single shared list cannot be true of every Option at once,
    // which is how one collective's copy came to be shown to others.
    assert.deepEqual(includedLines({ step_count: 3 }), includedLines({ step_count: 3 }))
    assert.equal(includedLines({ step_count: 3 }).length, 3)
  })

  test('a missing pathway does not throw', () => {
    assert.equal(includedLines(undefined).length, 3)
  })
})
