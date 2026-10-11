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
  earningsBasis,
  earningsBasisNote,
  linesReconcile,
} from './connectEarnings.ts'

/**
 * A$100 sale on the 8% Creator plan → A$92.00 to the creator.
 *
 * The A$2.00 of card processing is Fresh Collective's cost and is NOT
 * subtracted. The old fixture said A$90.00, which is what the display was
 * still showing after the policy changed — the arithmetic failed to add up
 * by exactly the processing fee, and this fixture is why nothing caught it.
 */
const row = (overrides = {}) => ({
  payment_transaction_id: 'txn_1',
  created_at: '2026-09-20T12:00:00',
  currency: 'AUD',
  sale_amount_cents: 10000,
  platform_fee_cents: 800,
  processing_fee_cents: 200,
  creator_amount_cents: 9200,
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

describe('the fee breakdown — today\u2019s policy', () => {
  test('the lines are present and in order', () => {
    assert.deepEqual(earningLines(row()).map((l) => l.label), [
      'Sale',
      'Fresh Collective commission',
      'Your earnings',
      'Card processing — Fresh Collective covers this',
    ])
  })

  test('the creator\u2019s arithmetic is sale minus commission, and it adds up', () => {
    const lines = earningLines(row())
    assert.equal(lines[0].value, 'A$100.00')
    assert.equal(lines[1].value, '− A$8.00')
    assert.equal(lines[2].value, 'A$92.00')
    assert.equal(10000 - 800, 9200)
  })

  test('processing is shown but never as a deduction', () => {
    const processing = earningLines(row())
      .find((l) => l.label.startsWith('Card processing'))!
    assert.equal(processing.value, 'A$2.00')      // visible, for transparency
    assert.ok(!processing.value.includes('−'))     // but not taken from them
    assert.equal(processing.isDeduction, false)
    assert.equal(processing.covered, true)
  })

  test('only the commission is marked as a deduction', () => {
    const deductions = earningLines(row()).filter((l) => l.isDeduction)
    assert.deepEqual(deductions.map((l) => l.label), ['Fresh Collective commission'])
  })

  test('the 8% Creator plan', () => {
    const r = row({ platform_fee_cents: 800, creator_amount_cents: 9200 })
    assert.equal(earningsBasis(r), 'commission_only')
    assert.ok(linesReconcile(r))
    assert.equal(earningLines(r)[2].value, 'A$92.00')
  })

  test('the 4% Pro plan', () => {
    // The intended Pro rate. Production stays at 3% until approved, so this
    // pins the arithmetic rather than the live figure.
    const r = row({ platform_fee_cents: 400, creator_amount_cents: 9600 })
    assert.equal(earningsBasis(r), 'commission_only')
    assert.ok(linesReconcile(r))
    assert.equal(earningLines(r)[2].value, 'A$96.00')
  })

  test('the 3% Pro rate currently live in production', () => {
    const r = row({ platform_fee_cents: 300, creator_amount_cents: 9700 })
    assert.equal(earningsBasis(r), 'commission_only')
    assert.ok(linesReconcile(r))
  })

  test('a 0% Founding Creator receives the whole sale', () => {
    const r = row({ platform_fee_cents: 0, creator_amount_cents: 10000 })
    assert.equal(earningsBasis(r), 'commission_only')
    assert.ok(linesReconcile(r))
    const lines = earningLines(r)
    assert.equal(lines[1].value, '− A$0.00')
    assert.equal(lines[2].value, 'A$100.00')
    // The case most at risk of being got wrong: 0% commission must not be
    // quietly reduced by the processing fee.
    assert.equal(lines[2].value, lines[0].value)
  })

  test('an instalment is priced the same way', () => {
    const r = row({
      sale_amount_cents: 5000, platform_fee_cents: 400,
      processing_fee_cents: 150, creator_amount_cents: 4600,
    })
    assert.equal(earningsBasis(r), 'commission_only')
    assert.equal(earningLines(r)[2].value, 'A$46.00')
  })

  test('an unknown processing fee is "being confirmed", never zero', () => {
    const r = row({ processing_fee_cents: null })
    const processing = earningLines(r)
      .find((l) => l.label.startsWith('Card processing'))!
    assert.equal(processing.value, 'being confirmed')
    assert.equal(processing.pending, true)
    // And it does not hold up the creator's own figure, which never
    // depended on it.
    assert.equal(earningLines(r)[2].value, 'A$92.00')
    assert.equal(earningsBasis(r), 'commission_only')
    assert.ok(linesReconcile(r))
  })

  test('an unpriced row says so rather than guessing', () => {
    const r = row({ processing_fee_cents: null, creator_amount_cents: null })
    assert.equal(earningsBasis(r), 'not_yet_priced')
    assert.ok(linesReconcile(r))
    assert.equal(earningLines(r)[2].value, 'being confirmed')
    assert.equal(earningLines(r)[2].pending, true)
  })
})

describe('historical transfers — the older rule, honoured not excused', () => {
  /** Sent before FC absorbed processing: 10000 − 800 − 200 = 9000. */
  const historical = (overrides = {}) =>
    row({ creator_amount_cents: 9000, ...overrides })

  test('it is recognised as priced under the older rule', () => {
    assert.equal(earningsBasis(historical()), 'commission_and_processing')
  })

  test('it reconciles — it is correct, not tolerated', () => {
    assert.ok(linesReconcile(historical()))
  })

  test('it reports the amount actually transferred, not today\u2019s figure', () => {
    const lines = earningLines(historical())
    assert.deepEqual(lines.map((l) => l.label), [
      'Sale',
      'Card processing fee',
      'Fresh Collective commission',
      'Transferred to you',
    ])
    assert.equal(lines[3].value, 'A$90.00')        // what really left
    assert.notEqual(lines[3].value, 'A$92.00')     // not re-derived
  })

  test('the processing fee is shown as the deduction it really was', () => {
    const processing = earningLines(historical())
      .find((l) => l.label === 'Card processing fee')!
    assert.equal(processing.value, '− A$2.00')
    assert.equal(processing.isDeduction, true)
    assert.ok(!processing.covered)
  })

  test('and it is explained, so it does not read as an error', () => {
    const note = earningsBasisNote(historical())
    assert.ok(note && note.includes('before Fresh Collective began covering'))
  })

  test('a current row gets no such note', () => {
    assert.equal(earningsBasisNote(row()), null)
  })

  test('a zero processing fee resolves to today\u2019s policy, not the old one', () => {
    // Both rules agree when the fee is zero. The result must be deterministic.
    const r = row({ processing_fee_cents: 0, creator_amount_cents: 9200 })
    assert.equal(earningsBasis(r), 'commission_only')
    assert.equal(earningsBasisNote(r), null)
  })
})

describe('figures that do not account for the sale', () => {
  test('a creator figure matching neither rule fails reconciliation', () => {
    const r = row({ creator_amount_cents: 8500 })
    assert.equal(earningsBasis(r), 'unreconciled')
    assert.equal(linesReconcile(r), false)
  })

  test('the old display bug would now fail', () => {
    // 10000 − 800 − 200 presented as earnings under today's policy. This is
    // exactly what shipped, and the guard must reject it as a *current*
    // figure while still accepting it as a historical transfer.
    const asHistorical = row({ creator_amount_cents: 9000 })
    assert.equal(earningsBasis(asHistorical), 'commission_and_processing')
    // Same figures, but with no processing fee to justify the gap: nothing
    // accounts for the missing A$2.00, so it must not be shown as a breakdown.
    const unjustified = row({ creator_amount_cents: 9000, processing_fee_cents: null })
    assert.equal(earningsBasis(unjustified), 'unreconciled')
  })

  test('a breakdown that cannot add up is withheld rather than shown wrong', () => {
    const lines = earningLines(row({ creator_amount_cents: 8500 }))
    assert.deepEqual(lines.map((l) => l.label), ['Sale', 'Your earnings'])
    assert.ok(!lines.some((l) => l.isDeduction))
  })

  test('an inflated creator figure fails too', () => {
    const r = row({ creator_amount_cents: 10000 })   // more than sale − commission
    assert.equal(earningsBasis(r), 'unreconciled')
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
    assert.match(summary.headline, /No earnings yet/)
    assert.equal(summary.sentTotal, null)
  })

  test('a transfer is never described as money already in the bank', () => {
    // Fresh Collective does not observe the bank payout, so nothing here may
    // claim the money has landed.
    const summary = earningsHeadline(response())
    const text = `${summary.headline} ${summary.body}`
    assert.ok(!/paid into|arrived|in your bank account|received/i.test(text), text)
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
