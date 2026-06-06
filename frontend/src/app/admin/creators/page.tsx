'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CreatorRow {
  id: string
  name: string | null
  email: string
  role: string
  created_at: string
  collective_count: number
  plan_name: string
  subscription_status: string
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: 'bg-teal-50 text-teal-700 border-teal-200',
    trialing: 'bg-blue-50 text-blue-700 border-blue-200',
    past_due: 'bg-amber-50 text-amber-700 border-amber-200',
    cancelled: 'bg-slate-100 text-slate-500 border-slate-200',
    unpaid: 'bg-red-50 text-red-700 border-red-200',
    none: 'bg-slate-100 text-slate-500 border-slate-200',
  }
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${map[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
      {status}
    </span>
  )
}

export default function AdminCreatorsPage() {
  const [rows, setRows] = useState<CreatorRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/admin/platform/creators'), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json()
      })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[14px] text-[#64748B]">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        Loading…
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
        {error}
      </div>
    )
  }

  return (
    <div>
      <h1 className="mb-1 text-[1.5rem] font-bold text-[#0F172A]">Creators</h1>
      <p className="mb-6 text-[13px] text-[#64748B]">{rows.length} creator{rows.length !== 1 ? 's' : ''}</p>

      <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
        {/* Desktop */}
        <div className="hidden overflow-x-auto lg:block">
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                {['Name', 'Email', 'Plan', 'Subscription', 'Collectives', 'Joined'].map((h) => (
                  <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={row.id}
                  style={{ borderBottom: i < rows.length - 1 ? '1px solid #F1F5F9' : undefined }}
                >
                  <td className="px-4 py-3 text-[13px] font-medium text-[#0F172A]">{row.name ?? '—'}</td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.email}</td>
                  <td className="px-4 py-3 text-[13px] text-[#0F172A]">{row.plan_name}</td>
                  <td className="px-4 py-3"><StatusBadge status={row.subscription_status} /></td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.collective_count}</td>
                  <td className="px-4 py-3 text-[13px] text-[#94A3B8]">
                    {new Date(row.created_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-[13px] text-[#94A3B8]">
                    No creators yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Mobile cards */}
        <div className="divide-y divide-[#F1F5F9] lg:hidden">
          {rows.map((row) => (
            <div key={row.id} className="p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div>
                  <p className="text-[14px] font-semibold text-[#0F172A]">{row.name ?? row.email}</p>
                  <p className="text-[12px] text-[#64748B]">{row.email}</p>
                </div>
                <StatusBadge status={row.subscription_status} />
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[12px]">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Plan</p>
                  <p className="font-medium text-[#0F172A]">{row.plan_name}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Collectives</p>
                  <p className="font-medium text-[#0F172A]">{row.collective_count}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Joined</p>
                  <p className="font-medium text-[#0F172A]">
                    {new Date(row.created_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })}
                  </p>
                </div>
              </div>
            </div>
          ))}
          {rows.length === 0 && (
            <p className="p-6 text-center text-[13px] text-[#94A3B8]">No creators yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}
