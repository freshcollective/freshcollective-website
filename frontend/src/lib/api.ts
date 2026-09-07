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
 * • ``resolveMediaUrl`` returns the URL to use for ``<img src>`` and
 *   other browser-visible asset references. Private uploads under
 *   ``/api/uploads/*`` are rendered SAME-ORIGIN against the Next.js
 *   BFF proxy: the auth-gated fc-api route requires the ``fc_session``
 *   cookie, and that cookie lives on the fc-web origin under
 *   ``SameSite=Lax`` — it does not accompany cross-site subresource
 *   requests to a different registrable domain (e.g. Render's
 *   ``*.onrender.com`` split, where ``onrender.com`` is on the Public
 *   Suffix List and each subdomain is treated as a distinct site).
 *   The BFF proxy already forwards the cookie server-side and passes
 *   through the fc-api ``302`` to the short-lived R2 presigned URL,
 *   so the image bytes never stream through Node — only the redirect
 *   header does. Public ``/api/uploads/platform-artwork/*`` continues
 *   to work through the same path (fc-api serves those without an
 *   auth gate). External ``http(s)://…`` URLs are returned verbatim.
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
 * Same-origin URL for a browser-visible asset (``<img src>``,
 * ``<audio src>``, download links, etc.).
 *
 * Behaviour:
 *   * ``null`` / ``undefined`` / ``''``            → ``null``
 *   * ``http(s)://…``                              → returned verbatim
 *     (external — YouTube/Vimeo/Loom embeds, admin-pasted URLs, etc.)
 *   * ``/api/uploads/…`` or any other absolute path → returned verbatim
 *     (already a same-origin relative URL — browser hits fc-web,
 *     the BFF proxy forwards to fc-api with the ``fc_session`` cookie,
 *     fc-api replies with a 302 to R2's short-lived presigned URL,
 *     the browser follows the redirect directly to R2)
 *   * bare storage key (e.g. ``media/embody/{uuid}_x.png``) →
 *     ``/api/uploads/{key}`` (same-origin relative)
 *
 * Never used for authenticated JSON API calls — that's ``apiUrl``.
 */
export function resolveMediaUrl(path: string | null | undefined): string | null {
  if (!path) return null
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  if (path.startsWith('/')) return path
  return `/api/uploads/${path}`
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
