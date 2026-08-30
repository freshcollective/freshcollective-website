/**
 * SEC-010 Step 2 — BFF security-boundary tests for
 * ``applyBffAuthHeaders`` in ``bffAuth.ts``.
 *
 * Locks in the six invariants captured in the module docstring:
 *
 *   1. Browser-supplied ``X-Fc-Client-IP`` cannot survive to fc-api,
 *      even if pre-populated on the outbound Headers.
 *   2. Browser-supplied ``X-Fc-Bff-Auth`` cannot survive, same
 *      reason.
 *   3. Configured ``INTERNAL_BFF_SECRET`` produces exactly one
 *      outbound ``X-Fc-Bff-Auth`` matching the configured value.
 *   4. Trusted inbound ``CF-Connecting-IP`` produces exactly one
 *      outbound ``X-Fc-Client-IP`` matching that value.
 *   5. Missing secret produces neither internal identity header
 *      (local dev / production misconfiguration).
 *   6. Internal headers are not exposed through response forwarding
 *      — enforced by omission from the route's response allowlist,
 *      verified here by structural inspection of the source.
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// @ts-expect-error - Node-native import path
import { applyBffAuthHeaders } from './bffAuth.ts'


describe('applyBffAuthHeaders — browser-supplied internal headers cannot survive', () => {
  test('inbound X-Fc-Client-IP already on outbound is deleted before setting', () => {
    // Simulate a future regression where the allowlist accidentally
    // let the browser-supplied X-Fc-Client-IP through: pre-populate
    // it on the outbound Headers object.
    const outbound = new Headers()
    outbound.set('x-fc-client-ip', '6.6.6.6') // <-- attacker-controlled

    applyBffAuthHeaders(outbound, /*cf*/ null, /*secret*/ 'unused-in-this-branch')

    // No credential logic depends on the pre-populated value; but the
    // guarantee is: we start by deleting it. With no cf-connecting-ip
    // supplied, no X-Fc-Client-IP is set at all.
    assert.equal(outbound.get('x-fc-client-ip'), null,
      'browser-supplied X-Fc-Client-IP must not survive')
  })

  test('inbound X-Fc-Bff-Auth already on outbound is deleted before setting', () => {
    const outbound = new Headers()
    outbound.set('x-fc-bff-auth', 'attacker-claim') // <-- attacker-controlled

    // Without a configured secret, no X-Fc-Bff-Auth is set at all.
    applyBffAuthHeaders(outbound, /*cf*/ null, /*secret*/ undefined)

    assert.equal(outbound.get('x-fc-bff-auth'), null,
      'browser-supplied X-Fc-Bff-Auth must not survive when unconfigured')
  })

  test('browser-supplied X-Fc-Bff-Auth is overwritten (not passed through) when secret is set', () => {
    const outbound = new Headers()
    outbound.set('x-fc-bff-auth', 'attacker-claim')
    outbound.set('x-fc-client-ip', '6.6.6.6')

    applyBffAuthHeaders(outbound, /*cf*/ '1.2.3.4', /*secret*/ 'real-secret-value')

    assert.equal(outbound.get('x-fc-bff-auth'), 'real-secret-value',
      'attacker-supplied X-Fc-Bff-Auth must be overwritten with the real secret')
    assert.equal(outbound.get('x-fc-client-ip'), '1.2.3.4',
      'attacker-supplied X-Fc-Client-IP must be overwritten with the trusted CF value')
  })
})


describe('applyBffAuthHeaders — outbound header shape', () => {
  test('configured secret produces X-Fc-Bff-Auth matching env value', () => {
    const outbound = new Headers()
    applyBffAuthHeaders(outbound, '1.2.3.4', 'my-configured-secret')
    assert.equal(outbound.get('x-fc-bff-auth'), 'my-configured-secret')
  })

  test('inbound CF-Connecting-IP produces exactly one outbound X-Fc-Client-IP', () => {
    const outbound = new Headers()
    applyBffAuthHeaders(outbound, '203.0.113.42', 'my-secret')

    assert.equal(outbound.get('x-fc-client-ip'), '203.0.113.42')

    // Ensure exactly one value — Headers.getSetCookie doesn't apply
    // here; use headers iteration to count occurrences.
    let count = 0
    outbound.forEach((_v, name) => {
      if (name.toLowerCase() === 'x-fc-client-ip') count++
    })
    assert.equal(count, 1, 'exactly one X-Fc-Client-IP outbound')
  })

  test('missing secret produces NEITHER internal identity header', () => {
    const outbound = new Headers()
    applyBffAuthHeaders(outbound, '1.2.3.4', undefined)

    assert.equal(outbound.get('x-fc-bff-auth'), null,
      'no X-Fc-Bff-Auth when secret is unset (local dev)')
    assert.equal(outbound.get('x-fc-client-ip'), null,
      'no X-Fc-Client-IP without the auth header — never send a claim we cannot authenticate')
  })

  test('empty string secret is treated as unset', () => {
    const outbound = new Headers()
    applyBffAuthHeaders(outbound, '1.2.3.4', '')
    assert.equal(outbound.get('x-fc-bff-auth'), null)
    assert.equal(outbound.get('x-fc-client-ip'), null)
  })

  test('missing CF-Connecting-IP still sets the auth header alone', () => {
    const outbound = new Headers()
    applyBffAuthHeaders(outbound, null, 'my-secret')

    // The auth header is sent so fc-api knows the request is
    // BFF-mediated even in the unusual case where CF is not present.
    // fc-api's key function will fall back to the private peer.
    assert.equal(outbound.get('x-fc-bff-auth'), 'my-secret')
    assert.equal(outbound.get('x-fc-client-ip'), null)
  })

  test('other outbound headers are left alone', () => {
    const outbound = new Headers()
    outbound.set('content-type', 'application/json')
    outbound.set('cookie', 'fc_session=abc')

    applyBffAuthHeaders(outbound, '1.2.3.4', 'my-secret')

    assert.equal(outbound.get('content-type'), 'application/json')
    assert.equal(outbound.get('cookie'), 'fc_session=abc')
  })
})


describe('SEC-002 response allowlist — internal headers cannot leak via response forwarding', () => {
  test('route response allowlist does NOT include x-fc-bff-auth or x-fc-client-ip', () => {
    // Structural check: read the route handler source and confirm
    // neither header appears in RESPONSE_HEADERS_ALLOWLIST. This
    // detects a future refactor that accidentally added them.
    const here = dirname(fileURLToPath(import.meta.url))
    const routePath = join(here, '..', 'app', 'api', '[...path]', 'route.ts')
    const source = readFileSync(routePath, 'utf-8')

    const allowlistMatch = source.match(
      /RESPONSE_HEADERS_ALLOWLIST[^]*?new Set\(\[([^\]]*)\]/,
    )
    assert.ok(allowlistMatch, 'expected to find RESPONSE_HEADERS_ALLOWLIST in route.ts')
    const body = allowlistMatch[1].toLowerCase()

    assert.equal(body.includes('x-fc-bff-auth'), false,
      'x-fc-bff-auth must not be forwardable in the response')
    assert.equal(body.includes('x-fc-client-ip'), false,
      'x-fc-client-ip must not be forwardable in the response')
  })

  test('route request allowlist does NOT include either internal header', () => {
    // Same structural check for the request allowlist. Explicit
    // .delete() in bffAuth.ts is belt-and-braces; the request
    // allowlist is the primary line of defence and must not include
    // either header name.
    const here = dirname(fileURLToPath(import.meta.url))
    const routePath = join(here, '..', 'app', 'api', '[...path]', 'route.ts')
    const source = readFileSync(routePath, 'utf-8')

    const allowlistMatch = source.match(
      /REQUEST_HEADERS_ALLOWLIST[^]*?new Set\(\[([^\]]*)\]/,
    )
    assert.ok(allowlistMatch, 'expected to find REQUEST_HEADERS_ALLOWLIST in route.ts')
    const body = allowlistMatch[1].toLowerCase()

    assert.equal(body.includes('x-fc-bff-auth'), false,
      'x-fc-bff-auth must not be in the inbound allowlist')
    assert.equal(body.includes('x-fc-client-ip'), false,
      'x-fc-client-ip must not be in the inbound allowlist')
  })
})
