'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface PlatformOverview {
  total_collectives: number
  active_collectives: number
  draft_collectives: number
  archived_collectives: number
  total_users: number
  admin_users: number
  creator_users: number
  member_users: number
  pending_access_requests: number
  pending_invitations: number
  total_gross_cents: number
  succeeded_transactions: number
}

function StatCard({
  label,
  value,
  sub,
  warn,
}: {
  label: string
  value: string | number
  sub?: string
  warn?: boolean
}) {
  return (
    <div
      className="rounded-xl bg-white p-4"
      style={{ border: `1px solid ${warn ? '#FCA5A5' : '#E2E8F0'}` }}
    >
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
        {label}
      </p>
      <p className={`text-[1.6rem] font-bold leading-none ${warn ? 'text-red-600' : 'text-[#0F172A]'}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-[11px] text-[#94A3B8]">{sub}</p>}
    </div>
  )
}

function fmt(cents: number) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: 'AUD',
    minimumFractionDigits: 0,
  }).format(cents / 100)
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<PlatformOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/admin/platform/overview'), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json()
      })
      .then(setData)
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

  if (error || !data) {
    return (
      <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
        {error ?? 'No data'}
      </div>
    )
  }

  const needsAttention = data.pending_access_requests + data.pending_invitations

  return (
    <div>
      <h1 className="mb-6 text-[1.5rem] font-bold text-[#0F172A]">Platform Overview</h1>

      {needsAttention > 0 && (
        <div
          className="mb-6 flex items-center gap-3 rounded-xl bg-amber-50 px-4 py-3"
          style={{ border: '1px solid #FCD34D' }}
        >
          <span className="text-[18px]">⚠</span>
          <p className="text-[13px] font-medium text-amber-800">
            {data.pending_access_requests > 0 && (
              <span>{data.pending_access_requests} pending access request{data.pending_access_requests !== 1 ? 's' : ''}</span>
            )}
            {data.pending_access_requests > 0 && data.pending_invitations > 0 && <span> · </span>}
            {data.pending_invitations > 0 && (
              <span>{data.pending_invitations} open invitation{data.pending_invitations !== 1 ? 's' : ''}</span>
            )}
            {' — '}
            <a href="/admin/access" className="underline hover:text-amber-900">Review now →</a>
          </p>
        </div>
      )}

      <div className="mb-8">
        <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">Collectives</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total" value={data.total_collectives} />
          <StatCard label="Active" value={data.active_collectives} />
          <StatCard label="Draft" value={data.draft_collectives} />
          <StatCard label="Archived" value={data.archived_collectives} />
        </div>
      </div>

      <div className="mb-8">
        <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">Users</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total Users" value={data.total_users} />
          <StatCard label="Creators" value={data.creator_users} />
          <StatCard label="Members" value={data.member_users} />
          <StatCard label="Admins" value={data.admin_users} />
        </div>
      </div>

      <div className="mb-8">
        <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">Revenue</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatCard label="Total Gross (AUD)" value={fmt(data.total_gross_cents)} />
          <StatCard label="Succeeded Transactions" value={data.succeeded_transactions} />
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">Queue</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatCard
            label="Pending Access Requests"
            value={data.pending_access_requests}
            warn={data.pending_access_requests > 0}
          />
          <StatCard
            label="Open Invitations"
            value={data.pending_invitations}
          />
        </div>
      </div>
    </div>
  )
}
