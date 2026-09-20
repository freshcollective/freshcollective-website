import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * Joining a Collective, from the outside.
 *
 * Free joining is the default and must stay untouched; purchase-
 * required removes the free door and offers the creator's chosen
 * Payment Options instead. The rule is enforced server-side — these
 * pin the client so it agrees rather than invents.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

describe('the About call to action', () => {
  const cta = () => read('app/spaces/[slug]/about/SpaceAboutCTA.tsx')

  test('an open Collective keeps its free Join action', () => {
    const src = cta()
    assert.match(src, /\/api\/spaces\/\$\{slug\}\/join/)
    assert.ok(src.includes("joinPolicy = 'open'"), 'and open is the default')
  })

  test('purchase-required replaces it with the doors', () => {
    const src = cta()
    assert.match(src, /if \(joinPolicy === 'purchase_required'\)/)
    assert.match(src, /<JoiningDoors/)
  })

  test('the policy is checked before the display-only pricing branches', () => {
    // pricing_type is a display string; join_policy is the enforced
    // rule. If pricing branches ran first, a Collective marked
    // "coming_soon" would hide doors that actually work.
    const src = cta()
    assert.ok(
      src.indexOf("joinPolicy === 'purchase_required'") <
      src.indexOf("pricingType === 'invite_only'"),
    )
  })

  test('the page passes the real values through', () => {
    const page = read('app/spaces/[slug]/about/page.tsx')
    assert.match(page, /joinPolicy=\{space\.join_policy \?\? 'open'\}/)
    assert.match(page, /joiningOptions=\{space\.joining_options \?\? \[\]\}/)
  })
})

describe('the joining doors', () => {
  const doors = () => read('app/spaces/[slug]/about/JoiningDoors.tsx')

  test('they lead into the real checkout, not the prototype', () => {
    // Through the shared button, which is the same one the Series
    // sidebar uses — one purchase, two entry points.
    const src = doors()
    assert.match(src, /ScheduleChoice/)
    const button = read('components/commerce/PurchaseScheduleButton.tsx')
    assert.match(button, /apiUrl\('\/api\/checkout'\)/)
    assert.ok(!/fetch\([^)]*checkout\/member/.test(src), 'no call to the prototype')
    assert.ok(!/href=.*checkout\/member/.test(src), 'no link to the prototype')
  })

  test('the checkout request carries BOTH ids', () => {
    // payment_option_schedule_id is required by UnifiedCheckoutRequest.
    // The first door sent only the option id and 422'd before any
    // business logic ran.
    const button = read('components/commerce/PurchaseScheduleButton.tsx')
    assert.match(button, /payment_option_id: paymentOptionId/)
    assert.match(button, /payment_option_schedule_id: paymentOptionScheduleId/)
  })

  test('a door with several ways to pay lets the member choose', () => {
    const src = doors()
    assert.match(src, /buyable\.map\(\(schedule, i\) =>/)
    assert.match(src, /is_member_checkoutable/)
  })

  test('a schedule the backend would refuse is never offered', () => {
    // The surface reads the backend's flag; it must not re-decide.
    const src = doors()
    assert.match(src, /filter\(\s*\(s\) => s\.is_member_checkoutable,?\s*\)/)
  })

  test('prices come from schedules, never the legacy option columns', () => {
    // Banned as a field access, not as a word — the file documents
    // in prose why those columns are the wrong source.
    const src = doors()
    assert.ok(!/\.override_total_cents/.test(src), 'legacy column read')
    assert.ok(!/\.calculated_total_cents/.test(src), 'legacy column read')
    assert.match(src, /scheduleShortDescription/, 'uses the shared formatter')
  })

  test('no doors is a closed state, never a free join', () => {
    // The escape hatch that must not exist.
    const src = doors()
    assert.match(src, /options\.length === 0/)
    assert.match(src, /Not open for new members right now/)
    assert.ok(
      !/apiUrl\(`\/api\/spaces\/\$\{slug\}\/join`\)/.test(src),
      'no free-join call anywhere in this file',
    )
  })

  test('a signed-out visitor sees the real prices before signing in', () => {
    // Learning the price only after creating an account is the wrong
    // order to learn it in.
    const src = doors()
    assert.match(src, /Sign in to continue/)
    assert.match(src, /priceSummary\(option\)/)
    assert.ok(!src.includes('Sign in to join'), 'not a promise of free membership')
  })

  test('an existing member is not told to join again', () => {
    const src = doors()
    assert.match(src, /isMember/)
    assert.match(src, /Purchase \$\{option\.name\}/)
  })

  test('the copy says membership comes with the purchase', () => {
    // One purchase, not two steps — the product point of the phase.
    assert.match(doors(), /Membership comes with your (first )?purchase/)
  })
})

describe('the Creator Studio control', () => {
  const form = () => read('app/creator-studio/settings/JoinPolicyForm.tsx')

  test('the tab is called Access & Visibility', () => {
    const shell = read('app/creator-studio/settings/SettingsTabbedShell.tsx')
    assert.match(shell, /label: 'Access & Visibility'/)
    assert.match(shell, /key: 'visibility'/, 'URL key unchanged')
  })

  test('it offers exactly the two supported policies', () => {
    const src = form()
    assert.match(src, /value: 'open' as const/)
    assert.match(src, /value: 'purchase_required' as const/)
    assert.ok(!src.includes('invite_only'), 'no third policy was invented')
  })

  test('free to join is described as fully supported, not legacy', () => {
    assert.match(form(), /Free to join/)
    assert.match(form(), /Anyone signed in can join/)
  })

  test('doors are chosen from published options only', () => {
    const src = form()
    assert.match(src, /options\.filter\(\(o\) => o\.status === 'published'\)/)
  })

  test('a creator with no usable doors is warned loudly', () => {
    const src = form()
    assert.match(src, /No ways to join are selected/)
    assert.match(src, /no published Payment Options yet/)
    assert.match(src, /not open for new members right now/)
  })

  test('it explains that buying a door also grants what the option grants', () => {
    assert.match(form(), /one purchase, not two/i)
  })

  test('auto-managed Collectives do not get the control', () => {
    const shell = read('app/creator-studio/settings/SettingsTabbedShell.tsx')
    assert.match(shell, /!spaceDetail\.auto_grant_role && \(/)
  })

  test('changing the policy never removes members, and says so', () => {
    assert.match(form(), /never removes anyone/)
  })
})


describe('the shared purchase components', () => {
  const read2 = (p: string) => read(p)

  test('the Series sidebar and the joining doors use one button', () => {
    // Cloning the checkout call is how the two surfaces would drift
    // on what a price or a commitment means.
    const sidebar = read2('app/spaces/[slug]/gathering-series/[series-slug]/SeriesSidebar.tsx')
    const doors = read2('app/spaces/[slug]/about/JoiningDoors.tsx')
    for (const src of [sidebar, doors]) {
      assert.match(src, /from '@\/components\/commerce\/ScheduleChoice'/)
      assert.ok(!/apiUrl\('\/api\/checkout'\)/.test(src), 'no second checkout call')
    }
  })

  test('the button is told where to return, not which series it is', () => {
    const button = read2('components/commerce/PurchaseScheduleButton.tsx')
    assert.match(button, /returnBase: string/)
    assert.ok(!button.includes('seriesSlug'), 'no leftover series coupling')
  })

  test('the finite-plan confirmation step survived the extraction', () => {
    const button = read2('components/commerce/PurchaseScheduleButton.tsx')
    assert.match(button, /PaymentPlanConfirmDialog/)
    assert.match(button, /planConfirmationCopy/)
  })

  test('both surfaces return the buyer to where they started', () => {
    const doors = read2('app/spaces/[slug]/about/JoiningDoors.tsx')
    assert.match(doors, /returnBase = `\/spaces\/\$\{slug\}\/about`/)
    const sidebar = read2('app/spaces/[slug]/gathering-series/[series-slug]/SeriesSidebar.tsx')
    assert.match(sidebar, /returnBase=\{`\/spaces\/\$\{spaceSlug\}\/gathering-series\/\$\{seriesSlug\}`\}/)
  })
})

describe('the purchase-required CTA is evaluated first', () => {
  const cta = () => read('app/spaces/[slug]/about/SpaceAboutCTA.tsx')

  test('before the signed-out branch', () => {
    // That branch renders "Join collective", which promises free
    // membership a purchase-required Collective does not have.
    const src = cta()
    assert.ok(
      src.indexOf("joinPolicy === 'purchase_required'") < src.indexOf('// Not logged in'),
    )
  })

  test('but after the states of people already inside', () => {
    const src = cta()
    const policy = src.indexOf("joinPolicy === 'purchase_required'")
    assert.ok(src.indexOf('hasPendingInvite') > policy || src.indexOf('isMember') < policy)
  })

  test('the Collective palette reaches the purchase buttons', () => {
    assert.match(cta(), /palette=\{palette\}/)
    assert.match(read('app/spaces/[slug]/about/page.tsx'), /palette=\{space\.colour_palette \?\? null\}/)
  })
})
