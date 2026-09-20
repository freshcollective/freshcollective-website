'use client'

import Link from 'next/link'

import ScheduleChoice from '@/components/commerce/ScheduleChoice'
import { scheduleShortDescription } from '@/lib/paymentPlan'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import type { JoiningOption } from '@/types/platform'

/**
 * Ways into a Collective that cannot be joined for free.
 *
 * Each option renders the same schedule choices the Gathering Series
 * sidebar shows, through the same components, into the same
 * ``POST /api/checkout``. The joining door is another entry point into
 * an existing purchase, not a second commerce flow: buying a term here
 * grants exactly what that Payment Option grants, and brings the buyer
 * into the Collective on the way.
 *
 * Prices come from the Option's published, checkoutable schedules —
 * never from its ``override_total_cents`` / ``calculated_total_cents``,
 * which are authoring fields and are routinely empty on real Options.
 * The first version of this file read those and showed "No price set"
 * on three perfectly healthy $180–$378 options.
 */

function priceSummary(option: JoiningOption): string | null {
  const buyable = (option.schedules ?? []).filter((s) => s.is_member_checkoutable)
  if (buyable.length === 0) return null
  return buyable.map(scheduleShortDescription).filter(Boolean).join(' or ')
}

export default function JoiningDoors({
  slug,
  options,
  isLoggedIn,
  isMember = false,
  palette = null,
}: {
  slug: string
  options: JoiningOption[]
  isLoggedIn: boolean
  /** A member reaching this page should not be told to join again;
   *  the same options remain purchasable to them. */
  isMember?: boolean
  palette?: CollectivePaletteMeta | null
}) {
  // No doors is a real answer, never a reason to fall back to a free
  // join. The creator has either not nominated an option yet or has
  // unpublished the ones they had; a visitor should be told plainly
  // rather than shown a button that cannot work.
  if (options.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-center">
        <p className="text-[13px] font-medium text-slate-600">
          Not open for new members right now
        </p>
        <p className="mt-1 text-[12px] text-slate-500">
          Check back soon, or get in touch with the collective.
        </p>
      </div>
    )
  }

  const returnBase = `/spaces/${slug}/about`

  // Signed out: show the real commitment before asking for an
  // account. Sending someone to a login screen that promised "join"
  // and then revealing a price is the wrong order to learn it in.
  if (!isLoggedIn) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-[13px] leading-relaxed text-black">
          Membership comes with your first purchase — there is no separate
          joining step.
        </p>
        <ul className="space-y-2 p-0">
          {options.map((option) => {
            const summary = priceSummary(option)
            return (
              <li
                key={option.id}
                className="rounded-xl border border-slate-200 px-3.5 py-2.5"
              >
                <p className="text-[13px] font-semibold text-navy-900">
                  {option.name}
                </p>
                {summary && (
                  <p className="mt-0.5 text-[12.5px] text-black">{summary}</p>
                )}
              </li>
            )
          })}
        </ul>
        <Link
          href={`/login?next=/spaces/${slug}/about`}
          className="rounded-xl px-4 py-2.5 text-center text-[13px] font-semibold text-white"
          style={{ background: 'var(--fc-accent, #38A09E)' }}
        >
          Sign in to continue
        </Link>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {!isMember && (
        <p className="text-[13px] leading-relaxed text-black">
          Membership comes with your purchase — there is no separate joining
          step.
        </p>
      )}
      {options.map((option) => {
        const buyable = (option.schedules ?? []).filter(
          (s) => s.is_member_checkoutable,
        )
        if (buyable.length === 0) return null
        return (
          <div key={option.id}>
            <p className="text-[13.5px] font-semibold text-navy-900">
              {option.name}
            </p>
            {option.buyer_note && (
              <p className="mt-0.5 text-[12.5px] leading-snug text-black">
                {option.buyer_note}
              </p>
            )}
            <div className="mt-3 space-y-3">
              {buyable.map((schedule, i) => (
                <ScheduleChoice
                  key={schedule.id}
                  optionName={option.name}
                  schedule={schedule}
                  paymentOptionId={option.id}
                  returnBase={returnBase}
                  palette={palette}
                  withDivider={i > 0}
                  // A member is buying, not joining — they are already in.
                  ctaLabel={isMember
                    ? (schedule.schedule_type === 'recurring_installments'
                        ? `Start payment plan · ${option.name}`
                        : `Purchase ${option.name}`)
                    : undefined}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
