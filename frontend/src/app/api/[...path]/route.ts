/**
 * Same-origin BFF proxy for browser-originated FastAPI calls (SEC-002).
 *
 * Browsers on ``fc-web`` never talk to ``fc-api`` directly. Instead the
 * client fetches ``/api/…`` on its own origin; this handler forwards the
 * request server-side to ``API_INTERNAL_URL/api/…`` and streams the
 * response back. The ``fc_session`` cookie therefore lives on the
 * ``fc-web`` origin and stays same-site (``SameSite=Lax``) — which is
 * what makes the whole authentication model work on Render.
 *
 * Non-goals (deliberately excluded):
 *
 * • Webhooks (Stripe, Resend) MUST hit ``fc-api`` directly so signature
 *   verification runs against the raw upstream body. This proxy refuses
 *   to forward ``/api/webhooks/*`` so a misconfiguration is loud rather
 *   than silently corrupting a signed payload.
 *
 * • Internal cron endpoints (``/api/internal/*``) are called by
 *   trusted schedulers with ``X-Internal-Token``. They are not part of
 *   the browser surface and are refused here for the same reason.
 *
 * • Media / uploaded assets under ``/api/uploads/*`` currently render as
 *   direct ``<img src>`` against ``fc-api``; those requests remain
 *   direct so we don't stream every image through a Node dyno.
 *
 * Least-privilege: the backend URL is read only from ``API_INTERNAL_URL``
 * (never a client-controlled header) and is never exposed as
 * ``NEXT_PUBLIC_*``. Header forwarding uses explicit allowlists.
 */

import { NextRequest } from 'next/server'

import { resolveInternalApiBase } from '@/lib/api'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const REQUEST_TIMEOUT_MS = 30_000

// Path segments (after ``/api/``) that this proxy refuses to forward.
// Matching is a prefix on the joined path — ``webhooks`` catches
// ``/api/webhooks/stripe``, ``internal`` catches ``/api/internal/comms/…``.
const DENIED_PATH_PREFIXES: readonly string[] = ['webhooks', 'internal']

// Inbound headers we forward from browser → backend. Cookie is handled
// explicitly below (case-insensitive), so it's not in this set.
// Content-Length is intentionally omitted — undici recalculates it (or
// chooses chunked encoding) when the request is re-issued.
const REQUEST_HEADERS_ALLOWLIST: ReadonlySet<string> = new Set([
  'content-type',
  'accept',
  'accept-language',
  'user-agent',
])

// Outbound headers we copy from backend → browser. Set-Cookie is handled
// separately (see getSetCookie() below) because it can appear multiple
// times and needs per-value forwarding.
const RESPONSE_HEADERS_ALLOWLIST: ReadonlySet<string> = new Set([
  'content-type',
  'cache-control',
  'location',
  'etag',
  'last-modified',
  'vary',
])

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params
  const joined = path.join('/')

  const firstSegment = path[0] ?? ''
  if (DENIED_PATH_PREFIXES.includes(firstSegment)) {
    // Refuse loudly so a misrouted Stripe / cron request never has its
    // body reserialised by this proxy.
    return jsonResponse(404, { detail: 'Not found.' })
  }

  if (!process.env.API_INTERNAL_URL) {
    return jsonResponse(500, {
      detail: 'API_INTERNAL_URL is not configured on this server.',
    })
  }

  const search = new URL(request.url).search
  // ``resolveInternalApiBase`` (see ``@/lib/api``) accepts either a
  // full ``http[s]://…`` URL (local dev, historical) or a bare
  // ``hostname[:port]`` (Render private-networking ``hostport`` shape,
  // SEC-010 Step 1). It normalises both to a valid absolute base.
  const targetUrl = `${resolveInternalApiBase()}/api/${joined}${search}`

  const outboundHeaders = new Headers()
  request.headers.forEach((value, name) => {
    if (REQUEST_HEADERS_ALLOWLIST.has(name.toLowerCase())) {
      outboundHeaders.set(name, value)
    }
  })
  const cookieHeader = request.headers.get('cookie')
  if (cookieHeader) outboundHeaders.set('cookie', cookieHeader)

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  const method = request.method.toUpperCase()
  const canHaveBody = method !== 'GET' && method !== 'HEAD'

  try {
    // Buffer the request body once before forwarding. Streaming via
    // ``duplex: 'half'`` is fragile under Next.js 16 + Turbopack in
    // dev, and the endpoints this proxy serves (JSON, small avatars,
    // creator library uploads) all fit comfortably in memory. Node's
    // default request-size limits still apply upstream.
    const init: RequestInit = {
      method,
      headers: outboundHeaders,
      redirect: 'manual',
      signal: controller.signal,
    }
    if (canHaveBody) {
      const bodyBuffer = await request.arrayBuffer()
      // Only attach a body when there is actually one — an empty POST
      // (0 bytes) should not send an empty Buffer that some servers
      // reject with "unexpected end of input".
      if (bodyBuffer.byteLength > 0) init.body = bodyBuffer
    }

    const backendResponse = await fetch(targetUrl, init)

    const responseHeaders = new Headers()
    backendResponse.headers.forEach((value, name) => {
      if (RESPONSE_HEADERS_ALLOWLIST.has(name.toLowerCase())) {
        responseHeaders.set(name, value)
      }
    })

    // Set-Cookie may appear multiple times (login + housekeeping cookies
    // in the same response). ``getSetCookie()`` returns each occurrence
    // separately so we don't accidentally comma-join them.
    const setCookies =
      typeof backendResponse.headers.getSetCookie === 'function'
        ? backendResponse.headers.getSetCookie()
        : []
    for (const cookie of setCookies) {
      responseHeaders.append('set-cookie', cookie)
    }

    return new Response(backendResponse.body, {
      status: backendResponse.status,
      statusText: backendResponse.statusText,
      headers: responseHeaders,
    })
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') {
      return jsonResponse(504, {
        detail: 'The backend took too long to respond.',
      })
    }
    // Log the underlying reason so proxy misconfigurations surface in
    // dev without leaking internals to the client.
    console.error('[api-proxy] fetch failed:', err)
    return jsonResponse(502, {
      detail: 'Unable to reach the backend.',
    })
  } finally {
    clearTimeout(timer)
  }
}

export const GET = proxy
export const POST = proxy
export const PATCH = proxy
export const PUT = proxy
export const DELETE = proxy
export const HEAD = proxy
export const OPTIONS = proxy
