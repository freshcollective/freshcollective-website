import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * These files explain at length *why* commerce is hidden on Community,
 * so a raw substring check would trip on the explanation rather than a
 * regression.
 */
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const SIDEBAR = 'app/creator-studio/CreatorStudioSidebar.tsx'
const COMMERCIAL_ROUTES = [
  'app/creator-studio/payment-options/page.tsx',
  'app/creator-studio/discount-codes/page.tsx',
  'app/creator-studio/payments/page.tsx',
  'app/creator-studio/payment-plans/page.tsx',
  'app/creator-studio/access/page.tsx',
]

describe('Creator Studio navigation is plan-aware, not capability-only', () => {
  test('every commercial nav item is plan-gated', () => {
    const src = codeOnly(SIDEBAR)
    // Each item is one object literal on one line; the plan flag must
    // appear on the same line as the href.
    for (const href of [
      '/creator-studio/payment-options',
      '/creator-studio/discount-codes',
      '/creator-studio/payments',
      '/creator-studio/payment-plans',
      '/creator-studio/access',
      '/creator-studio/offers',
    ]) {
      const line = src.split('\n').find((l) => l.includes(`href: '${href}'`))
      assert.ok(line, `no nav entry for ${href}`)
      assert.match(
        line,
        /requiresPaidOffers: true/,
        `${href} must be hidden from plans without paid offers`,
      )
    }
  })

  test('non-commercial tools are NOT plan-gated', () => {
    const src = codeOnly(SIDEBAR)
    // A Community creator must keep everything their plan includes:
    // pathways, gatherings, resources, conversations, people.
    for (const href of [
      '/creator-studio/community',
      '/creator-studio/people',
    ]) {
      const line = src.split('\n').find((l) => l.includes(`href: '${href}'`))
      assert.ok(line, `no nav entry for ${href}`)
      assert.ok(
        !line.includes('requiresPaidOffers'),
        `${href} is non-commercial and must stay visible on Community`,
      )
    }
  })

  test('the plan gate outranks "paused"', () => {
    // Offer Pages is paused AND commercial. "Coming later" is
    // misleading to a plan that will never unlock it.
    const src = codeOnly(SIDEBAR)
    assert.match(src, /items\.filter\(\s*\(\{ requiresPaidOffers \}\) =>/)
    assert.ok(
      !/paused \|\| !requiresPaidOffers/.test(src),
      'paused must no longer bypass the plan gate',
    )
  })

  test('a fully gated group renders nothing, not a bare heading', () => {
    const src = codeOnly(SIDEBAR)
    assert.match(src, /if \(visible\.length === 0\) return null/)
  })

  test('the gate is driven by the resolved plan capability', () => {
    const layout = codeOnly('app/creator-studio/layout.tsx')
    assert.match(layout, /current_plan\?\.paid_offers_enabled/)
    // Platform Owner always commercial; a fetch failure must hide, not
    // expose.
    assert.match(layout, /is_platform_owner/)
    assert.match(layout, /let paidOffersEnabled = false/)
  })
})

describe('direct navigation does not grant commercial capability', () => {
  test('every commercial route gates on the resolved plan', () => {
    for (const route of COMMERCIAL_ROUTES) {
      const src = codeOnly(route)
      assert.match(
        src,
        /paid_offers_enabled/,
        `${route} must check the plan, not just creator capability`,
      )
      assert.match(
        src,
        /PlanUpgradeNotice/,
        `${route} must render the upgrade notice rather than the tool`,
      )
    }
  })

  test('the notice points at a real upgrade surface', () => {
    const src = codeOnly('components/creator/PlanUpgradeNotice.tsx')
    assert.match(src, /href="\/creator-studio\/billing"/)
    // Must not send a Community creator into the prototype signup flow.
    assert.ok(!src.includes('/signup/creator'))
    assert.ok(!src.includes('/checkout/next'))
    assert.ok(!src.includes('preview=true'))
  })

  test('platform owner is never locked out of commercial routes', () => {
    for (const route of COMMERCIAL_ROUTES) {
      const src = codeOnly(route)
      assert.match(src, /is_platform_owner/, `${route} must exempt the owner`)
    }
  })
})

describe('pricing types mirror the backend guard', () => {
  const FORM = 'app/creator-studio/settings/CollectiveSettingsForm.tsx'

  test('only Free is non-commercial, matching guard_paid_offers_enabled', () => {
    // The guard early-returns for pricing_type == 'free' only, so every
    // other value — invite_only and coming_soon included — is refused
    // on Community today. The table must not be a prettier guess.
    const src = read(FORM)
    const table = src.slice(src.indexOf('PRICING_TYPE_OPTIONS'))
    const free = table.slice(table.indexOf("'free'"), table.indexOf("'paid_one_time'"))
    assert.match(free, /commercial: false/)
    for (const value of [
      'paid_one_time', 'paid_monthly', 'paid_annual',
      'invite_only', 'coming_soon',
    ]) {
      const i = table.indexOf(`'${value}'`)
      assert.ok(i > -1, `${value} missing from the option table`)
      const row = table.slice(i, i + 120)
      assert.match(row, /commercial: true/, `${value} must require a paid plan`)
    }
  })

  test('paid types are unselectable without the capability', () => {
    const src = codeOnly(FORM)
    assert.match(src, /disabled=\{commercial && !paidOffersEnabled/)
  })

  test('a value already saved stays selectable', () => {
    // Otherwise a Collective holding a paid type from an earlier plan
    // renders a select that misreports its own state, with no way back
    // to Free.
    const src = codeOnly(FORM)
    assert.match(src, /value !== space\.pricing_type/)
  })

  test('an upgrade affordance replaces a silent dead end', () => {
    const src = codeOnly(FORM)
    assert.match(src, /Paid pricing is available on Creator plans/)
    assert.match(src, /creator-studio\/billing/)
  })
})

describe('Account → Plan states Community as a real plan', () => {
  const ACCOUNT = 'app/creator-studio/account/AccountTabbedShell.tsx'

  test('it no longer says "No active plan"', () => {
    const src = codeOnly(ACCOUNT)
    assert.ok(
      !src.includes('No active plan'),
      'Community is a deliberate $0 plan, not an absence',
    )
    assert.ok(!src.includes('Once you subscribe to a plan'))
  })

  test('a $0 plan reads as Free, not $0 / month', () => {
    const src = codeOnly(ACCOUNT)
    assert.match(src, /monthly_price_cents === 0\s*\n?\s*\?\s*'Free'/)
  })

  test('plan bullets come from the backend capability record', () => {
    const src = codeOnly(ACCOUNT)
    assert.match(src, /plan\.card_features/)
  })

  test('a non-commercial plan gets an upgrade CTA', () => {
    const src = codeOnly(ACCOUNT)
    assert.match(src, /paid_offers_enabled \? 'Manage plan →' : 'Upgrade plan →'/)
    assert.match(src, /creator-studio\/billing/)
  })
})
