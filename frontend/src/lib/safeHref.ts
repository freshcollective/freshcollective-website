/**
 * SEC-016 — client-side navigation URL guard.
 *
 * Defence in depth for content-block sinks whose ``embed_url`` reaches
 * a clickable ``<a href>``. The authoritative validation runs on the
 * backend (``app.services.content_url``) at write time; this guard
 * protects against legacy rows that predate that validator and against
 * any future path that forgets to validate at the API boundary.
 *
 * Policy mirrors the backend ``validate_nav_url`` — accept:
 *   * ``https://``, ``http://``
 *   * ``mailto:`` (with any address body — link renderers may render
 *     the raw text alongside)
 *   * ``/``-relative internal paths (single leading slash only —
 *     ``//host`` is protocol-relative and rejected)
 *
 * Reject everything else (``javascript:``, ``data:``, ``vbscript:``,
 * ``blob:``, ``file:``, ``ftp:``, ``tel:``, ``//host``) and the common
 * case/whitespace variants.
 *
 * Returns ``null`` for unsafe input so callers can render a text-only
 * fallback instead of a live anchor.
 */

export function safeHref(raw: string | null | undefined): string | null {
  if (raw == null) return null
  const s = String(raw).trim()
  if (!s) return null

  // Internal path. Single leading slash only — protocol-relative
  // ``//evil.com/path`` would resolve cross-origin in the browser.
  if (s.startsWith('/')) {
    if (s.startsWith('//')) return null
    return s
  }

  const lower = s.toLowerCase()
  if (lower.startsWith('mailto:')) return s
  if (lower.startsWith('https://') || lower.startsWith('http://')) return s

  return null
}
