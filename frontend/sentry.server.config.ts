/**
 * Node-runtime error monitoring for fc-web.
 *
 * This is the server half: server components, layouts, route handlers
 * and the BFF proxy all run here, and what they can see is wider than
 * what the browser can — a request's cookies include the session, and a
 * rendering function's locals include whatever it fetched. So the
 * privacy configuration is not weaker here, it is the same object,
 * applied to the runtime that needs it more.
 *
 * Imported by ``src/instrumentation.ts``'s ``register()``, which Next
 * calls once per server process before any request is handled.
 *
 * Kept at the project root rather than under ``src/`` because that is
 * where Sentry's own tooling looks for it, so adopting
 * ``withSentryConfig`` in Phase 4 for source maps needs no file move.
 */

import * as Sentry from '@sentry/nextjs'

import { keepOnlyErrorMonitoring, sentryDsn, SHARED_SENTRY_OPTIONS } from './src/lib/sentryRuntime.ts'

const dsn = sentryDsn()

if (dsn) {
  Sentry.init({
    ...SHARED_SENTRY_OPTIONS,
    dsn,

    initialScope: { tags: { component: 'fc-web', runtime: 'nodejs' } },

    integrations: (defaults) => keepOnlyErrorMonitoring(defaults),

    /**
     * Next throws these two by design and they are not errors:
     * ``redirect()`` and ``notFound()`` are implemented as exceptions
     * that the framework catches. Without this, every 404 and every
     * post-login redirect would be an issue.
     */
    ignoreErrors: ['NEXT_REDIRECT', 'NEXT_NOT_FOUND', 'NEXT_HTTP_ERROR_FALLBACK'],
  })
}
