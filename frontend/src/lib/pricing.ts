import type { PricingType } from '@/types/platform'

interface PricingSource {
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note?: string | null
}

interface FullPricingSource extends PricingSource {
  has_paid_internal_content: boolean
  /**
   * Creator-entered copy describing what is paid separately.
   * This is the PRIMARY source for the inline "· ..." suffix.
   * min_paid_pathway_price_cents is only used as a fallback when this is blank.
   */
  paid_content_summary?: string | null
  /**
   * Auto-derived minimum price of any active paid pathway in this collective (cents).
   * Only shown if paid_content_summary is blank and the value is a positive integer.
   */
  min_paid_pathway_price_cents?: number | null
}

function formatAmount(cents: number, currency: string): string {
  const amount = (cents / 100).toFixed(0)
  return `$${amount} ${currency || 'AUD'}`
}

/** Lowercase the first character of a string for inline embedding. */
function inlineCase(s: string): string {
  return s.charAt(0).toLowerCase() + s.slice(1)
}

/** The join-cost label only — answers "What does it cost to join this collective?" */
export function formatCollectiveAccessLabel(space: PricingSource): string {
  const { pricing_type, pricing_amount_cents, pricing_currency } = space
  const currency = pricing_currency || 'AUD'

  switch (pricing_type) {
    case 'free':
      return 'Free to join'
    case 'invite_only':
      return 'Invite only'
    case 'coming_soon':
      return 'Paid — coming soon'
    case 'paid_one_time':
      return pricing_amount_cents ? formatAmount(pricing_amount_cents, currency) : 'Paid'
    case 'paid_monthly':
      return pricing_amount_cents ? `${formatAmount(pricing_amount_cents, currency)} / month` : 'Paid / month'
    case 'paid_annual':
      return pricing_amount_cents ? `${formatAmount(pricing_amount_cents, currency)} / year` : 'Paid / year'
    default:
      return 'Free to join'
  }
}

/**
 * Full public summary label for Explore cards and the About quick-facts row.
 *
 * Priority for the "· ..." suffix:
 *   1. paid_content_summary (creator-entered) — always wins when present
 *   2. min_paid_pathway_price_cents (auto-derived) — fallback when (1) is blank
 *   3. Generic "paid pathways available" — last resort
 */
export function formatCollectivePricingSummary(space: FullPricingSource): string {
  const { pricing_type, pricing_currency, has_paid_internal_content, paid_content_summary, min_paid_pathway_price_cents } = space
  const currency = pricing_currency || 'AUD'
  const accessLabel = formatCollectiveAccessLabel(space)

  if (pricing_type === 'invite_only' || pricing_type === 'coming_soon') {
    return accessLabel
  }

  if (pricing_type === 'free') {
    if (!has_paid_internal_content) {
      return 'Free to join · all included'
    }
    // 1. Creator-entered copy wins
    const manualSummary = paid_content_summary?.trim()
    if (manualSummary) {
      return `Free to join · ${inlineCase(manualSummary)}`
    }
    // 2. Auto-derived pathway price fallback
    if (min_paid_pathway_price_cents != null && min_paid_pathway_price_cents > 0) {
      return `Free to join · pathways from ${formatAmount(min_paid_pathway_price_cents, currency)}`
    }
    // 3. Generic fallback
    return 'Free to join · paid pathways available'
  }

  // Paid collective
  if (has_paid_internal_content) {
    const manualSummary = paid_content_summary?.trim()
    if (manualSummary) {
      return `${accessLabel} · ${inlineCase(manualSummary)}`
    }
    return `${accessLabel} · paid extras available`
  }
  return accessLabel
}

/** Legacy alias — prefer the two functions above. */
export function formatCollectivePrice(space: PricingSource): string {
  return formatCollectiveAccessLabel(space)
}

export function isPaidPricingType(type: PricingType): boolean {
  return type === 'paid_one_time' || type === 'paid_monthly' || type === 'paid_annual'
}
