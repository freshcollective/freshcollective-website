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
 * • Media / uploaded assets under ``/api/uploads/*`` DO flow through
 *   this proxy. The auth-gated fc-api serve route requires the
 *   ``fc_session`` cookie, which lives on the fc-web origin and
 *   does not accompany cross-site ``<img>`` subresource requests
 *   (Render's ``*.onrender.com`` split, where ``onrender.com`` is
 *   on the Public Suffix List, makes fc-web and fc-api distinct
 *   sites for SameSite=Lax purposes). Routing through the proxy
 *   forwards the cookie server-side and preserves the fc-api ``302``
 *   to the R2 presigned URL — the browser follows that redirect
 *   directly to R2 for the actual bytes, so only the redirect header
 *   (not the image payload) transits Node.
 *
 * Least-privilege: the backend URL is read only from ``API_INTERNAL_URL``
 * (never a client-controlled header) and is never exposed as
 * ``NEXT_PUBLIC_*``. Header forwarding uses explicit allowlists.
 */

import { NextRequest } from 'next/server'

import { resolveInternalApiBase } from '@/lib/api'
import { applyBffAuthHeaders } from '@/lib/bffAuth'
import { captureProxyFailure, classifyProxyFailure } from '@/lib/sentryHandled'
import { isOfferingFileUpload } from '@/lib/uploadRouting'
import {
  acquireLargeUploadSlot,
  needsSlot,
} from '@/lib/uploadConcurrency'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const REQUEST_TIMEOUT_MS = 30_000

// Offerings B5 — a longer budget for the two Offering file-upload paths,
// and nothing else.
//
// The 30 s default is right for JSON and small images, and it is not
// survivable for an Offering file. The timer starts when this proxy
// issues its outbound fetch, so the budget has to cover fc-api spooling
// the body to disk, counting it, transferring it to R2 as a bounded
// multipart upload, and only then replying. Creator Portfolio allows a
// 50 MB file; a 50 MB multipart transfer out of Render Singapore does
// not reliably finish inside 30 s, and when it does not, the creator
// sees a network error for an upload that actually succeeded.
//
// 120 s is deliberately generous rather than tuned: this is a ceiling
// that prevents a false failure, not a target. Render allows an HTTP
// response to take far longer, so nothing upstream contradicts it.
//
// Scoped by path so no other endpoint's failure behaviour changes — a
// hung JSON call still gives up after 30 s, which is what keeps a
// genuinely stuck backend from holding browser connections open.
const UPLOAD_REQUEST_TIMEOUT_MS = 120_000

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

  // SEC-010 Step 2 — BFF-authenticated client-IP claim. See
  // ``bff-auth.ts`` for the security invariants and the tests that
  // lock them in.
  applyBffAuthHeaders(
    outboundHeaders,
    request.headers.get('cf-connecting-ip'),
    process.env.INTERNAL_BFF_SECRET,
  )

  const method = request.method.toUpperCase()
  const canHaveBody = method !== 'GET' && method !== 'HEAD'

  const timeoutMs = isOfferingFileUpload(method, joined)
    ? UPLOAD_REQUEST_TIMEOUT_MS
    : REQUEST_TIMEOUT_MS

  // Shed a large upload rather than carry more than this process has
  // memory for. Small requests never take a slot. See
  // ``uploadConcurrency.ts`` for the measurements behind the number.
  //
  // 429, not 503: the request is being shed deliberately and the client
  // should retry. 503 would also be captured as a Sentry event, which
  // is how FC-API-9 came to hold 36 events of the system working.
  let releaseSlot: (() => void) | null = null
  const declaredBytes = Number.parseInt(
    request.headers.get('content-length') ?? '', 10,
  )
  if (needsSlot(method, request.headers.get('content-length'))) {
    releaseSlot = acquireLargeUploadSlot(declaredBytes)
    if (!releaseSlot) {
      return jsonResponse(429, {
        detail: {
          reason: 'upload_busy',
          message:
            "We're handling other uploads right now. Please try again in "
            + 'a moment — nothing has been lost.',
        },
      })
    }
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    // Stream the request body straight through; nothing is buffered
    // here. This replaced ``await request.arrayBuffer()`` in B6/B7
    // after measurement showed that buffering made fc-web's memory
    // scale with upload size and killed the process under concurrent
    // uploads.
    //
    // Measured on a production build inside a hard 512 MB cgroup —
    // four concurrent 50 MB uploads, peak resident memory:
    //
    //   buffered, middleware on /api   454 MB for ONE; OOM at two
    //   streamed, middleware on /api   382 MB for ONE; OOM at two
    //   streamed, /api excluded        390 MB for FOUR, no OOM
    //
    // Both halves are needed. Streaming here is useless on its own
    // because Next clones the body for the middleware layer before any
    // handler runs (``getCloneableBody`` in
    // ``server/lib/router-utils/resolve-routes.js``), so the matcher in
    // ``src/proxy.ts`` excludes ``/api/`` — where the middleware did
    // nothing anyway. See the B6/B7 report.
    //
    // The historical note here said ``duplex: 'half'`` was fragile under
    // Next 16 + Turbopack in dev. Retested on 16.2.4 in both dev and
    // production: full byte integrity at 1–25 MiB, no errors.
    const init: RequestInit = {
      method,
      headers: outboundHeaders,
      redirect: 'manual',
      signal: controller.signal,
    }
    if (canHaveBody && request.body && request.headers.get('content-length') !== '0') {
      // Hand undici the inbound stream directly rather than
      // materialising it. ``duplex: 'half'`` is required by the fetch
      // spec whenever the body is a stream.
      //
      // An empty POST takes the branch below instead: the old code was
      // careful not to send a zero-length body that "some servers reject
      // with unexpected end of input", and that care is preserved.
      ;(init as RequestInit & { duplex: 'half' }).duplex = 'half'
      init.body = request.body
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
    // Only this branch reports. A backend that answers — 401, 404, 422,
    // even its own 500 — is not a proxy failure: the response is
    // returned untouched above, and fc-api's own Sentry project already
    // owns whatever it did wrong. What reaches here is the case where
    // fc-api never answered at all, and today that disappears into a
    // Render log line.
    //
    // Reported before the response is built, so the ordering can never
    // put reporting between the member and their answer. Neither
    // branch's status, body or timing changes.
    captureProxyFailure(err, {
      method,
      path: joined,
      kind: classifyProxyFailure(err),
      timeoutMs,
    })
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
    releaseSlot?.()
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
