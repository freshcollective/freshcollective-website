'use client'

import Link from 'next/link'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { EventBooking, AddMemberResponse, SpaceSummary } from '@/types/platform'

// ---------------------------------------------------------------------------
// Exported types (used by layout.tsx + CreatorStudioShell.tsx)
// ---------------------------------------------------------------------------

export interface LiteGathering {
  id: string
  title: string
  starts_at: string
  booked_count: number
  capacity: number | null
  requires_booking: boolean
  is_published: boolean
}

export interface LiteInvitation {
  id: string
  email: string
  name: string | null
  role: string
  token: string
  created_at: string
}

export interface LiteAccessRequest {
  id: string
  user_display_name: string
  user_email: string
  created_at: string
  status: string
}

export interface LitePathway {
  id: string
  slug: string
  title: string
  status: string
  access_type: string
  price_cents: number | null
  currency: string | null
}

export interface LiteMember {
  id: string
  display_name: string
}

export interface LiteBillingData {
  planName: string
  monthlyPriceCents: number
  currency: string
  transactionFeeBasisPoints: number
  creatorBillingConnected: boolean
  memberPaymentsConnected: boolean
  stripeConnectConnected: boolean
  collectivesUsed: number
  collectiveLimit: number
}

export interface LiteData {
  pathwayCounts: { published: number; comingSoon: number; drafts: number; archived: number }
  publishedPathways: LitePathway[]
  allPathways: LitePathway[]
  upcomingGatherings: LiteGathering[]
  memberCount: number
  leaderCount: number
  members: LiteMember[]
  invitations: LiteInvitation[]
  accessRequests: LiteAccessRequest[]
  pendingInvites: number
  pendingRequests: number
  resourceCount: number
  billing: LiteBillingData | null
}

// ---------------------------------------------------------------------------
// Tab types
// ---------------------------------------------------------------------------

type Tab = 'overview' | 'gatherings' | 'people' | 'pathways' | 'resources' | 'payments' | 'settings'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview',   label: 'Overview' },
  { id: 'gatherings', label: 'Gatherings' },
  { id: 'people',     label: 'People' },
  { id: 'pathways',   label: 'Pathways' },
  { id: 'resources',  label: 'Resources' },
  { id: 'payments',   label: 'Payments' },
  { id: 'settings',   label: 'Settings' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string) {
  return (
    new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }) +
    ' · ' +
    new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  )
}

function formatShortDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function accessLabel(p: LitePathway): string {
  if (p.access_type === 'included' || p.access_type === 'free') return 'Free'
  if (p.access_type === 'one_time' && p.price_cents) {
    const d = p.price_cents / 100
    return `$${Number.isInteger(d) ? d : d.toFixed(2)} ${p.currency ?? 'AUD'}`
  }
  if (p.access_type === 'subscription' && p.price_cents) {
    const d = p.price_cents / 100
    return `$${Number.isInteger(d) ? d : d.toFixed(2)}/mo`
  }
  return 'Paid'
}

// ---------------------------------------------------------------------------
// Shared UI primitives
// ---------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">
      {children}
    </p>
  )
}

function Card({ children, accent }: { children: React.ReactNode; accent?: 'teal' | 'gold' }) {
  const accentStyle =
    accent === 'teal'
      ? { border: '1px solid rgba(56,160,158,0.18)', borderTop: '2px solid rgba(56,160,158,0.55)' }
      : accent === 'gold'
        ? { border: '1px solid rgba(212,176,72,0.22)', borderTop: '2px solid rgba(196,158,52,0.55)' }
        : { border: '1px solid rgba(0,0,0,0.07)' }
  return (
    <div
      className="overflow-hidden rounded-2xl bg-white"
      style={{ ...accentStyle, boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      {children}
    </div>
  )
}

function CardBody({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-4">{children}</div>
}

function TealBtn({
  onClick,
  disabled,
  children,
}: {
  onClick?: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
      style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
    >
      {children}
    </button>
  )
}

function GhostBtn({
  onClick,
  disabled,
  children,
  danger,
}: {
  onClick?: () => void
  disabled?: boolean
  children: React.ReactNode
  danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-xl border px-3.5 py-2 text-[12px] font-semibold transition-colors disabled:opacity-40 ${
        danger
          ? 'border-red-200 text-red-600 hover:bg-red-50'
          : 'border-slate-200 text-slate-600 hover:border-teal-200 hover:text-teal-700'
      }`}
    >
      {children}
    </button>
  )
}

function CopyButton({
  text,
  label = 'Copy',
  copiedLabel = '✓ Copied!',
}: {
  text: string
  label?: string
  copiedLabel?: string
}) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2200)
    })
  }
  return <GhostBtn onClick={handleCopy}>{copied ? copiedLabel : label}</GhostBtn>
}

function Toggle({
  value,
  onChange,
  label,
}: {
  value: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2.5">
      <span className="text-[13px] font-medium text-slate-700">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className="relative h-5 w-9 shrink-0 rounded-full transition-colors"
        style={{ background: value ? '#38A09E' : '#cbd5e1' }}
      >
        <span
          className="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
          style={{ left: value ? '1.125rem' : '0.125rem' }}
        />
      </button>
    </div>
  )
}

function AttendancePill({ status }: { status: string | null }) {
  const styles: Record<string, { label: string; bg: string; color: string }> = {
    attended: { label: 'Attended', bg: 'rgba(56,160,158,0.12)', color: '#0f766e' },
    no_show:  { label: 'No show',  bg: 'rgba(239,68,68,0.08)',  color: '#b91c1c' },
    pending:  { label: 'Pending',  bg: 'rgba(148,163,184,0.12)', color: '#64748b' },
  }
  const s = status && styles[status] ? styles[status] : styles.pending
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
      style={{ background: s.bg, color: s.color }}
    >
      {s.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

function TabNav({
  activeTab,
  onTabChange,
  pendingPeople,
}: {
  activeTab: Tab
  onTabChange: (tab: Tab) => void
  pendingPeople: number
}) {
  return (
    <div
      className="sticky top-0 z-20 flex overflow-x-auto border-b bg-white px-3 py-2"
      style={{ borderColor: 'rgba(0,0,0,0.07)', scrollbarWidth: 'none' }}
    >
      <div className="flex gap-1">
        {TABS.map(({ id, label }) => {
          const isActive = activeTab === id
          const badge = id === 'people' && pendingPeople > 0 ? pendingPeople : null
          return (
            <button
              key={id}
              type="button"
              onClick={() => onTabChange(id)}
              className="relative flex min-w-[72px] shrink-0 items-center justify-center gap-1 rounded-xl px-3 py-2 text-[12px] font-semibold transition-colors"
              style={
                isActive
                  ? { background: 'rgba(56,160,158,0.12)', color: '#0f766e' }
                  : { color: '#64748b' }
              }
            >
              {label}
              {badge !== null && (
                <span
                  className="flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[9px] font-bold text-white"
                  style={{ background: '#D97706' }}
                >
                  {badge}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// GatheringBookingsPanel
// ---------------------------------------------------------------------------

function GatheringBookingsPanel({
  gathering,
  spaceSlug,
  members,
  onClose,
}: {
  gathering: LiteGathering
  spaceSlug: string
  members: LiteMember[]
  onClose: () => void
}) {
  const [bookings, setBookings] = useState<EventBooking[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState('')
  const [addingBooking, setAddingBooking] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [attendanceBusy, setAttendanceBusy] = useState<string | null>(null)

  const isPast = new Date(gathering.starts_at) < new Date()

  useEffect(() => {
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${gathering.id}/bookings`), {
      credentials: 'include',
    })
      .then(r => (r.ok ? r.json() : []))
      .then((data: EventBooking[]) => setBookings(data))
      .catch(() => setBookings([]))
      .finally(() => setLoading(false))
  }, [gathering.id, spaceSlug])

  async function handleAddBooking() {
    if (!selectedUserId) return
    setAddingBooking(true)
    setAddError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/events/${gathering.id}/bookings/manual`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: selectedUserId, note: null }),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `HTTP ${res.status}`)
      }
      const listRes = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/events/${gathering.id}/bookings`),
        { credentials: 'include' },
      )
      if (listRes.ok) setBookings(await listRes.json())
      setShowAddForm(false)
      setSelectedUserId('')
    } catch (err) {
      setAddError(err instanceof Error ? err.message : 'Could not add booking.')
    } finally {
      setAddingBooking(false)
    }
  }

  async function handleCancelBooking(bookingId: string) {
    setCancellingId(bookingId)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/events/${gathering.id}/bookings/${bookingId}/cancel`),
        { method: 'POST', credentials: 'include' },
      )
      if (res.ok) {
        setBookings(
          prev =>
            prev?.map(b =>
              b.booking_id === bookingId ? { ...b, status: 'cancelled' as const } : b,
            ) ?? null,
        )
      }
    } finally {
      setCancellingId(null)
    }
  }

  async function handleAttendance(bookingId: string, status: string) {
    setAttendanceBusy(bookingId)
    try {
      const res = await fetch(
        apiUrl(
          `/api/creator/spaces/${spaceSlug}/events/${gathering.id}/bookings/${bookingId}/attendance`,
        ),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status }),
        },
      )
      if (res.ok) {
        const data = await res.json()
        setBookings(
          prev =>
            prev?.map(b =>
              b.booking_id === bookingId ? { ...b, attendance_status: data.attendance_status } : b,
            ) ?? null,
        )
      }
    } finally {
      setAttendanceBusy(null)
    }
  }

  const confirmed = bookings?.filter(b => b.status === 'confirmed') ?? []
  const cancelled = bookings?.filter(b => b.status === 'cancelled') ?? []
  const attendedCount = confirmed.filter(b => b.attendance_status === 'attended').length
  const noShowCount = confirmed.filter(b => b.attendance_status === 'no_show').length
  const availableMembers = members.filter(m => !confirmed.some(b => b.user_id === m.id))
  const capacityFull = gathering.capacity != null && confirmed.length >= gathering.capacity

  return (
    <div className="border-t bg-slate-50 px-4 pb-4 pt-4" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[12px] font-semibold text-navy-900">
          Bookings
          {bookings !== null && (
            <span className="ml-1.5 font-normal text-slate-400">
              {confirmed.length}
              {gathering.capacity != null ? ` / ${gathering.capacity}` : ''}
            </span>
          )}
        </p>
        <button
          onClick={onClose}
          className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] text-slate-500 hover:bg-slate-100"
        >
          Close ↑
        </button>
      </div>

      {isPast && confirmed.length > 0 && (
        <div className="mb-3 flex gap-4 text-[11px]">
          {attendedCount > 0 && <span style={{ color: '#0f766e' }}>{attendedCount} attended</span>}
          {noShowCount > 0 && <span style={{ color: '#b91c1c' }}>{noShowCount} no show</span>}
          {confirmed.length - attendedCount - noShowCount > 0 && (
            <span className="text-slate-400">
              {confirmed.length - attendedCount - noShowCount} not marked
            </span>
          )}
        </div>
      )}

      {loading && <p className="py-4 text-center text-[13px] text-slate-400">Loading bookings…</p>}
      {!loading && confirmed.length === 0 && !showAddForm && (
        <p className="mb-3 text-[13px] text-slate-400">No confirmed bookings yet.</p>
      )}

      {!loading && confirmed.length > 0 && (
        <div
          className="mb-3 divide-y overflow-hidden rounded-xl border bg-white"
          style={{ borderColor: 'rgba(0,0,0,0.08)' }}
        >
          {confirmed.map(b => (
            <div key={b.booking_id} className="px-4 py-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <p className="text-[13px] font-medium" style={{ color: '#152236' }}>
                      {b.name ?? b.email}
                    </p>
                    {isPast && <AttendancePill status={b.attendance_status ?? null} />}
                    {b.source === 'creator_manual' && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium text-slate-400"
                        style={{ background: 'rgba(0,0,0,0.05)' }}
                      >
                        Manual
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-slate-400">{b.email}</p>
                </div>
                <button
                  onClick={() => handleCancelBooking(b.booking_id)}
                  disabled={cancellingId === b.booking_id}
                  className="shrink-0 text-[11px] text-slate-400 underline hover:text-slate-600 disabled:opacity-50"
                >
                  {cancellingId === b.booking_id ? 'Removing…' : 'Remove'}
                </button>
              </div>
              {isPast && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {b.attendance_status !== 'attended' && (
                    <button
                      onClick={() => handleAttendance(b.booking_id, 'attended')}
                      disabled={attendanceBusy === b.booking_id}
                      className="rounded-md px-2.5 py-1 text-[11px] font-semibold disabled:opacity-40"
                      style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}
                    >
                      ✓ Attended
                    </button>
                  )}
                  {b.attendance_status !== 'no_show' && (
                    <button
                      onClick={() => handleAttendance(b.booking_id, 'no_show')}
                      disabled={attendanceBusy === b.booking_id}
                      className="rounded-md px-2.5 py-1 text-[11px] font-semibold disabled:opacity-40"
                      style={{ background: 'rgba(239,68,68,0.06)', color: '#b91c1c' }}
                    >
                      ✗ No show
                    </button>
                  )}
                  {b.attendance_status && b.attendance_status !== 'pending' && (
                    <button
                      onClick={() => handleAttendance(b.booking_id, 'pending')}
                      disabled={attendanceBusy === b.booking_id}
                      className="rounded-md px-2.5 py-1 text-[11px] text-slate-400 hover:text-slate-600 disabled:opacity-40"
                    >
                      Reset
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!loading && cancelled.length > 0 && (
        <details className="mb-3">
          <summary className="cursor-pointer text-[11px] text-slate-400 hover:text-slate-600">
            {cancelled.length} cancelled booking{cancelled.length !== 1 ? 's' : ''}
          </summary>
          <div className="mt-2 divide-y overflow-hidden rounded-xl border bg-white opacity-60">
            {cancelled.map(b => (
              <div key={b.booking_id} className="px-4 py-2.5">
                <p className="text-[12px] text-slate-400 line-through">{b.name ?? b.email}</p>
              </div>
            ))}
          </div>
        </details>
      )}

      {!loading && !isPast && !capacityFull && availableMembers.length > 0 && (
        <>
          {!showAddForm ? (
            <button
              onClick={() => setShowAddForm(true)}
              className="mt-1 text-[12px] font-semibold text-teal-600 hover:text-teal-700"
            >
              + Add booking
            </button>
          ) : (
            <div
              className="mt-2 rounded-xl border bg-white p-3.5"
              style={{ borderColor: 'rgba(56,160,158,0.20)' }}
            >
              <p className="mb-2.5 text-[12px] font-semibold text-navy-900">Add a booking</p>
              <select
                value={selectedUserId}
                onChange={e => {
                  setSelectedUserId(e.target.value)
                  setAddError(null)
                }}
                className="mb-2.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
              >
                <option value="">Select a member…</option>
                {availableMembers.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
              {addError && <p className="mb-2 text-[11px] text-red-500">{addError}</p>}
              <div className="flex gap-2">
                <button
                  onClick={handleAddBooking}
                  disabled={!selectedUserId || addingBooking}
                  className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-40"
                  style={{ background: '#38A09E' }}
                >
                  {addingBooking ? 'Adding…' : 'Confirm'}
                </button>
                <button
                  onClick={() => {
                    setShowAddForm(false)
                    setSelectedUserId('')
                    setAddError(null)
                  }}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] text-slate-500 hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {!loading && !isPast && capacityFull && (
        <p className="mt-1 text-[11px] text-slate-400">Session is at capacity.</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// AddPersonForm
// ---------------------------------------------------------------------------

function AddPersonForm({ spaceSlug, onDone }: { spaceSlug: string; onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState('learner')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AddMemberResponse | null>(null)

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
        body: JSON.stringify({ email: trimmedEmail, name: name.trim() || null, role, note: null }),
      })
      const data: AddMemberResponse = await res.json()
      if (!res.ok) {
        setError(
          typeof (data as { detail?: string }).detail === 'string'
            ? (data as { detail?: string }).detail!
            : 'Something went wrong.',
        )
        return
      }
      setResult(data)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const RESULT_LABEL: Record<string, string> = {
    added_as_member: 'Added to collective',
    invite_created: 'Invitation created',
    already_member: 'Already a member',
    invite_already_pending: 'Invite already pending',
  }
  const RESULT_COLOR: Record<string, string> = {
    added_as_member: '#0f766e',
    invite_created: '#0f766e',
    already_member: '#64748b',
    invite_already_pending: '#64748b',
  }

  if (result) {
    return (
      <div
        className="rounded-xl border bg-slate-50 px-4 py-4 text-center"
        style={{ borderColor: 'rgba(0,0,0,0.07)' }}
      >
        <p
          className="text-[14px] font-semibold"
          style={{ color: RESULT_COLOR[result.result] ?? '#152236' }}
        >
          {RESULT_LABEL[result.result] ?? result.result}
        </p>
        <p className="mt-1 text-[12px] text-slate-500">{result.message}</p>
        <button
          onClick={onDone}
          className="mt-3 rounded-xl px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Done
        </button>
      </div>
    )
  }

  return (
    <div
      className="space-y-3 rounded-xl border bg-slate-50 px-4 py-4"
      style={{ borderColor: 'rgba(56,160,158,0.18)' }}
    >
      <p className="text-[12px] font-semibold text-slate-600">
        Add an existing member directly, or invite someone by email.
      </p>
      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Email <span className="font-normal text-slate-400">(required)</span>
        </label>
        <input
          type="email"
          value={email}
          onChange={e => {
            setEmail(e.target.value)
            setError(null)
          }}
          placeholder="jane@example.com"
          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
        />
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Name <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Jane Smith"
          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
        />
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">Role</label>
        <select
          value={role}
          onChange={e => setRole(e.target.value)}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
        >
          <option value="learner">Member</option>
          <option value="moderator">Moderator</option>
          <option value="creator">Leader</option>
        </select>
      </div>
      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{error}</p>
      )}
      <div className="flex gap-2.5 pt-1">
        <button
          onClick={handleSubmit}
          disabled={!email.trim() || loading}
          className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {loading ? 'Adding…' : 'Add person'}
        </button>
        <button
          onClick={onDone}
          className="rounded-xl border border-slate-200 px-4 py-2.5 text-[13px] text-slate-500 hover:bg-slate-100"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// InviteRow
// ---------------------------------------------------------------------------

function InviteRow({
  invite,
  spaceSlug,
  onCancelled,
}: {
  invite: LiteInvitation
  spaceSlug: string
  onCancelled: (id: string) => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [origin, setOrigin] = useState('')
  useEffect(() => {
    setOrigin(window.location.origin)
  }, [])
  const inviteLink = origin ? `${origin}/invites/${invite.token}` : `/invites/${invite.token}`
  const ROLE_LABEL: Record<string, string> = {
    creator: 'Leader',
    moderator: 'Moderator',
    learner: 'Member',
  }

  async function handleCancel() {
    if (!confirm(`Cancel invitation to ${invite.email}?`)) return
    setCancelling(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/invitations/${invite.id}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (res.ok || res.status === 204) onCancelled(invite.id)
      else setError('Could not cancel invitation.')
    } catch {
      setError('Something went wrong.')
    } finally {
      setCancelling(false)
    }
  }

  return (
    <div className="flex items-start gap-3 px-5 py-3.5">
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
        style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}
      >
        {(invite.name ?? invite.email).charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium" style={{ color: '#152236' }}>
          {invite.name ?? invite.email}
        </p>
        <p className="truncate text-[11px] text-slate-400">
          {invite.email} · {ROLE_LABEL[invite.role] ?? invite.role}
        </p>
        <p className="mt-0.5 text-[11px] text-slate-400">
          Invited {formatShortDate(invite.created_at)}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <CopyButton text={inviteLink} label="Copy invite link" copiedLabel="✓ Copied!" />
          <GhostBtn onClick={handleCancel} disabled={cancelling} danger>
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </GhostBtn>
        </div>
        {error && <p className="mt-1 text-[11px] text-red-500">{error}</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AccessRequestRow
// ---------------------------------------------------------------------------

function AccessRequestRow({
  request,
  spaceSlug,
  onResolved,
}: {
  request: LiteAccessRequest
  spaceSlug: string
  onResolved: (id: string) => void
}) {
  const [approving, setApproving] = useState(false)
  const [declining, setDeclining] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function act(action: 'approve' | 'decline') {
    const setter = action === 'approve' ? setApproving : setDeclining
    setter(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/access-requests/${request.id}/${action}`),
        { method: 'POST', credentials: 'include' },
      )
      if (res.ok) onResolved(request.id)
      else {
        const body = await res.json().catch(() => ({}))
        setError(
          typeof body.detail === 'string' ? body.detail : `Could not ${action} request.`,
        )
      }
    } catch {
      setError('Something went wrong.')
    } finally {
      setter(false)
    }
  }

  return (
    <div className="flex items-start gap-3 px-5 py-3.5">
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
        style={{ background: 'rgba(212,176,72,0.14)', color: '#b08d2a' }}
      >
        {request.user_display_name.charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium" style={{ color: '#152236' }}>
          {request.user_display_name}
        </p>
        <p className="truncate text-[11px] text-slate-400">{request.user_email}</p>
        <p className="mt-0.5 text-[11px] text-slate-400">
          Requested {formatShortDate(request.created_at)}
        </p>
        <div className="mt-2 flex gap-2">
          <TealBtn onClick={() => act('approve')} disabled={approving || declining}>
            {approving ? 'Approving…' : 'Approve'}
          </TealBtn>
          <GhostBtn onClick={() => act('decline')} disabled={approving || declining} danger>
            {declining ? 'Declining…' : 'Decline'}
          </GhostBtn>
        </div>
        {error && <p className="mt-1 text-[11px] text-red-500">{error}</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Overview
// ---------------------------------------------------------------------------

function OverviewTab({
  activeSpace,
  slug,
  liteData,
}: {
  activeSpace: SpaceSummary
  slug: string
  liteData: LiteData
}) {
  const {
    memberCount,
    leaderCount,
    resourceCount,
    pathwayCounts,
    upcomingGatherings,
    invitations,
    accessRequests,
    billing,
  } = liteData

  const pendingTotal =
    invitations.length + accessRequests.filter(r => r.status === 'pending').length

  return (
    <div className="space-y-4">
      {/* Collective status */}
      <Card accent="teal">
        <CardBody>
          <SectionLabel>Your collective</SectionLabel>
          <p className="text-[16px] font-semibold leading-snug" style={{ color: '#152236' }}>
            {activeSpace.name}
          </p>
          {activeSpace.tagline && (
            <p className="mb-3 mt-1 text-[13px] leading-relaxed text-slate-500">
              {activeSpace.tagline}
            </p>
          )}
          <div className="mb-4 flex flex-wrap gap-2">
            <span
              className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              style={{
                background:
                  activeSpace.status === 'active'
                    ? 'rgba(56,160,158,0.10)'
                    : 'rgba(0,0,0,0.06)',
                color: activeSpace.status === 'active' ? '#38A09E' : '#64748b',
              }}
            >
              {activeSpace.status === 'active' ? 'Active' : 'Draft'}
            </span>
            <span
              className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              style={{ background: 'rgba(0,0,0,0.05)', color: '#64748b' }}
            >
              {activeSpace.is_public ? 'Public' : 'Private'}
            </span>
          </div>
          <div className="flex gap-2.5">
            <Link
              href={`/spaces/${slug}`}
              className="flex-1 rounded-xl px-4 py-2.5 text-center text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              View collective
            </Link>
            <CopyButton
              text={
                typeof window !== 'undefined'
                  ? `${window.location.origin}/spaces/${slug}`
                  : `/spaces/${slug}`
              }
              label="Copy link"
            />
          </div>
        </CardBody>
      </Card>

      {/* At a glance stats */}
      <Card>
        <CardBody>
          <SectionLabel>At a glance</SectionLabel>
          <div className="flex flex-wrap gap-x-6 gap-y-3">
            {[
              { value: memberCount, label: memberCount === 1 ? 'member' : 'members' },
              { value: leaderCount, label: leaderCount === 1 ? 'leader' : 'leaders' },
              { value: pathwayCounts.published, label: 'pathways' },
              { value: resourceCount, label: 'resources' },
            ].map(item => (
              <div key={item.label}>
                <p
                  className="text-[22px] font-semibold leading-none"
                  style={{ color: '#152236' }}
                >
                  {item.value}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">{item.label}</p>
              </div>
            ))}
            {pendingTotal > 0 && (
              <div>
                <p
                  className="text-[22px] font-semibold leading-none"
                  style={{ color: '#b08d2a' }}
                >
                  {pendingTotal}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">pending</p>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* Upcoming gatherings preview */}
      {upcomingGatherings.length > 0 && (
        <Card>
          <div className="border-b px-5 pb-3 pt-4" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            <SectionLabel>Upcoming gatherings</SectionLabel>
          </div>
          <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            {upcomingGatherings.slice(0, 3).map(g => (
              <div key={g.id} className="px-5 py-3.5">
                <p className="text-[13px] font-semibold leading-snug" style={{ color: '#152236' }}>
                  {g.title}
                </p>
                <p className="mt-0.5 text-[12px] text-slate-400">{formatDate(g.starts_at)}</p>
                {g.requires_booking && (
                  <p className="mt-0.5 text-[11px]" style={{ color: '#38A09E' }}>
                    {g.booked_count} booked
                    {g.capacity != null ? ` / ${g.capacity}` : ''}
                  </p>
                )}
              </div>
            ))}
          </div>
          {upcomingGatherings.length > 3 && (
            <div className="border-t px-5 py-3" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
              <p className="text-[12px] text-slate-400">
                +{upcomingGatherings.length - 3} more — see Gatherings tab
              </p>
            </div>
          )}
        </Card>
      )}

      {/* Browse as member */}
      <Card>
        <CardBody>
          <SectionLabel>Browse as member</SectionLabel>
          <div className="flex flex-wrap gap-2">
            {[
              { label: 'About', href: `/spaces/${slug}/about` },
              { label: 'Pathways', href: `/spaces/${slug}/pathways` },
              { label: 'Gatherings', href: `/spaces/${slug}/events` },
              { label: 'Resources', href: `/spaces/${slug}/resources` },
              { label: 'Community', href: `/spaces/${slug}/community` },
            ].map(link => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded-xl border border-slate-200 px-3.5 py-2 text-[12px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
              >
                {link.label}
              </Link>
            ))}
          </div>
        </CardBody>
      </Card>

      {/* Account status */}
      {billing && (
        <Card>
          <CardBody>
            <SectionLabel>Account</SectionLabel>
            <div className="flex flex-wrap gap-2">
              <span
                className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={
                  billing.creatorBillingConnected
                    ? { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
                    : { background: 'rgba(245,158,11,0.12)', color: '#92400e' }
                }
              >
                {billing.creatorBillingConnected ? '✓ Billing' : '! Billing not connected'}
              </span>
              <span
                className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={
                  billing.stripeConnectConnected
                    ? { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
                    : { background: 'rgba(245,158,11,0.12)', color: '#92400e' }
                }
              >
                {billing.stripeConnectConnected ? '✓ Stripe' : '! Stripe not connected'}
              </span>
              <span
                className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={{ background: 'rgba(0,0,0,0.05)', color: '#64748b' }}
              >
                {billing.planName}
              </span>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Gatherings — creation form + list
// ---------------------------------------------------------------------------

const LOCATION_TYPE_OPTIONS = [
  { value: 'zoom' as const, label: 'Zoom / Online' },
  { value: 'in_person' as const, label: 'In Person' },
  { value: 'async_recorded' as const, label: 'Recorded / Async' },
]

function AddGatheringForm({
  spaceSlug,
  onCreated,
  onClose,
}: {
  spaceSlug: string
  onCreated: (g: LiteGathering) => void
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [locationType, setLocationType] = useState<'zoom' | 'in_person' | 'async_recorded'>('zoom')
  const [locationUrl, setLocationUrl] = useState('')
  const [description, setDescription] = useState('')
  const [isPublished, setIsPublished] = useState(false)
  const [isPublic, setIsPublic] = useState(false)
  const [requiresBooking, setRequiresBooking] = useState(false)
  const [capacity, setCapacity] = useState('')
  const [bookingNote, setBookingNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const locationUrlLabel =
    locationType === 'zoom'
      ? 'Zoom / join link'
      : locationType === 'in_person'
        ? 'Location / address'
        : 'Recording URL'
  const locationUrlPlaceholder =
    locationType === 'zoom'
      ? 'https://zoom.us/j/…'
      : locationType === 'in_person'
        ? 'Address or venue name'
        : 'https://…'

  function validate(): string | null {
    if (!title.trim()) return 'Title is required.'
    if (!date) return 'Date is required.'
    if (!startTime) return 'Start time is required.'
    if (endTime && endTime <= startTime) return 'End time must be after start time.'
    if (requiresBooking && capacity) {
      const n = parseInt(capacity, 10)
      if (isNaN(n) || n <= 0) return 'Capacity must be a positive number.'
    }
    return null
  }

  async function handleCreate() {
    const validationError = validate()
    if (validationError) { setError(validationError); return }
    setSaving(true)
    setError(null)
    try {
      const startsAtISO = new Date(`${date}T${startTime}`).toISOString()
      const endsAtISO = endTime ? new Date(`${date}T${endTime}`).toISOString() : null
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          starts_at: startsAtISO,
          ends_at: endsAtISO,
          location_type: locationType,
          location_url: locationUrl.trim() || null,
          recording_url: null,
          is_published: isPublished,
          is_public: isPublic,
          requires_booking: requiresBooking,
          capacity: requiresBooking && capacity ? parseInt(capacity, 10) : null,
          booking_closes_at: null,
          booking_note: bookingNote.trim() || null,
        }),
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `HTTP ${res.status}`)
      }
      const data = await res.json()
      setDone(true)
      onCreated({
        id: data.id,
        title: data.title,
        starts_at: data.starts_at,
        booked_count: 0,
        capacity: data.capacity ?? null,
        requires_booking: data.requires_booking,
        is_published: data.is_published,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create gathering.')
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <div
        className="rounded-xl border bg-slate-50 px-4 py-5 text-center"
        style={{ borderColor: 'rgba(56,160,158,0.20)' }}
      >
        <p className="mb-1 text-[14px] font-semibold" style={{ color: '#0f766e' }}>
          Gathering created!
        </p>
        <p className="mb-3 text-[12px] text-slate-400">It has been added to the list below.</p>
        <button
          onClick={onClose}
          className="rounded-xl px-5 py-2 text-[13px] font-semibold text-white"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Done
        </button>
      </div>
    )
  }

  return (
    <div
      className="space-y-3.5 rounded-xl border bg-slate-50 px-4 py-4"
      style={{ borderColor: 'rgba(56,160,158,0.18)' }}
    >
      <p className="text-[13px] font-semibold text-slate-700">New gathering</p>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Title <span className="font-normal text-slate-400">(required)</span>
        </label>
        <input
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="e.g. Monthly Q&A"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
        />
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label className="mb-1 block text-[11px] font-semibold text-slate-500">Date</label>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-semibold text-slate-500">Start time</label>
          <input
            type="time"
            value={startTime}
            onChange={e => setStartTime(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          End time <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <input
          type="time"
          value={endTime}
          onChange={e => setEndTime(e.target.value)}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold text-slate-500">Format</label>
        <div className="flex flex-wrap gap-1.5">
          {LOCATION_TYPE_OPTIONS.map(lt => (
            <button
              key={lt.value}
              type="button"
              onClick={() => setLocationType(lt.value)}
              className="rounded-xl border px-3 py-1.5 text-[12px] font-semibold transition-colors"
              style={
                locationType === lt.value
                  ? {
                      background: 'rgba(56,160,158,0.10)',
                      border: '1px solid rgba(56,160,158,0.35)',
                      color: '#0f766e',
                    }
                  : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
              }
            >
              {lt.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          {locationUrlLabel} <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <input
          type="text"
          value={locationUrl}
          onChange={e => setLocationUrl(e.target.value)}
          placeholder={locationUrlPlaceholder}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
        />
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Description <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
        />
      </div>

      <Toggle value={isPublished} onChange={setIsPublished} label="Published" />
      <Toggle value={isPublic} onChange={setIsPublic} label="Public preview" />
      <Toggle value={requiresBooking} onChange={setRequiresBooking} label="Require booking" />

      {requiresBooking && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold text-slate-500">
            Capacity <span className="font-normal text-slate-400">(leave empty for unlimited)</span>
          </label>
          <input
            type="number"
            value={capacity}
            onChange={e => setCapacity(e.target.value)}
            min="1"
            placeholder="e.g. 20"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
          />
        </div>
      )}

      {requiresBooking && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold text-slate-500">
            Booking note <span className="font-normal text-slate-400">(optional)</span>
          </label>
          <input
            type="text"
            value={bookingNote}
            onChange={e => setBookingNote(e.target.value)}
            placeholder="e.g. Zoom link sent on confirmation"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
          />
        </div>
      )}

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{error}</p>
      )}

      <p className="text-[11px] text-slate-400">
        Create recurring sessions and edit advanced details on desktop.
      </p>

      <div className="flex gap-2.5 pt-1">
        <button
          onClick={handleCreate}
          disabled={saving}
          className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {saving ? 'Creating…' : 'Create gathering'}
        </button>
        <button
          onClick={onClose}
          className="rounded-xl border border-slate-200 px-4 py-2.5 text-[13px] text-slate-500 hover:bg-slate-100"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function GatheringsTabContent({
  gatherings: initGatherings,
  spaceSlug,
  members,
}: {
  gatherings: LiteGathering[]
  spaceSlug: string
  members: LiteMember[]
}) {
  const [gatherings, setGatherings] = useState(initGatherings)
  const [openId, setOpenId] = useState<string | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)

  function handleGatheringCreated(g: LiteGathering) {
    setGatherings(prev =>
      [...prev, g].sort(
        (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
      ),
    )
  }

  return (
    <div className="space-y-4">
      {showAddForm ? (
        <AddGatheringForm
          spaceSlug={spaceSlug}
          onCreated={g => { handleGatheringCreated(g); }}
          onClose={() => setShowAddForm(false)}
        />
      ) : (
        <button
          onClick={() => setShowAddForm(true)}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-teal-300 px-4 py-3 text-[13px] font-semibold transition-colors hover:bg-teal-50"
          style={{ color: '#38A09E' }}
        >
          + Add gathering
        </button>
      )}

      {gatherings.length === 0 && !showAddForm && (
        <Card>
          <CardBody>
            <p className="text-[14px] font-semibold" style={{ color: '#152236' }}>
              No upcoming gatherings
            </p>
            <p className="mt-1 text-[13px] text-slate-400">
              Use the button above to create one, or use desktop for advanced options.
            </p>
          </CardBody>
        </Card>
      )}

      {gatherings.length > 0 && (
        <Card>
          <div className="border-b px-5 pb-3 pt-4" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            <SectionLabel>Upcoming gatherings · {gatherings.length}</SectionLabel>
          </div>
          <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            {gatherings.map(g => (
              <div key={g.id}>
                <div className="px-5 py-3.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p
                        className="text-[13px] font-semibold leading-snug"
                        style={{ color: '#152236' }}
                      >
                        {g.title}
                      </p>
                      <p className="mt-0.5 text-[12px] text-slate-400">
                        {formatDate(g.starts_at)}
                      </p>
                      {g.requires_booking && (
                        <p className="mt-0.5 text-[11px]" style={{ color: '#38A09E' }}>
                          {g.booked_count} booked
                          {g.capacity != null ? ` / ${g.capacity}` : ''}
                        </p>
                      )}
                    </div>
                    {g.requires_booking && (
                      <button
                        onClick={() => setOpenId(openId === g.id ? null : g.id)}
                        className="shrink-0 rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:border-teal-200 hover:text-teal-700"
                      >
                        {openId === g.id ? 'Close ↑' : 'Bookings ↓'}
                      </button>
                    )}
                  </div>
                </div>
                {openId === g.id && (
                  <GatheringBookingsPanel
                    gathering={g}
                    spaceSlug={spaceSlug}
                    members={members}
                    onClose={() => setOpenId(null)}
                  />
                )}
              </div>
            ))}
          </div>
          <div className="border-t px-5 py-3" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            <p className="text-[11px] text-slate-400">
              Edit details and create recurring sessions on desktop.
            </p>
          </div>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: People
// ---------------------------------------------------------------------------

function PeopleTabContent({
  memberCount,
  leaderCount,
  invitations: initInvitations,
  accessRequests: initRequests,
  spaceSlug,
}: {
  memberCount: number
  leaderCount: number
  invitations: LiteInvitation[]
  accessRequests: LiteAccessRequest[]
  spaceSlug: string
}) {
  const [showAddForm, setShowAddForm] = useState(false)
  const [invitations, setInvitations] = useState(initInvitations)
  const [requests, setRequests] = useState(initRequests)
  const totalPending = invitations.length + requests.length

  return (
    <div className="space-y-4">
      <Card accent={totalPending > 0 ? 'gold' : undefined}>
        <CardBody>
          <SectionLabel>People</SectionLabel>
          <div className="mb-4 flex gap-6">
            {memberCount > 0 && (
              <div>
                <p
                  className="text-[22px] font-semibold leading-none"
                  style={{ color: '#152236' }}
                >
                  {memberCount}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">
                  {memberCount === 1 ? 'member' : 'members'}
                </p>
              </div>
            )}
            {leaderCount > 0 && (
              <div>
                <p
                  className="text-[22px] font-semibold leading-none"
                  style={{ color: '#152236' }}
                >
                  {leaderCount}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">
                  {leaderCount === 1 ? 'leader' : 'leaders'}
                </p>
              </div>
            )}
            {totalPending > 0 && (
              <div>
                <p
                  className="text-[22px] font-semibold leading-none"
                  style={{ color: '#b08d2a' }}
                >
                  {totalPending}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">pending</p>
              </div>
            )}
          </div>
          {!showAddForm && (
            <button
              onClick={() => setShowAddForm(true)}
              className="flex items-center gap-1.5 rounded-xl border border-slate-200 px-4 py-2.5 text-[13px] font-semibold text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
            >
              + Add person
            </button>
          )}
          {showAddForm && (
            <AddPersonForm spaceSlug={spaceSlug} onDone={() => setShowAddForm(false)} />
          )}
        </CardBody>

        {requests.length > 0 && (
          <div>
            <div
              className="border-t px-5 pb-1 pt-3"
              style={{ borderColor: 'rgba(0,0,0,0.07)' }}
            >
              <p
                className="text-[11px] font-bold uppercase tracking-[0.12em]"
                style={{ color: '#b08d2a' }}
              >
                Access requests · {requests.length}
              </p>
            </div>
            <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
              {requests.map(r => (
                <AccessRequestRow
                  key={r.id}
                  request={r}
                  spaceSlug={spaceSlug}
                  onResolved={id => setRequests(prev => prev.filter(x => x.id !== id))}
                />
              ))}
            </div>
          </div>
        )}

        {invitations.length > 0 && (
          <div>
            <div
              className="border-t px-5 pb-1 pt-3"
              style={{ borderColor: 'rgba(0,0,0,0.07)' }}
            >
              <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">
                Pending invites · {invitations.length}
              </p>
            </div>
            <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
              {invitations.map(inv => (
                <InviteRow
                  key={inv.id}
                  invite={inv}
                  spaceSlug={spaceSlug}
                  onCancelled={id => setInvitations(prev => prev.filter(x => x.id !== id))}
                />
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Pathways — creation form + grouped list
// ---------------------------------------------------------------------------

const ACCESS_TYPE_OPTIONS = [
  { value: 'free', label: 'Free' },
  { value: 'included', label: 'Included' },
  { value: 'one_time', label: 'One-time payment' },
  { value: 'subscription', label: 'Subscription' },
] as const

function AddPathwayForm({
  spaceSlug,
  onCreated,
  onClose,
}: {
  spaceSlug: string
  onCreated: (p: LitePathway) => void
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<'draft' | 'active' | 'coming_soon'>('draft')
  const [accessType, setAccessType] = useState<'free' | 'included' | 'one_time' | 'subscription'>('free')
  const [priceDollars, setPriceDollars] = useState('')
  const [currency] = useState('AUD')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const isPaid = accessType === 'one_time' || accessType === 'subscription'

  const STATUS_OPTIONS = [
    { value: 'draft' as const, label: 'Draft' },
    { value: 'active' as const, label: 'Published' },
    { value: 'coming_soon' as const, label: 'Coming soon' },
  ]

  function validate(): string | null {
    if (!title.trim()) return 'Title is required.'
    if (isPaid) {
      const d = parseFloat(priceDollars)
      if (!priceDollars.trim() || isNaN(d) || d <= 0) return 'Enter a valid price greater than 0.'
    }
    return null
  }

  async function handleCreate() {
    const validationError = validate()
    if (validationError) { setError(validationError); return }
    setSaving(true)
    setError(null)
    try {
      const priceCents = isPaid ? Math.round(parseFloat(priceDollars) * 100) : null
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          practice_body: null,
          status,
          access_type: accessType,
          price_cents: priceCents,
          currency: isPaid ? currency : null,
          billing_interval: accessType === 'subscription' ? 'month' : null,
        }),
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `HTTP ${res.status}`)
      }
      const data = await res.json()
      setDone(true)
      onCreated({
        id: data.id,
        slug: data.slug,
        title: data.title,
        status: data.status,
        access_type: data.access_type,
        price_cents: data.price_cents ?? null,
        currency: data.currency ?? null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create pathway.')
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <div
        className="rounded-xl border bg-slate-50 px-4 py-5 text-center"
        style={{ borderColor: 'rgba(56,160,158,0.20)' }}
      >
        <p className="mb-1 text-[14px] font-semibold" style={{ color: '#0f766e' }}>
          Pathway created!
        </p>
        <p className="mb-3 text-[12px] text-slate-400">Add steps and full content on desktop.</p>
        <button
          onClick={onClose}
          className="rounded-xl px-5 py-2 text-[13px] font-semibold text-white"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Done
        </button>
      </div>
    )
  }

  return (
    <div
      className="space-y-3.5 rounded-xl border bg-slate-50 px-4 py-4"
      style={{ borderColor: 'rgba(56,160,158,0.18)' }}
    >
      <p className="text-[13px] font-semibold text-slate-700">New pathway</p>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Title <span className="font-normal text-slate-400">(required)</span>
        </label>
        <input
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="e.g. 30-Day Reset"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
        />
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Short description <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          placeholder="What is this pathway about?"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold text-slate-500">Status</label>
        <div className="flex flex-wrap gap-1.5">
          {STATUS_OPTIONS.map(s => (
            <button
              key={s.value}
              type="button"
              onClick={() => setStatus(s.value)}
              className="rounded-xl border px-3 py-1.5 text-[12px] font-semibold transition-colors"
              style={
                status === s.value
                  ? {
                      background: 'rgba(56,160,158,0.10)',
                      border: '1px solid rgba(56,160,158,0.35)',
                      color: '#0f766e',
                    }
                  : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
              }
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold text-slate-500">Access</label>
        <div className="flex flex-wrap gap-1.5">
          {ACCESS_TYPE_OPTIONS.map(opt => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setAccessType(opt.value)}
              className="rounded-xl border px-3 py-1.5 text-[12px] font-semibold transition-colors"
              style={
                accessType === opt.value
                  ? {
                      background: 'rgba(56,160,158,0.10)',
                      border: '1px solid rgba(56,160,158,0.35)',
                      color: '#0f766e',
                    }
                  : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
              }
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {isPaid && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold text-slate-500">
            Price ({currency}) <span className="font-normal text-slate-400">(required)</span>
          </label>
          <div className="flex items-center gap-2">
            <span className="text-[14px] text-slate-400">$</span>
            <input
              type="number"
              value={priceDollars}
              onChange={e => setPriceDollars(e.target.value)}
              min="0"
              step="0.01"
              placeholder="0.00"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
            />
            <span className="text-[13px] font-medium text-slate-500">
              {accessType === 'subscription' ? '/mo' : ''}
            </span>
          </div>
        </div>
      )}

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{error}</p>
      )}

      <div className="flex gap-2.5 pt-1">
        <button
          onClick={handleCreate}
          disabled={saving}
          className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {saving ? 'Creating…' : 'Create pathway'}
        </button>
        <button
          onClick={onClose}
          className="rounded-xl border border-slate-200 px-4 py-2.5 text-[13px] text-slate-500 hover:bg-slate-100"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function PathwaysTabContent({
  allPathways,
  spaceSlug,
}: {
  allPathways: LitePathway[]
  spaceSlug: string
}) {
  const [pathways, setPathways] = useState(allPathways)
  const [togglingSlug, setTogglingSlug] = useState<string | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)

  const STATUS_GROUPS: { label: string; status: string }[] = [
    { label: 'Published', status: 'active' },
    { label: 'Coming soon', status: 'coming_soon' },
    { label: 'Drafts', status: 'draft' },
    { label: 'Archived', status: 'archived' },
  ]

  async function toggleStatus(pathway: LitePathway) {
    const newStatus = pathway.status === 'active' ? 'draft' : 'active'
    setTogglingSlug(pathway.slug)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus }),
        },
      )
      if (res.ok) {
        setPathways(prev =>
          prev.map(p => (p.slug === pathway.slug ? { ...p, status: newStatus } : p)),
        )
      }
    } finally {
      setTogglingSlug(null)
    }
  }

  return (
    <div className="space-y-4">
      {showAddForm ? (
        <AddPathwayForm
          spaceSlug={spaceSlug}
          onCreated={p => setPathways(prev => [...prev, p])}
          onClose={() => setShowAddForm(false)}
        />
      ) : (
        <button
          onClick={() => setShowAddForm(true)}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-teal-300 px-4 py-3 text-[13px] font-semibold transition-colors hover:bg-teal-50"
          style={{ color: '#38A09E' }}
        >
          + Add pathway
        </button>
      )}

      {pathways.length === 0 && !showAddForm && (
        <Card>
          <CardBody>
            <p className="text-[14px] font-semibold" style={{ color: '#152236' }}>
              No pathways yet
            </p>
            <p className="mt-1 text-[13px] text-slate-400">
              Use the button above to create a pathway shell, then add steps on desktop.
            </p>
          </CardBody>
        </Card>
      )}

      {STATUS_GROUPS.map(({ label, status }) => {
        const items = pathways.filter(p => p.status === status)
        if (items.length === 0) return null
        return (
          <Card key={status}>
            <div className="border-b px-5 pb-3 pt-4" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
              <SectionLabel>
                {label} · {items.length}
              </SectionLabel>
            </div>
            <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
              {items.map(p => (
                <div key={p.slug} className="flex items-center gap-3 px-5 py-3.5">
                  <div className="min-w-0 flex-1">
                    <p
                      className="truncate text-[13px] font-medium"
                      style={{ color: status === 'archived' ? '#94a3b8' : '#152236' }}
                    >
                      {p.title}
                    </p>
                    <p className="mt-0.5 text-[11px] text-slate-400">{accessLabel(p)}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {(status === 'active' || status === 'draft') && (
                      <button
                        onClick={() => toggleStatus(p)}
                        disabled={togglingSlug === p.slug}
                        className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:border-teal-200 hover:text-teal-700 disabled:opacity-40"
                      >
                        {togglingSlug === p.slug
                          ? '…'
                          : status === 'active'
                            ? 'Unpublish'
                            : 'Publish'}
                      </button>
                    )}
                    {(status === 'active' || status === 'coming_soon') && (
                      <Link
                        href={`/spaces/${spaceSlug}/pathways/${p.slug}`}
                        className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:border-teal-200 hover:text-teal-700"
                      >
                        Preview →
                      </Link>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )
      })}

      <p className="px-1 text-[12px] text-slate-400">
        Add steps and edit pathway content on desktop.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Resources — creation form + list
// ---------------------------------------------------------------------------

interface MobileResource {
  id: string
  title: string
  description: string | null
  resource_type: string
  status: string
  url: string | null
  file_name: string | null
}

const MOBILE_RESOURCE_TYPES = [
  { value: 'link' as const,     label: 'Link',     needsUrl: true },
  { value: 'video' as const,    label: 'Video',    needsUrl: true },
  { value: 'replay' as const,   label: 'Replay',   needsUrl: true },
  { value: 'guide' as const,    label: 'Guide',    needsUrl: false },
  { value: 'template' as const, label: 'Template', needsUrl: true },
  { value: 'audio' as const,    label: 'Audio',    needsUrl: true },
  { value: 'other' as const,    label: 'Other',    needsUrl: false },
]

function AddResourceForm({
  spaceSlug,
  pathways,
  onCreated,
  onClose,
}: {
  spaceSlug: string
  pathways: LitePathway[]
  onCreated: (r: MobileResource) => void
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [resourceType, setResourceType] = useState<'link' | 'video' | 'replay' | 'guide' | 'template' | 'audio' | 'other'>('link')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<'draft' | 'published'>('draft')
  const [scope, setScope] = useState<'general' | 'pathway'>('general')
  const [pathwayId, setPathwayId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const selectedType = MOBILE_RESOURCE_TYPES.find(t => t.value === resourceType)
  const needsUrl = selectedType?.needsUrl ?? false

  const activePaths = pathways.filter(p => p.status !== 'archived')

  function validate(): string | null {
    if (!title.trim()) return 'Title is required.'
    if (needsUrl) {
      if (!url.trim()) return 'URL is required for this resource type.'
      try { new URL(url.trim()) } catch { return 'Enter a valid URL (include https://).' }
    }
    if (scope === 'pathway' && !pathwayId) return 'Select a pathway for pathway-specific resources.'
    return null
  }

  async function handleCreate() {
    const validationError = validate()
    if (validationError) { setError(validationError); return }
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          resource_type: resourceType,
          url: url.trim() || null,
          status,
          scope,
          pathway_id: scope === 'pathway' ? pathwayId : null,
        }),
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `HTTP ${res.status}`)
      }
      const data = await res.json()
      setDone(true)
      onCreated({
        id: data.id,
        title: data.title,
        description: data.description ?? null,
        resource_type: data.resource_type,
        status: data.status,
        url: data.url ?? null,
        file_name: null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create resource.')
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <div
        className="rounded-xl border bg-slate-50 px-4 py-5 text-center"
        style={{ borderColor: 'rgba(56,160,158,0.20)' }}
      >
        <p className="mb-1 text-[14px] font-semibold" style={{ color: '#0f766e' }}>
          Resource created!
        </p>
        <p className="mb-3 text-[12px] text-slate-400">It has been added to the list.</p>
        <button
          onClick={onClose}
          className="rounded-xl px-5 py-2 text-[13px] font-semibold text-white"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Done
        </button>
      </div>
    )
  }

  return (
    <div
      className="space-y-3.5 rounded-xl border bg-slate-50 px-4 py-4"
      style={{ borderColor: 'rgba(56,160,158,0.18)' }}
    >
      <p className="text-[13px] font-semibold text-slate-700">New resource</p>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Title <span className="font-normal text-slate-400">(required)</span>
        </label>
        <input
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="e.g. Getting Started Guide"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold text-slate-500">Type</label>
        <div className="flex flex-wrap gap-1.5">
          {MOBILE_RESOURCE_TYPES.map(t => (
            <button
              key={t.value}
              type="button"
              onClick={() => setResourceType(t.value)}
              className="rounded-xl border px-3 py-1.5 text-[12px] font-semibold transition-colors"
              style={
                resourceType === t.value
                  ? {
                      background: 'rgba(56,160,158,0.10)',
                      border: '1px solid rgba(56,160,158,0.35)',
                      color: '#0f766e',
                    }
                  : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
              }
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-semibold text-slate-500">
          Description <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
        />
      </div>

      {needsUrl && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold text-slate-500">
            URL <span className="font-normal text-slate-400">(required)</span>
          </label>
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://…"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
          />
        </div>
      )}

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold text-slate-500">Scope</label>
        <div className="flex gap-1.5">
          {[
            { value: 'general' as const, label: 'General / shared' },
            { value: 'pathway' as const, label: 'Pathway-specific' },
          ].map(s => (
            <button
              key={s.value}
              type="button"
              onClick={() => setScope(s.value)}
              className="rounded-xl border px-3 py-1.5 text-[12px] font-semibold transition-colors"
              style={
                scope === s.value
                  ? {
                      background: 'rgba(56,160,158,0.10)',
                      border: '1px solid rgba(56,160,158,0.35)',
                      color: '#0f766e',
                    }
                  : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
              }
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {scope === 'pathway' && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold text-slate-500">
            Pathway <span className="font-normal text-slate-400">(required)</span>
          </label>
          {activePaths.length === 0 ? (
            <p className="text-[12px] text-slate-400">No active pathways found.</p>
          ) : (
            <select
              value={pathwayId}
              onChange={e => setPathwayId(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
            >
              <option value="">Select a pathway…</option>
              {activePaths.map(p => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold text-slate-500">Status</label>
        <div className="flex gap-1.5">
          {[
            { value: 'draft' as const, label: 'Draft' },
            { value: 'published' as const, label: 'Published' },
          ].map(s => (
            <button
              key={s.value}
              type="button"
              onClick={() => setStatus(s.value)}
              className="rounded-xl border px-3 py-1.5 text-[12px] font-semibold transition-colors"
              style={
                status === s.value
                  ? {
                      background: 'rgba(56,160,158,0.10)',
                      border: '1px solid rgba(56,160,158,0.35)',
                      color: '#0f766e',
                    }
                  : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
              }
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{error}</p>
      )}

      <p className="text-[11px] text-slate-400">
        Upload files and organise larger resources on desktop.
      </p>

      <div className="flex gap-2.5 pt-1">
        <button
          onClick={handleCreate}
          disabled={saving}
          className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {saving ? 'Creating…' : 'Create resource'}
        </button>
        <button
          onClick={onClose}
          className="rounded-xl border border-slate-200 px-4 py-2.5 text-[13px] text-slate-500 hover:bg-slate-100"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function ResourceRow({
  resource,
  spaceSlug,
  isEditing,
  onEditToggle,
  onUpdate,
  onTogglePublish,
  toggling,
}: {
  resource: MobileResource
  spaceSlug: string
  isEditing: boolean
  onEditToggle: (id: string) => void
  onUpdate: (r: MobileResource) => void
  onTogglePublish: (r: MobileResource) => void
  toggling: boolean
}) {
  const [title, setTitle] = useState(resource.title)
  const [description, setDescription] = useState(resource.description ?? '')
  const [url, setUrl] = useState(resource.url ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const ICONS: Record<string, string> = {
    link: '🔗', file: '📄', replay: '▶', guide: '📖',
    template: '📋', audio: '🎧', video: '🎬', pdf: '📄', other: '◫',
  }
  const icon = ICONS[resource.resource_type] ?? '◫'

  async function handleSave() {
    if (!title.trim()) return
    setSaving(true)
    setError(null)
    try {
      const body: Record<string, string | null> = {
        title: title.trim(),
        description: description.trim() || null,
      }
      if (!resource.file_name) body.url = url.trim() || null

      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${resource.id}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
      if (res.ok) {
        onUpdate({
          ...resource,
          title: title.trim(),
          description: description.trim() || null,
          url: resource.file_name ? resource.url : url.trim() || null,
        })
        onEditToggle(resource.id)
      } else {
        const b = await res.json().catch(() => ({}))
        setError(typeof b.detail === 'string' ? b.detail : 'Could not save.')
      }
    } finally {
      setSaving(false)
    }
  }

  function handleCancel() {
    setTitle(resource.title)
    setDescription(resource.description ?? '')
    setUrl(resource.url ?? '')
    setError(null)
    onEditToggle(resource.id)
  }

  return (
    <div className="px-5 py-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[12px]">{icon}</span>
            <p className="truncate text-[13px] font-medium" style={{ color: '#152236' }}>
              {resource.title}
            </p>
          </div>
          {resource.description && !isEditing && (
            <p className="mt-0.5 line-clamp-1 text-[11px] text-slate-400">
              {resource.description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            onClick={() => onTogglePublish(resource)}
            disabled={toggling}
            className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:border-teal-200 hover:text-teal-700 disabled:opacity-40"
          >
            {toggling ? '…' : resource.status === 'published' ? 'Unpublish' : 'Publish'}
          </button>
          <button
            onClick={() => onEditToggle(resource.id)}
            className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:border-teal-200 hover:text-teal-700"
          >
            {isEditing ? 'Cancel' : 'Edit'}
          </button>
        </div>
      </div>

      {isEditing && (
        <div
          className="mt-3 space-y-2.5 rounded-xl border bg-slate-50 p-3.5"
          style={{ borderColor: 'rgba(56,160,158,0.18)' }}
        >
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-slate-500">Title</label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-slate-500">
              Description
            </label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
            />
          </div>
          {!resource.file_name && (
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-slate-500">URL</label>
              <input
                type="url"
                value={url}
                onChange={e => setUrl(e.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
              />
            </div>
          )}
          {error && <p className="text-[11px] text-red-500">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={!title.trim() || saving}
              className="rounded-xl px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-40"
              style={{ background: '#38A09E' }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              onClick={handleCancel}
              className="rounded-xl border border-slate-200 px-4 py-2 text-[13px] text-slate-500"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function ResourcesTabContent({
  spaceSlug,
  pathways,
}: {
  spaceSlug: string
  pathways: LitePathway[]
}) {
  const [resources, setResources] = useState<MobileResource[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)

  useEffect(() => {
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources`), { credentials: 'include' })
      .then(r => (r.ok ? r.json() : []))
      .then(setResources)
      .catch(() => setResources([]))
      .finally(() => setLoading(false))
  }, [spaceSlug])

  async function togglePublish(resource: MobileResource) {
    const newStatus = resource.status === 'published' ? 'draft' : 'published'
    setTogglingId(resource.id)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${resource.id}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus }),
        },
      )
      if (res.ok) {
        setResources(
          prev => prev?.map(r => (r.id === resource.id ? { ...r, status: newStatus } : r)) ?? null,
        )
      }
    } finally {
      setTogglingId(null)
    }
  }

  if (loading) {
    return (
      <Card>
        <CardBody>
          <p className="text-[13px] text-slate-400">Loading resources…</p>
        </CardBody>
      </Card>
    )
  }

  const published = (resources ?? []).filter(r => r.status === 'published')
  const drafts = (resources ?? []).filter(r => r.status !== 'published')

  return (
    <div className="space-y-4">
      {showAddForm ? (
        <AddResourceForm
          spaceSlug={spaceSlug}
          pathways={pathways}
          onCreated={r => {
            setResources(prev => (prev ? [r, ...prev] : [r]))
          }}
          onClose={() => setShowAddForm(false)}
        />
      ) : (
        <button
          onClick={() => setShowAddForm(true)}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-teal-300 px-4 py-3 text-[13px] font-semibold transition-colors hover:bg-teal-50"
          style={{ color: '#38A09E' }}
        >
          + Add resource
        </button>
      )}

      {!loading && resources !== null && resources.length === 0 && !showAddForm && (
        <Card>
          <CardBody>
            <p className="text-[14px] font-semibold" style={{ color: '#152236' }}>
              No resources yet
            </p>
            <p className="mt-1 text-[13px] text-slate-400">
              Use the button above to add a link or guide, or upload files on desktop.
            </p>
          </CardBody>
        </Card>
      )}

      {published.length > 0 && (
        <Card>
          <div className="border-b px-5 pb-3 pt-4" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            <SectionLabel>Published · {published.length}</SectionLabel>
          </div>
          <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            {published.map(r => (
              <ResourceRow
                key={r.id}
                resource={r}
                spaceSlug={spaceSlug}
                isEditing={editingId === r.id}
                onEditToggle={id => setEditingId(editingId === id ? null : id)}
                onUpdate={updated =>
                  setResources(prev => prev?.map(x => (x.id === updated.id ? updated : x)) ?? null)
                }
                onTogglePublish={togglePublish}
                toggling={togglingId === r.id}
              />
            ))}
          </div>
        </Card>
      )}

      {drafts.length > 0 && (
        <Card>
          <div className="border-b px-5 pb-3 pt-4" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            <SectionLabel>Drafts · {drafts.length}</SectionLabel>
          </div>
          <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            {drafts.map(r => (
              <ResourceRow
                key={r.id}
                resource={r}
                spaceSlug={spaceSlug}
                isEditing={editingId === r.id}
                onEditToggle={id => setEditingId(editingId === id ? null : id)}
                onUpdate={updated =>
                  setResources(prev => prev?.map(x => (x.id === updated.id ? updated : x)) ?? null)
                }
                onTogglePublish={togglePublish}
                toggling={togglingId === r.id}
              />
            ))}
          </div>
        </Card>
      )}

      <p className="px-1 text-[12px] text-slate-400">
        Upload and organise resources on desktop.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Payments
// ---------------------------------------------------------------------------

interface LitePaymentSummary {
  total_creator_net_amount_cents: number
  pending_payout_cents: number
  succeeded_count: number
}

function PaymentsTabContent({ billing }: { billing: LiteBillingData }) {
  const [summary, setSummary] = useState<LitePaymentSummary | null>(null)
  const [loadingPayments, setLoadingPayments] = useState(true)

  const currency = billing.currency.toUpperCase()
  const fmtFee = (bp: number) => `${(bp / 100).toFixed(0)}%`

  function fmtAmount(cents: number) {
    return new Intl.NumberFormat('en-AU', {
      style: 'currency',
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(cents / 100)
  }

  useEffect(() => {
    fetch(apiUrl('/api/creator/payments/summary'), { credentials: 'include' })
      .then(r => (r.ok ? (r.json() as Promise<LitePaymentSummary>) : null))
      .then(data => setSummary(data))
      .catch(() => setSummary(null))
      .finally(() => setLoadingPayments(false))
  }, [])

  const isStripeConnected = billing.stripeConnectConnected
  const hasTransactions = summary !== null && summary.succeeded_count > 0

  return (
    <div className="space-y-4">
      <Card>
        <CardBody>
          <SectionLabel>Payments</SectionLabel>
          <div className="mb-4">
            <span
              className="mb-2 inline-block rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              style={
                isStripeConnected
                  ? { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
                  : { background: 'rgba(245,158,11,0.12)', color: '#92400e' }
              }
            >
              {isStripeConnected ? 'Stripe connected' : 'Stripe not connected'}
            </span>
            {!isStripeConnected && (
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
                Connect payment processing on desktop to start accepting paid pathways or bookings.
              </p>
            )}
          </div>

          {loadingPayments && (
            <p className="mb-4 text-[12px] text-slate-400">Loading payment data…</p>
          )}

          {!loadingPayments && (
            <div className="mb-4 grid grid-cols-2 gap-3">
              <div
                className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(0,0,0,0.03)', border: '1px solid rgba(0,0,0,0.06)' }}
              >
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Total earned
                </p>
                <p
                  className="mt-0.5 text-[18px] font-semibold leading-none"
                  style={{ color: '#152236' }}
                >
                  {hasTransactions
                    ? fmtAmount(summary!.total_creator_net_amount_cents)
                    : '—'}
                </p>
                {hasTransactions && (
                  <p className="mt-0.5 text-[10px] text-slate-400">
                    after {fmtFee(billing.transactionFeeBasisPoints)} fee
                  </p>
                )}
              </div>
              <div
                className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(0,0,0,0.03)', border: '1px solid rgba(0,0,0,0.06)' }}
              >
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Pending payout
                </p>
                <p
                  className="mt-0.5 text-[18px] font-semibold leading-none"
                  style={{ color: '#152236' }}
                >
                  {hasTransactions ? fmtAmount(summary!.pending_payout_cents) : '—'}
                </p>
              </div>
            </div>
          )}

          {!loadingPayments && !hasTransactions && (
            <p className="mb-3 text-[12px] text-slate-400">No member payments recorded yet.</p>
          )}

          <p className="text-[12px] text-slate-400">
            View transactions and manage payments on desktop.
          </p>
        </CardBody>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Settings
// ---------------------------------------------------------------------------

function SettingsTabContent({
  activeSpace,
  spaceSlug,
}: {
  activeSpace: SpaceSummary
  spaceSlug: string
}) {
  const [name, setName] = useState(activeSpace.name)
  const [tagline, setTagline] = useState(activeSpace.tagline ?? '')
  const [status, setStatus] = useState(activeSpace.status)
  const [isPublic, setIsPublic] = useState(activeSpace.is_public)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  async function handleSave() {
    if (!name.trim()) return
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          tagline: tagline.trim() || null,
          status,
          is_public: isPublic,
        }),
      })
      if (res.ok) {
        setSaved(true)
        setTimeout(() => setSaved(false), 3000)
      } else {
        const b = await res.json().catch(() => ({}))
        setError(typeof b.detail === 'string' ? b.detail : 'Could not save settings.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardBody>
          <SectionLabel>Collective settings</SectionLabel>
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-slate-500">Name</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 outline-none focus:border-teal-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-slate-500">Tagline</label>
              <input
                type="text"
                value={tagline}
                onChange={e => setTagline(e.target.value)}
                placeholder="A short description of your collective"
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none focus:border-teal-400"
              />
            </div>

            <div>
              <label className="mb-2 block text-[11px] font-semibold text-slate-500">Status</label>
              <div className="flex gap-2">
                {(['active', 'draft'] as const).map(s => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStatus(s)}
                    className="rounded-xl border px-4 py-2 text-[13px] font-semibold transition-colors"
                    style={
                      status === s
                        ? {
                            background: 'rgba(56,160,158,0.10)',
                            border: '1px solid rgba(56,160,158,0.35)',
                            color: '#0f766e',
                          }
                        : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
                    }
                  >
                    {s === 'active' ? 'Active' : 'Draft'}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-2 block text-[11px] font-semibold text-slate-500">
                Visibility
              </label>
              <div className="flex gap-2">
                {[
                  { value: true, label: 'Public' },
                  { value: false, label: 'Private' },
                ].map(({ value, label }) => (
                  <button
                    key={String(value)}
                    type="button"
                    onClick={() => setIsPublic(value)}
                    className="rounded-xl border px-4 py-2 text-[13px] font-semibold transition-colors"
                    style={
                      isPublic === value
                        ? {
                            background: 'rgba(56,160,158,0.10)',
                            border: '1px solid rgba(56,160,158,0.35)',
                            color: '#0f766e',
                          }
                        : { border: '1px solid rgba(0,0,0,0.10)', color: '#64748b' }
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {error && (
            <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-[13px] text-red-600">
              {error}
            </div>
          )}

          <button
            onClick={handleSave}
            disabled={!name.trim() || saving}
            className="mt-5 w-full rounded-xl py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {saving ? 'Saving…' : saved ? '✓ Saved!' : 'Save changes'}
          </button>
        </CardBody>
      </Card>

      <p className="px-1 text-[12px] text-slate-400">
        About page, banner image, pricing, and URL slug are managed on desktop.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  user: { name: string | null; email: string }
  activeSpace: SpaceSummary | null
  spaces: SpaceSummary[]
  liteData: LiteData
}

export default function CreatorStudioLiteMobile({ user, activeSpace, spaces, liteData }: Props) {
  const router = useRouter()
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [switchingTo, setSwitchingTo] = useState<string | null>(null)

  const { upcomingGatherings, members, invitations, accessRequests, allPathways, billing } =
    liteData

  const slug = activeSpace?.slug ?? ''
  const totalPending =
    invitations.length + accessRequests.filter(r => r.status === 'pending').length

  function switchCollective(newSlug: string) {
    if (newSlug === slug) return
    setSwitchingTo(newSlug)
    document.cookie = `fc_creator_space=${newSlug}; path=/; max-age=86400`
    router.push('/creator-studio')
    router.refresh()
  }

  return (
    <div className="flex min-h-screen flex-col" style={{ background: '#F7F8FA' }}>
      {/* ── Header ── */}
      <div
        style={{
          background: 'linear-gradient(180deg, #073B3A 0%, #062F35 100%)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        <div className="px-4 pb-4 pt-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="font-serif text-[17px] leading-tight text-white">Creator Studio</p>
              <p
                className="text-[11px] font-bold uppercase tracking-[0.18em]"
                style={{ color: 'rgba(255,255,255,0.40)' }}
              >
                Fresh Collective
              </p>
            </div>
            <Link
              href="/dashboard"
              className="text-[12px] font-medium transition-opacity hover:opacity-80"
              style={{ color: 'rgba(255,255,255,0.55)' }}
            >
              ← Platform
            </Link>
          </div>

          {activeSpace && (
            <div
              className="rounded-xl px-3 py-2.5"
              style={{
                background: 'rgba(255,255,255,0.07)',
                border: '1px solid rgba(255,255,255,0.10)',
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p
                    className="text-[11px] font-semibold uppercase tracking-wide"
                    style={{ color: '#42C7C6' }}
                  >
                    Current collective
                  </p>
                  <p className="mt-0.5 truncate text-[14px] font-semibold text-white">
                    {activeSpace.name}
                  </p>
                </div>
                <Link
                  href={`/spaces/${slug}`}
                  className="shrink-0 text-[12px] font-semibold transition-opacity hover:opacity-80"
                  style={{ color: '#8DE8E6' }}
                >
                  View →
                </Link>
              </div>
              {spaces.length > 1 && (
                <div className="mt-2">
                  <select
                    value={activeSpace.slug}
                    onChange={e => switchCollective(e.target.value)}
                    disabled={switchingTo !== null}
                    className="w-full rounded-lg border bg-transparent px-2.5 py-1.5 text-[12px] font-medium text-white outline-none"
                    style={{
                      borderColor: 'rgba(255,255,255,0.22)',
                      background: 'rgba(0,0,0,0.20)',
                    }}
                  >
                    {spaces.map(s => (
                      <option key={s.slug} value={s.slug} style={{ background: '#073B3A' }}>
                        {s.name}
                        {s.status !== 'active' ? ' (Draft)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Tab navigation ── */}
      {activeSpace && (
        <TabNav
          activeTab={activeTab}
          onTabChange={tab => {
            setActiveTab(tab)
            window.scrollTo({ top: 0 })
          }}
          pendingPeople={totalPending}
        />
      )}

      {/* ── Tab content ── */}
      <div className="flex-1 px-4 py-5 pb-10">
        {!activeSpace ? (
          <Card>
            <CardBody>
              <p className="mb-2 text-[15px] font-semibold" style={{ color: '#152236' }}>
                No collective selected
              </p>
              <p className="mb-4 text-[13px] text-slate-500">
                Open Creator Studio on a larger screen to set up your collective.
              </p>
              <Link href="/dashboard" className="text-[13px] font-medium" style={{ color: '#38A09E' }}>
                ← Back to platform
              </Link>
            </CardBody>
          </Card>
        ) : (
          <>
            {activeTab === 'overview' && (
              <OverviewTab activeSpace={activeSpace} slug={slug} liteData={liteData} />
            )}
            {activeTab === 'gatherings' && (
              <GatheringsTabContent
                gatherings={upcomingGatherings}
                spaceSlug={slug}
                members={members}
              />
            )}
            {activeTab === 'people' && (
              <PeopleTabContent
                memberCount={liteData.memberCount}
                leaderCount={liteData.leaderCount}
                invitations={invitations}
                accessRequests={accessRequests.filter(r => r.status === 'pending')}
                spaceSlug={slug}
              />
            )}
            {activeTab === 'pathways' && (
              <PathwaysTabContent allPathways={allPathways} spaceSlug={slug} />
            )}
            {activeTab === 'resources' && (
              <ResourcesTabContent spaceSlug={slug} pathways={allPathways} />
            )}
            {activeTab === 'payments' && billing ? (
              <PaymentsTabContent billing={billing} />
            ) : activeTab === 'payments' ? (
              <Card>
                <CardBody>
                  <p className="text-[13px] text-slate-400">Payment data is not available.</p>
                </CardBody>
              </Card>
            ) : null}
            {activeTab === 'settings' && (
              <SettingsTabContent activeSpace={activeSpace} spaceSlug={slug} />
            )}
          </>
        )}

        <p className="mt-6 text-center text-[11px] text-slate-400">
          Signed in as {user.name ?? user.email}
        </p>
      </div>
    </div>
  )
}
