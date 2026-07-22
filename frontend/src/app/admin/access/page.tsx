'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface AccessRequestRow {
  id: string
  space_id: string
  space_name: string
  space_slug: string
  user_id: string
  user_name: string | null
  user_email: string
  status: string
  message: string | null
  created_at: string
}

interface InvitationRow {
  id: string
  space_id: string
  space_name: string
  space_slug: string
  email: string
  name: string | null
  role: string
  invited_by_name: string | null
  invited_by_email: string | null
  created_at: string
}

interface AccessData {
  access_requests: AccessRequestRow[]
  invitations: InvitationRow[]
}

type Tab = 'requests' | 'invitations'

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'bg-amber-50 text-amber-700 border-amber-200',
    approved: 'bg-teal-50 text-teal-700 border-teal-200',
    declined: 'bg-red-50 text-red-600 border-red-200',
  }
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${map[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
      {status}
    </span>
  )
}

function fmtDate(s: string) {
  return new Date(s).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function AdminAccessPage() {
  const [data, setData] = useState<AccessData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('requests')

  useEffect(() => {
    fetch(apiUrl('/api/admin/platform/access'), { credentials: 'include' })
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
      <div className="flex items-center gap-2 text-[14px] text-[#000000]">
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

  const pendingRequests = data.access_requests.filter((r) => r.status === 'pending')

  const tabs: { key: Tab; label: string }[] = [
    { key: 'requests', label: `Access Requests (${data.access_requests.length})` },
    { key: 'invitations', label: `Open Invitations (${data.invitations.length})` },
  ]

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Invitations</h1>
        <p className="mt-1 text-[13px] text-[#000000]">
          Invitations sent, doorways being opened, and members waiting to walk through.
          Every collective&rsquo;s creator decides who joins their world.
        </p>
      </div>

      {pendingRequests.length > 0 && (
        <div
          className="mb-5 flex items-center gap-2 rounded-xl bg-amber-50 px-4 py-3"
          style={{ border: '1px solid #FCD34D' }}
        >
          <span className="text-[16px]">⚠</span>
          <p className="text-[13px] font-medium text-amber-800">
            {pendingRequests.length} pending access request{pendingRequests.length !== 1 ? 's' : ''} awaiting creator approval.
          </p>
        </div>
      )}

      {/* Tabs */}
      <div className="mb-4 flex gap-1">
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
              tab === key ? 'bg-teal-500 text-white' : 'bg-white text-[#000000] hover:bg-[#F1F5F9]'
            }`}
            style={{ border: '1px solid #E2E8F0' }}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'requests' && (
        <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-left">
              <thead>
                <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                  {['User', 'Collective', 'Status', 'Message', 'Requested'].map((h) => (
                    <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#000000]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.access_requests.map((row, i) => (
                  <tr
                    key={row.id}
                    style={{
                      borderBottom: i < data.access_requests.length - 1 ? '1px solid #F1F5F9' : undefined,
                      background: row.status === 'pending' ? '#FFFBEB' : undefined,
                    }}
                  >
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-medium text-[#0F172A]">{row.user_name ?? '—'}</p>
                      <p className="text-[11px] text-[#000000]">{row.user_email}</p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#0F172A]">{row.space_name}</p>
                      <p className="text-[11px] text-[#000000]">{row.space_slug}</p>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                    <td className="max-w-[220px] px-4 py-3 text-[12px] text-[#000000]">
                      {row.message ? (
                        <span className="line-clamp-2">{row.message}</span>
                      ) : (
                        <span className="text-[#000000]">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#000000]">{fmtDate(row.created_at)}</td>
                  </tr>
                ))}
                {data.access_requests.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-[13px] text-[#000000]">
                      No access requests.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="divide-y divide-[#F1F5F9] lg:hidden">
            {data.access_requests.map((row) => (
              <div
                key={row.id}
                className="p-4"
                style={{ background: row.status === 'pending' ? '#FFFBEB' : undefined }}
              >
                <div className="mb-1 flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[14px] font-semibold text-[#0F172A]">{row.user_name ?? row.user_email}</p>
                    <p className="text-[12px] text-[#000000]">{row.user_email}</p>
                  </div>
                  <StatusBadge status={row.status} />
                </div>
                <p className="text-[12px] text-[#000000]">Collective: {row.space_name}</p>
                {row.message && (
                  <p className="mt-1 text-[12px] italic text-[#000000]">&ldquo;{row.message}&rdquo;</p>
                )}
                <p className="mt-1 text-[11px] text-[#000000]">{fmtDate(row.created_at)}</p>
              </div>
            ))}
            {data.access_requests.length === 0 && (
              <p className="p-6 text-center text-[13px] text-[#000000]">No access requests.</p>
            )}
          </div>
        </div>
      )}

      {tab === 'invitations' && (
        <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-left">
              <thead>
                <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                  {['Invited Email', 'Name', 'Collective', 'Role', 'Invited By', 'Sent'].map((h) => (
                    <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#000000]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.invitations.map((row, i) => (
                  <tr
                    key={row.id}
                    style={{ borderBottom: i < data.invitations.length - 1 ? '1px solid #F1F5F9' : undefined }}
                  >
                    <td className="px-4 py-3 text-[13px] font-medium text-[#0F172A]">{row.email}</td>
                    <td className="px-4 py-3 text-[13px] text-[#000000]">{row.name ?? '—'}</td>
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#0F172A]">{row.space_name}</p>
                      <p className="text-[11px] text-[#000000]">{row.space_slug}</p>
                    </td>
                    <td className="px-4 py-3 text-[12px] capitalize text-[#000000]">{row.role}</td>
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#0F172A]">{row.invited_by_name ?? '—'}</p>
                      <p className="text-[11px] text-[#000000]">{row.invited_by_email ?? ''}</p>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#000000]">{fmtDate(row.created_at)}</td>
                  </tr>
                ))}
                {data.invitations.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-[13px] text-[#000000]">
                      No open invitations.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="divide-y divide-[#F1F5F9] lg:hidden">
            {data.invitations.map((row) => (
              <div key={row.id} className="p-4">
                <p className="text-[14px] font-semibold text-[#0F172A]">{row.email}</p>
                {row.name && <p className="text-[12px] text-[#000000]">{row.name}</p>}
                <p className="mt-1 text-[12px] text-[#000000]">Collective: {row.space_name}</p>
                <p className="text-[12px] text-[#000000]">
                  Role: {row.role} · Sent {fmtDate(row.created_at)}
                </p>
                {row.invited_by_name && (
                  <p className="text-[11px] text-[#000000]">By {row.invited_by_name}</p>
                )}
              </div>
            ))}
            {data.invitations.length === 0 && (
              <p className="p-6 text-center text-[13px] text-[#000000]">No open invitations.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
