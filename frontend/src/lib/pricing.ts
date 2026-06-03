import type { PricingType } from '@/types/platform'

interface PricingSource {
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note?: string | null
}

interface FullPricingSource extends PricingSource {
  has_paid_internal_content: boolean
  min_paid_pathway_price_cents?: number | null
}

function formatAmount(cents: number, currency: string): string {
  const amount = (cents / 100).toFixed(0)
  return `$${amount} ${currency || 'AUD'}`
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
 * Full public summary label shown on Explore cards and About page.
 * Communicates both the join cost AND whether paid content exists inside.
 */
export function formatCollectivePricingSummary(space: FullPricingSource): string {
  const { pricing_type, pricing_amount_cents, pricing_currency, has_paid_internal_content, min_paid_pathway_price_cents } = space
  const currency = pricing_currency || 'AUD'
  const accessLabel = formatCollectiveAccessLabel(space)

  if (pricing_type === 'invite_only' || pricing_type === 'coming_soon') {
    return accessLabel
  }

  if (pricing_type === 'free') {
    if (!has_paid_internal_content) {
      return 'Free to join · all included'
    }
    // TODO: derive minimum pathway pricing dynamically once pathway pricing is fully live
    if (min_paid_pathway_price_cents != null && min_paid_pathway_price_cents > 0) {
      return `Free to join · pathways from ${formatAmount(min_paid_pathway_price_cents, currency)}`
    }
    return 'Free to join · paid pathways available'
  }

  // Paid collective
  const base = accessLabel
  if (has_paid_internal_content) {
    return `${base} · paid extras available`
  }
  return base
}

/** Legacy alias — kept for backwards compat; prefer the two functions above. */
export function formatCollectivePrice(space: PricingSource): string {
  return formatCollectiveAccessLabel(space)
}

export function isPaidPricingType(type: PricingType): boolean {
  return type === 'paid_one_time' || type === 'paid_monthly' || type === 'paid_annual'
}
