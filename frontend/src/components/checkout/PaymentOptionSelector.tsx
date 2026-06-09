'use client'

import { useState } from 'react'
import { CheckoutButton } from './CheckoutButton'
import type { PaymentOptionSummary } from '@/types/platform'

function formatPrice(cents: number, currency: string): string {
  const amount = cents / 100
  const symbol = currency.toUpperCase() === 'AUD' ? '$' : currency
  return `${symbol}${amount % 1 === 0 ? amount.toFixed(0) : amount.toFixed(2)}`
}

interface Props {
  pathwayId: string
  options: PaymentOptionSummary[]
}

export function PaymentOptionSelector({ pathwayId, options }: Props) {
  const [selectedId, setSelectedId] = useState<string>(options[0]?.id ?? '')
  const selected = options.find(o => o.id === selectedId)

  return (
    <div className="space-y-4">
      <div className="space-y-3">
        {options.map(opt => {
          const price = opt.effective_price_cents != null
            ? formatPrice(opt.effective_price_cents, opt.currency)
            : null
          const isSelected = opt.id === selectedId
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => setSelectedId(opt.id)}
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
                    <p className="mt-0.5 text-[13px] text-slate-500">{opt.description}</p>
                  )}
                  {opt.buyer_note && (
                    <p className="mt-1 text-[12px] text-teal-700">{opt.buyer_note}</p>
                  )}
                  {opt.payment_type === 'term_pass' && opt.term_end_date && (
                    <p className="mt-1 text-[12px] text-slate-400">
                      Access until {new Date(opt.term_end_date).toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })}
                    </p>
                  )}
                  {opt.sessions_per_week != null && opt.total_sessions != null && (
                    <p className="mt-1 text-[12px] text-slate-400">
                      {opt.sessions_per_week}×/week · {opt.total_sessions} sessions total
                    </p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  {price && (
                    <p className="font-bold text-navy-900 text-[16px]">{price}</p>
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

      {selected && (
        <div className="rounded-xl border border-border bg-white p-4 space-y-2">
          <div className="flex items-center justify-between text-[14px]">
            <span className="text-slate-600">{selected.name}</span>
            <span className="font-semibold text-navy-900">
              {selected.effective_price_cents != null
                ? formatPrice(selected.effective_price_cents, selected.currency)
                : '—'}
            </span>
          </div>
          <div className="flex items-center justify-between border-t pt-2 font-semibold text-[14px]" style={{ borderColor: '#E2E8F0' }}>
            <span className="text-navy-900">Total</span>
            <span className="text-navy-900">
              {selected.effective_price_cents != null
                ? formatPrice(selected.effective_price_cents, selected.currency)
                : '—'}
            </span>
          </div>
        </div>
      )}

      <CheckoutButton
        pathwayId={pathwayId}
        paymentOptionId={selectedId || null}
        label={
          selected?.effective_price_cents != null
            ? `Unlock for ${formatPrice(selected.effective_price_cents, selected.currency)}`
            : 'Unlock pathway'
        }
      />

      <p className="text-center text-[11px] leading-relaxed text-slate-400">
        Secure checkout via Stripe. You&apos;ll be redirected to complete payment.
      </p>
    </div>
  )
}
