/**
 * The creator's bank account and their actual bank payouts.
 *
 * The assertions that matter most are the negative ones: nothing here may
 * describe a Stripe transfer, or a payout still in transit, as money that
 * has reached the bank.
 */

import { readFileSync } from 'node:fs'
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
  // Stripe reports this on every sync, and it was correct throughout the
  // production incident. It is what decides whether an account exists.
  external_account_count: 1,
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

describe('the bank account — three states, not two', () => {
  /**
   * The live defect this replaces: existence was keyed on ``bank_last4``,
   * so a creator whose account Stripe had confirmed — payouts active, a
   * payout already paid — was told "No bank account added yet" and invited
   * to add one, purely because the masked details had not been read.
   */

  test('no account: say so, and offer to add one', () => {
    const view = bankAccountView(status({
      external_account_count: 0, bank_last4: null, bank_name: null,
    }))
    assert.equal(view.present, false)
    assert.equal(view.detailsPending, false)
    assert.match(view.label, /No bank account added yet/)
    assert.equal(view.actionLabel, 'Add bank details')
  })

  test('account with details: name it precisely', () => {
    const view = bankAccountView(status())
    assert.equal(view.present, true)
    assert.equal(view.detailsPending, false)
    assert.equal(view.label, 'Commonwealth Bank •••• 4321')
    assert.equal(view.actionLabel, 'Update bank details')
  })

  test('a short bank name renders cleanly', () => {
    // The production account that exposed this defect had a three-letter
    // bank name, which is the shape worth pinning. Fictional digits: there
    // is no reason for a real account's details to live in a test file.
    const view = bankAccountView(status({
      external_account_count: 1, bank_name: 'ABC', bank_last4: '1234',
      bank_currency: 'AUD',
    }))
    assert.equal(view.label, 'ABC •••• 1234')
    assert.equal(view.actionLabel, 'Update bank details')
  })

  test('account without details: confirming, never "none"', () => {
    // The state that was missing. Stripe says one account exists; we have
    // not read its digits yet.
    const view = bankAccountView(status({
      external_account_count: 1, bank_last4: null, bank_name: null,
    }))
    assert.equal(view.present, true)
    assert.equal(view.detailsPending, true)
    assert.match(view.label, /Your bank account is set up/)
    assert.match(view.label, /confirming the details with Stripe/)
    // Must not claim there is none, and must not invite adding one.
    assert.ok(!/No bank account/i.test(view.label))
    assert.equal(view.actionLabel, 'Update bank details')
  })

  test('existence follows the count, never the masked details', () => {
    // The invariant. Any count above zero means an account exists,
    // whatever we happen to know about it.
    for (const last4 of [null, '1234']) {
      assert.equal(
        bankAccountView(status({ external_account_count: 1, bank_last4: last4 })).present,
        true, `last4=${last4}`,
      )
    }
    // And masked details without a count cannot conjure one into being.
    assert.equal(
      bankAccountView(status({ external_account_count: 0, bank_last4: '1234' })).present,
      false,
    )
  })

  test('"Add" is only ever offered when there is nothing there', () => {
    const adding = [0, 1, 2]
      .filter((n) => bankAccountView(status({ external_account_count: n }))
        .actionLabel === 'Add bank details')
    assert.deepEqual(adding, [0])
  })

  test('it never shows anything that could be a full number', () => {
    const view = bankAccountView(status())
    const digits = view.label.replace(/\D/g, '')
    assert.equal(digits.length, 4, `too many digits: ${view.label}`)
  })

  test('it says Fresh Collective never sees the account number', () => {
    for (const count of [1, 0]) {
      assert.match(
        bankAccountView(status({ external_account_count: count })).note,
        /never sees/,
      )
    }
  })

  test('a bank with no name still shows the last four', () => {
    const view = bankAccountView(status({ bank_name: null }))
    assert.equal(view.label, '•••• 4321')
  })

  test('no status at all is handled', () => {
    const view = bankAccountView(null)
    assert.equal(view.present, false)
    assert.equal(view.actionLabel, 'Add bank details')
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
    // No account at all — count zero, not merely missing digits.
    const { body } = payoutsHeadline(
      [], status({ external_account_count: 0, bank_last4: null }),
    )
    assert.match(body, /Once your bank details are added/)
  })

  test('an account whose details are still confirming is not "no account"', () => {
    // The headline keys off existence too, so a creator mid-confirmation is
    // not told to add bank details they already have.
    const { body } = payoutsHeadline(
      [], status({ external_account_count: 1, bank_last4: null }),
    )
    assert.match(body, /Your bank details are set up/)
    assert.ok(!/Once your bank details are added/.test(body))
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
      [[], status({ external_account_count: 0, bank_last4: null })],
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

describe('refreshing the connection also refreshes the bank section', () => {
  /**
   * The live defect: the readiness panel held its own status and the bank
   * section held a prop frozen at page load, so "Refresh status" updated
   * one and left the other claiming no bank account existed. No amount of
   * refreshing — or reloading, since the database was never updated —
   * changed it.
   *
   * These read the source, because what matters is the wiring: one status,
   * one source, and the refresh that actually re-reads Stripe.
   */
  const read = (rel: string) =>
    readFileSync(new URL(rel, import.meta.url), 'utf8')
  const code = (rel: string) =>
    read(rel)
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      .replace(/(^|[^:])\/\/.*$/gm, '$1')

  const PAGE = '../app/creator-studio/bank-payouts/page.tsx'
  const SECTIONS = '../app/creator-studio/bank-payouts/BankPayoutsSections.tsx'
  const PANEL = '../app/creator-studio/billing/StripeConnectPanel.tsx'
  const BANK = '../app/creator-studio/bank-payouts/BankAccountPanel.tsx'

  test('the page renders one wrapper, not two independent sections', () => {
    const src = code(PAGE)
    assert.match(src, /<BankPayoutsSections/)
    // Neither may be mounted directly any more, or they would each hold
    // their own copy of the status again.
    assert.ok(!/<StripeConnectPanel/.test(src))
    assert.ok(!/<BankAccountPanel/.test(src))
  })

  test('the wrapper holds the status and passes it to the bank section', () => {
    const src = code(SECTIONS)
    assert.match(src, /useState<CreatorStripeConnectStatus \| null>/)
    assert.match(src, /onStatusChange=\{setStatus\}/)
    assert.match(src, /<BankAccountPanel status=\{status\}/)
  })

  test('the panel reports every status it learns', () => {
    const src = code(PANEL)
    // A single setter that notifies, so no code path can learn a status
    // without telling the parent.
    assert.match(src, /onStatusChange\?\.\(next\)/)
    assert.match(src, /onStatusChange\?: \(status: CreatorStripeConnectStatus\) => void/)
  })

  test('the refresh action re-reads Stripe, not our stored copy', () => {
    // POST /refresh re-reads Stripe and persists the masked details.
    // GET /status returns the stored projection and would never populate
    // them — which is why the earnings "Refresh" button could not help.
    const src = code(PANEL)
    assert.match(src, /setStatus\(await refreshStatus\(transport\)\)/)
    const onRefresh = src.slice(src.indexOf('function onRefresh'))
      .slice(0, 160)
    assert.ok(!/loadStatus/.test(onRefresh), 'onRefresh must not use loadStatus')
  })

  test('the bank section takes its status as a prop, never a stale copy', () => {
    const src = code(BANK)
    // It must not hold its own status state: that is how the two drifted.
    assert.ok(!/useState<CreatorStripeConnectStatus/.test(src))
    assert.match(src, /status: CreatorStripeConnectStatus \| null/)
  })

  test('the bank section makes no duplicate status request', () => {
    // It receives the status; only the payouts are its own to fetch.
    const src = code(BANK)
    assert.ok(!/stripe-connect\/status/.test(src))
    assert.match(src, /stripe-connect\/payouts/)
  })
})
