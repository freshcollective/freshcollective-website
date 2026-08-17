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
  test('renders AUD with $ prefix, integer', () => {
    assert.equal(formatMoney(2000, 'AUD'), '$20')
  })
  test('renders AUD with 2 decimals when non-integer', () => {
    assert.equal(formatMoney(2050, 'AUD'), '$20.50')
  })
  test('renders USD with $ prefix', () => {
    assert.equal(formatMoney(2000, 'USD'), '$20')
  })
  test('renders unknown currencies with ISO code prefix', () => {
    assert.equal(formatMoney(2000, 'EUR'), 'EUR 20')
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
    assert.equal(scheduleShortDescription(fin()), '3 weekly payments of $20')
  })
  test('formats a fortnightly plan', () => {
    assert.equal(
      scheduleShortDescription(fin({ interval: 'fortnight' })),
      '3 fortnightly payments of $20',
    )
  })
  test('formats a monthly plan', () => {
    assert.equal(
      scheduleShortDescription(fin({ interval: 'month' })),
      '3 monthly payments of $20',
    )
  })
  test('formats pay-in-full with "once"', () => {
    assert.equal(scheduleShortDescription(paif()), '$600 once')
  })
})

describe('scheduleTotalLine', () => {
  test('returns total for a finite plan when total_amount_cents is set', () => {
    assert.equal(scheduleTotalLine(fin()), '$60 total')
  })
  test('computes total from per x count when total is missing', () => {
    assert.equal(
      scheduleTotalLine(fin({ total_amount_cents: null })),
      '$60 total',
    )
  })
  test('returns null for pay-in-full (total is in short description)', () => {
    assert.equal(scheduleTotalLine(paif()), null)
  })
})

describe('scheduleDisclosureCopy', () => {
  test('produces a complete finite-plan disclosure paragraph', () => {
    const copy = scheduleDisclosureCopy(fin())
    assert.ok(copy.includes('3 weekly payments of $20'))
    assert.ok(copy.includes('$60 total'))
    assert.ok(copy.includes('charged automatically'))
    assert.ok(copy.includes('Access begins after your first payment succeeds'))
  })
  test('produces a short pay-in-full disclosure', () => {
    const copy = scheduleDisclosureCopy(paif())
    assert.ok(copy.includes('$600 paid now'))
    assert.ok(copy.includes('Access begins immediately'))
  })
})

describe('scheduleCtaLabel', () => {
  test('finite → "Start payment plan"', () => {
    assert.equal(scheduleCtaLabel(fin()), 'Start payment plan')
  })
  test('pay-in-full → "Pay $X"', () => {
    assert.equal(scheduleCtaLabel(paif()), 'Pay $600')
  })
})
