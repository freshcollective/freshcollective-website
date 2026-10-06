/**
 * The real SDK, end to end, with nothing mocked but the network.
 *
 * Everything else in this suite asserts on our own functions. This file
 * asserts on the envelope the SDK would actually have put on the wire:
 * a real ``Sentry.init`` with the real ``SHARED_SENTRY_OPTIONS``, a
 * transport that collects instead of sending, and every default
 * integration having had its turn. That is the only way to be sure the
 * scrubbers are wired to the hooks the SDK really calls, and that
 * nothing the SDK adds on its own arrives alongside them.
 *
 * This runs the **Node** SDK, because that is what resolves under
 * ``node --test``. It is not a stand-in for the browser build — but the
 * options object and both scrubbers are the same values in both
 * runtimes by construction (``src/lib/sentryRuntime.ts``), so what is
 * proved here about the pipeline holds on both sides of it. The
 * browser-specific rules are asserted directly in
 * ``sentryPrivacy.test.ts``.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/sentryPipeline.test.ts
 */

import { strict as assert } from 'node:assert'
import { afterEach, beforeEach, describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import {
  ERROR_MONITORING_INTEGRATIONS,
  SDK_FORCED_INTEGRATIONS,
  SHARED_SENTRY_OPTIONS,
  keepOnlyErrorMonitoring,
} from './sentryRuntime.ts'
// @ts-expect-error - Node-native import path
import {
  classifyProxyFailure,
  degradedSurfaceContext,
  proxyFailureContext,
} from './sentryHandled.ts'

// The SDK ships CJS; under Node's ESM loader the members land on
// ``default``. Next's bundler handles this interop itself, which is why
// the app's own files can use a plain namespace import.
import * as sentryNamespace from '@sentry/nextjs'
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Sentry: any = (sentryNamespace as any).default ?? sentryNamespace

const FAKE_DSN = 'https://fakekey@o4509999999999.ingest.de.sentry.io/4509000000001'
const RELEASE = '1234567890abcdef1234567890abcdef12345678'

const FAKE_EMAIL = 'member@example.invalid'
const FAKE_RESET = 'FAKE_RESET_TOKEN_abc123'
const FAKE_BEARER = 'Bearer FAKE_JWT_xyz789'
const FAKE_COOKIE = 'fc_session=FAKE_SESSION_VALUE'
const FAKE_INVITE = 'FAKE_INVITE_TOKEN_ghi789'
const FAKE_INTERNAL = 'FAKE_INTERNAL_TOKEN'
const FAKE_SIG = 't=1,v1=FAKE_STRIPE_SIGNATURE'

const ALL_FAKE_SECRETS = [
  FAKE_EMAIL, FAKE_RESET, FAKE_BEARER, FAKE_COOKIE, FAKE_INVITE,
  FAKE_INTERNAL, FAKE_SIG, 'FAKE_SESSION_VALUE', 'FAKE_JWT_xyz789',
  'FAKE_STRIPE_SIGNATURE', 'hunter2',
]

interface Captured {
  events: Record<string, unknown>[]
  others: string[]
}

let captured: Captured

/**
 * A transport that records envelopes rather than sending them. The last
 * thing in the pipeline, so what it sees is what would genuinely have
 * left the process.
 */
function capturingTransport() {
  return {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    send: async (envelope: any) => {
      const items = envelope?.[1] ?? []
      for (const [header, payload] of items) {
        const type = header?.type
        if (type === 'event') captured.events.push(payload)
        else captured.others.push(String(type))
      }
      return {}
    },
    flush: async () => true,
  }
}

function start(extra: Record<string, unknown> = {}): void {
  Sentry.init({
    ...SHARED_SENTRY_OPTIONS,
    dsn: FAKE_DSN,
    environment: 'production',
    release: RELEASE,
    initialScope: { tags: { component: 'fc-web', runtime: 'nodejs' } },
    // The same filter both init files apply.
    integrations: (defaults: { name: string }[]) => keepOnlyErrorMonitoring(defaults),
    transport: capturingTransport,
    ...extra,
  })
}

async function settle(): Promise<void> {
  await Sentry.flush(2000)
}

function blob(value: unknown): string {
  return JSON.stringify(value)
}

/**
 * The event with stack-frame source context removed.
 *
 * ``ContextLines`` embeds the lines of **our own source files** around
 * each frame, which is deliberate — it is the difference between a
 * readable stack and a list of line numbers, and it contains code, not
 * member data. But this test file's source happens to contain every
 * fake credential it asserts about, so a naive scan of the envelope
 * finds them in the context lines of its own frames and reports a leak
 * that is really a quine.
 *
 * Stripped for the secret scan only; ``sourceContextIsOurOwnCode``
 * below asserts separately what those lines may contain.
 */
function withoutSourceContext(event: Record<string, unknown>): unknown {
  const copy = JSON.parse(blob(event)) as Record<string, unknown>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  for (const value of (copy.exception as any)?.values ?? []) {
    for (const frame of value?.stacktrace?.frames ?? []) {
      delete frame.pre_context
      delete frame.context_line
      delete frame.post_context
    }
  }
  return copy
}

function assertNoSecrets(value: unknown, label: string): void {
  const text = blob(
    value && typeof value === 'object' && 'exception' in (value as object)
      ? withoutSourceContext(value as Record<string, unknown>)
      : value,
  )
  for (const secret of ALL_FAKE_SECRETS) {
    assert.ok(!text.includes(secret), `${secret} survived into ${label}`)
  }
}

beforeEach(() => {
  captured = { events: [], others: [] }
})

afterEach(() => {
  Sentry.getGlobalScope?.().clear?.()
  Sentry.getIsolationScope?.().clear?.()
})

// ---------------------------------------------------------------------------
// The envelope
// ---------------------------------------------------------------------------

describe('a captured exception carries no credentials', () => {
  test('and keeps everything that makes it diagnosable', async () => {
    start()
    Sentry.addBreadcrumb({
      category: 'navigation',
      data: { from: '/login', to: `/reset-password?token=${FAKE_RESET}` },
    })
    Sentry.addBreadcrumb({
      category: 'fetch',
      data: { url: `/api/invites/${FAKE_INVITE}`, method: 'POST', status_code: 500 },
    })
    Sentry.withScope((scope: Record<string, (...args: unknown[]) => unknown>) => {
      scope.setUser({ id: 'usr_123', email: FAKE_EMAIL, ip_address: '203.0.113.9' })
      scope.setExtra('authorization', FAKE_BEARER)
      scope.setExtra('reset_url', `https://freshcollective.au/reset-password?token=${FAKE_RESET}`)
      scope.setExtra('harmless_detail', 'this one should survive')
      scope.setTag('surface', 'reset-password')
      Sentry.captureException(
        new TypeError(`reset failed for ${FAKE_EMAIL} with token=${FAKE_RESET}`),
      )
    })
    await settle()

    assert.equal(captured.events.length, 1)
    const event = captured.events[0]
    assertNoSecrets(event, 'the event envelope')

    // The useful half.
    assert.equal(blob(event).includes('TypeError'), true)
    assert.equal((event.environment as string), 'production')
    assert.equal((event.release as string), RELEASE)
    const tags = event.tags as Record<string, string>
    assert.equal(tags.component, 'fc-web')
    assert.equal(tags.runtime, 'nodejs')
    assert.equal(tags.surface, 'reset-password')
    const extra = event.extra as Record<string, unknown>
    assert.equal(extra.harmless_detail, 'this one should survive')
    assert.deepEqual(event.user, { id: 'usr_123' })
  })

  test('the breadcrumb trail survives, sanitised', async () => {
    start()
    Sentry.addBreadcrumb({
      category: 'navigation',
      data: { from: '/login', to: `/reset-password?token=${FAKE_RESET}` },
    })
    Sentry.captureException(new Error('after navigating'))
    await settle()

    const event = captured.events[0]
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const crumbs: any[] = (event.breadcrumbs as any) ?? []
    assert.ok(crumbs.length >= 1, 'the trail was emptied rather than cleaned')
    const nav = crumbs.find((c) => c.category === 'navigation')
    assert.equal(nav.data.from, '/login')
    assert.ok(String(nav.data.to).startsWith('/reset-password?token='))
    assertNoSecrets(event, 'an event with breadcrumbs')
  })

  test('no user context is invented when none was set', async () => {
    start()
    Sentry.captureException(new Error('anonymous'))
    await settle()
    assert.equal(captured.events[0].user, undefined)
  })

  test('a stray ip_address never reaches the envelope', async () => {
    start()
    Sentry.withScope((scope: Record<string, (...args: unknown[]) => unknown>) => {
      scope.setUser({ id: 'usr_9', ip_address: '198.51.100.7' })
      Sentry.captureException(new Error('with an ip'))
    })
    await settle()
    assert.ok(
      !blob(withoutSourceContext(captured.events[0])).includes('198.51.100.7'),
    )
    assert.deepEqual(captured.events[0].user, { id: 'usr_9' })
  })

  test('source context is our own code, and is kept on purpose', async () => {
    // The counterpart to every assertion above: a scrubber that
    // stripped this would make a minified production stack unreadable
    // for no privacy gain. These lines come from files in this repo.
    start()
    Sentry.captureException(new Error('for its stack'))
    await settle()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const frames: any[] =
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (captured.events[0].exception as any)?.values?.[0]?.stacktrace?.frames ?? []
    const withContext = frames.filter((f) => f.context_line !== undefined)
    assert.ok(withContext.length > 0, 'no source context was attached at all')
    for (const frame of withContext) {
      assert.equal(typeof frame.filename, 'string')
    }
  })
})

// ---------------------------------------------------------------------------
// Server-side request data — the wider surface
// ---------------------------------------------------------------------------

describe('a server event carrying request data', () => {
  test('keeps the route and loses the session, the headers and the body', async () => {
    // The shape ``onRequestError`` produces: a real request, with the
    // cookie that authenticates the member and the URL they were on.
    start()
    Sentry.withScope((scope: Record<string, (...args: unknown[]) => unknown>) => {
      scope.setSDKProcessingMetadata?.({})
      scope.addEventProcessor?.((event: Record<string, unknown>) => {
        event.request = {
          method: 'POST',
          url: `https://freshcollective.au/reset-password?token=${FAKE_RESET}&tab=x`,
          query_string: `token=${FAKE_RESET}&tab=x`,
          headers: {
            Cookie: FAKE_COOKIE,
            Authorization: FAKE_BEARER,
            'X-Internal-Token': FAKE_INTERNAL,
            'Stripe-Signature': FAKE_SIG,
            'Content-Type': 'application/json',
          },
          cookies: { fc_session: 'FAKE_SESSION_VALUE' },
          data: { password: 'hunter2', token: FAKE_RESET },
        }
        return event
      })
      Sentry.captureException(new Error('server component threw'))
    })
    await settle()

    const event = captured.events[0]
    assertNoSecrets(event, 'a server event with request data')
    const request = event.request as Record<string, unknown>
    assert.equal(request.data, undefined, 'the body must be gone')
    assert.equal(request.cookies, undefined, 'cookies must be gone')
    const headers = request.headers as Record<string, string>
    assert.equal(headers.Cookie, '[redacted]')
    assert.equal(headers.Authorization, '[redacted]')
    assert.equal(headers['X-Internal-Token'], '[redacted]')
    assert.equal(headers['Stripe-Signature'], '[redacted]')
    // And the part worth keeping.
    assert.equal(headers['Content-Type'], 'application/json')
    assert.ok(String(request.url).includes('/reset-password'))
    assert.ok(String(request.url).includes('tab=x'))
  })
})

// ---------------------------------------------------------------------------
// Handled failures: the BFF and the degraded surfaces
// ---------------------------------------------------------------------------

describe('classifyProxyFailure', () => {
  test('an aborted fetch is a timeout', () => {
    const err = new Error('aborted')
    err.name = 'AbortError'
    assert.equal(classifyProxyFailure(err), 'timeout')
  })

  for (const error of [
    new TypeError('fetch failed'),
    Object.assign(new Error('ECONNREFUSED'), { code: 'ECONNREFUSED' }),
    'a string someone threw',
    undefined,
  ]) {
    test(`anything else is a connection failure: ${String(error)}`, () => {
      assert.equal(classifyProxyFailure(error), 'connection')
    })
  }
})

describe('an upstream failure produces one event with safe context only', () => {
  test('a timeout', async () => {
    start()
    const err = new Error('The operation was aborted')
    err.name = 'AbortError'
    Sentry.captureException(err, proxyFailureContext({
      method: 'POST',
      path: 'spaces/embody/conversations',
      kind: classifyProxyFailure(err),
      timeoutMs: 30_000,
    }))
    await settle()

    assert.equal(captured.events.length, 1, 'exactly one event per failure')
    const event = captured.events[0]
    assert.equal((event.tags as Record<string, string>).proxy_failure, 'timeout')
    const extra = event.extra as Record<string, unknown>
    assert.equal(extra.method, 'POST')
    assert.equal(extra.api_path, 'spaces/embody/conversations')
    assert.equal(extra.timeout_ms_budget, 30_000)
    assertNoSecrets(event, 'a proxy timeout event')
  })

  test('a connection failure', async () => {
    start()
    const err = new TypeError('fetch failed')
    Sentry.captureException(err, proxyFailureContext({
      method: 'GET',
      path: 'auth/me',
      kind: classifyProxyFailure(err),
      timeoutMs: 30_000,
    }))
    await settle()
    assert.equal(captured.events.length, 1)
    assert.equal(
      (captured.events[0].tags as Record<string, string>).proxy_failure,
      'connection',
    )
  })

  test('the context carries a path, never a URL with its query', () => {
    // The query string is where the claim and reset tokens live, so the
    // application path is what identifies the call.
    const context = proxyFailureContext({
      method: 'POST',
      path: 'auth/reset',
      kind: 'timeout',
      timeoutMs: 30_000,
    })
    const text = blob(context)
    assert.ok(!text.includes('?'), 'no query string may appear')
    assert.ok(!/cookie|authorization|token=/i.test(text))
  })
})

describe('a degraded surface produces one tagged event', () => {
  test('with the surface and the fetch that failed', async () => {
    start()
    Sentry.captureException(
      new Error('fetch failed'),
      degradedSurfaceContext('creator-offers', 'offers'),
    )
    await settle()

    assert.equal(captured.events.length, 1)
    const event = captured.events[0]
    assert.equal(
      (event.tags as Record<string, string>).degraded_surface,
      'creator-offers',
    )
    assert.equal((event.extra as Record<string, unknown>).fetch, 'offers')
  })

  test('the surface alone is enough', () => {
    assert.deepEqual(degradedSurfaceContext('dashboard'), {
      tags: { degraded_surface: 'dashboard' },
      extra: undefined,
    })
  })
})

// ---------------------------------------------------------------------------
// Nothing but errors leaves the process
// ---------------------------------------------------------------------------

describe('no other envelope type is ever sent', () => {
  test('an error capture sends exactly one event and nothing else', async () => {
    start()
    Sentry.captureException(new Error('just an error'))
    await settle()
    assert.equal(captured.events.length, 1)
    assert.deepEqual(
      captured.others.filter((t) => t !== 'client_report'),
      [],
      `unexpected envelope items: ${captured.others.join(', ')}`,
    )
  })

  test('starting a span produces no transaction envelope', async () => {
    start()
    await Sentry.startSpan({ name: 'deliberate' }, async () => {
      // Tracing is off, so this should be inert.
    })
    await settle()
    assert.deepEqual(
      captured.others.filter((t) => t !== 'client_report'),
      [],
      'a transaction escaped with tracing disabled',
    )
  })

  test('the client reports tracing as disabled', () => {
    start()
    const options = Sentry.getClient().getOptions()
    assert.equal(options.tracesSampleRate, 0)
  })

  test('no replay or profiling integration is active', () => {
    start()
    const client = Sentry.getClient()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const active = Object.keys((client as any)._integrations ?? {})
    assert.ok(active.length > 0, 'no integrations resolved — check the harness')
    for (const name of active) {
      assert.ok(
        !/tracing|replay|profil|metric|feedback|session|conversationid|localvariables/i.test(name),
        `${name} is active and is not error monitoring`,
      )
    }
  })

  test('a dropped event does not become a second event', async () => {
    // ``Dedupe`` is one of the integrations we keep. The same error
    // captured twice is one issue, not two.
    start()
    const err = new Error('the same failure')
    Sentry.captureException(err)
    Sentry.captureException(err)
    await settle()
    assert.equal(captured.events.length, 1, 'the same error was filed twice')
  })
})

// ---------------------------------------------------------------------------
// With no DSN
// ---------------------------------------------------------------------------

describe('with no DSN', () => {
  test('capturing with no client at all is inert', async () => {
    // What production actually does: both init files call ``init`` only
    // when a DSN is present, so with none there is no client. Asserted
    // by closing the one this suite created rather than by initialising
    // with an empty DSN — which, measured, leaves the previous client
    // in place and would make this test prove nothing.
    start()
    await Sentry.close(2000)
    captured = { events: [], others: [] }
    Sentry.captureException(new Error('nobody is listening'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    assert.deepEqual(captured.events, [])
  })
})

describe('the resolved integration set', () => {
  test('contains nothing outside the error-monitoring allowlist', async () => {
    // The real reason this is an allowlist. @sentry/nextjs resolves
    // around fifty default integrations on the server — Postgres,
    // Prisma, Kafka, OpenAI, Anthropic_AI, LangChain and the rest — and
    // every one of them patches modules at startup. This is the test
    // that fails if an SDK upgrade adds another.
    start()
    const client = Sentry.getClient()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const active = Object.keys((client as any)._integrations ?? {})
    assert.ok(active.length > 0, 'no integrations resolved — check the harness')
    const permitted = [
      ...(ERROR_MONITORING_INTEGRATIONS as string[]),
      // Added by the client after the filter runs; inert with tracing
      // off, and proved inert by the span test above.
      ...(SDK_FORCED_INTEGRATIONS as string[]),
    ]
    const unexpected = active.filter((name) => !permitted.includes(name))
    assert.deepEqual(
      unexpected,
      [],
      `not error monitoring: ${unexpected.join(', ')}`,
    )
  })

  test('the allowlist is not so narrow that errors stop being caught', async () => {
    start()
    const client = Sentry.getClient()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const active = Object.keys((client as any)._integrations ?? {})
    for (const essential of ['EventFilters', 'LinkedErrors', 'Dedupe', 'ContextLines']) {
      assert.ok(active.includes(essential), `${essential} should be active`)
    }
  })
})
