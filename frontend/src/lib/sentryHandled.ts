/**
 * Reporting a failure the code already handled.
 *
 * Most of what fc-web does wrong in production is not an unhandled
 * throw. It is a ``catch`` that logs to the Render console and returns
 * a fallback, so the page renders empty, the member sees nothing
 * obviously broken, and no boundary fires. There is no stack trace to
 * find later because nothing crashed.
 *
 * These are the two shapes worth reporting:
 *
 *   * the BFF proxy cannot reach fc-api at all — a timeout or a
 *     connection failure, where the member gets a 504 or 502 and the
 *     only record today is ``console.error``;
 *   * a server component's data fetch throws and the surface renders
 *     degraded. ``src/lib/serverApi.ts`` returns ``null``/``[]`` for
 *     every non-OK *response*, so a wrapper's ``catch`` only ever sees
 *     a transport-level failure — which also means fc-api never saw the
 *     request and has nothing in its own Sentry project. Nothing else
 *     knows.
 *
 * Deliberately not a general-purpose logger. Everything attached is a
 * primitive that went through ``safeContext``, so no call site can hand
 * over a response body, and nothing here can throw into the path it is
 * reporting on.
 */

import * as Sentry from '@sentry/nextjs'

import { safeContext } from './sentryPrivacy.ts'

/** How the BFF failed to reach fc-api. Not *why* the backend said no. */
export type ProxyFailureKind = 'timeout' | 'connection'

/**
 * Which kind of unreachable this was.
 *
 * The proxy aborts its own fetch at the timeout, so an ``AbortError``
 * means fc-api was too slow rather than absent — a different problem
 * with a different fix, and the distinction is the first thing anyone
 * looking at the issue wants. Everything else is a connection failure:
 * DNS, a refused socket, a dropped TLS handshake, Render's private
 * network between the two services.
 *
 * Separated from the route so the classification can be tested without
 * standing up a Next request.
 */
export function classifyProxyFailure(error: unknown): ProxyFailureKind {
  return error instanceof Error && error.name === 'AbortError'
    ? 'timeout'
    : 'connection'
}

export interface HandledOptions {
  tags?: Record<string, string>
  extra?: Record<string, unknown>
}

/**
 * Report a handled failure. Never throws, never changes the caller's
 * control flow — if Sentry is unreachable, misconfigured or absent, the
 * caller's own fallback still happens exactly as it did before.
 */
export function captureHandledFailure(
  error: unknown,
  { tags, extra }: HandledOptions = {},
): void {
  try {
    Sentry.captureException(error, {
      level: 'error',
      tags,
      extra: extra ? safeContext(extra) : undefined,
    })
  } catch {
    // Reporting a degraded page must not degrade it further.
  }
}

/**
 * What a degraded surface reports.
 *
 * Separated from the capture so the payload can be asserted on its own,
 * including by a test that drives the real SDK — the question "what
 * exactly leaves the process" should not require a Next request to
 * answer.
 *
 * ``surface`` names the page in product terms — ``creator-offers``,
 * ``dashboard`` — so the issue list reads as a list of pages that are
 * quietly broken. ``label`` is the specific fetch within it, which is
 * what makes two failures on the same page distinguishable.
 */
export function degradedSurfaceContext(
  surface: string,
  label?: string,
): HandledOptions {
  return {
    tags: { degraded_surface: surface },
    extra: label ? { fetch: label } : undefined,
  }
}

/** A server surface that rendered without its data. */
export function captureDegradedSurface(
  error: unknown,
  surface: string,
  label?: string,
): void {
  captureHandledFailure(error, degradedSurfaceContext(surface, label))
}

/**
 * The BFF could not reach fc-api.
 *
 * ``path`` is the application path (``spaces/embody/conversations``),
 * never the URL: the query string is where the claim and reset tokens
 * live, and the method plus the path is what identifies the call.
 */
export interface ProxyFailure {
  method: string
  path: string
  kind: ProxyFailureKind
  timeoutMs: number
}

/** What a proxy failure reports. Asserted directly by its own test. */
export function proxyFailureContext(
  { method, path, kind, timeoutMs }: ProxyFailure,
): HandledOptions {
  return {
    tags: { proxy_failure: kind },
    extra: { method, api_path: path, timeout_ms_budget: timeoutMs },
  }
}

export function captureProxyFailure(error: unknown, failure: ProxyFailure): void {
  captureHandledFailure(error, proxyFailureContext(failure))
}
