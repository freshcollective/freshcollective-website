/**
 * Asking the server what a discount code is worth.
 *
 * The rule this module exists to keep: the browser sends a code and
 * renders figures. It never calculates one. Every amount displayed here
 * came from the server in the same response that declared the code
 * valid, and the code — not a price — is all that goes back at checkout.
 *
 * That is not ceremony. A discount computed client-side is a number the
 * member can edit, and a number that has to agree with a separate
 * server calculation forever. Sending only the code means there is one
 * calculation, on the side that takes the money.
 *
 * A rejected code is a 200 with `valid: false`, not an HTTP error — so
 * `previewDiscount` treats a thrown fetch as a genuine failure to reach
 * the server, and nothing else.
 */

// Relative, not aliased: this module is covered by node --test, which
// does not resolve the '@/' path alias.
import { apiUrl } from './api.ts'
import { formatMoneyCents } from './formatMoney.ts'

export interface DiscountPreview {
  valid: boolean
  /** The code as the server stores it — trimmed and upper-cased. */
  code: string
  reason?: string | null
  message?: string | null
  original_amount_cents?: number | null
  discount_amount_cents?: number | null
  final_amount_cents?: number | null
  currency?: string | null
  /**
   * Stage 4 — `'single'` for one charge, `'plan'` for finite
   * instalments. On a plan the three amounts above describe the WHOLE
   * commitment, which is what the discount applied to, and the four
   * instalment fields describe how it is paid.
   */
  payment_mode?: 'single' | 'plan' | null
  installment_count?: number | null
  /** What instalments 1..N-1 cost. */
  installment_amount_cents?: number | null
  /** The last instalment, which carries any rounding remainder. */
  final_installment_amount_cents?: number | null
}

/**
 * What is being priced. Exactly one shape, never both.
 *
 * A Payment Option purchase names the option and the schedule; a direct
 * Pathway or Gathering names the experience; an Offering names its
 * slugs. The server refuses a request that names more than one shape,
 * because an answer about the wrong price is worse than no answer — so
 * this is a discriminated union rather than six optional fields.
 */
export type DiscountTarget =
  | {
      kind: 'payment_option'
      paymentOptionId: string
      paymentOptionScheduleId: string
    }
  | { kind: 'pathway' | 'gathering'; targetId: string }
  | { kind: 'offering'; spaceSlug: string; offeringSlug: string }

/** What the field is doing right now. */
export type DiscountFieldState =
  | { status: 'empty' }
  | { status: 'checking' }
  | { status: 'applied'; preview: DiscountPreview }
  | { status: 'rejected'; message: string }
  | { status: 'unreachable'; message: string }

/** Trim and upper-case, matching the server's normalisation. */
export function normaliseCodeInput(raw: string): string {
  return raw.trim().toUpperCase()
}

/**
 * The request fields for one target. Exported so a test can assert the
 * wire shape without a fetch, and so there is one place that maps the
 * union onto the snake_case the API expects.
 */
export function targetBody(target: DiscountTarget): Record<string, string> {
  if (target.kind === 'payment_option') {
    return {
      payment_option_id: target.paymentOptionId,
      payment_option_schedule_id: target.paymentOptionScheduleId,
    }
  }
  if (target.kind === 'offering') {
    // Named by slug, because the member knows which resource they want
    // and has never heard of a Payment Option. The server resolves the
    // Option behind it and prices it as one — which is what it is, and
    // what lets a code scoped to that Option apply.
    return {
      offering_space_slug: target.spaceSlug,
      offering_slug: target.offeringSlug,
    }
  }
  return { direct_kind: target.kind, direct_id: target.targetId }
}

/**
 * Ask what this code would do to this offer's price.
 *
 * Returns the server's verdict. Throws only when the server could not be
 * reached or answered with something unreadable — an invalid code is an
 * answer, not a failure.
 */
export async function previewDiscount(params: {
  code: string
  target: DiscountTarget
  signal?: AbortSignal
}): Promise<DiscountPreview> {
  const res = await fetch(apiUrl('/api/checkout/discount-preview'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    signal: params.signal,
    body: JSON.stringify({
      code: params.code,
      ...targetBody(params.target),
    }),
  })

  if (res.status === 429) {
    throw new Error('Too many attempts. Please wait a moment and try again.')
  }
  if (!res.ok) {
    // 401/404/422 are shape or session problems, not verdicts on the code.
    throw new Error(`We couldn't check that code just now (${res.status}).`)
  }
  return await res.json() as DiscountPreview
}

/**
 * "A$153 — you save A$153" — built entirely from server figures.
 *
 * Returns null when the preview is not a valid, priced one, so a caller
 * cannot accidentally render a partial result.
 */
export function describeApplied(preview: DiscountPreview): {
  final: string
  saving: string
  original: string
} | null {
  if (!preview.valid) return null
  const { final_amount_cents, discount_amount_cents, original_amount_cents, currency } = preview
  if (final_amount_cents == null || discount_amount_cents == null
    || original_amount_cents == null || !currency) {
    return null
  }
  return {
    final: formatMoneyCents(final_amount_cents, currency),
    saving: formatMoneyCents(discount_amount_cents, currency),
    original: formatMoneyCents(original_amount_cents, currency),
  }
}

/**
 * "4 payments of A$40" — or "2 of A$43.33, then A$43.34".
 *
 * Built entirely from server figures. The browser never divides a total
 * by a count: a discounted commitment rarely splits into equal cents,
 * and a client that guessed at the remainder would show a schedule the
 * member is not actually charged. §7 is explicit that the real
 * instalments must be visible before they agree.
 *
 * Returns null when the preview is not a valid plan preview, so a caller
 * cannot render a partial schedule.
 */
export function describeSchedule(preview: DiscountPreview): {
  line: string
  total: string
  isEven: boolean
} | null {
  if (!preview.valid || preview.payment_mode !== 'plan') return null
  const count = preview.installment_count
  const base = preview.installment_amount_cents
  const last = preview.final_installment_amount_cents
  const currency = preview.currency
  const total = preview.final_amount_cents
  if (count == null || base == null || last == null || !currency
    || total == null || count < 1) {
    return null
  }

  const baseText = formatMoneyCents(base, currency)
  const totalText = formatMoneyCents(total, currency)
  const isEven = base === last

  if (isEven) {
    return {
      line: `${count} payment${count === 1 ? '' : 's'} of ${baseText}`,
      total: totalText,
      isEven: true,
    }
  }

  const lastText = formatMoneyCents(last, currency)
  const earlier = count - 1
  // Named separately rather than averaged. "3 payments of A$43.33" would
  // be a small lie about the last one, and rounding the lot up would be
  // a larger one about all of them.
  return {
    line:
      earlier === 1
        ? `1 payment of ${baseText}, then ${lastText}`
        : `${earlier} payments of ${baseText}, then ${lastText}`,
    total: totalText,
    isEven: false,
  }
}

/**
 * The state a verdict puts the field into.
 *
 * A rejection always carries a message: the server sends plain-language
 * prose for every reason, and falling back to a generic line would throw
 * away the useful half ("that code expired on Sunday" → "invalid code").
 */
export function stateFromPreview(preview: DiscountPreview): DiscountFieldState {
  if (preview.valid && describeApplied(preview)) {
    return { status: 'applied', preview }
  }
  return {
    status: 'rejected',
    message: preview.message || 'That code cannot be used for this offer.',
  }
}
