'use client'

import { useState } from 'react'

interface Props {
  feeBasisPoints: number
  currency: string
}

export default function BillingFeeCalculator({ feeBasisPoints, currency }: Props) {
  const [saleCents, setSaleCents] = useState(4900) // $49 default

  const feeAmount = Math.round(saleCents * (feeBasisPoints / 10000))
  const creatorAmount = saleCents - feeAmount
  const feePct = (feeBasisPoints / 100).toFixed(0)

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = parseFloat(e.target.value)
    if (!isNaN(raw) && raw >= 0) {
      setSaleCents(Math.round(raw * 100))
    }
  }

  function fmt(cents: number): string {
    return `$${(cents / 100).toFixed(2)} ${currency}`
  }

  return (
    <div className="max-w-sm space-y-4">
      <div>
        <label htmlFor="sale-amount" className="mb-1.5 block text-[13px] font-medium text-slate-700">
          Member sale amount ({currency})
        </label>
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-medium text-slate-500">$</span>
          <input
            id="sale-amount"
            type="number"
            min="0"
            step="1"
            defaultValue="49"
            onChange={handleChange}
            className="w-32 rounded-xl border border-slate-200 bg-white px-3 py-2 text-[14px] font-medium text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400"
          />
        </div>
      </div>

      <div className="space-y-2 rounded-xl bg-slate-50 p-4 text-[13px]">
        <div className="flex justify-between">
          <span className="text-slate-500">Sale amount</span>
          <span className="font-medium text-navy-900">{fmt(saleCents)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Fresh Collective fee ({feePct}%)</span>
          <span className="font-medium text-amber-700">− {fmt(feeAmount)}</span>
        </div>
        <div className="flex justify-between border-t border-slate-200 pt-2">
          <span className="font-semibold text-slate-700">Your estimated amount</span>
          <span className="font-bold text-teal-700">{fmt(creatorAmount)}</span>
        </div>
      </div>

      <p className="text-[11px] leading-relaxed text-slate-400">
        Estimate only. Does not include Stripe processing fees (~1.75% + $0.30 AUD), GST, refunds, disputes, or payout costs. Upgrade to Creator Plus to reduce your fee to 3%.
      </p>
    </div>
  )
}
