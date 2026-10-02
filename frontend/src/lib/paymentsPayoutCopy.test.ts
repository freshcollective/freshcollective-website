/**
 * Payments received — payout copy follows the payout model.
 *
 * The page told every creator that Connect was "coming in a future
 * update" and that they did "not need to connect your own Stripe
 * account", unconditionally. For a creator whose sales already route
 * through Connect — whose money has already moved — both were false.
 *
 * Comments are stripped before the source scan. The prose here names the
 * strings it bans, and a blunt match over the raw file would fail on its
 * own documentation.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
// @ts-expect-error - Node-native import
import { payoutMix, payoutNote } from './paymentsPayoutCopy.ts'

const _here = dirname(fileURLToPath(import.meta.url))

function codeOf(path: string): string {
  return readFileSync(path, 'utf-8')
    .replace(/\/\*[^]*?\*\//g, '')
    .replace(/\{\/\*[^]*?\*\/\}/g, '')
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n')
}

const HELPER = codeOf(join(_here, 'paymentsPayoutCopy.ts'))
const PAGE = codeOf(join(
  _here, '..', 'app', 'creator-studio', 'payments', 'CreatorPaymentsClient.tsx',
))

const manual = { payout_model: 'manual' as const }
const connect = { payout_model: 'connect' as const }


describe('the stale pre-Connect claims are gone', () => {
  // Written as fragments because the originals were JSX-wrapped across
  // lines, which is why a literal search for the full sentence missed.
  const BANNED = [
    'Connect are coming',
    'coming in a future update',
    'handled manually by',
    'paid out',
  ]

  for (const phrase of BANNED) {
    test(`the helper never says "${phrase}"`, () => {
      assert.ok(!HELPER.toLowerCase().includes(phrase.toLowerCase()))
    })
    test(`the page never says "${phrase}"`, () => {
      assert.ok(!PAGE.toLowerCase().includes(phrase.toLowerCase()))
    })
  }

  test('the page no longer hard-codes its payout note', () => {
    assert.match(PAGE, /payoutCopy\.body/)
  })

  test('the "no Stripe needed" card is gated, not unconditional', () => {
    assert.match(PAGE, /payoutCopy\.showNoStripeNeededCard/)
  })
})


describe('payoutMix', () => {
  test('no rows reads as manual, the safe default', () => {
    assert.equal(payoutMix([]), 'none')
    assert.equal(payoutMix(undefined), 'none')
  })

  test('a single Connect row makes the list Connect', () => {
    assert.equal(payoutMix([connect]), 'connect_only')
  })

  test('history and Connect together is mixed, not one or the other', () => {
    // payout_model is frozen per transaction, so this is the normal
    // state of a creator who was switched over mid-life.
    assert.equal(payoutMix([manual, connect]), 'mixed')
  })

  test('an absent payout_model counts as manual', () => {
    assert.equal(payoutMix([{}]), 'manual_only')
  })
})


describe('payoutNote', () => {
  test('a manual creator still gets manual copy', () => {
    const note = payoutNote([manual])
    assert.match(note.body, /paid to you by Fresh Collective/)
    assert.equal(note.showNoStripeNeededCard, true)
  })

  test('a Connect creator is told where the money actually went', () => {
    const note = payoutNote([connect])
    assert.match(note.body, /transferred to your own Stripe account/)
    assert.equal(note.showNoStripeNeededCard, false)
  })

  test('Connect copy explains that Stripe pays the bank separately', () => {
    // The distinction the whole wording rule exists for.
    const note = payoutNote([connect])
    assert.match(note.body, /Sent to Stripe/)
    assert.match(note.body, /bank account on its own schedule/)
  })

  test('a Connect creator is never told the money reached their bank', () => {
    // A transfer reaches the creator's Stripe balance. Stripe pays the
    // bank afterwards, on its own schedule — a different event.
    const body = payoutNote([connect]).body.toLowerCase()
    for (const claim of ['paid out', 'paid into your bank', 'in your bank']) {
      assert.ok(!body.includes(claim), `must not claim "${claim}"`)
    }
  })

  test('a mixed list says both things rather than averaging them', () => {
    const note = payoutNote([manual, connect])
    assert.match(note.body, /transferred to your own Stripe account/)
    assert.match(note.body, /before your account was connected/)
  })

  test('one Connect row is enough to suppress the Stripe card', () => {
    assert.equal(payoutNote([manual, connect]).showNoStripeNeededCard, false)
  })

  test('the fee line is appended when supplied', () => {
    assert.match(payoutNote([manual], { feeDisplay: '8%' }).body, /8% per sale/)
    assert.ok(!payoutNote([manual]).body.includes('per sale'))
  })
})


// ---------------------------------------------------------------------------
// The Billing page block
// ---------------------------------------------------------------------------

// @ts-expect-error - Node-native import
import { billingPayoutPhase } from './paymentsPayoutCopy.ts'

const BILLING_PAGE = codeOf(join(
  _here, '..', 'app', 'creator-studio', 'billing', 'page.tsx',
))

describe('the Billing phase block no longer contradicts the panel below it', () => {
  const BANNED = [
    'Phase 1 — current',
    'disbursed manually',
    'Automatic payouts of your sales through Stripe',
    'Refunds, disputes, and payout reporting',
  ]

  for (const phrase of BANNED) {
    test(`the page no longer hard-codes "${phrase}"`, () => {
      assert.ok(
        !BILLING_PAGE.includes(phrase),
        `"${phrase}" rendered directly above the live Connect earnings list`,
      )
    })
  }

  test('the block is driven by routing state, not a fixed label', () => {
    assert.match(BILLING_PAGE, /billingPayoutPhase\(/)
    assert.match(BILLING_PAGE, /payoutPhase\.comingLater\.map/)
  })

  test('it reads connect_routing_enabled, not merely "connected"', () => {
    // A connected-but-not-enabled account is still paid by hand.
    assert.match(BILLING_PAGE, /connectStatus\?\.connect_routing_enabled/)
  })
})


describe('billingPayoutPhase', () => {
  test('a routed creator is told their sales go to their Stripe account', () => {
    const phase = billingPayoutPhase(true)
    assert.match(phase.body, /transferred to your own Stripe account/)
    assert.ok(!phase.body.includes('disbursed manually'))
  })

  test('a routed creator is not told automatic payouts are still coming', () => {
    const phase = billingPayoutPhase(true)
    assert.ok(
      !phase.comingLater.some((i) => /automatic payouts/i.test(i)),
      'they already have them',
    )
  })

  test('nobody is told refunds are coming later — they shipped', () => {
    for (const enabled of [true, false]) {
      assert.ok(
        !billingPayoutPhase(enabled).comingLater.some((i) => /refund/i.test(i)),
      )
    }
  })

  test('GST and tax reporting genuinely has not shipped, so it stays', () => {
    for (const enabled of [true, false]) {
      assert.ok(
        billingPayoutPhase(enabled).comingLater.some((i) => /GST/.test(i)),
      )
    }
  })

  test('a routed creator is never told the money reached their bank', () => {
    const body = billingPayoutPhase(true).body.toLowerCase()
    for (const claim of ['paid out', 'paid into your bank', 'in your bank']) {
      assert.ok(!body.includes(claim), `must not claim "${claim}"`)
    }
    assert.match(billingPayoutPhase(true).body, /on its own schedule/)
  })

  test('mixed history is named, so older manual sales still make sense', () => {
    assert.match(
      billingPayoutPhase(true).body,
      /before your account was connected/,
    )
  })

  test('a manual creator keeps manual copy and the Connect roadmap line', () => {
    const phase = billingPayoutPhase(false)
    assert.match(phase.body, /paid to you by Fresh Collective/)
    assert.match(phase.body, /Connecting Stripe above prepares your account/)
    assert.ok(phase.comingLater.some((i) => /Automatic payouts/.test(i)))
  })

  test('null routing state is treated as manual, the safe default', () => {
    assert.deepEqual(billingPayoutPhase(null), billingPayoutPhase(false))
    assert.deepEqual(billingPayoutPhase(undefined), billingPayoutPhase(false))
  })
})
