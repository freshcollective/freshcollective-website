'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CollectiveRow {
  id: string
  name: string
  slug: string
  status: string
  is_public: boolean
  has_paid_internal_content: boolean
  creator_name: string | null
  creator_email: string | null
  member_count: number
  pathway_count: number
  gathering_count: number
  resource_count: number
  created_at: string
  updated_at: string
}

type Tab = 'all' | 'active' | 'draft' | 'archived'

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: 'bg-teal-50 text-teal-700 border-teal-200',
    draft: 'bg-slate-100 text-slate-500 border-slate-200',
    archived: 'bg-orange-50 text-orange-600 border-orange-200',
  }
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${map[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
      {status}
    </span>
  )
}

export default function AdminCollectivesPage() {
  const [rows, setRows] = useState<CollectiveRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('all')

  useEffect(() => {
    fetch(apiUrl('/api/admin/platform/collectives'), { credentials: 'include' })
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

  const tabs: { key: Tab; label: string }[] = [
    { key: 'all', label: `All (${rows.length})` },
    { key: 'active', label: `Active (${rows.filter((r) => r.status === 'active').length})` },
    { key: 'draft', label: `Draft (${rows.filter((r) => r.status === 'draft').length})` },
    { key: 'archived', label: `Archived (${rows.filter((r) => r.status === 'archived').length})` },
  ]

  const filtered = tab === 'all' ? rows : rows.filter((r) => r.status === tab)

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Collectives</h1>
        <p className="mt-1 text-[13px] text-[#64748B]">All spaces on the platform. Creator details and billing are managed via Creator Billing.</p>
      </div>

      {/* Tabs */}
      <div className="mb-4 flex gap-1">
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
              tab === key
                ? 'bg-teal-500 text-white'
                : 'bg-white text-[#475569] hover:bg-[#F1F5F9]'
            }`}
            style={{ border: '1px solid #E2E8F0' }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
        {/* Desktop */}
        <div className="hidden overflow-x-auto lg:block">
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                {['Name', 'Creator', 'Status', 'Members', 'Pathways', 'Gatherings', 'Resources', 'Visibility'].map((h) => (
                  <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, i) => (
                <tr
                  key={row.id}
                  style={{ borderBottom: i < filtered.length - 1 ? '1px solid #F1F5F9' : undefined }}
                >
                  <td className="px-4 py-3">
                    <p className="text-[13px] font-medium text-[#0F172A]">{row.name}</p>
                    <p className="text-[11px] text-[#94A3B8]">{row.slug}</p>
                    {row.has_paid_internal_content && (
                      <span className="mt-0.5 inline-block rounded-full bg-purple-50 px-1.5 py-0.5 text-[10px] font-semibold text-purple-600">
                        Paid content
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-[13px] text-[#0F172A]">{row.creator_name ?? '—'}</p>
                    <p className="text-[11px] text-[#94A3B8]">{row.creator_email ?? ''}</p>
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.member_count}</td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.pathway_count}</td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.gathering_count}</td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.resource_count}</td>
                  <td className="px-4 py-3">
                    <span className={`text-[12px] font-medium ${row.is_public ? 'text-teal-600' : 'text-[#94A3B8]'}`}>
                      {row.is_public ? 'Public' : 'Private'}
                    </span>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-[13px] text-[#94A3B8]">
                    No collectives.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Mobile cards */}
        <div className="divide-y divide-[#F1F5F9] lg:hidden">
          {filtered.map((row) => (
            <div key={row.id} className="p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div>
                  <p className="text-[14px] font-semibold text-[#0F172A]">{row.name}</p>
                  <p className="text-[12px] text-[#64748B]">{row.slug}</p>
                </div>
                <StatusBadge status={row.status} />
              </div>
              <p className="mb-2 text-[12px] text-[#64748B]">
                {row.creator_name ?? row.creator_email ?? '—'}
              </p>
              <div className="grid grid-cols-4 gap-2 text-center text-[12px]">
                {[
                  { label: 'Members', v: row.member_count },
                  { label: 'Pathways', v: row.pathway_count },
                  { label: 'Gatherings', v: row.gathering_count },
                  { label: 'Resources', v: row.resource_count },
                ].map(({ label, v }) => (
                  <div key={label}>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">{label}</p>
                    <p className="font-medium text-[#0F172A]">{v}</p>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="p-6 text-center text-[13px] text-[#94A3B8]">No collectives.</p>
          )}
        </div>
      </div>
    </div>
  )
}
