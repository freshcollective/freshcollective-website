import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { PUBLIC_PLANS } from './plans.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const BILLING = 'app/creator-studio/billing/page.tsx'
const DASHBOARD = 'app/dashboard/page.tsx'
const ORIENTATION = 'app/dashboard/FirstCollectiveOrientation.tsx'
const BUILD_CLIENT = 'app/build-your-collective/BuildYourCollectiveClient.tsx'

// ---------------------------------------------------------------------------
// 1. Community Billing shows no commercial payment infrastructure
// ---------------------------------------------------------------------------

describe('Community Billing hides payment setup', () => {
  test('the payment setup block is gated on the plan capability', () => {
    const src = codeOnly(BILLING)
    assert.match(
      src,
      /\{current_plan\.paid_offers_enabled && \(\s*\n\s*<>/,
      'the commercial block must be gated on paid_offers_enabled',
    )
  })

  test('Stripe Connect sits inside the gate, not before it', () => {
    const src = codeOnly(BILLING)
    const gate = src.indexOf('{current_plan.paid_offers_enabled && (')
    const connect = src.indexOf('<StripeConnectPanel')
    assert.ok(gate > -1 && connect > -1)
    assert.ok(connect > gate, 'StripeConnectPanel must be inside the gate')
  })

  test('the gate uses the capability, never a plan-name string', () => {
    const src = codeOnly(BILLING)
    // A slug comparison would silently exclude Founding Creator or a
    // complimentary Creator grant.
    assert.ok(
      !/current_plan\.slug === 'community'/.test(src),
      'gate on paid_offers_enabled, not on the plan slug',
    )
  })

  test('the current-plan card and plan comparison stay outside the gate', () => {
    const src = codeOnly(BILLING)
    const gate = src.indexOf('{current_plan.paid_offers_enabled && (')
    const currentPlanCard = src.indexOf('Current plan')
    const comparison = src.indexOf('available_plans')
    assert.ok(currentPlanCard > -1 && currentPlanCard < gate,
      'Community must still see its current plan')
    assert.ok(comparison > -1 && comparison < gate,
      'Community must still see the plan comparison / upgrade options')
  })

  test('no second upgrade CTA is bolted on after the comparison', () => {
    // The comparison already carries Start/Upgrade buttons; another
    // prompt here would be the third on one page.
    const src = codeOnly(BILLING)
    const gate = src.indexOf('{current_plan.paid_offers_enabled && (')
    const tail = src.slice(gate)
    assert.ok(
      !/Want to sell through your Collective/.test(tail),
      'option A was chosen — the comparison is the upgrade affordance',
    )
  })

  test('the Platform Owner branch is untouched', () => {
    const src = codeOnly(BILLING)
    assert.match(src, /function PlatformOwnerBilling/)
    const owner = src.slice(src.indexOf('function PlatformOwnerBilling'))
    assert.match(owner, /Member payments/, 'owner keeps the commercial view')
  })
})

// ---------------------------------------------------------------------------
// 2. Create a Collective reaches a plan choice
// ---------------------------------------------------------------------------

describe('Create a Collective leads to a plan choice', () => {
  test('a non-Creator is sent to the plan chooser, anchored at the plans', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /const PLAN_CHOOSER_HREF = '\/for-creators#plans'/)
  })

  test('it does not silently choose Community', () => {
    const src = codeOnly(DASHBOARD)
    assert.ok(
      !src.includes('plan=community'),
      'the dashboard must not preselect a plan on the reader’s behalf',
    )
  })

  test('an existing Creator goes to the plan-aware creator home', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /const CREATOR_HOME_HREF = '\/creator-studio'/)
    assert.match(src, /isCreator \? CREATOR_HOME_HREF : PLAN_CHOOSER_HREF/)
  })

  test('both CTAs receive the creator state', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /<CreateCollectiveLink isCreator=\{isCreatorOrAdmin\} \/>/)
    assert.match(src, /<EmptyCollectivesCard isCreator=\{isCreatorOrAdmin\} \/>/)
  })

  test('every plan the chooser offers has a live destination', () => {
    // Community → live activation. Creator / Pro → /checkout/creator,
    // which POSTs to /api/purchases/creator-subscription for a real
    // Stripe Checkout Session. No prototype or holding screen.
    assert.equal(PUBLIC_PLANS.community.ctaHref, '/signup/creator?plan=community')
    assert.equal(PUBLIC_PLANS.creator.ctaHref, '/checkout/creator?plan=creator')
    assert.equal(PUBLIC_PLANS.pro.ctaHref, '/checkout/creator?plan=pro')
    for (const plan of Object.values(PUBLIC_PLANS)) {
      assert.ok(
        !plan.ctaHref.includes('/checkout/next'),
        `${plan.slug} must not point at the prototype holding screen`,
      )
      assert.ok(!plan.ctaHref.includes('preview=true'))
    }
  })

  test('the paid checkout page is the live Stripe one', () => {
    const src = read('app/checkout/creator/page.tsx')
    assert.match(src, /api\/purchases\/creator-subscription|CreatorCheckoutButton/)
    // Community is redirected away rather than offered a paid page.
    assert.match(src, /signup\/creator\?plan=community/)
  })
})

// ---------------------------------------------------------------------------
// 3. Post-onboarding orientation
// ---------------------------------------------------------------------------

describe('post-onboarding orientation points at the creator band', () => {
  test('the handoff carries the completion state', () => {
    const src = codeOnly(BUILD_CLIENT)
    assert.match(src, /\/dashboard\?creator_onboarding=complete/)
  })

  test('the prompt needs both the flag and Creator capability', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /justFinishedFirstCollective && isCreatorOrAdmin/)
    assert.match(src, /onboardingFlag === 'complete'/)
  })

  test('it targets the existing creator band, not a new section', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /const CREATOR_BAND_ID = 'what-youre-building'/)
    assert.match(src, /id=\{CREATOR_BAND_ID\}/)
    assert.match(src, /targetId=\{CREATOR_BAND_ID\}/)
  })

  test('it cannot become permanent — the param is consumed', () => {
    const src = codeOnly(ORIENTATION)
    assert.match(src, /router\.replace\('\/dashboard', \{ scroll: false \}\)/)
  })

  test('it scrolls rather than duplicating the creator cards', () => {
    const src = codeOnly(ORIENTATION)
    assert.match(src, /scrollIntoView\(\{ behavior: 'smooth'/)
    assert.ok(
      !src.includes('CreatorStudioCard') && !src.includes('CreatorCollectiveCard'),
      'Your World must not become a Creator dashboard',
    )
  })

  test('the creator band still holds everything the prompt promises', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /Collectives you created/)
    assert.match(src, /CreatorStudioCard/)
    // World Builders arrives through ordinary memberships, unfiltered.
    assert.ok(!/auto_grant_role/.test(src))
  })

  test('a plain member never sees the prompt', () => {
    const src = codeOnly(DASHBOARD)
    const i = src.indexOf('<FirstCollectiveOrientation')
    const guard = src.lastIndexOf('isCreatorOrAdmin', i)
    assert.ok(guard > -1 && i - guard < 200, 'must sit behind the creator guard')
  })
})
