import type { PricingType } from '@/types/platform'

interface PricingSource {
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note?: string | null
}

export function formatCollectivePrice(space: PricingSource): string {
  const { pricing_type, pricing_amount_cents, pricing_currency } = space
  const currency = pricing_currency || 'AUD'

  switch (pricing_type) {
    case 'free':
      return 'Free'
    case 'invite_only':
      return 'Invite only'
    case 'coming_soon':
      return 'Paid — coming soon'
    case 'paid_one_time': {
      if (!pricing_amount_cents) return 'Paid'
      const amount = (pricing_amount_cents / 100).toFixed(0)
      return `$${amount} ${currency}`
    }
    case 'paid_monthly': {
      if (!pricing_amount_cents) return 'Paid / month'
      const amount = (pricing_amount_cents / 100).toFixed(0)
      return `$${amount} ${currency} / month`
    }
    case 'paid_annual': {
      if (!pricing_amount_cents) return 'Paid / year'
      const amount = (pricing_amount_cents / 100).toFixed(0)
      return `$${amount} ${currency} / year`
    }
    default:
      return 'Free'
  }
}

export function isPaidPricingType(type: PricingType): boolean {
  return type === 'paid_one_time' || type === 'paid_monthly' || type === 'paid_annual'
}
