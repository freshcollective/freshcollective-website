export type AccessType = 'free' | 'included' | 'one_time' | 'subscription' | string

export function isPathwayLocked(accessType: AccessType): boolean {
  return accessType === 'one_time' || accessType === 'subscription'
}

export function formatPathwayPrice(
  priceCents: number | null,
  currency: string | null,
  billingInterval: string | null,
): string {
  if (!priceCents) return ''
  const dollars = Math.round(priceCents / 100)
  const curr = (currency ?? 'AUD').toUpperCase()
  if (billingInterval === 'month') return `$${dollars} ${curr}/mo`
  if (billingInterval === 'year') return `$${dollars} ${curr}/yr`
  if (billingInterval) return `$${dollars} ${curr}/${billingInterval}`
  return `$${dollars} ${curr}`
}

export function accessBadgeLabel(accessType: AccessType): string | null {
  if (accessType === 'free') return 'Free'
  if (accessType === 'included') return 'Included'
  return null
}

export function unlockCtaLabel(
  accessType: AccessType,
  priceCents: number | null,
  currency: string | null,
  billingInterval: string | null,
): string {
  const price = formatPathwayPrice(priceCents, currency, billingInterval)
  if (accessType === 'subscription') return price ? `Join for ${price}` : 'Join'
  return price ? `Unlock for ${price}` : 'Unlock'
}
