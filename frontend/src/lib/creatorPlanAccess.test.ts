import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describeCreatorAccess } from './creatorPlanAccess.ts'
import { buildCreatorPlanCard } from './creatorPlanCard.ts'
import type { CreatorPlanOut, CreatorSubscriptionOut } from '@/types/platform'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const NOW = new Date('2026-10-04T00:00:00Z')

function plan(over: Partial<CreatorPlanOut> = {}): CreatorPlanOut {
  return {
    id: 'plan-creator',
    name: 'Creator',
    slug: 'creator',
    monthly_price_cents: 1900,
    currency: 'AUD',
    transaction_fee_basis_points: 800,
    ...over,
  } as CreatorPlanOut
}

function sub(over: Partial<CreatorSubscriptionOut> = {}): CreatorSubscriptionOut {
  return {
    id: 'sub-1',
    status: 'active',
    starts_at: '2026-10-04T00:00:00Z',
    ends_at: null,
    stripe_connected: false,
    source: 'manual_grant',
    ...over,
  } as CreatorSubscriptionOut
}

describe('a complimentary grant is never shown as a paid subscription', () => {
  test('an active comp grant is labelled complimentary', () => {
    const v = describeCreatorAccess(
      plan(),
      sub({ grant_reason: 'comp', ends_at: '2026-11-04T00:00:00Z' }),
      NOW,
    )
    assert.equal(v.kind, 'complimentary')
    assert.equal(v.label, 'Complimentary Creator access')
    assert.equal(v.isUnbilled, true)
  })

  test('the retail price is never quoted as what they pay', () => {
    const v = describeCreatorAccess(
      plan(),
      sub({ grant_reason: 'comp', ends_at: '2026-11-04T00:00:00Z' }),
      NOW,
    )
    assert.equal(v.priceOverride, 'Complimentary')
    assert.ok(!/19/.test(v.priceOverride ?? ''))
  })

  test('the end date is shown', () => {
    const v = describeCreatorAccess(
      plan(),
      sub({ grant_reason: 'comp', ends_at: '2026-11-04T00:00:00Z' }),
      NOW,
    )
    assert.match(v.termNote ?? '', /4 Nov 2026/)
  })

  test('no copy claims a future charge — a grant has no Stripe subscription', () => {
    for (const ends of [null, '2026-11-04T00:00:00Z', '2026-09-01T00:00:00Z']) {
      const note = describeCreatorAccess(
        plan(), sub({ grant_reason: 'comp', ends_at: ends }), NOW,
      ).termNote ?? ''
      assert.ok(
        !/\$19|will be charged|then \$|billing starts|renews/i.test(note),
        `grant copy must not imply a charge: ${note}`,
      )
    }
  })

  test('no copy claims the access stops by itself — nothing enforces ends_at', () => {
    const note = describeCreatorAccess(
      plan(), sub({ grant_reason: 'comp', ends_at: '2026-11-04T00:00:00Z' }), NOW,
    ).termNote ?? ''
    // "Granted until", not "Active until": the backend has no sweeper
    // for ends_at, so an automatic cutoff would be a false promise.
    assert.match(note, /Granted until/)
    assert.ok(!/expires automatically|will end|access ends/i.test(note))
  })

  test('a lapsed grant says access continues, matching real backend behaviour', () => {
    const v = describeCreatorAccess(
      plan(), sub({ grant_reason: 'comp', ends_at: '2026-09-01T00:00:00Z' }), NOW,
    )
    assert.match(v.termNote ?? '', /1 Sept 2026/)
    assert.match(v.termNote ?? '', /still active/i)
  })

  test('an indefinite grant says so without inventing a date', () => {
    const v = describeCreatorAccess(
      plan(), sub({ grant_reason: 'comp', ends_at: null }), NOW,
    )
    assert.match(v.termNote ?? '', /no end date/i)
  })

  test('a non-comp administrative grant is still unbilled, worded neutrally', () => {
    const v = describeCreatorAccess(
      plan(), sub({ grant_reason: 'beta', ends_at: '2026-11-04T00:00:00Z' }), NOW,
    )
    assert.equal(v.kind, 'granted')
    assert.equal(v.isUnbilled, true)
    assert.ok(!/complimentary/i.test(v.label ?? ''))
  })
})

describe('paid and free plans are unaffected', () => {
  test('a Stripe-billed subscription keeps the retail price', () => {
    const v = describeCreatorAccess(
      plan(), sub({ source: 'stripe_paid', grant_reason: null }), NOW,
    )
    assert.equal(v.kind, 'paid')
    assert.equal(v.priceOverride, null)
    assert.equal(v.isUnbilled, false)
    assert.equal(v.termNote, null)
  })

  test('the Community plan still renders as free', () => {
    const v = describeCreatorAccess(
      plan({ slug: 'community', name: 'Community', monthly_price_cents: 0 }),
      null, NOW,
    )
    assert.equal(v.kind, 'free')
    assert.equal(v.priceOverride, null)
  })

  test('no plan is a neutral state', () => {
    assert.equal(describeCreatorAccess(null, null, NOW).kind, 'none')
    assert.equal(describeCreatorAccess(plan(), null, NOW).kind, 'none')
  })
})

describe('the plan card tells the same truth', () => {
  test('a comp grant does not quote $19 / month', () => {
    const card = buildCreatorPlanCard(
      plan(), sub({ grant_reason: 'comp', ends_at: '2026-11-04T00:00:00Z' }), 800,
    )
    assert.equal(card.priceLabel, 'Complimentary')
    assert.match(card.statusNote ?? '', /Granted until 4 Nov 2026/)
  })

  test('a paid subscription still quotes the retail price', () => {
    const card = buildCreatorPlanCard(
      plan(), sub({ source: 'stripe_paid', grant_reason: null }), 800,
    )
    assert.equal(card.priceLabel, '$19 / month')
  })

  test('a scheduled cancellation still wins over the grant note', () => {
    // cancel_at_period_end only occurs on Stripe-billed subs, but the
    // ordering must not swallow it if the data ever overlaps.
    const card = buildCreatorPlanCard(
      plan(),
      sub({
        source: 'stripe_paid', grant_reason: null,
        cancel_at_period_end: true, current_period_end: '2026-11-04T00:00:00Z',
      }),
      800,
    )
    assert.match(card.statusNote ?? '', /Cancels on 4 Nov 2026/)
  })
})

describe('Billing renders the access state rather than the bare price', () => {
  const BILLING = 'app/creator-studio/billing/page.tsx'

  test('the page derives the access view', () => {
    const src = codeOnly(BILLING)
    assert.match(src, /describeCreatorAccess\(current_plan, billing\.subscription\)/)
  })

  test('the price line defers to the override', () => {
    const src = codeOnly(BILLING)
    assert.match(src, /access\.priceOverride/)
  })

  test('the misleading "Billed manually" line is gone', () => {
    const src = codeOnly(BILLING)
    assert.ok(
      !src.includes('Billed manually by Fresh Collective'),
      'no grant reason means "we invoice you" — the line was never true',
    )
  })

  test('the label and term note are rendered', () => {
    const src = codeOnly(BILLING)
    assert.match(src, /access\.label/)
    assert.match(src, /access\.termNote/)
  })

  test('the retail price is still available for plan comparison', () => {
    const src = codeOnly(BILLING)
    assert.match(src, /formatPrice\(current_plan\.monthly_price_cents/)
  })
})

describe('the Billing status pill does not warn an unbilled creator', () => {
  const BILLING = 'app/creator-studio/billing/page.tsx'

  test('a manual grant reports no billing required', () => {
    const src = codeOnly(BILLING)
    const pill = src.slice(src.indexOf('function BillingStatusPill'))
    assert.match(pill, /sub\?\.source === 'manual_grant'/)
    assert.match(pill, /No billing required/)
  })

  test('a grant no longer falls through to the not-connected warning', () => {
    const src = codeOnly(BILLING)
    const pill = src.slice(src.indexOf('function BillingStatusPill'))
    // The grant branch must come before the stripePaid branches, so it
    // cannot fall through to the default label.
    const grantBranch = pill.indexOf("sub?.source === 'manual_grant'")
    const firstStripeBranch = pill.indexOf("stripePaid && sub?.status === 'active'")
    assert.ok(grantBranch > -1 && firstStripeBranch > -1)
    assert.ok(
      grantBranch < firstStripeBranch,
      'the manual-grant branch must be evaluated before the Stripe branches',
    )
  })

  test('the paid branches still key off a real Stripe subscription', () => {
    const src = codeOnly(BILLING)
    const pill = src.slice(src.indexOf('function BillingStatusPill'))
    assert.match(pill, /const stripePaid = sub\?\.source === 'stripe_paid'/)
    assert.match(pill, /Past due \(grace\)/)
    assert.match(pill, /Lapsed/)
  })
})
