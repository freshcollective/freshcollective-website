'use client'

import Link from 'next/link'
import { useState, useEffect, useRef } from 'react'
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

export interface LiteData {
  pathwayCounts: { published: number; comingSoon: number; drafts: number; archived: number }
  publishedPathways: LitePathway[]
  upcomingGatherings: LiteGathering[]
  memberCount: number
  leaderCount: number
  members: LiteMember[]
  invitations: LiteInvitation[]
  accessRequests: LiteAccessRequest[]
  pendingInvites: number
  pendingRequests: number
  resourceCount: number
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }) +
    ' · ' +
    new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
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
// Small shared UI
// ---------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">
      {children}
    </p>
  )
}

function Card({ children, accent }: { children: React.ReactNode; accent?: 'teal' | 'gold' }) {
  const accentStyle = accent === 'teal'
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

function TealBtn({ onClick, disabled, children }: {
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

function GhostBtn({ onClick, disabled, children, danger }: {
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

function CopyButton({ text, label = 'Copy', copiedLabel = '✓ Copied!' }: {
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
  return (
    <GhostBtn onClick={handleCopy}>{copied ? copiedLabel : label}</GhostBtn>
  )
}

function AttendancePill({ status }: { status: string | null }) {
  const styles: Record<string, { label: string; bg: string; color: string }> = {
    attended: { label: 'Attended', bg: 'rgba(56,160,158,0.12)', color: '#0f766e' },
    no_show:  { label: 'No show',  bg: 'rgba(239,68,68,0.08)',  color: '#b91c1c' },
    pending:  { label: 'Pending',  bg: 'rgba(148,163,184,0.12)', color: '#64748b' },
  }
  const s = (status && styles[status]) ? styles[status] : styles.pending
  return (
    <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold" style={{ background: s.bg, color: s.color }}>
      {s.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Gathering bookings panel (lazy-loaded)
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
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${gathering.id}/bookings`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
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
        setBookings(prev => prev?.map(b => b.booking_id === bookingId ? { ...b, status: 'cancelled' as const } : b) ?? null)
      }
    } finally {
      setCancellingId(null)
    }
  }

  async function handleAttendance(bookingId: string, status: string) {
    setAttendanceBusy(bookingId)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/events/${gathering.id}/bookings/${bookingId}/attendance`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status }),
        },
      )
      if (res.ok) {
        const data = await res.json()
        setBookings(prev => prev?.map(b =>
          b.booking_id === bookingId ? { ...b, attendance_status: data.attendance_status } : b
        ) ?? null)
      }
    } finally {
      setAttendanceBusy(null)
    }
  }

  const confirmed = bookings?.filter(b => b.status === 'confirmed') ?? []
  const cancelled = bookings?.filter(b => b.status === 'cancelled') ?? []
  const attendedCount = confirmed.filter(b => b.attendance_status === 'attended').length
  const noShowCount   = confirmed.filter(b => b.attendance_status === 'no_show').length

  const availableMembers = members.filter(
    m => !confirmed.some(b => b.user_id === m.id)
  )

  const capacityFull = gathering.capacity != null && confirmed.length >= gathering.capacity

  return (
    <div
      className="border-t bg-slate-50 px-4 pb-4 pt-4"
      style={{ borderColor: 'rgba(0,0,0,0.07)' }}
    >
      {/* Header row */}
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[12px] font-semibold text-navy-900">
          Bookings
          {bookings !== null && (
            <span className="ml-1.5 text-slate-400 font-normal">
              {confirmed.length}{gathering.capacity != null ? ` / ${gathering.capacity}` : ''}
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

      {/* Past attendance summary */}
      {isPast && confirmed.length > 0 && (
        <div className="mb-3 flex gap-4 text-[11px]">
          {attendedCount > 0 && <span style={{ color: '#0f766e' }}>{attendedCount} attended</span>}
          {noShowCount > 0 && <span style={{ color: '#b91c1c' }}>{noShowCount} no show</span>}
          {confirmed.length - attendedCount - noShowCount > 0 && (
            <span className="text-slate-400">{confirmed.length - attendedCount - noShowCount} not marked</span>
          )}
        </div>
      )}

      {loading && (
        <p className="py-4 text-center text-[13px] text-slate-400">Loading bookings…</p>
      )}

      {!loading && confirmed.length === 0 && !showAddForm && (
        <p className="mb-3 text-[13px] text-slate-400">No confirmed bookings yet.</p>
      )}

      {/* Confirmed bookings */}
      {!loading && confirmed.length > 0 && (
        <div className="mb-3 divide-y overflow-hidden rounded-xl border border-border bg-white" style={{ borderColor: 'rgba(0,0,0,0.08)' }}>
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
                      <span className="rounded-full px-2 py-0.5 text-[10px] font-medium text-slate-400" style={{ background: 'rgba(0,0,0,0.05)' }}>
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
              {/* Attendance buttons — past sessions only */}
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
                      className="rounded-md px-2.5 py-1 text-[11px] text-slate-400 disabled:opacity-40 hover:text-slate-600"
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

      {/* Cancelled bookings (collapsed) */}
      {!loading && cancelled.length > 0 && (
        <details className="mb-3">
          <summary className="cursor-pointer text-[11px] text-slate-400 hover:text-slate-600">
            {cancelled.length} cancelled booking{cancelled.length !== 1 ? 's' : ''}
          </summary>
          <div className="mt-2 divide-y overflow-hidden rounded-xl border border-border bg-white opacity-60">
            {cancelled.map(b => (
              <div key={b.booking_id} className="px-4 py-2.5">
                <p className="text-[12px] text-slate-400 line-through">{b.name ?? b.email}</p>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Add booking (future sessions only) */}
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
            <div className="mt-2 rounded-xl border border-border bg-white p-3.5" style={{ borderColor: 'rgba(56,160,158,0.20)' }}>
              <p className="mb-2.5 text-[12px] font-semibold text-navy-900">Add a booking</p>
              <select
                value={selectedUserId}
                onChange={e => { setSelectedUserId(e.target.value); setAddError(null) }}
                className="mb-2.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 outline-none focus:border-teal-400"
              >
                <option value="">Select a member…</option>
                {availableMembers.map(m => (
                  <option key={m.id} value={m.id}>{m.display_name}</option>
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
                  onClick={() => { setShowAddForm(false); setSelectedUserId(''); setAddError(null) }}
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

      <p className="mt-4 text-[11px] text-slate-400">
        To edit session details, open Creator Studio on desktop.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Gatherings card
// ---------------------------------------------------------------------------

function GatheringsCard({
  gatherings,
  spaceSlug,
  members,
}: {
  gatherings: LiteGathering[]
  spaceSlug: string
  members: LiteMember[]
}) {
  const [openId, setOpenId] = useState<string | null>(null)

  if (gatherings.length === 0) return null

  return (
    <Card>
      <div className="border-b px-5 pt-4 pb-3" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
        <SectionLabel>Upcoming gatherings</SectionLabel>
      </div>
      <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
        {gatherings.map(g => (
          <div key={g.id}>
            <div className="px-5 py-3.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold leading-snug" style={{ color: '#152236' }}>
                    {g.title}
                  </p>
                  <p className="mt-0.5 text-[12px] text-slate-400">{formatDate(g.starts_at)}</p>
                  {g.requires_booking && (
                    <p className="mt-0.5 text-[11px]" style={{ color: '#38A09E' }}>
                      {g.booked_count} booked{g.capacity != null ? ` / ${g.capacity}` : ''}
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
          You can check bookings and invite people from mobile. Use desktop for detailed editing.
        </p>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Add person inline form
// ---------------------------------------------------------------------------

function AddPersonForm({
  spaceSlug,
  onDone,
}: {
  spaceSlug: string
  onDone: () => void
}) {
  const [email, setEmail] = useState('')
  const [name, setName]   = useState('')
  const [role, setRole]   = useState('learner')
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
        body: JSON.stringify({ email: trimmedEmail, name: name.trim() || null, role, note: null }),
      })
      const data: AddMemberResponse = await res.json()
      if (!res.ok) {
        setError(typeof (data as { detail?: string }).detail === 'string' ? (data as { detail?: string }).detail! : 'Something went wrong.')
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
      <div className="rounded-xl border bg-slate-50 px-4 py-4 text-center" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
        <p className="text-[14px] font-semibold" style={{ color: RESULT_COLOR[result.result] ?? '#152236' }}>
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
    <div className="space-y-3 rounded-xl border bg-slate-50 px-4 py-4" style={{ borderColor: 'rgba(56,160,158,0.18)' }}>
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
          onChange={e => { setEmail(e.target.value); setError(null) }}
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
// Pending invitation row
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
  useEffect(() => { setOrigin(window.location.origin) }, [])
  const inviteLink = origin ? `${origin}/invites/${invite.token}` : `/invites/${invite.token}`
  const ROLE_LABEL: Record<string, string> = { creator: 'Leader', moderator: 'Moderator', learner: 'Member' }

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
    } catch { setError('Something went wrong.') }
    finally { setCancelling(false) }
  }

  return (
    <div className="flex items-start gap-3 px-5 py-3.5">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold" style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}>
        {(invite.name ?? invite.email).charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium" style={{ color: '#152236' }}>
          {invite.name ?? invite.email}
        </p>
        <p className="truncate text-[11px] text-slate-400">{invite.email} · {ROLE_LABEL[invite.role] ?? invite.role}</p>
        <p className="mt-0.5 text-[11px] text-slate-400">Invited {formatShortDate(invite.created_at)}</p>
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
// Pending access request row
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
        setError(typeof body.detail === 'string' ? body.detail : `Could not ${action} request.`)
      }
    } catch { setError('Something went wrong.') }
    finally { setter(false) }
  }

  return (
    <div className="flex items-start gap-3 px-5 py-3.5">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold" style={{ background: 'rgba(212,176,72,0.14)', color: '#b08d2a' }}>
        {request.user_display_name.charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium" style={{ color: '#152236' }}>
          {request.user_display_name}
        </p>
        <p className="truncate text-[11px] text-slate-400">{request.user_email}</p>
        <p className="mt-0.5 text-[11px] text-slate-400">Requested {formatShortDate(request.created_at)}</p>
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
// People card
// ---------------------------------------------------------------------------

function PeopleCard({
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
    <Card accent={totalPending > 0 ? 'gold' : undefined}>
      <CardBody>
        <SectionLabel>People</SectionLabel>
        {/* Stats */}
        <div className="mb-4 flex gap-6">
          {memberCount > 0 && (
            <div>
              <p className="text-[22px] font-semibold leading-none" style={{ color: '#152236' }}>{memberCount}</p>
              <p className="mt-0.5 text-[11px] text-slate-400">{memberCount === 1 ? 'member' : 'members'}</p>
            </div>
          )}
          {leaderCount > 0 && (
            <div>
              <p className="text-[22px] font-semibold leading-none" style={{ color: '#152236' }}>{leaderCount}</p>
              <p className="mt-0.5 text-[11px] text-slate-400">{leaderCount === 1 ? 'leader' : 'leaders'}</p>
            </div>
          )}
          {totalPending > 0 && (
            <div>
              <p className="text-[22px] font-semibold leading-none" style={{ color: '#b08d2a' }}>{totalPending}</p>
              <p className="mt-0.5 text-[11px] text-slate-400">pending</p>
            </div>
          )}
        </div>

        {/* Add person toggle */}
        {!showAddForm && (
          <button
            onClick={() => setShowAddForm(true)}
            className="mb-4 flex items-center gap-1.5 rounded-xl border border-slate-200 px-4 py-2.5 text-[13px] font-semibold text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            + Add person
          </button>
        )}
        {showAddForm && (
          <div className="mb-4">
            <AddPersonForm spaceSlug={spaceSlug} onDone={() => setShowAddForm(false)} />
          </div>
        )}
      </CardBody>

      {/* Pending access requests */}
      {requests.length > 0 && (
        <div>
          <div className="border-t px-5 pt-3 pb-1" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            <p className="text-[11px] font-bold uppercase tracking-[0.12em]" style={{ color: '#b08d2a' }}>
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

      {/* Pending invitations */}
      {invitations.length > 0 && (
        <div>
          <div className="border-t px-5 pt-3 pb-1" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
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
  )
}

// ---------------------------------------------------------------------------
// Pathways card
// ---------------------------------------------------------------------------

function PathwaysCard({
  counts,
  published,
  spaceSlug,
}: {
  counts: LiteData['pathwayCounts']
  published: LitePathway[]
  spaceSlug: string
}) {
  const total = counts.published + counts.comingSoon + counts.drafts + counts.archived
  return (
    <Card>
      <CardBody>
        <SectionLabel>Pathways</SectionLabel>
        {total === 0 ? (
          <p className="mb-3 text-[13px] text-slate-400">No pathways yet.</p>
        ) : (
          <div className="mb-4 flex flex-wrap gap-x-6 gap-y-3">
            {counts.published > 0 && (
              <div>
                <p className="text-[20px] font-semibold leading-none" style={{ color: '#152236' }}>{counts.published}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">published</p>
              </div>
            )}
            {counts.comingSoon > 0 && (
              <div>
                <p className="text-[20px] font-semibold leading-none" style={{ color: '#152236' }}>{counts.comingSoon}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">coming soon</p>
              </div>
            )}
            {counts.drafts > 0 && (
              <div>
                <p className="text-[20px] font-semibold leading-none" style={{ color: '#152236' }}>{counts.drafts}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">{counts.drafts === 1 ? 'draft' : 'drafts'}</p>
              </div>
            )}
            {counts.archived > 0 && (
              <div>
                <p className="text-[20px] font-semibold leading-none text-slate-400">{counts.archived}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">archived</p>
              </div>
            )}
          </div>
        )}
        <p className="text-[12px] text-slate-400">Create and edit pathways on desktop.</p>
      </CardBody>

      {/* Published pathway list */}
      {published.length > 0 && (
        <div className="border-t" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
          <div className="divide-y" style={{ borderColor: 'rgba(0,0,0,0.07)' }}>
            {published.map(p => (
              <div key={p.slug} className="flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium" style={{ color: '#152236' }}>{p.title}</p>
                  <p className="mt-0.5 text-[11px] text-slate-400">{accessLabel(p)}</p>
                </div>
                <Link
                  href={`/spaces/${spaceSlug}/pathways/${p.slug}`}
                  className="shrink-0 rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:border-teal-200 hover:text-teal-700"
                >
                  Preview →
                </Link>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
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
  const [switchingTo, setSwitchingTo] = useState<string | null>(null)

  const {
    pathwayCounts,
    publishedPathways,
    upcomingGatherings,
    memberCount,
    leaderCount,
    members,
    invitations,
    accessRequests,
    resourceCount,
  } = liteData

  const slug = activeSpace?.slug ?? ''
  const totalPending = invitations.length + accessRequests.filter(r => r.status === 'pending').length

  function switchCollective(newSlug: string) {
    if (newSlug === slug) return
    setSwitchingTo(newSlug)
    document.cookie = `fc_creator_space=${newSlug}; path=/; max-age=86400`
    router.push('/creator-studio')
    router.refresh()
  }

  return (
    <div className="min-h-screen" style={{ background: '#F7F8FA' }}>

      {/* ── Header ── */}
      <div style={{ background: 'linear-gradient(180deg, #073B3A 0%, #062F35 100%)', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <div className="px-4 pt-4 pb-4">
          {/* Branding */}
          <div className="mb-3">
            <p className="font-serif text-[17px] leading-tight text-white">Creator Studio</p>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em]" style={{ color: 'rgba(255,255,255,0.40)' }}>
              Fresh Collective
            </p>
          </div>

          {/* Current collective */}
          {activeSpace && (
            <div className="mb-3 rounded-xl px-3 py-2.5" style={{ background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.10)' }}>
              <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: '#42C7C6' }}>
                Current collective
              </p>
              <p className="mt-0.5 text-[14px] font-semibold leading-snug text-white">{activeSpace.name}</p>
              <p className="mt-0.5 text-[11px]" style={{ color: 'rgba(255,255,255,0.50)' }}>
                {activeSpace.is_public ? 'Public' : 'Private'} · {activeSpace.status === 'active' ? 'Active' : 'Draft'}
              </p>
              {/* Collective switcher */}
              {spaces.length > 1 && (
                <div className="mt-2">
                  <select
                    value={activeSpace.slug}
                    onChange={e => switchCollective(e.target.value)}
                    disabled={switchingTo !== null}
                    className="w-full rounded-lg border bg-transparent px-2.5 py-1.5 text-[12px] font-medium text-white outline-none"
                    style={{ borderColor: 'rgba(255,255,255,0.22)', background: 'rgba(0,0,0,0.20)' }}
                  >
                    {spaces.map(s => (
                      <option key={s.slug} value={s.slug} style={{ background: '#073B3A' }}>
                        {s.name}{s.status !== 'active' ? ' (Draft)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          {/* Nav links */}
          <div className="flex items-center gap-4">
            <Link href="/dashboard" className="text-[12px] font-medium transition-opacity hover:opacity-80" style={{ color: 'rgba(255,255,255,0.55)' }}>
              ← Back to platform
            </Link>
            {activeSpace && (
              <Link href={`/spaces/${slug}`} className="ml-auto text-[12px] font-semibold transition-opacity hover:opacity-80" style={{ color: '#8DE8E6' }}>
                View public page →
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* ── Cards ── */}
      <div className="space-y-4 px-4 py-5 pb-10">

        {/* Notice */}
        <Card>
          <CardBody>
            <p className="mb-1.5 text-[15px] font-semibold" style={{ color: '#152236' }}>Creator Studio Lite</p>
            <p className="mb-4 text-[13px] leading-relaxed text-slate-500">
              From mobile, you can check bookings, invite people, copy links, and preview your collective.
              Use desktop for detailed editing.
            </p>
            {activeSpace && (
              <div className="flex gap-2.5">
                <Link
                  href={`/spaces/${slug}`}
                  className="flex-1 rounded-xl px-4 py-2.5 text-center text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                >
                  View collective
                </Link>
                <div>
                  <CopyButton
                    text={typeof window !== 'undefined' ? `${window.location.origin}/spaces/${slug}` : `/spaces/${slug}`}
                    label="Copy link"
                  />
                </div>
              </div>
            )}
          </CardBody>
        </Card>

        {/* Collective overview + public page links */}
        {activeSpace && (
          <Card accent="teal">
            <CardBody>
              <SectionLabel>Your collective</SectionLabel>
              <p className="text-[16px] font-semibold leading-snug" style={{ color: '#152236' }}>{activeSpace.name}</p>
              {activeSpace.tagline && (
                <p className="mt-1 mb-3 text-[13px] leading-relaxed text-slate-500">{activeSpace.tagline}</p>
              )}
              <div className="mb-4 flex flex-wrap gap-2">
                <span
                  className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                  style={{
                    background: activeSpace.status === 'active' ? 'rgba(56,160,158,0.10)' : 'rgba(0,0,0,0.06)',
                    color: activeSpace.status === 'active' ? '#38A09E' : '#64748b',
                  }}
                >
                  {activeSpace.status === 'active' ? 'Active' : 'Draft'}
                </span>
                <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold" style={{ background: 'rgba(0,0,0,0.05)', color: '#64748b' }}>
                  {activeSpace.is_public ? 'Public' : 'Private'}
                </span>
              </div>
              {/* Public page quick links */}
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Browse as member</p>
              <div className="flex flex-wrap gap-2">
                {[
                  { label: 'About',       href: `/spaces/${slug}/about` },
                  { label: 'Pathways',    href: `/spaces/${slug}/pathways` },
                  { label: 'Gatherings',  href: `/spaces/${slug}/events` },
                  { label: 'Resources',   href: `/spaces/${slug}/resources` },
                  { label: 'Community',   href: `/spaces/${slug}/community` },
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
        )}

        {/* Gatherings */}
        {activeSpace && upcomingGatherings.length > 0 && (
          <GatheringsCard gatherings={upcomingGatherings} spaceSlug={slug} members={members} />
        )}

        {/* People */}
        {activeSpace && (
          <PeopleCard
            memberCount={memberCount}
            leaderCount={leaderCount}
            invitations={invitations}
            accessRequests={accessRequests.filter(r => r.status === 'pending')}
            spaceSlug={slug}
          />
        )}

        {/* Pathways */}
        {activeSpace && (
          <PathwaysCard counts={pathwayCounts} published={publishedPathways} spaceSlug={slug} />
        )}

        {/* Resources */}
        {activeSpace && (
          <Card>
            <CardBody>
              <SectionLabel>Resources</SectionLabel>
              {resourceCount > 0 ? (
                <p className="mb-3 text-[15px] font-semibold" style={{ color: '#152236' }}>
                  {resourceCount} resource{resourceCount !== 1 ? 's' : ''}
                </p>
              ) : (
                <p className="mb-3 text-[13px] text-slate-400">No published resources yet.</p>
              )}
              <Link
                href={`/spaces/${slug}/resources`}
                className="inline-flex items-center rounded-xl border border-slate-200 px-3.5 py-2 text-[12px] font-medium text-slate-600 hover:border-teal-200 hover:text-teal-700"
              >
                View resources page →
              </Link>
              <p className="mt-3 text-[12px] text-slate-400">Upload and organise resources on desktop.</p>
            </CardBody>
          </Card>
        )}

        {/* No collective selected */}
        {!activeSpace && (
          <Card>
            <CardBody>
              <p className="mb-2 text-[15px] font-semibold" style={{ color: '#152236' }}>No collective selected</p>
              <p className="mb-4 text-[13px] text-slate-500">Open Creator Studio on a larger screen to set up your collective.</p>
              <Link href="/dashboard" className="text-[13px] font-medium" style={{ color: '#38A09E' }}>
                ← Back to platform
              </Link>
            </CardBody>
          </Card>
        )}

        <p className="text-center text-[11px] text-slate-400">
          Signed in as {user.name ?? user.email}
        </p>

      </div>
    </div>
  )
}
