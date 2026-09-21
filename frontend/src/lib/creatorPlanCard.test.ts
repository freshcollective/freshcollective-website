import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { buildCreatorPlanCard } from './creatorPlanCard.ts'
import type { CreatorPlanOut, CreatorSubscriptionOut } from '../types/platform.ts'

/**
 * What the creator plan card says.
 *
 * It used to say the same thing to everyone: "Founding Creator
 * Access", "14 days free", "then $19 / month" were literal strings.
 * A Founding Creator on $0 was quoted $19 and a trial they were not
 * in; a Pro creator paying $79 was quoted $19 too.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

function plan(over: Partial<CreatorPlanOut> = {}): CreatorPlanOut {
  return {
    id: 'p1', name: 'Creator', slug: 'creator', description: null,
    monthly_price_cents: 1900, currency: 'AUD',
    transaction_fee_basis_points: 800,
    collective_limit: 3, pathway_limit: null,
    media_storage_limit_mb: null, creator_admin_seat_limit: null,
    ...over,
  } as CreatorPlanOut
}

function sub(over: Partial<CreatorSubscriptionOut> = {}): CreatorSubscriptionOut {
  return {
    id: 's1', status: 'active', starts_at: '2026-01-01T00:00:00',
    ends_at: null, stripe_connected: true,
    ...over,
  } as CreatorSubscriptionOut
}

const FOUNDING = plan({
  name: 'Founding Creator', slug: 'founding-creator',
  monthly_price_cents: 0, transaction_fee_basis_points: 0,
})

describe('the plan the creator is actually on', () => {
  test('a Founding Creator reads $0 and 0%, with no trial', () => {
    // The reported bug, as an assertion.
    const v = buildCreatorPlanCard(FOUNDING, sub({ source: 'manual_grant' }), 0)
    assert.equal(v.planName, 'Founding Creator')
    assert.equal(v.priceLabel, '$0 / month')
    assert.equal(v.feeLabel, '0%')
    assert.equal(v.trialLabel, null)
    assert.equal(v.statusNote, null)
  })

  test('a Pro creator is not quoted the Creator price', () => {
    const v = buildCreatorPlanCard(
      plan({ name: 'Pro', slug: 'pro', monthly_price_cents: 7900 }), sub(), 800,
    )
    assert.equal(v.planName, 'Pro')
    assert.equal(v.priceLabel, '$79 / month')
    assert.equal(v.feeLabel, '8%')
  })

  test('a $19 plan still reads $19 — for the right reason', () => {
    const v = buildCreatorPlanCard(plan(), sub(), 800)
    assert.equal(v.priceLabel, '$19 / month')
  })

  test('the Organisation plan says talk to us, not free', () => {
    const v = buildCreatorPlanCard(
      plan({ name: 'Organisation', monthly_price_cents: null }), sub(), 0,
    )
    assert.equal(v.priceLabel, 'Talk to us')
  })

  test('a fractional fee keeps its decimal', () => {
    assert.equal(buildCreatorPlanCard(plan(), sub(), 250).feeLabel, '2.5%')
  })

  test('the name is never invented', () => {
    const v = buildCreatorPlanCard(FOUNDING, sub(), 0)
    assert.ok(!v.planName?.includes('Access'), 'no "Founding Creator Access"')
  })
})

describe('trial state comes from the subscription, never the card', () => {
  test('a trialing creator sees the real end date', () => {
    const v = buildCreatorPlanCard(
      plan(), sub({ status: 'trialing', current_period_end: '2026-10-05T00:00:00' }), 800,
    )
    assert.match(v.trialLabel ?? '', /^Free trial until 5 Oct 2026$/)
    assert.match(v.statusNote ?? '', /Billing starts 5 Oct 2026/)
  })

  test('a trial with no known end date says only what is known', () => {
    const v = buildCreatorPlanCard(plan(), sub({ status: 'trialing' }), 800)
    assert.equal(v.trialLabel, 'Free trial')
    assert.equal(v.statusNote, null, 'no invented date')
  })

  test('nobody who is not trialing sees a trial line', () => {
    for (const status of ['active', 'past_due', 'cancelled', 'unpaid'] as const) {
      assert.equal(
        buildCreatorPlanCard(plan(), sub({ status }), 800).trialLabel, null, status,
      )
    }
  })

  test('a manually granted plan has no trial', () => {
    assert.equal(
      buildCreatorPlanCard(FOUNDING, sub({ source: 'manual_grant' }), 0).trialLabel,
      null,
    )
  })
})

describe('cancellation, stated factually', () => {
  test('a scheduled cancellation is still an active plan', () => {
    // cancel_at_period_end leaves status='active'; the model says the
    // creator keeps capability through the paid-through date. Calling
    // this "cancelled" would tell a paying creator their access had
    // already gone.
    const v = buildCreatorPlanCard(
      plan(),
      sub({ status: 'active', cancel_at_period_end: true,
            current_period_end: '2026-11-01T00:00:00' }),
      800,
    )
    assert.match(v.statusNote ?? '', /Cancels on 1 Nov 2026\. Your plan continues until then\./)
    assert.ok(!/ended/i.test(v.statusNote ?? ''))
    assert.equal(v.priceLabel, '$19 / month', 'still priced — it is still running')
  })

  test('a scheduled cancellation with no date still does not claim it has ended', () => {
    const v = buildCreatorPlanCard(
      plan(), sub({ status: 'active', cancel_at_period_end: true }), 800,
    )
    assert.match(v.statusNote ?? '', /continues until the end of the current period/)
  })

  test("a cancelled status is reached only after the period closed", () => {
    const v = buildCreatorPlanCard(
      plan(), sub({ status: 'cancelled', ends_at: '2026-09-01T00:00:00' }), 800,
    )
    assert.equal(v.statusNote, 'Ended on 1 Sept 2026.')
  })

  test('an active plan with no cancellation says nothing at all', () => {
    assert.equal(buildCreatorPlanCard(plan(), sub(), 800).statusNote, null)
  })
})

describe('payment trouble, without overstating it', () => {
  test('past due names the grace deadline when there is one', () => {
    const v = buildCreatorPlanCard(
      plan(), sub({ status: 'past_due', grace_expires_at: '2026-10-08T00:00:00' }), 800,
    )
    assert.match(v.statusNote ?? '', /Payment overdue\. Your plan continues until 8 Oct 2026\./)
  })

  test('past due without a deadline states only the fact', () => {
    assert.equal(
      buildCreatorPlanCard(plan(), sub({ status: 'past_due' }), 800).statusNote,
      'Payment overdue.',
    )
  })

  test('unpaid is described as inactive', () => {
    assert.match(
      buildCreatorPlanCard(plan(), sub({ status: 'unpaid' }), 800).statusNote ?? '',
      /inactive/,
    )
  })
})

describe('no plan is a neutral state, not invented terms', () => {
  test('no plan names no price and no trial', () => {
    const v = buildCreatorPlanCard(null, null, 0)
    assert.equal(v.planName, null)
    assert.equal(v.priceLabel, null)
    assert.equal(v.trialLabel, null)
    assert.ok(v.isUnknown)
  })

  test('the fee still shows when it is known', () => {
    assert.equal(buildCreatorPlanCard(null, null, 0).feeLabel, '0%')
  })

  test('an unknown fee is omitted rather than shown as zero', () => {
    assert.equal(buildCreatorPlanCard(plan(), sub(), null).feeLabel, null)
  })
})

describe('the card renders from the data', () => {
  const client = () => read('app/creator-studio/payments/CreatorPaymentsClient.tsx')

  test('no hard-coded plan name, trial or price survives', () => {
    const src = client()
    assert.ok(!src.includes('Founding Creator Access'))
    assert.ok(!src.includes('14 days free'))
    assert.ok(!src.includes('$19 / month'))
  })

  test('every value comes from the summariser', () => {
    const src = client()
    for (const field of ['planName', 'priceLabel', 'feeLabel', 'trialLabel', 'statusNote']) {
      assert.ok(src.includes(`planCard.${field}`), field)
    }
  })

  test('the page derives it from billing, not from anything else', () => {
    const page = read('app/creator-studio/payments/page.tsx')
    assert.match(page, /buildCreatorPlanCard\(\s*billing\?\.current_plan/)
    assert.match(page, /billing\?\.subscription/)
  })

  test('no account is special-cased', () => {
    // An email address or a personal name, not the '@' of an import
    // path — the point is that no account is singled out.
    const src = client() + read('lib/creatorPlanCard.ts')
    assert.ok(!/[\w.]+@[\w.]+\.\w+/.test(src), 'an email address is hard-coded')
    assert.ok(!/lindsey|hilliard/i.test(src), 'an account name is hard-coded')
    assert.ok(!/user\.(id|email)\s*===/.test(src), 'a per-account branch exists')
  })

  test('the card is not hidden from admins or owners', () => {
    // The platform-owner branch is a different card, not an absence.
    assert.match(client(), /selectedSpaceIsPlatformOwned \? \(/)
  })
})
