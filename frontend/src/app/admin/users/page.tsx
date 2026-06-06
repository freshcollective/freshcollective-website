'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface UserRow {
  id: string
  name: string | null
  email: string
  role: string
  created_at: string
  joined_collectives: number
  owned_collectives: number
}

const ROLE_COLORS: Record<string, string> = {
  admin: 'bg-purple-50 text-purple-700 border-purple-200',
  creator: 'bg-teal-50 text-teal-700 border-teal-200',
  user: 'bg-slate-100 text-slate-500 border-slate-200',
}

export default function AdminUsersPage() {
  const [rows, setRows] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    fetch(apiUrl('/api/admin/platform/users'), { credentials: 'include' })
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

  const q = search.trim().toLowerCase()
  const filtered = q
    ? rows.filter((r) =>
        r.email.toLowerCase().includes(q) ||
        (r.name ?? '').toLowerCase().includes(q)
      )
    : rows

  return (
    <div>
      <h1 className="mb-1 text-[1.5rem] font-bold text-[#0F172A]">Users</h1>
      <p className="mb-4 text-[13px] text-[#64748B]">{rows.length} total user{rows.length !== 1 ? 's' : ''}</p>

      <input
        type="search"
        placeholder="Search by name or email…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="mb-4 w-full max-w-sm rounded-lg border border-[#E2E8F0] bg-white px-3 py-2 text-[13px] placeholder-[#94A3B8] focus:border-teal-400 focus:outline-none"
      />

      <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
        {/* Desktop */}
        <div className="hidden overflow-x-auto lg:block">
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                {['Name', 'Email', 'Role', 'Joined Collectives', 'Owned Collectives', 'Registered'].map((h) => (
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
                  <td className="px-4 py-3 text-[13px] font-medium text-[#0F172A]">{row.name ?? '—'}</td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.email}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${ROLE_COLORS[row.role] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                      {row.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.joined_collectives}</td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">{row.owned_collectives}</td>
                  <td className="px-4 py-3 text-[13px] text-[#94A3B8]">
                    {new Date(row.created_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-[13px] text-[#94A3B8]">
                    {q ? 'No users match your search.' : 'No users yet.'}
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
                  <p className="text-[14px] font-semibold text-[#0F172A]">{row.name ?? row.email}</p>
                  <p className="text-[12px] text-[#64748B]">{row.email}</p>
                </div>
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${ROLE_COLORS[row.role] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                  {row.role}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[12px]">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Joined</p>
                  <p className="font-medium text-[#0F172A]">{row.joined_collectives}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Owned</p>
                  <p className="font-medium text-[#0F172A]">{row.owned_collectives}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Since</p>
                  <p className="font-medium text-[#0F172A]">
                    {new Date(row.created_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })}
                  </p>
                </div>
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="p-6 text-center text-[13px] text-[#94A3B8]">
              {q ? 'No users match your search.' : 'No users yet.'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
