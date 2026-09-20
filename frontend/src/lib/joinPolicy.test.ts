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
    const src = doors()
    assert.match(src, /apiUrl\('\/api\/checkout'\)/)
    // Banned as a destination, not as a word — the file explains in a
    // comment why the prototype is not used, which is worth keeping.
    assert.ok(!/fetch\([^)]*checkout\/member/.test(src), 'no call to the prototype')
    assert.ok(!/href=.*checkout\/member/.test(src), 'no link to the prototype')
    assert.match(src, /payment_option_id: optionId/)
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

  test('a signed-out visitor is sent to sign in, not to a dead button', () => {
    assert.match(doors(), /Sign in to join/)
  })

  test('the copy says membership comes with the purchase', () => {
    // One purchase, not two steps — the product point of the phase.
    assert.match(doors(), /Joining happens with your purchase/)
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
