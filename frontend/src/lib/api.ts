/**
 * URL helpers for calling the backend.
 *
 * Browser-originated calls go through the same-origin Next.js proxy
 * (``src/app/api/[...path]/route.ts``) so the ``fc_session`` cookie
 * stays same-site under ``SameSite=Lax`` — see SEC-002.
 *
 * • ``apiUrl('/api/…')`` in the browser returns the path unchanged, so
 *   ``fetch(apiUrl(path))`` becomes a same-origin request against the
 *   Next.js proxy.
 *
 * • ``apiUrl('/api/…')`` on the server (server components, route
 *   handlers, ``serverApi.fetchWithSession``) returns an absolute URL
 *   built from ``API_INTERNAL_URL`` — server-to-server traffic that
 *   bypasses the proxy.
 *
 * • ``resolveMediaUrl`` returns absolute URLs against the backend for
 *   ``<img src>`` and other public asset references. It uses
 *   ``NEXT_PUBLIC_API_URL`` because those URLs must be resolvable in
 *   the browser. This variable is NOT used for authenticated API
 *   traffic and holds only the public host.
 */

function stripTrailingSlash(url: string): string {
  return url.replace(/\/$/, '')
}

/**
 * Resolve the server-side backend base URL.
 *
 * Accepts two shapes from ``API_INTERNAL_URL`` so the same code path
 * works in every environment (SEC-010 Step 1):
 *
 *   * ``http://…`` or ``https://…`` — used as-is. This covers local
 *     dev (``http://localhost:8000`` in ``.env``) and any future
 *     environment that wants an explicit scheme.
 *   * bare ``hostname[:port]`` — treated as an internal HTTP endpoint
 *     and ``http://`` is prepended. This is the shape Render's
 *     ``fromService.property: hostport`` returns for private
 *     service-to-service networking, where TLS is unnecessary because
 *     the traffic never leaves Render's per-account internal network.
 *
 * Trailing slashes are stripped so path concatenation is safe.
 */
export function resolveInternalApiBase(): string {
  const raw = process.env.API_INTERNAL_URL ?? 'http://localhost:8000'
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`
  return stripTrailingSlash(withScheme)
}

/**
 * Build a URL for an application API call.
 *
 * In the browser this returns the path unchanged (``/api/…``) so the
 * request goes to the same-origin Next.js proxy. On the server it
 * returns an absolute URL built from ``API_INTERNAL_URL``. Server-side
 * callers therefore reach the backend directly without hopping through
 * the proxy.
 */
export function apiUrl(path: string): string {
  if (typeof window !== 'undefined') {
    return path
  }
  return `${resolveInternalApiBase()}${path}`
}

/**
 * Absolute URL for a media / uploaded-asset reference (``<img src>``,
 * downloadable file, etc.). Uses the public backend host baked into the
 * client bundle via ``NEXT_PUBLIC_API_URL``. Never used for
 * authenticated JSON API calls.
 */
export function resolveMediaUrl(path: string | null | undefined): string | null {
  if (!path) return null
  if (path.startsWith('http')) return path
  const base = stripTrailingSlash(
    process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000',
  )
  return path.startsWith('/') ? `${base}${path}` : `${base}/${path}`
}

export interface ApiError {
  detail: string | { msg: string; type: string }[]
}

export function extractErrorMessage(err: ApiError): string {
  if (typeof err.detail === 'string') return err.detail
  if (Array.isArray(err.detail)) {
    return err.detail.map((e) => e.msg).join(', ')
  }
  return 'Something went wrong. Please try again.'
}
