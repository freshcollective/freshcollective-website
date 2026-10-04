import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  describeCreatorAccess,
  GRACE_PERIOD_DAYS,
  RENEWAL_WINDOW_DAYS,
} from './creatorPlanAccess.ts'
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

  test('the end date is shown as an enforced term', () => {
    const v = describeCreatorAccess(
      plan(),
      sub({ grant_reason: 'comp', ends_at: '2026-11-04T00:00:00Z' }),
      NOW,
    )
    assert.match(v.termNote ?? '', /4 Nov 2026/)
    // "Active until" is accurate now that creator_grant_expiry.py
    // enforces ends_at and returns the creator to Community.
    assert.match(v.termNote ?? '', /Active until/)
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

  test('the active phase states the term without urgency', () => {
    // A grant with a month left needs no countdown and no mention of
    // what happens if they do nothing — that belongs in the renewal
    // window, where there is actually a decision to make.
    const v = describeCreatorAccess(
      plan(), sub({ grant_reason: 'comp', ends_at: '2026-11-04T00:00:00Z' }), NOW,
    )
    assert.equal(v.phase, 'active')
    assert.match(v.termNote ?? '', /Active until/)
    assert.match(v.termNote ?? '', /not be charged/)
  })

  test('a just-past end date gets no bespoke claim either way', () => {
    // Expiry is scheduled, so this state is transient. The old copy
    // asserted "your access is still active", which stops being true
    // the moment the reconciler runs.
    const v = describeCreatorAccess(
      plan(), sub({ grant_reason: 'comp', ends_at: '2026-09-01T00:00:00Z' }), NOW,
    )
    assert.match(v.termNote ?? '', /1 Sept 2026/)
    assert.match(v.termNote ?? '', /ended on/i)
    assert.ok(!/still active/i.test(v.termNote ?? ''))
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
    assert.match(card.statusNote ?? '', /Active until 4 Nov 2026/)
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

  test('the pill asks one question — is this creator billed at all', () => {
    const src = codeOnly(BILLING)
    const pill = src.slice(src.indexOf('function BillingStatusPill'))
    assert.match(pill, /describeCreatorAccess\(plan, sub\)\.isUnbilled/)
    assert.match(pill, /No billing required/)
  })

  test('the unbilled branch is evaluated before the Stripe branches', () => {
    const src = codeOnly(BILLING)
    const pill = src.slice(src.indexOf('function BillingStatusPill'))
    const unbilled = pill.indexOf('.isUnbilled')
    const firstStripeBranch = pill.indexOf("stripePaid && sub?.status === 'active'")
    assert.ok(unbilled > -1 && firstStripeBranch > -1)
    assert.ok(
      unbilled < firstStripeBranch,
      'an unbilled creator must never fall through to a Stripe branch',
    )
  })

  test('the pill no longer depends on is_purchasable', () => {
    // Community has is_purchasable=true (it *is* self-service), so the
    // old zero-price branch missed it and a Community creator saw a
    // yellow "Billing not connected yet".
    const src = codeOnly(BILLING)
    const pill = src.slice(
      src.indexOf('function BillingStatusPill'),
      src.indexOf('function BillingStatusPill') + 1800,
    )
    assert.ok(
      !pill.includes('is_purchasable'),
      'is_purchasable is the wrong question for "is this billed?"',
    )
  })

  test('a Community creator with no subscription is unbilled', () => {
    // Jenson's exact shape: $0 plan, no subscription row at all.
    const v = describeCreatorAccess(
      plan({ slug: 'community', name: 'Community', monthly_price_cents: 0 }),
      null,
      NOW,
    )
    assert.equal(v.isUnbilled, true)
  })

  test('the paid branches still key off a real Stripe subscription', () => {
    const src = codeOnly(BILLING)
    const pill = src.slice(src.indexOf('function BillingStatusPill'))
    assert.match(pill, /const stripePaid = sub\?\.source === 'stripe_paid'/)
    assert.match(pill, /Past due \(grace\)/)
    assert.match(pill, /Lapsed/)
  })
})

describe('the complimentary lifecycle has three phases', () => {
  const ENDS = '2026-11-04T00:00:00Z'

  function at(iso: string) {
    return describeCreatorAccess(
      plan(), sub({ grant_reason: 'comp', ends_at: ENDS }), new Date(iso),
    )
  }

  test('more than 14 days out is active', () => {
    assert.equal(at('2026-10-20T00:00:00Z').phase, 'active')
  })

  test('inside the final 14 days is the renewal window', () => {
    // 2026-10-21 is exactly 14 days before 2026-11-04.
    assert.equal(at('2026-10-22T00:00:00Z').phase, 'renewal')
  })

  test('after the end date is grace, not fallback', () => {
    // The product rule: never straight to Community at ends_at.
    const v = at('2026-11-05T00:00:00Z')
    assert.equal(v.phase, 'grace')
    assert.match(v.label ?? '', /has ended/)
  })

  test('grace copy gives the deadline and protects the content', () => {
    const v = at('2026-11-05T00:00:00Z')
    assert.match(v.termNote ?? '', /11 Nov 2026/)   // ends_at + 7 days
    assert.match(v.termNote ?? '', /until/)
    assert.equal(v.graceEndsOn, '11 Nov 2026')
  })

  test('the renewal phase names the end date', () => {
    assert.match(at('2026-10-25T00:00:00Z').termNote ?? '', /4 Nov 2026/)
  })

  test('no phase ever implies an automatic charge', () => {
    for (const when of [
      '2026-10-20T00:00:00Z', '2026-10-25T00:00:00Z', '2026-11-05T00:00:00Z',
    ]) {
      const note = at(when).termNote ?? ''
      assert.ok(
        !/will be charged|automatically|charged automatically/i.test(note),
        `continuing is always an explicit purchase: ${note}`,
      )
    }
  })

  test('an indefinite grant has no phase', () => {
    const v = describeCreatorAccess(
      plan(), sub({ grant_reason: 'comp', ends_at: null }), NOW,
    )
    assert.equal(v.phase, 'none')
    assert.equal(v.graceEndsOn, null)
  })

  test('a paid subscription has no complimentary phase', () => {
    const v = describeCreatorAccess(
      plan(), sub({ source: 'stripe_paid', grant_reason: null }), NOW,
    )
    assert.equal(v.phase, 'none')
  })

  test('the windows match the backend constants', () => {
    assert.equal(RENEWAL_WINDOW_DAYS, 14)
    assert.equal(GRACE_PERIOD_DAYS, 7)
  })
})

describe('Billing surfaces the continuation offer', () => {
  const BILLING = 'app/creator-studio/billing/page.tsx'

  test('the panel renders only in the renewal and grace phases', () => {
    const src = codeOnly(BILLING)
    assert.match(
      src,
      /access\.phase === 'renewal' \|\| access\.phase === 'grace'/,
    )
  })

  test('it offers the real Stripe subscribe flow, not a prototype', () => {
    const src = codeOnly(BILLING)
    const panel = src.slice(src.indexOf('function ComplimentaryContinuationPanel'))
    assert.match(panel, /StartSubscriptionButton/)
    assert.match(panel, /planSlug="creator"/)
    assert.ok(!panel.includes('/signup/creator'))
    assert.ok(!panel.includes('/checkout/next'))
  })

  test('it never promises an automatic charge', () => {
    const src = codeOnly(BILLING)
    const panel = src.slice(src.indexOf('function ComplimentaryContinuationPanel'))
    assert.ok(!/charged automatically|will be charged/i.test(panel))
  })

  test('it says the content survives', () => {
    const src = codeOnly(BILLING)
    const panel = src.slice(src.indexOf('function ComplimentaryContinuationPanel'))
    assert.match(panel, /Collective and (everything in it|content)/)
  })

  test('it explains that electing early costs nothing extra', () => {
    const src = codeOnly(BILLING)
    const panel = src.slice(src.indexOf('function ComplimentaryContinuationPanel'))
    assert.match(panel, /complimentary time short/)
  })
})
