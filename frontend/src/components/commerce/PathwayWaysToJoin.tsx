'use client'

import { useState } from 'react'

import DiscountCodeField from '@/components/checkout/DiscountCodeField'
import ScheduleChoice from '@/components/commerce/ScheduleChoice'
import type { ViewerOptionStatus } from '@/lib/gatheringPurchaseStatus'
import { CheckoutButton } from '@/components/checkout/CheckoutButton'
import { formatMoneyCents } from '@/lib/formatMoney'
import {
  paletteHex,
  rgbaFromHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'
import type { WaysToJoinArrangement } from '@/types/platform'

/**
 * Stage 2C — every way to buy one Pathway, as a column of equal cards.
 *
 * Replaces a single headline price and a "See ways to join" link that
 * sent the member to another page to find out what the choices were.
 * A Pathway can be sold directly and through Payment Options at the
 * same time, so one price could only ever be part of the answer: with
 * a A$59 direct price beside a A$29 bundle, "From A$59" was wrong and
 * "From A$29" would have been wrong in the other direction. The fix is
 * not a better headline, it is showing the choices.
 *
 * Built to match the Gathering Series sidebar deliberately — same card
 * container, same type scale, and the same `ScheduleChoice` and
 * `PurchaseScheduleButton` components underneath, so an Option offered
 * on both surfaces is one commitment described one way. The Series
 * page itself is untouched.
 *
 * Equal treatment is the point, and it is structural rather than
 * cosmetic: both kinds of card get the same container, the same
 * heading, the same price prominence and the same button, and the
 * order is the resolver's (direct first, then the creator's own Option
 * order) rather than cheapest-first. Nothing is labelled recommended,
 * because the creator decides what to offer and the member decides
 * what to buy.
 *
 * Nothing here talks to the backend. The arrangements arrive already
 * resolved, already ordered and with the unavailable ones dropped, so
 * this file cannot invent a price or offer a route checkout would
 * refuse.
 */

export default function PathwayWaysToJoin({
  spaceSlug,
  pathwaySlug,
  pathwayId,
  arrangements,
  palette,
  isAuthenticated,
  heading = 'Ways to join',
  showHeading = true,
  returnBase,
  discountCodesEnabled = false,
  viewerOptionStatus = null,
}: {
  spaceSlug: string
  /** Only needed when the list can contain a direct card — a
   *  Gathering's individual ticket keeps its own booking control, so
   *  that surface passes neither of these. */
  pathwaySlug?: string
  pathwayId?: string
  arrangements: WaysToJoinArrangement[]
  palette?: CollectivePaletteMeta | null
  isAuthenticated: boolean
  heading?: string
  /** Set false when the surface already carries a Ways to join
   *  heading of its own and these cards sit under it alongside
   *  something else — the standalone Gathering page puts its
   *  individual ticket in the same list. */
  showHeading?: boolean
  /** Where Stripe returns the buyer. Defaults to the Pathway checkout
   *  page; a Gathering passes its own page, because that is where the
   *  purchase started and where the booking will show up. */
  returnBase?: string
  /** Stage 4 — whether this Collective's surface may offer a discount
   *  code. Resolved by the backend from UNIVERSAL_DISCOUNT_CODES_ENABLED
   *  and threaded down; nothing here decides it, and the default is off
   *  so a surface that has not been taught to pass it shows no code box
   *  rather than one the server refuses. */
  discountCodesEnabled?: boolean
  /** Stage 4B — the member's status, and which Option it belongs to.
   *
   *  Plain data rather than a predicate because the pages rendering
   *  this are server components and these cards are client components.
   *  Each card compares the id against its own, so the status lands on
   *  one arrangement — being shown against all of them was the bug.
   *  Omitted on surfaces that do not resolve it, where every card
   *  renders exactly as before. */
  viewerOptionStatus?: ViewerOptionStatus | null
}) {
  const primary = paletteHex('primary', palette ?? null) ?? '#0f766e'

  if (arrangements.length === 0) return null

  return (
    <div>
      {showHeading && (
        <p
          className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
          style={{ color: primary }}
        >
          {heading}
        </p>
      )}

      <ul className="space-y-3">
        {arrangements.map((a) => (
          <li
            key={
              a.source === 'direct'
                ? 'direct'
                : `option-${a.payment_option_id}`
            }
          >
            {a.source === 'direct' ? (
              <DirectCard
                pathwayId={pathwayId ?? ''}
                arrangement={a}
                palette={palette}
                isAuthenticated={isAuthenticated}
                accentHex={primary}
                discountCodesEnabled={discountCodesEnabled}
              />
            ) : (
              <OptionCard
                returnBase={
                  returnBase
                  ?? `/spaces/${spaceSlug}/pathways/${pathwaySlug}/checkout`
                }
                arrangement={a}
                palette={palette}
                discountCodesEnabled={discountCodesEnabled}
                viewerOptionStatus={viewerOptionStatus}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Shared container, so neither kind of card reads as the default. */
function cardStyle(primary: string) {
  return {
    borderColor: rgbaFromHex(primary, 0.14),
    background: rgbaFromHex(primary, 0.06),
  }
}

/**
 * One Ways to join card.
 *
 * Exported so a surface with an arrangement of its own can render it
 * with the same weight as the Options beside it, rather than
 * reproducing the container and drifting from it. The standalone
 * Gathering page uses this for its individual ticket: the ticket's own
 * purchase logic is untouched and simply sits inside.
 *
 * The tint is derived from the Collective's primary, so a card is
 * branded wherever it is used and falls back to the platform colour
 * only when a Collective has no palette.
 */
export function WaysToJoinCard({
  title, palette, children,
}: {
  title?: string
  palette?: CollectivePaletteMeta | null
  children: React.ReactNode
}) {
  const primary = paletteHex('primary', palette ?? null) ?? '#0f766e'
  return (
    <div className="rounded-2xl border p-4" style={cardStyle(primary)}>
      {title && (
        <h3 className="font-serif text-[16px] text-navy-900 break-words">
          {title}
        </h3>
      )}
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// The Pathway's own price
// ---------------------------------------------------------------------------

function DirectCard({
  pathwayId, arrangement, palette, isAuthenticated, accentHex,
  discountCodesEnabled,
}: {
  pathwayId: string
  arrangement: WaysToJoinArrangement
  palette?: CollectivePaletteMeta | null
  isAuthenticated: boolean
  accentHex: string
  discountCodesEnabled: boolean
}) {
  // Currency from the arrangement, never a literal — a Collective
  // selling in USD must read US$59, not $59.
  const price = formatMoneyCents(arrangement.price_cents, arrangement.currency)
  // Only ever a code. The amount is the server's business — see
  // ``DiscountCodeField``.
  const [discountCode, setDiscountCode] = useState<string | null>(null)

  return (
    <WaysToJoinCard title="Purchase this Pathway" palette={palette}>
      <div className="mt-3 mb-2">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[12px] font-medium text-navy-900">
            One-time payment
          </span>
          <span className="shrink-0 text-[13px] font-semibold text-navy-900">
            {price} once
          </span>
        </div>
        <p className="mt-0.5 text-[11px] text-slate-500">
          Access to this Pathway only.
        </p>
      </div>

      {/* Stage 4 — a Collective-wide code reaches this door too. The
          field prices it against the Pathway's own price, with no
          Payment Option named, which is what keeps a code scoped to one
          Option off a standalone purchase of this Pathway. */}
      {discountCodesEnabled && (
        <div className="mb-2">
          <DiscountCodeField
            target={{ kind: 'pathway', targetId: pathwayId }}
            onChange={setDiscountCode}
          />
        </div>
      )}

      <CheckoutButton
        pathwayId={pathwayId}
        label={`Purchase for ${price}`}
        isAuthenticated={isAuthenticated}
        appearance="card"
        accentHex={accentHex}
        discountCode={discountCode}
      />
    </WaysToJoinCard>
  )
}

// ---------------------------------------------------------------------------
// One Payment Option, with a row per schedule
// ---------------------------------------------------------------------------

function OptionCard({
  returnBase, arrangement, palette, discountCodesEnabled, viewerOptionStatus,
}: {
  returnBase: string
  arrangement: WaysToJoinArrangement
  palette?: CollectivePaletteMeta | null
  discountCodesEnabled: boolean
  viewerOptionStatus?: ViewerOptionStatus | null
}) {
  const optionName = arrangement.name ?? 'Payment option'
  // Stage 4B — this card's own status. Every other card resolves to
  // null, which is the point.
  const viewerStatus =
    viewerOptionStatus
    && arrangement.payment_option_id
    && viewerOptionStatus.paymentOptionId === arrangement.payment_option_id
      ? viewerOptionStatus.state
      : null

  // The Pathway being viewed leads the list and is implicit in the
  // card's context, so only the *rest* is worth printing — but it must
  // be printed, because a bundle that grants three Pathways must not
  // read as though it grants the one being looked at. Capped at three
  // so a large bundle cannot push the purchase button off the card;
  // the remainder is counted rather than silently dropped.
  const alsoIncludes = arrangement.included_titles.slice(1)
  const shown = alsoIncludes.slice(0, 3)
  const extra = alsoIncludes.length - shown.length

  return (
    <WaysToJoinCard title={optionName} palette={palette}>
      {arrangement.description && (
        <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">
          {arrangement.description}
        </p>
      )}

      {shown.length > 0 && (
        <p className="mt-2 text-[12px] leading-relaxed text-slate-600">
          <span className="text-slate-500">Also includes: </span>
          {shown.join(', ')}
          {extra > 0 && ` and ${extra} more`}
        </p>
      )}

      {viewerStatus === 'purchased' && (
        <div
          className="mt-3 rounded-xl px-3 py-2"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
            border: '1px solid var(--fc-accent-line, rgba(56,160,158,0.15))',
          }}
        >
          <p
            className="text-[13px] font-semibold"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            You&rsquo;ve purchased this
          </p>
        </div>
      )}

      {viewerStatus === 'pending' && (
        <div
          className="mt-3 rounded-xl px-3 py-2"
          style={{ background: 'rgba(212,176,72,0.10)', border: '1px solid rgba(212,176,72,0.30)' }}
        >
          <p className="text-[13px] font-semibold" style={{ color: '#8A6A15' }}>
            Payment in progress
          </p>
          <p className="mt-1 text-[12px] leading-relaxed" style={{ color: '#8A6A15' }}>
            Complete your payment to confirm your place. Use the button
            below to continue checkout &mdash; it returns you to the
            same payment page rather than opening a second one.
          </p>
        </div>
      )}

      <div className="mt-3 space-y-3">
        {arrangement.schedules.map((s, i) => (
          <ScheduleChoice
            key={s.id}
            optionName={optionName}
            schedule={s}
            paymentOptionId={arrangement.payment_option_id ?? ''}
            returnBase={returnBase}
            palette={palette}
            withDivider={i > 0}
            discountCodesEnabled={discountCodesEnabled}
            ctaLabel={
              // "Join with X" is the Series' wording and is wrong here
              // — a Pathway is bought, not joined. The schedule's own
              // amount is already on the row above, so the label does
              // not repeat it.
              s.schedule_type === 'recurring_installments'
                ? `Start payment plan · ${optionName}`
                : `Purchase ${optionName}`
            }
          />
        ))}
      </div>
    </WaysToJoinCard>
  )
}
