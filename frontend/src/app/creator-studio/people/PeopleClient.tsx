'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import type { AccessRequest, AccessPassAdminSummary, AddMemberResponse, CreatorMemberDetail, CreatorPathway, MemberBookingItem, MemberPathwayAccessItem, SpaceInvitation } from '@/types/platform'
import { apiUrl } from '@/lib/api'
import { formatPathwayPrice } from '@/lib/pathwayAccess'

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

const ROLE_LABEL: Record<string, string> = {
  creator:   'Leader',
  moderator: 'Moderator',
  learner:   'Member',
}

const LOCATION_LABEL: Record<string, string> = {
  zoom: 'Zoom',
  in_person: 'In person',
  async_recorded: 'Recorded',
}

const ATTENDANCE_LABEL: Record<string, { label: string; bg: string; color: string }> = {
  attended:  { label: 'Attended',  bg: 'rgba(56,160,158,0.10)',  color: '#0f766e' },
  no_show:   { label: 'No show',   bg: 'rgba(239,68,68,0.08)',   color: '#b91c1c' },
  pending:   { label: 'Pending',   bg: 'rgba(148,163,184,0.12)', color: '#64748b' },
}

function roleBadgeStyle(role: string): { background: string; color: string } {
  if (role === 'creator')   return { background: 'rgba(14,116,144,0.10)',  color: '#0e7490' }
  if (role === 'moderator') return { background: 'rgba(99,102,241,0.09)',  color: '#6366f1' }
  return                           { background: 'rgba(56,160,158,0.09)',  color: '#38A09E' }
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function initials(name: string) {
  return name.split(' ').slice(0, 2).map((p) => p[0] ?? '').join('').toUpperCase()
}

// ---------------------------------------------------------------------------
// Small reusable pieces
// ---------------------------------------------------------------------------

function Avatar({ name, size = 9 }: { name: string; size?: number }) {
  return (
    <div
      className={`flex h-${size} w-${size} shrink-0 items-center justify-center rounded-full text-[11px] font-semibold`}
      style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}
    >
      {initials(name)}
    </div>
  )
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold" style={roleBadgeStyle(role)}>
      {ROLE_LABEL[role] ?? role}
    </span>
  )
}

function SectionHeading({ title, count }: { title: string; count?: number }) {
  return (
    <div className="mb-3 flex items-baseline gap-2">
      <h2 className="text-[16px] font-semibold text-navy-900">{title}</h2>
      {count !== undefined && <span className="text-[13px] text-slate-400">{count}</span>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invite link card
// ---------------------------------------------------------------------------

function InviteLinkCard({ spaceSlug, isPublic }: { spaceSlug: string; isPublic: boolean }) {
  const [origin, setOrigin] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => { setOrigin(window.location.origin) }, [])

  const inviteUrl = origin ? `${origin}/spaces/${spaceSlug}` : `/spaces/${spaceSlug}`

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(inviteUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard API unavailable */ }
  }

  return (
    <div className="rounded-2xl border border-border bg-white p-5">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <p className="text-[14px] font-semibold text-navy-900">Collective link</p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-slate-500">
            {isPublic
              ? 'People can view this collective and join if access is open. Share this link freely.'
              : 'This collective is private. Share this link — people can request access or accept a direct invite.'}
          </p>
        </div>
        {!isPublic && (
          <span className="mt-0.5 shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
            style={{ background: 'rgba(148,163,184,0.15)', color: '#64748b' }}>
            Private
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1 truncate rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-600 select-all" title={inviteUrl}>
          {inviteUrl}
        </div>
        <button onClick={copyLink}
          className="shrink-0 rounded-lg px-4 py-2 text-[13px] font-semibold transition-all"
          style={{ background: copied ? 'rgba(56,160,158,0.18)' : 'rgba(56,160,158,0.09)', color: '#38A09E' }}>
          {copied ? 'Copied!' : 'Copy link'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pathway access section (member detail)
// ---------------------------------------------------------------------------

const ACCESS_STATE_STYLE: Record<string, { background: string; color: string }> = {
  accessible:  { background: 'rgba(56,160,158,0.10)',  color: '#0f766e' },
  locked:      { background: 'rgba(148,163,184,0.14)', color: '#475569' },
  revoked:     { background: 'rgba(239,68,68,0.08)',   color: '#dc2626' },
  expired:     { background: 'rgba(234,179,8,0.12)',   color: '#a16207' },
  cancelled:   { background: 'rgba(148,163,184,0.14)', color: '#475569' },
  coming_soon: { background: 'rgba(234,179,8,0.12)',   color: '#a16207' },
  draft:       { background: 'rgba(99,102,241,0.10)',  color: '#6366f1' },
  archived:    { background: 'rgba(148,163,184,0.10)', color: '#64748b' },
}

function AccessPill({ state, label }: { state: string; label: string }) {
  const style = ACCESS_STATE_STYLE[state] ?? ACCESS_STATE_STYLE.locked
  return (
    <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold" style={style}>{label}</span>
  )
}

function PathwayAccessRow({ item, spaceSlug, userId, onRevoked }: {
  item: MemberPathwayAccessItem; spaceSlug: string; userId: string; onRevoked: () => void
}) {
  const [revoking, setRevoking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const priceLabel = item.access_state === 'locked' && item.price_cents
    ? formatPathwayPrice(item.price_cents, item.currency, item.billing_interval)
    : null
  const canRevoke = item.access_state === 'accessible' && item.access_source === 'manual_grant'

  async function handleRevoke() {
    if (!confirm(`Revoke access to "${item.title}" for this member?`)) return
    setRevoking(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${userId}/pathway-access/revoke`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ pathway_id: item.id }),
      })
      if (res.ok) onRevoked()
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not revoke access.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setRevoking(false) }
  }

  return (
    <div className="rounded-xl border border-border bg-white p-3.5">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[13px] font-medium leading-snug text-navy-900">{item.title}</p>
        <AccessPill state={item.access_state} label={item.access_label} />
      </div>
      {priceLabel ? (
        <p className="mt-1 text-[11px] text-slate-400">{priceLabel}</p>
      ) : item.access_source ? (
        <p className="mt-1 text-[11px] text-slate-400 capitalize">{item.access_source.replace(/_/g, ' ')}</p>
      ) : null}
      {item.access_state === 'accessible' && item.total_steps > 0 && (
        <div className="mt-2.5">
          <div className="mb-1 flex items-baseline justify-between text-[11px] text-slate-400">
            <span>{item.completed_steps} of {item.total_steps} steps</span>
            <span>{item.progress_pct}%</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-teal-100">
            <div className="h-full rounded-full bg-teal-500 transition-all" style={{ width: `${item.progress_pct}%` }} />
          </div>
          <p className="mt-1.5 text-[11px] text-slate-400">
            {item.last_activity_at ? `Last active: ${formatDate(item.last_activity_at)}` : 'No activity yet'}
          </p>
        </div>
      )}
      {canRevoke && (
        <div className="mt-2">
          <button onClick={handleRevoke} disabled={revoking}
            className="text-[11px] font-medium text-red-500 underline underline-offset-2 hover:opacity-70 disabled:opacity-40">
            {revoking ? 'Revoking…' : 'Revoke access'}
          </button>
        </div>
      )}
      {error && <p className="mt-1 text-[11px] text-red-500">{error}</p>}
    </div>
  )
}

interface PathwayOption { id: string; title: string; access_type: string }

function GrantAccessModal({ spaceSlug, userId, onClose, onGranted }: {
  spaceSlug: string; userId: string; onClose: () => void; onGranted: () => void
}) {
  const [pathways, setPathways] = useState<PathwayOption[]>([])
  const [pathwayId, setPathwayId] = useState('')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [fetching, setFetching] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways`), { credentials: 'include' })
      .then((r) => r.ok ? r.json() : [])
      .then((data: { id: string; title: string; access_type: string; status: string }[]) => {
        const paid = data.filter((p) => p.status === 'active' && ['one_time', 'subscription'].includes(p.access_type))
        setPathways(paid)
        if (paid.length > 0) setPathwayId(paid[0].id)
      })
      .catch(() => setPathways([]))
      .finally(() => setFetching(false))
  }, [spaceSlug])

  async function handleSubmit() {
    if (!pathwayId) return
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${userId}/pathway-access/grant`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ pathway_id: pathwayId, notes: notes.trim() || null }),
      })
      if (res.ok) { setSuccess(true); onGranted() }
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not grant access.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setLoading(false) }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl">
        {success ? (
          <div className="py-4 text-center">
            <p className="text-[16px] font-semibold text-navy-900">Access granted</p>
            <p className="mt-1.5 text-[13px] text-slate-500">The member now has access to this pathway.</p>
            <button onClick={onClose} className="mt-4 rounded-xl px-4 py-2 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
          </div>
        ) : (
          <>
            <h2 className="mb-4 text-[16px] font-semibold text-navy-900">Grant pathway access</h2>
            {fetching ? <p className="text-[13px] text-slate-400">Loading pathways…</p>
              : pathways.length === 0 ? <p className="text-[13px] text-slate-500">No paid pathways found. Manual grants are only available for paid pathways.</p>
              : (
                <div className="space-y-4">
                  <div>
                    <label className="mb-1 block text-[12px] font-semibold text-slate-500">Pathway</label>
                    <select value={pathwayId} onChange={(e) => setPathwayId(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                      {pathways.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] font-semibold text-slate-500">Notes (optional)</label>
                    <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                      placeholder="Reason for grant, e.g. scholarship, beta tester…"
                      className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400" />
                  </div>
                  {error && <p className="text-[12px] text-red-500">{error}</p>}
                  <div className="flex gap-2 pt-1">
                    <button onClick={handleSubmit} disabled={loading || !pathwayId}
                      className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50"
                      style={{ background: '#38A09E' }}>
                      {loading ? 'Granting…' : 'Grant access'}
                    </button>
                    <button onClick={onClose} className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-slate-500 hover:bg-slate-50">Cancel</button>
                  </div>
                </div>
              )}
          </>
        )}
      </div>
    </>
  )
}

function PathwayAccessSection({ member, spaceSlug }: { member: CreatorMemberDetail; spaceSlug: string }) {
  const [items, setItems] = useState<MemberPathwayAccessItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [showGrant, setShowGrant] = useState(false)

  function loadItems() {
    setLoading(true)
    setItems(null)
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/pathway-access`), { credentials: 'include' })
      .then((res) => res.ok ? res.json() : null)
      .then((data: MemberPathwayAccessItem[] | null) => setItems(data ?? []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setItems(null)
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/pathway-access`), { credentials: 'include' })
      .then((res) => res.ok ? res.json() : null)
      .then((data: MemberPathwayAccessItem[] | null) => { if (!cancelled) setItems(data ?? []) })
      .catch(() => { if (!cancelled) setItems([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [member.id, spaceSlug])

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Pathway access</p>
        <button onClick={() => setShowGrant(true)}
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold transition-colors"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}>
          + Grant access
        </button>
      </div>
      {loading && <p className="text-[13px] italic text-slate-400">Loading…</p>}
      {!loading && items?.length === 0 && (
        <div className="space-y-1">
          <p className="text-[13px] font-medium text-slate-500">No pathway access yet.</p>
          <p className="text-[12px] text-slate-400">Free and included pathways appear here once the member starts them.</p>
        </div>
      )}
      {!loading && items && items.length > 0 && (
        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <PathwayAccessRow key={item.id} item={item} spaceSlug={spaceSlug} userId={member.id} onRevoked={loadItems} />
          ))}
        </div>
      )}
      {showGrant && (
        <GrantAccessModal spaceSlug={spaceSlug} userId={member.id}
          onClose={() => setShowGrant(false)}
          onGranted={() => { setShowGrant(false); loadItems() }} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Grant pass to member modal (user pre-filled)
// ---------------------------------------------------------------------------

interface PaymentOptionItem {
  id: string
  name: string
  total_sessions: number | null
  sessions_per_week: number | null
  status: string
}

const PASS_SOURCE_OPTIONS = [
  { value: 'bank_transfer', label: 'Paid by bank transfer' },
  { value: 'cash', label: 'Paid by cash' },
  { value: 'complimentary', label: 'Complimentary' },
  { value: 'admin_grant', label: 'Admin / manual grant' },
  { value: 'test', label: 'Test' },
]

function GrantPassToMemberModal({ spaceSlug, member, onClose, onGranted }: {
  spaceSlug: string
  member: CreatorMemberDetail
  onClose: () => void
  onGranted: () => void
}) {
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
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then((data: CreatorPathway[]) => {
        const paid = data.filter(p => p.status === 'active' && ['one_time', 'subscription', 'included'].includes(p.access_type))
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
      }).catch(() => {})
  }, [selectedPathwaySlug, spaceSlug])

  async function handleSubmit() {
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
          user_id: member.id,
          payment_option_id: selectedOptionId || null,
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
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl overflow-y-auto max-h-[90vh]">
        {success ? (
          <div className="py-4 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full text-xl"
              style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}>✓</div>
            <p className="text-[16px] font-semibold text-navy-900">Pass granted</p>
            <p className="mt-1 text-[13px] text-slate-500">{member.display_name} now has an active pass.</p>
            <button onClick={onClose} className="mt-4 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
          </div>
        ) : (
          <>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[16px] font-semibold text-navy-900">Grant pass to {member.display_name}</h2>
              <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
              </button>
            </div>
            <div className="space-y-4">
              {pathways.length > 0 && (
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-slate-500">Pathway</label>
                  <select value={selectedPathwaySlug} onChange={e => setSelectedPathwaySlug(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                    {pathways.map(p => <option key={p.slug} value={p.slug}>{p.title}</option>)}
                  </select>
                </div>
              )}
              {paymentOptions.length > 0 && (
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-slate-500">Pass option</label>
                  <select value={selectedOptionId} onChange={e => setSelectedOptionId(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                    {paymentOptions.map(o => (
                      <option key={o.id} value={o.id}>
                        {o.name}{o.total_sessions ? ` · ${o.total_sessions} sessions` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {pathways.length === 0 && (
                <p className="text-[13px] text-slate-500">No active paid pathways found in this collective.</p>
              )}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-500">Payment source</label>
                <select value={source} onChange={e => setSource(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                  {PASS_SOURCE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
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
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-500">Notes (optional)</label>
                <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)}
                  placeholder="Scholarship, special arrangement…"
                  className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400" />
              </div>
              {error && <p className="text-[12px] text-red-500">{error}</p>}
              <div className="flex gap-2 pt-1">
                <button onClick={handleSubmit} disabled={loading}
                  className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50"
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

// ---------------------------------------------------------------------------
// Member passes section (in detail panel)
// ---------------------------------------------------------------------------

function MemberPassCreditBar({ used, total }: { used: number; total: number | null }) {
  if (total === null) return <span className="text-[12px] text-slate-400">Unlimited</span>
  const remaining = Math.max(0, total - used)
  const pct = total > 0 ? Math.round((remaining / total) * 100) : 0
  const barColour = pct > 40 ? '#38A09E' : pct > 15 ? '#F59E0B' : '#EF4444'
  return (
    <div className="mt-1.5">
      <p className="text-[12px] text-slate-500">{remaining} of {total} sessions remaining</p>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: barColour }} />
      </div>
    </div>
  )
}

const PASS_STATUS_STYLE: Record<string, { bg: string; color: string }> = {
  active:    { bg: 'rgba(56,160,158,0.10)',  color: '#0f766e' },
  pending:   { bg: 'rgba(234,179,8,0.12)',   color: '#a16207' },
  expired:   { bg: 'rgba(148,163,184,0.12)', color: '#475569' },
  cancelled: { bg: 'rgba(239,68,68,0.08)',   color: '#dc2626' },
}

function MemberPassesSection({ member, spaceSlug }: { member: CreatorMemberDetail; spaceSlug: string }) {
  const [passes, setPasses] = useState<AccessPassAdminSummary[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [showGrantModal, setShowGrantModal] = useState(false)

  function loadPasses() {
    setLoading(true)
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/passes`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then((data: AccessPassAdminSummary[]) => setPasses(data))
      .catch(() => setPasses([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/passes`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then((data: AccessPassAdminSummary[]) => { if (!cancelled) setPasses(data) })
      .catch(() => { if (!cancelled) setPasses([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [member.id, spaceSlug])

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Passes</p>
        <button onClick={() => setShowGrantModal(true)}
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold transition-colors"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}>
          + Grant pass
        </button>
      </div>
      {loading && <p className="text-[13px] italic text-slate-400">Loading…</p>}
      {!loading && passes?.length === 0 && (
        <p className="text-[13px] text-slate-400">No passes yet.</p>
      )}
      {!loading && passes && passes.length > 0 && (
        <div className="flex flex-col gap-2">
          {passes.map(pass => {
            const statusStyle = PASS_STATUS_STYLE[pass.status] ?? PASS_STATUS_STYLE.expired
            const validUntil = pass.valid_until
              ? new Date(pass.valid_until).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
              : null
            return (
              <div key={pass.id} className="rounded-xl border border-border bg-white p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[13px] font-medium text-navy-900">
                    {pass.option_name ?? pass.pathway_title ?? 'Pass'}
                  </p>
                  <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize" style={statusStyle}>
                    {pass.status}
                  </span>
                </div>
                {pass.pathway_title && pass.option_name && (
                  <p className="mt-0.5 text-[11px] text-teal-600">{pass.pathway_title}</p>
                )}
                {validUntil && (
                  <p className="mt-0.5 text-[11px] text-slate-400">Valid until {validUntil}</p>
                )}
                <MemberPassCreditBar used={pass.used_credits} total={pass.total_credits} />
                {pass.credits_per_week && (
                  <p className="mt-1 text-[11px] text-slate-400">{pass.credits_per_week} sessions/week</p>
                )}
              </div>
            )
          })}
        </div>
      )}
      {showGrantModal && (
        <GrantPassToMemberModal
          spaceSlug={spaceSlug}
          member={member}
          onClose={() => setShowGrantModal(false)}
          onGranted={() => { setShowGrantModal(false); loadPasses() }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Gathering history (member detail)
// ---------------------------------------------------------------------------

function GatheringHistorySection({ member, spaceSlug }: { member: CreatorMemberDetail; spaceSlug: string }) {
  const [bookings, setBookings] = useState<MemberBookingItem[] | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/bookings`), { credentials: 'include' })
      .then((r) => r.ok ? r.json() : [])
      .then((data: MemberBookingItem[]) => { if (!cancelled) setBookings(data) })
      .catch(() => { if (!cancelled) setBookings([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [member.id, spaceSlug])

  const now = new Date()
  const upcoming = bookings?.filter(b => new Date(b.event_starts_at) >= now && b.booking_status === 'confirmed') ?? []
  const past = bookings?.filter(b => new Date(b.event_starts_at) < now && b.booking_status === 'confirmed') ?? []
  const cancelled = bookings?.filter(b => b.booking_status === 'cancelled') ?? []

  return (
    <div>
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Gathering history</p>
      {loading && <p className="text-[13px] italic text-slate-400">Loading…</p>}
      {!loading && bookings?.length === 0 && (
        <p className="text-[13px] text-slate-400">No gathering bookings yet.</p>
      )}
      {!loading && bookings && bookings.length > 0 && (
        <div className="space-y-4">
          {upcoming.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-teal-600">Upcoming</p>
              <div className="flex flex-col gap-1.5">
                {upcoming.map(b => (
                  <GatheringBookingRow key={b.booking_id} booking={b} />
                ))}
              </div>
            </div>
          )}
          {past.length > 0 && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Past</p>
              <div className="flex flex-col gap-1.5">
                {past.map(b => (
                  <GatheringBookingRow key={b.booking_id} booking={b} />
                ))}
              </div>
            </div>
          )}
          {cancelled.length > 0 && (
            <details>
              <summary className="cursor-pointer text-[11px] text-slate-400 hover:text-slate-600">
                {cancelled.length} cancelled booking{cancelled.length !== 1 ? 's' : ''}
              </summary>
              <div className="mt-1.5 flex flex-col gap-1.5">
                {cancelled.map(b => (
                  <GatheringBookingRow key={b.booking_id} booking={b} />
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function GatheringBookingRow({ booking }: { booking: MemberBookingItem }) {
  const isCancelled = booking.booking_status === 'cancelled'
  const att = booking.attendance_status
  const attStyle = att ? ATTENDANCE_LABEL[att] : null

  return (
    <div className={`rounded-lg border border-border bg-white px-3 py-2.5 ${isCancelled ? 'opacity-50' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <p className={`text-[13px] font-medium leading-snug text-navy-900 ${isCancelled ? 'line-through' : ''}`}>
          {booking.event_title}
        </p>
        {attStyle && (
          <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold" style={{ background: attStyle.bg, color: attStyle.color }}>
            {attStyle.label}
          </span>
        )}
        {!attStyle && isCancelled && (
          <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{ background: 'rgba(0,0,0,0.06)', color: '#94a3b8' }}>
            Cancelled
          </span>
        )}
      </div>
      <p className="mt-0.5 text-[11px] text-slate-400">
        {formatDateTime(booking.event_starts_at)} · {LOCATION_LABEL[booking.event_location_type] ?? booking.event_location_type}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Member detail panel
// ---------------------------------------------------------------------------

function MemberDetailPanel({ member, onClose, spaceSlug }: {
  member: CreatorMemberDetail; onClose: () => void; spaceSlug: string
}) {
  return (
    <div className="rounded-2xl border border-border bg-white">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-[15px] font-semibold text-navy-900">Member details</h2>
        <button onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          aria-label="Close">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="space-y-5 px-5 py-5">
        <div className="flex items-center gap-3">
          <Avatar name={member.display_name} size={10} />
          <div>
            <p className="text-[15px] font-semibold text-navy-900">{member.display_name}</p>
            <p className="mt-0.5 text-[12px] text-slate-500">{member.email}</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Status</p>
            <span className="mt-1 inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}>
              Active
            </span>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Role</p>
            <div className="mt-1"><RoleBadge role={member.space_role} /></div>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Joined</p>
            <p className="mt-1 text-[13px] text-navy-900">{formatDate(member.joined_at)}</p>
          </div>
        </div>

        <div className="border-t border-border pt-4">
          <MemberPassesSection member={member} spaceSlug={spaceSlug} />
        </div>

        <div className="border-t border-border pt-4">
          <GatheringHistorySection member={member} spaceSlug={spaceSlug} />
        </div>

        <div className="border-t border-border pt-4">
          <PathwayAccessSection member={member} spaceSlug={spaceSlug} />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Add person modal (smart: add existing user or create invite)
// ---------------------------------------------------------------------------

function AddPersonModal({ spaceSlug, existingMemberEmails, existingInviteEmails, onClose, onSuccess }: {
  spaceSlug: string
  existingMemberEmails: Set<string>
  existingInviteEmails: Set<string>
  onClose: () => void
  onSuccess: () => void
}) {
  const [name, setName]   = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole]   = useState('learner')
  const [note, setNote]   = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [result, setResult]   = useState<AddMemberResponse | null>(null)

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

  async function handleSubmit() {
    setError(null)
    const trimmedEmail = email.trim().toLowerCase()
    if (!trimmedEmail || !EMAIL_RE.test(trimmedEmail)) {
      setError('Enter a valid email address.')
      return
    }
    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/add`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: trimmedEmail, name: name.trim() || null, role, note: note.trim() || null }),
      })
      const data: AddMemberResponse = await res.json()
      if (!res.ok) {
        setError(typeof (data as { detail?: string }).detail === 'string' ? (data as { detail?: string }).detail! : 'Something went wrong.')
        return
      }
      setResult(data)
      onSuccess()
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const resultStyles: Record<string, { icon: string; color: string; bg: string }> = {
    added_as_member:       { icon: '✓', color: '#0f766e', bg: 'rgba(56,160,158,0.10)' },
    invite_created:        { icon: '✉', color: '#0f766e', bg: 'rgba(56,160,158,0.10)' },
    already_member:        { icon: '·', color: '#64748b', bg: 'rgba(148,163,184,0.12)' },
    invite_already_pending:{ icon: '·', color: '#64748b', bg: 'rgba(148,163,184,0.12)' },
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl">
        {result ? (
          <div className="py-4 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full text-lg"
              style={{ background: resultStyles[result.result]?.bg, color: resultStyles[result.result]?.color }}>
              {resultStyles[result.result]?.icon}
            </div>
            <p className="text-[16px] font-semibold text-navy-900">
              {result.result === 'added_as_member' ? 'Added to collective' :
               result.result === 'invite_created' ? 'Invitation created' :
               result.result === 'already_member' ? 'Already a member' : 'Invite already pending'}
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-slate-500">{result.message}</p>
            {result.result === 'invite_created' && (
              <p className="mt-2 text-[11px] text-slate-400">
                Share the invite link from the Pending invites section. Email sending coming soon.
              </p>
            )}
            <button onClick={onClose}
              className="mt-5 rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}>
              Done
            </button>
          </div>
        ) : (
          <>
            <div className="mb-1 flex items-center justify-between">
              <h2 className="text-[17px] font-semibold text-navy-900">Add person</h2>
              <button onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                aria-label="Close">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            <p className="mb-5 text-[13px] text-slate-500">
              Add an existing Fresh Collective member directly, or invite someone by email.
            </p>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                  Email address <span className="font-normal text-slate-400">(required)</span>
                </label>
                <input type="email" value={email} onChange={(e) => { setEmail(e.target.value); setError(null) }}
                  placeholder="jane@example.com"
                  className={`w-full rounded-lg border px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 ${error ? 'border-red-300' : 'border-slate-200'}`} />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                  Name <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="Jane Smith"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Role</label>
                <select value={role} onChange={(e) => setRole(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400">
                  <option value="learner">Member</option>
                  <option value="moderator">Moderator</option>
                  <option value="creator">Leader</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                  Note <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <textarea value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="Context about this person…"
                  rows={2}
                  className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400" />
              </div>
            </div>
            {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}
            <div className="mt-6 flex items-center gap-3">
              <button disabled={!email.trim() || loading} onClick={handleSubmit}
                className="flex-1 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}>
                {loading ? 'Adding…' : 'Add person'}
              </button>
              <button onClick={onClose} className="rounded-xl border border-border px-4 py-2.5 text-[13px] font-medium text-slate-500 hover:bg-slate-50">
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Access request row
// ---------------------------------------------------------------------------

function AccessRequestRow({ request, spaceSlug, isLast, onResolved }: {
  request: AccessRequest; spaceSlug: string; isLast: boolean; onResolved: (id: string) => void
}) {
  const [approving, setApproving] = useState(false)
  const [declining, setDeclining] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function act(action: 'approve' | 'decline') {
    const setter = action === 'approve' ? setApproving : setDeclining
    setter(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/access-requests/${request.id}/${action}`),
        { method: 'POST', credentials: 'include' })
      if (res.ok) onResolved(request.id)
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : `Could not ${action} request.`)
      }
    } catch { setError('Something went wrong.') }
    finally { setter(false) }
  }

  return (
    <li className={`flex items-center gap-3 px-5 py-4 ${!isLast ? 'border-b border-border' : ''}`}>
      <Avatar name={request.user_display_name} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium text-navy-900">{request.user_display_name}</p>
        <p className="mt-0.5 truncate text-[12px] text-slate-500">{request.user_email}</p>
        <p className="mt-0.5 text-[11px] text-slate-400">Requested {formatDate(request.created_at)}</p>
      </div>
      <div className="flex shrink-0 gap-2">
        <button onClick={() => act('approve')} disabled={approving || declining}
          className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: '#38A09E' }}>
          {approving ? 'Approving…' : 'Approve'}
        </button>
        <button onClick={() => act('decline')} disabled={approving || declining}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-40">
          {declining ? 'Declining…' : 'Decline'}
        </button>
      </div>
      {error && <p className="text-[11px] text-red-500">{error}</p>}
    </li>
  )
}

// ---------------------------------------------------------------------------
// Pending invites section
// ---------------------------------------------------------------------------

function PendingInviteRow({ invite, spaceSlug, onCancelled }: {
  invite: SpaceInvitation; spaceSlug: string; onCancelled: () => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const [copied, setCopied]         = useState(false)
  const [error, setError]           = useState<string | null>(null)
  const [origin, setOrigin]         = useState('')

  useEffect(() => { setOrigin(window.location.origin) }, [])

  const inviteLink = origin ? `${origin}/invites/${invite.token}` : `/invites/${invite.token}`

  async function handleCancel() {
    if (!confirm(`Cancel invitation to ${invite.email}?`)) return
    setCancelling(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/invitations/${invite.id}`),
        { method: 'DELETE', credentials: 'include' })
      if (res.ok || res.status === 204) onCancelled()
      else setError('Could not cancel invitation.')
    } catch { setError('Something went wrong.') }
    finally { setCancelling(false) }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(inviteLink)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard unavailable */ }
  }

  const displayName = invite.name || invite.email

  return (
    <li className="border-b border-border px-5 py-4 last:border-0">
      <div className="flex items-center gap-3">
        <Avatar name={displayName} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-medium text-navy-900">{displayName}</p>
          {invite.name && <p className="mt-0.5 truncate text-[12px] text-slate-500">{invite.email}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <RoleBadge role={invite.role} />
          <span className="hidden text-[12px] text-slate-400 sm:inline">{formatDate(invite.created_at)}</span>
        </div>
        <button onClick={handleCancel} disabled={cancelling}
          className="shrink-0 rounded-lg border border-slate-200 px-3 py-1 text-[12px] font-medium text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-40">
          {cancelling ? 'Cancelling…' : 'Cancel'}
        </button>
      </div>
      {origin && (
        <div className="mt-2.5 flex items-center gap-2 pl-12">
          <span className="flex-1 truncate rounded-md border border-slate-100 bg-slate-50 px-2.5 py-1 font-mono text-[11px] text-slate-500 select-all">
            {inviteLink}
          </span>
          <button onClick={copyLink}
            className="shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold transition-all"
            style={{ background: copied ? 'rgba(56,160,158,0.18)' : 'rgba(56,160,158,0.09)', color: '#38A09E' }}>
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      )}
      {error && <p className="mt-1 text-[11px] text-red-500">{error}</p>}
    </li>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface Props {
  members:        CreatorMemberDetail[]
  invitations:    SpaceInvitation[]
  accessRequests: AccessRequest[]
  spaceName:      string
  spaceSlug:      string
  spaceIsPublic:  boolean
}

export default function PeopleClient({ members, invitations, accessRequests: initialAccessRequests, spaceName, spaceSlug, spaceIsPublic }: Props) {
  const router = useRouter()
  const [addPersonOpen, setAddPersonOpen]       = useState(false)
  const [selectedMember, setSelectedMember]     = useState<CreatorMemberDetail | null>(null)
  const [search, setSearch]                     = useState('')
  const [accessRequests, setAccessRequests]     = useState<AccessRequest[]>(initialAccessRequests)

  const existingMemberEmails = useMemo(
    () => new Set(members.map((m) => m.email.toLowerCase())),
    [members],
  )
  const existingInviteEmails = useMemo(
    () => new Set(invitations.map((i) => i.email.toLowerCase())),
    [invitations],
  )

  const filteredMembers = useMemo(() => {
    if (!search.trim()) return members
    const q = search.trim().toLowerCase()
    return members.filter((m) =>
      m.display_name.toLowerCase().includes(q) || m.email.toLowerCase().includes(q)
    )
  }, [members, search])

  function handleAddSuccess() {
    router.refresh()
  }

  function handleInviteCancelled() {
    router.refresh()
    if (selectedMember) setSelectedMember(null)
  }

  const now = new Date()
  const memberOnlyCount  = members.filter((m) => m.space_role === 'learner').length
  const leaderCount      = members.filter((m) => m.space_role === 'creator' || m.space_role === 'moderator').length

  return (
    <div className="w-full max-w-[1100px] space-y-8 px-8 py-8 md:px-10 md:py-10">

      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
            {spaceName}
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">People</h1>
          <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
            Manage members, invitations, and access for this collective.
          </p>
        </div>
        <button
          onClick={() => setAddPersonOpen(true)}
          className="mt-1 inline-flex shrink-0 items-center gap-2 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          Add person
        </button>
      </div>

      {/* ── Stats ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Active people',   value: members.length },
          { label: 'Members',         value: memberOnlyCount },
          { label: 'Leaders',         value: leaderCount },
          { label: 'Pending invites', value: invitations.length },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-white p-4">
            <p className="font-serif text-2xl text-navy-900">{value}</p>
            <p className="mt-0.5 text-[13px] text-slate-500">{label}</p>
          </div>
        ))}
      </div>

      {/* ── Collective link ── */}
      <InviteLinkCard spaceSlug={spaceSlug} isPublic={spaceIsPublic} />

      {/* ── Access requests ── */}
      <section>
        <SectionHeading title="Access requests" count={accessRequests.length} />
        <div className="rounded-2xl border border-border bg-white">
          {accessRequests.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <p className="text-[14px] font-medium text-slate-500">No pending access requests.</p>
              <p className="mt-1 text-[13px] text-slate-400">
                When someone requests to join a private collective, their request appears here.
              </p>
            </div>
          ) : (
            <ul>
              {accessRequests.map((req, i) => (
                <AccessRequestRow key={req.id} request={req} spaceSlug={spaceSlug} isLast={i === accessRequests.length - 1}
                  onResolved={(id) => setAccessRequests((prev) => prev.filter((r) => r.id !== id))} />
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* ── Pending invites ── */}
      <section>
        <SectionHeading title="Pending invites" count={invitations.length} />
        <div className="rounded-2xl border border-border bg-white">
          {invitations.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <p className="text-[14px] font-medium text-slate-500">No pending invites.</p>
              <p className="mt-1 text-[13px] text-slate-400">
                Invites you create will appear here until the person joins.
              </p>
            </div>
          ) : (
            <ul>
              {invitations.map((invite) => (
                <PendingInviteRow key={invite.id} invite={invite} spaceSlug={spaceSlug} onCancelled={handleInviteCancelled} />
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* ── Current people ── */}
      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <SectionHeading title="Current people" count={members.length} />
          <input
            type="text"
            placeholder="Search by name or email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
          />
        </div>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
          {/* Member list */}
          <div className="min-w-0 flex-1 rounded-2xl border border-border bg-white">
            {filteredMembers.length === 0 ? (
              <div className="px-6 py-10 text-center">
                {members.length === 0 ? (
                  <>
                    <p className="mb-1 text-[15px] font-semibold text-navy-900">No members yet.</p>
                    <p className="text-[13px] text-slate-400">Add your first person to get started.</p>
                  </>
                ) : (
                  <p className="text-[14px] text-slate-400">No members match your search.</p>
                )}
              </div>
            ) : (
              <ul>
                {filteredMembers.map((member, i) => {
                  const isLast = i === filteredMembers.length - 1
                  const isSelected = selectedMember?.id === member.id
                  return (
                    <li key={member.id}>
                      <button
                        onClick={() => setSelectedMember(isSelected ? null : member)}
                        className={`w-full cursor-pointer text-left transition-colors ${!isLast ? 'border-b border-border' : ''} ${isSelected ? 'bg-teal-50/50' : 'hover:bg-teal-50/30'}`}
                        style={isSelected ? { borderLeft: '2px solid rgba(56,160,158,0.45)' } : undefined}
                      >
                        <div className="flex items-center gap-4 px-5 py-4">
                          <Avatar name={member.display_name} />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[14px] font-medium text-navy-900">{member.display_name}</p>
                            <p className="mt-0.5 truncate text-[12px] text-slate-500">{member.email}</p>
                          </div>
                          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                            <RoleBadge role={member.space_role} />
                            <span className="hidden text-[12px] text-slate-400 sm:inline">{formatDate(member.joined_at)}</span>
                          </div>
                        </div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {/* Detail panel */}
          {selectedMember && (
            <div className="w-full xl:w-[360px] xl:shrink-0">
              <MemberDetailPanel member={selectedMember} onClose={() => setSelectedMember(null)} spaceSlug={spaceSlug} />
            </div>
          )}
        </div>
      </section>

      <p className="text-[13px] text-slate-500">
        <span className="font-medium">Private to creator admins.</span>{' '}
        Use member information respectfully and only for managing this collective.
      </p>

      {addPersonOpen && (
        <AddPersonModal
          spaceSlug={spaceSlug}
          existingMemberEmails={existingMemberEmails}
          existingInviteEmails={existingInviteEmails}
          onClose={() => setAddPersonOpen(false)}
          onSuccess={handleAddSuccess}
        />
      )}
    </div>
  )
}
