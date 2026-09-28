/**
 * Discount codes in Creator language: conversion and display.
 *
 * The API speaks basis points and minor units; a Creator types 50 and
 * $25. Every conversion lives in one module so a form and a list cannot
 * disagree about what 5000 means, and these are the tests that hold it
 * to that — the React surfaces are unreachable by this runner.
 *
 *   node --experimental-strip-types --test src/lib/discountCodes.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import {
  MAX_PERCENT,
  bpsToPercent,
  centsToDollars,
  describeStatus,
  dollarsToCents,
  emptyForm,
  formFromCode,
  formatDiscountValue,
  formatExpiry,
  formatScope,
  formatUsage,
  normaliseCodeInput,
  percentToBps,
  toCreatePayload,
  toUpdatePayload,
  validateForm,
} from './discountCodes.ts'

function code(over: Record<string, unknown> = {}) {
  return {
    id: 'dc_1', space_id: 's_1', code: 'FAMILY50',
    discount_type: 'percentage', percent_bps: 5000, amount_cents: null,
    currency: null, scope_kind: 'space', scope_id: null,
    scope_payment_option_name: null, is_active: true,
    expires_on: null, expires_at: null,
    max_redemptions: null, redemption_count: 0,
    definition_editable: true, deletable: true,
    created_at: '2026-09-28T00:00:00', updated_at: '2026-09-28T00:00:00',
    ...over,
  }
}


describe('units are converted at the boundary, never shown raw', () => {
  test('a Creator types 50 and the API receives 5000', () => {
    assert.equal(percentToBps('50'), 5000)
    assert.equal(percentToBps(50), 5000)
  })

  test('fractional percentages survive the round trip', () => {
    assert.equal(percentToBps('25.5'), 2550)
    assert.equal(bpsToPercent(2550), 25.5)
  })

  test('dollars become cents, rounded not truncated', () => {
    assert.equal(dollarsToCents('25.50'), 2550)
    assert.equal(dollarsToCents('0.015'), 2)     // 1.5c → 2c
    assert.equal(centsToDollars(2550), 25.5)
  })

  test('nonsense input does not become a silent zero', () => {
    assert.ok(Number.isNaN(percentToBps('abc')))
    assert.ok(Number.isNaN(dollarsToCents('')))
  })

  test('the payload carries API units, not Creator units', () => {
    const values = { ...emptyForm(), code: 'family50', percent: '50' }
    const payload = toCreatePayload(values)

    assert.equal(payload.percent_bps, 5000)
    assert.equal(payload.code, 'FAMILY50')
    assert.equal(payload.amount_cents, null)
  })

  test('a fixed-amount payload carries cents and a currency', () => {
    const values = {
      ...emptyForm(), code: 'TAKE25', discountType: 'fixed_amount',
      amount: '25.50', currency: 'aud',
    }
    const payload = toCreatePayload(values)

    assert.equal(payload.amount_cents, 2550)
    assert.equal(payload.currency, 'AUD')
    assert.equal(payload.percent_bps, null)
  })
})


describe('the code field normalises visibly as it is typed', () => {
  test('lower and mixed case become capitals', () => {
    assert.equal(normaliseCodeInput('family50'), 'FAMILY50')
    assert.equal(normaliseCodeInput('Family50'), 'FAMILY50')
  })

  test('characters the API would refuse are dropped as you type', () => {
    assert.equal(normaliseCodeInput('family 50!'), 'FAMILY50')
    assert.equal(normaliseCodeInput('take-25_off'), 'TAKE-25_OFF')
  })
})


describe('display speaks Creator, not schema', () => {
  test('a percentage reads as a percentage', () => {
    assert.equal(formatDiscountValue(code()), '50%')
    assert.equal(formatDiscountValue(code({ percent_bps: 2550 })), '25.5%')
    assert.equal(formatDiscountValue(code({ percent_bps: 9900 })), '99%')
  })

  test('a fixed amount reads as money with its currency', () => {
    const fixed = code({
      discount_type: 'fixed_amount', percent_bps: null,
      amount_cents: 2500, currency: 'AUD',
    })
    assert.equal(formatDiscountValue(fixed), 'A$25.00 AUD')
  })

  test('an unknown currency still renders rather than breaking', () => {
    const fixed = code({
      discount_type: 'fixed_amount', percent_bps: null,
      amount_cents: 2500, currency: 'XYZ',
    })
    assert.equal(formatDiscountValue(fixed), '25.00 XYZ')
  })

  test('scope reads as a place or an offer name', () => {
    assert.equal(formatScope(code()), 'Entire Collective')
    assert.equal(
      formatScope(code({ scope_kind: 'payment_option', scope_payment_option_name: 'Activate' })),
      'Activate',
    )
  })

  test('usage is a sentence, not a raw count', () => {
    assert.equal(formatUsage(code({ redemption_count: 0 })), '0 uses')
    assert.equal(formatUsage(code({ redemption_count: 1 })), '1 use')
    assert.equal(formatUsage(code({ redemption_count: 3, max_redemptions: 25 })), '3 of 25 used')
  })

  test('expiry is a date or nothing', () => {
    assert.equal(formatExpiry(null), null)
    assert.equal(formatExpiry('2026-10-31'), '31 Oct 2026')
  })
})


describe('status says what a Creator needs, not just is_active', () => {
  const now = new Date('2026-10-01T00:00:00Z')

  test('an available code is Active', () => {
    assert.equal(describeStatus(code(), now).label, 'Active')
  })

  test('a switched-off code is Inactive', () => {
    assert.equal(describeStatus(code({ is_active: false }), now).label, 'Inactive')
  })

  test('a past end date reads as Expired even while switched on', () => {
    const s = describeStatus(code({ expires_on: '2026-09-01', expires_at: '2026-09-01T14:00:00' }), now)
    assert.equal(s.label, 'Expired')
    assert.ok(s.detail)
  })

  test('a filled-up code reads as Fully used, not Active', () => {
    // "Active" beside "25 of 25 used" would be a contradiction the
    // Creator has to resolve themselves.
    const s = describeStatus(code({ max_redemptions: 25, redemption_count: 25 }), now)
    assert.equal(s.label, 'Fully used')
  })

  test('one use remaining is still Active', () => {
    const s = describeStatus(code({ max_redemptions: 25, redemption_count: 24 }), now)
    assert.equal(s.label, 'Active')
  })

  test('switched off wins over every other reason', () => {
    const s = describeStatus(
      code({ is_active: false, max_redemptions: 1, redemption_count: 1 }), now,
    )
    assert.equal(s.label, 'Inactive')
  })
})


describe('the form refuses the obvious mistakes before a round trip', () => {
  test('a code is required', () => {
    assert.match(validateForm({ ...emptyForm(), percent: '50' }) ?? '', /FAMILY50/)
  })

  test('100% is not offered — it is a complimentary pass', () => {
    const problem = validateForm({ ...emptyForm(), code: 'FREE', percent: '100' })
    assert.match(problem ?? '', /99%/)
    assert.match(problem ?? '', /complimentary pass/)
  })

  test('99% is allowed', () => {
    assert.equal(validateForm({ ...emptyForm(), code: 'NEARLY', percent: '99' }), null)
  })

  test('zero and negative percentages are refused', () => {
    for (const percent of ['0', '-10']) {
      assert.ok(validateForm({ ...emptyForm(), code: 'X', percent }))
    }
  })

  test('a fixed amount needs a value above zero', () => {
    const base = { ...emptyForm(), code: 'X', discountType: 'fixed_amount' as const }
    assert.ok(validateForm({ ...base, amount: '0' }))
    assert.equal(validateForm({ ...base, amount: '25' }), null)
  })

  test('a scoped code must name its Payment Option', () => {
    const problem = validateForm({
      ...emptyForm(), code: 'X', percent: '50',
      scope: 'payment_option', paymentOptionId: '',
    })
    assert.match(problem ?? '', /which Payment Option/)
  })

  test('a limit must be a whole number of at least one', () => {
    const base = { ...emptyForm(), code: 'X', percent: '50' }
    assert.ok(validateForm({ ...base, maxRedemptions: '0' }))
    assert.ok(validateForm({ ...base, maxRedemptions: '2.5' }))
    assert.equal(validateForm({ ...base, maxRedemptions: '25' }), null)
  })

  test('an empty limit means no limit, which is allowed', () => {
    assert.equal(
      validateForm({ ...emptyForm(), code: 'X', percent: '50', maxRedemptions: '' }),
      null,
    )
  })

  test('MAX_PERCENT is the API ceiling, not a separate opinion', () => {
    assert.equal(MAX_PERCENT, 99)
  })
})


describe('a redeemed code sends only what it may still change', () => {
  test('the definition is left out of the patch entirely', () => {
    // The form disables those fields; this makes sure a stale client
    // cannot send them either and earn a 409 for something the Creator
    // did not try to do.
    const values = formFromCode(code({ definition_editable: false }))
    const payload = toUpdatePayload(values, false)

    assert.deepEqual(Object.keys(payload).sort(), [
      'expires_on', 'is_active', 'max_redemptions',
    ])
  })

  test('an unredeemed code sends the whole definition', () => {
    const payload = toUpdatePayload(formFromCode(code()), true)

    assert.ok('code' in payload)
    assert.ok('percent_bps' in payload)
    assert.ok('scope_kind' in payload)
  })

  test('operational fields are still editable when frozen', () => {
    const values = { ...formFromCode(code({ definition_editable: false })), maxRedemptions: '50' }
    const payload = toUpdatePayload(values, false)

    assert.equal(payload.max_redemptions, 50)
    assert.equal(payload.is_active, true)
  })

  test('the form round-trips an existing code', () => {
    const values = formFromCode(code({
      percent_bps: 2550, expires_on: '2026-10-31', expires_at: '2026-10-31T13:00:00',
    }))

    assert.equal(values.code, 'FAMILY50')
    assert.equal(values.percent, '25.5')
    assert.equal(values.expiresAt, '2026-10-31')
  })

  test('an end date is sent as a plain day, for the server to place', () => {
    // A Creator choosing 31 Oct means the code works all of 31 Oct
    // where the Collective is. Only the server knows where that is, so
    // this sends the day and nothing more — no invented time, no
    // timezone suffix, nothing that depends on this browser's clock.
    const payload = toCreatePayload({
      ...emptyForm(), code: 'X', percent: '50', expiresAt: '2026-10-31',
    })
    assert.equal(payload.expires_on, '2026-10-31')
    assert.ok(!('expires_at' in payload))
  })

  test('no end date sends null rather than an empty string', () => {
    const payload = toCreatePayload({ ...emptyForm(), code: 'X', percent: '50' })
    assert.equal(payload.expires_on, null)
  })

  test('the displayed end date is the day chosen, in every browser timezone', () => {
    // The old bug: a Melbourne code ending 31 Oct displayed as 1 Nov to
    // anyone whose browser was behind it. ``expires_on`` is already the
    // Collective's day, so rendering must not convert it at all.
    const previous = process.env.TZ
    const rendered = new Set<string>()
    // A control: something that DOES depend on the browser timezone, so
    // a test that silently stopped switching zones cannot pass anyway.
    const naive = new Set<string>()

    try {
      for (const TZ of ['UTC', 'Pacific/Kiritimati', 'Pacific/Midway', 'Asia/Kolkata']) {
        process.env.TZ = TZ
        rendered.add(String(formatExpiry('2026-10-31')))
        naive.add(new Date('2026-10-31T13:00:00Z').toISOString().slice(0, 10)
          + new Date('2026-10-31T13:00:00Z').getDate())
      }
    } finally {
      process.env.TZ = previous
    }

    assert.ok(naive.size > 1, 'timezone switching is not taking effect')
    assert.deepEqual([...rendered], ['31 Oct 2026'])
  })
})
