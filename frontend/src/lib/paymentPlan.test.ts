/**
 * Unit tests for the FIP4A shared payment-plan display helpers.
 *
 * Run with the built-in Node test runner + Node's experimental
 * type stripping:
 *
 *   node --experimental-strip-types --test src/lib/paymentPlan.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import {
  cadenceAdjective,
  formatMoney,
  humanCadence,
  scheduleCtaLabel,
  scheduleDisclosureCopy,
  scheduleKindLabel,
  scheduleShortDescription,
  scheduleTotalLine,
  planConfirmationCopy,
} from './paymentPlan.ts'

const fin = (overrides = {}) => ({
  schedule_type: 'recurring_installments' as const,
  total_amount_cents: 6000,
  installment_amount_cents: 2000,
  installment_count: 3,
  interval: 'week',
  currency: 'AUD',
  name: 'Weekly plan',
  ...overrides,
})

const paif = (overrides = {}) => ({
  schedule_type: 'pay_in_full' as const,
  total_amount_cents: 60000,
  installment_amount_cents: null,
  installment_count: null,
  interval: null,
  currency: 'AUD',
  name: 'Pay in full',
  ...overrides,
})

describe('formatMoney', () => {
  // Delegates to the shared `formatMoneyCents`. The point of the change
  // is the third assertion: AUD and USD used to render identically as
  // "$20", so a member could not tell which currency they were about to
  // be charged in.
  test('renders AUD unambiguously, integer', () => {
    assert.equal(formatMoney(2000, 'AUD'), 'A$20')
  })
  test('renders AUD with 2 decimals when non-integer', () => {
    assert.equal(formatMoney(2050, 'AUD'), 'A$20.50')
  })
  test('renders USD distinctly from AUD', () => {
    assert.equal(formatMoney(2000, 'USD'), 'US$20')
    assert.notEqual(formatMoney(2000, 'USD'), formatMoney(2000, 'AUD'))
  })
  test('renders GBP and EUR with their own symbols', () => {
    assert.equal(formatMoney(2000, 'GBP'), '\u00a320')
    assert.equal(formatMoney(2000, 'EUR'), '\u20ac20')
  })
  test('keeps the ISO code for a currency outside the whitelist', () => {
    // Never a bare "20" — an amount with no currency reads as the
    // viewer's own.
    assert.equal(formatMoney(2000, 'JPY'), 'JPY 20')
  })
  test('renders zero', () => {
    assert.equal(formatMoney(0, 'AUD'), 'A$0')
  })
})

describe('humanCadence / cadenceAdjective', () => {
  test('week → weekly', () => {
    assert.equal(humanCadence('week'), 'weekly')
  })
  test('fortnight → fortnightly', () => {
    assert.equal(humanCadence('fortnight'), 'fortnightly')
  })
  test('month → monthly', () => {
    assert.equal(humanCadence('month'), 'monthly')
  })
  test('null returns null on humanCadence', () => {
    assert.equal(humanCadence(null), null)
  })
  test('cadenceAdjective falls back to "recurring" when interval is null', () => {
    assert.equal(cadenceAdjective(null), 'recurring')
  })
  test('leaves unknown intervals verbatim', () => {
    assert.equal(humanCadence('quarterly'), 'quarterly')
  })
})

describe('scheduleKindLabel', () => {
  test('returns "Payment plan" for finite instalments', () => {
    assert.equal(scheduleKindLabel(fin()), 'Payment plan')
  })
  test('returns "Pay in full" for pay-in-full', () => {
    assert.equal(scheduleKindLabel(paif()), 'Pay in full')
  })
})

describe('scheduleShortDescription', () => {
  test('formats a weekly x N plan', () => {
    assert.equal(scheduleShortDescription(fin()), '3 weekly payments of A$20')
  })
  test('formats a fortnightly plan', () => {
    assert.equal(
      scheduleShortDescription(fin({ interval: 'fortnight' })),
      '3 fortnightly payments of A$20',
    )
  })
  test('formats a monthly plan', () => {
    assert.equal(
      scheduleShortDescription(fin({ interval: 'month' })),
      '3 monthly payments of A$20',
    )
  })
  test('formats pay-in-full with "once"', () => {
    assert.equal(scheduleShortDescription(paif()), 'A$600 once')
  })
})

describe('scheduleTotalLine', () => {
  test('returns total for a finite plan when total_amount_cents is set', () => {
    assert.equal(scheduleTotalLine(fin()), 'A$60 total')
  })
  test('computes total from per x count when total is missing', () => {
    assert.equal(
      scheduleTotalLine(fin({ total_amount_cents: null })),
      'A$60 total',
    )
  })
  test('returns null for pay-in-full (total is in short description)', () => {
    assert.equal(scheduleTotalLine(paif()), null)
  })
})

describe('scheduleDisclosureCopy', () => {
  test('produces a complete finite-plan disclosure paragraph', () => {
    const copy = scheduleDisclosureCopy(fin())
    assert.ok(copy.includes('3 weekly payments of A$20'))
    assert.ok(copy.includes('A$60 total'))
    assert.ok(copy.includes('charged automatically'))
    assert.ok(copy.includes('Access begins after your first payment succeeds'))
  })
  test('produces a short pay-in-full disclosure', () => {
    const copy = scheduleDisclosureCopy(paif())
    assert.ok(copy.includes('A$600 paid now'))
    assert.ok(copy.includes('Access begins immediately'))
  })
})

describe('scheduleCtaLabel', () => {
  test('finite → "Start payment plan"', () => {
    assert.equal(scheduleCtaLabel(fin()), 'Start payment plan')
  })
  test('pay-in-full → "Pay $X"', () => {
    assert.equal(scheduleCtaLabel(paif()), 'Pay A$600')
  })
})


/**
 * Pre-Stripe confirmation copy.
 *
 * Stripe's setup-mode page cannot show an amount, so these strings
 * are the last plain statement of the commitment a member sees
 * before handing over a card. Every figure must come from the
 * schedule — nothing hard-coded to any Payment Option.
 */
describe('planConfirmationCopy', () => {
  test('reports the reported EMBODY plan correctly', () => {
    const copy = planConfirmationCopy(
      fin({
        installment_amount_cents: 3780,
        installment_count: 10,
        total_amount_cents: 37800,
        interval: 'week',
      }),
    )
    assert.ok(copy)
    assert.equal(copy.firstCharge, 'A$37.80 charged after setup')
    assert.equal(copy.thenLine, 'Then 9 weekly payments of A$37.80')
    assert.equal(copy.totalLine, 'A$378 total')
    assert.equal(copy.count, 10)
  })

  test('singularises the follow-up for a two-payment plan', () => {
    const copy = planConfirmationCopy(
      fin({
        installment_amount_cents: 3780,
        installment_count: 2,
        total_amount_cents: 7560,
      }),
    )
    assert.ok(copy)
    assert.equal(copy.thenLine, 'Then 1 weekly payment of A$37.80')
  })

  test('uses the schedule cadence, not a fixed word', () => {
    const fortnightly = planConfirmationCopy(
      fin({ interval: 'fortnight', installment_count: 5 }),
    )
    const monthly = planConfirmationCopy(
      fin({ interval: 'month', installment_count: 6 }),
    )
    assert.ok(fortnightly && monthly)
    assert.match(fortnightly.thenLine, /fortnightly payments/)
    assert.match(monthly.thenLine, /monthly payments/)
  })

  test('derives the total when the schedule has none stored', () => {
    const copy = planConfirmationCopy(
      fin({
        installment_amount_cents: 3780,
        installment_count: 10,
        total_amount_cents: null,
      }),
    )
    assert.ok(copy)
    assert.equal(copy.totalLine, 'A$378 total')
  })

  test('prefers the stored total over a derived one', () => {
    // A stored total that disagrees is a data problem, not something
    // this helper should paper over by silently recomputing.
    const copy = planConfirmationCopy(
      fin({
        installment_amount_cents: 2000,
        installment_count: 3,
        total_amount_cents: 5900,
      }),
    )
    assert.ok(copy)
    assert.equal(copy.totalLine, 'A$59 total')
  })

  test('respects the schedule currency', () => {
    const copy = planConfirmationCopy(
      fin({ currency: 'GBP', installment_amount_cents: 1000, installment_count: 4, total_amount_cents: 4000 }),
    )
    assert.ok(copy)
    // GBP now gets its own symbol rather than an ISO prefix.
    assert.match(copy.firstCharge, /\u00a310 charged after setup/)
  })

  test('returns null for pay-in-full', () => {
    assert.equal(planConfirmationCopy(paif()), null)
  })

  test('returns null when the figures are incomplete', () => {
    assert.equal(
      planConfirmationCopy(fin({ installment_amount_cents: null })),
      null,
    )
    assert.equal(
      planConfirmationCopy(fin({ installment_count: null })),
      null,
    )
  })
})

// ---------------------------------------------------------------------------
// Stage 4B — the last amount before Stripe, and the only one on Apple Pay
// ---------------------------------------------------------------------------

describe('planConfirmationCopy with a discount quote', () => {
  const twoByFive = {
    id: 's1',
    schedule_type: 'recurring_installments' as const,
    total_amount_cents: 1000,
    installment_amount_cents: 500,
    installment_count: 2,
    interval: 'month',
    currency: 'AUD',
  }

  function quote(over: Record<string, unknown> = {}) {
    return {
      valid: true,
      code: 'STAGE4TEST3',
      payment_mode: 'plan',
      currency: 'AUD',
      original_amount_cents: 1000,
      discount_amount_cents: 400,
      final_amount_cents: 600,
      installment_count: 2,
      installment_amount_cents: 300,
      final_installment_amount_cents: 300,
      ...over,
    } as never
  }

  test('without a quote it still describes the list price', () => {
    const c = planConfirmationCopy(twoByFive as never)!
    assert.equal(c.firstCharge, 'A$5 charged after setup')
    assert.equal(c.totalLine, 'A$10 total')
  })

  test('the production case: the member is told A$3, not A$5', () => {
    const c = planConfirmationCopy(twoByFive as never, quote())!
    assert.equal(c.firstCharge, 'A$3 charged after setup')
    assert.equal(c.thenLine, 'Then 1 monthly payment of A$3')
    assert.equal(c.totalLine, 'A$6 total')
  })

  test('an invalid quote falls back to the list price rather than guessing', () => {
    const c = planConfirmationCopy(twoByFive as never, { valid: false } as never)!
    assert.equal(c.firstCharge, 'A$5 charged after setup')
  })

  test('a pay-in-full quote never rewrites a plan', () => {
    const c = planConfirmationCopy(
      twoByFive as never, quote({ payment_mode: 'direct' }),
    )!
    assert.equal(c.firstCharge, 'A$5 charged after setup')
  })

  test('an uneven final instalment is disclosed, not averaged', () => {
    // 3 x A$50 less A$20 — §10's worked example.
    const threeByFifty = {
      ...twoByFive, total_amount_cents: 15000,
      installment_amount_cents: 5000, installment_count: 3,
    }
    const c = planConfirmationCopy(threeByFifty as never, quote({
      original_amount_cents: 15000, discount_amount_cents: 2000,
      final_amount_cents: 13000, installment_count: 3,
      installment_amount_cents: 4333, final_installment_amount_cents: 4334,
    }))!
    assert.equal(c.firstCharge, 'A$43.33 charged after setup')
    assert.equal(
      c.thenLine,
      'Then 1 monthly payment of A$43.33, and a final payment of A$43.34',
    )
    assert.equal(c.totalLine, 'A$130 total')
  })

  test('a two-payment uneven plan names the final payment alone', () => {
    const c = planConfirmationCopy(twoByFive as never, quote({
      final_amount_cents: 601, installment_amount_cents: 300,
      final_installment_amount_cents: 301,
    }))!
    assert.equal(c.firstCharge, 'A$3 charged after setup')
    assert.equal(c.thenLine, 'Then a final monthly payment of A$3.01')
    assert.equal(c.totalLine, 'A$6.01 total')
  })
})
