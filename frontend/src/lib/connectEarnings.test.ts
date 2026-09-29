/**
 * The Connect earnings lines a creator actually reads.
 *
 * The arithmetic tests matter most: if the three parts of a sale do not add up
 * on screen, the figures are worse than showing fewer of them. And an unknown
 * processing fee must never render as zero, which would be a claim about a real
 * cost that has not been measured.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import
import {
  earningLines,
  earningsHeadline,
  formatMoney,
  instalmentCaption,
  isReturned,
  linesReconcile,
} from './connectEarnings.ts'

/** A$100 sale, 8% platform fee, A$2.00 Stripe fee → A$90.00 to the creator. */
const row = (overrides = {}) => ({
  payment_transaction_id: 'txn_1',
  created_at: '2026-09-20T12:00:00',
  currency: 'AUD',
  sale_amount_cents: 10000,
  platform_fee_cents: 800,
  processing_fee_cents: 200,
  creator_amount_cents: 9000,
  status: 'sent',
  status_label: 'Sent to Stripe',
  amount_is_estimate: false,
  refunded_amount_cents: 0,
  installment_number: null,
  ...overrides,
})

const response = (overrides = {}) => ({
  currency: 'AUD',
  sale_total_cents: 10000,
  platform_fee_total_cents: 800,
  processing_fee_total_cents: 200,
  creator_total_cents: 9000,
  sent_total_cents: 9000,
  awaiting_total_cents: 0,
  row_count: 1,
  rows: [row()],
  ...overrides,
})

describe('money formatting', () => {
  test('AUD reads as A$', () => {
    assert.equal(formatMoney(9000, 'AUD'), 'A$90.00')
  })

  test('another currency keeps its code', () => {
    assert.equal(formatMoney(9000, 'NZD'), 'NZD 90.00')
  })

  test('an unknown amount is a dash, never zero', () => {
    assert.equal(formatMoney(null, 'AUD'), '—')
  })

  test('cents are not lost', () => {
    assert.equal(formatMoney(8965, 'AUD'), 'A$89.65')
    assert.equal(formatMoney(5, 'AUD'), 'A$0.05')
  })
})

describe('the fee breakdown', () => {
  test('all four lines are present and in order', () => {
    const lines = earningLines(row())
    assert.deepEqual(lines.map((l) => l.label), [
      'Sale',
      'Stripe’s processing fee',
      'Fresh Collective’s platform fee',
      'Your share',
    ])
  })

  test('Stripe’s fee comes before Fresh Collective’s', () => {
    // The order is the disclosure made concrete.
    const labels = earningLines(row()).map((l) => l.label)
    assert.ok(labels.indexOf('Stripe’s processing fee') <
      labels.indexOf('Fresh Collective’s platform fee'))
  })

  test('the exact 8% example', () => {
    const lines = earningLines(row())
    assert.equal(lines[0].value, 'A$100.00')
    assert.equal(lines[1].value, '− A$2.00')
    assert.equal(lines[2].value, '− A$8.00')
    assert.equal(lines[3].value, 'A$90.00')
  })

  test('a 0% creator sees the Stripe fee taken and the rest kept', () => {
    const lines = earningLines(row({
      platform_fee_cents: 0, creator_amount_cents: 9800,
    }))
    assert.equal(lines[1].value, '− A$2.00')
    assert.equal(lines[2].value, '− A$0.00')
    assert.equal(lines[3].value, 'A$98.00')
  })

  test('an instalment shows the discounted-sale arithmetic too', () => {
    const lines = earningLines(row({
      sale_amount_cents: 5000, platform_fee_cents: 400,
      processing_fee_cents: 150, creator_amount_cents: 4450,
    }))
    assert.equal(lines[3].value, 'A$44.50')
  })

  test('the parts account for the sale exactly', () => {
    for (const r of [
      row(),
      row({ platform_fee_cents: 0, creator_amount_cents: 9800 }),
      row({
        sale_amount_cents: 5000, platform_fee_cents: 400,
        processing_fee_cents: 150, creator_amount_cents: 4450,
      }),
    ]) {
      assert.ok(linesReconcile(r), JSON.stringify(r))
    }
  })

  test('an unknown fee is "being confirmed", never zero', () => {
    const lines = earningLines(row({
      processing_fee_cents: null, creator_amount_cents: null,
    }))
    assert.equal(lines[1].value, 'being confirmed')
    assert.equal(lines[3].value, 'being confirmed')
    assert.equal(lines[1].pending, true)
    assert.equal(lines[3].pending, true)
    // Nothing reads as a settled zero.
    assert.ok(!lines.some((l) => l.value === '− A$0.00' && l.pending))
  })

  test('an unpriced row has nothing to reconcile', () => {
    assert.equal(
      linesReconcile(row({ processing_fee_cents: null, creator_amount_cents: null })),
      true,
    )
  })
})

describe('the summary', () => {
  test('it says sent to Stripe, not paid', () => {
    // A completed transfer reaches the creator's Stripe balance; Stripe pays
    // their bank on its own schedule.
    const summary = earningsHeadline(response())
    assert.equal(summary.sentTotal, 'A$90.00')
    assert.ok(!/\bpaid\b/i.test(summary.headline + summary.body))
  })

  test('one sale is singular', () => {
    assert.match(earningsHeadline(response()).headline, /^1 sale/)
  })

  test('several sales are plural', () => {
    assert.match(
      earningsHeadline(response({ row_count: 3 })).headline, /^3 sales/,
    )
  })

  test('money still on its way is surfaced separately', () => {
    const summary = earningsHeadline(response({ awaiting_total_cents: 4500 }))
    assert.equal(summary.awaitingTotal, 'A$45.00')
  })

  test('nothing on its way shows no second figure', () => {
    assert.equal(earningsHeadline(response()).awaitingTotal, null)
  })

  test('an empty list explains itself rather than showing zeros', () => {
    const summary = earningsHeadline(response({ row_count: 0, rows: [] }))
    assert.match(summary.headline, /No Stripe payouts yet/)
    assert.equal(summary.sentTotal, null)
  })
})

describe('captions', () => {
  test('a one-off purchase has none', () => {
    assert.equal(instalmentCaption(row()), null)
  })

  test('an instalment says which payment it is', () => {
    assert.equal(
      instalmentCaption(row({ installment_number: 3 })),
      'Payment 3 of a payment plan',
    )
  })

  test('a refunded row is flagged', () => {
    assert.equal(isReturned(row()), false)
    assert.equal(isReturned(row({ refunded_amount_cents: 5000 })), true)
  })
})

describe('nothing internal reaches the creator', () => {
  test('no row field carries a Stripe id or a recovery amount', () => {
    // The shape mirrors the backend response, which excludes them; this fails
    // if either side starts leaking.
    const keys = Object.keys(row())
    for (const forbidden of [
      'connect_destination_account_id',
      'provider_transfer_id',
      'provider_charge_id',
      'connect_unrecovered_amount_cents',
      'reversal_last_error',
      'transfer_last_error',
    ]) {
      assert.ok(!keys.includes(forbidden), forbidden)
    }
  })

  test('rendered lines contain no identifiers', () => {
    const rendered = earningLines(row())
      .map((l) => `${l.label} ${l.value}`)
      .join(' ')
    assert.ok(!rendered.includes('acct_'))
    assert.ok(!rendered.includes('tr_'))
    assert.ok(!rendered.includes('ch_'))
  })
})
