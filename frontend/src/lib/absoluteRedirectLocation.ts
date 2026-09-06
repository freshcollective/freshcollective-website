/**
 * Route-Handler helper — build an absolute Location URL from the
 * browser-facing request headers.
 *
 * Rationale (recorded here so a future refactor can't quietly regress
 * the invariant):
 *
 * Next.js Route Handlers receive a stock ``Request`` whose ``url`` is
 * whatever the Node server saw. On Render that is
 * ``http://localhost:$PORT/…`` because Render terminates TLS at its
 * proxy and forwards to Node listening on the container's localhost.
 * ``new URL(path, request.url)`` in a Route Handler therefore yields
 * an absolute URL pointing at localhost, which is what we caught and
 * removed.
 *
 * Returning a plain relative ``Location`` header (``/some/path``) is
 * correct HTTP per RFC 7231 §7.1.2 and works in a plain browser
 * navigation, but a Next.js App Router client-side navigation from
 * ``<Link>`` performs an RSC fetch with ``redirect: 'manual'`` and
 * hands the Location string into the router. Any prefetch/cache layer
 * that resolves that relative string against a stale internal URL
 * could still misroute the browser. Absolute URLs bypass every
 * client-side resolution path.
 *
 * The trusted source for the browser-facing origin is the ``Host``
 * header (Cloudflare + Render preserve this as the client-facing
 * hostname) combined with ``x-forwarded-proto`` (Cloudflare sets this
 * to ``https`` on every terminated TLS connection). Falls back to a
 * relative Location if ``Host`` is unexpectedly missing — the browser
 * then resolves against its own origin, which is never localhost.
 */

export function buildAbsoluteRedirectLocation(
  request: Request,
  path: string,
): string {
  const host = request.headers.get('host')
  if (!host) return path
  const proto = request.headers.get('x-forwarded-proto') || 'https'
  return `${proto}://${host}${path}`
}
