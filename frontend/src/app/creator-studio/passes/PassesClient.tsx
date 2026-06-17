'use client'

import { useState, useEffect } from 'react'
import type { AccessPassAdminSummary, CreatorPathway, CreatorMemberDetail } from '@/types/platform'
import { apiUrl } from '@/lib/api'

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

interface PaymentOptionItem {
  id: string
  name: string
  total_sessions: number | null
  sessions_per_week: number | null
  term_start_date: string | null
  term_end_date: string | null
  effective_price_cents: number | null
  currency: string
  status: string
}

const SOURCE_OPTIONS = [
  { value: 'bank_transfer', label: 'Paid by bank transfer' },
  { value: 'cash', label: 'Paid by cash' },
  { value: 'complimentary', label: 'Complimentary' },
  { value: 'admin_grant', label: 'Admin / manual grant' },
  { value: 'test', label: 'Test' },
]

function GrantPassModal({ spaceSlug, onClose, onGranted }: {
  spaceSlug: string
  onClose: () => void
  onGranted: () => void
}) {
  const [members, setMembers] = useState<CreatorMemberDetail[]>([])
  const [memberSearch, setMemberSearch] = useState('')
  const [selectedMember, setSelectedMember] = useState<CreatorMemberDetail | null>(null)
  const [pathways, setPathways] = useState<CreatorPathway[]>([])
  const [selectedPathwaySlug, setSelectedPathwaySlug] = useState('')
  const [paymentOptions, setPaymentOptions] = useState<PaymentOptionItem[]>([])
  const [selectedOptionId, setSelectedOptionId] = useState('')
  const [source, setSource] = useState('bank_transfer')
  const [recordPayment, setRecordPayment] = useState(false)
  const [paymentAmountStr, setPaymentAmountStr] = useState('')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    Promise.all([
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : []),
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : []),
    ]).then(([membersData, pathwaysData]: [CreatorMemberDetail[], CreatorPathway[]]) => {
      setMembers(membersData)
      const paid = pathwaysData.filter(p => p.status === 'active' && ['one_time', 'subscription', 'included'].includes(p.access_type))
      setPathways(paid)
      if (paid.length > 0) setSelectedPathwaySlug(paid[0].slug)
    }).catch(() => {})
  }, [spaceSlug])

  useEffect(() => {
    if (!selectedPathwaySlug) return
    setPaymentOptions([])
    setSelectedOptionId('')
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${selectedPathwaySlug}/payment-options`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then((opts: PaymentOptionItem[]) => {
        const published = opts.filter(o => o.status === 'published')
        setPaymentOptions(published)
        if (published.length > 0) setSelectedOptionId(published[0].id)
      })
      .catch(() => {})
  }, [selectedPathwaySlug, spaceSlug])

  const filteredMembers = memberSearch.trim()
    ? members.filter(m =>
        m.display_name.toLowerCase().includes(memberSearch.toLowerCase()) ||
        m.email.toLowerCase().includes(memberSearch.toLowerCase())
      ).slice(0, 6)
    : []

  async function handleSubmit() {
    if (!selectedMember) { setError('Select a member.'); return }
    if (!selectedOptionId) { setError('Select a pass option before granting.'); return }
    const paymentAmountCents = recordPayment && paymentAmountStr
      ? Math.round(parseFloat(paymentAmountStr) * 100)
      : null
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/passes/grant`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: selectedMember.id,
          payment_option_id: selectedOptionId,
          source,
          notes: notes.trim() || null,
          also_grant_pathway_access: true,
          record_payment: recordPayment && !!paymentAmountCents,
          payment_amount_cents: paymentAmountCents,
        }),
      })
      if (res.ok) { setSuccess(true); onGranted() }
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not grant pass.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setLoading(false) }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl overflow-y-auto max-h-[90vh]">
        {success ? (
          <div className="py-4 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full text-xl"
              style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}>✓</div>
            <p className="text-[16px] font-semibold text-navy-900">Pass granted</p>
            <p className="mt-1 text-[13px] text-slate-500">
              {selectedMember?.display_name} now has an active pass.
            </p>
            <button onClick={onClose} className="mt-4 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
          </div>
        ) : (
          <>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[17px] font-semibold text-navy-900">Grant pass</h2>
              <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
              </button>
            </div>

            <div className="space-y-4">
              {/* Member search */}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-500">Member</label>
                {selectedMember ? (
                  <div className="flex items-center justify-between rounded-xl border border-teal-200 bg-teal-50/40 px-3 py-2">
                    <div>
                      <p className="text-[13px] font-semibold text-navy-900">{selectedMember.display_name}</p>
                      <p className="text-[11px] text-slate-500">{selectedMember.email}</p>
                    </div>
                    <button onClick={() => { setSelectedMember(null); setMemberSearch('') }}
                      className="text-[11px] text-slate-400 hover:text-slate-600">Change</button>
                  </div>
                ) : (
                  <div className="relative">
                    <input
                      type="text"
                      value={memberSearch}
                      onChange={e => setMemberSearch(e.target.value)}
                      placeholder="Search by name or email…"
                      className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400"
                    />
                    {filteredMembers.length > 0 && (
                      <ul className="absolute z-10 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg">
                        {filteredMembers.map(m => (
                          <li key={m.id}>
                            <button
                              type="button"
                              onClick={() => { setSelectedMember(m); setMemberSearch('') }}
                              className="w-full px-3 py-2.5 text-left hover:bg-teal-50/60 first:rounded-t-xl last:rounded-b-xl"
                            >
                              <p className="text-[13px] font-medium text-navy-900">{m.display_name}</p>
                              <p className="text-[11px] text-slate-500">{m.email}</p>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {memberSearch.trim() && filteredMembers.length === 0 && (
                      <p className="mt-1 text-[12px] text-slate-400">No members found.</p>
                    )}
                  </div>
                )}
              </div>

              {/* Pathway */}
              {pathways.length > 0 && (
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-slate-500">Pathway</label>
                  <select value={selectedPathwaySlug} onChange={e => setSelectedPathwaySlug(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                    {pathways.map(p => <option key={p.slug} value={p.slug}>{p.title}</option>)}
                  </select>
                </div>
              )}

              {/* Payment option */}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-500">
                  Pass option <span className="text-red-400">*</span>
                </label>
                {paymentOptions.length > 0 ? (
                  <select value={selectedOptionId} onChange={e => setSelectedOptionId(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                    {paymentOptions.map(o => (
                      <option key={o.id} value={o.id}>
                        {o.name}{o.total_sessions ? ` · ${o.total_sessions} sessions` : ''}
                      </option>
                    ))}
                  </select>
                ) : selectedPathwaySlug ? (
                  <p className="text-[12px] text-amber-600">
                    No published payment options for this pathway. Publish at least one option before granting a pass.
                  </p>
                ) : (
                  <p className="text-[12px] text-slate-400">Select a pathway first.</p>
                )}
              </div>

              {/* Payment source */}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-500">Payment source</label>
                <select value={source} onChange={e => setSource(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                  {SOURCE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>

              {/* Record payment */}
              <div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={recordPayment} onChange={e => setRecordPayment(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-400" />
                  <span className="text-[13px] text-navy-900">Record a payment amount</span>
                </label>
                {recordPayment && (
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-[13px] text-slate-500">AUD $</span>
                    <input type="number" min="0" step="0.01" value={paymentAmountStr}
                      onChange={e => setPaymentAmountStr(e.target.value)}
                      placeholder="0.00"
                      className="w-32 rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400" />
                  </div>
                )}
              </div>

              {/* Notes */}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-500">Notes (optional)</label>
                <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)}
                  placeholder="Scholarship, special arrangement…"
                  className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400" />
              </div>

              {error && <p className="text-[12px] text-red-500">{error}</p>}

              <div className="flex gap-2 pt-1">
                <button onClick={handleSubmit} disabled={loading || !selectedMember || !selectedOptionId}
                  className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: '#38A09E' }}>
                  {loading ? 'Granting…' : 'Grant pass'}
                </button>
                <button onClick={onClose} className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-slate-500 hover:bg-slate-50">Cancel</button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}

export default function PassesClient({ passes, spaceName, spaceSlug }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>('active')
  const [showGrantModal, setShowGrantModal] = useState(false)
  const [grantKey, setGrantKey] = useState(0)

  const filtered = statusFilter === 'all'
    ? passes
    : passes.filter(p => p.status === statusFilter)

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-2xl text-navy-900">Member Passes</h1>
          <p className="text-[14px] text-slate-500">{spaceName} · Member term passes and session balances</p>
        </div>
        <button
          onClick={() => setShowGrantModal(true)}
          className="mt-1 shrink-0 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Grant pass
        </button>
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
            Passes are created via Stripe checkout or by granting a pass manually.
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
                <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Sessions</th>
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

      {showGrantModal && (
        <GrantPassModal
          key={grantKey}
          spaceSlug={spaceSlug}
          onClose={() => setShowGrantModal(false)}
          onGranted={() => {
            setShowGrantModal(false)
            setGrantKey(k => k + 1)
          }}
        />
      )}
    </div>
  )
}
