/**
 * What Sentry is allowed to know about a member.
 *
 * Phase 3 puts error monitoring in the browser and in fc-web's Node
 * runtime. The risk is not that it fails to report — it is that it
 * reports too much, and in the browser the default surface is wider
 * than on the server: every navigation, every fetch, every
 * ``console.error`` argument becomes a breadcrumb attached to the next
 * error, and this app has URLs whose query string *is* a credential.
 *
 *     /reset-password?token=<raw reset token>
 *     /checkout/complete?token=<raw claim token>
 *     /invites/<raw invite token>
 *
 * A member who follows a reset link and then hits an unrelated render
 * error would, with the SDK's defaults, hand that token to a third
 * party. So the sanitiser is not a nicety here; it is the reason this
 * phase is safe to ship.
 *
 * Deliberately dependency-free
 * ----------------------------
 * This module imports nothing — not Sentry, not Next, not Node. That
 * buys three things: it runs identically in the browser bundle and in
 * the Node runtime, so there is one set of rules rather than two that
 * drift; ``src/lib/sentryPrivacy.test.ts`` can exercise it under
 * ``node --test`` with no DOM and no SDK; and it cannot pull a server
 * module into the client bundle by accident.
 *
 * It is the same vocabulary as ``backend/app/core/observability.py`` on
 * purpose. The platform has one answer to "what is a secret", not a
 * frontend one and a backend one.
 */

export const REDACTED = '[redacted]'
export const REDACTED_EMAIL = '[email redacted]'

/**
 * Query parameters whose value is a credential or an identity.
 *
 * ``email`` is here because ``/verify-email?email=…`` and several
 * MailerLite-shaped links carry it, and an address is the one piece of
 * member identity that makes a Sentry issue personally identifying on
 * its own.
 */
export const SENSITIVE_QUERY_PARAMS: readonly string[] = [
  'token',
  'access_token',
  'refresh_token',
  'reset_token',
  'verification_token',
  'claim_token',
  'invite_token',
  'code',
  'secret',
  'password',
  'email',
]

/**
 * Substring-matched, case-insensitively, against key / header / field
 * names. A hit replaces the value and keeps the key: knowing that an
 * ``Authorization`` header was present is useful, knowing its contents
 * is not.
 */
export const SENSITIVE_KEY_PARTS: readonly string[] = [
  'token',
  'authorization',
  'cookie', // also catches set-cookie
  'stripe-signature',
  'stripe_signature',
  'password',
  'secret',
  'api_key',
  'apikey',
  'bearer',
  'session',
  'jwt',
  'email',
  // The absolute links that carry a single-use credential in their
  // query string. Named explicitly because "url" alone is far too
  // broad to redact.
  'reset_url',
  'verify_url',
  'accept_url',
]

/**
 * Path segments after which the next segment is a raw token rather
 * than an identifier worth keeping.
 *
 * ``/invites/<token>`` is the only one today. The following segments
 * are preserved — ``/invites/<token>/accept`` becomes
 * ``/invites/[redacted]/accept``, which still says which flow broke.
 */
export const SENSITIVE_PATH_PREFIXES: readonly string[] = ['invites']

/** Ordinary email shapes only — a greedier pattern eats Stripe ids. */
const EMAIL = /\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b/g

/** ``key=value`` in free text, most often an interpolated URL. */
const INLINE_SECRET = new RegExp(
  `\\b(${SENSITIVE_QUERY_PARAMS.join('|')})=([^\\s&'"<>)\\]]+)`,
  'gi',
)

/**
 * ``Bearer <value>``. The one credential shape that announces itself
 * by a prefix instead of by a key name, so nothing else can catch it.
 */
const INLINE_BEARER = /\bBearer\s+[A-Za-z0-9._\-~+/=]+/gi

/** Guard against a pathological structure costing more than the event. */
const MAX_DEPTH = 8

export function isSensitiveKey(key: unknown): boolean {
  if (typeof key !== 'string') return false
  const lowered = key.toLowerCase()
  return SENSITIVE_KEY_PARTS.some((part) => lowered.includes(part))
}

/**
 * Redact credentials and email addresses in free text.
 *
 * Applied to exception messages, breadcrumb messages and console
 * output — never to an exception *type*, a module name or a stack
 * frame, which is where the debugging value lives.
 */
export function redactText(value: string): string {
  return value
    .replace(INLINE_SECRET, (_m, name: string) => `${name}=${REDACTED}`)
    .replace(INLINE_BEARER, `Bearer ${REDACTED}`)
    .replace(EMAIL, REDACTED_EMAIL)
}

function redactParamString(query: string): string {
  return query
    .split('&')
    .map((pair) => {
      if (!pair) return pair
      const eq = pair.indexOf('=')
      if (eq < 0) return pair
      const name = pair.slice(0, eq)
      const lowered = decodeURIComponent(name).toLowerCase()
      return SENSITIVE_QUERY_PARAMS.includes(lowered)
        ? `${name}=${REDACTED}`
        : pair
    })
    .join('&')
}

function redactPath(path: string): string {
  const segments = path.split('/')
  for (let i = 0; i < segments.length - 1; i += 1) {
    if (SENSITIVE_PATH_PREFIXES.includes(segments[i].toLowerCase())) {
      // Only the segment immediately after the marker. Anything
      // beyond it is route structure, not a credential.
      if (segments[i + 1]) segments[i + 1] = REDACTED
    }
  }
  // An address can appear in a path too (``/unsubscribe/x@y.com``).
  return segments.join('/').replace(EMAIL, REDACTED_EMAIL)
}

/**
 * Strip credentials from a URL while keeping it useful.
 *
 * Absolute and relative URLs, fragments, and anything malformed all go
 * through the same string-level path rather than ``new URL()``: the
 * input here is whatever the SDK recorded, which includes
 * ``about:blank``, ``javascript:…`` and half-built hrefs, and a parser
 * that throws on those would take the whole event with it.
 *
 * Only values are replaced. A URL whose single ``token`` parameter is
 * sensitive keeps its origin, its path and its other parameters —
 * ``/reset-password`` is exactly the thing worth knowing.
 */
export function sanitiseUrl(url: unknown): string {
  if (typeof url !== 'string') return REDACTED
  if (!url) return url
  try {
    const hashAt = url.indexOf('#')
    const base = hashAt >= 0 ? url.slice(0, hashAt) : url
    const fragment = hashAt >= 0 ? url.slice(hashAt + 1) : null

    const queryAt = base.indexOf('?')
    const path = queryAt >= 0 ? base.slice(0, queryAt) : base
    const query = queryAt >= 0 ? base.slice(queryAt + 1) : null

    let out = redactPath(path)
    if (query !== null) out += `?${redactParamString(query)}`
    if (fragment !== null) {
      // A fragment can be a parameter string (``#token=…``) or free
      // text, so both rule sets run. Free text first, deliberately:
      // the other order redacts ``token=FAKE`` to ``token=[redacted]``
      // and then matches its own output, because ``[redacted]`` is a
      // perfectly good-looking value. This way round is idempotent.
      out += `#${redactParamString(redactText(fragment))}`
    }
    return out
  } catch {
    // Unparseable in some way we did not anticipate. A redacted URL
    // costs debugging context; a leaked one cannot be taken back.
    return REDACTED
  }
}

/** Recursively redact sensitive keys and free text in a value. */
export function scrubValue(value: unknown, depth = 0): unknown {
  if (depth > MAX_DEPTH) return REDACTED
  if (typeof value === 'string') return redactText(value)
  if (Array.isArray(value)) return value.map((v) => scrubValue(v, depth + 1))
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, inner] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSensitiveKey(key) ? REDACTED : scrubValue(inner, depth + 1)
    }
    return out
  }
  return value
}

/** Substituted for a context value that is not a primitive. */
export const DROPPED_NOT_A_PRIMITIVE = '[dropped: not a primitive]'

/**
 * What a hand-written capture may attach.
 *
 * Every value must be a string, a number or a boolean; anything else —
 * a response body, a member record, an Error, a Stripe object — is
 * replaced. This is the same structural guarantee the backend's job
 * summaries use, and for the same reason: the mistake worth preventing
 * is not a wrong decision, it is a convenient one. ``extra: { response }``
 * is three keystrokes and would ship a member's data to a third party.
 *
 * Strings still pass through ``redactText``, because a safe-looking
 * label can carry an interpolated address.
 */
export function safeContext(
  values: Record<string, unknown>,
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {}
  for (const [key, value] of Object.entries(values)) {
    if (isSensitiveKey(key)) {
      out[key] = REDACTED
    } else if (typeof value === 'string') {
      out[key] = redactText(value)
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      out[key] = value
    } else {
      out[key] = DROPPED_NOT_A_PRIMITIVE
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// Event shapes
// ---------------------------------------------------------------------------
//
// Structurally typed rather than imported from the SDK, so this module
// stays dependency-free and the tests can build an event by hand. The
// call sites in the init files cast to the SDK's own types.

interface LooseRequest {
  url?: unknown
  query_string?: unknown
  headers?: Record<string, unknown>
  cookies?: unknown
  data?: unknown
  env?: Record<string, unknown>
}

export interface LooseBreadcrumb {
  category?: string
  message?: unknown
  data?: Record<string, unknown>
  [key: string]: unknown
}

export interface LooseEvent {
  request?: LooseRequest
  transaction?: unknown
  message?: unknown
  logentry?: { message?: unknown; formatted?: unknown; params?: unknown }
  exception?: { values?: Array<{ value?: unknown; [k: string]: unknown }> }
  extra?: Record<string, unknown>
  contexts?: Record<string, unknown>
  tags?: Record<string, unknown>
  user?: Record<string, unknown> | null
  breadcrumbs?: LooseBreadcrumb[] | { values?: LooseBreadcrumb[] }
  [key: string]: unknown
}

/** Header names dropped outright rather than redacted in place. */
function scrubRequest(request: LooseRequest): LooseRequest {
  const out: LooseRequest = { ...request }

  // The body, unconditionally — a password-reset POST carries a raw
  // token and a Conversation POST carries what a member wrote.
  delete out.data
  delete out.cookies

  if (out.headers && typeof out.headers === 'object') {
    const headers: Record<string, unknown> = {}
    for (const [name, value] of Object.entries(out.headers)) {
      headers[name] = isSensitiveKey(name) ? REDACTED : scrubValue(value)
    }
    out.headers = headers
  }

  if (typeof out.url === 'string') out.url = sanitiseUrl(out.url)
  if (typeof out.query_string === 'string') {
    out.query_string = redactParamString(out.query_string)
  }
  if (out.env && typeof out.env === 'object') {
    const env: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(out.env)) {
      if (key === 'QUERY_STRING') continue
      env[key] = isSensitiveKey(key) ? REDACTED : scrubValue(value)
    }
    out.env = env
  }

  return out
}

/**
 * ``beforeBreadcrumb`` — sanitise a breadcrumb, or drop it.
 *
 * Returns ``null`` to drop. Dropping is rare and deliberate: the trail
 * of where a member was before an error is most of what makes a
 * browser issue diagnosable, so this redacts values and keeps the
 * shape wherever it can.
 */
export function scrubBreadcrumb(
  crumb: LooseBreadcrumb | null,
): LooseBreadcrumb | null {
  if (!crumb) return crumb
  try {
    const out: LooseBreadcrumb = { ...crumb }

    if (typeof out.message === 'string') {
      // A navigation crumb's message is a URL; a console crumb's is
      // text. ``sanitiseUrl`` is wrong for prose and ``redactText`` is
      // weak on a path, so pick by what the crumb is.
      out.message =
        out.category === 'navigation' || out.category === 'fetch' ||
        out.category === 'xhr'
          ? sanitiseUrl(out.message)
          : redactText(out.message)
    }

    if (out.data && typeof out.data === 'object') {
      const data: Record<string, unknown> = {}
      for (const [key, value] of Object.entries(out.data)) {
        if (isSensitiveKey(key)) {
          data[key] = REDACTED
        } else if (
          typeof value === 'string' &&
          (key === 'url' || key === 'to' || key === 'from')
        ) {
          data[key] = sanitiseUrl(value)
        } else {
          data[key] = scrubValue(value)
        }
      }
      // ``console`` breadcrumbs carry the raw serialised arguments of
      // every ``console.error`` call in the app. That is an unbounded
      // channel — a logged API response object would arrive whole —
      // and the joined text is already in ``message``, scrubbed. So
      // the arguments go, and nothing diagnosable goes with them.
      if (out.category === 'console') delete data.arguments
      out.data = data
    }

    return out
  } catch {
    return null
  }
}

/**
 * ``beforeSend`` — redact the event, or drop it trying.
 *
 * Returns ``null`` only on an internal failure, which drops the event.
 * That is the deliberate direction, and the same one the backend
 * scrubber takes: a missing error report costs debugging time, and a
 * member's reset token in a third-party service is a different kind of
 * problem that cannot be taken back.
 */
export function scrubEvent(event: LooseEvent | null): LooseEvent | null {
  if (!event) return event
  try {
    const out: LooseEvent = { ...event }

    if (out.request && typeof out.request === 'object') {
      out.request = scrubRequest(out.request)
    }

    // The transaction name is a route (``/spaces/[slug]``) in the
    // normal case, and a raw URL in some browser events.
    if (typeof out.transaction === 'string') {
      out.transaction = sanitiseUrl(out.transaction)
    }

    for (const key of ['extra', 'contexts', 'tags'] as const) {
      const section = out[key]
      if (section && typeof section === 'object') {
        out[key] = scrubValue(section) as Record<string, unknown>
      }
    }

    // ``extra.arguments`` is not ours. The browser SDK's wrapper around
    // ``setTimeout`` / ``addEventListener`` attaches the wrapped
    // callback's arguments to the event, which for an event handler
    // means the DOM event — and through it, in principle, whatever a
    // member had typed. The same unbounded channel as a console
    // breadcrumb's arguments and a log record's params, and dropped for
    // the same reason: there is no key to recognise a value by, and a
    // timer callback's arguments were never the diagnostic part.
    if (out.extra && typeof out.extra === 'object') {
      const extra = { ...(out.extra as Record<string, unknown>) }
      delete extra.arguments
      out.extra = extra
    }

    if (typeof out.message === 'string') out.message = redactText(out.message)
    if (out.logentry && typeof out.logentry === 'object') {
      const logentry = { ...out.logentry }
      for (const field of ['message', 'formatted'] as const) {
        if (typeof logentry[field] === 'string') {
          logentry[field] = redactText(logentry[field] as string)
        }
      }
      delete logentry.params
      out.logentry = logentry
    }

    // Exception type, module and stack are untouched — that is the
    // half worth having. Only the human-readable value is cleaned.
    if (out.exception && Array.isArray(out.exception.values)) {
      out.exception = {
        ...out.exception,
        values: out.exception.values.map((entry) =>
          entry && typeof entry.value === 'string'
            ? { ...entry, value: redactText(entry.value) }
            : entry,
        ),
      }
    }

    const crumbs = out.breadcrumbs
    if (Array.isArray(crumbs)) {
      out.breadcrumbs = crumbs
        .map(scrubBreadcrumb)
        .filter((c): c is LooseBreadcrumb => !!c)
    } else if (crumbs && Array.isArray(crumbs.values)) {
      out.breadcrumbs = {
        ...crumbs,
        values: crumbs.values
          .map(scrubBreadcrumb)
          .filter((c): c is LooseBreadcrumb => !!c),
      }
    }

    // An opaque id answers "which member hit this". An address, a name
    // and an IP answer questions nobody asked. ``ip_address`` is the
    // one the SDK adds by itself when it can.
    if (out.user && typeof out.user === 'object') {
      const id = (out.user as Record<string, unknown>).id
      out.user = id === undefined ? null : { id }
      if (out.user === null) delete out.user
    }

    return out
  } catch {
    return null
  }
}
