/**
 * What leaving a Collective means, in words.
 *
 * Kept out of the component for the usual reason — it is the part worth
 * testing — but also because the wording here is load-bearing. Every
 * line is a claim about what the backend will actually do, and three of
 * them differ from the obvious phrasing because the obvious phrasing
 * would not be true.
 *
 * **"You can rejoin later" is said, and now it is true.** It was not
 * when this was first written: ``join_space`` returned a false
 * ``already_member`` for a ``removed`` row, and a creator re-add
 * collided with the uniqueness constraint, so there was no way back to
 * promise. Removal provenance (migration 166) fixed both — a departure
 * records itself as ``voluntary``, and
 * ``membership_grant.may_rejoin`` lets exactly that case back through
 * the ordinary Join flow.
 *
 * "subject to its membership requirements" is doing real work in that
 * sentence rather than hedging: rejoining re-runs the Collective's
 * join policy and its member allowance, so a Collective that has since
 * become purchase-required, or filled up, will say so. What it does
 * not do is restore anything that was revoked on the way out.
 *
 * **Paid things are described as kept, not as lost.** Leaving makes no
 * payment change of any kind: no pass is cancelled, no booking is
 * cancelled, no refund is issued, nothing is said to Stripe. The lines
 * below say so, because a member who assumes "leaving = losing what I
 * paid for" would be wrong in both directions — they keep the pass, and
 * they also keep the charge.
 *
 * **``included_with_offer`` is called out separately.** It is the one
 * access type that is paid for but still gated on active membership
 * (see ``spaces.routes._check_pathway_access``), so it is the one place
 * where leaving really does close something bought. It gets its own
 * line rather than being folded into the general warning.
 */

export interface DeparturePreview {
  can_leave: boolean
  blocked_reason: string | null
  live_payment_plans: number
  active_passes: number
  unused_credits: number
  future_bookings: number
  purchased_future_bookings: number
  purchased_pathways: number
  membership_gated_paid_pathways: number
  offerings_retained: number
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many
}

/**
 * Why this member may not leave, or ``null`` when they may.
 *
 * Mirrors the server's ``blocked_reason`` values. An unrecognised
 * reason still produces a message rather than an empty dialog — a new
 * refusal on the backend should read as "not right now", never as a
 * confirm button for a departure that will fail.
 */
export function departureBlockedMessage(
  preview: DeparturePreview,
): string | null {
  if (preview.can_leave) return null

  switch (preview.blocked_reason) {
    case 'live_payment_plan':
      return (
        preview.live_payment_plans === 1
          ? 'You have a payment plan in progress for this Collective. '
          : 'You have payment plans in progress for this Collective. '
      ) + 'Please contact the Collective’s creator to settle or cancel it '
        + 'before leaving, so you are not charged for access you no '
        + 'longer have.'
    case 'caretaker_role':
      return (
        'You help run this Collective, so you cannot leave it as a '
        + 'member. Stepping back is handled in Creator Studio.'
      )
    case 'auto_managed_collective':
      return (
        'Membership of this Collective is managed automatically from '
        + 'your Fresh Collective account, so it cannot be left here.'
      )
    case 'not_a_member':
      return 'You are not currently a member of this Collective.'
    default:
      return 'This Collective cannot be left right now.'
  }
}

/**
 * The paragraphs the confirmation dialog shows, in order.
 *
 * Always leads with what is lost and ends with what is kept, so the
 * last thing read is the reassurance rather than the warning.
 */
export function departureConsequenceLines(
  preview: DeparturePreview,
): string[] {
  const lines: string[] = [
    'You’ll lose access to this Collective’s Pathways, Gatherings and '
    + 'member-only community spaces.',
  ]

  const gated = preview.membership_gated_paid_pathways
  if (gated > 0) {
    lines.push(
      `${gated} ${plural(gated, 'Pathway', 'Pathways')} you unlocked with a `
      + `paid offer ${plural(gated, 'needs', 'need')} active membership, so `
      + `leaving will close ${plural(gated, 'it', 'them')}. Nothing is `
      + 'refunded.',
    )
  }

  if (preview.purchased_pathways > 0) {
    const n = preview.purchased_pathways
    lines.push(
      `${n} ${plural(n, 'Pathway', 'Pathways')} you bought outright will stay `
      + `available to you.`,
    )
  }

  if (preview.active_passes > 0) {
    const n = preview.active_passes
    const credits =
      preview.unused_credits > 0
        ? ` ${preview.unused_credits} unused `
          + `${plural(preview.unused_credits, 'credit', 'credits')} `
          + 'will stay on them.'
        : ''
    lines.push(
      `Your ${n} active ${plural(n, 'pass', 'passes')} here `
      + `${plural(n, 'is', 'are')} not cancelled and not refunded, but `
      + `you’ll need to be a member again to use ${plural(n, 'it', 'them')}.`
      + credits,
    )
  }

  // Two groups, described differently, because they behave
  // differently. A reservation the member paid for stays reachable
  // after departure through the per-reservation exception in
  // ``spaces.retained_reservations``; one that came with membership
  // goes when membership does. Saying "you may no longer be able to
  // reach them" of both was true of neither.
  const paidBookings = preview.purchased_future_bookings
  const includedBookings = Math.max(
    0, preview.future_bookings - paidBookings,
  )

  if (paidBookings > 0) {
    lines.push(
      `Your ${paidBookings} paid Gathering `
      + `${plural(paidBookings, 'reservation', 'reservations')} `
      + `${plural(paidBookings, 'stays', 'stay')} yours — not cancelled and `
      + `not refunded. You’ll still be able to see `
      + `${plural(paidBookings, 'it', 'them')} and cancel from this page.`,
    )
  }

  if (includedBookings > 0) {
    lines.push(
      `${includedBookings} upcoming `
      + `${plural(includedBookings, 'booking', 'bookings')} that came with `
      + `membership will no longer be available to you.`,
    )
  }

  lines.push(
    preview.offerings_retained > 0
      ? `The ${preview.offerings_retained} `
        + `${plural(preview.offerings_retained, 'Offering', 'Offerings')} `
        + 'you’ve acquired will stay in Your Collection.'
      : 'Any Offerings you’ve already added to Your Collection will remain '
        + 'available to you.',
  )

  // Last: the way back. Phrased as a right with a condition, not a
  // promise — the condition is the Collective's own join policy and
  // allowance, both re-checked on rejoin. See the module docstring.
  lines.push(
    'You can rejoin this Collective later, subject to its membership '
    + 'requirements.',
  )

  return lines
}

/** Whether the Membership card should offer this at all. */
export function canOfferLeave(role: string): boolean {
  return role === 'learner'
}
