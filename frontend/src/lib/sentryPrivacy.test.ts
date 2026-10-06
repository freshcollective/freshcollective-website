/**
 * What must never reach Sentry from fc-web.
 *
 * The browser SDK's defaults are wide: every navigation, every fetch
 * and every ``console.error`` argument becomes a breadcrumb on the next
 * error, and this app has URLs whose query string *is* a credential. So
 * most of this file is about absence — a member who follows a reset
 * link and then hits an unrelated render error must not hand that token
 * to a third party.
 *
 * The other half proves the useful part survives. A sanitiser that
 * replaced every URL with ``[redacted]`` would pass every leak test in
 * here and make the issue list worthless.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/sentryPrivacy.test.ts
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import {
  DROPPED_NOT_A_PRIMITIVE,
  REDACTED,
  REDACTED_EMAIL,
  SENSITIVE_QUERY_PARAMS,
  isSensitiveKey,
  redactText,
  safeContext,
  sanitiseUrl,
  scrubBreadcrumb,
  scrubEvent,
} from './sentryPrivacy.ts'

// Fake, and recognisable as fake. ``.invalid`` is reserved by RFC 2606
// and can never resolve.
const FAKE_EMAIL = 'member@example.invalid'
const FAKE_RESET = 'FAKE_RESET_TOKEN_abc123'
const FAKE_CLAIM = 'FAKE_CLAIM_TOKEN_def456'
const FAKE_INVITE = 'FAKE_INVITE_TOKEN_ghi789'
const FAKE_BEARER = 'Bearer FAKE_JWT_xyz789'
const FAKE_COOKIE = 'fc_session=FAKE_SESSION_VALUE'
const FAKE_SIG = 't=1,v1=FAKE_STRIPE_SIGNATURE'

/**
 * Every fake credential used anywhere in this file. A sanitised value
 * is checked against the whole set rather than against the one secret
 * the test happened to be about — the failure worth catching is a
 * channel nobody thought of.
 */
const ALL_FAKE_SECRETS = [
  FAKE_EMAIL, FAKE_RESET, FAKE_CLAIM, FAKE_INVITE, FAKE_BEARER, FAKE_COOKIE,
  FAKE_SIG, 'FAKE_SESSION_VALUE', 'FAKE_JWT_xyz789', 'FAKE_STRIPE_SIGNATURE',
  'hunter2',
]

function assertNoSecrets(value: unknown, label = 'value'): void {
  const blob = JSON.stringify(value)
  for (const secret of ALL_FAKE_SECRETS) {
    assert.ok(
      !blob.includes(secret),
      `${secret} survived into ${label}:\n${blob.slice(0, 1500)}`,
    )
  }
}

// ---------------------------------------------------------------------------
// The URL sanitiser — the production requirement
// ---------------------------------------------------------------------------

describe('sanitiseUrl — the three token-bearing shapes', () => {
  test('a password reset keeps its route and loses its token', () => {
    const out = sanitiseUrl(`/reset-password?token=${FAKE_RESET}`)
    assert.equal(out, `/reset-password?token=${REDACTED}`)
  })

  test('a checkout claim token is redacted', () => {
    const out = sanitiseUrl(
      `https://freshcollective.au/checkout/complete?token=${FAKE_CLAIM}`,
    )
    assert.equal(
      out,
      `https://freshcollective.au/checkout/complete?token=${REDACTED}`,
    )
  })

  test('an invite token is a path segment, not a query value', () => {
    // The shape a query-parameter rule cannot see. Redacted by position.
    assert.equal(sanitiseUrl(`/invites/${FAKE_INVITE}`), `/invites/${REDACTED}`)
  })

  test('the route after an invite token survives', () => {
    assert.equal(
      sanitiseUrl(`/invites/${FAKE_INVITE}/accept`),
      `/invites/${REDACTED}/accept`,
    )
  })

  test('an absolute invite URL is handled the same way', () => {
    assert.equal(
      sanitiseUrl(`https://freshcollective.au/invites/${FAKE_INVITE}`),
      `https://freshcollective.au/invites/${REDACTED}`,
    )
  })
})

describe('sanitiseUrl — every declared parameter', () => {
  for (const param of SENSITIVE_QUERY_PARAMS as string[]) {
    test(`${param} is redacted`, () => {
      const out = sanitiseUrl(`/anywhere?${param}=SECRET_VALUE_HERE`)
      assert.equal(out, `/anywhere?${param}=${REDACTED}`)
      assert.ok(!out.includes('SECRET_VALUE_HERE'))
    })
  }

  test('the parameter name survives so the shape is still readable', () => {
    assert.ok(sanitiseUrl('/x?token=abc').includes('token='))
  })

  test('matching is case-insensitive', () => {
    assert.equal(sanitiseUrl('/x?Token=abc'), `/x?Token=${REDACTED}`)
  })

  test('an email parameter is redacted', () => {
    assert.equal(
      sanitiseUrl(`/verify-email?email=${FAKE_EMAIL}`),
      `/verify-email?email=${REDACTED}`,
    )
  })
})

describe('sanitiseUrl — what must NOT be destroyed', () => {
  test('a harmless parameter is preserved beside a redacted one', () => {
    // The whole point of not replacing the URL wholesale.
    assert.equal(
      sanitiseUrl(`/reset-password?token=${FAKE_RESET}&tab=settings`),
      `/reset-password?token=${REDACTED}&tab=settings`,
    )
  })

  test('a URL with only harmless parameters is untouched', () => {
    const url = 'https://freshcollective.au/spaces/embody?tab=about&page=2'
    assert.equal(sanitiseUrl(url), url)
  })

  test('an ordinary path is untouched', () => {
    const url = '/spaces/embody/pathways/real-journey/step-one'
    assert.equal(sanitiseUrl(url), url)
  })

  test('the origin survives', () => {
    assert.ok(
      sanitiseUrl('https://freshcollective.au/x?token=a')
        .startsWith('https://freshcollective.au/'),
    )
  })

  test('a Stripe-shaped identifier in a path is not mistaken for a secret', () => {
    const url = '/admin/payments/ch_3AbcDEF123xyz'
    assert.equal(sanitiseUrl(url), url)
  })
})

describe('sanitiseUrl — defensive cases', () => {
  test('a fragment carrying a token is redacted', () => {
    assert.equal(
      sanitiseUrl(`/reset-password#token=${FAKE_RESET}`),
      `/reset-password#token=${REDACTED}`,
    )
  })

  test('a fragment carrying an address is redacted', () => {
    assert.equal(
      sanitiseUrl(`/x#contact=${FAKE_EMAIL}`),
      `/x#contact=${REDACTED_EMAIL}`,
    )
  })

  test('query and fragment are both handled on one URL', () => {
    const out = sanitiseUrl(
      `/checkout/complete?token=${FAKE_CLAIM}&step=2#token=${FAKE_RESET}`,
    )
    assertNoSecrets(out, 'a URL with both')
    assert.ok(out.includes('step=2'))
  })

  test('an address inside a path is redacted', () => {
    assert.equal(
      sanitiseUrl(`/unsubscribe/${FAKE_EMAIL}`),
      `/unsubscribe/${REDACTED_EMAIL}`,
    )
  })

  for (const malformed of [
    '',
    '???',
    'not a url at all',
    'http://',
    '//',
    'javascript:void(0)',
    'about:blank',
    '/x?=novalue&&&',
    '/x?token',
  ]) {
    test(`malformed input is handled: ${JSON.stringify(malformed)}`, () => {
      // The contract is "never throws, never leaks", not "returns
      // something pretty".
      const out = sanitiseUrl(malformed)
      assert.equal(typeof out, 'string')
      assertNoSecrets(out, 'malformed output')
    })
  }

  test('a non-string is redacted rather than coerced', () => {
    assert.equal(sanitiseUrl(undefined), REDACTED)
    assert.equal(sanitiseUrl(null), REDACTED)
    assert.equal(sanitiseUrl({ url: 'x' }), REDACTED)
  })
})

// ---------------------------------------------------------------------------
// Free text
// ---------------------------------------------------------------------------

describe('redactText', () => {
  test('an address in an exception message is redacted', () => {
    const out = redactText(`No account for ${FAKE_EMAIL} in this collective`)
    assert.equal(out, `No account for ${REDACTED_EMAIL} in this collective`)
  })

  test('an inline token is redacted', () => {
    assertNoSecrets(redactText(`failed with token=${FAKE_RESET}`), 'message')
  })

  test('a Bearer value is redacted', () => {
    // The one credential shape with no key name to match on.
    assert.equal(redactText(`auth header was ${FAKE_BEARER}`), `auth header was Bearer ${REDACTED}`)
  })

  for (const keep of [
    'transfer tr_1Nxyz failed for acct_1Abc',
    'ch_3Abc123XyZ was already refunded',
    'embody-circle is not a pathway',
    'version 2.71.0',
    'bearer',
  ]) {
    test(`useful text survives: ${keep}`, () => {
      assert.equal(redactText(keep), keep)
    })
  }
})

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function loadedEvent() {
  return {
    message: `reset failed for ${FAKE_EMAIL}`,
    transaction: `/reset-password?token=${FAKE_RESET}`,
    request: {
      url: `https://freshcollective.au/reset-password?token=${FAKE_RESET}&tab=x`,
      query_string: `token=${FAKE_RESET}&tab=x`,
      method: 'POST',
      data: { password: 'hunter2', token: FAKE_RESET },
      cookies: { fc_session: 'FAKE_SESSION_VALUE' },
      headers: {
        Cookie: FAKE_COOKIE,
        Authorization: FAKE_BEARER,
        'Set-Cookie': FAKE_COOKIE,
        'X-Internal-Token': 'FAKE_INTERNAL',
        'Stripe-Signature': FAKE_SIG,
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0',
      },
    },
    exception: {
      values: [
        {
          type: 'TypeError',
          value: `cannot read properties of ${FAKE_EMAIL} (token=${FAKE_RESET})`,
          stacktrace: { frames: [{ filename: 'app/reset/page.tsx', lineno: 42 }] },
        },
      ],
    },
    extra: {
      reset_url: `https://freshcollective.au/reset-password?token=${FAKE_RESET}`,
      authorization: FAKE_BEARER,
      harmless_detail: 'this one should survive',
    },
    tags: { component: 'fc-web', session: 'FAKE_SESSION_VALUE' },
    user: { id: 'usr_123', email: FAKE_EMAIL, username: 'Lindsey', ip_address: '203.0.113.9' },
    breadcrumbs: {
      values: [
        { category: 'navigation', data: { from: '/login', to: `/reset-password?token=${FAKE_RESET}` } },
        { category: 'fetch', data: { url: `/api/auth/reset?token=${FAKE_RESET}`, method: 'POST', status_code: 500 } },
        { category: 'console', level: 'error', message: `[dashboard] failed for ${FAKE_EMAIL}`, data: { arguments: [{ email: FAKE_EMAIL, body: 'secret prose' }] } },
        { category: 'ui.click', message: 'button.primary' },
      ],
    },
  }
}

describe('scrubEvent — a fully loaded event', () => {
  const scrubbed = scrubEvent(loadedEvent())!

  test('nothing fake survives anywhere in the event', () => {
    assertNoSecrets(scrubbed, 'the whole event')
  })

  test('the request body is removed entirely', () => {
    assert.equal(scrubbed.request.data, undefined)
  })

  test('cookies are removed entirely', () => {
    assert.equal(scrubbed.request.cookies, undefined)
  })

  for (const header of ['Cookie', 'Authorization', 'Set-Cookie', 'X-Internal-Token', 'Stripe-Signature']) {
    test(`${header} is redacted but still named`, () => {
      assert.equal(scrubbed.request.headers[header], REDACTED)
    })
  }

  test('a benign header is kept', () => {
    assert.equal(scrubbed.request.headers['Content-Type'], 'application/json')
    assert.equal(scrubbed.request.headers['User-Agent'], 'Mozilla/5.0')
  })

  test('the request URL keeps its route and its harmless parameter', () => {
    assert.ok(scrubbed.request.url.includes('/reset-password'))
    assert.ok(scrubbed.request.url.includes('tab=x'))
  })

  test('the user is reduced to an opaque id', () => {
    assert.deepEqual(scrubbed.user, { id: 'usr_123' })
  })

  test('the exception type and stack survive', () => {
    assert.equal(scrubbed.exception.values[0].type, 'TypeError')
    assert.equal(
      scrubbed.exception.values[0].stacktrace.frames[0].filename,
      'app/reset/page.tsx',
    )
  })

  test('a harmless extra survives', () => {
    assert.equal(scrubbed.extra.harmless_detail, 'this one should survive')
  })

  test('a useful tag survives', () => {
    assert.equal(scrubbed.tags.component, 'fc-web')
  })

  test('the breadcrumb trail is kept, not emptied', () => {
    assert.equal(scrubbed.breadcrumbs.values.length, 4)
  })
})

describe('scrubEvent — user context', () => {
  test('an event with no user is left alone', () => {
    const out = scrubEvent({ message: 'x' })!
    assert.equal('user' in out, false)
  })

  test('a user with no id is dropped rather than half-kept', () => {
    const out = scrubEvent({ user: { email: FAKE_EMAIL } })!
    assert.equal(out.user, undefined)
  })

  test('a numeric id survives', () => {
    const out = scrubEvent({ user: { id: 42, email: FAKE_EMAIL } })!
    assert.deepEqual(out.user, { id: 42 })
  })
})

describe('scrubEvent — failing closed', () => {
  test('an event that cannot be scrubbed is dropped, not sent raw', () => {
    const hostile = {
      get request(): never {
        throw new Error('deliberate')
      },
    }
    assert.equal(scrubEvent(hostile as never), null)
  })

  test('a minimal event is handled', () => {
    assert.ok(scrubEvent({ message: 'plain' }))
  })

  test('deep nesting terminates', () => {
    let nested: Record<string, unknown> = { token: FAKE_RESET }
    for (let i = 0; i < 40; i += 1) nested = { inner: nested }
    const out = scrubEvent({ extra: { nested } })!
    assertNoSecrets(out, 'deeply nested extra')
  })
})

// ---------------------------------------------------------------------------
// Breadcrumbs
// ---------------------------------------------------------------------------

describe('scrubBreadcrumb', () => {
  test('a navigation to a reset link is sanitised, not dropped', () => {
    const out = scrubBreadcrumb({
      category: 'navigation',
      data: { from: '/login', to: `/reset-password?token=${FAKE_RESET}` },
    })!
    assert.equal(out.data!.from, '/login')
    assert.equal(out.data!.to, `/reset-password?token=${REDACTED}`)
  })

  test('a fetch breadcrumb keeps its method and status', () => {
    const out = scrubBreadcrumb({
      category: 'fetch',
      data: { url: `/api/invites/${FAKE_INVITE}`, method: 'POST', status_code: 403 },
    })!
    assert.equal(out.data!.method, 'POST')
    assert.equal(out.data!.status_code, 403)
    assert.equal(out.data!.url, `/api/invites/${REDACTED}`)
  })

  test('an xhr breadcrumb is sanitised too', () => {
    const out = scrubBreadcrumb({
      category: 'xhr',
      data: { url: `/api/auth/reset?token=${FAKE_RESET}` },
    })!
    assertNoSecrets(out, 'xhr breadcrumb')
  })

  test('a navigation message that is a URL is sanitised as one', () => {
    const out = scrubBreadcrumb({
      category: 'navigation',
      message: `/checkout/complete?token=${FAKE_CLAIM}`,
    })!
    assert.equal(out.message, `/checkout/complete?token=${REDACTED}`)
  })

  test('console arguments are dropped outright', () => {
    // The unbounded channel: every console.error in the app arrives
    // here with its arguments serialised, and this codebase logs whole
    // API errors. The joined text is already in ``message``.
    const out = scrubBreadcrumb({
      category: 'console',
      level: 'error',
      message: `[library] fetch failed for ${FAKE_EMAIL}`,
      data: { arguments: [{ member: FAKE_EMAIL, body: 'what someone wrote' }], logger: 'console' },
    })!
    assert.equal(out.data!.arguments, undefined)
    assert.equal(out.data!.logger, 'console')
    assertNoSecrets(out, 'console breadcrumb')
  })

  test('a click breadcrumb is left alone', () => {
    const crumb = { category: 'ui.click', message: 'button.primary' }
    assert.deepEqual(scrubBreadcrumb({ ...crumb }), crumb)
  })

  test('an Authorization value in breadcrumb data is redacted', () => {
    const out = scrubBreadcrumb({
      category: 'fetch',
      data: { url: '/api/x', authorization: FAKE_BEARER },
    })!
    assert.equal(out.data!.authorization, REDACTED)
  })

  test('a breadcrumb that cannot be scrubbed is dropped', () => {
    const hostile = {
      category: 'console',
      get data(): never {
        throw new Error('deliberate')
      },
    }
    assert.equal(scrubBreadcrumb(hostile as never), null)
  })
})

// ---------------------------------------------------------------------------
// Hand-written context
// ---------------------------------------------------------------------------

describe('safeContext', () => {
  test('primitives survive', () => {
    assert.deepEqual(
      safeContext({ method: 'GET', api_path: 'spaces/embody', ok: false, count: 3 }),
      { method: 'GET', api_path: 'spaces/embody', ok: false, count: 3 },
    )
  })

  for (const [label, value] of [
    ['a response body', { detail: 'x', member: FAKE_EMAIL }],
    ['an array', ['a', FAKE_RESET]],
    ['an Error', new Error(FAKE_RESET)],
    ['a function', () => FAKE_RESET],
  ] as [string, unknown][]) {
    test(`${label} is dropped rather than serialised`, () => {
      const out = safeContext({ detail: value })
      assert.equal(out.detail, DROPPED_NOT_A_PRIMITIVE)
      assertNoSecrets(out, 'safeContext output')
    })
  }

  test('a sensitive key is redacted even with a primitive value', () => {
    assert.equal(safeContext({ reset_token: 'anything' }).reset_token, REDACTED)
  })

  test('a string value is still scrubbed', () => {
    assertNoSecrets(safeContext({ note: `sent to ${FAKE_EMAIL}` }), 'string value')
  })
})

describe('isSensitiveKey', () => {
  for (const key of ['Cookie', 'set-cookie', 'AUTHORIZATION', 'reset_token', 'x-internal-token', 'stripe-signature', 'jwt', 'email', 'password']) {
    test(`${key} is sensitive`, () => assert.ok(isSensitiveKey(key)))
  }
  for (const key of ['method', 'status_code', 'component', 'api_path', 'slug']) {
    test(`${key} is not`, () => assert.ok(!isSensitiveKey(key)))
  }
})
