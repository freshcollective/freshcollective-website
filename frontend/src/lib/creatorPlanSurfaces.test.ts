/**
 * Every creator-facing plan surface states the commission, and states it
 * from the plan configuration rather than its own copy of the number.
 *
 * The Creator Pro commission moved 3% → 4% in October 2026. The public
 * pricing page carried the figure correctly, but three other surfaces a
 * creator passes through on the way to paying did not state it at all:
 *
 *   * the Creator Studio plan comparison cards — the screen where an
 *     upgrade is actually chosen, and where the commission is half of
 *     what is being compared;
 *   * the plan checkout review — the last screen before Stripe;
 *   * the current-plan details — correct on the fee, silent on who pays
 *     the card processing cost, which makes "8% on member sales" read as
 *     "8% plus the card fee".
 *
 * These are source-contract tests: the surfaces are server components,
 * so rather than rendering them this asserts what the source commits to.
 * Comments are stripped first — a figure or a symbol inside a comment is
 * not something the page ships, and matching them produces false
 * failures that teach people to loosen the test.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import { PUBLIC_PLANS, PROCESSING_COVERED_LINE, commissionBullet } from './plans.ts'

function codeOnly(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}

const read = (p: string) => readFileSync(p, 'utf8')

const SRC = {
  sidebar: read('src/app/creator-studio/CreatorStudioSidebar.tsx'),
  billing: read('src/app/creator-studio/billing/page.tsx'),
  checkoutReview: read('src/app/checkout/creator/page.tsx'),
  planTab: read('src/app/creator-studio/account/AccountTabbedShell.tsx'),
  forCreators: read('src/app/for-creators/page.tsx'),
}
const CODE = Object.fromEntries(
  Object.entries(SRC).map(([k, v]) => [k, codeOnly(v)]),
) as Record<keyof typeof SRC, string>

describe('the commission is stated wherever a plan is chosen', () => {
  test('the Creator Studio comparison card renders the commercial terms', () => {
    assert.ok(
      /<PlanCommercialTerms\s+plan=\{plan\}\s*\/>/.test(CODE.billing),
      'the comparison card does not render PlanCommercialTerms',
    )
  })

  test('the comparison card derives the rate from the served plan', () => {
    // formatFee(plan.transaction_fee_basis_points) — the ``creator_plans``
    // value checkout itself reads. Not a literal.
    const block = CODE.billing.slice(
      CODE.billing.indexOf('function PlanCommercialTerms'),
    )
    assert.ok(
      block.includes('formatFee(plan.transaction_fee_basis_points)'),
      'PlanCommercialTerms does not format the served fee',
    )
    assert.ok(
      block.includes('PROCESSING_COVERED_LINE'),
      'PlanCommercialTerms omits who covers card processing',
    )
  })

  test('the checkout review states the commission before Stripe', () => {
    // Asserting the symbol merely *appears* is not enough: replacing the
    // guard with ``{false && (`` left the call site intact inside dead
    // JSX and the check still passed. Both the guard and the rendered
    // node are required, so a block that can never render fails here.
    assert.ok(
      /\{\s*commissionBullet\(plan\)\s*&&\s*\(/.test(CODE.checkoutReview),
      'the commission block is not guarded by the live commission value',
    )
    assert.ok(
      /\{\s*commissionBullet\(plan\)\s*\}/.test(CODE.checkoutReview),
      'the checkout review never renders the commission',
    )
    assert.ok(
      CODE.checkoutReview.includes('PROCESSING_COVERED_LINE'),
      'the checkout review omits who covers card processing',
    )
    // It must appear before the button that leaves for Stripe, or it is
    // not a review of what is being agreed to.
    assert.ok(
      CODE.checkoutReview.indexOf('commissionBullet(plan)')
        < CODE.checkoutReview.indexOf('<CreatorCheckoutButton'),
      'the commission is stated after the Stripe CTA',
    )
  })

  test('the current-plan details say who covers card processing', () => {
    assert.ok(
      CODE.planTab.includes('PROCESSING_COVERED_LINE'),
      'the Plan tab omits who covers card processing',
    )
  })
})

describe('no plan surface carries its own copy of a rate', () => {
  test('no creator-facing surface writes a commission percentage inline', () => {
    for (const [name, src] of Object.entries(CODE)) {
      const stated = src.match(/\d+%\s*(commission|on paid|on member sales|platform fee)/)
      assert.equal(stated, null, `${name} states ${stated?.[0]} inline`)
    }
  })

  test('the comparison card states the commission exactly once', () => {
    // It used to be pushed into the bullet list by two fallback helpers
    // as well. Three copies on one card is how a figure gets half-updated.
    const pushes = CODE.billing.match(
      /out\.push\(`\$\{formatFee\(plan\.transaction_fee_basis_points\)\}/g,
    )
    assert.equal(pushes, null, 'a fallback helper still pushes the fee as a bullet')
  })
})

describe('Creator Portfolio is the name everywhere a customer looks', () => {
  test('the public pricing page takes its plan names from the config', () => {
    for (const slug of ['community', 'creator', 'pro'] as const) {
      assert.ok(
        CODE.forCreators.includes(`name: PUBLIC_PLANS.${slug}.displayName`),
        `/for-creators hardcodes the ${slug} plan name`,
      )
    }
  })

  test('the config calls the $79 tier Creator Portfolio, never Pro', () => {
    assert.equal(PUBLIC_PLANS.pro.displayName, 'Creator Portfolio')
    assert.equal(PUBLIC_PLANS.pro.slug, 'pro', 'the internal slug must stay pro')
  })

  test('Creator Studio never prints a raw plan name', () => {
    // ``plan.name`` is the internal name ("Pro"). Every creator-facing
    // render goes through creatorFacingPlanName, which maps the slug.
    for (const key of ['billing', 'planTab'] as const) {
      const raw = CODE[key].match(/\{\s*(current_)?plan\.name\s*\}/)
      assert.equal(raw, null, `${key} prints a raw plan name: ${raw?.[0]}`)
    }
  })
})

describe('the plan comparison page is reachable from the sidebar', () => {
  test('ACCOUNT carries a Creator Plan link', () => {
    const accountNav = CODE.sidebar.slice(
      CODE.sidebar.indexOf('const ACCOUNT_NAV'),
      CODE.sidebar.indexOf('interface Props'),
    )
    assert.ok(
      accountNav.includes("label: 'Creator Plan'"),
      'ACCOUNT has no Creator Plan link',
    )
    assert.ok(
      accountNav.includes("href: '/creator-studio/billing'"),
      'the Creator Plan link does not point at the plan page',
    )
  })

  test('it points at the existing page, not a new one', () => {
    // Account → Plan's "Manage plan" button already opens
    // /creator-studio/billing. The sidebar link must be the same
    // destination, so there is one page and no duplicated flow.
    assert.ok(
      CODE.planTab.includes('href="/creator-studio/billing"'),
      'Account → Plan no longer links to the plan page',
    )
  })

  test('Account itself still has its own link', () => {
    const accountNav = CODE.sidebar.slice(
      CODE.sidebar.indexOf('const ACCOUNT_NAV'),
      CODE.sidebar.indexOf('interface Props'),
    )
    assert.ok(accountNav.includes("label: 'Account'"), 'the Account link was lost')
  })

  test('the link is not gated behind paid offers', () => {
    // A Community creator is exactly who needs to find the upgrade path.
    const accountNav = CODE.sidebar.slice(
      CODE.sidebar.indexOf('const ACCOUNT_NAV'),
      CODE.sidebar.indexOf('interface Props'),
    )
    const planLine = accountNav
      .split('\n')
      .find((l) => l.includes("label: 'Creator Plan'")) ?? ''
    assert.ok(
      !planLine.includes('requiresPaidOffers'),
      'the Creator Plan link is hidden from Community creators',
    )
  })
})

describe('the shared lines read as intended', () => {
  test('the commission bullet names the live rate', () => {
    assert.equal(commissionBullet(PUBLIC_PLANS.pro), '4% commission on paid offers')
    assert.equal(commissionBullet(PUBLIC_PLANS.creator), '8% commission on paid offers')
  })

  test('Community has no commission line to state', () => {
    assert.equal(commissionBullet(PUBLIC_PLANS.community), null)
  })

  test('the processing line quotes no rate', () => {
    assert.ok(!/\d/.test(PROCESSING_COVERED_LINE), PROCESSING_COVERED_LINE)
  })
})
