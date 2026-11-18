import type { JoinPolicy, PricingType } from '@/types/platform'
// Relative, like the other lib-to-lib imports that the node test
// runner has to resolve: it has no tsconfig path mapping, so an
// ``@/`` alias here breaks every test that imports this module.
import { ONE_TIME_INTERVAL, formatRecurring } from './membership.ts'

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

/**
 * Pathway prices, and nothing else any more.
 *
 * Collective *membership* amounts moved to the shared membership
 * formatter, which names the currency ("A$29") instead of leaving a
 * bare "$" that five currencies share. This one is left as it was on
 * purpose: Pathway, Gathering, Offering and Payment Option pricing
 * are outside Stage 5A.4a's brief, and changing them here would be
 * the platform-wide money refactor it rules out. They carry the same
 * ambiguity and are worth the same treatment later.
 */
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
    // Membership amounts go through the shared membership formatter,
    // so the About page, the settings card, the conversion prompt and
    // Stripe's own checkout page all say the same thing.
    case 'paid_one_time':
      return pricing_amount_cents
        ? formatRecurring(pricing_amount_cents, currency, ONE_TIME_INTERVAL)
        : 'Paid'
    case 'paid_monthly':
      return pricing_amount_cents
        ? formatRecurring(pricing_amount_cents, currency, 'month')
        : 'Paid / month'
    case 'paid_annual':
      return pricing_amount_cents
        ? formatRecurring(pricing_amount_cents, currency, 'year')
        : 'Paid / year'
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


/**
 * The largest membership amount the form will accept, in cents.
 *
 * ``spaces.pricing_amount_cents`` is a PostgreSQL ``INTEGER``, so the
 * hard ceiling is 2,147,483,647 cents. This sits well below it: a
 * Collective membership priced above a million dollars is a typo, and
 * catching it here turns a database error into a sentence.
 */
export const MEMBERSHIP_AMOUNT_MAX_CENTS = 99_999_999

/**
 * A typed membership amount, as integer cents.
 *
 * Why this is a function rather than four lines in the form
 * ----------------------------------------------------------
 *
 * The input is where a creator says what their work costs, and it had
 * two faults that only a parser can fix together. ``step="1"`` meant
 * the browser refused "5.99" outright, offering 5 or 6; and the form
 * re-read a stored amount with ``Math.round(cents / 100)``, so a price
 * with cents came back as a whole dollar and the next save wrote that
 * rounded figure to the database. Fixing only the first would have made
 * the second worse — decimals could be entered, then silently lost on
 * the next visit.
 *
 * So parsing, validation and the rounding rule live in one place with
 * tests, and the form asks this function rather than deciding for
 * itself.
 *
 * ``Math.round`` is doing real work: ``parseFloat('5.99') * 100`` is
 * 598.9999999999999 in binary floating point, and truncating it would
 * store A$5.98. Rounding is what makes the stored integer match what
 * the creator typed.
 *
 * An empty field is not an error — it means "no amount set", which is
 * how a creator clears a price. The caller decides whether that is
 * acceptable for the pricing type it is saving.
 */
export function parseMembershipAmountCents(input: string): {
  cents: number | null
  error: string | null
} {
  const raw = input.trim()
  if (!raw) return { cents: null, error: null }

  // A leading decimal point is what someone typing ".99" means, and
  // refusing it would be pedantry rather than validation.
  const normalised = raw.startsWith('.') ? `0${raw}` : raw

  // Digits, optionally followed by one or two decimal places. This is
  // also what rejects a negative (no leading minus), exponent notation
  // and a third decimal place — each of which would otherwise be
  // silently rounded into a price the creator did not choose.
  if (!/^\d+(\.\d{1,2})?$/.test(normalised)) {
    return {
      cents: null,
      error:
        'Enter an amount in dollars and cents, using numbers only — '
        + 'for example 29.50. Two decimal places at most.',
    }
  }

  const cents = Math.round(Number(normalised) * 100)
  if (cents === 0) {
    return {
      cents: null,
      error:
        'Enter an amount greater than zero, or clear the field to '
        + 'remove the price.',
    }
  }
  if (cents > MEMBERSHIP_AMOUNT_MAX_CENTS) {
    return {
      cents: null,
      error: 'That amount is too large. Enter up to 999,999.99.',
    }
  }
  return { cents, error: null }
}

/**
 * A stored amount, as the creator should see it in the input.
 *
 * Whole dollars stay whole ("49", not "49.00") because that is what a
 * creator typed; an amount with cents keeps both digits. The old
 * ``Math.round(cents / 100)`` lost the cents entirely, which is the
 * half of the defect that survived a reload.
 */
export function membershipAmountToInput(cents: number | null | undefined): string {
  if (cents == null || cents <= 0) return ''
  const dollars = cents / 100
  return Number.isInteger(dollars) ? String(dollars) : dollars.toFixed(2)
}
