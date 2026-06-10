'use client'

import { useState } from 'react'
import type { AccessPassAdminSummary } from '@/types/platform'

interface Props {
  passes: AccessPassAdminSummary[]
  spaceName: string
  spaceSlug: string
}

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  pending: 'Pending',
  expired: 'Expired',
  cancelled: 'Cancelled',
  used: 'Used',
  suspended: 'Suspended',
}

const STATUS_COLOURS: Record<string, string> = {
  active: 'bg-teal-50 text-teal-700 border-teal-200',
  pending: 'bg-amber-50 text-amber-700 border-amber-200',
  expired: 'bg-slate-100 text-slate-500 border-slate-200',
  cancelled: 'bg-red-50 text-red-600 border-red-200',
  used: 'bg-slate-100 text-slate-500 border-slate-200',
  suspended: 'bg-orange-50 text-orange-600 border-orange-200',
}

const PASS_TYPE_LABELS: Record<string, string> = {
  term_pass: 'Term Pass',
  class_pass: 'Class Pass',
  pathway_access: 'Pathway Access',
  event_ticket: 'Event Ticket',
  retreat_booking: 'Retreat Booking',
  membership: 'Membership',
  bundle: 'Bundle',
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

function CreditBar({ used, total }: { used: number; total: number | null }) {
  if (total === null) {
    return <span className="text-[13px] text-slate-400">Unlimited</span>
  }
  const remaining = Math.max(0, total - used)
  const pct = total > 0 ? Math.round((remaining / total) * 100) : 0
  const barColour = pct > 40 ? '#38A09E' : pct > 15 ? '#F59E0B' : '#EF4444'
  return (
    <div>
      <span className="text-[13px] font-semibold text-navy-900">{remaining}</span>
      <span className="text-[12px] text-slate-400"> / {total}</span>
      <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: barColour }} />
      </div>
    </div>
  )
}

export default function PassesClient({ passes, spaceName }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>('active')

  const filtered = statusFilter === 'all'
    ? passes
    : passes.filter(p => p.status === statusFilter)

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      {/* Header */}
      <div className="mb-6 flex flex-col gap-1">
        <h1 className="font-serif text-2xl text-navy-900">Member Passes</h1>
        <p className="text-[14px] text-slate-500">{spaceName} · Session allowances and access passes</p>
      </div>

      {/* Filters */}
      <div className="mb-5 flex flex-wrap gap-2">
        {(['active', 'expired', 'cancelled', 'all'] as const).map(f => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`rounded-full border px-3 py-1 text-[12px] font-medium transition-colors ${
              statusFilter === f
                ? 'border-teal-500 bg-teal-50 text-teal-700'
                : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'
            }`}
          >
            {f === 'all' ? 'All statuses' : STATUS_LABELS[f] ?? f}
          </button>
        ))}
        <span className="ml-auto text-[12px] text-slate-400 self-center">
          {filtered.length} {filtered.length === 1 ? 'pass' : 'passes'}
        </span>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="text-[15px] font-semibold text-navy-900">No passes found.</p>
          <p className="mt-1 text-[13px] text-slate-500">
            Passes are created automatically when members complete a term pass purchase.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Member</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Pass</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Status</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Valid</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Credits</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Per week</th>
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Bookings (30d)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {filtered.map(pass => (
                <tr key={pass.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-4 py-3.5">
                    <p className="text-[13px] font-semibold text-navy-900">{pass.member_name ?? '—'}</p>
                    <p className="text-[12px] text-slate-400">{pass.member_email ?? ''}</p>
                  </td>
                  <td className="px-4 py-3.5">
                    <p className="text-[13px] font-semibold text-navy-900">{pass.option_name ?? '—'}</p>
                    <p className="text-[11px] text-slate-400">{PASS_TYPE_LABELS[pass.pass_type] ?? pass.pass_type}</p>
                    {pass.pathway_title && (
                      <p className="text-[11px] text-teal-600">{pass.pathway_title}</p>
                    )}
                  </td>
                  <td className="px-4 py-3.5">
                    <span
                      className={`inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${STATUS_COLOURS[pass.status] ?? 'bg-slate-100 text-slate-500'}`}
                    >
                      {STATUS_LABELS[pass.status] ?? pass.status}
                    </span>
                  </td>
                  <td className="px-4 py-3.5">
                    <p className="text-[12px] text-navy-900">{formatDate(pass.valid_from)}</p>
                    {pass.valid_until && (
                      <p className="text-[11px] text-slate-400">→ {formatDate(pass.valid_until)}</p>
                    )}
                  </td>
                  <td className="px-4 py-3.5">
                    <CreditBar used={pass.used_credits} total={pass.total_credits} />
                  </td>
                  <td className="px-4 py-3.5">
                    {pass.credits_per_week != null ? (
                      <span className="text-[13px] text-navy-900">{pass.credits_per_week}/wk</span>
                    ) : (
                      <span className="text-[13px] text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3.5">
                    <span className="text-[13px] font-semibold text-navy-900">{pass.recent_bookings}</span>
                    <span className="text-[12px] text-slate-400"> / {pass.total_bookings} total</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
