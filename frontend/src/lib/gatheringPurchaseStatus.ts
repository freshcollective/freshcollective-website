/**
 * Which card on a Gathering page may claim the member's place.
 *
 * A Gathering can be reached by more than one route — its own ticket,
 * a Payment Option that bundles it, a Series pass, a caretaker adding
 * someone by hand. The page shows a card per route, and each card was
 * reading one shared value, ``my_booking_status``, to decide whether
 * *it* had been bought.
 *
 * That value answers a different question. It says a place exists, not
 * what produced it. So a member part-way through an instalment checkout
 * for a bundle saw "Payment in progress — Continue checkout" on the
 * Individual ticket card, for a purchase they had never begun; and once
 * the plan completed, the same card read "Ticket purchased".
 *
 * The rule here is simply that a card may speak for a place only when
 * the place came from that card's arrangement. Everything else about
 * the member's place — that it exists, that it is confirmed — stays
 * visible, because it is true and useful; it is just no longer
 * attributed to whichever card happened to be rendering.
 *
 * Pure, and imported with a relative ``.ts`` path by its test, so this
 * module must not use the ``@/`` alias — the bare node test runner
 * cannot resolve a tsconfig path.
 */

export type BookingStatus =
  | 'confirmed'
  | 'cancelled'
  | 'pending_payment'
  | null

export interface BookingOriginLike {
  kind:
    | 'direct_ticket'
    | 'payment_option'
    | 'series_pass'
    | 'creator_manual'
    | 'other'
  payment_option_id?: string | null
  payment_option_name?: string | null
}

/**
 * What the standalone-ticket card may say.
 *
 * ``covered`` and ``held_elsewhere`` are the two states that did not
 * exist before: a place this card did not sell. Both suppress the buy
 * button, because a second purchase would be a second payment for one
 * seat — §6E.
 */
export type TicketCardState =
  | 'purchased'        // bought here
  | 'pending'          // being bought here, right now
  | 'covered'          // a confirmed place from somewhere else
  | 'held_elsewhere'   // a place being held by another arrangement
  | 'available'        // no place

/**
 * An origin of ``null`` means the server did not say.
 *
 * Treated as "this card's own", which is what every pre-Stage-4B
 * client assumed and is right for the overwhelmingly common case: a
 * Gathering with no Payment Options has only one way in. A page that
 * does offer Options gets the field, so the ambiguity does not arise
 * where it would matter.
 */
function isOwnDirectTicket(origin: BookingOriginLike | null | undefined) {
  return !origin || origin.kind === 'direct_ticket'
}

export function ticketCardState(
  status: BookingStatus,
  origin: BookingOriginLike | null | undefined,
): TicketCardState {
  if (status === 'confirmed') {
    return isOwnDirectTicket(origin) ? 'purchased' : 'covered'
  }
  if (status === 'pending_payment') {
    return isOwnDirectTicket(origin) ? 'pending' : 'held_elsewhere'
  }
  // 'cancelled' and null are both "no current place". A cancelled
  // booking is history, and the member may buy again.
  return 'available'
}

/** True when the ticket card must not offer a purchase. */
export function ticketCardBlocksPurchase(state: TicketCardState): boolean {
  return state !== 'available'
}

/**
 * What one Payment Option card may say about the member's place.
 *
 * ``null`` for every card but the one that earned it, which is the
 * half of the fix that stops the status appearing in several places at
 * once.
 */
export function optionCardState(
  status: BookingStatus,
  origin: BookingOriginLike | null | undefined,
  paymentOptionId: string | null | undefined,
): 'purchased' | 'pending' | null {
  if (!origin || origin.kind !== 'payment_option') return null
  if (!paymentOptionId || !origin.payment_option_id) return null
  if (origin.payment_option_id !== paymentOptionId) return null
  if (status === 'confirmed') return 'purchased'
  if (status === 'pending_payment') return 'pending'
  return null
}

/**
 * "Included with Test Gathering Experience", or nothing.
 *
 * Only a named Payment Option and a Series pass can say where a place
 * came from in words a member recognises. A caretaker-added place is
 * deliberately silent: "Added by the Creator" is a fact about
 * administration, not something the member needs on a ticket card, and
 * "Complimentary" would be a guess about why.
 */
export function coveredByLabel(
  origin: BookingOriginLike | null | undefined,
): string | null {
  if (!origin) return null
  if (origin.kind === 'payment_option') {
    const name = (origin.payment_option_name ?? '').trim()
    return name ? `Included with ${name}` : null
  }
  if (origin.kind === 'series_pass') return 'Included with your Series pass'
  return null
}

/**
 * The heading for a place this card did not sell.
 *
 * Deliberately the same words whatever the origin — the member's
 * question is "am I going?", and the answer does not change with the
 * paperwork. ``coveredByLabel`` adds the provenance underneath, when
 * there is any worth stating.
 */
export function coveredHeading(state: TicketCardState): string | null {
  if (state === 'covered') return 'Your place is confirmed'
  if (state === 'held_elsewhere') return 'Your place is being held'
  return null
}

/**
 * The member's Payment Option status as plain data.
 *
 * ``optionCardState`` is the rule; this is the shape that can cross a
 * server/client boundary. The Gathering page is a server component and
 * the cards are client components, so the answer has to travel as
 * values — a predicate function would type-check and then throw at
 * runtime ("Functions cannot be passed directly to Client
 * Components").
 *
 * Carrying the id rather than a per-card verdict keeps the single
 * authoritative answer in one place: each card still compares against
 * its own Option, which is what stops the status appearing on all of
 * them at once.
 */
export interface ViewerOptionStatus {
  paymentOptionId: string
  state: 'purchased' | 'pending'
}

export function viewerOptionStatus(
  status: BookingStatus,
  origin: BookingOriginLike | null | undefined,
): ViewerOptionStatus | null {
  const id = origin?.payment_option_id
  if (!id) return null
  const state = optionCardState(status, origin, id)
  return state ? { paymentOptionId: id, state } : null
}
