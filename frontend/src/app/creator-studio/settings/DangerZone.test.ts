/**
 * Structural tests for the draft-Collective Danger Zone.
 *
 * Same pattern as ``src/lib/bffAuth.test.ts`` and the
 * collective-switch route tests: read the source and assert the
 * load-bearing invariants without spinning up React DOM.
 *
 * The specific invariants that must not silently regress:
 *
 *   1. The component early-returns (renders nothing) for any status
 *      other than 'draft'. Archive lifecycle for active/archived
 *      Collectives is deliberately out of scope; a future edit that
 *      loosened the gate would present a destructive action outside
 *      the eligibility envelope.
 *
 *   2. The destructive button is disabled until the typed name
 *      exactly matches the Collective name. Case-sensitive equality
 *      (``typed === name``) is the confirmation UX contract.
 *
 *   3. On success, the active-collective cookie is cleared if (and
 *      ONLY if) the deleted slug is the active one — otherwise the
 *      sidebar would keep rendering chrome for a Collective that no
 *      longer exists.
 *
 *   4. On success, navigation goes to ``/creator-studio`` (the index
 *      page with the switcher).
 *
 *   5. HTTP call is a DELETE to ``/api/creator/spaces/{slug}``.
 *
 * Run with:
 *
 *   node --experimental-strip-types --test \
 *     src/app/creator-studio/settings/DangerZone.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'


const _here = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(_here, 'DangerZone.tsx'), 'utf-8')
const CODE = SOURCE.replace(/\/\*[^]*?\*\//g, '')
  .split('\n')
  .map((line) => line.replace(/\/\/.*$/, ''))
  .join('\n')


describe('DangerZone — draft-only rendering gate', () => {
  test("early-returns null when status !== 'draft'", () => {
    // The check must appear near the top of the component, before
    // any hook call. Match the exact guard expression.
    assert.match(
      CODE,
      /if\s*\(\s*status\s*!==\s*['"]draft['"]\s*\)\s*return\s+null/,
      "expected an early return `if (status !== 'draft') return null` " +
        'so the destructive action never renders outside draft.',
    )
  })
})


describe('DangerZone — type-to-confirm', () => {
  test('canConfirm requires typed === name (exact equality)', () => {
    // ``typed === name`` — case-sensitive strict-equal. NOT
    // ``.toLowerCase()`` or ``.trim()`` — the confirmation UX
    // contract is exact match so accidental confirmations are hard.
    assert.match(
      CODE,
      /canConfirm\s*=\s*typed\s*===\s*name/,
      'canConfirm must be exact string equality (typed === name)',
    )
  })

  test('destructive button is disabled by canConfirm', () => {
    // The button's ``disabled`` binding must be ``!canConfirm`` so
    // click is impossible until the name matches AND the request
    // is not already in flight.
    assert.match(
      CODE,
      /disabled=\{!canConfirm\}/,
      "destructive button's disabled must be bound to !canConfirm",
    )
  })
})


describe('DangerZone — success flow', () => {
  test('DELETE targets /api/creator/spaces/{slug} (URL-encoded)', () => {
    assert.match(
      CODE,
      /fetch\(\s*`\/api\/creator\/spaces\/\$\{encodeURIComponent\(slug\)\}`\s*,\s*\{[^}]*method:\s*['"]DELETE['"]/,
      'expected DELETE fetch to /api/creator/spaces/${encodeURIComponent(slug)}',
    )
  })

  test('active-space cookie is cleared ONLY when it names the deleted slug', () => {
    // The clear branch is gated on ``active === slug``. A
    // non-matching active cookie must be left alone (deleting some
    // other draft while a different active-collective is current
    // should not surprise-clear the sidebar).
    assert.match(
      CODE,
      /if\s*\(\s*active\s*===\s*slug\s*\)/,
      'expected `if (active === slug)` gate around cookie clear',
    )
    assert.match(
      CODE,
      /max-age=0/,
      'cookie clear should set max-age=0',
    )
  })

  test('active-space cookie identifier matches ACTIVE_SPACE_COOKIE', () => {
    // Import from the shared constant, not a hardcoded string, so a
    // rename in ``activeSpaceCookie.ts`` propagates.
    assert.match(
      CODE,
      /import\s+\{\s*ACTIVE_SPACE_COOKIE\s*\}\s+from\s+['"]@\/lib\/activeSpaceCookie['"]/,
      'expected ACTIVE_SPACE_COOKIE import from @/lib/activeSpaceCookie',
    )
    // And the cookie read/write must use the constant.
    assert.match(
      CODE,
      /\$\{ACTIVE_SPACE_COOKIE\}=;\s*path=\/;\s*max-age=0/,
      'cookie clear must use the ACTIVE_SPACE_COOKIE constant, not a hardcoded name',
    )
  })

  test('successful delete navigates to /creator-studio', () => {
    assert.match(
      CODE,
      /router\.push\(\s*['"]\/creator-studio['"]\s*\)/,
      "expected router.push('/creator-studio') on success",
    )
  })
})
