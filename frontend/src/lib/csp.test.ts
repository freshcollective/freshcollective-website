/**
 * SEC-011 Stage A — CSP + security-header pins.
 *
 * These tests protect the CSP against silent drift. They exercise
 * the exact strings ``next.config.ts`` would emit, so a mistaken
 * relaxation (e.g. someone adds ``'unsafe-eval'``, ``data:`` in
 * script-src, a ``localhost`` origin, or drops a required embed
 * host) fails the build.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/csp.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import { CSP_REPORT_ONLY, SECURITY_HEADERS } from './securityHeaders.ts'
// @ts-expect-error - Node-native import path
import { EMBED_PROVIDERS } from './embedAllowlist.ts'


function parseCsp(csp: string): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const part of csp.split(';').map((s) => s.trim()).filter(Boolean)) {
    const [name, ...values] = part.split(/\s+/)
    out[name!] = values
  }
  return out
}


// ---------------------------------------------------------------------------
// 1. Enforcement posture — Stage C must ship enforcing CSP, not Report-Only
// ---------------------------------------------------------------------------

describe('SEC-011 Stage C — CSP is enforcing', () => {
  test('the reported header key is Content-Security-Policy', () => {
    const keys = SECURITY_HEADERS.map((h: { key: string }) => h.key)
    assert.ok(
      keys.includes('Content-Security-Policy'),
      'expected Content-Security-Policy in the shipped header set',
    )
  })

  test('Report-Only CSP header is no longer shipped', () => {
    const keys = SECURITY_HEADERS.map((h: { key: string }) => h.key.toLowerCase())
    assert.ok(
      !keys.includes('content-security-policy-report-only'),
      'Stage C enforces — Report-Only must not ship alongside the enforcing header',
    )
  })
})


// ---------------------------------------------------------------------------
// 2. Global transport headers
// ---------------------------------------------------------------------------

describe('SEC-011 Stage A — transport/content headers', () => {
  function get(name: string): string | undefined {
    const h = SECURITY_HEADERS.find(
      (row: { key: string }) => row.key.toLowerCase() === name.toLowerCase(),
    )
    return h?.value
  }

  test('HSTS is exactly max-age=31536000 (no includeSubDomains/preload)', () => {
    const v = get('Strict-Transport-Security')
    assert.equal(v, 'max-age=31536000')
    assert.ok(!v!.toLowerCase().includes('includesubdomains'))
    assert.ok(!v!.toLowerCase().includes('preload'))
  })

  test('X-Content-Type-Options: nosniff is set', () => {
    assert.equal(get('X-Content-Type-Options'), 'nosniff')
  })

  test('Referrer-Policy: strict-origin-when-cross-origin is set', () => {
    assert.equal(get('Referrer-Policy'), 'strict-origin-when-cross-origin')
  })

  test('X-Frame-Options: DENY is set', () => {
    assert.equal(get('X-Frame-Options'), 'DENY')
  })

  test('Permissions-Policy is present', () => {
    const v = get('Permissions-Policy')
    assert.ok(v)
    assert.ok(v!.includes('camera=()'))
    assert.ok(v!.includes('microphone=()'))
    assert.ok(v!.includes('geolocation=()'))
  })
})


// ---------------------------------------------------------------------------
// 3. CSP directive shape
// ---------------------------------------------------------------------------

describe('SEC-011 Stage A — CSP directive shape', () => {
  const parsed = parseCsp(CSP_REPORT_ONLY)

  test('default-src is self only', () => {
    assert.deepEqual(parsed['default-src'], ["'self'"])
  })

  test('script-src is self + unsafe-inline; no unsafe-eval; no data:', () => {
    const values = parsed['script-src']
    assert.ok(values.includes("'self'"))
    assert.ok(values.includes("'unsafe-inline'"))
    assert.ok(!values.includes("'unsafe-eval'"),
      "Stage A must not permit 'unsafe-eval' in script-src")
    assert.ok(!values.some((v) => v.startsWith('data:')),
      'Stage A must not permit data: URIs in script-src')
  })

  test('style-src allows self + unsafe-inline (Next hydration + inline React styles)', () => {
    const values = parsed['style-src']
    assert.ok(values.includes("'self'"))
    assert.ok(values.includes("'unsafe-inline'"))
  })

  test('img-src includes self and the configured media origin', () => {
    const values = parsed['img-src']
    assert.ok(values.includes("'self'"))
    // Media host is the NEXT_PUBLIC_API_URL — in dev this is
    // http://localhost:8000, in production it's fc-api's public URL.
    const mediaOrigin = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '')
    assert.ok(values.includes(mediaOrigin))
    assert.ok(values.includes('data:'))
    assert.ok(values.includes('blob:'))
  })

  test('font-src is self only', () => {
    assert.deepEqual(parsed['font-src'], ["'self'"])
  })

  test('connect-src is self only (SEC-002 same-origin BFF)', () => {
    assert.deepEqual(parsed['connect-src'], ["'self'"])
  })

  test('form-action allows self and Stripe Checkout', () => {
    const values = parsed['form-action']
    assert.ok(values.includes("'self'"))
    assert.ok(values.includes('https://checkout.stripe.com'))
  })

  test("frame-ancestors is 'none'", () => {
    assert.deepEqual(parsed['frame-ancestors'], ["'none'"])
  })

  test("base-uri is 'self'", () => {
    assert.deepEqual(parsed['base-uri'], ["'self'"])
  })

  test("object-src is 'none'", () => {
    assert.deepEqual(parsed['object-src'], ["'none'"])
  })
})


// ---------------------------------------------------------------------------
// 4. frame-src is pinned against the repo's embed allowlist
// ---------------------------------------------------------------------------

describe('SEC-011 Stage A — frame-src ↔ EMBED_PROVIDERS drift check', () => {
  const parsed = parseCsp(CSP_REPORT_ONLY)
  const frameSrc = new Set(parsed['frame-src'])

  test('every embed provider host is present in frame-src', () => {
    for (const provider of EMBED_PROVIDERS) {
      for (const host of provider.hosts) {
        const origin = `https://${host}`
        assert.ok(
          frameSrc.has(origin),
          `EMBED_PROVIDERS lists ${provider.name} host ${host!}, ` +
            `but CSP frame-src does not include ${origin} — allowlists have drifted.`,
        )
      }
    }
  })

  test('frame-src includes Stripe Checkout (future-proofing for payments flag)', () => {
    assert.ok(frameSrc.has('https://checkout.stripe.com'))
  })

  test('frame-src has no unexpected extra origins', () => {
    const expected = new Set<string>([
      ...EMBED_PROVIDERS.flatMap((p) =>
        p.hosts.map((h) => `https://${h}`),
      ),
      'https://checkout.stripe.com',
    ])
    for (const origin of frameSrc) {
      assert.ok(
        expected.has(origin),
        `CSP frame-src contains ${origin} which is neither in ` +
          'EMBED_PROVIDERS nor the Stripe Checkout allowlist. ' +
          'Add to the allowlist or remove from CSP.',
      )
    }
  })
})


// ---------------------------------------------------------------------------
// 5. No dev/local origins ever
// ---------------------------------------------------------------------------

describe('SEC-011 Stage A — no dev origins in CSP', () => {
  test('no CSP directive contains localhost/127.0.0.1/.local in production', () => {
    // In dev tests we may see localhost via NEXT_PUBLIC_API_URL; guard
    // only that CSP doesn't contain them when running in production.
    if (process.env.NODE_ENV !== 'production') {
      return
    }
    for (const [name, values] of Object.entries(parseCsp(CSP_REPORT_ONLY))) {
      for (const v of values) {
        assert.ok(
          !/localhost|127\.0\.0\.1|\.local(?![a-z])/.test(v),
          `CSP directive ${name} contains dev origin ${v!} in production build`,
        )
      }
    }
  })
})
