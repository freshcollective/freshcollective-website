'use client'

import { useState, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import type { MemberProfile, SpaceInvitation } from '@/types/platform'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Unified entry type
// ---------------------------------------------------------------------------

type PersonEntry =
  | { kind: 'member'; data: MemberProfile }
  | { kind: 'invite'; data: SpaceInvitation }

function entryId(e: PersonEntry)     { return e.data.id }
function entryStatus(e: PersonEntry) { return e.kind === 'member' ? 'active' : 'invited' }
function entryRole(e: PersonEntry)   { return e.kind === 'member' ? e.data.space_role : e.data.role }
function entryDate(e: PersonEntry)   { return e.kind === 'member' ? e.data.joined_at : e.data.created_at }

function entryDisplayName(e: PersonEntry): string {
  if (e.kind === 'member') return e.data.display_name
  return e.data.name || e.data.email
}

function entryEmail(e: PersonEntry): string | null {
  if (e.kind === 'member') return null  // not exposed by current endpoint
  return e.data.email
}

function entryMatchesSearch(e: PersonEntry, q: string): boolean {
  const name = entryDisplayName(e).toLowerCase()
  const email = entryEmail(e)?.toLowerCase() ?? ''
  return name.includes(q) || email.includes(q)
}

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

const ROLE_LABEL: Record<string, string> = {
  creator:   'Leader',
  moderator: 'Moderator',
  learner:   'Member',
}

function roleBadgeStyle(role: string): { background: string; color: string } {
  if (role === 'creator')   return { background: 'rgba(14,116,144,0.10)',  color: '#0e7470' }
  if (role === 'moderator') return { background: 'rgba(99,102,241,0.09)',  color: '#6366f1' }
  return                           { background: 'rgba(56,160,158,0.09)',  color: '#38A09E' }
}

const STATUS_STYLE: Record<string, { background: string; color: string }> = {
  active:    { background: 'rgba(56,160,158,0.10)',  color: '#38A09E' },
  invited:   { background: 'rgba(234,179,8,0.12)',   color: '#a16207' },
  paused:    { background: 'rgba(148,163,184,0.15)', color: '#64748b' },
  completed: { background: 'rgba(99,102,241,0.10)',  color: '#6366f1' },
  removed:   { background: 'rgba(239,68,68,0.08)',   color: '#dc2626' },
}

function statusStyle(s: string) { return STATUS_STYLE[s] ?? STATUS_STYLE.active }

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

function initials(name: string) {
  return name.split(' ').slice(0, 2).map((p) => p[0] ?? '').join('').toUpperCase()
}

// ---------------------------------------------------------------------------
// Small pieces
// ---------------------------------------------------------------------------

function Avatar({ name }: { name: string }) {
  return (
    <div
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
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

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize"
      style={statusStyle(status)}
    >
      {status}
    </span>
  )
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <div className="mt-1">{children}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function DetailPanel({ entry, onClose }: { entry: PersonEntry; onClose: () => void }) {
  const status = entryStatus(entry)
  const role   = entryRole(entry)
  const email  = entryEmail(entry)
  const name   = entryDisplayName(entry)
  const date   = entryDate(entry)
  const note   = entry.kind === 'invite' ? entry.data.note : null
  const bio    = entry.kind === 'member' ? entry.data.bio  : null

  return (
    <div className="rounded-2xl border border-border bg-white">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-[15px] font-semibold text-navy-900">Member details</h2>
        <button
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          aria-label="Close"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="space-y-5 px-5 py-5">

        {/* Identity */}
        <div className="flex items-center gap-3">
          <Avatar name={name} />
          <div>
            <p className="text-[15px] font-semibold text-navy-900">{name}</p>
            {email ? (
              <p className="mt-0.5 text-[13px] text-slate-600">{email}</p>
            ) : (
              /* TODO: Expose email via a creator-only members endpoint */
              <p className="mt-0.5 text-[12px] italic text-slate-400">Email not available in this view</p>
            )}
          </div>
        </div>

        {/* Status + Role */}
        <div className="flex flex-wrap gap-5">
          <FieldRow label="Status">
            <StatusBadge status={status} />
          </FieldRow>
          <FieldRow label="Role">
            <RoleBadge role={role} />
          </FieldRow>
        </div>

        {/* Date */}
        <FieldRow label={entry.kind === 'invite' ? 'Invited' : 'Joined'}>
          <p className="text-[14px] text-navy-900">{formatDate(date)}</p>
        </FieldRow>

        {/* Bio (members only) */}
        {bio && (
          <FieldRow label="Bio">
            <p className="text-[13px] leading-relaxed text-slate-600">{bio}</p>
          </FieldRow>
        )}

        {/* Invite note (invites only) */}
        {note && (
          <FieldRow label="Invite note">
            <p className="text-[13px] leading-relaxed text-slate-600">{note}</p>
          </FieldRow>
        )}

        {/* Current pathway */}
        <FieldRow label="Current pathway">
          {/* TODO: Connect to enrollment data once available */}
          <p className="text-[13px] italic text-slate-400">
            {entry.kind === 'invite' ? 'Not started yet' : 'Not tracked yet'}
          </p>
        </FieldRow>

        {/* Last activity */}
        <FieldRow label="Last activity">
          {/* TODO: Aggregate from step_progress to compute last active date per member */}
          <p className="text-[13px] italic text-slate-400">
            {entry.kind === 'invite' ? 'Not active yet' : 'Not tracked yet'}
          </p>
        </FieldRow>

        {/* Tags */}
        <FieldRow label="Tags">
          {/* TODO: Add a tags/labels model to space_membership or a separate join table */}
          <p className="text-[13px] italic text-slate-400">No tags yet</p>
          <button
            disabled
            title="Tag saving coming soon"
            className="mt-2 cursor-not-allowed rounded-full border border-dashed border-slate-300 px-2.5 py-0.5 text-[11px] font-medium text-slate-400"
          >
            + Add tag
          </button>
        </FieldRow>

        <div className="border-t border-border" />

        {/* Private creator notes */}
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Private creator notes
          </p>
          <p className="mb-2 mt-0.5 text-[11px] text-slate-400">Only you can see these notes.</p>
          {/* TODO: Persist private creator notes when member notes API is available. */}
          <textarea
            rows={4}
            disabled
            placeholder="Add a private note about this person..."
            className="w-full cursor-not-allowed resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-400 placeholder-slate-300 outline-none"
          />
          <p className="mt-1.5 text-[11px] text-slate-400">Note saving coming soon.</p>
        </div>

      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invite modal (wired to real API)
// ---------------------------------------------------------------------------

function InviteModal({
  spaceSlug,
  existingInviteEmails,
  onClose,
  onSuccess,
}: {
  spaceSlug: string
  existingInviteEmails: Set<string>
  onClose: () => void
  onSuccess: () => void
}) {
  const [name, setName]     = useState('')
  const [email, setEmail]   = useState('')
  const [role, setRole]     = useState('learner')
  const [note, setNote]     = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState<string | null>(null)
  const [sent, setSent]     = useState(false)

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

  async function handleSubmit() {
    setError(null)
    const trimmedEmail = email.trim().toLowerCase()

    if (!trimmedEmail) {
      setError('Enter a valid email address.')
      return
    }
    if (!EMAIL_RE.test(trimmedEmail)) {
      setError('Enter a valid email address.')
      return
    }
    if (existingInviteEmails.has(trimmedEmail)) {
      setError('This person has already been invited to this collective.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/invitations`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          email: trimmedEmail,
          name: name.trim() || null,
          role,
          note: note.trim() || null,
        }),
      })

      if (!res.ok) {
        let detail: string | null = null
        try {
          const body = await res.json()
          if (typeof body.detail === 'string') detail = body.detail
          else if (Array.isArray(body.detail) && body.detail.length > 0) {
            // Pydantic 422 validation error — extract first message
            const first = body.detail[0]
            detail = typeof first?.msg === 'string' ? first.msg : null
          }
        } catch { /* response not JSON */ }

        if (res.status === 409) {
          setError(detail ?? 'This person already belongs to or has been invited to this collective.')
        } else if (res.status === 422 || res.status === 400) {
          setError(detail ?? 'Enter a valid email address.')
        } else {
          setError(detail ?? 'Invite could not be created. Please try again.')
        }
        return
      }

      setSent(true)
      onSuccess()
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl">

        {sent ? (
          <div className="py-4 text-center">
            <div
              className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
              style={{ background: 'rgba(56,160,158,0.10)' }}
            >
              <svg width="20" height="16" viewBox="0 0 20 16" fill="none" aria-hidden="true">
                <path d="M2 8l5 5L18 2" stroke="#38A09E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-[16px] font-semibold text-navy-900">Invite created</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
              <span className="font-medium text-navy-900">{email.trim().toLowerCase()}</span> has
              been added to your invited list.
            </p>
            {/* TODO: Send invitation email when email service is connected. */}
            <p className="mt-2 text-[11px] text-slate-400">
              No email has been sent yet — email sending coming soon.
            </p>
            <button
              onClick={onClose}
              className="mt-5 rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Done
            </button>
          </div>
        ) : (
          <>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-[17px] font-semibold text-navy-900">Invite person</h2>
              <button
                onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                aria-label="Close"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Jane Smith"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
                />
              </div>

              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                  Email address <span className="font-normal text-slate-400">(required)</span>
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); setError(null) }}
                  placeholder="jane@example.com"
                  className={`w-full rounded-lg border px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 ${
                    error ? 'border-red-300' : 'border-slate-200'
                  }`}
                />
              </div>

              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Role</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
                >
                  <option value="learner">Member</option>
                  <option value="moderator">Moderator</option>
                  <option value="creator">Leader</option>
                </select>
              </div>

              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                  Personal note{' '}
                  <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="A short note about this person or why you're inviting them…"
                  rows={3}
                  className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
                />
              </div>
            </div>

            {/* Error message */}
            {error && (
              <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">
                {error}
              </p>
            )}

            <div className="mt-6 flex items-center justify-between gap-3">
              {/* TODO: Send invitation email when email service is connected. */}
              <p className="text-[11px] text-slate-400">No email is sent yet.</p>
              <button
                disabled={!email.trim() || loading}
                onClick={handleSubmit}
                className="shrink-0 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {loading ? 'Creating…' : 'Create invite'}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// People list
// ---------------------------------------------------------------------------

function PeopleList({
  entries,
  totalCount,
  statusFilter,
  selected,
  onSelect,
  onInvite,
}: {
  entries: PersonEntry[]
  totalCount: number
  statusFilter: string
  selected: PersonEntry | null
  onSelect: (e: PersonEntry) => void
  onInvite: () => void
}) {
  if (entries.length === 0) {
    return (
      <div className="px-6 py-14 text-center">
        {totalCount === 0 ? (
          <>
            <p className="mb-1 text-[15px] font-semibold text-navy-900">No people yet.</p>
            <p className="mb-5 text-[14px] leading-relaxed text-slate-500">
              Invite your first person when you are ready to open this collective.
            </p>
            <button
              onClick={onInvite}
              className="rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Invite person
            </button>
          </>
        ) : statusFilter !== 'all' && statusFilter !== 'active' && statusFilter !== 'invited' ? (
          <>
            <p className="text-[14px] text-slate-500">
              No members with <span className="font-medium capitalize">{statusFilter}</span> status.
            </p>
            {/* TODO: Surface paused/completed/removed once creator endpoint exposes all statuses */}
            <p className="mt-1 text-[13px] italic text-slate-400">
              Status tracking beyond Active and Invited is coming soon.
            </p>
          </>
        ) : (
          <p className="text-[14px] text-slate-400">No people match your search.</p>
        )}
      </div>
    )
  }

  return (
    <ul>
      {entries.map((entry, i) => {
        const isLast     = i === entries.length - 1
        const isSelected = selected ? entryId(selected) === entryId(entry) : false
        const status     = entryStatus(entry)
        const role       = entryRole(entry)
        const name       = entryDisplayName(entry)
        const email      = entryEmail(entry)
        const date       = entryDate(entry)

        return (
          <li key={entryId(entry)}>
            <button
              onClick={() => onSelect(entry)}
              className={`w-full cursor-pointer text-left transition-colors ${
                !isLast ? 'border-b border-border' : ''
              } ${isSelected ? 'bg-teal-50/50' : 'hover:bg-teal-50/30'}`}
              style={isSelected ? { borderLeft: '2px solid rgba(56,160,158,0.45)' } : undefined}
            >
              <div className="flex items-center gap-4 px-5 py-4">
                <Avatar name={name} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-medium text-navy-900">{name}</p>
                  {email ? (
                    <p className="mt-0.5 truncate text-[12px] text-slate-500">{email}</p>
                  ) : (
                    /* TODO: Show email once creator endpoint exposes it */
                    <p className="mt-0.5 truncate text-[12px] italic text-slate-400">
                      Email not available
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                  <StatusBadge status={status} />
                  <RoleBadge role={role} />
                  <span className="hidden text-[12px] text-slate-400 sm:inline">
                    {formatDate(date)}
                  </span>
                </div>
              </div>
              <p className="px-5 pb-3 text-[12px] text-slate-400 sm:hidden">
                {entry.kind === 'invite' ? 'Invited ' : 'Joined '}
                {formatDate(date)}
              </p>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Status filter options
// ---------------------------------------------------------------------------

const STATUS_OPTIONS = [
  { value: 'all',       label: 'All statuses' },
  { value: 'active',    label: 'Active' },
  { value: 'invited',   label: 'Invited' },
  // TODO: Surface these once creator endpoint exposes all membership statuses
  { value: 'paused',    label: 'Paused' },
  { value: 'completed', label: 'Completed' },
  { value: 'removed',   label: 'Removed' },
]

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface Props {
  members:     MemberProfile[]
  invitations: SpaceInvitation[]
  spaceName:   string
  spaceSlug:   string
}

export default function PeopleClient({ members, invitations, spaceName, spaceSlug }: Props) {
  const router = useRouter()
  const [search, setSearch]             = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selected, setSelected]         = useState<PersonEntry | null>(null)
  const [inviteOpen, setInviteOpen]     = useState(false)

  // Derived stats
  const now = new Date()
  const newThisMonth = members.filter((m) => {
    const d = new Date(m.joined_at)
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()
  }).length

  // Combined total (members + pending invitations)
  const totalCount = members.length + invitations.length

  // Build unified sorted list: active members first, then invitations by date
  const allEntries: PersonEntry[] = useMemo(() => {
    const memberEntries: PersonEntry[] = members.map((m) => ({ kind: 'member', data: m }))
    const inviteEntries: PersonEntry[] = invitations.map((i) => ({ kind: 'invite', data: i }))
    return [...memberEntries, ...inviteEntries]
  }, [members, invitations])

  const filtered = useMemo(() => {
    let list = allEntries
    if (statusFilter === 'active')  list = list.filter((e) => e.kind === 'member')
    else if (statusFilter === 'invited') list = list.filter((e) => e.kind === 'invite')
    else if (statusFilter !== 'all') {
      // paused/completed/removed — no data yet
      list = []
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter((e) => entryMatchesSearch(e, q))
    }
    return list
  }, [allEntries, statusFilter, search])

  const existingInviteEmails = useMemo(
    () => new Set(invitations.map((i) => i.email.toLowerCase())),
    [invitations],
  )

  function handleSelect(entry: PersonEntry) {
    setSelected((prev) =>
      prev && entryId(prev) === entryId(entry) ? null : entry,
    )
  }

  function handleInviteSuccess() {
    // Refresh server component data to pick up the new invitation
    router.refresh()
  }

  return (
    <div className="w-full max-w-[1180px] space-y-6 px-8 py-8 md:px-10 md:py-10">

      {/* ── Header ── */}
      <div>
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          {spaceName}
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">People</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          See who belongs to this collective, how they joined, and where they are in the experience.
        </p>
      </div>

      {/* ── Stats row ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Total people',   value: totalCount },
          { label: 'Active members', value: members.length },
          { label: 'Invited',        value: invitations.length },
          { label: 'New this month', value: newThisMonth },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-white p-4">
            <p className="font-serif text-2xl text-navy-900">{value}</p>
            <p className="mt-0.5 text-[13px] text-slate-500">{label}</p>
          </div>
        ))}
      </div>

      {/* ── Main area: list + detail panel ── */}
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">

        {/* List card */}
        <div className="min-w-0 flex-1 rounded-2xl border border-border bg-white">

          {/* Toolbar */}
          <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-4">
            <input
              type="text"
              placeholder="Search by name or email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="min-w-[140px] flex-1 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
            />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button
              onClick={() => setInviteOpen(true)}
              className="ml-auto shrink-0 rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Invite person
            </button>
          </div>

          <PeopleList
            entries={filtered}
            totalCount={totalCount}
            statusFilter={statusFilter}
            selected={selected}
            onSelect={handleSelect}
            onInvite={() => setInviteOpen(true)}
          />
        </div>

        {/* Detail panel — right of list at xl+, stacked below on smaller screens */}
        {selected && (
          <div className="w-full xl:w-[340px] xl:shrink-0">
            <DetailPanel entry={selected} onClose={() => setSelected(null)} />
          </div>
        )}
      </div>

      {/* ── Privacy note ── */}
      <p className="text-[13px] text-slate-500">
        <span className="font-medium">Private to creator admins.</span>{' '}
        Use member information respectfully and only for managing this collective.
      </p>

      {/* ── Invite modal ── */}
      {inviteOpen && (
        <InviteModal
          spaceSlug={spaceSlug}
          existingInviteEmails={existingInviteEmails}
          onClose={() => setInviteOpen(false)}
          onSuccess={handleInviteSuccess}
        />
      )}
    </div>
  )
}
