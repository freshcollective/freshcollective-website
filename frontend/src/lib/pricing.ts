import type { JoinPolicy, PricingType } from '@/types/platform'

interface PricingSource {
  pricing_type: PricingType
  pricing_amount_cents: number | null
  pricing_currency: string
  pricing_note?: string | null
  /**
   * How someone actually becomes a member. Authoritative over
   * ``pricing_type`` for any statement about *joining*.
   *
   * The two answer different questions and can legitimately disagree:
   * EMBODY is ``pricing_type: 'free'`` — it charges nothing for
   * membership itself — while ``join_policy: 'purchase_required'``,
   * because membership only arrives attached to a term purchase. The
   * About page said "Free to join" and "Membership comes with your
   * first purchase" in the same column until this was threaded
   * through.
   *
   * Optional and defaulting to ``open`` so every caller that has not
   * hydrated it keeps today's behaviour exactly.
   */
  join_policy?: JoinPolicy | null
}

/** The joining claim, when the policy overrides whatever the pricing
 *  fields would have said. ``null`` means "pricing_type still tells
 *  the truth here". */
function joinPolicyLabel(space: PricingSource): string | null {
  return space.join_policy === 'purchase_required'
    ? 'Membership comes with a purchase'
    : null
}

interface FullPricingSource extends PricingSource {
  /** Creator-manually-set flag indicating this collective has paid internal content. */
  has_paid_internal_content: boolean
  /**
   * Auto-derived: true if the collective has at least one active paid pathway.
   * Computed by the backend from pathway pricing data.
   */
  derived_has_paid_internal_content?: boolean
  /**
   * Creator-entered copy for the paid-separately suffix.
   * PRIMARY source for the inline "· ..." label — wins over auto-derived price.
   * Only falls back to min_paid_pathway_price_cents when this is blank.
   */
  paid_content_summary?: string | null
  /**
   * Auto-derived minimum price of any active paid pathway (cents).
   * Only shown when paid_content_summary is blank.
   */
  min_paid_pathway_price_cents?: number | null
}

function formatAmount(cents: number, currency: string): string {
  const amount = (cents / 100).toFixed(0)
  return `$${amount} ${currency || 'AUD'}`
}

/** True for a letter in upper case. Non-letters are neither, which
 *  is what makes "3 sessions" and "$20 passes" fall through
 *  untouched. */
function isUpper(ch: string): boolean {
  return ch !== '' && ch !== ch.toLowerCase() && ch === ch.toUpperCase()
}

/**
 * Lower-case the first character for inline embedding, e.g.
 * "Free to join · paid pathways available".
 *
 * Unless the summary opens on an acronym or a styled proper name,
 * which two leading capitals reliably signal. Lower-casing
 * unconditionally turned a creator's "EMBODY term access…" into
 * "eMBODY term access…" on the public Explore card and About row —
 * their own Collective's name, misspelt by us, on the page that
 * introduces it.
 *
 *   "Paid pathways available"  → "paid pathways available"
 *   "EMBODY term access"       → "EMBODY term access"
 *   "AI resources available"   → "AI resources available"
 *
 * Two capitals rather than one, because a single leading capital is
 * ordinary sentence case and lower-casing it is the whole point of
 * this helper.
 */
function inlineCase(s: string): string {
  if (isUpper(s.charAt(0)) && isUpper(s.charAt(1))) return s
  return s.charAt(0).toLowerCase() + s.slice(1)
}

/** The join-cost label only — answers "What does it cost to join this collective?" */
export function formatCollectiveAccessLabel(space: PricingSource): string {
  const policyLabel = joinPolicyLabel(space)
  if (policyLabel) return policyLabel

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
 * Full public summary for Explore cards and the About quick-facts row.
 *
 * effectiveHasPaidContent = has_paid_internal_content OR derived_has_paid_internal_content
 *
 * Priority for the "· ..." suffix when paid content is present:
 *   1. paid_content_summary (creator-entered) — always wins when non-empty
 *   2. min_paid_pathway_price_cents (auto-derived) — used only when (1) is blank
 *   3. "paid pathways available" — generic last resort
 */
export function formatCollectivePricingSummary(space: FullPricingSource): string {
  const {
    pricing_type, pricing_currency,
    has_paid_internal_content, derived_has_paid_internal_content,
    paid_content_summary, min_paid_pathway_price_cents,
  } = space
  const currency = pricing_currency || 'AUD'
  const accessLabel = formatCollectiveAccessLabel(space)

  // A purchase-required Collective has already said the important
  // thing. Appending "· pathways from $X" would read as a second,
  // competing price for the same doorway.
  if (joinPolicyLabel(space)) {
    return accessLabel
  }

  if (pricing_type === 'invite_only' || pricing_type === 'coming_soon') {
    return accessLabel
  }

  const effectivePaid = has_paid_internal_content || (derived_has_paid_internal_content ?? false)

  if (pricing_type === 'free') {
    if (!effectivePaid) {
      return 'Free to join · all included'
    }
    // 1. Auto-derived pathway price wins when active paid pathways exist
    if (min_paid_pathway_price_cents != null && min_paid_pathway_price_cents > 0) {
      return `Free to join · pathways from ${formatAmount(min_paid_pathway_price_cents, currency)}`
    }
    // 2. Creator-entered copy fallback when no price is derivable
    const manualSummary = paid_content_summary?.trim()
    if (manualSummary) {
      return `Free to join · ${inlineCase(manualSummary)}`
    }
    // 3. Generic fallback
    return 'Free to join · paid content available'
  }

  // Paid collective
  if (effectivePaid) {
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
