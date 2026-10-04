/**
 * Structural tests for the "Include me in Ways to Connect" control.
 *
 * Same pattern as ``src/app/creator-studio/settings/DangerZone.test.ts``:
 * read the source and assert the load-bearing invariants without
 * spinning up React DOM. Comments are stripped first, so prose about
 * an invariant can never stand in for the invariant itself.
 *
 * The invariants that must not silently regress:
 *
 *   1. The toggle's initial state comes from the persisted profile
 *      value, not from a hardcoded default. A form that always opened
 *      "on" would silently re-enable a member who had switched off.
 *
 *   2. The value is sent on the same PATCH as the rest of the form,
 *      so saving goes through the mechanism already in place rather
 *      than a second request with its own failure modes.
 *
 *   3. The control is a real switch — announced and operable
 *      assistively. It now gets that by *being* the shared
 *      ``platform/Switch`` rather than by hand-rolling
 *      ``role="switch"`` here, so the assertion follows it: this file
 *      checks the control is wired to the state, and
 *      ``switch.test.ts`` checks the switch is a switch.
 *
 *   4. The copy states both directions. A member reading only "show
 *      you people" would not learn that they are shown to others.
 *
 *   5. No Recognition data is fetched or rendered here. Work Item 2
 *      ships the control, not the surface.
 *
 * Run with:
 *
 *   node --experimental-strip-types --test \
 *     src/components/settings/ProfileForm.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const _here = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(_here, 'ProfileForm.tsx'), 'utf-8')
// Strip block comments and JSX comment expressions so documentation
// never satisfies an assertion about behaviour.
const CODE = SOURCE
  .replace(/\{\s*\/\*[^]*?\*\/\s*\}/g, '')
  .replace(/\/\*[^]*?\*\//g, '')

describe('Ways to Connect participation toggle', () => {
  test('initialises from the persisted profile value', () => {
    assert.match(
      CODE,
      /useState\(\s*profile\.ways_to_connect_enabled\s*\)/,
      'the toggle must open showing what is stored, not a default',
    )
  })

  test('never hardcodes an initial value', () => {
    assert.ok(
      !/setWaysToConnect\]?\s*=\s*useState\((?:true|false)\)/.test(CODE),
      'a literal initial value would ignore the member’s saved choice',
    )
  })

  test('is sent on the existing profile PATCH', () => {
    assert.match(
      CODE,
      /ways_to_connect_enabled:\s*waysToConnect/,
      'the value must ride the form’s own save request',
    )
    const body = CODE.slice(CODE.indexOf('JSON.stringify({'))
    assert.ok(
      body.indexOf('ways_to_connect_enabled') <
        body.indexOf('})'),
      'it belongs inside the PATCH body, not a separate request',
    )
  })

  test('there is exactly one save request in the form submit', () => {
    const submit = CODE.slice(
      CODE.indexOf('async function handleSubmit'),
      CODE.indexOf('const previewName'),
    )
    const patches = submit.match(/method:\s*'PATCH'/g) ?? []
    assert.equal(patches.length, 1, 'one Save, one request')
  })

  test('renders the shared switch, bound to its state', () => {
    // Not a local copy of one. The copy this replaced drifted from the
    // canonical geometry and sat its thumb off-centre.
    assert.match(CODE, /<Switch\s+checked=\{waysToConnect\}/)
    assert.match(CODE, /from '@\/components\/platform'/)
  })

  test('no hand-rolled switch markup remains', () => {
    for (const smell of ['role="switch"', 'translate-x-0.5', 'aria-checked=']) {
      assert.ok(
        !CODE.includes(smell),
        `the shared component owns this now: ${smell}`,
      )
    }
  })

  test('the switch carries an accessible name', () => {
    assert.match(CODE, /aria-label="Include me in Ways to Connect"/)
  })

  test('toggling flips the state rather than setting a constant', () => {
    assert.match(CODE, /setWaysToConnect\(!waysToConnect\)/)
  })
})

describe('the member-facing copy', () => {
  test('uses the agreed label', () => {
    assert.match(CODE, /Include me in Ways to Connect/)
  })

  test('states both directions of the setting', () => {
    assert.match(CODE, /show you people/i, 'what the member sees')
    assert.match(CODE, /show\s+you to them/i, 'what others see')
  })

  test('avoids recommendation and networking language', () => {
    for (const banned of [
      'fellow traveller',
      'fellow travellers',
      'people you may know',
      'matches',
      'recommend',
      'suggested people',
      'connections you might',
    ]) {
      assert.ok(
        !CODE.toLowerCase().includes(banned),
        `member-facing copy must not use "${banned}"`,
      )
    }
  })
})

describe('scope', () => {
  test('renders no Recognition data', () => {
    for (const leaked of [
      'recognition',
      '/api/recognition',
      'shared_gathering',
      'sharedPathway',
    ]) {
      assert.ok(
        !CODE.toLowerCase().includes(leaked.toLowerCase()),
        `the settings form must not surface Recognition yet ("${leaked}")`,
      )
    }
  })
})
