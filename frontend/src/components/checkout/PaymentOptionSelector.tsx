'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { CheckoutButton } from './CheckoutButton'
import type { PaymentOptionSummary, PaymentOptionScheduleSummary } from '@/types/platform'

function formatPrice(cents: number, currency: string): string {
  const amount = cents / 100
  const symbol = currency.toUpperCase() === 'AUD' ? '$' : currency
  return `${symbol}${amount % 1 === 0 ? amount.toFixed(0) : amount.toFixed(2)}`
}

function formatScheduleLabel(s: PaymentOptionScheduleSummary): string {
  if (s.schedule_type === 'pay_in_full' && s.total_amount_cents != null) {
    return formatPrice(s.total_amount_cents, s.currency)
  }
  if (s.schedule_type === 'recurring_installments') {
    const count = s.installment_count
    const amount = s.installment_amount_cents != null
      ? formatPrice(s.installment_amount_cents, s.currency)
      : '—'
    const intervalLabel =
      s.interval === 'fortnight' ? 'fortnightly'
      : s.interval === 'week' ? 'weekly'
      : (s.interval ?? '')
    return count ? `${count} × ${amount} ${intervalLabel}` : `${amount} ${intervalLabel}`
  }
  return s.name
}

function scheduleCheckoutLabel(s: PaymentOptionScheduleSummary): string {
  if (s.schedule_type === 'pay_in_full' && s.total_amount_cents != null) {
    return `Pay ${formatPrice(s.total_amount_cents, s.currency)} AUD`
  }
  if (s.schedule_type === 'recurring_installments') {
    const intervalLabel =
      s.interval === 'fortnight' ? 'fortnightly'
      : s.interval === 'week' ? 'weekly'
      : 'recurring'
    return `Start ${intervalLabel} payments`
  }
  return 'Unlock pathway'
}

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
  if (effectiveScheduleId) params.set('payment_option_schedule_id', effectiveScheduleId)
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
        Create a free account so we can save your access and connect your payment to your profile.
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
  const [selectedOptionId, setSelectedOptionId] = useState<string>(
    initialOptionId ?? options[0]?.id ?? ''
  )
  const [selectedScheduleId, setSelectedScheduleId] = useState<string | null>(
    initialScheduleId ?? null
  )

  const selectedOption = options.find(o => o.id === selectedOptionId)
  const publishedSchedules = selectedOption?.schedules ?? []
  const hasSchedules = publishedSchedules.length > 0

  function handleOptionSelect(id: string) {
    setSelectedOptionId(id)
    setSelectedScheduleId(null)
  }

  // Default to first schedule when none explicitly chosen
  const effectiveScheduleId = hasSchedules
    ? (selectedScheduleId ?? publishedSchedules[0]?.id ?? null)
    : null
  const selectedSchedule = effectiveScheduleId
    ? (publishedSchedules.find(s => s.id === effectiveScheduleId) ?? null)
    : null

  const ctaLabel = (() => {
    if (selectedSchedule) return scheduleCheckoutLabel(selectedSchedule)
    if (selectedOption?.effective_price_cents != null) {
      return `Pay ${formatPrice(selectedOption.effective_price_cents, selectedOption.currency)} AUD`
    }
    return 'Unlock pathway'
  })()

  const summaryPrice = (() => {
    if (selectedSchedule?.schedule_type === 'pay_in_full' && selectedSchedule.total_amount_cents != null) {
      return formatPrice(selectedSchedule.total_amount_cents, selectedSchedule.currency)
    }
    if (selectedOption?.effective_price_cents != null) {
      return formatPrice(selectedOption.effective_price_cents, selectedOption.currency)
    }
    return '—'
  })()

  return (
    <div className="space-y-4">

      {/* Step 1: Choose payment option */}
      <div className="space-y-3">
        {options.map(opt => {
          const price = opt.effective_price_cents != null
            ? formatPrice(opt.effective_price_cents, opt.currency)
            : null
          const isSelected = opt.id === selectedOptionId
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => handleOptionSelect(opt.id)}
              className="w-full rounded-xl border-2 bg-white p-4 text-left transition-colors"
              style={{
                borderColor: isSelected ? '#38A09E' : '#E2E8F0',
                background: isSelected ? 'rgba(56,160,158,0.04)' : '#FFFFFF',
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-navy-900 text-[14px]">{opt.name}</p>
                  {opt.description && (
                    <p className="mt-0.5 text-[13px] text-black">{opt.description}</p>
                  )}
                  {opt.buyer_note && (
                    <p className="mt-1 text-[12px] text-teal-700">{opt.buyer_note}</p>
                  )}
                  {opt.payment_type === 'term_pass' && opt.term_end_date && (
                    <p className="mt-1 text-[12px] text-black">
                      Access until {new Date(opt.term_end_date).toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })}
                    </p>
                  )}
                  {opt.sessions_per_week != null && opt.total_sessions != null && (
                    <p className="mt-1 text-[12px] text-black">
                      {opt.sessions_per_week} session{opt.sessions_per_week !== 1 ? 's' : ''} per week · {opt.total_sessions} sessions included
                    </p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  {price && (
                    <p className="font-bold text-navy-900 text-[16px]">{price}</p>
                  )}
                  {opt.schedules.length > 1 && (
                    <p className="mt-0.5 text-[11px] text-black">{opt.schedules.length} payment options</p>
                  )}
                  <div
                    className="mt-1 ml-auto h-4 w-4 rounded-full border-2 flex items-center justify-center"
                    style={{ borderColor: isSelected ? '#38A09E' : '#CBD5E1' }}
                  >
                    {isSelected && (
                      <div className="h-2 w-2 rounded-full" style={{ background: '#38A09E' }} />
                    )}
                  </div>
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {/* Step 2: Choose payment schedule (shown when the selected option has published schedules) */}
      {hasSchedules && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-black">
            Payment schedule
          </p>
          <div className="space-y-2">
            {publishedSchedules.map(s => {
              const isSelSched = s.id === effectiveScheduleId
              const isRecurring = s.schedule_type === 'recurring_installments'
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => { if (!isRecurring) setSelectedScheduleId(s.id) }}
                  disabled={isRecurring}
                  className="w-full rounded-lg border-2 bg-white px-4 py-3 text-left transition-colors disabled:opacity-50"
                  style={{
                    borderColor: isSelSched && !isRecurring ? '#38A09E' : '#E2E8F0',
                    background: isSelSched && !isRecurring ? 'rgba(56,160,158,0.04)' : '#FFFFFF',
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-[13px] font-semibold text-navy-900">{s.name}</p>
                      {s.buyer_note && (
                        <p className="mt-0.5 text-[11px] text-black">{s.buyer_note}</p>
                      )}
                      {isRecurring && (
                        <p className="mt-0.5 text-[11px] text-amber-600">Coming soon — not yet available</p>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-[13px] font-bold text-navy-900">{formatScheduleLabel(s)}</p>
                      <div
                        className="mt-1 ml-auto h-4 w-4 rounded-full border-2 flex items-center justify-center"
                        style={{ borderColor: isSelSched && !isRecurring ? '#38A09E' : '#CBD5E1' }}
                      >
                        {isSelSched && !isRecurring && (
                          <div className="h-2 w-2 rounded-full" style={{ background: '#38A09E' }} />
                        )}
                      </div>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Payment summary */}
      {selectedOption && (
        <div className="rounded-xl border border-border bg-white p-4 space-y-2">
          <div className="flex items-center justify-between text-[14px]">
            <span className="text-black">{selectedOption.name}</span>
            <span className="font-semibold text-navy-900">{summaryPrice}</span>
          </div>
          {selectedSchedule && selectedSchedule.schedule_type !== 'pay_in_full' && selectedSchedule.installment_count && (
            <div className="flex items-center justify-between text-[12px] text-black">
              <span>{selectedSchedule.name}</span>
            </div>
          )}
          <div className="flex items-center justify-between border-t pt-2 font-semibold text-[14px]" style={{ borderColor: '#E2E8F0' }}>
            <span className="text-navy-900">Total</span>
            <span className="text-navy-900">{summaryPrice}</span>
          </div>
        </div>
      )}

      {isAuthenticated ? (
        <>
          <CheckoutButton
            pathwayId={pathwayId}
            paymentOptionId={selectedOptionId || null}
            paymentOptionScheduleId={effectiveScheduleId}
            label={ctaLabel}
          />
          <p className="text-center text-[11px] leading-relaxed text-black">
            Secure checkout via Stripe. You&apos;ll be redirected to complete payment.
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
