/**
 * ONE-OFF: prove a Node-runtime error reaches the fc-web Sentry project.
 *
 * Run once from the fc-web Render shell after ``NEXT_PUBLIC_SENTRY_DSN``
 * is set and the service has rebuilt. It sends exactly one synthetic
 * error through the real shared options and the real scrubbers, then
 * exits.
 *
 * Why a script and not a route
 * ---------------------------
 * A ``/sentry-debug`` page would be a permanent, reachable way to make
 * production throw. This leaves nothing behind: no route, no page,
 * nothing a stranger can hit. The only way to run it is to already be
 * inside the service.
 *
 * What it proves
 * --------------
 *   1. The event reaches the fc-web project at all — DSN, network, the
 *      lot. (The browser half is verified separately, from DevTools:
 *      only the browser can prove the CSP permits the ingest origin.)
 *   2. ``environment``, ``release`` and the ``component`` / ``runtime``
 *      tags arrive correctly. Release comes from ``RENDER_GIT_COMMIT``.
 *   3. The scrubbers work on real data paths, because this deliberately
 *      carries fake credentials through every channel they cover: an
 *      exception message, ``extra``, a tag, a breadcrumb, a request URL
 *      with a token, request headers, and a user record.
 *
 * Every "secret" below is a literal in this file — a fake address at
 * ``.invalid`` (a reserved TLD that can never resolve) and obvious
 * ``FAKE_…`` strings. Nothing is read from the environment except the
 * DSN it needs and the two non-secret values it reports, so this cannot
 * print or transmit anything real.
 *
 * Usage, from the fc-web Render shell::
 *
 *     node --experimental-strip-types scripts/sentry-smoke-test.ts
 *
 * Exit codes::
 *
 *     0  one event was submitted and flushed
 *     1  no DSN in this shell, or the flush timed out
 *
 * Not referenced by the app, absent from render.yaml, and not part of
 * the build.
 */

import * as sentryNamespace from '@sentry/nextjs'

import {
  SHARED_SENTRY_OPTIONS,
  keepOnlyErrorMonitoring,
  sentryDsn,
  sentryEnvironment,
  sentryRelease,
} from '../src/lib/sentryRuntime.ts'

// The SDK ships CJS; under Node's own ESM loader its members land on
// ``default``. Next's bundler handles this interop itself, which is why
// the app's files use a plain namespace import and this script cannot.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Sentry: any = (sentryNamespace as any).default ?? sentryNamespace

const FAKE_EMAIL = 'test@example.invalid'
const FAKE_TOKEN = 'FAKE_SERVER_SMOKE_TOKEN'
const FAKE_BEARER = 'Bearer FAKE_SERVER_SMOKE_JWT'
const FAKE_COOKIE = 'fc_session=FAKE_SERVER_SMOKE_SESSION'

const MARKER = 'fc-web server smoke test — synthetic, safe to delete'

class FcWebSmokeTestError extends Error {
  constructor(message: string) {
    super(message)
    // The name is the point: unmistakable in the issue list, and
    // unmistakably not a real failure.
    this.name = 'FcWebSmokeTestError'
  }
}

async function main(): Promise<number> {
  const dsn = sentryDsn()
  if (!dsn) {
    console.error(
      'NEXT_PUBLIC_SENTRY_DSN is not set in this shell, so nothing was sent.\n' +
        'Set it on fc-web, let the service rebuild, then run this again.',
    )
    return 1
  }

  Sentry.init({
    ...SHARED_SENTRY_OPTIONS,
    dsn,
    initialScope: { tags: { component: 'fc-web', runtime: 'nodejs' } },
    integrations: (defaults: { name: string }[]) => keepOnlyErrorMonitoring(defaults),
  })

  console.log(`environment : ${sentryEnvironment()}`)
  console.log(`release     : ${sentryRelease() ?? '(unset)'}`)
  console.log('component   : fc-web')
  console.log('runtime     : nodejs')
  console.log('')

  Sentry.addBreadcrumb({
    category: 'navigation',
    data: { from: '/login', to: `/reset-password?token=${FAKE_TOKEN}` },
  })
  Sentry.addBreadcrumb({
    category: 'console',
    level: 'error',
    message: `[smoke-test] failed for ${FAKE_EMAIL}`,
    data: { arguments: [{ email: FAKE_EMAIL, body: 'prose a member wrote' }] },
  })

  let eventId: string | undefined
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Sentry.withScope((scope: any) => {
    scope.setUser({ id: 'smoke-test-user', email: FAKE_EMAIL, ip_address: '203.0.113.9' })
    scope.setTag('smoke_test_token', FAKE_TOKEN)
    scope.setExtra('authorization', FAKE_BEARER)
    scope.setExtra('reset_url', `https://freshcollective.au/reset-password?token=${FAKE_TOKEN}`)
    scope.setExtra('harmless_detail', 'this one should survive')
    // The server-only surface: a request, with the header that
    // authenticates a member and the URL they were on.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    scope.addEventProcessor((event: any) => {
      event.request = {
        method: 'POST',
        url: `https://freshcollective.au/reset-password?token=${FAKE_TOKEN}&tab=keepme`,
        headers: { Cookie: FAKE_COOKIE, Authorization: FAKE_BEARER },
        cookies: { fc_session: 'FAKE_SERVER_SMOKE_SESSION' },
        data: { password: 'FAKE_SERVER_SMOKE_PASSWORD' },
      }
      return event
    })
    eventId = Sentry.captureException(
      new FcWebSmokeTestError(
        `${MARKER}. Contact ${FAKE_EMAIL} with token=${FAKE_TOKEN} (${FAKE_BEARER}) — ` +
          'none of those may appear in Sentry.',
      ),
    )
  })

  const flushed = await Sentry.flush(10_000)
  console.log(`event id    : ${eventId}`)
  console.log('')
  if (!eventId) {
    console.error('The SDK did not accept the event. Check the DSN.')
    return 1
  }
  if (flushed === false) {
    console.error(
      'Submitted, but the flush timed out — the event may still arrive. ' +
        'Check Sentry before re-running.',
    )
    return 1
  }

  console.log('Sent. In the fc-web Sentry project, confirm the newest issue:')
  console.log('  * is titled FcWebSmokeTestError')
  console.log(`  * carries environment=${sentryEnvironment()} and release=${(sentryRelease() ?? '(unset)').slice(0, 12)}`)
  console.log('  * has tags component=fc-web and runtime=nodejs')
  console.log("  * contains 'this one should survive' in its extra data")
  console.log('  * shows the URL as /reset-password?token=[redacted]&tab=keepme')
  console.log('  * shows a user id but no email and no IP address')
  console.log('  * has NO request body and NO Cookie or Authorization value')
  console.log(`  * contains NO occurrence of ${FAKE_EMAIL}, ${FAKE_TOKEN},`)
  console.log(`    ${FAKE_BEARER}, or FAKE_SERVER_SMOKE_SESSION`)
  console.log('')
  console.log('Then delete the issue.')
  return 0
}

process.exitCode = await main()
