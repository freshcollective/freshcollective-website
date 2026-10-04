import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * Comments in these files explain the handoff decision at length —
 * which Creator Studio CTA was removed and why — so a raw substring
 * check would fail on the explanation rather than on a regression.
 */
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const CONFIRM = 'components/build/steps/ConfirmationStep.tsx'
const CLIENT = 'app/build-your-collective/BuildYourCollectiveClient.tsx'
const DASHBOARD = 'app/dashboard/page.tsx'

describe('completion routes into Your World', () => {
  test('Your World is an accepted destination', () => {
    const src = codeOnly(CONFIRM)
    assert.match(src, /'your_world'/)
  })

  test('the primary CTA is Your World', () => {
    const src = codeOnly(CONFIRM)
    // The primary button is the gradient pill; the secondary is plain
    // text. Assert on order: Your World must come first.
    const yourWorld = src.indexOf("onOpen('your_world')")
    const worldBuilders = src.indexOf("onOpen('world_builders')")
    assert.ok(yourWorld > -1, 'Your World CTA must exist')
    assert.ok(worldBuilders > -1, 'World Builders CTA must remain')
    assert.ok(
      yourWorld < worldBuilders,
      'Your World must be the primary (first) CTA',
    )
    assert.match(src, /Enter Your World/)
  })

  test('World Builders remains reachable as a secondary CTA', () => {
    const src = codeOnly(CONFIRM)
    assert.match(src, /Begin in World Builders/)
  })

  test('the completion screen no longer offers Creator Studio directly', () => {
    const src = codeOnly(CONFIRM)
    assert.ok(
      !src.includes("onOpen('creator_studio')"),
      "Your World's creator band covers Creator Studio; a third CTA on the "
      + 'emotional peak of the ritual duplicates it',
    )
  })

  test('the client routes your_world to the canonical member dashboard', () => {
    const src = codeOnly(CLIENT)
    // Carries ?creator_onboarding=complete so Your World can point at
    // the creator band, which sits below the fold.
    assert.match(src, /router\.push\('\/dashboard\?creator_onboarding=complete'\)/)
  })

  test('the default destination is Your World, not Creator Studio', () => {
    const src = codeOnly(CLIENT)
    const elseBlock = src.slice(src.lastIndexOf('} else {'))
    assert.match(
      elseBlock,
      /\/dashboard/,
      'an unspecified destination should land on Your World',
    )
  })

  test('creator_studio still switches the active space when used', () => {
    // Kept as an accepted destination for the preview harness and any
    // future caller — the switch route sets the active-space cookie.
    const src = codeOnly(CLIENT)
    assert.match(src, /creator-studio\/collective\/switch\//)
  })

  test('World Builders still routes into Pathways', () => {
    const src = codeOnly(CLIENT)
    assert.match(src, /\/spaces\/\$\{world_builders_slug\}\/pathways/)
  })
})

describe('Your World already shows what the handoff promises', () => {
  test('the new Collective appears under Collectives you created', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /Collectives you created/)
    assert.match(src, /CreatorCollectiveCard/)
    assert.match(src, /getCreatorSpaces/)
  })

  test('World Builders is not filtered out of the member memberships', () => {
    const src = codeOnly(DASHBOARD)
    // Memberships are filtered on status only. An auto_grant_role
    // filter here would hide World Builders from Your World.
    assert.ok(
      !/auto_grant_role/.test(src),
      'Your World must not exclude auto-granted Collectives',
    )
    assert.match(src, /memberships\.filter\(\(m\) => m\.status === 'active'\)/)
  })

  test('the Creator Studio prompt exists on Your World', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /CreatorStudioCard/)
    assert.match(src, /Create & Manage/)
  })

  test('the creator band is gated to creators', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(
      src,
      /user\?\.role === 'creator' \|\| user\?\.role === 'admin'/,
      'isCreatorOrAdmin must gate the band',
    )
    assert.match(src, /creatorCards\.length > 0 \|\| isCreatorOrAdmin/)
  })

  test('a plain member sees no Creator Studio prompt', () => {
    const src = codeOnly(DASHBOARD)
    // The Create & Manage section — which holds the Creator Studio card
    // — must sit inside an isCreatorOrAdmin guard.
    const studioAt = src.indexOf('CreatorStudioCard')
    const guardAt = src.lastIndexOf('isCreatorOrAdmin', studioAt)
    assert.ok(
      guardAt > -1 && studioAt - guardAt < 600,
      'CreatorStudioCard must be rendered under an isCreatorOrAdmin guard',
    )
  })
})
