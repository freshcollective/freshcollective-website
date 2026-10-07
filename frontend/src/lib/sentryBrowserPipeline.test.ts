/**
 * The browser half of the pipeline, driven for real.
 *
 * Written after a production smoke test found nothing in Sentry. The
 * integration turned out to be sound and the test method faulty — but
 * the diagnosis exposed a genuine gap in this suite: everything about
 * the browser was asserted either on our own option objects or through
 * the **Node** SDK, and the two SDKs resolve different integrations.
 * The allowlist had been written against the server's set, and silently
 * excluded a browser integration that belonged in it.
 *
 * So this file loads ``@sentry/nextjs``'s real client entry — the same
 * module ``instrumentation-client.ts`` imports — in a Node process with
 * enough of a DOM for it to install, and asserts three things that
 * nothing else could:
 *
 *   1. which integrations the browser actually ends up with;
 *   2. that Sentry's global error handler is installed, since that is
 *      the path a thrown page error takes;
 *   3. that an error handed to that handler reaches the transport as
 *      one scrubbed envelope.
 *
 * The DOM here is a stub, not a browser, so this proves the wiring
 * rather than the rendering. That is the part that was wrong.
 *
 * Globals are mutated deliberately. Node's test runner gives each file
 * its own process, so nothing leaks into another suite.
 *
 * Run with:
 *
 *     node --experimental-strip-types --test src/lib/sentryBrowserPipeline.test.ts
 */

import { strict as assert } from 'node:assert'
import { createRequire } from 'node:module'
import { before, describe, test } from 'node:test'

// @ts-expect-error - Node-native import path
import {
  ERROR_MONITORING_INTEGRATIONS,
  SDK_FORCED_INTEGRATIONS,
  SHARED_SENTRY_OPTIONS,
  keepOnlyErrorMonitoring,
} from './sentryRuntime.ts'

const FRONTEND = new URL('../../', import.meta.url).pathname
const require = createRequire(FRONTEND)

/**
 * The client entry, by path.
 *
 * ``@sentry/nextjs``'s ``exports`` map resolves to the Node build under
 * Node — which is the whole problem this file exists to fix, so the
 * browser build is addressed directly. The SDK version is pinned
 * exactly, and if this path ever moves, a loudly failing test is the
 * right outcome.
 */
const CLIENT_ENTRY = `${FRONTEND}node_modules/@sentry/nextjs/build/cjs/client/index.js`

const FAKE_DSN = 'https://fakekey@o4509999999999.ingest.de.sentry.io/4509000000001'
const RELEASE = '1234567890abcdef1234567890abcdef12345678'

const FAKE_EMAIL = 'member@example.invalid'
const FAKE_TOKEN = 'FAKE_BROWSER_TOKEN'
const FAKE_BEARER = 'Bearer FAKE_BROWSER_JWT'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let Sentry: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let client: any
let offered: string[] = []
let kept: string[] = []
const sent: { type: string; payload: Record<string, unknown> }[] = []

function installDom(): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const g = globalThis as any
  g.window = globalThis
  g.self = globalThis
  g.location = new URL('https://freshcollective.au/?token=FAKE_SMOKE_TOKEN_abc')
  Object.defineProperty(globalThis, 'navigator', {
    value: { userAgent: 'test-harness', language: 'en-AU', languages: ['en-AU'] },
    configurable: true,
  })
  g.document = {
    readyState: 'complete',
    visibilityState: 'visible',
    addEventListener: () => {},
    removeEventListener: () => {},
    createElement: () => ({ setAttribute() {}, style: {} }),
    documentElement: { style: {}, dataset: {} },
    querySelector: () => null,
    head: { appendChild() {} },
  }
  g.addEventListener = () => {}
  g.removeEventListener = () => {}
}

before(() => {
  installDom()
  Sentry = require(CLIENT_ENTRY)
  client = Sentry.init({
    ...SHARED_SENTRY_OPTIONS,
    dsn: FAKE_DSN,
    environment: 'production',
    release: RELEASE,
    initialScope: { tags: { component: 'fc-web', runtime: 'browser' } },
    // Exactly what instrumentation-client.ts passes.
    integrations: (defaults: { name: string }[]) => {
      offered = defaults.map((i) => i.name)
      kept = keepOnlyErrorMonitoring(defaults).map((i) => i.name)
      return keepOnlyErrorMonitoring(defaults)
    },
    transport: () => ({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      send: async (envelope: any) => {
        for (const [header, payload] of envelope?.[1] ?? []) {
          sent.push({ type: header?.type, payload })
        }
        return {}
      },
      flush: async () => true,
    }),
  })
})

function blob(value: unknown): string {
  return JSON.stringify(value)
}

// ---------------------------------------------------------------------------
// What the browser actually ends up with
// ---------------------------------------------------------------------------

describe('the resolved browser integrations', () => {
  test('the browser is offered a different default set than the server', () => {
    // The fact the allowlist was written without. Stated so the next
    // person does not have to rediscover it.
    assert.ok(offered.includes('BrowserTracing'), 'tracing is a browser default')
    assert.ok(offered.includes('BrowserSession'), 'release health is a browser default')
    assert.ok(
      offered.includes('NextjsClientStackFrameNormalization'),
      '@sentry/nextjs adds this one only in the browser',
    )
  })

  test('the error handlers survive the filter', () => {
    // The two that matter for capturing anything at all: one installs
    // window.onerror, the other wraps setTimeout and friends.
    assert.ok(kept.includes('GlobalHandlers'))
    assert.ok(kept.includes('BrowserApiErrors'))
  })

  test('stack-frame normalisation survives the filter', () => {
    // Excluded by oversight once. It rewrites frame filenames to
    // app:///_next/… and marks framework chunks as not ours — error
    // monitoring, and what source maps will match in Phase 4.
    assert.ok(kept.includes('NextjsClientStackFrameNormalization'))
  })

  test('tracing, release health and gen-AI enrichment do not', () => {
    for (const name of ['BrowserTracing', 'BrowserSession', 'ConversationId']) {
      assert.ok(!kept.includes(name), `${name} must be filtered out`)
    }
  })

  test('the active set is exactly the allowlist, intersected with the defaults', () => {
    const active = Object.keys(client._integrations ?? {})
    assert.ok(active.length > 0, 'no integrations resolved — check the harness')
    const permitted = [
      ...(ERROR_MONITORING_INTEGRATIONS as string[]),
      ...(SDK_FORCED_INTEGRATIONS as string[]),
    ]
    const unexpected = active.filter((name) => !permitted.includes(name))
    assert.deepEqual(unexpected, [], `not error monitoring: ${unexpected.join(', ')}`)
  })

  test('nothing in the active set is a performance or replay product', () => {
    const active = Object.keys(client._integrations ?? {})
    for (const name of active) {
      assert.ok(
        !/replay|profil|metric|feedback|tracing/i.test(name),
        `${name} is active in the browser`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// The path a thrown page error actually takes
// ---------------------------------------------------------------------------

describe('the global error handler is installed', () => {
  test('Sentry owns window.onerror', () => {
    // Sentry assigns the ``onerror`` *property* — it does not add an
    // ``error`` event listener. That is why a manually dispatched
    // ErrorEvent is not a valid test of this integration, and why the
    // live probe for it is ``window.onerror.__SENTRY_INSTRUMENTED__``.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const handler = (globalThis as any).onerror
    assert.equal(typeof handler, 'function')
    assert.equal(handler.__SENTRY_INSTRUMENTED__, true)
  })

  test('setTimeout is wrapped, so a throw inside a callback is caught', () => {
    // The second capture path, and the reason a page-code setTimeout
    // throw is reported even though it is the *wrapper*, not
    // window.onerror, that catches it.
    //
    // Asserted structurally rather than by throwing inside a timer:
    // Sentry's wrapper captures and then rethrows, and under Node a
    // rethrow in a timer callback ends the process rather than
    // reaching window.onerror the way a browser would. What belongs
    // here is that the wrapper is installed; its behaviour is the
    // SDK's own.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    assert.ok((globalThis as any).setTimeout.__sentry_original__, 'setTimeout is not wrapped')
  })

  test('the DSN parsed into the EU ingest host', () => {
    const dsn = client.getDsn()
    assert.equal(dsn.host, 'o4509999999999.ingest.de.sentry.io')
    assert.equal(dsn.protocol, 'https')
    assert.equal(dsn.projectId, '4509000000001')
  })
})

// ---------------------------------------------------------------------------
// An event reaches the transport, scrubbed
// ---------------------------------------------------------------------------

describe('an error handed to window.onerror reaches the transport', () => {
  test('as exactly one scrubbed event envelope', async () => {
    sent.length = 0
    const error = new Error(
      `FC smoke test — FC-SMOKE-OK — contact ${FAKE_EMAIL} with ` +
        `token=${FAKE_TOKEN} and ${FAKE_BEARER}`,
    )
    // Exactly the five arguments a browser passes.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(globalThis as any).onerror(
      error.message,
      'https://freshcollective.au/?token=FAKE_SMOKE_TOKEN_abc',
      1,
      1,
      error,
    )
    await Sentry.flush(2000)

    assert.equal(sent.length, 1, 'no envelope reached the transport')
    assert.equal(sent[0].type, 'event')
    const event = sent[0].payload
    const text = blob(event)

    // The marker survives...
    assert.ok(text.includes('FC-SMOKE-OK'))
    assert.equal(event.environment, 'production')
    assert.equal(event.release, RELEASE)
    const tags = event.tags as Record<string, string>
    assert.equal(tags.component, 'fc-web')
    assert.equal(tags.runtime, 'browser')
    // ...and the credentials do not.
    for (const secret of [FAKE_EMAIL, FAKE_TOKEN, 'FAKE_BROWSER_JWT']) {
      assert.ok(!text.includes(secret), `${secret} survived into the envelope`)
    }
  })

  test('beforeSend keeps the event rather than dropping it', async () => {
    // The failure mode worth ruling out explicitly: a scrubber that
    // fails closed on every browser event would look exactly like an
    // integration that never initialised.
    sent.length = 0
    Sentry.captureException(new Error('plain browser error'))
    await Sentry.flush(2000)
    assert.equal(sent.length, 1)
  })
})
