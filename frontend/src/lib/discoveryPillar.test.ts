/**
 * The Discover Places doorway, and the three ways it can go missing.
 *
 * It vanished from live Your World with nothing in the code to blame:
 * both Render discovery flags had been reset to false, and the card is —
 * correctly — gated on the frontend one. The composition was intact the
 * whole time, which is exactly why nothing caught it.
 *
 * ``featureFlags.test.ts`` already covers how a flag string is parsed.
 * What was missing is anything tying the flag to the doorway. These are
 * contract tests over source and blueprint rather than rendering tests:
 * the dashboard is a server component, so the Node runner cannot render
 * it, and the thing worth protecting is the wiring, not the markup.
 *
 * What they cannot do — and this is the honest limit — is assert what
 * Render's Dashboard currently holds. They protect the code and the
 * blueprint; a Dashboard-only edit that contradicts the blueprint is
 * invisible here, and is precisely what the blueprint sync reverted.
 *
 *   node --experimental-strip-types --test src/lib/discoveryPillar.test.ts
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const DASHBOARD = read('../app/dashboard/page.tsx')
const DESTINATION = read('../app/discover-places/page.tsx')
const BLUEPRINT = read('../../../render.yaml')

const DISCOVERY_FLAG = 'NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED'


/** The value of a ``- key: NAME`` / ``value: "x"`` pair in render.yaml. */
function blueprintValue(key: string): string | null {
  const re = new RegExp(`-\\s*key:\\s*${key}\\s*\\n\\s*value:\\s*"([^"]*)"`)
  return BLUEPRINT.match(re)?.[1] ?? null
}


describe('the dashboard composition keeps both doorways', () => {
  test('Discover Places is rendered from Your World', () => {
    // The regression this file exists for would be a refactor quietly
    // dropping the card while the flag stayed on.
    assert.match(DASHBOARD, /<DiscoverPlacesCard/)
  })

  test('it is gated on the discovery flag, not on something else', () => {
    assert.match(DASHBOARD, /discoveryOn\s*&&\s*\(\s*\n?\s*<DiscoverPlacesCard/)
  })

  test('discoveryOn comes from the canonical flag helper', () => {
    assert.match(DASHBOARD, /const\s+discoveryOn\s*=\s*isDiscoveryPillarEnabled\(\)/)
  })

  test('Explore Collectives stays unconditional', () => {
    // It must not acquire a gate: with Discovery off it is the only
    // doorway left, and the section is built to show it alone.
    const card = DASHBOARD.match(/.{0,80}<ExploreCollectivesCard/s)?.[0] ?? ''
    assert.match(DASHBOARD, /<ExploreCollectivesCard/)
    assert.doesNotMatch(card, /&&\s*\(?\s*$/)
  })

  test('both doorways sit in the same section, so neither is buried', () => {
    const explore = DASHBOARD.indexOf('<ExploreCollectivesCard')
    const discover = DASHBOARD.indexOf('<DiscoverPlacesCard')
    const sectionEnd = DASHBOARD.indexOf('</Section>', explore)
    assert.ok(explore > 0 && discover > 0)
    assert.ok(
      discover < sectionEnd,
      'Discover Places left the "Elsewhere in the world" section',
    )
  })

  test('Ways to Connect remains separately gated', () => {
    assert.match(DASHBOARD, /waysToConnectOn\s*&&\s*\(\s*\n?\s*<WaysToConnectCard/)
  })
})


describe('the destination is gated on the same flag as the card', () => {
  test('/discover-places consults the discovery flag', () => {
    assert.match(DESTINATION, /isDiscoveryPillarEnabled\(\)/)
  })

  test('and refuses when it is off, so the card never leads nowhere', () => {
    assert.match(DESTINATION, /if\s*\(!isDiscoveryPillarEnabled\(\)\)\s*notFound\(\)/)
  })
})


describe('the Blueprint keeps frontend and backend discovery in step', () => {
  // render.yaml line 152 warns: turn the backend on FIRST, or the page
  // renders and every /api/places call 503s. This asserts the two can
  // never be declared out of step, in either direction.

  test('both discovery flags are declared', () => {
    assert.notEqual(blueprintValue(DISCOVERY_FLAG), null)
    assert.notEqual(blueprintValue('DISCOVERY_PILLAR_ENABLED'), null)
  })

  test('they hold the same value', () => {
    assert.equal(
      blueprintValue(DISCOVERY_FLAG),
      blueprintValue('DISCOVERY_PILLAR_ENABLED'),
      'fc-web and fc-api discovery flags disagree — the 503 trap',
    )
  })

  test('discovery is currently declared on', () => {
    // Recorded deliberately: the surface is live, and the value lives in
    // the blueprint so a sync cannot silently turn it off again.
    assert.equal(blueprintValue('DISCOVERY_PILLAR_ENABLED'), 'true')
  })

  test('Ways to Connect stays declared off, on both services', () => {
    assert.equal(blueprintValue('NEXT_PUBLIC_WAYS_TO_CONNECT_ENABLED'), 'false')
    assert.equal(blueprintValue('WAYS_TO_CONNECT_ENABLED'), 'false')
  })

  test('the two pillars are independent — Discovery on does not imply WTC on', () => {
    assert.notEqual(
      blueprintValue('DISCOVERY_PILLAR_ENABLED'),
      blueprintValue('WAYS_TO_CONNECT_ENABLED'),
    )
  })

  test('discovery is blueprint-managed, not left to the Dashboard', () => {
    // A ``sync: false`` entry is Dashboard-owned and survives a sync; a
    // ``value:`` entry is reasserted by it. Discovery must be the latter,
    // or the reset that caused this incident can recur.
    const re = /-\s*key:\s*DISCOVERY_PILLAR_ENABLED\s*\n\s*(value:|sync:)/
    assert.match(BLUEPRINT.match(re)?.[1] ?? '', /value:/)
  })
})
