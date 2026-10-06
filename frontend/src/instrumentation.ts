/**
 * Server registration hook.
 *
 * Next calls ``register()`` once per server process, before the first
 * request. Two things live here:
 *
 *   * the Node SDK's initialisation, loaded from
 *     ``sentry.server.config.ts``;
 *   * ``onRequestError``, which is how a server-component or
 *     route-handler error reaches Sentry at all. Next catches those
 *     itself and renders the error boundary, so nothing throws past
 *     the framework for a global handler to see — this hook is the
 *     only place they surface.
 *
 * No Edge entry: re-audited on 2026-10-07 and fc-web has no middleware
 * and no route declaring ``runtime = 'edge'``. The BFF proxy pins
 * itself to ``nodejs`` explicitly. Adding an Edge config would be
 * configuring a runtime that does not exist.
 */

import * as Sentry from '@sentry/nextjs'

export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('../sentry.server.config.ts')
  }
}

/**
 * Next hands every request-scoped error here. ``captureRequestError``
 * is the SDK's own handler for it: it attaches the route, the router
 * kind and the render phase, and it is the documented single
 * integration point, so no route needs wrapping and nothing gets
 * reported twice.
 *
 * The request it receives carries headers — including the session
 * cookie. Those never reach Sentry: ``dataCollection`` refuses header
 * and cookie collection, and ``scrubEvent`` redacts by name on the way
 * out as a second layer.
 */
export const onRequestError = Sentry.captureRequestError
