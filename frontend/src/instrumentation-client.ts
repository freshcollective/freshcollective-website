/**
 * Browser error monitoring.
 *
 * Next loads this file in the client before anything else runs — it is
 * a framework convention, not a Sentry one, which is why no build
 * wrapper is involved in getting it to execute.
 *
 * Phase 3 scope: errors. No tracing, no Session Replay, no profiling —
 * see ``src/lib/sentryRuntime.ts`` for how that is enforced rather than
 * merely left unconfigured, and ``src/lib/sentryPrivacy.ts`` for what
 * is allowed to leave the browser.
 *
 * With no DSN this is a clean no-op: ``init`` is never called, so the
 * SDK installs no handlers and makes no request. That is how every
 * local ``next dev`` and every CI build behaves.
 */

import * as Sentry from '@sentry/nextjs'

import { keepOnlyErrorMonitoring, sentryDsn, SHARED_SENTRY_OPTIONS } from '@/lib/sentryRuntime'

const dsn = sentryDsn()

if (dsn) {
  Sentry.init({
    ...SHARED_SENTRY_OPTIONS,
    dsn,

    /** Which process this is, matching the backend's convention. */
    initialScope: { tags: { component: 'fc-web', runtime: 'browser' } },

    /**
     * The default set, minus anything that is not error monitoring.
     * Filtered rather than listed, so a default added by a future SDK
     * release does not quietly arrive in production.
     */
    integrations: (defaults) => keepOnlyErrorMonitoring(defaults),

    /**
     * Noise that is not ours and is not actionable. Browser extensions
     * and injected scripts throw inside our page constantly; a
     * cancelled navigation is not a failure.
     */
    ignoreErrors: [
      'ResizeObserver loop completed with undelivered notifications',
      'ResizeObserver loop limit exceeded',
      /^Non-Error promise rejection captured/,
      'AbortError',
      'The operation was aborted',
    ],
  })
}
