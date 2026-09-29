import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  describeDiscountShape,
  describeTransactionDiscount,
  type DiscountedTransaction,
} from './discountDisplay.ts'

const DISCOUNTED: DiscountedTransaction = {
  currency: 'AUD',
  gross_amount_cents: 15300,
  discount_code: 'FAMILY50',
  discount_original_amount_cents: 30600,
  discount_amount_cents: 15300,
  discount_type: 'percentage',
  discount_percent_bps: 5000,
}

describe('explaining a discounted charge', () => {
  test('the EMBODY reference case reads correctly', () => {
    const d = describeTransactionDiscount(DISCOUNTED)

    assert.deepEqual(d, {
      label: 'FAMILY50 · 50% off',
      originalAmount: 'A$306',
      discountAmount: 'A$153',
      amountPaid: 'A$153',
    })
  })

  test('a fixed-dollar discount is worded as an amount, not a percentage', () => {
    const d = describeTransactionDiscount({
      ...DISCOUNTED,
      gross_amount_cents: 25600,
      discount_amount_cents: 5000,
      discount_type: 'fixed_amount',
      discount_percent_bps: null,
      discount_code: 'FIFTYOFF',
    })

    assert.equal(d?.label, 'FIFTYOFF · A$50 off')
    assert.equal(d?.amountPaid, 'A$256')
  })

  test('the amount paid comes from the ledger, not from subtraction', () => {
    // Deliberately inconsistent inputs: if the display derived the paid
    // amount it would say A$1, and the creator would be shown a figure
    // that never appeared on anyone's card.
    const d = describeTransactionDiscount({
      ...DISCOUNTED, gross_amount_cents: 9999,
    })

    assert.equal(d?.amountPaid, 'A$99.99')
  })

  test('a fractional percentage keeps its fraction', () => {
    assert.equal(
      describeDiscountShape({ ...DISCOUNTED, discount_percent_bps: 1250 }),
      '12.5% off',
    )
  })

  test('a whole percentage shows no decimals', () => {
    assert.equal(
      describeDiscountShape({ ...DISCOUNTED, discount_percent_bps: 2500 }),
      '25% off',
    )
  })
})

describe('transactions with no discount', () => {
  test('a historical transaction renders nothing extra', () => {
    // The important one: every transaction predating the feature must
    // look exactly as it did before.
    const historical: DiscountedTransaction = {
      currency: 'AUD', gross_amount_cents: 30600,
    }

    assert.equal(describeTransactionDiscount(historical), null)
  })

  test('explicit nulls are also nothing', () => {
    assert.equal(describeTransactionDiscount({
      currency: 'AUD', gross_amount_cents: 30600,
      discount_code: null, discount_original_amount_cents: null,
      discount_amount_cents: null,
    }), null)
  })

  test('a half-filled snapshot renders nothing rather than a gap', () => {
    // A code with no figures cannot be explained, and "you saved " with a
    // blank is worse than silence.
    assert.equal(describeTransactionDiscount({
      currency: 'AUD', gross_amount_cents: 15300,
      discount_code: 'FAMILY50',
    }), null)
    assert.equal(describeTransactionDiscount({
      currency: 'AUD', gross_amount_cents: 15300,
      discount_code: 'FAMILY50', discount_original_amount_cents: 30600,
    }), null)
  })

  test('an unknown discount shape still names the code', () => {
    const d = describeTransactionDiscount({
      ...DISCOUNTED, discount_type: 'something_new', discount_percent_bps: null,
    })

    assert.equal(d?.label, 'FAMILY50')
    assert.equal(d?.originalAmount, 'A$306')
  })
})
