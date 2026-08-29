/**
 * TEMPORARY (SEC-010 diagnostic) — REMOVE AFTER USE
 *
 * fc-web inbound observation of trusted-proxy header shapes reaching
 * this Node runtime from Cloudflare. Paired with the fc-api-side
 * ``/api/admin/_diagnostic/proxy-headers`` endpoint; the two will be
 * removed together in one follow-up ``diagnostic: remove …`` commit.
 *
 * Route file lives at ``src/app/api/diagnostic/proxy-headers`` so
 * Next.js resolves it BEFORE the SEC-002 catch-all at
 * ``src/app/api/[...path]/route.ts``. (A ``_diagnostic`` segment
 * would have made Next.js treat this as a private folder — excluded
 * from routing — so the plain word is used.) This handler runs
 * entirely on fc-web and does NOT proxy anything to fc-api — it
 * observes what Cloudflare (fronting fc-web) hands us, nothing more.
 *
 * Auth model — mirrors ``src/lib/requireAuthenticatedUser.ts``:
 *
 *   1. Require an ``fc_session`` cookie (401 otherwise).
 *   2. Call ``${API_INTERNAL_URL}/api/auth/me`` server-to-server with
 *      the cookie forwarded, so the backend is the sole authority on
 *      the session's validity and role.
 *   3. Require ``role === 'admin'`` (401 otherwise).
 *
 * Response body is a fixed ``{"ok": true}`` — the endpoint never
 * echoes any observed header value to the HTTP caller. Server-side
 * ``console.warn`` captures ONLY the small non-sensitive transport
 * set: X-Forwarded-For, CF-Connecting-IP, X-Real-IP, Forwarded, Via,
 * CF-Ray, and Host. Cookies, auth headers, bodies, PII, query
 * strings, and arbitrary headers are deliberately not logged.
 */

import { NextRequest } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const SESSION_COOKIE = 'fc_session'
const BACKEND_URL = process.env.API_INTERNAL_URL

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function _requireAdmin(request: NextRequest): Promise<boolean> {
  const cookie = request.headers.get('cookie') ?? ''
  const hasSession = cookie.split(';').some((c) => c.trim().startsWith(`${SESSION_COOKIE}=`))
  if (!hasSession) return false
  if (!BACKEND_URL) return false

  try {
    const res = await fetch(`${BACKEND_URL.replace(/\/$/, '')}/api/auth/me`, {
      headers: { cookie },
      cache: 'no-store',
    })
    if (!res.ok) return false
    const me = (await res.json().catch(() => null)) as { role?: string } | null
    return me?.role === 'admin'
  } catch {
    return false
  }
}

export async function GET(request: NextRequest): Promise<Response> {
  const ok = await _requireAdmin(request)
  if (!ok) return jsonResponse(401, { detail: 'Not authenticated.' })

  // Deliberately narrow, non-sensitive header set.
  console.warn(
    'SEC-010-DIAG-FCWEB path=%s host=%s xff=%s cf_connecting_ip=%s x_real_ip=%s forwarded=%s via=%s cf_ray=%s',
    '/api/diagnostic/proxy-headers',
    JSON.stringify(request.headers.get('host')),
    JSON.stringify(request.headers.get('x-forwarded-for')),
    JSON.stringify(request.headers.get('cf-connecting-ip')),
    JSON.stringify(request.headers.get('x-real-ip')),
    JSON.stringify(request.headers.get('forwarded')),
    JSON.stringify(request.headers.get('via')),
    JSON.stringify(request.headers.get('cf-ray')),
  )
  return jsonResponse(200, { ok: true })
}
