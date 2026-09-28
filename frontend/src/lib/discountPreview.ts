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
}

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
 * Ask what this code would do to this offer's price.
 *
 * Returns the server's verdict. Throws only when the server could not be
 * reached or answered with something unreadable — an invalid code is an
 * answer, not a failure.
 */
export async function previewDiscount(params: {
  code: string
  paymentOptionId: string
  paymentOptionScheduleId: string
  signal?: AbortSignal
}): Promise<DiscountPreview> {
  const res = await fetch(apiUrl('/api/checkout/discount-preview'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    signal: params.signal,
    body: JSON.stringify({
      code: params.code,
      payment_option_id: params.paymentOptionId,
      payment_option_schedule_id: params.paymentOptionScheduleId,
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
