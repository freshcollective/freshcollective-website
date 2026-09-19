/**
 * Two source contracts for the Email Templates surface.
 *
 * This repo has no component-rendering harness, so these read the page
 * files directly. That is a weaker kind of test and only worth doing
 * for properties whose absence is a real defect and whose presence
 * nothing else can currently assert:
 *
 * 1. The page must never offer a recipient field. A test send goes to
 *    the signed-in admin and nowhere else — the backend reads the
 *    address from the session and ignores any `to` in the body (proved
 *    in `tests/test_email_template_admin_api_phase_b.py`), but an input
 *    box that appears to accept an address would still be a lie.
 * 2. The route must check the admin role. The /admin layout guards it
 *    and every endpoint sits behind `get_admin_user`, which is the
 *    authoritative boundary; this pins that the page has not been
 *    written to assume the layout's guard.
 *
 * Everything else about this UI is tested as logic in
 * `src/lib/emailTemplates.test.ts`.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))

function sourceFiles(): string[] {
  return readdirSync(HERE)
    .filter((f) => (f.endsWith('.tsx') || f.endsWith('.ts')) && !f.endsWith('.test.ts'))
    .map((f) => join(HERE, f))
}

describe('the test-send control', () => {
  test('offers no recipient input of any kind', () => {
    for (const path of sourceFiles()) {
      const src = readFileSync(path, 'utf8')
      const inputs = src.match(/<input[^>]*>/gs) ?? []
      for (const tag of inputs) {
        assert.ok(
          !/type=["']email["']/.test(tag),
          `${path} renders an email input — a test send has one possible ` +
          'recipient and it is not typed in',
        )
      }
      assert.ok(
        !/\brecipient\b\s*[:=]/i.test(src),
        `${path} appears to carry a recipient value`,
      )
      // The request body must not name a recipient either.
      assert.ok(!/["']to["']\s*:/.test(src), `${path} sends a "to" field`)
    }
  })
})

describe('route protection', () => {
  test('the page checks the admin role before rendering anything', () => {
    const src = readFileSync(join(HERE, 'page.tsx'), 'utf8')
    assert.match(src, /requireAuthenticatedUser/)
    assert.match(src, /role\s*!==\s*['"]admin['"]/)
  })

  test('the client component is never rendered to a non-admin', () => {
    const src = readFileSync(join(HERE, 'page.tsx'), 'utf8')
    const denial = src.indexOf("role !== 'admin'")
    const render = src.indexOf('<EmailTemplatesClient')
    assert.ok(denial !== -1 && render !== -1 && denial < render,
      'the role check must precede the render')
  })
})
