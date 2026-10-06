'use client'

/**
 * Reporting from React error boundaries, exactly once.
 *
 * Next's error boundaries are the only place a client-side render
 * failure becomes visible: React catches the throw, the boundary
 * renders, and nothing propagates to a global handler. Before this,
 * production errors reached ``error.tsx``, drew the "Something went
 * wrong" page, and left no trace at all — the dev-only
 * ``console.error`` in that file was the whole reporting story.
 *
 * Two things make this less trivial than ``captureException(error)``.
 *
 * **Server errors must not be filed twice.** When a server component
 * throws, Next reports it through ``onRequestError`` — with the real
 * stack, the real route and the real module — and *then* sends the
 * client a stripped error so the boundary can render. Capturing that
 * again from the browser produces a second issue for one failure, and
 * the second one is the useless one: no stack, a generic message. The
 * distinguishing mark is ``digest``, which Next sets only on an error
 * that crossed the server boundary.
 *
 * **Boundaries re-render.** An effect keyed on ``error`` runs again
 * after any state change that remounts the boundary, and React's
 * StrictMode invokes effects twice in development. A WeakSet of
 * already-reported errors makes "once" a property of the error object
 * rather than of how carefully the caller wrote its dependencies.
 */

import * as Sentry from '@sentry/nextjs'

/**
 * Errors already reported. Weak, so this cannot hold a render tree
 * alive — entries disappear with the error they key on.
 */
const reported = new WeakSet<object>()

export interface BoundaryError {
  digest?: string
  message?: string
}

/**
 * Whether this boundary should report this error.
 *
 * Exported for its own sake: the two reasons to say no are the whole
 * substance of this module, and ``sentryBoundary.test.ts`` asserts both
 * without needing a browser or an SDK.
 */
export function shouldReportBoundaryError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  // Reported by ``onRequestError`` already, with better information.
  if (typeof (error as BoundaryError).digest === 'string') return false
  if (reported.has(error)) return false
  reported.add(error)
  return true
}

/**
 * Report a boundary error, or deliberately say nothing.
 *
 * ``boundary`` is the name of the boundary that caught it — ``'route'``
 * or ``'global'`` — so the issue says how bad the failure was: a
 * segment that failed to render, or the root layout itself.
 *
 * Nothing about the member or the props goes with it. The error and
 * where it was caught is the whole payload; ``scrubEvent`` then runs
 * over it like any other event.
 */
export function captureBoundaryError(
  error: unknown,
  boundary: 'route' | 'global',
): void {
  if (!shouldReportBoundaryError(error)) return
  Sentry.captureException(error, {
    tags: { error_boundary: boundary },
    level: boundary === 'global' ? 'fatal' : 'error',
  })
}
