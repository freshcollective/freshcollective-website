/**
 * Extract a human-readable message from a FastAPI (or generic
 * fetch) error response body.
 *
 * The backend uses at least four distinct error-body shapes:
 *
 *   1. Plain-string detail — the pre-FIP1 convention.
 *      ``{"detail": "Payment schedule not found."}``
 *
 *   2. Structured detail (FIP1+ validators) — an object with a
 *      human message plus a list of field-level errors.
 *      ``{"detail": {"message": "…", "errors": ["…", "…"]}}``
 *
 *   3. Pydantic / FastAPI request validation — an array of
 *      per-field entries.
 *      ``{"detail": [{"loc": ["body", "amount"], "msg": "…",
 *                     "type": "…"}]}``
 *
 *   4. Nothing readable (network error, HTML 5xx, no body).
 *      → we fall back to a generic message that includes the
 *        HTTP status so operators can find the request in logs.
 *
 * Rendering ``[object Object]`` to a Creator is a bug — no matter
 * what the backend sends, this function must return a string.
 *
 * Not React-specific; used from every Creator Studio form + can
 * be adopted anywhere fetch() throws.
 */

export interface ExtractOptions {
  /** HTTP status when the caller knows it — surfaces in the
   *  fallback message so support can find the request server-side. */
  status?: number
  /** Copy shown when nothing readable can be extracted. */
  fallback?: string
}

/** Extract a human-readable message from an arbitrary error value. */
export function extractApiErrorMessage(
  input: unknown,
  opts: ExtractOptions = {},
): string {
  const fallback = opts.fallback ?? 'Something went wrong. Please try again.'
  if (input === null || input === undefined) return fallback

  // Native Error — inspect its message first, but also unwrap the
  // "cause" chain in case someone wrapped a fetch body inside.
  if (input instanceof Error) {
    const m = messageFromString(input.message)
    if (m) return m
    return fallback
  }

  // Plain string — either a JSON blob or a message.
  if (typeof input === 'string') {
    return messageFromString(input) ?? input
  }

  // Object body — walk the known shapes.
  if (typeof input === 'object') {
    const msg = messageFromDetailObject(input as Record<string, unknown>)
    if (msg) return msg
  }

  return fallback
}

// ---------------------------------------------------------------------------
// Convenience: extract from a completed fetch Response
// ---------------------------------------------------------------------------

/**
 * Read a fetch Response's body and return a message. Consumes the
 * body once — callers should not read it again. Safe against
 * responses that carry no body / non-JSON.
 */
export async function extractApiErrorFromResponse(
  res: Response,
  opts: ExtractOptions = {},
): Promise<string> {
  const options: ExtractOptions = {
    status: res.status,
    fallback: opts.fallback ?? `Request failed (${res.status} ${res.statusText}).`,
  }
  let body: unknown = null
  try {
    // Try JSON first — that's what FastAPI serves for errors.
    body = await res.clone().json()
  } catch {
    try {
      body = await res.text()
    } catch {
      body = null
    }
  }
  return extractApiErrorMessage(body, options)
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function messageFromString(raw: string): string | null {
  const trimmed = raw?.trim()
  if (!trimmed) return null

  // JSON string — parse and delegate.
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed)
      if (typeof parsed === 'string') return parsed
      if (typeof parsed === 'object' && parsed !== null) {
        const m = messageFromDetailObject(parsed as Record<string, unknown>)
        if (m) return m
      }
    } catch {
      /* fall through — return the raw string as-is */
    }
  }

  // Common JS-side symptom: someone did ``String(errorObject)`` and
  // got ``[object Object]``. Treat as "no readable message" so the
  // caller's fallback fires.
  if (trimmed === '[object Object]') return null

  return trimmed
}

function messageFromDetailObject(obj: Record<string, unknown>): string | null {
  // Prefer ``.detail`` if present — that's what FastAPI wraps errors in.
  const detail = 'detail' in obj ? obj.detail : obj

  // Structured detail (FIP1+ validators): ``{message, errors: []}``.
  if (isPlainObject(detail)) {
    const message = typeof detail.message === 'string'
      ? detail.message.trim()
      : ''
    const errors = Array.isArray(detail.errors)
      ? detail.errors
          .map((e) => (typeof e === 'string' ? e : safeStringifyError(e)))
          .filter((s): s is string => !!s)
      : []
    if (message && errors.length > 0) {
      return `${message} ${errors.join(' ')}`
    }
    if (message) return message
    if (errors.length > 0) return errors.join(' ')
    // Fall through — object without message/errors, try flat scan.
  }

  // Pydantic validation error list: ``[{loc, msg, type}, …]``.
  if (Array.isArray(detail)) {
    const parts = detail
      .map((e) => formatPydanticError(e))
      .filter((s): s is string => !!s)
    if (parts.length > 0) return parts.join(' ')
  }

  // Plain-string detail wrapped in an object.
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim()
  }

  // Object with a top-level ``message`` / ``error`` field (some
  // legacy endpoints use these).
  const flat = ['message', 'error', 'reason']
    .map((k) => (typeof obj[k] === 'string' ? (obj[k] as string).trim() : null))
    .find((s): s is string => !!s)
  return flat ?? null
}

function formatPydanticError(entry: unknown): string | null {
  if (!isPlainObject(entry)) return null
  const msg = typeof entry.msg === 'string' ? entry.msg.trim() : ''
  const loc = Array.isArray(entry.loc)
    ? entry.loc.filter((s) => typeof s === 'string' || typeof s === 'number')
    : []
  if (!msg) return null
  // Skip the leading "body" segment that FastAPI always prefixes.
  const field = loc.length > 1 ? loc.slice(1).join('.') : loc.join('.')
  return field ? `${field}: ${msg}` : msg
}

function safeStringifyError(entry: unknown): string | null {
  if (typeof entry === 'string') return entry.trim() || null
  if (isPlainObject(entry)) {
    const msg = typeof entry.msg === 'string' ? entry.msg : null
    const message = typeof entry.message === 'string' ? entry.message : null
    return (msg || message || '').trim() || null
  }
  return null
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
