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

/**
 * The "Paid separately" line in the About page's Access card.
 *
 * Priority, unchanged from the inline version this replaces:
 *   1. ``paid_content_summary`` (creator-entered) — always wins when non-empty
 *   2. the backend's derived minimum paid Pathway price
 *   3. a generic last resort
 *
 * Note this is the opposite precedence to the inline suffix in
 * ``formatCollectivePricingSummary`` for a free Collective, where the
 * derived price wins. That difference is deliberate and pre-existing:
 * the Access card is the creator's own description of what they sell,
 * while the quick-facts row is a price comparison. Both are left as
 * they were.
 *
 * Lives here, exported, because it used to be a template literal inside
 * an async server component — unreachable from the test harness, which
 * is why it quietly kept quoting a stale price alongside the row above
 * it. ``min_paid_pathway_price_cents`` must come from the backend; see
 * the note on that field.
 */
export function formatPaidSeparatelyCopy(space: FullPricingSource): string {
  const manualSummary = space.paid_content_summary?.trim()
  if (manualSummary) return manualSummary

  const cents = space.min_paid_pathway_price_cents
  if (cents != null && cents > 0) {
    // Deliberately the same shape the page rendered before: whole
    // dollars, AUD. Currency is not read from ``pricing_currency``
    // here because it never was, and changing the copy was not part
    // of fixing where the number comes from.
    return `Pathways from $${Math.round(cents / 100)} AUD`
  }
  return 'Paid pathways available separately'
}

/**
 * The Access card's line when there is no paid content to describe.
 *
 * Reached only when the purchase-required and paid-separately branches
 * above have both declined, so it is the "nothing is sold inside here"
 * case. Priority, unchanged:
 *   1. the creator's own ``pricing_note``
 *   2. a statement about joining, for a free Collective
 *   3. nothing at all — a paid Collective has already said its price
 *      in the Access label, and repeating it here reads as a second fee
 *
 * This used to say "All available content is included." It was too
 * strong a claim to derive from a purchasability flag. A Collective can
 * hold paid content that is configured but not currently checkoutable
 * — an instalment plan published before member plans were switched on,
 * for instance — and the public flag is false in exactly that case. So
 * the page would tell a visitor everything was included while the
 * creator had already published something that is not.
 *
 * "Joining this Collective is free." says only the part that is
 * reliably true here, which is the part the Access card is answering.
 * It makes no claim about what is inside.
 */
export function formatAccessFallbackCopy(space: PricingSource): string | null {
  // Truthy rather than trimmed, deliberately: that is what this branch
  // has always done, and tightening it would change which Collectives
  // see their own note.
  if (space.pricing_note) return space.pricing_note
  if (space.pricing_type === 'free') return 'Joining this Collective is free.'
  return null
}

/** Legacy alias — prefer the two functions above. */
export function formatCollectivePrice(space: PricingSource): string {
  return formatCollectiveAccessLabel(space)
}

export function isPaidPricingType(type: PricingType): boolean {
  return type === 'paid_one_time' || type === 'paid_monthly' || type === 'paid_annual'
}
