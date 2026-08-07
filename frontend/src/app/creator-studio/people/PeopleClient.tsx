'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import type { AccessRequest, AccessPassAdminSummary, AddMemberResponse, CreatorMemberDetail, CreatorPathway, DirectMessageItem, ManualMember, ManualMemberPathwayAccess, MemberBookingItem, MemberPathwayAccessItem, MessageThreadDetail, SpaceInvitation } from '@/types/platform'
import { apiUrl } from '@/lib/api'
import { formatPathwayPrice } from '@/lib/pathwayAccess'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import { Button } from '@/components/platform/Button'
import { PlusIcon } from '@/components/creator/PrimaryActionLink'

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
      {count !== undefined && <span className="text-[13px] text-black">{count}</span>}
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
          <p className="mt-0.5 text-[13px] leading-relaxed text-black">
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
        <div className="flex-1 truncate rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-black select-all" title={inviteUrl}>
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
        <p className="mt-1 text-[11px] text-black">{priceLabel}</p>
      ) : item.access_source ? (
        <p className="mt-1 text-[11px] text-black capitalize">{item.access_source.replace(/_/g, ' ')}</p>
      ) : null}
      {item.access_state === 'accessible' && item.total_steps > 0 && (
        <div className="mt-2.5">
          <div className="mb-1 flex items-baseline justify-between text-[11px] text-black">
            <span>{item.completed_steps} of {item.total_steps} steps</span>
            <span>{item.progress_pct}%</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-teal-100">
            <div className="h-full rounded-full bg-teal-500 transition-all" style={{ width: `${item.progress_pct}%` }} />
          </div>
          <p className="mt-1.5 text-[11px] text-black">
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
            <p className="mt-1.5 text-[13px] text-black">The member now has access to this pathway.</p>
            <button onClick={onClose} className="mt-4 rounded-xl px-4 py-2 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
          </div>
        ) : (
          <>
            <h2 className="mb-4 text-[16px] font-semibold text-navy-900">Grant pathway access</h2>
            {fetching ? <p className="text-[13px] text-black">Loading pathways…</p>
              : pathways.length === 0 ? <p className="text-[13px] text-black">No paid pathways found. Manual grants are only available for paid pathways.</p>
              : (
                <div className="space-y-4">
                  <div>
                    <label className="mb-1 block text-[12px] font-semibold text-black">Pathway</label>
                    <select value={pathwayId} onChange={(e) => setPathwayId(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                      {pathways.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] font-semibold text-black">Notes (optional)</label>
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
                    <button onClick={onClose} className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-black hover:bg-slate-50">Cancel</button>
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
        <p className="text-[11px] font-semibold uppercase tracking-wide text-black">Pathway access</p>
        <button onClick={() => setShowGrant(true)}
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold transition-colors"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}>
          + Grant access
        </button>
      </div>
      {loading && <p className="text-[13px] italic text-black">Loading…</p>}
      {!loading && items?.length === 0 && (
        <div className="space-y-1">
          <p className="text-[13px] font-medium text-black">No pathway access yet.</p>
          <p className="text-[12px] text-black">Free and included pathways appear here once the member starts them.</p>
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
          user_id: member.id,
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
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl overflow-y-auto max-h-[90vh]">
        {success ? (
          <div className="py-4 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full text-xl"
              style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}>✓</div>
            <p className="text-[16px] font-semibold text-navy-900">Pass granted</p>
            <p className="mt-1 text-[13px] text-black">{member.display_name} now has an active pass.</p>
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
                  <label className="mb-1 block text-[12px] font-semibold text-black">Pathway</label>
                  <select value={selectedPathwaySlug} onChange={e => setSelectedPathwaySlug(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                    {pathways.map(p => <option key={p.slug} value={p.slug}>{p.title}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">
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
                ) : pathways.length === 0 ? (
                  <p className="text-[12px] text-black">No active pathways found in this collective.</p>
                ) : selectedPathwaySlug ? (
                  <p className="text-[12px] text-amber-600">
                    No published payment options for this pathway. Publish at least one option before granting a pass.
                  </p>
                ) : (
                  <p className="text-[12px] text-black">Select a pathway first.</p>
                )}
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Payment source</label>
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
                    <span className="text-[13px] text-black">AUD $</span>
                    <input type="number" min="0" step="0.01" value={paymentAmountStr}
                      onChange={e => setPaymentAmountStr(e.target.value)}
                      placeholder="0.00"
                      className="w-32 rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400" />
                  </div>
                )}
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Notes (optional)</label>
                <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)}
                  placeholder="Scholarship, special arrangement…"
                  className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400" />
              </div>
              {error && <p className="text-[12px] text-red-500">{error}</p>}
              <div className="flex gap-2 pt-1">
                <button onClick={handleSubmit} disabled={loading || !selectedOptionId}
                  className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: '#38A09E' }}>
                  {loading ? 'Granting…' : 'Grant pass'}
                </button>
                <button onClick={onClose} className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-black hover:bg-slate-50">Cancel</button>
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
  if (total === null) return <span className="text-[12px] text-black">Unlimited</span>
  const remaining = Math.max(0, total - used)
  const pct = total > 0 ? Math.round((remaining / total) * 100) : 0
  const barColour = pct > 40 ? '#38A09E' : pct > 15 ? '#F59E0B' : '#EF4444'
  return (
    <div className="mt-1.5">
      <p className="text-[12px] text-black">{remaining} of {total} sessions remaining</p>
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
        <p className="text-[11px] font-semibold uppercase tracking-wide text-black">Passes</p>
        <button onClick={() => setShowGrantModal(true)}
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold transition-colors"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}>
          + Grant pass
        </button>
      </div>
      {loading && <p className="text-[13px] italic text-black">Loading…</p>}
      {!loading && passes?.length === 0 && (
        <p className="text-[13px] text-black">No passes yet.</p>
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
                  <p className="mt-0.5 text-[11px] text-black">Valid until {validUntil}</p>
                )}
                <MemberPassCreditBar used={pass.used_credits} total={pass.total_credits} />
                {pass.credits_per_week && (
                  <p className="mt-1 text-[11px] text-black">{pass.credits_per_week} sessions/week</p>
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
// Book session modal
// ---------------------------------------------------------------------------

interface ActivePassInfo {
  pass_id: string
  option_name: string | null
  pathway_title: string | null
  total_credits: number | null
  used_credits: number
  remaining_credits: number | null
  credits_per_week: number | null
  valid_from: string | null
  valid_until: string | null
  status: string
}

interface SpaceEvent {
  id: string
  title: string
  starts_at: string
  location_type: string
}

// ---------------------------------------------------------------------------
// BookSessionModal — single session or recurring (book regular sessions)
// ---------------------------------------------------------------------------

const WEEKDAY_PLURAL: Record<number, string> = {
  0: 'Mondays', 1: 'Tuesdays', 2: 'Wednesdays', 3: 'Thursdays',
  4: 'Fridays', 5: 'Saturdays', 6: 'Sundays',
}

interface RecurringResultItem {
  event_id: string
  event_title: string
  starts_at: string
  booking_id: string | null
  status: 'booked' | 'skipped'
  reason: string | null
}

interface RecurringResult {
  booked: RecurringResultItem[]
  skipped: RecurringResultItem[]
  pass_summary: {
    pass_id: string
    option_name: string | null
    total_credits: number | null
    used_credits: number
    remaining_credits: number | null
    credits_per_week: number | null
  } | null
}

interface EventPattern {
  key: string
  label: string
  events: SpaceEvent[]
}

function PassInfoCard({ pass, deductNote }: { pass: ActivePassInfo; deductNote?: string }) {
  return (
    <div className="rounded-xl border border-teal-100 bg-teal-50/40 px-3 py-2.5">
      <p className="text-[12px] font-semibold text-teal-700">{pass.option_name ?? 'Active pass'}</p>
      <p className="mt-0.5 text-[11px] text-black">
        {pass.remaining_credits ?? '?'} of {pass.total_credits ?? '?'} sessions remaining
        {pass.credits_per_week ? ` · ${pass.credits_per_week}/week` : ''}
      </p>
      {pass.valid_until && (
        <p className="mt-0.5 text-[11px] text-black">
          Valid until {new Date(pass.valid_until).toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })}
        </p>
      )}
      {deductNote && <p className="mt-1.5 text-[11px] text-teal-600">{deductNote}</p>}
    </div>
  )
}

function BookSessionModal({ spaceSlug, member, onClose, onBooked }: {
  spaceSlug: string
  member: CreatorMemberDetail
  onClose: () => void
  onBooked: () => void
}) {
  // Shared data
  const [events, setEvents] = useState<SpaceEvent[]>([])
  const [activePass, setActivePass] = useState<ActivePassInfo | null | undefined>(undefined)
  const [bookView, setBookView] = useState<'single' | 'recurring'>('single')

  // Single-session state
  const [selectedEventId, setSelectedEventId] = useState('')
  const [mode, setMode] = useState<'pass' | 'override'>('pass')
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  // Recurring state
  const [recurringMode, setRecurringMode] = useState<'pass' | 'override'>('pass')
  const [selectedPatterns, setSelectedPatterns] = useState<Set<string>>(new Set())
  const [recurringNote, setRecurringNote] = useState('')
  const [recurringLoading, setRecurringLoading] = useState(false)
  const [recurringError, setRecurringError] = useState<string | null>(null)
  const [recurringResult, setRecurringResult] = useState<RecurringResult | null>(null)

  useEffect(() => {
    Promise.all([
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : []),
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/active-pass`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : null)
        .catch(() => null),
    ]).then(([eventsData, passData]: [SpaceEvent[], ActivePassInfo | null]) => {
      const now = new Date()
      const upcoming = (eventsData || []).filter((e: SpaceEvent) => new Date(e.starts_at) > now)
      setEvents(upcoming)
      if (upcoming.length > 0) setSelectedEventId(upcoming[0].id)
      setActivePass(passData)
      if (!passData) { setMode('override'); setRecurringMode('override') }
    }).catch(() => { setEvents([]); setActivePass(null); setMode('override'); setRecurringMode('override') })
  }, [spaceSlug, member.id])

  // Compute event patterns from upcoming events, filtered by pass dates if in pass mode
  const eligibleEvents = useMemo(() => {
    if (recurringMode !== 'pass' || !activePass) return events
    const from = activePass.valid_from ? new Date(activePass.valid_from) : null
    const until = activePass.valid_until ? new Date(activePass.valid_until) : null
    return events.filter(e => {
      const d = new Date(e.starts_at)
      if (from && d < from) return false
      if (until && d > until) return false
      return true
    })
  }, [events, recurringMode, activePass])

  const patterns = useMemo((): EventPattern[] => {
    const map = new Map<string, SpaceEvent[]>()
    for (const ev of eligibleEvents) {
      const d = new Date(ev.starts_at)
      const weekday = d.getDay() // 0=Sun, 1=Mon…
      const jsWeekday = weekday // 0=Sun
      // Convert JS weekday (0=Sun) to Python weekday (0=Mon)
      const h = d.getHours().toString().padStart(2, '0')
      const m = d.getMinutes().toString().padStart(2, '0')
      const key = `${jsWeekday}|${h}:${m}`
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(ev)
    }
    return Array.from(map.entries()).map(([key, evs]) => {
      const d = new Date(evs[0].starts_at)
      const weekday = d.getDay()
      const weekdayName = WEEKDAY_PLURAL[weekday === 0 ? 6 : weekday - 1] ?? WEEKDAY_PLURAL[weekday]
      const timeStr = d.toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit', hour12: true })
      return { key, label: `${weekdayName} at ${timeStr}`, events: evs.sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime()) }
    }).sort((a, b) => new Date(a.events[0].starts_at).getTime() - new Date(b.events[0].starts_at).getTime())
  }, [eligibleEvents])

  const previewEvents = useMemo(() => {
    return patterns
      .filter(p => selectedPatterns.has(p.key))
      .flatMap(p => p.events)
      .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
  }, [patterns, selectedPatterns])

  function togglePattern(key: string) {
    setSelectedPatterns(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  // Single-session submit
  async function handleSubmit() {
    if (!selectedEventId) { setError('Select a session.'); return }
    if (mode === 'pass' && !activePass) { setError('No active pass found for this member.'); return }
    setError(null); setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${selectedEventId}/bookings/manual`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: member.id,
          use_pass: mode === 'pass',
          access_pass_id: mode === 'pass' ? activePass?.pass_id : null,
          note: note.trim() || null,
        }),
      })
      if (res.ok) { setSuccess(true); onBooked() }
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not book session.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setLoading(false) }
  }

  // Recurring submit
  async function handleRecurringSubmit() {
    if (previewEvents.length === 0) { setRecurringError('Select at least one session pattern.'); return }
    if (recurringMode === 'pass' && !activePass) { setRecurringError('No active pass found for this member.'); return }
    setRecurringError(null); setRecurringLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/bookings/recurring`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          event_ids: previewEvents.map(e => e.id),
          use_pass: recurringMode === 'pass',
          access_pass_id: recurringMode === 'pass' ? activePass?.pass_id : null,
          note: recurringNote.trim() || null,
        }),
      })
      if (res.ok) {
        const result: RecurringResult = await res.json()
        setRecurringResult(result)
        if (result.booked.length > 0) onBooked()
      } else {
        const body = await res.json().catch(() => ({}))
        setRecurringError(typeof body.detail === 'string' ? body.detail : 'Could not book sessions.')
      }
    } catch { setRecurringError('Something went wrong. Please try again.') }
    finally { setRecurringLoading(false) }
  }

  const CloseBtn = () => (
    <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
    </button>
  )

  const ModeToggle = ({ value, onChange }: { value: 'pass' | 'override'; onChange: (v: 'pass' | 'override') => void }) => (
    <div>
      <label className="mb-1.5 block text-[12px] font-semibold text-black">Booking mode</label>
      <div className="flex gap-2">
        <button type="button" onClick={() => onChange('pass')}
          className={`flex-1 rounded-xl border px-3 py-2.5 text-[12px] font-semibold transition-colors ${value === 'pass' ? 'border-teal-400 bg-teal-50 text-teal-700' : 'border-slate-200 text-slate-500 hover:border-slate-300'}`}>
          Use member pass
        </button>
        <button type="button" onClick={() => onChange('override')}
          className={`flex-1 rounded-xl border px-3 py-2.5 text-[12px] font-semibold transition-colors ${value === 'override' ? 'border-amber-400 bg-amber-50 text-amber-700' : 'border-slate-200 text-slate-500 hover:border-slate-300'}`}>
          Manual override
        </button>
      </div>
    </div>
  )

  const PassSection = ({ passMode }: { passMode: 'pass' | 'override' }) => (
    <>
      {passMode === 'pass' && (
        <div>
          {activePass === undefined && <p className="text-[12px] text-black">Loading pass info…</p>}
          {activePass === null && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5">
              <p className="text-[12px] font-semibold text-amber-700">No active pass</p>
              <p className="mt-0.5 text-[11px] text-amber-600">This member has no active pass. Use Manual override or grant them a pass first.</p>
            </div>
          )}
          {activePass && <PassInfoCard pass={activePass} deductNote="Sessions will be deducted from this pass." />}
        </div>
      )}
      {passMode === 'override' && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 px-3 py-2.5">
          <p className="text-[11px] text-amber-700">No sessions will be deducted from the member&apos;s pass.</p>
        </div>
      )}
    </>
  )

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl overflow-y-auto max-h-[90vh]">

        {/* ── Single session success ── */}
        {bookView === 'single' && success ? (
          <div className="py-4 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full text-xl"
              style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}>✓</div>
            <p className="text-[16px] font-semibold text-navy-900">Session booked</p>
            <p className="mt-1 text-[13px] text-black">
              {member.display_name} has been booked.
              {mode === 'pass' ? ' 1 session deducted from their pass.' : ' No sessions deducted (manual override).'}
            </p>
            <button onClick={onClose} className="mt-4 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
          </div>

        /* ── Recurring result ── */
        ) : bookView === 'recurring' && recurringResult ? (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[16px] font-semibold text-navy-900">Booking complete</h2>
              <CloseBtn />
            </div>
            <div className="space-y-4">
              {recurringResult.booked.length > 0 && (
                <div>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-teal-600">
                    Booked ({recurringResult.booked.length})
                  </p>
                  <div className="space-y-1">
                    {recurringResult.booked.map(item => (
                      <div key={item.event_id} className="flex items-center gap-2 rounded-lg bg-teal-50 px-3 py-1.5">
                        <span className="text-teal-500 text-[12px]">✓</span>
                        <div>
                          <span className="text-[12px] font-medium text-teal-800">{item.event_title}</span>
                          <span className="ml-2 text-[11px] text-black">
                            {new Date(item.starts_at).toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short' })}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {recurringResult.skipped.length > 0 && (
                <details open={recurringResult.booked.length === 0}>
                  <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-black hover:text-slate-600">
                    Skipped ({recurringResult.skipped.length})
                  </summary>
                  <div className="mt-2 space-y-1">
                    {recurringResult.skipped.map(item => (
                      <div key={item.event_id} className="rounded-lg bg-slate-50 px-3 py-1.5">
                        <span className="text-[12px] font-medium text-black">{item.event_title}</span>
                        <span className="ml-2 text-[11px] text-black">
                          {item.starts_at ? new Date(item.starts_at).toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short' }) : ''}
                        </span>
                        {item.reason && <p className="mt-0.5 text-[11px] text-black">{item.reason}</p>}
                      </div>
                    ))}
                  </div>
                </details>
              )}
              {recurringResult.pass_summary && (
                <div className="rounded-xl border border-teal-100 bg-teal-50/40 px-3 py-2.5">
                  <p className="text-[11px] font-semibold text-teal-700">Pass balance after booking</p>
                  <p className="mt-0.5 text-[11px] text-black">
                    {recurringResult.pass_summary.remaining_credits ?? '?'} of {recurringResult.pass_summary.total_credits ?? '?'} sessions remaining
                  </p>
                </div>
              )}
              <button onClick={onClose} className="w-full rounded-xl py-2.5 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
            </div>
          </div>

        ) : (
          <>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[16px] font-semibold text-navy-900">Book {member.display_name}</h2>
              <CloseBtn />
            </div>

            {/* ── View tabs ── */}
            <div className="mb-4 flex gap-1 rounded-xl bg-slate-100 p-1">
              <button type="button" onClick={() => setBookView('single')}
                className={`flex-1 rounded-lg py-1.5 text-[12px] font-semibold transition-colors ${bookView === 'single' ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
                Single session
              </button>
              <button type="button" onClick={() => setBookView('recurring')}
                className={`flex-1 rounded-lg py-1.5 text-[12px] font-semibold transition-colors ${bookView === 'recurring' ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
                Book regular sessions
              </button>
            </div>

            {/* ── Single session view ── */}
            {bookView === 'single' && (
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">Session</label>
                  {events.length === 0 ? (
                    <p className="text-[12px] text-black">No upcoming sessions found.</p>
                  ) : (
                    <select value={selectedEventId} onChange={e => setSelectedEventId(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-400">
                      {events.map(ev => (
                        <option key={ev.id} value={ev.id}>
                          {new Date(ev.starts_at).toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short' })} — {ev.title}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <ModeToggle value={mode} onChange={v => setMode(v)} />
                <PassSection passMode={mode} />
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">Note (optional)</label>
                  <textarea rows={2} value={note} onChange={e => setNote(e.target.value)}
                    placeholder="e.g. Regular Tuesday session, make-up booking…"
                    className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400" />
                </div>
                {error && <p className="text-[12px] text-red-500">{error}</p>}
                <div className="flex gap-2 pt-1">
                  <button onClick={handleSubmit}
                    disabled={loading || !selectedEventId || events.length === 0 || (mode === 'pass' && !activePass)}
                    className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ background: mode === 'override' ? '#B45309' : '#38A09E' }}>
                    {loading ? 'Booking…' : mode === 'pass' ? 'Book (use pass)' : 'Book (override)'}
                  </button>
                  <button onClick={onClose} className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-black hover:bg-slate-50">Cancel</button>
                </div>
              </div>
            )}

            {/* ── Recurring view ── */}
            {bookView === 'recurring' && (
              <div className="space-y-4">
                <ModeToggle value={recurringMode} onChange={v => { setRecurringMode(v); setSelectedPatterns(new Set()) }} />
                <PassSection passMode={recurringMode} />

                <div>
                  <label className="mb-2 block text-[12px] font-semibold text-black">
                    Select session patterns
                    {recurringMode === 'pass' && activePass?.valid_until && (
                      <span className="ml-1 font-normal text-black">
                        (showing sessions within pass dates)
                      </span>
                    )}
                  </label>
                  {activePass === undefined && <p className="text-[12px] text-black">Loading…</p>}
                  {patterns.length === 0 && activePass !== undefined && (
                    <p className="text-[12px] text-black">No eligible upcoming sessions found.</p>
                  )}
                  {patterns.length > 0 && (
                    <div className="space-y-2">
                      {patterns.map(pattern => (
                        <label key={pattern.key}
                          className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors ${selectedPatterns.has(pattern.key) ? 'border-teal-300 bg-teal-50' : 'border-slate-200 hover:border-slate-300'}`}>
                          <input type="checkbox" checked={selectedPatterns.has(pattern.key)} onChange={() => togglePattern(pattern.key)}
                            className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-teal-600" />
                          <div className="flex-1 min-w-0">
                            <p className="text-[13px] font-semibold text-navy-900">{pattern.label}</p>
                            <p className="text-[11px] text-black">
                              {pattern.events.length} session{pattern.events.length !== 1 ? 's' : ''}
                              {pattern.events.length > 0 && (
                                <> · {new Date(pattern.events[0].starts_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })}
                                  {' → '}{new Date(pattern.events[pattern.events.length - 1].starts_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })}</>
                              )}
                            </p>
                          </div>
                        </label>
                      ))}
                    </div>
                  )}
                </div>

                {previewEvents.length > 0 && (
                  <details open>
                    <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-black hover:text-slate-600">
                      Preview — {previewEvents.length} session{previewEvents.length !== 1 ? 's' : ''} selected
                    </summary>
                    <div className="mt-2 max-h-40 overflow-y-auto space-y-1 pr-1">
                      {previewEvents.map(ev => (
                        <div key={ev.id} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-1.5">
                          <span className="text-[11px] text-black w-24 shrink-0">
                            {new Date(ev.starts_at).toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short' })}
                          </span>
                          <span className="text-[12px] text-navy-900 truncate">{ev.title}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">Note (optional)</label>
                  <textarea rows={2} value={recurringNote} onChange={e => setRecurringNote(e.target.value)}
                    placeholder="e.g. Term 3 regular sessions"
                    className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-400" />
                </div>

                {recurringError && <p className="text-[12px] text-red-500">{recurringError}</p>}

                <div className="flex gap-2 pt-1">
                  <button onClick={handleRecurringSubmit}
                    disabled={recurringLoading || previewEvents.length === 0 || (recurringMode === 'pass' && !activePass)}
                    className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ background: recurringMode === 'override' ? '#B45309' : '#38A09E' }}>
                    {recurringLoading
                      ? 'Booking…'
                      : previewEvents.length === 0
                        ? 'Select sessions first'
                        : `Book ${previewEvents.length} session${previewEvents.length !== 1 ? 's' : ''}${recurringMode === 'pass' ? ' (use pass)' : ' (override)'}`}
                  </button>
                  <button onClick={onClose} className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-black hover:bg-slate-50">Cancel</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Gathering history (member detail)
// ---------------------------------------------------------------------------

function GatheringHistorySection({ member, spaceSlug }: { member: CreatorMemberDetail; spaceSlug: string }) {
  const [bookings, setBookings] = useState<MemberBookingItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [showBookModal, setShowBookModal] = useState(false)

  function loadBookings() {
    setLoading(true)
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}/bookings`), { credentials: 'include' })
      .then((r) => r.ok ? r.json() : [])
      .then((data: MemberBookingItem[]) => setBookings(data))
      .catch(() => setBookings([]))
      .finally(() => setLoading(false))
  }

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
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-black">Gathering history</p>
        <button onClick={() => setShowBookModal(true)}
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold transition-colors"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}>
          + Book session
        </button>
      </div>
      {loading && <p className="text-[13px] italic text-black">Loading…</p>}
      {!loading && bookings?.length === 0 && (
        <p className="text-[13px] text-black">No gathering bookings yet.</p>
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
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-black">Past</p>
              <div className="flex flex-col gap-1.5">
                {past.map(b => (
                  <GatheringBookingRow key={b.booking_id} booking={b} />
                ))}
              </div>
            </div>
          )}
          {cancelled.length > 0 && (
            <details>
              <summary className="cursor-pointer text-[11px] text-black hover:text-slate-600">
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
      {showBookModal && (
        <BookSessionModal
          spaceSlug={spaceSlug}
          member={member}
          onClose={() => setShowBookModal(false)}
          onBooked={() => { setShowBookModal(false); loadBookings() }}
        />
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
      <p className="mt-0.5 text-[11px] text-black">
        {formatDateTime(booking.event_starts_at)} · {LOCATION_LABEL[booking.event_location_type] ?? booking.event_location_type}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Direct message modal (creator → member)
// ---------------------------------------------------------------------------

function DirectMessageModal({ member, spaceSlug, onClose }: {
  member: CreatorMemberDetail
  spaceSlug: string
  onClose: () => void
}) {
  const [thread, setThread]     = useState<MessageThreadDetail | null>(null)
  const [loading, setLoading]   = useState(true)
  const [body, setBody]         = useState('')
  const [sending, setSending]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  // Load existing thread (if any) by sending a zero-length probe — instead,
  // just list threads and find the one for this member.
  useEffect(() => {
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/messages`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then((threads: { thread_id: string; other_user_id: string }[]) => {
        const existing = threads.find(t => t.other_user_id === member.id)
        if (!existing) { setLoading(false); return }
        return fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/messages/${existing.thread_id}`), { credentials: 'include' })
          .then(r => r.ok ? r.json() : null)
          .then(data => { setThread(data); setLoading(false) })
      })
      .catch(() => setLoading(false))
  }, [member.id, spaceSlug])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [thread?.messages])

  // Mark creator's unread messages as read when modal opens
  useEffect(() => {
    if (thread) {
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/messages/${thread.thread_id}/read`), {
        method: 'POST', credentials: 'include',
      }).catch(() => {})
    }
  }, [thread?.thread_id, spaceSlug])

  async function handleSend() {
    const text = body.trim()
    if (!text) return
    setSending(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/messages`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ member_id: member.id, body: text }),
      })
      if (res.ok) {
        const data: MessageThreadDetail = await res.json()
        setThread(data)
        setBody('')
      } else {
        const data = await res.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'Could not send message.')
      }
    } catch { setError('Something went wrong.') }
    finally { setSending(false) }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  function formatTime(iso: string): string {
    const d = new Date(iso)
    const diffMin = Math.floor((Date.now() - d.getTime()) / 60000)
    if (diffMin < 1) return 'Just now'
    if (diffMin < 60) return `${diffMin}m ago`
    if (diffMin < 1440) return d.toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit' })
    return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
  }

  const messages: DirectMessageItem[] = thread?.messages ?? []

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 flex w-full max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl bg-white shadow-2xl" style={{ maxHeight: '85vh' }}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <p className="text-[15px] font-semibold text-navy-900">Message {member.display_name}</p>
            <p className="text-[12px] text-black">Direct message · private</p>
          </div>
          <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <p className="text-center text-[13px] text-black">Loading…</p>
          ) : messages.length === 0 ? (
            <p className="text-center text-[13px] text-black">
              No messages yet. Send the first message below.
            </p>
          ) : (
            <div className="space-y-3">
              {messages.map(msg => {
                const isMe = thread && msg.sender_id === thread.creator_id
                return (
                  <div key={msg.id} className={`flex ${isMe ? 'justify-end' : 'justify-start'}`}>
                    <div className={[
                      'max-w-[80%] rounded-2xl px-4 py-2.5',
                      isMe ? 'rounded-br-sm text-white' : 'rounded-bl-sm bg-slate-100 text-navy-900',
                    ].join(' ')}
                      style={isMe ? { background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' } : undefined}>
                      {!isMe && (
                        <p className="mb-0.5 text-[11px] font-semibold text-teal-700">{msg.sender_name}</p>
                      )}
                      <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{msg.body}</p>
                      <p className={`mt-0.5 text-right text-[10px] ${isMe ? 'text-white' : 'text-black'}`}>
                        {formatTime(msg.created_at)}
                      </p>
                    </div>
                  </div>
                )
              })}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="border-t border-border p-4">
          <textarea
            value={body}
            onChange={e => { setBody(e.target.value); setError(null) }}
            onKeyDown={handleKeyDown}
            placeholder={`Message ${member.display_name}…`}
            rows={2}
            className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2.5 text-[13px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
          />
          {error && <p className="mt-1 text-[11px] text-red-500">{error}</p>}
          <div className="mt-2 flex items-center justify-between">
            <p className="text-[11px] text-black">Enter to send</p>
            <button onClick={handleSend} disabled={!body.trim() || sending}
              className="rounded-xl px-4 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: '#38A09E' }}>
              {sending ? 'Sending…' : 'Send'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

// Member detail panel
// ---------------------------------------------------------------------------

function RemoveMemberModal({ member, spaceName, spaceSlug, onClose, onRemoved }: {
  member: CreatorMemberDetail
  spaceName: string
  spaceSlug: string
  onClose: () => void
  onRemoved: () => void
}) {
  const [removing, setRemoving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRemove() {
    setRemoving(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/members/${member.id}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (res.ok) {
        onRemoved()
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not remove member. Please try again.')
      }
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setRemoving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.45)' }}>
      <div className="w-full max-w-sm rounded-2xl border border-border bg-white shadow-xl">
        <div className="px-6 py-5">
          <h3 className="text-[16px] font-semibold text-navy-900">
            Remove from {spaceName}?
          </h3>
          <p className="mt-3 text-[14px] leading-relaxed text-black">
            <span className="font-medium">{member.display_name}</span> will lose access to this
            collective, including pathways and member content. Their Fresh Collective account will
            not be deleted.
          </p>
          {error && (
            <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
              {error}
            </p>
          )}
        </div>
        <div className="flex gap-2 border-t border-border px-6 py-4">
          <button
            onClick={handleRemove}
            disabled={removing}
            className="flex-1 rounded-xl px-4 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ background: '#dc2626' }}
          >
            {removing ? 'Removing…' : 'Remove member'}
          </button>
          <button
            onClick={onClose}
            disabled={removing}
            className="flex-1 rounded-xl border border-border px-4 py-2.5 text-[14px] font-medium text-black hover:bg-slate-50 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

function MemberDetailPanel({ member, onClose, spaceSlug, spaceName, onMemberRemoved }: {
  member: CreatorMemberDetail
  onClose: () => void
  spaceSlug: string
  spaceName: string
  onMemberRemoved: (userId: string) => void
}) {
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [showMessage, setShowMessage]     = useState(false)

  return (
    <>
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
              <p className="mt-0.5 text-[12px] text-black">{member.email}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-5">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-black">Status</p>
              <span className="mt-1 inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}>
                Active
              </span>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-black">Role</p>
              <div className="mt-1"><RoleBadge role={member.space_role} /></div>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-black">Joined</p>
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

          {/* Message member */}
          <div className="border-t border-border pt-4">
            <button
              onClick={() => setShowMessage(true)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-1.5 text-[12px] font-semibold text-black transition-colors hover:border-teal-300 hover:text-teal-700"
            >
              <svg width="13" height="11" viewBox="0 0 13 11" fill="none" aria-hidden="true">
                <rect x="0.5" y="0.5" width="12" height="9" rx="1.5" stroke="currentColor"/>
                <path d="M1 3l5.5 3.5L12 3" stroke="currentColor" strokeLinecap="round"/>
              </svg>
              Message member
            </button>
          </div>

          {/* Remove member */}
          <div className="border-t border-border pt-4">
            <button
              onClick={() => setConfirmRemove(true)}
              className="text-[13px] font-medium text-red-500 transition-colors hover:text-red-700"
            >
              Remove from collective…
            </button>
          </div>
        </div>
      </div>

      {confirmRemove && (
        <RemoveMemberModal
          member={member}
          spaceName={spaceName}
          spaceSlug={spaceSlug}
          onClose={() => setConfirmRemove(false)}
          onRemoved={() => onMemberRemoved(member.id)}
        />
      )}

      {showMessage && (
        <DirectMessageModal
          member={member}
          spaceSlug={spaceSlug}
          onClose={() => setShowMessage(false)}
        />
      )}
    </>
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
  const [firstName, setFirstName]         = useState('')
  const [lastName, setLastName]           = useState('')
  const [email, setEmail]                 = useState('')
  const [role, setRole]                   = useState('learner')
  const [note, setNote]                   = useState('')
  const [paymentOptions, setPaymentOptions] = useState<{ id: string; name: string }[]>([])
  const [paymentOptionId, setPaymentOptionId] = useState('')
  const [paymentStatus, setPaymentStatus] = useState('unpaid')
  const [loading, setLoading]             = useState(false)
  const [error, setError]                 = useState<string | null>(null)
  const [result, setResult]               = useState<AddMemberResponse | null>(null)

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

  useEffect(() => {
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/payment-options`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then(data => setPaymentOptions(Array.isArray(data) ? data.filter((o: { status?: string }) => o.status === 'published') : []))
      .catch(() => {})
  }, [spaceSlug])

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
        body: JSON.stringify({
          email: trimmedEmail,
          first_name: firstName.trim() || null,
          last_name: lastName.trim() || null,
          role,
          note: note.trim() || null,
          payment_option_id: paymentOptionId || null,
          payment_status: paymentStatus,
        }),
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
    added_as_member:        { icon: '✓', color: '#0f766e', bg: 'rgba(56,160,158,0.10)' },
    pending_invite_created: { icon: '✉', color: '#0f766e', bg: 'rgba(56,160,158,0.10)' },
    invite_created:         { icon: '✉', color: '#0f766e', bg: 'rgba(56,160,158,0.10)' },
    already_member:         { icon: '·', color: '#64748b', bg: 'rgba(148,163,184,0.12)' },
    invite_already_pending: { icon: '·', color: '#64748b', bg: 'rgba(148,163,184,0.12)' },
  }

  const resultTitle: Record<string, string> = {
    added_as_member:        'Added to collective',
    pending_invite_created: 'Draft invitation created',
    invite_created:         'Invitation created',
    already_member:         'Already a member',
    invite_already_pending: 'Invite already pending',
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl bg-white p-6 shadow-xl" style={{ maxHeight: '90vh' }}>
        {result ? (
          <div className="py-4 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full text-lg"
              style={{ background: resultStyles[result.result]?.bg, color: resultStyles[result.result]?.color }}>
              {resultStyles[result.result]?.icon}
            </div>
            <p className="text-[16px] font-semibold text-navy-900">{resultTitle[result.result] ?? result.result}</p>
            <p className="mt-2 text-[13px] leading-relaxed text-black">{result.message}</p>
            {(result.result === 'pending_invite_created' || result.result === 'invite_created') && (
              <p className="mt-2 text-[11px] text-black">
                Use &quot;Send invite&quot; in the Pending invites section to email them their invitation link.
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
              <h2 className="text-[17px] font-semibold text-navy-900">Add member</h2>
              <button onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                aria-label="Close">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            <p className="mb-5 text-[13px] text-black">
              If they have an account, they&apos;ll be added immediately. Otherwise a draft invitation is created — no email sent until you click &quot;Send invite&quot;.
            </p>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">First name</label>
                  <input type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)}
                    placeholder="Jane"
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400" />
                </div>
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">Last name</label>
                  <input type="text" value={lastName} onChange={(e) => setLastName(e.target.value)}
                    placeholder="Smith"
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400" />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">
                  Email address <span className="font-normal text-red-400">*</span>
                </label>
                <input type="email" value={email} onChange={(e) => { setEmail(e.target.value); setError(null) }}
                  placeholder="jane@example.com"
                  className={`w-full rounded-lg border px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 ${error ? 'border-red-300' : 'border-slate-200'}`} />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Role</label>
                <select value={role} onChange={(e) => setRole(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400">
                  <option value="learner">Member</option>
                  <option value="moderator">Moderator</option>
                  <option value="creator">Leader</option>
                </select>
              </div>
              {paymentOptions.length > 0 && (
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">Offer / plan</label>
                  <select value={paymentOptionId} onChange={(e) => setPaymentOptionId(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400">
                    <option value="">None</option>
                    {paymentOptions.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Payment status</label>
                <select value={paymentStatus} onChange={(e) => setPaymentStatus(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400">
                  <option value="unpaid">Unpaid</option>
                  <option value="pending">Payment pending</option>
                  <option value="paid">Paid</option>
                  <option value="complimentary">Complimentary</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">
                  Note <span className="font-normal text-black">(optional)</span>
                </label>
                <textarea value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="Context about this person…"
                  rows={2}
                  className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400" />
              </div>
            </div>
            {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}
            <div className="mt-6 flex items-center gap-3">
              <Button
                variant="primary"
                size="md"
                fullWidth
                loading={loading}
                disabled={!email.trim()}
                iconStart={loading ? undefined : <PlusIcon />}
                onClick={handleSubmit}
              >
                {loading ? 'Adding…' : 'Add member'}
              </Button>
              <Button variant="secondary" size="md" onClick={onClose}>
                Cancel
              </Button>
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
        <p className="mt-0.5 truncate text-[12px] text-black">{request.user_email}</p>
        <p className="mt-0.5 text-[11px] text-black">Requested {formatDate(request.created_at)}</p>
      </div>
      <div className="flex shrink-0 gap-2">
        <button onClick={() => act('approve')} disabled={approving || declining}
          className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: '#38A09E' }}>
          {approving ? 'Approving…' : 'Approve'}
        </button>
        <button onClick={() => act('decline')} disabled={approving || declining}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-black hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-40">
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

function PendingInviteRow({ invite: initialInvite, spaceSlug, onCancelled }: {
  invite: SpaceInvitation; spaceSlug: string; onCancelled: () => void
}) {
  const [invite, setInvite]         = useState(initialInvite)
  const [cancelling, setCancelling] = useState(false)
  const [sending, setSending]       = useState(false)
  const [copied, setCopied]         = useState(false)
  const [error, setError]           = useState<string | null>(null)
  const [origin, setOrigin]         = useState('')

  useEffect(() => { setOrigin(window.location.origin) }, [])

  const inviteLink = origin ? `${origin}/invites/${invite.token}` : `/invites/${invite.token}`
  const isDraft = !invite.sent_at

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

  async function handleSend() {
    setSending(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/invitations/${invite.id}/send`),
        { method: 'POST', credentials: 'include' })
      if (res.ok) {
        const updated: SpaceInvitation = await res.json()
        setInvite(updated)
      } else {
        setError('Could not send invitation.')
      }
    } catch { setError('Something went wrong.') }
    finally { setSending(false) }
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
          {invite.name && <p className="mt-0.5 truncate text-[12px] text-black">{invite.email}</p>}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <RoleBadge role={invite.role} />
            {invite.payment_status && invite.payment_status !== 'unpaid' && (
              <PaymentStatusBadge status={invite.payment_status} />
            )}
            {isDraft ? (
              <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                style={{ background: 'rgba(251,191,36,0.14)', color: '#92400e' }}>
                Draft
              </span>
            ) : (
              <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                style={{ background: 'rgba(56,160,158,0.12)', color: '#0f766e' }}>
                Sent {formatDate(invite.sent_at!)}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {isDraft && (
            <button onClick={handleSend} disabled={sending}
              className="rounded-lg px-3 py-1 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: '#38A09E' }}>
              {sending ? 'Sending…' : 'Send invite'}
            </button>
          )}
          <button onClick={handleCancel} disabled={cancelling}
            className="rounded-lg border border-slate-200 px-3 py-1 text-[12px] font-medium text-black hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-40">
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        </div>
      </div>
      {origin && (
        <div className="mt-2.5 flex items-center gap-2 pl-12">
          <span className="flex-1 truncate rounded-md border border-slate-100 bg-slate-50 px-2.5 py-1 font-mono text-[11px] text-black select-all">
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
// Manual / Offline Members
// ---------------------------------------------------------------------------

const PAYMENT_STATUS_LABELS: Record<string, string> = {
  unpaid: 'Unpaid',
  pending: 'Payment pending',
  paid: 'Paid',
  complimentary: 'Complimentary',
}

const PAYMENT_STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  unpaid:        { bg: 'rgba(148,163,184,0.14)', color: '#64748b' },
  pending:       { bg: 'rgba(251,191,36,0.18)',  color: '#92400e' },
  paid:          { bg: 'rgba(56,160,158,0.14)',  color: '#0f766e' },
  complimentary: { bg: 'rgba(139,92,246,0.14)',  color: '#6d28d9' },
}

function StatusBadge({ status }: { status: ManualMember['status'] }) {
  if (status === 'managed') return (
    <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
      style={{ background: 'rgba(56,160,158,0.12)', color: '#0f766e' }}>
      Managed
    </span>
  )
  if (status === 'invited') return (
    <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
      style={{ background: 'rgba(251,191,36,0.16)', color: '#92400e' }}>
      Invited
    </span>
  )
  return (
    <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
      style={{ background: 'rgba(148,163,184,0.16)', color: '#64748b' }}>
      Offline
    </span>
  )
}

function PaymentStatusBadge({ status }: { status: string }) {
  const c = PAYMENT_STATUS_COLORS[status] ?? PAYMENT_STATUS_COLORS.unpaid
  return (
    <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
      style={{ background: c.bg, color: c.color }}>
      {PAYMENT_STATUS_LABELS[status] ?? status}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Managed member pathway access panel
// ---------------------------------------------------------------------------

function ManagedPathwaySection({ member, spaceSlug }: { member: ManualMember; spaceSlug: string }) {
  const [items, setItems]             = useState<ManualMemberPathwayAccess[] | null>(null)
  const [showGrant, setShowGrant]     = useState(false)
  const [allPathways, setAllPathways] = useState<CreatorPathway[]>([])
  const [grantSlug, setGrantSlug]     = useState('')
  const [grantNotes, setGrantNotes]   = useState('')
  const [granting, setGranting]       = useState(false)
  const [grantError, setGrantError]   = useState<string | null>(null)
  const [revoking, setRevoking]       = useState<string | null>(null)

  function load() {
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members/${member.id}/pathway-access`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then(data => setItems(data))
      .catch(() => setItems([]))
  }

  useEffect(() => { load() }, [member.id])

  useEffect(() => {
    if (showGrant && allPathways.length === 0) {
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : [])
        .then(data => {
          setAllPathways(data.filter((p: CreatorPathway) => p.status === 'active'))
          if (data.length > 0) setGrantSlug(data.filter((p: CreatorPathway) => p.status === 'active')[0]?.slug ?? '')
        })
        .catch(() => {})
    }
  }, [showGrant])

  async function handleGrant() {
    if (!grantSlug) return
    setGranting(true)
    setGrantError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members/${member.id}/pathway-access`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ pathway_slug: grantSlug, notes: grantNotes.trim() || null }),
      })
      if (res.ok) {
        setShowGrant(false)
        setGrantNotes('')
        load()
      } else {
        const body = await res.json().catch(() => ({}))
        setGrantError(typeof body.detail === 'string' ? body.detail : 'Could not grant access.')
      }
    } catch { setGrantError('Something went wrong.') }
    finally { setGranting(false) }
  }

  async function handleRevoke(pathwayId: string) {
    if (!confirm('Remove pathway access for this member?')) return
    setRevoking(pathwayId)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members/${member.id}/pathway-access/${pathwayId}`), {
        method: 'DELETE', credentials: 'include',
      })
      if (res.ok || res.status === 204) load()
    } catch { /* ignore */ }
    finally { setRevoking(null) }
  }

  const grantedIds = new Set(items?.map(i => i.pathway_id) ?? [])
  const availablePathways = allPathways.filter(p => !grantedIds.has(p.id))

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-black">Pathway access</p>
        <button onClick={() => setShowGrant(true)}
          className="text-[11px] font-semibold text-teal-600 hover:text-teal-800">
          + Grant access
        </button>
      </div>

      {items === null ? (
        <p className="text-[12px] text-black">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-[12px] text-black">No pathway access granted yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map(item => (
            <li key={item.grant_id} className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-[12px] font-medium text-navy-900">{item.pathway_title}</p>
                {item.notes && <p className="truncate text-[11px] text-black">{item.notes}</p>}
              </div>
              <button onClick={() => handleRevoke(item.pathway_id)}
                disabled={revoking === item.pathway_id}
                className="shrink-0 text-[11px] text-red-400 hover:text-red-600 disabled:opacity-40">
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {showGrant && (
        <>
          <div className="fixed inset-0 z-40 bg-black/40" onClick={() => setShowGrant(false)} />
          <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="mb-3 text-[15px] font-semibold text-navy-900">Grant pathway access</h3>
            {availablePathways.length === 0 ? (
              <p className="text-[13px] text-black">All active pathways have already been granted.</p>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">Pathway</label>
                  <select value={grantSlug} onChange={e => setGrantSlug(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400">
                    {availablePathways.map(p => <option key={p.id} value={p.slug}>{p.title}</option>)}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[12px] font-semibold text-black">Note <span className="font-normal text-black">(optional)</span></label>
                  <input value={grantNotes} onChange={e => setGrantNotes(e.target.value)} placeholder="e.g. Included in EMBODY package"
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] outline-none focus:border-teal-400" />
                </div>
                {grantError && <p className="text-[12px] text-red-500">{grantError}</p>}
                <div className="flex gap-2 pt-1">
                  <button onClick={handleGrant} disabled={granting || !grantSlug}
                    className="flex-1 rounded-xl py-2 text-[13px] font-semibold text-white disabled:opacity-50"
                    style={{ background: '#38A09E' }}>
                    {granting ? 'Granting…' : 'Grant access'}
                  </button>
                  <button onClick={() => setShowGrant(false)}
                    className="rounded-xl border border-border px-4 py-2 text-[12px] font-medium text-black hover:bg-slate-50">
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invite managed member (add email + create invitation link)
// ---------------------------------------------------------------------------

function InviteManagedMemberSection({ member, spaceSlug, onInvited }: {
  member: ManualMember
  spaceSlug: string
  onInvited: (updated: ManualMember) => void
}) {
  const [email, setEmail]       = useState(member.email ?? '')
  const [sending, setSending]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [done, setDone]         = useState(member.status === 'invited')
  const [origin, setOrigin]     = useState('')

  useEffect(() => { setOrigin(window.location.origin) }, [])

  async function handleInvite() {
    const trimmed = email.trim().toLowerCase()
    if (!trimmed || !trimmed.includes('@')) { setError('Enter a valid email address.'); return }
    setSending(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members/${member.id}/invite`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: trimmed }),
      })
      if (res.ok) {
        const updated: ManualMember = await res.json()
        setDone(true)
        onInvited(updated)
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not send invitation.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setSending(false) }
  }

  if (done) return (
    <div className="rounded-lg border border-teal-100 bg-teal-50 px-3 py-2.5">
      <p className="text-[12px] font-medium text-teal-700">Invitation created</p>
      <p className="mt-0.5 text-[11px] text-teal-600">
        An invitation link has been created for {member.email}. Share the invite link from the Pending Invites section above, or copy it from there.
      </p>
    </div>
  )

  return (
    <div>
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-black">Invite to platform</p>
      <p className="mb-2 text-[12px] text-black">
        Add an email address and create an invitation link. No email is sent automatically — you can share the link directly.
      </p>
      <div className="flex gap-2">
        <input type="email" value={email} onChange={e => { setEmail(e.target.value); setError(null) }}
          placeholder="jane@example.com"
          className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-[13px] outline-none focus:border-teal-400" />
        <button onClick={handleInvite} disabled={sending || !email.trim()}
          className="shrink-0 rounded-xl px-3 py-2 text-[12px] font-semibold text-white disabled:opacity-50"
          style={{ background: '#38A09E' }}>
          {sending ? 'Creating…' : 'Create invite'}
        </button>
      </div>
      {error && <p className="mt-1.5 text-[12px] text-red-500">{error}</p>}
    </div>
  )
}

function AddManualMemberModal({ spaceSlug, onClose, onCreated }: {
  spaceSlug: string
  onClose: () => void
  onCreated: (m: ManualMember) => void
}) {
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName]   = useState('')
  const [email, setEmail]         = useState('')
  const [phone, setPhone]         = useState('')
  const [passLabel, setPassLabel] = useState('')
  const [notes, setNotes]         = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  async function handleSubmit() {
    if (!firstName.trim()) { setError('First name is required.'); return }
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          first_name: firstName.trim(),
          last_name: lastName.trim() || null,
          email: email.trim() || null,
          phone: phone.trim() || null,
          pass_label: passLabel.trim() || null,
          notes: notes.trim() || null,
        }),
      })
      if (res.ok) {
        const created: ManualMember = await res.json()
        onCreated(created)
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not add member.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setLoading(false) }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl overflow-y-auto max-h-[90vh]">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-[17px] font-semibold text-navy-900">Add offline member</h2>
            <p className="mt-0.5 text-[12px] text-black">Name only required. You can assign passes, payment status, and pathway access after adding.</p>
          </div>
          <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          </button>
        </div>

        <div className="space-y-4">
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-[12px] font-semibold text-black">
                First name <span className="text-red-400">*</span>
              </label>
              <input value={firstName} onChange={e => setFirstName(e.target.value)} placeholder="Jane"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400" />
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-[12px] font-semibold text-black">
                Last name <span className="font-normal text-black">(optional)</span>
              </label>
              <input value={lastName} onChange={e => setLastName(e.target.value)} placeholder="Smith"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400" />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">
              Email <span className="font-normal text-black">(optional — no invite will be sent)</span>
            </label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="jane@example.com"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400" />
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">
              Phone <span className="font-normal text-black">(optional)</span>
            </label>
            <input type="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+61 400 000 000"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400" />
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">
              Member pass / option <span className="font-normal text-black">(optional)</span>
            </label>
            <input value={passLabel} onChange={e => setPassLabel(e.target.value)} placeholder="e.g. EMBODY Monthly, Full Access…"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400" />
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">
              Notes <span className="font-normal text-black">(optional)</span>
            </label>
            <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="e.g. Current client, joined via referral…"
              className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400" />
          </div>
          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button onClick={handleSubmit} disabled={loading || !firstName.trim()}
              className="flex-1 rounded-xl py-2.5 text-[14px] font-semibold text-white disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}>
              {loading ? 'Adding…' : 'Add offline member'}
            </button>
            <button onClick={onClose} className="rounded-xl border border-border px-4 py-2.5 text-[13px] font-medium text-black hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function EditManualMemberPanel({ member: initialMember, spaceSlug, onClose, onUpdated, onDeleted }: {
  member: ManualMember
  spaceSlug: string
  onClose: () => void
  onUpdated: (m: ManualMember) => void
  onDeleted: (id: string) => void
}) {
  const [member, setMember]       = useState(initialMember)
  const [firstName, setFirstName] = useState(member.first_name)
  const [lastName, setLastName]   = useState(member.last_name ?? '')
  const [phone, setPhone]         = useState(member.phone ?? '')
  const [passLabel, setPassLabel] = useState(member.pass_label ?? '')
  const [notes, setNotes]         = useState(member.notes ?? '')
  const [paymentStatus, setPaymentStatus] = useState(member.payment_status)
  const [paymentOptions, setPaymentOptions] = useState<{ id: string; name: string }[]>([])
  const [selectedOptionId, setSelectedOptionId] = useState(member.payment_option_id ?? '')
  const [saving, setSaving]       = useState(false)
  const [promoting, setPromoting] = useState(false)
  const [deleting, setDeleting]   = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const isManaged = member.status === 'managed' || member.status === 'invited'

  useEffect(() => {
    if (isManaged) {
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/payment-options`), { credentials: 'include' })
        .then(r => r.ok ? r.json() : [])
        .then((data: { id: string; name: string; status: string }[]) =>
          setPaymentOptions(data.filter(o => o.status === 'published'))
        )
        .catch(() => {})
    }
  }, [isManaged, spaceSlug])

  async function handleSave() {
    if (!firstName.trim()) { setError('First name is required.'); return }
    setError(null)
    setSaving(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members/${member.id}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          first_name: firstName.trim(),
          last_name: lastName.trim() || null,
          phone: phone.trim() || null,
          pass_label: passLabel.trim() || null,
          notes: notes.trim() || null,
          ...(isManaged ? {
            payment_option_id: selectedOptionId || null,
            payment_status: paymentStatus,
          } : {}),
        }),
      })
      if (res.ok) {
        const updated: ManualMember = await res.json()
        setMember(updated)
        onUpdated(updated)
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not save changes.')
      }
    } catch { setError('Something went wrong. Please try again.') }
    finally { setSaving(false) }
  }

  async function handlePromote() {
    setPromoting(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members/${member.id}/promote`), {
        method: 'POST', credentials: 'include',
      })
      if (res.ok) {
        const updated: ManualMember = await res.json()
        setMember(updated)
        onUpdated(updated)
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not promote member.')
      }
    } catch { setError('Something went wrong.') }
    finally { setPromoting(false) }
  }

  async function handleDelete() {
    if (!confirm(`Remove ${member.display_name} from this collective? This cannot be undone.`)) return
    setDeleting(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/manual-members/${member.id}`), {
        method: 'DELETE', credentials: 'include',
      })
      if (res.ok || res.status === 204) {
        onDeleted(member.id)
      } else {
        setError('Could not remove member.')
      }
    } catch { setError('Something went wrong.') }
    finally { setDeleting(false) }
  }

  return (
    <div className="rounded-2xl border border-border bg-white">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <h2 className="text-[15px] font-semibold text-navy-900">{member.display_name}</h2>
          <div className="mt-1 flex items-center gap-1.5">
            <StatusBadge status={member.status} />
            {member.status === 'offline' && (
              <span className="text-[11px] text-black">Not yet on platform</span>
            )}
            {member.status === 'managed' && (
              <span className="text-[11px] text-black">Managed — no login yet</span>
            )}
            {member.status === 'invited' && (
              <span className="text-[11px] text-black">Invitation pending</span>
            )}
          </div>
        </div>
        <button onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="space-y-4 px-5 py-5">
        {/* Core fields */}
        <div className="flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-black">First name</label>
            <input value={firstName} onChange={e => setFirstName(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400" />
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-black">Last name</label>
            <input value={lastName} onChange={e => setLastName(e.target.value)} placeholder="—"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 outline-none focus:border-teal-400" />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-black">Phone</label>
          <input type="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="—"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 outline-none focus:border-teal-400" />
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-black">Notes</label>
          <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)} placeholder="—"
            className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 outline-none focus:border-teal-400" />
        </div>

        {/* Managed-only: pass assignment + payment status */}
        {isManaged && (
          <>
            <div className="rounded-xl border border-slate-100 bg-slate-50 p-3 space-y-3">
              <div>
                <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-black">
                  Offer / pass
                </label>
                {paymentOptions.length > 0 ? (
                  <select value={selectedOptionId} onChange={e => setSelectedOptionId(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400">
                    <option value="">— None assigned —</option>
                    {paymentOptions.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                ) : (
                  <div>
                    <input value={passLabel} onChange={e => setPassLabel(e.target.value)} placeholder="e.g. EMBODY Monthly"
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-300 outline-none focus:border-teal-400" />
                    <p className="mt-1 text-[11px] text-black">No published offers yet — enter a label manually.</p>
                  </div>
                )}
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-black">Payment status</label>
                <select value={paymentStatus} onChange={e => setPaymentStatus(e.target.value as ManualMember['payment_status'])}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400">
                  <option value="unpaid">Unpaid</option>
                  <option value="pending">Payment pending</option>
                  <option value="paid">Paid</option>
                  <option value="complimentary">Complimentary</option>
                </select>
              </div>
            </div>
          </>
        )}

        {error && <p className="text-[12px] text-red-500">{error}</p>}
        <div className="flex gap-2">
          <button onClick={handleSave} disabled={saving}
            className="flex-1 rounded-xl py-2 text-[13px] font-semibold text-white disabled:opacity-50"
            style={{ background: '#38A09E' }}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>

        {/* Promote to managed (offline only) */}
        {member.status === 'offline' && (
          <div className="rounded-xl border border-teal-100 bg-teal-50/60 p-3">
            <p className="mb-1.5 text-[12px] font-semibold text-teal-800">Promote to managed member</p>
            <p className="mb-2 text-[11px] text-black">
              Unlock pass assignment, payment tracking, and pathway access. No email is sent and no login is created.
            </p>
            <button onClick={handlePromote} disabled={promoting}
              className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-teal-700 ring-1 ring-teal-300 hover:bg-teal-100 disabled:opacity-40">
              {promoting ? 'Promoting…' : 'Promote to managed member'}
            </button>
          </div>
        )}

        {/* Managed: pathway access */}
        {isManaged && (
          <div className="border-t border-border pt-4">
            <ManagedPathwaySection member={member} spaceSlug={spaceSlug} />
          </div>
        )}

        {/* Managed: invite to platform */}
        {(member.status === 'managed' || member.status === 'invited') && (
          <div className="border-t border-border pt-4">
            <InviteManagedMemberSection
              member={member}
              spaceSlug={spaceSlug}
              onInvited={(updated) => { setMember(updated); onUpdated(updated) }}
            />
          </div>
        )}

        <div className="border-t border-border pt-4">
          <button onClick={handleDelete} disabled={deleting}
            className="text-[13px] font-medium text-red-500 transition-colors hover:text-red-700 disabled:opacity-40">
            {deleting ? 'Removing…' : 'Remove from collective…'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface Props {
  members:        CreatorMemberDetail[]
  invitations:    SpaceInvitation[]
  accessRequests: AccessRequest[]
  manualMembers:  ManualMember[]
  spaceName:      string
  spaceSlug:      string
  spaceIsPublic:  boolean
  headerLocation: { name?: string; hero_artwork_url?: string | null; thumbnail_artwork_url?: string | null } | null
  headerCoverImageUrl: string | null
}

export default function PeopleClient({ members: initialMembers, invitations, accessRequests: initialAccessRequests, manualMembers: initialManualMembers, spaceName, spaceSlug, spaceIsPublic, headerLocation, headerCoverImageUrl }: Props) {
  const router = useRouter()
  const [membersList, setMembersList]                   = useState<CreatorMemberDetail[]>(initialMembers)
  const [manualMembersList, setManualMembersList]       = useState<ManualMember[]>(initialManualMembers)
  const [addPersonOpen, setAddPersonOpen]               = useState(false)
  const [selectedMember, setSelectedMember]             = useState<CreatorMemberDetail | null>(null)
  const [selectedManualMember, setSelectedManualMember] = useState<ManualMember | null>(null)
  const [search, setSearch]                             = useState('')
  const [accessRequests, setAccessRequests]             = useState<AccessRequest[]>(initialAccessRequests)

  function handleMemberRemoved(userId: string) {
    setMembersList((prev) => prev.filter((m) => m.id !== userId))
    setSelectedMember(null)
  }

  const existingMemberEmails = useMemo(
    () => new Set(membersList.map((m) => m.email.toLowerCase())),
    [membersList],
  )
  const existingInviteEmails = useMemo(
    () => new Set(invitations.map((i) => i.email.toLowerCase())),
    [invitations],
  )

  const filteredMembers = useMemo(() => {
    if (!search.trim()) return membersList
    const q = search.trim().toLowerCase()
    return membersList.filter((m) =>
      m.display_name.toLowerCase().includes(q) || m.email.toLowerCase().includes(q)
    )
  }, [membersList, search])

  const filteredManualMembers = useMemo(() => {
    if (!search.trim()) return manualMembersList
    const q = search.trim().toLowerCase()
    return manualMembersList.filter((m) =>
      m.display_name.toLowerCase().includes(q) ||
      (m.email ?? '').toLowerCase().includes(q) ||
      (m.pass_label ?? '').toLowerCase().includes(q)
    )
  }, [manualMembersList, search])

  function handleAddSuccess() {
    router.refresh()
  }

  function handleInviteCancelled() {
    router.refresh()
    if (selectedMember) setSelectedMember(null)
  }

  const now = new Date()
  const memberOnlyCount  = membersList.filter((m) => m.space_role === 'learner').length
  const leaderCount      = membersList.filter((m) => m.space_role === 'creator' || m.space_role === 'moderator').length

  return (
    <div className="w-full max-w-[1100px] space-y-8 px-8 py-8 md:px-10 md:py-10">

      <CollectiveArtworkHeader
        collectiveName={spaceName}
        sectionTitle="People"
        meta="Members, invitations and access for this collective."
        location={headerLocation}
        coverImageUrl={headerCoverImageUrl}
        action={
          <Button
            variant="primary"
            size="md"
            iconStart={<PlusIcon />}
            onClick={() => setAddPersonOpen(true)}
          >
            Add member
          </Button>
        }
      />

      {/* ── Stats ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
        {[
          { label: 'Active people',   value: membersList.length },
          { label: 'Members',         value: memberOnlyCount },
          { label: 'Leaders',         value: leaderCount },
          { label: 'Pending invites', value: invitations.length },
          { label: 'Offline / managed', value: manualMembersList.length },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-white p-4">
            <p className="font-serif text-2xl text-navy-900">{value}</p>
            <p className="mt-0.5 text-[13px] text-black">{label}</p>
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
              <p className="text-[14px] font-medium text-black">No pending access requests.</p>
              <p className="mt-1 text-[13px] text-black">
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
              <p className="text-[14px] font-medium text-black">No pending invites.</p>
              <p className="mt-1 text-[13px] text-black">
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

      {/* ── Offline / manual members ── */}
      <section>
        <div className="mb-3 flex items-center justify-between gap-3">
          <SectionHeading title="Offline &amp; managed members" count={manualMembersList.length} />
        </div>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
          <div className="min-w-0 flex-1 rounded-2xl border border-border bg-white">
            {filteredManualMembers.length === 0 ? (
              <div className="px-6 py-10 text-center">
                {manualMembersList.length === 0 ? (
                  <>
                    <p className="mb-1 text-[15px] font-semibold text-navy-900">No legacy offline members.</p>
                    <p className="text-[13px] text-black">
                      Use &quot;Add member&quot; to add new clients — they&apos;ll appear in Pending invites.
                    </p>
                  </>
                ) : (
                  <p className="text-[14px] text-black">No members match your search.</p>
                )}
              </div>
            ) : (
              <ul>
                {filteredManualMembers.map((m, i) => {
                  const isLast = i === filteredManualMembers.length - 1
                  const isSelected = selectedManualMember?.id === m.id
                  const offerLabel = m.payment_option_name ?? m.pass_label
                  return (
                    <li key={m.id}>
                      <button
                        onClick={() => {
                          setSelectedManualMember(isSelected ? null : m)
                          setSelectedMember(null)
                        }}
                        className={`w-full cursor-pointer text-left transition-colors ${!isLast ? 'border-b border-border' : ''} ${isSelected ? 'bg-slate-50' : 'hover:bg-slate-50/60'}`}
                        style={isSelected ? { borderLeft: '2px solid #94a3b8' } : undefined}
                      >
                        <div className="flex items-center gap-4 px-5 py-4">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
                            style={{ background: 'rgba(148,163,184,0.15)', color: '#64748b' }}>
                            {initials(m.display_name)}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[14px] font-medium text-navy-900">{m.display_name}</p>
                            <p className="mt-0.5 truncate text-[12px] text-black">
                              {m.email ?? (m.phone ?? 'No contact info')}
                            </p>
                          </div>
                          <div className="flex shrink-0 flex-wrap items-center gap-2">
                            {offerLabel && (
                              <span className="hidden rounded-full px-2 py-0.5 text-[10px] font-medium sm:inline"
                                style={{ background: 'rgba(56,160,158,0.09)', color: '#0f766e' }}>
                                {offerLabel}
                              </span>
                            )}
                            {(m.status === 'managed' || m.status === 'invited') && m.payment_status !== 'unpaid' && (
                              <PaymentStatusBadge status={m.payment_status} />
                            )}
                            <StatusBadge status={m.status} />
                          </div>
                        </div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {selectedManualMember && (
            <div className="w-full xl:w-[360px] xl:shrink-0">
              <EditManualMemberPanel
                member={selectedManualMember}
                spaceSlug={spaceSlug}
                onClose={() => setSelectedManualMember(null)}
                onUpdated={(updated) => {
                  setManualMembersList(prev => prev.map(m => m.id === updated.id ? updated : m))
                  setSelectedManualMember(updated)
                }}
                onDeleted={(id) => {
                  setManualMembersList(prev => prev.filter(m => m.id !== id))
                  setSelectedManualMember(null)
                }}
              />
            </div>
          )}
        </div>
      </section>

      {/* ── Current people ── */}
      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <SectionHeading title="Current people" count={membersList.length} />
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
                {membersList.length === 0 ? (
                  <>
                    <p className="mb-1 text-[15px] font-semibold text-navy-900">No members yet.</p>
                    <p className="text-[13px] text-black">Add your first person to get started.</p>
                  </>
                ) : (
                  <p className="text-[14px] text-black">No members match your search.</p>
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
                            <p className="mt-0.5 truncate text-[12px] text-black">{member.email}</p>
                          </div>
                          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                            <RoleBadge role={member.space_role} />
                            <span className="hidden text-[12px] text-black sm:inline">{formatDate(member.joined_at)}</span>
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
              <MemberDetailPanel
                member={selectedMember}
                onClose={() => setSelectedMember(null)}
                spaceSlug={spaceSlug}
                spaceName={spaceName}
                onMemberRemoved={handleMemberRemoved}
              />
            </div>
          )}
        </div>
      </section>

      <p className="text-[13px] text-black">
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
