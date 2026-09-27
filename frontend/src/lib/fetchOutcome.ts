/**
 * How a server page should read a completed — or failed — request.
 *
 * Several pages collapsed every unhappy path into the happy one:
 *
 *     if (!res.ok) return []
 *     catch { return [] }
 *
 * which reads a 500 as "you have no messages" and a dropped connection as
 * "this thread does not exist". The messages routes returned 500 for every
 * member for three weeks and the UI showed a tidy empty inbox the whole
 * time. Nobody could have reported it as a bug, because it did not look
 * like one.
 *
 * Three outcomes, because three different things happened and each wants
 * different UI:
 *
 *   ``ok``       the server answered. An empty list is *data* — render the
 *                empty state, which is a true statement about the account.
 *   ``missing``  the server answered 403 or 404. The thing is not there, or
 *                not yours; to you those are the same, which is why the
 *                backend answers 404 for both. ``notFound()``.
 *   ``failure``  nothing usable came back — 5xx, an unexpected status, or a
 *                request that never completed. Throw, and let
 *                ``app/error.tsx`` say so.
 *
 * The decision is a pure function, and the outcome is assembled by one too,
 * so every branch is unit-testable without mocking ``next/headers`` — the
 * same reason ``resolveAuthAction`` is split out of
 * ``requireAuthenticatedUser``.
 *
 * Not messages-specific. Any server page with the same three states can
 * use it.
 */

export type FetchOutcomeKind = 'ok' | 'missing' | 'failure'

export type FetchOutcome<T> =
  | { kind: 'ok'; data: T }
  | { kind: 'missing' }
  | { kind: 'failure'; message: string; status: number | null }

/** Default copy when a failure carries nothing readable. */
export const GENERIC_FAILURE =
  'Something went wrong loading this page. Please try again.'

/**
 * Which outcome a status code represents.
 *
 * ``null`` means the request never completed — a thrown ``fetch``, so no
 * status exists. That is a failure, never an empty result.
 *
 * 401 is a failure rather than its own outcome on purpose: every protected
 * page runs ``requireAuthenticatedUser`` first, so a 401 here means the
 * session died between two calls in one request. Rare, and genuinely
 * wrong — not something to render as ordinary UI.
 */
export function classifyStatus(status: number | null): FetchOutcomeKind {
  if (status === null) return 'failure'
  if (status >= 200 && status < 300) return 'ok'
  if (status === 403 || status === 404) return 'missing'
  return 'failure'
}

export interface OutcomeInput<T> {
  /** ``null`` when the request never completed. */
  status: number | null
  /** Parsed body, when the request succeeded. */
  data?: T
  /** Message extracted from an error body, when there was one. */
  message?: string | null
}

/** Assemble the outcome. Pure, so the page's behaviour is testable. */
export function buildOutcome<T>({
  status,
  data,
  message,
}: OutcomeInput<T>): FetchOutcome<T> {
  const kind = classifyStatus(status)
  if (kind === 'missing') return { kind: 'missing' }
  if (kind === 'failure') {
    return {
      kind: 'failure',
      message: (message ?? '').trim() || GENERIC_FAILURE,
      status,
    }
  }
  // A 2xx whose body could not be parsed is a failure, not an empty
  // result — the one case where "ok" would still be a lie.
  if (data === undefined) {
    return {
      kind: 'failure',
      message: (message ?? '').trim() || GENERIC_FAILURE,
      status,
    }
  }
  return { kind: 'ok', data }
}

/**
 * Turn a failure outcome into the thrown error ``app/error.tsx`` renders.
 *
 * A helper rather than an inline ``throw`` so every page words it the same
 * way and the status reaches the server log.
 */
export function failureError(
  outcome: Extract<FetchOutcome<unknown>, { kind: 'failure' }>,
  context: string,
): Error {
  const status = outcome.status === null ? 'no response' : `HTTP ${outcome.status}`
  return new Error(`${context} failed (${status}): ${outcome.message}`)
}
