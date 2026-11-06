/**
 * Stage 1B.1 — how a creator reads their own purchase arrangements.
 *
 * Display only. Every figure in here arrives from the backend's
 * ``GET /api/creator/spaces/{slug}/purchase-preview/{kind}/{id}``,
 * which derives it from the Stage 1A resolver. This module never
 * multiplies an instalment by a count, never chooses between two
 * prices, and never decides whether something can be purchased — a
 * surface that re-decided any of those would be the second opinion the
 * whole staged rebuild exists to remove.
 *
 * What it does own is *wording*, which is why it lives in ``lib``
 * rather than in the components: copy for a payment arrangement is
 * worth testing against the real reason codes the API can emit, and
 * two editors render it.
 *
 * Money and schedule phrasing come from ``paymentPlan.ts`` — the same
 * helpers the member-facing joining door and Series sidebar use. A
 * creator should read their price in the words their members read it
 * in, and there should be one implementation of "3 weekly payments of
 * $33".
 */

import {
  formatMoney,
  scheduleShortDescription,
  scheduleTotalLine,
} from './paymentPlan.ts'

// ---------------------------------------------------------------------------
// The API shape
// ---------------------------------------------------------------------------

export type PreviewSource = 'direct' | 'payment_option'
export type PreviewKind = 'pathway' | 'gathering'

export interface PreviewIncluded {
  kind: string
  title: string | null
}

export interface PreviewArrangement {
  source: PreviewSource
  name: string
  schedule_name: string | null
  schedule_type: string
  currency: string
  total_amount_cents: number | null
  /** What actually leaves the member's account first. For an instalment
   *  plan this is the first instalment, because that is what Stripe's
   *  subscription price charges. */
  upfront_amount_cents: number | null
  /** A deposit configured on the schedule that no billing code
   *  collects. Never the first charge — see `arrangementUpfrontWarning`. */
  unsupported_upfront_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  is_bundle: boolean
  is_free: boolean
  included: PreviewIncluded[]
  /** Present only for a Payment Option arrangement — the preview links
   *  to its editor. A direct price has no Option behind it. */
  payment_option_id: string | null
  /** After the live-platform overlay: what a member could complete. */
  available_for_new_purchase: boolean
  unavailable_reason: string | null
  /** Before the overlay: whether the creator's configuration is done. */
  configured_available: boolean
  /** Configuration complete, platform not selling it yet. */
  blocked_by_platform: boolean
  is_historical_source: boolean
}

export interface PurchasePreview {
  experience_kind: PreviewKind
  experience_id: string
  title: string | null
  access_type: string | null
  has_purchasable_arrangement: boolean
  arrangements: PreviewArrangement[]
}

// ---------------------------------------------------------------------------
// Names
// ---------------------------------------------------------------------------

/** What to call this arrangement in the list.
 *
 * A direct price is "the individual purchase" rather than the
 * experience's own title — the title is already the page heading, and
 * repeating it says nothing about how the money moves. */
export function arrangementTitle(
  arrangement: PreviewArrangement,
  kind: PreviewKind,
): string {
  if (arrangement.source === 'direct') {
    return kind === 'gathering' ? 'Individual ticket' : 'Individual purchase'
  }
  return arrangement.name
}

/** The payment line: "$49 once" · "3 weekly payments of $33".
 *
 * Option schedules go through the shared member formatter untouched.
 * A direct price has no schedule row, so it is phrased here in the
 * same shape that formatter gives a pay-in-full schedule. */
export function arrangementPaymentLine(
  arrangement: PreviewArrangement,
): string {
  if (arrangement.source === 'direct') {
    if (arrangement.total_amount_cents == null) return 'No price set'
    if (arrangement.total_amount_cents === 0) return 'Free'
    return `${formatMoney(
      arrangement.total_amount_cents,
      arrangement.currency,
    )} once`
  }
  return scheduleShortDescription(arrangement)
}

/** "$99 total", for an instalment plan only — so a creator never has
 *  to do the multiplication. Null for everything else, where the
 *  payment line already carries the figure. */
export function arrangementTotalLine(
  arrangement: PreviewArrangement,
): string | null {
  if (arrangement.source === 'direct') return null
  return scheduleTotalLine(arrangement)
}

/** A configured deposit that nothing will collect.
 *
 * `PaymentOptionSchedule.upfront_amount_cents` is settable in three
 * creator editors and stored, and no billing code reads it: Stripe's
 * subscription price is built from the instalment amount at a fixed
 * interval, with no separate deposit charge anywhere in the plan
 * lifecycle. A creator who set one believes they are collecting a
 * deposit and are not.
 *
 * So the figure is never presented as the first charge — it is named
 * as a discrepancy, because silently dropping it would leave the
 * creator believing the deposit works, and showing it as real would
 * repeat their mistake back to them as a fact. */
export function arrangementUpfrontWarning(
  arrangement: PreviewArrangement,
): string | null {
  const configured = arrangement.unsupported_upfront_amount_cents
  if (configured == null) return null
  const first = arrangement.installment_amount_cents
  const firstText =
    first != null ? formatMoney(first, arrangement.currency) : 'the first instalment'
  return (
    `This arrangement has a ${formatMoney(configured, arrangement.currency)} ` +
    `upfront amount set, but it is not collected. Members are charged ` +
    `${firstText} first, then the rest of the plan. Remove the upfront ` +
    `amount, or ask us about deposits.`
  )
}

const INCLUDED_KIND_LABELS: Record<string, string> = {
  pathway: 'Pathway',
  event_series: 'Gathering Series',
  gathering: 'Gathering',
  offering: 'Offering',
}

/** Member-facing name for a grant kind. ``event_series`` is internal
 *  vocabulary and must never reach a creator. */
export function includedKindLabel(kind: string): string {
  return INCLUDED_KIND_LABELS[kind] ?? 'Experience'
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export type StatusTone = 'available' | 'draft' | 'pending' | 'attention' | 'archived'

export interface ArrangementStatus {
  label: string
  tone: StatusTone
}

/**
 * The badge. Four distinct states, because they call for four
 * different responses from the creator:
 *
 *   available  — nothing to do
 *   draft      — publish it (the creator's move)
 *   archived   — deliberately retired; existing access preserved
 *   pending    — set up correctly, platform not selling it yet (ask us)
 *   attention  — the configuration is incomplete or wrong (fix it)
 *
 * Collapsing "pending" into "attention" would accuse a creator of a
 * mistake they did not make; collapsing it into "available" would
 * promise a sale that cannot happen.
 */
export function arrangementStatus(
  arrangement: PreviewArrangement,
): ArrangementStatus {
  if (arrangement.available_for_new_purchase) {
    return { label: 'Available', tone: 'available' }
  }
  const reason = arrangement.unavailable_reason
  if (reason === 'option_archived') {
    return { label: 'Archived', tone: 'archived' }
  }
  if (reason === 'option_not_published' || reason === 'schedule_not_published') {
    return { label: 'Draft', tone: 'draft' }
  }
  if (
    reason === 'price_not_set' ||
    reason === 'price_invalid' ||
    reason === 'schedule_invalid'
  ) {
    return { label: 'Needs attention', tone: 'attention' }
  }
  return { label: 'Not purchasable yet', tone: 'pending' }
}

/**
 * Why it isn't available, in a sentence a creator can act on — or
 * understand that they cannot.
 *
 * Every reason the API can emit is covered. The fallback exists so an
 * unrecognised reason still reads as English rather than as a code,
 * and the cross-boundary test in ``purchasePreview.test.ts`` asserts
 * the set is closed against the backend constants.
 */
export function arrangementExplanation(
  arrangement: PreviewArrangement,
  kind: PreviewKind,
): string | null {
  if (arrangement.available_for_new_purchase) return null
  const experience = kind === 'gathering' ? 'Gathering' : 'Pathway'

  switch (arrangement.unavailable_reason) {
    case 'option_not_published':
      return 'This Payment Option is still a draft. Publish it to start selling through it.'
    case 'option_archived':
      return 'This Payment Option is archived, so it is no longer offered to new members. Anyone who bought through it keeps their access.'
    case 'schedule_not_published':
      return 'This payment schedule is still a draft. Publish it in Payment Options.'
    case 'unsupported_inclusion':
      return 'Individual Gathering payments through Payment Options are coming soon. Members cannot purchase through this option yet.'
    case 'instalments_not_enabled':
      return 'Payment plans are not switched on here yet, so members can only pay in full.'
    case 'schedule_invalid':
      return 'This payment schedule is missing something it needs. Check its amounts in Payment Options.'
    case 'schedule_type_unsupported':
      return 'This kind of payment schedule cannot be sold through checkout.'
    case 'price_not_set':
      return 'No price has been set yet.'
    case 'price_invalid':
      return 'The amount saved here is not a valid price.'
    case 'experience_unavailable':
      return kind === 'gathering'
        ? 'This Gathering is not published yet, so nobody can book it.'
        : 'This Pathway is not active yet, so nobody can purchase it.'
    case 'pathway_requires_payment_option':
      return 'This Pathway now sells through Payment Options, so its own price is no longer offered at checkout. Members purchase through the Options listed here.'
    case 'creator_plan_not_configured':
      return 'Your Collective does not have a Fresh Collective plan assigned yet, so paid checkout is unavailable. Contact us and we will sort it out — your setup here is fine.'
    case 'creator_plan_forbids_paid_offers':
      return 'Your current Fresh Collective plan does not include paid offers. Upgrading to Creator or higher enables paid checkout.'
    case 'gathering_sales_disabled':
      // Deliberately the same explanation the Gathering editor already
      // gives beside the ticket price. One fact, one wording.
      return 'Ticket sales are switched off on this environment, so this Gathering can be set up with a price but cannot be bought yet.'
    default:
      return `Members cannot purchase this ${experience} through this arrangement right now.`
  }
}

// ---------------------------------------------------------------------------
// Empty and access states
// ---------------------------------------------------------------------------

/**
 * What to say when there is nothing to buy.
 *
 * An empty list is usually correct rather than broken — a free or
 * members-only experience has no purchase arrangements by design, and
 * showing "nothing configured" there would invent a problem. The one
 * genuine gap is a Pathway set to Payment Option access that no Option
 * includes: then nobody can reach it, and that is worth saying.
 */
export function accessExplanation(
  preview: PurchasePreview,
): { text: string; isGap: boolean } {
  const { access_type: access, experience_kind: kind } = preview

  if (kind === 'pathway') {
    if (access === 'free') {
      return {
        text: 'This Pathway is public — anyone can find and begin it. There is nothing to purchase.',
        isGap: false,
      }
    }
    if (access === 'included') {
      return {
        text: 'This Pathway is included for members of your Collective. There is nothing to purchase.',
        isGap: false,
      }
    }
    if (access === 'included_with_offer') {
      return {
        text: 'No Payment Option includes this Pathway yet, so no one can reach it. Add it to an Option in Payment Options.',
        isGap: true,
      }
    }
    if (access === 'subscription') {
      // A legacy per-Pathway subscription. Nothing sells one — the
      // checkout door accepts only one-time Pathway access — so the
      // resolver emits no arrangement for it. Saying "nothing is set
      // up" would be wrong: something is set up, and it is retired.
      return {
        text: 'This Pathway is on a legacy monthly subscription, which is no longer sold. Ongoing access is set up through Payment Options.',
        isGap: true,
      }
    }
    return {
      text: 'No purchase arrangement is set up for this Pathway yet.',
      isGap: true,
    }
  }

  if (access === 'paid_separately') {
    return {
      text: 'This Gathering is ticketed, but no ticket price is set yet.',
      isGap: true,
    }
  }
  if (access === 'invitation_only') {
    return {
      text: 'This Gathering is invitation only — you add attendees yourself. There is nothing to purchase.',
      isGap: false,
    }
  }
  if (access === 'included_with_pathway') {
    return {
      text: 'This Gathering is included for members on a particular Pathway. There is nothing to purchase here.',
      isGap: false,
    }
  }
  if (access === 'included_with_series') {
    return {
      text: 'This Gathering is included with a Series pass. Members buy the pass, not this Gathering.',
      isGap: false,
    }
  }
  return {
    text: 'This Gathering is included for members of your Collective. There is nothing to purchase.',
    isGap: false,
  }
}

// ---------------------------------------------------------------------------
// Grouping
// ---------------------------------------------------------------------------

export interface GroupedArrangements {
  /** The experience's own price, when it has one. At most one. */
  direct: PreviewArrangement | null
  /** Payment Option arrangements, in the order the API returned them —
   *  the creator's own Option order, then schedule order. */
  options: PreviewArrangement[]
}

export function groupArrangements(
  preview: PurchasePreview,
): GroupedArrangements {
  return {
    direct: preview.arrangements.find((a) => a.source === 'direct') ?? null,
    options: preview.arrangements.filter((a) => a.source === 'payment_option'),
  }
}

/** A stable React key. Built from the Option id and the arrangement's
 *  position rather than from an arrangement identifier, which the
 *  read-only API deliberately does not return. */
export function arrangementKey(
  arrangement: PreviewArrangement,
  index: number,
): string {
  return `${arrangement.payment_option_id ?? 'direct'}:${index}`
}

export interface OptionGroup {
  payment_option_id: string
  name: string
  /** Every schedule arrangement for this Option, in the creator's own
   *  order. Two schedules on one Option are two arrangements with two
   *  prices — the distinction the whole stage rests on — so they are
   *  listed, never merged into one figure. */
  schedules: PreviewArrangement[]
  /** What this Option grants beyond the experience being viewed. */
  included: PreviewIncluded[]
  isBundle: boolean
}

/**
 * Payment Option arrangements, gathered under their Option.
 *
 * The API returns one row per schedule, which is right for pricing and
 * wrong for reading: a creator with "Pay in full" and "Payment plan"
 * on one bundle should see one bundle with two ways to pay, not the
 * bundle's name twice.
 */
export function groupByOption(preview: PurchasePreview): OptionGroup[] {
  const order: string[] = []
  const groups = new Map<string, OptionGroup>()

  for (const arrangement of preview.arrangements) {
    if (arrangement.source !== 'payment_option') continue
    const id = arrangement.payment_option_id
    if (!id) continue
    let group = groups.get(id)
    if (!group) {
      group = {
        payment_option_id: id,
        name: arrangement.name,
        schedules: [],
        included: arrangement.included,
        isBundle: arrangement.is_bundle,
      }
      groups.set(id, group)
      order.push(id)
    }
    group.schedules.push(arrangement)
  }

  return order.map((id) => groups.get(id)!)
}

/** Everything this Option grants apart from the experience being
 *  viewed — "also includes". Filtering the experience itself out of
 *  its own bundle list keeps the sentence useful. */
export function alsoIncluded(
  group: OptionGroup,
  preview: PurchasePreview,
): PreviewIncluded[] {
  return group.included.filter(
    (inc) => !(inc.kind === preview.experience_kind && inc.title === preview.title),
  )
}
