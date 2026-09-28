import { formatCalendarDate } from './dateTime.ts'

/**
 * Turning discount codes between Creator language and API units.
 *
 * The API speaks basis points and minor units because money arithmetic
 * has to be exact. A Creator types "50" and "$25". Every conversion
 * between the two lives here, so a form and a list cannot disagree about
 * what 5000 means, and so the arithmetic is testable without rendering
 * anything.
 *
 * Nothing here re-derives a business rule. Whether a code may still be
 * edited or deleted is the API's answer — ``definition_editable`` and
 * ``deletable`` — and the UI reads those rather than recomputing them
 * from a redemption count it would then have to keep in step.
 */

export interface DiscountCode {
  id: string
  space_id: string
  code: string
  discount_type: 'percentage' | 'fixed_amount'
  percent_bps: number | null
  amount_cents: number | null
  currency: string | null
  scope_kind: 'space' | 'payment_option'
  scope_id: string | null
  scope_payment_option_name: string | null
  is_active: boolean
  /** The calendar day the Creator chose, in the Collective's timezone.
   *  This is what to display — it is the date they picked. */
  expires_on: string | null
  /** The canonical instant the code stops working, resolved server-side.
   *  Never rendered: reading it in the browser's timezone is exactly the
   *  bug this field's companion exists to avoid. */
  expires_at: string | null
  max_redemptions: number | null
  redemption_count: number
  definition_editable: boolean
  deletable: boolean
  created_at: string
  updated_at: string
}

/** The largest discount v1 offers. 100% is complimentary access, which
 *  is a different thing, and the API refuses it. */
export const MAX_PERCENT = 99

// ---------------------------------------------------------------------------
// Unit conversion, at the boundary
// ---------------------------------------------------------------------------

/** "50" → 5000. Two decimal places of precision, no floating drift. */
export function percentToBps(percent: number | string): number {
  // ``Number('')`` is 0, so a blank field would otherwise become a
  // silent 0% rather than an error the Creator can see.
  if (typeof percent === 'string' && !percent.trim()) return NaN
  const n = typeof percent === 'string' ? Number(percent) : percent
  if (!Number.isFinite(n)) return NaN
  return Math.round(n * 100)
}

/** 5000 → 50. Trailing zeroes trimmed: 2550 → 25.5, not 25.50. */
export function bpsToPercent(bps: number | null): number | null {
  if (bps === null || !Number.isFinite(bps)) return null
  return bps / 100
}

/** "25.50" → 2550. Rounds to the cent rather than truncating. */
export function dollarsToCents(dollars: number | string): number {
  // Same trap as above: a blank amount must not become $0.00.
  if (typeof dollars === 'string' && !dollars.trim()) return NaN
  const n = typeof dollars === 'string' ? Number(dollars) : dollars
  if (!Number.isFinite(n)) return NaN
  return Math.round(n * 100)
}

/** 2550 → 25.5 */
export function centsToDollars(cents: number | null): number | null {
  if (cents === null || !Number.isFinite(cents)) return null
  return cents / 100
}

/** What the input shows back as the Creator types.
 *
 *  Codes are matched case-insensitively and stored upper-cased, so the
 *  field normalises visibly — typing "family50" shows FAMILY50, and the
 *  Creator is never surprised later by a code that looks different from
 *  what they entered. */
export function normaliseCodeInput(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9_-]/g, '')
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

const CURRENCY_SYMBOL: Record<string, string> = {
  AUD: 'A$', NZD: 'NZ$', USD: 'US$', GBP: '£', EUR: '€',
}

/** "50% off" / "$25.00 AUD off" — never basis points or cents. */
export function formatDiscountValue(code: Pick<
  DiscountCode, 'discount_type' | 'percent_bps' | 'amount_cents' | 'currency'
>): string {
  if (code.discount_type === 'percentage') {
    const pct = bpsToPercent(code.percent_bps)
    return pct === null ? '—' : `${trimNumber(pct)}%`
  }
  const dollars = centsToDollars(code.amount_cents)
  if (dollars === null) return '—'
  const currency = (code.currency ?? '').toUpperCase()
  const symbol = CURRENCY_SYMBOL[currency] ?? ''
  const amount = dollars.toFixed(2)
  return symbol ? `${symbol}${amount} ${currency}`.trim() : `${amount} ${currency}`.trim()
}

/** "Entire Collective" or the Payment Option's own name. */
export function formatScope(code: Pick<
  DiscountCode, 'scope_kind' | 'scope_payment_option_name'
>): string {
  if (code.scope_kind === 'space') return 'Entire Collective'
  return code.scope_payment_option_name || 'One Payment Option'
}

export type StatusTone = 'active' | 'inactive' | 'expired' | 'used-up'

export interface CodeStatus {
  label: string
  tone: StatusTone
  /** Why it cannot currently be used, when that is the case. */
  detail?: string
}

/**
 * What a Creator needs to know at a glance.
 *
 * Deliberately richer than ``is_active``: a code can be switched on and
 * still unusable because it expired or filled up, and "Active" next to
 * "25 / 25 used" would be a lie the Creator has to work out for
 * themselves.
 */
export function describeStatus(
  code: Pick<DiscountCode, 'is_active' | 'expires_at' | 'max_redemptions' | 'redemption_count'>,
  now: Date = new Date(),
): CodeStatus {
  if (!code.is_active) return { label: 'Inactive', tone: 'inactive' }

  // Status asks "is it over yet?", which is a question about an instant,
  // so this reads ``expires_at`` while the label beside it reads
  // ``expires_on``. ``<=`` matches the server: that instant is the first
  // moment the code is gone, not the last moment it works.
  if (code.expires_at) {
    const expiry = new Date(
      /Z$|[+-]\d{2}:?\d{2}$/.test(code.expires_at) ? code.expires_at : `${code.expires_at}Z`,
    )
    if (expiry.getTime() <= now.getTime()) {
      return { label: 'Expired', tone: 'expired', detail: 'This code has passed its end date.' }
    }
  }

  if (code.max_redemptions !== null && code.redemption_count >= code.max_redemptions) {
    return {
      label: 'Fully used',
      tone: 'used-up',
      detail: 'This code has reached the number of uses you set.',
    }
  }

  return { label: 'Active', tone: 'active' }
}

/** "3 used" / "3 of 25 used" — never a bare system count. */
export function formatUsage(code: Pick<DiscountCode, 'redemption_count' | 'max_redemptions'>): string {
  if (code.max_redemptions === null) {
    return code.redemption_count === 1 ? '1 use' : `${code.redemption_count} uses`
  }
  return `${code.redemption_count} of ${code.max_redemptions} used`
}

/**
 * "31 Oct 2026", or null when there is no end date.
 *
 * Reads ``expires_on`` — the day the Creator chose, already resolved
 * against the Collective's timezone by the server. Deliberately NOT the
 * instant: rendering that in the reader's timezone is how a Melbourne
 * code came to display as ending on 1 November.
 */
export function formatExpiry(expires_on: string | null): string | null {
  if (!expires_on) return null
  return formatCalendarDate(expires_on)
}

function trimNumber(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2)))
}

// ---------------------------------------------------------------------------
// Form ↔ API
// ---------------------------------------------------------------------------

export interface DiscountFormValues {
  code: string
  discountType: 'percentage' | 'fixed_amount'
  percent: string
  amount: string
  currency: string
  scope: 'space' | 'payment_option'
  paymentOptionId: string
  expiresAt: string
  maxRedemptions: string
  isActive: boolean
}

export function emptyForm(defaultCurrency = 'AUD'): DiscountFormValues {
  return {
    code: '', discountType: 'percentage', percent: '', amount: '',
    currency: defaultCurrency, scope: 'space', paymentOptionId: '',
    expiresAt: '', maxRedemptions: '', isActive: true,
  }
}

export function formFromCode(code: DiscountCode): DiscountFormValues {
  return {
    code: code.code,
    discountType: code.discount_type,
    percent: code.percent_bps === null ? '' : String(bpsToPercent(code.percent_bps)),
    amount: code.amount_cents === null ? '' : String(centsToDollars(code.amount_cents)),
    currency: code.currency ?? 'AUD',
    scope: code.scope_kind,
    paymentOptionId: code.scope_id ?? '',
    expiresAt: code.expires_on ?? '',
    maxRedemptions: code.max_redemptions === null ? '' : String(code.max_redemptions),
    isActive: code.is_active,
  }
}

/** Creator-facing checks, so the obvious mistakes are caught before a
 *  round trip. The API validates independently and is the authority. */
export function validateForm(values: DiscountFormValues): string | null {
  if (!values.code.trim()) return 'Give the code a name, for example FAMILY50.'

  if (values.discountType === 'percentage') {
    const pct = Number(values.percent)
    if (!values.percent.trim() || !Number.isFinite(pct)) return 'Enter a percentage.'
    if (pct <= 0) return 'The percentage needs to be above zero.'
    if (pct > MAX_PERCENT) {
      return `The most you can discount is ${MAX_PERCENT}%. To give access for free, use a complimentary pass instead.`
    }
  } else {
    const amount = Number(values.amount)
    if (!values.amount.trim() || !Number.isFinite(amount)) return 'Enter an amount.'
    if (amount <= 0) return 'The amount needs to be above zero.'
    if (!values.currency.trim()) return 'Choose a currency.'
  }

  if (values.scope === 'payment_option' && !values.paymentOptionId) {
    return 'Choose which Payment Option this code applies to.'
  }

  if (values.maxRedemptions.trim()) {
    const max = Number(values.maxRedemptions)
    if (!Number.isInteger(max) || max < 1) return 'The limit on uses needs to be a whole number, at least 1.'
  }

  return null
}

/** The request body, in API units. */
export function toCreatePayload(values: DiscountFormValues): Record<string, unknown> {
  const isPercent = values.discountType === 'percentage'
  return {
    code: values.code.trim().toUpperCase(),
    discount_type: values.discountType,
    percent_bps: isPercent ? percentToBps(values.percent) : null,
    amount_cents: isPercent ? null : dollarsToCents(values.amount),
    currency: isPercent ? null : values.currency.trim().toUpperCase(),
    scope_kind: values.scope,
    scope_id: values.scope === 'payment_option' ? values.paymentOptionId : null,
    // See ``toUpdatePayload``: a calendar day, resolved server-side.
    expires_on: values.expiresAt || null,
    max_redemptions: values.maxRedemptions.trim() ? Number(values.maxRedemptions) : null,
    is_active: values.isActive,
  }
}

/**
 * The PATCH body, carrying only what this Creator may still change.
 *
 * Once a code has been redeemed the API freezes its definition, so
 * sending those fields would earn a 409 for something the Creator did
 * not try to do — the form disables them, and this makes sure a stale
 * client cannot send them either.
 */
export function toUpdatePayload(
  values: DiscountFormValues, definitionEditable: boolean,
): Record<string, unknown> {
  const operational = {
    // The DAY, not an instant. The server resolves it against the
    // Collective's timezone; a browser-built timestamp would make the
    // answer depend on where the Creator happens to be sitting.
    expires_on: values.expiresAt || null,
    max_redemptions: values.maxRedemptions.trim() ? Number(values.maxRedemptions) : null,
    is_active: values.isActive,
  }
  if (!definitionEditable) return operational

  const isPercent = values.discountType === 'percentage'
  return {
    ...operational,
    code: values.code.trim().toUpperCase(),
    discount_type: values.discountType,
    percent_bps: isPercent ? percentToBps(values.percent) : null,
    amount_cents: isPercent ? null : dollarsToCents(values.amount),
    currency: isPercent ? null : values.currency.trim().toUpperCase(),
    scope_kind: values.scope,
    scope_id: values.scope === 'payment_option' ? values.paymentOptionId : null,
  }
}
