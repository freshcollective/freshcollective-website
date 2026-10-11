/**
 * The creator's bank account and their actual bank payouts.
 *
 * The assertions that matter most are the negative ones: nothing here may
 * describe a Stripe transfer, or a payout still in transit, as money that
 * has reached the bank.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

// @ts-expect-error - Node-native import
import {
  PAYOUT_STATUS_LABELS,
  bankAccountView,
  formatPayoutDate,
  formatPayoutMoney,
  payoutRowView,
  payoutsFreshness,
  payoutsHeadline,
  historyNote,
} from './bankPayouts.ts'

const status = (o = {}) => ({
  state: 'ready',
  connected: true,
  stripe_account_id: 'acct_x',
  bank_name: 'Commonwealth Bank',
  bank_last4: '4321',
  bank_currency: 'AUD',
  payout_interval: 'weekly',
  payout_delay_days: 2,
  connect_routing_enabled: true,
  ...o,
})

const payout = (o = {}) => ({
  amount_cents: 9200,
  currency: 'AUD',
  status: 'paid' as const,
  arrival_date: '2026-10-13T00:00:00',
  initiated_at: '2026-10-10T00:00:00',
  ...o,
})

describe('the bank account, masked', () => {
  test('it shows the bank and the last four only', () => {
    const view = bankAccountView(status())
    assert.equal(view.present, true)
    assert.equal(view.label, 'Commonwealth Bank •••• 4321')
  })

  test('it never shows anything that could be a full number', () => {
    const view = bankAccountView(status())
    const digits = view.label.replace(/\D/g, '')
    assert.equal(digits.length, 4, `too many digits: ${view.label}`)
  })

  test('it says Fresh Collective never sees the account number', () => {
    assert.match(bankAccountView(status()).note, /never sees your full account number/)
  })

  test('a missing bank account is stated, not dressed up', () => {
    // A creator can have transfers enabled with nowhere to pay out to.
    // Reassuring them in that state would be the wrong thing.
    const view = bankAccountView(status({ bank_last4: null, bank_name: null }))
    assert.equal(view.present, false)
    assert.match(view.label, /No bank account added yet/)
    assert.match(view.note, /Add your bank details/)
  })

  test('a bank with no name still shows the last four', () => {
    const view = bankAccountView(status({ bank_name: null }))
    assert.equal(view.label, '•••• 4321')
  })

  test('no status at all is handled', () => {
    assert.equal(bankAccountView(null).present, false)
  })
})

describe('payout status wording', () => {
  test('only one status says the money arrived', () => {
    const arrived = Object.entries(PAYOUT_STATUS_LABELS)
      .filter(([, label]) => /paid into/i.test(label))
      .map(([key]) => key)
    assert.deepEqual(arrived, ['paid'])
  })

  test('in_transit is never phrased as arrived', () => {
    const view = payoutRowView(payout({ status: 'in_transit' }))
    assert.equal(view.status, 'On its way to your bank')
    assert.equal(view.arrived, false)
    assert.ok(!/paid/i.test(view.status))
  })

  test('a payout in transit is dated as expected, not as paid', () => {
    // The single most misleading thing the page could say.
    const view = payoutRowView(payout({ status: 'in_transit' }))
    assert.equal(view.when, 'Expected 13 Oct 2026')
    assert.ok(!/^Paid/.test(view.when!))
  })

  test('a paid payout is dated in the past tense', () => {
    const view = payoutRowView(payout({ status: 'paid' }))
    assert.equal(view.when, 'Paid 13 Oct 2026')
    assert.equal(view.arrived, true)
  })

  test('a failed payout needs attention and is not blamed on the creator', () => {
    const view = payoutRowView(payout({ status: 'failed' }))
    assert.equal(view.attention, true)
    assert.equal(view.status, 'Didn’t go through')
    assert.equal(view.arrived, false)
  })

  test('a cancelled payout is not a failure', () => {
    const view = payoutRowView(payout({ status: 'canceled' }))
    assert.equal(view.status, 'Cancelled')
    assert.equal(view.attention, false)
  })

  test('pending does not promise a date it does not have', () => {
    const view = payoutRowView(payout({ status: 'pending', arrival_date: null }))
    assert.equal(view.when, null)
    assert.equal(view.status, 'Preparing')
  })

  test('an unrecognised status is honest rather than invented', () => {
    // Stripe could add one. Better "being confirmed" than a wrong guess.
    const view = payoutRowView(payout({ status: 'something_new' as never }))
    assert.equal(view.status, 'Being confirmed')
    assert.equal(view.arrived, false)
  })

  test('the amount is formatted, never rounded away', () => {
    assert.equal(formatPayoutMoney(9200, 'AUD'), 'A$92.00')
    assert.equal(formatPayoutMoney(5, 'AUD'), 'A$0.05')
  })

  test('a malformed date is omitted rather than shown as Invalid Date', () => {
    assert.equal(formatPayoutDate('not-a-date'), null)
    assert.equal(formatPayoutDate(null), null)
  })
})

describe('the payouts headline', () => {
  test('with payouts, it says what "paid" means', () => {
    const { body } = payoutsHeadline([payout()], status())
    assert.match(body, /Only .Paid into your bank. means it has arrived/)
  })

  test('with no bank account, it says to add one', () => {
    const { body } = payoutsHeadline([], status({ bank_last4: null }))
    assert.match(body, /Once your bank details are added/)
  })

  test('with a bank account but no payouts, it says why', () => {
    // Two quite different causes for an empty list. Saying which saves the
    // creator guessing.
    const { body } = payoutsHeadline([], status())
    assert.match(body, /Your bank details are set up/)
  })

  test('nothing in the headline claims a transfer is a bank payout', () => {
    for (const args of [
      [[payout()], status()],
      [[], status()],
      [[], status({ bank_last4: null })],
    ] as const) {
      const { headline, body } = payoutsHeadline(...(args as [never, never]))
      const text = `${headline} ${body}`
      assert.ok(!/transfer/i.test(text), text)
    }
  })
})

describe('freshness', () => {
  test('it says when Stripe was last checked', () => {
    assert.equal(
      payoutsFreshness('2026-10-11T03:00:00'),
      'Checked with Stripe on 11 Oct 2026',
    )
  })

  test('it says nothing rather than implying a live view', () => {
    assert.equal(payoutsFreshness(null), null)
  })
})

describe('what a creator is asked to do', () => {
  test('a failed payout says the money is not lost', () => {
    // "Didn't go through" alone reads as money gone. It is still in their
    // Stripe balance and will be sent again.
    const view = payoutRowView(payout({ status: 'failed' }))
    assert.ok(view.action)
    assert.match(view.action!, /still with Stripe/)
    assert.match(view.action!, /bank details/)
  })

  test('a cancelled payout asks nothing of them', () => {
    // Almost always Fresh Collective's or Stripe's doing. Telling someone to
    // act when they cannot is worse than saying nothing.
    assert.equal(payoutRowView(payout({ status: 'canceled' })).action, null)
  })

  test('a successful or in-flight payout asks nothing either', () => {
    for (const status of ['paid', 'in_transit', 'pending'] as const) {
      assert.equal(payoutRowView(payout({ status })).action, null, status)
    }
  })

  test('only the failed row is flagged for attention', () => {
    const flagged = (['pending', 'in_transit', 'paid', 'failed', 'canceled'] as const)
      .filter((s) => payoutRowView(payout({ status: s })).attention)
    assert.deepEqual(flagged, ['failed'])
  })
})

describe('a partial history is never presented as complete', () => {
  test('while importing, with payouts shown, it says the list may be short', () => {
    const note = historyNote(false, 5)
    assert.ok(note)
    assert.match(note!, /still importing your older payouts/)
    assert.match(note!, /may not be complete/)
  })

  test('while importing, with nothing yet, it explains the emptiness', () => {
    // An empty list during import must not read as "you have never been
    // paid" — the creator would conclude a payout never happened.
    const note = historyNote(false, 0)
    assert.ok(note)
    assert.match(note!, /still importing your payout history/)
  })

  test('once complete, it says nothing at all', () => {
    assert.equal(historyNote(true, 5), null)
    assert.equal(historyNote(true, 0), null)
  })

  test('the note never claims the history is complete', () => {
    for (const count of [0, 1, 50]) {
      const note = historyNote(false, count)
      assert.ok(!/all your payouts|complete history|everything/i.test(note!), note!)
    }
  })
})
