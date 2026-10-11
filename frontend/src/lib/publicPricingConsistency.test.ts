/**
 * The public pricing figures must match what checkout actually charges.
 *
 * Checkout reads the ``creator_plans`` row in the database. Every public
 * surface reads :data:`PUBLIC_PLANS`. Those two can drift, and the direction
 * that matters is a public page advertising a *lower* commission than is
 * actually taken — a creator would have signed up on a promise Fresh
 * Collective then broke on every sale.
 *
 * The frontend test runner cannot reach the database, so this pins the
 * published figures to the values recorded here. Changing the live Pro fee
 * therefore fails this test until the config and this file move together,
 * which is the point: the failure is the reminder.
 *
 * It also enforces that the figure lives in one place. Before this, the home
 * page and /for-creators each carried their own copy of the commission.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import {
  PROCESSING_COVERED_LINE,
  PUBLIC_PLANS,
  commissionBullet,
  commissionBulletShort,
} from './plans.ts'

/**
 * What ``creator_plans`` holds in production right now.
 *
 * Creator is 8%. Pro is 3% — the intended rate is 4%, but the database
 * change has not been approved, so 4% must not be published yet.
 */
const LIVE_COMMISSION_BPS = { creator: 800, pro: 300 } as const

/**
 * Source with comments removed.
 *
 * A comment is not published, so a figure inside one is not a pricing claim
 * — and matching them produces false failures that teach people to loosen
 * the test. What ships is what matters.
 */
function codeOnly(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
    // Import declarations too: counting a symbol's *usages* must not count
    // the line that brings it into scope. Without this, removing one of two
    // usages still left two matches and the check passed.
    .replace(/^import\s[\s\S]*?from\s+'[^']+'\s*$/gm, '')
}

const PAGES = {
  forCreators: codeOnly(readFileSync('src/app/for-creators/page.tsx', 'utf8')),
  home: codeOnly(readFileSync('src/components/home/HomePricing.tsx', 'utf8')),
}

describe('the shared pricing config matches production', () => {
  test('Creator commission', () => {
    assert.equal(PUBLIC_PLANS.creator.commissionBasisPoints, LIVE_COMMISSION_BPS.creator)
    assert.equal(PUBLIC_PLANS.creator.commissionLabel, '8%')
  })

  test('Pro commission is the live 3%, not the intended 4%', () => {
    assert.equal(PUBLIC_PLANS.pro.commissionBasisPoints, LIVE_COMMISSION_BPS.pro)
    assert.equal(PUBLIC_PLANS.pro.commissionLabel, '3%')
  })

  test('the label and the basis points agree', () => {
    // A label saying one thing while the number says another would publish a
    // figure nobody chose.
    for (const plan of Object.values(PUBLIC_PLANS)) {
      if (plan.commissionBasisPoints === null) {
        assert.equal(plan.commissionLabel, null, plan.slug)
        continue
      }
      assert.equal(
        plan.commissionLabel,
        `${plan.commissionBasisPoints / 100}%`,
        plan.slug,
      )
    }
  })

  test('Community states no commission at all', () => {
    assert.equal(PUBLIC_PLANS.community.commissionBasisPoints, null)
    assert.equal(commissionBullet(PUBLIC_PLANS.community), null)
  })

  test('the bullet helpers read the config', () => {
    assert.equal(commissionBullet(PUBLIC_PLANS.creator), '8% commission on paid offers')
    assert.equal(commissionBulletShort(PUBLIC_PLANS.pro), '3% on paid transactions')
  })
})

describe('no public surface hardcodes its own figure', () => {
  test('neither page hardcodes a commission percentage', () => {
    // This is what Option B bought: one value, two readers.
    for (const [name, src] of Object.entries(PAGES)) {
      const hardcoded = src.match(/'[0-9]+%\s+(on paid|commission)/)
      assert.equal(hardcoded, null, `${name} hardcodes ${hardcoded?.[0]}`)
    }
  })

  test('neither page hardcodes a monthly price', () => {
    for (const [name, src] of Object.entries(PAGES)) {
      const hardcoded = src.match(/'\$\d+ \/ month'/)
      assert.equal(hardcoded, null, `${name} hardcodes ${hardcoded?.[0]}`)
    }
  })

  test('the unapproved 4% rate appears nowhere public', () => {
    for (const [name, src] of Object.entries(PAGES)) {
      assert.ok(!/4%\s+(commission|on paid|platform fee)/.test(src), name)
    }
    assert.notEqual(PUBLIC_PLANS.pro.commissionLabel, '4%')
  })
})

describe('the all-inclusive model is stated publicly', () => {
  test('both paid plans say Fresh Collective covers processing', () => {
    for (const [name, src] of Object.entries(PAGES)) {
      const occurrences = src.split('PROCESSING_COVERED_LINE').length - 1
      assert.equal(occurrences, 2, `${name} states it ${occurrences} time(s)`)
    }
  })

  test('the line itself names no rate', () => {
    // Fresh Collective absorbs the cost, so quoting a processing rate only
    // invites a creator to subtract something they never pay.
    assert.ok(!/\d/.test(PROCESSING_COVERED_LINE), PROCESSING_COVERED_LINE)
  })

  test('no Stripe processing rate is quoted anywhere public', () => {
    // 1.75% was Stripe's old AU rate and survived in creator-facing copy long
    // after Stripe moved to 1.65%. Matched as rates, not bare numbers —
    // "1.75rem" is a font size.
    const rateLike = /\b(1\.75|1\.65|2\.9|2\.75)\s*%|\$0\.30\b/
    for (const [name, src] of Object.entries(PAGES)) {
      const match = src.match(rateLike)
      assert.equal(match, null, `${name} quotes ${match?.[0]}`)
    }
  })
})

describe('Commerce navigation', () => {
  const SIDEBAR = codeOnly(
    readFileSync('src/app/creator-studio/CreatorStudioSidebar.tsx', 'utf8'),
  )

  test('Bank payouts has its own nav entry', () => {
    // The defect this fixes: everything about payouts lived on
    // /creator-studio/billing, which has no nav entry at all. A creator who
    // had finished setting up could not find their payout settings again.
    assert.match(SIDEBAR, /href: '\/creator-studio\/bank-payouts'/)
    assert.match(SIDEBAR, /label: 'Bank payouts'/)
  })

  test('it sits beside Payments received, both plan-gated the same way', () => {
    const payments = SIDEBAR.indexOf("'/creator-studio/payments'")
    const payouts = SIDEBAR.indexOf("'/creator-studio/bank-payouts'")
    assert.ok(payments > 0 && payouts > payments, 'money in, then money out')
    // Community has no paid offers, so neither entry should appear there.
    const entry = SIDEBAR.slice(payouts, payouts + 200)
    assert.match(entry, /requiresPaidOffers: true/)
  })

  test('Billing no longer renders a second copy of the Connect panel', () => {
    const billing = codeOnly(
      readFileSync('src/app/creator-studio/billing/page.tsx', 'utf8'),
    )
    assert.ok(
      !billing.includes('<StripeConnectPanel'),
      'the panel must live in one place, or the two surfaces can disagree',
    )
    assert.match(billing, /\/creator-studio\/bank-payouts/)
  })

  test('the payout setup card points at the page, not a fragment', () => {
    const card = codeOnly(readFileSync('src/lib/payoutSetupCard.ts', 'utf8'))
    assert.match(card, /PAYOUTS_HREF = '\/creator-studio\/bank-payouts'/)
    assert.ok(!/billing#payouts/.test(card))
  })

  test('the platform owner is not shut out of the payout page', () => {
    // ``is_platform_owner`` previously replaced the whole panel with a
    // "not required" message, so the Platform Owner — who holds a Founding
    // Creator plan and a live connected account — could not reach their own
    // payout settings at all.
    const page = codeOnly(
      readFileSync('src/app/creator-studio/bank-payouts/page.tsx', 'utf8'),
    )
    assert.match(page, /gate\?\.is_platform_owner/)
    // Rendered via BankPayoutsSections, which shares one status between the
    // readiness panel and the bank-account section.
    assert.match(page, /<BankPayoutsSections/)
    const sections = codeOnly(
      readFileSync('src/app/creator-studio/bank-payouts/BankPayoutsSections.tsx', 'utf8'),
    )
    assert.match(sections, /<StripeConnectPanel/)
    // Rendered unconditionally, not inside a role branch.
    assert.ok(!/is_platform_owner \?/.test(page))
  })
})
