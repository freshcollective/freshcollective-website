'use client'

import { useState, useMemo } from 'react'
import type { MemberProfile } from '@/types/platform'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROLE_LABEL: Record<string, string> = {
  creator: 'Leader',
  moderator: 'Moderator',
  learner: 'Member',
}

function roleBadgeStyle(role: string): { background: string; color: string } {
  if (role === 'creator')   return { background: 'rgba(14,116,144,0.10)',  color: '#0e7470' }
  if (role === 'moderator') return { background: 'rgba(99,102,241,0.08)',  color: '#6366f1' }
  return                           { background: 'rgba(56,160,158,0.08)',  color: '#38A09E' }
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function initials(name: string) {
  return name
    .split(' ')
    .slice(0, 2)
    .map((p) => p[0] ?? '')
    .join('')
    .toUpperCase()
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Avatar({ name }: { name: string }) {
  return (
    <div
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
      style={{ background: 'rgba(56,160,158,0.12)', color: '#38A09E' }}
    >
      {initials(name)}
    </div>
  )
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={roleBadgeStyle(role)}
    >
      {ROLE_LABEL[role] ?? role}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Person detail panel (inline expand)
// ---------------------------------------------------------------------------

function PersonDetail({
  person,
  onClose,
}: {
  person: MemberProfile
  onClose: () => void
}) {
  const bStyle = roleBadgeStyle(person.space_role)

  return (
    <div className="border-b border-border bg-slate-50/60 px-5 py-5">
      <div className="grid gap-6 sm:grid-cols-2">

        {/* Left column */}
        <div className="space-y-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Name</p>
            <p className="mt-0.5 text-[14px] text-navy-900">{person.display_name}</p>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Role</p>
            <div className="mt-1">
              <span
                className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={bStyle}
              >
                {ROLE_LABEL[person.space_role] ?? person.space_role}
              </span>
            </div>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Joined</p>
            <p className="mt-0.5 text-[14px] text-navy-900">{formatDate(person.joined_at)}</p>
          </div>

          {person.bio && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Bio</p>
              <p className="mt-0.5 text-[13px] leading-relaxed text-slate-600">{person.bio}</p>
            </div>
          )}

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Email</p>
            {/* TODO: Expose email via a creator-only members endpoint */}
            <p className="mt-0.5 text-[13px] italic text-slate-400">Not available in this view</p>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Status</p>
            <span
              className="mt-1 inline-block rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}
            >
              Active
            </span>
            {/* TODO: Surface paused/invited/removed statuses once creator endpoint exposes them */}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Current pathway
            </p>
            {/* TODO: Connect to enrollment data (/api/spaces/{slug}/members/{id}/enrollments) */}
            <p className="mt-0.5 text-[13px] italic text-slate-400">Not tracked yet</p>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Last activity
            </p>
            {/* TODO: Connect to step_progress data to compute last active date */}
            <p className="mt-0.5 text-[13px] italic text-slate-400">Not tracked yet</p>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Tags</p>
            {/* TODO: Add a tags/labels model to space_membership or a join table */}
            <p className="mt-0.5 text-[13px] italic text-slate-400">No tags yet</p>
          </div>

          <div>
            <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Private creator notes
            </p>
            <p className="mb-1.5 text-[11px] text-slate-400">Only you can see these notes.</p>
            {/* TODO: Persist notes to backend — add a creator_member_notes table or
                store in space_membership.metadata JSON column */}
            <textarea
              rows={3}
              disabled
              placeholder="Note saving coming soon…"
              className="w-full cursor-not-allowed resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-400 placeholder-slate-300 outline-none"
            />
          </div>
        </div>
      </div>

      <button
        onClick={onClose}
        className="mt-4 text-[12px] font-medium text-teal-600 transition-colors hover:text-teal-700"
      >
        Close ↑
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invite modal
// ---------------------------------------------------------------------------

function InviteModal({ onClose }: { onClose: () => void }) {
  const [name, setName]     = useState('')
  const [email, setEmail]   = useState('')
  const [note, setNote]     = useState('')
  const [sent, setSent]     = useState(false)

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-xl">
        {sent ? (
          <div className="py-4 text-center">
            <div
              className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
              style={{ background: 'rgba(56,160,158,0.10)' }}
            >
              <svg width="20" height="16" viewBox="0 0 20 16" fill="none" aria-hidden="true">
                <path
                  d="M2 8l5 5L18 2"
                  stroke="#38A09E"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <p className="text-[16px] font-semibold text-navy-900">Invite queued</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
              <span className="font-medium text-navy-900">{email}</span> will receive an invite
              once the email service is connected.
            </p>
            {/* TODO: Connect invite flow to backend/email service. */}
            <p className="mt-2 text-[11px] text-slate-400">
              This is a UI placeholder — no email has been sent yet.
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
                  <path
                    d="M1 1l12 12M13 1L1 13"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
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
                  Email address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="jane@example.com"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
                />
              </div>

              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">
                  Personal note{' '}
                  <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="A short message to include with the invite…"
                  rows={3}
                  className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
                />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-between gap-3">
              <p className="text-[11px] text-slate-400">
                {/* TODO: Connect invite flow to backend/email service. */}
                Invite emails are not yet sent.
              </p>
              <button
                disabled={!email.trim()}
                onClick={() => setSent(true)}
                className="shrink-0 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                Send invite
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Main client component
// ---------------------------------------------------------------------------

interface Props {
  members: MemberProfile[]
  spaceName: string
}

export default function PeopleClient({ members, spaceName }: Props) {
  const [search, setSearch]         = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [selected, setSelected]     = useState<MemberProfile | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)

  const now = new Date()
  const newThisMonth = members.filter((m) => {
    const d = new Date(m.joined_at)
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()
  }).length

  const filtered = useMemo(() => {
    let list = members
    if (roleFilter !== 'all') list = list.filter((m) => m.space_role === roleFilter)
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter((m) => m.display_name.toLowerCase().includes(q))
    }
    return list
  }, [members, roleFilter, search])

  function toggleSelected(m: MemberProfile) {
    setSelected((prev) => (prev?.id === m.id ? null : m))
  }

  return (
    <div className="max-w-5xl space-y-6 px-8 py-8 md:px-10 md:py-10">

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
          { label: 'Total people',    value: members.length },
          { label: 'Active members',  value: members.length },
          // TODO: Surface invited count once invitation table/endpoint exists
          { label: 'Invited',         value: 0 },
          { label: 'New this month',  value: newThisMonth },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-white p-4">
            <p className="font-serif text-2xl text-navy-900">{value}</p>
            <p className="mt-0.5 text-[13px] text-slate-500">{label}</p>
          </div>
        ))}
      </div>

      {/* ── Main card ── */}
      <div className="rounded-2xl border border-border bg-white">

        {/* Search + filter bar */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-4">
          <input
            type="text"
            placeholder="Search by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="min-w-[160px] flex-1 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
          />
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
          >
            <option value="all">All roles</option>
            <option value="learner">Members</option>
            <option value="moderator">Moderators</option>
            <option value="creator">Leaders</option>
          </select>
          {/* TODO: Add filter by pathway once enrollment data is available */}
          {/* TODO: Add filter by tag once tags model exists */}
          <button
            onClick={() => setInviteOpen(true)}
            className="ml-auto shrink-0 rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Invite person
          </button>
        </div>

        {/* People list */}
        {filtered.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <p className="text-[14px] text-slate-400">
              {members.length === 0
                ? 'No people in this collective yet.'
                : 'No people match your search.'}
            </p>
          </div>
        ) : (
          <div>
            {/* Column headers — desktop only */}
            <div
              className="hidden border-b border-border px-5 py-2.5 sm:grid"
              style={{ gridTemplateColumns: '1fr 130px 150px' }}
            >
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Name</p>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Role</p>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Joined</p>
            </div>

            <ul>
              {filtered.map((m, i) => {
                const isLast     = i === filtered.length - 1
                const isSelected = selected?.id === m.id

                return (
                  <li key={m.id}>
                    {/* Row button */}
                    <button
                      onClick={() => toggleSelected(m)}
                      className={`w-full cursor-pointer text-left transition-colors ${
                        !isLast || isSelected ? 'border-b border-border' : ''
                      } ${isSelected ? 'bg-teal-50/40' : 'hover:bg-slate-50'}`}
                    >
                      {/* Desktop row */}
                      <div
                        className="hidden items-center gap-3 px-5 py-3.5 sm:grid"
                        style={{ gridTemplateColumns: '1fr 130px 150px' }}
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <Avatar name={m.display_name} />
                          <span className="truncate text-[14px] font-medium text-navy-900">
                            {m.display_name}
                          </span>
                        </div>
                        <RoleBadge role={m.space_role} />
                        <span className="text-[13px] text-slate-500">
                          {formatDate(m.joined_at)}
                        </span>
                      </div>

                      {/* Mobile card */}
                      <div className="flex items-start gap-3 px-5 py-4 sm:hidden">
                        <Avatar name={m.display_name} />
                        <div className="min-w-0 flex-1">
                          <p className="text-[14px] font-medium text-navy-900">
                            {m.display_name}
                          </p>
                          <div className="mt-1.5 flex flex-wrap items-center gap-2">
                            <RoleBadge role={m.space_role} />
                            <span className="text-[12px] text-slate-400">
                              {formatDate(m.joined_at)}
                            </span>
                          </div>
                        </div>
                      </div>
                    </button>

                    {/* Inline detail panel */}
                    {isSelected && (
                      <PersonDetail
                        person={m}
                        onClose={() => setSelected(null)}
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>

      {/* ── Privacy note ── */}
      <p className="text-[12px] text-slate-400">
        <span className="font-medium text-slate-500">Private to creator admins.</span>{' '}
        Use member information respectfully and only for managing this collective.
      </p>

      {/* ── Invite modal ── */}
      {inviteOpen && <InviteModal onClose={() => setInviteOpen(false)} />}
    </div>
  )
}
