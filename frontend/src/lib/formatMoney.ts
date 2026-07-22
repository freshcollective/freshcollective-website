/**
 * Money formatting for the MVP six-currency whitelist.
 *
 * Prices are stored as integer minor units ("cents") throughout the
 * backend. This helper is the one place the app converts them into
 * a display string. Never render raw cents.
 *
 * We deliberately do NOT use `Intl.NumberFormat` with `style: 'currency'`
 * as the primary shape because locale-dependent symbol placement can
 * make prices ambiguous (e.g. USD renders as `$25.00` and hides that
 * the price is USD, not AUD). Ambiguity-aware prefixes are used:
 *
 *   AUD → A$25
 *   NZD → NZ$25
 *   CAD → C$25
 *   USD → US$25
 *   GBP → £25
 *   EUR → €25
 *
 * Callers can override with `variant: 'full'` to add the ISO code:
 *   formatMoneyCents(2500, 'AUD', 'full') → 'A$25 AUD'
 */

export const SUPPORTED_CURRENCIES = ['AUD', 'USD', 'GBP', 'EUR', 'NZD', 'CAD'] as const
export type SupportedCurrency = (typeof SUPPORTED_CURRENCIES)[number]

const AMBIGUITY_AWARE_PREFIX: Record<string, string> = {
  AUD: 'A$',
  NZD: 'NZ$',
  CAD: 'C$',
  USD: 'US$',
  GBP: '£',
  EUR: '€',
}

/**
 * Format an integer-cents amount for display.
 *
 * @param cents      Integer minor units (e.g. 2500 = $25.00)
 * @param currency   Uppercase ISO 4217 code — one of SUPPORTED_CURRENCIES
 * @param variant    'compact' (default) → "A$25"      · "A$25.00"
 *                   'full'              → "A$25 AUD"  · "A$25.00 AUD"
 */
export function formatMoneyCents(
  cents: number | null | undefined,
  currency: string | null | undefined,
  variant: 'compact' | 'full' = 'compact',
): string {
  if (cents == null || currency == null) return ''
  const upper = currency.toUpperCase()
  const prefix = AMBIGUITY_AWARE_PREFIX[upper] ?? ''
  const dollars = cents / 100
  // Whole numbers show no decimals ("A$25"); fractional show two ("A$19.95").
  const body = Number.isInteger(dollars) ? dollars.toString() : dollars.toFixed(2)
  const base = `${prefix}${body}`
  return variant === 'full' ? `${base} ${upper}` : base
}

/** True if the currency is one we accept for MVP ticket sales. */
export function isSupportedCurrency(code: string | null | undefined): boolean {
  if (!code) return false
  return (SUPPORTED_CURRENCIES as readonly string[]).includes(code.toUpperCase())
}
