'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { CheckoutButton } from './CheckoutButton'
import type {
  PaymentOptionSummary,
  PaymentOptionScheduleSummary,
} from '@/types/platform'
import {
  cadenceAdjective,
  formatMoney,
  scheduleCtaLabel,
  scheduleDisclosureCopy,
  scheduleKindLabel,
  scheduleShortDescription,
  scheduleTotalLine,
} from '@/lib/paymentPlan'

/**
 * FIP4A — member-facing payment option + schedule selector.
 *
 * Renders the published Payment Options on a Pathway (or other
 * grant target) and lets the member choose:
 *
 *   1. which Payment Option they want (only surfaced if it has at
 *      least one member-checkoutable schedule)
 *   2. within that Option, which payment schedule — "Pay in full"
 *      vs "Payment plan" (finite instalments)
 *
 * The `is_member_checkoutable` flag on each schedule is the
 * single source of truth — the backend decides, the frontend never
 * re-derives. Recurring instalment schedules only appear as
 * choosable once the backend gate is on (see
 * `FINITE_PLAN_MEMBER_CHECKOUT_ENABLED` in the config doc).
 */

function AnonCheckoutCTAs({
  pathname,
  selectedOptionId,
  effectiveScheduleId,
}: {
  pathname: string
  selectedOptionId: string | null
  effectiveScheduleId: string | null
}) {
  const params = new URLSearchParams()
  if (selectedOptionId) params.set('payment_option_id', selectedOptionId)
  if (effectiveScheduleId)
    params.set('payment_option_schedule_id', effectiveScheduleId)
  const qs = params.toString()
  const checkoutUrl = pathname + (qs ? `?${qs}` : '')
  const encodedNext = encodeURIComponent(checkoutUrl)

  return (
    <div className="space-y-2">
      <Link
        href={`/signup?next=${encodedNext}`}
        className="block w-full rounded-full px-5 py-3 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
        style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
      >
        Create account to continue
      </Link>
      <Link
        href={`/login?next=${encodedNext}`}
        className="block w-full rounded-full border border-slate-200 px-5 py-2.5 text-center text-[14px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
      >
        Already have an account? Log in
      </Link>
      <p className="pt-1 text-center text-[11px] leading-relaxed text-black">
        Create a free account so we can save your access and connect your
        payment to your profile.
      </p>
    </div>
  )
}

interface Props {
  pathwayId: string
  options: PaymentOptionSummary[]
  isAuthenticated?: boolean
  initialOptionId?: string
  initialScheduleId?: string | null
}

export function PaymentOptionSelector({
  pathwayId,
  options,
  isAuthenticated = true,
  initialOptionId,
  initialScheduleId,
}: Props) {
  const pathname = usePathname()

  // Only surface options with at least one member-checkoutable
  // schedule — matches the SidebarWaysToJoin filter on the Series
  // side so members see the same choices in both places.
  const purchasableOptions = options.filter((o) =>
    o.schedules.some((s) => s.is_member_checkoutable),
  )

  const [selectedOptionId, setSelectedOptionId] = useState<string>(
    initialOptionId ?? purchasableOptions[0]?.id ?? options[0]?.id ?? '',
  )
  const [selectedScheduleId, setSelectedScheduleId] = useState<string | null>(
    initialScheduleId ?? null,
  )

  const selectedOption = options.find((o) => o.id === selectedOptionId)
  const checkoutableSchedules: PaymentOptionScheduleSummary[] = (
    selectedOption?.schedules ?? []
  ).filter((s) => s.is_member_checkoutable)
  const hasSchedules = checkoutableSchedules.length > 0

  function handleOptionSelect(id: string) {
    setSelectedOptionId(id)
    setSelectedScheduleId(null)
  }

  // Default to first checkoutable schedule when none explicitly chosen.
  const effectiveScheduleId = hasSchedules
    ? selectedScheduleId ?? checkoutableSchedules[0]?.id ?? null
    : null
  const selectedSchedule = effectiveScheduleId
    ? checkoutableSchedules.find((s) => s.id === effectiveScheduleId) ?? null
    : null

  const ctaLabel = selectedSchedule
    ? scheduleCtaLabel(selectedSchedule)
    : 'Continue to checkout'

  const disclosure = selectedSchedule
    ? scheduleDisclosureCopy(selectedSchedule)
    : null

  // Empty state — creator hasn't published anything checkoutable yet.
  if (purchasableOptions.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 bg-white px-5 py-6 text-center">
        <p className="text-[13px] font-medium text-navy-900">
          Ways to join are coming soon.
        </p>
        <p className="mt-1 text-[12px] leading-relaxed text-slate-600">
          The Creator hasn&rsquo;t published a payment option yet.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Step 1: Choose payment option (only shown if >1) */}
      {purchasableOptions.length > 1 && (
        <div className="space-y-3">
          {purchasableOptions.map((opt) => {
            const price =
              opt.effective_price_cents != null
                ? formatMoney(opt.effective_price_cents, opt.currency)
                : null
            const isSelected = opt.id === selectedOptionId
            const checkoutableForOpt = opt.schedules.filter(
              (s) => s.is_member_checkoutable,
            )
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => handleOptionSelect(opt.id)}
                className="w-full rounded-xl border-2 bg-white p-4 text-left transition-colors"
                style={{
                  borderColor: isSelected ? '#38A09E' : '#E2E8F0',
                  background: isSelected
                    ? 'rgba(56,160,158,0.04)'
                    : '#FFFFFF',
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[14px] font-semibold text-navy-900">
                      {opt.name}
                    </p>
                    {opt.description && (
                      <p className="mt-0.5 text-[13px] text-black">
                        {opt.description}
                      </p>
                    )}
                    {opt.buyer_note && (
                      <p className="mt-1 text-[12px] text-teal-700">
                        {opt.buyer_note}
                      </p>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    {price && (
                      <p className="text-[16px] font-bold text-navy-900">
                        {price}
                      </p>
                    )}
                    {checkoutableForOpt.length > 1 && (
                      <p className="mt-0.5 text-[11px] text-black">
                        {checkoutableForOpt.length} ways to pay
                      </p>
                    )}
                    <div
                      className="mt-1 ml-auto flex h-4 w-4 items-center justify-center rounded-full border-2"
                      style={{
                        borderColor: isSelected ? '#38A09E' : '#CBD5E1',
                      }}
                    >
                      {isSelected && (
                        <div
                          className="h-2 w-2 rounded-full"
                          style={{ background: '#38A09E' }}
                        />
                      )}
                    </div>
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}

      {/* Step 2: Choose how to pay (only shown if >1 checkoutable
          schedule under the selected Option). */}
      {hasSchedules && checkoutableSchedules.length > 1 && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-black">
            Choose how you&rsquo;d like to pay
          </p>
          <div className="space-y-2">
            {checkoutableSchedules.map((s) => {
              const isSelSched = s.id === effectiveScheduleId
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelectedScheduleId(s.id)}
                  className="w-full rounded-lg border-2 bg-white px-4 py-3 text-left transition-colors"
                  style={{
                    borderColor: isSelSched ? '#38A09E' : '#E2E8F0',
                    background: isSelSched
                      ? 'rgba(56,160,158,0.04)'
                      : '#FFFFFF',
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[13px] font-semibold text-navy-900">
                        {scheduleKindLabel(s)}
                      </p>
                      <p className="mt-0.5 text-[12px] text-black">
                        {scheduleShortDescription(s)}
                      </p>
                      {scheduleTotalLine(s) && (
                        <p className="mt-0.5 text-[11px] text-slate-600">
                          {scheduleTotalLine(s)}
                        </p>
                      )}
                      {s.buyer_note && (
                        <p className="mt-1 text-[11px] text-teal-700">
                          {s.buyer_note}
                        </p>
                      )}
                    </div>
                    <div
                      className="mt-1 ml-auto flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2"
                      style={{
                        borderColor: isSelSched ? '#38A09E' : '#CBD5E1',
                      }}
                    >
                      {isSelSched && (
                        <div
                          className="h-2 w-2 rounded-full"
                          style={{ background: '#38A09E' }}
                        />
                      )}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Payment summary */}
      {selectedOption && selectedSchedule && (
        <div
          className="space-y-2 rounded-xl border border-border bg-white p-4"
        >
          <div className="flex items-baseline justify-between gap-3 text-[14px]">
            <span className="text-black">{selectedOption.name}</span>
            <span className="font-semibold text-navy-900">
              {scheduleShortDescription(selectedSchedule)}
            </span>
          </div>
          {scheduleTotalLine(selectedSchedule) && (
            <div
              className="flex items-baseline justify-between gap-3 border-t pt-2 text-[13px]"
              style={{ borderColor: '#E2E8F0' }}
            >
              <span className="text-navy-900">Total commitment</span>
              <span className="font-semibold text-navy-900">
                {scheduleTotalLine(selectedSchedule)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Pre-checkout disclosure — makes the commitment explicit
          BEFORE the Stripe redirect. Stripe's server-generated
          setup-page disclosure is the final one; this is our
          own truthful summary on the FC side. */}
      {selectedSchedule?.schedule_type === 'recurring_installments' &&
        disclosure && (
          <p className="text-[12px] leading-relaxed text-slate-600">
            {disclosure}
          </p>
        )}

      {isAuthenticated ? (
        <>
          <CheckoutButton
            pathwayId={pathwayId}
            paymentOptionId={selectedOptionId || null}
            paymentOptionScheduleId={effectiveScheduleId}
            label={ctaLabel}
            useFinitePlanSuccessPage={
              selectedSchedule?.schedule_type === 'recurring_installments'
            }
          />
          <p className="text-center text-[11px] leading-relaxed text-black">
            Secure checkout via Stripe. You&rsquo;ll be redirected to complete
            payment.
          </p>
        </>
      ) : (
        <AnonCheckoutCTAs
          pathname={pathname}
          selectedOptionId={selectedOptionId || null}
          effectiveScheduleId={effectiveScheduleId}
        />
      )}
    </div>
  )
}
