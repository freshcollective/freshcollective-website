'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import type { MemberProfile, MemberPathwayAccessItem, SpaceInvitation } from '@/types/platform'
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

function roleBadgeStyle(role: string): { background: string; color: string } {
  if (role === 'creator')   return { background: 'rgba(14,116,144,0.10)',  color: '#0e7490' }
  if (role === 'moderator') return { background: 'rgba(99,102,241,0.09)',  color: '#6366f1' }
  return                           { background: 'rgba(56,160,158,0.09)',  color: '#38A09E' }
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
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
      {count !== undefined && (
        <span className="text-[13px] text-slate-400">{count}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invite link card
// ---------------------------------------------------------------------------

function InviteLinkCard({ spaceSlug, isPublic }: { spaceSlug: string; isPublic: boolean }) {
  const [origin, setOrigin] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setOrigin(window.location.origin)
  }, [])

  const inviteUrl = origin ? `${origin}/spaces/${spaceSlug}` : `/spaces/${spaceSlug}`

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(inviteUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API unavailable — select the text manually isn't ideal here
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-white p-5">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <p className="text-[14px] font-semibold text-navy-900">Collective link</p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-slate-500">
            {isPublic
              ? 'People can view this collective and join if access is open. Share this link freely.'
              : 'This collective is private. Share this link with people you want to invite — they can request access or be invited directly.'}
          </p>
        </div>
        {!isPublic && (
          <span
            className="mt-0.5 shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
            style={{ background: 'rgba(148,163,184,0.15)', color: '#64748b' }}
          >
            Private
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <div
          className="flex-1 truncate rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-600 select-all"
          title={inviteUrl}
        >
          {inviteUrl}
        </div>
        <button
          onClick={copyLink}
          className="shrink-0 rounded-lg px-4 py-2 text-[13px] font-semibold transition-all"
          style={{
            background: copied ? 'rgba(56,160,158,0.18)' : 'rgba(56,160,158,0.09)',
            color: '#38A09E',
          }}
        >
          {copied ? 'Copied!' : 'Copy link'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pathway access (grant access modal)
// ---------------------------------------------------------------------------

const ACCESS_STATE_STYLE: Record<string, { background: string; color: string }> = {
  accessible:   { background: 'rgba(56,160,158,0.10)',  color: '#0f766e' },
  locked:       { background: 'rgba(148,163,184,0.14)', color: '#475569' },
  revoked:      { background: 'rgba(239,68,68,0.08)',   color: '#dc2626' },
  expired:      { background: 'rgba(234,179,8,0.12)',   color: '#a16207' },
  cancelled:    { background: 'rgba(148,163,184,0.14)', color: '#475569' },
  coming_soon:  { background: 'rgba(234,179,8,0.12)',   color: '#a16207' },
  draft:        { background: 'rgba(99,102,241,0.10)',  color: '#6366f1' },
  archived:     { background: 'rgba(148,163,184,0.10)', color: '#64748b' },
}

function AccessPill({ state, label }: { state: string; label: string }) {
  const style = ACCESS_STATE_STYLE[state] ?? ACCESS_STATE_STYLE.locked
  return (
    <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold" style={style}>
      {label}
    </span>
  )
}

function PathwayAccessRow({
  item,
  spaceSlug,
  userId,
  onRevoked,
}: {
  item: MemberPathwayAccessItem
  spaceSlug: string
  userId: string
  onRevoked: () => void
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
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/members/${userId}/pathway-access/revoke`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ pathway_id: item.id }),
        },
      )
      if (res.ok) onRevoked()
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not revoke access.')
      }
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setRevoking(false)
    }
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
      {item.access_state === 'accessible' && item.total_steps === 0 && (
        <p className="mt-1 text-[11px] text-slate-400">No steps yet</p>
      )}
      {canRevoke && (
        <div className="mt-2 flex items-center gap-2">
          <button
            onClick={handleRevoke}
            disabled={revoking}
            className="text-[11px] font-medium text-red-500 underline underline-offset-2 transition-opacity hover:opacity-70 disabled:opacity-40"
          >
            {revoking ? 'Revoking…' : 'Revoke access'}
          </button>
        </div>
      )}
      {error && <p className="mt-1 text-[11px] text-red-500">{error}</p>}
    </div>
  )
}

interface PathwayOption { id: string; title: string; access_type: string }

function GrantAccessModal({
  spaceSlug,
  userId,
  onClose,
  onGranted,
}: {
  spaceSlug: string
  userId: string
  onClose: () => void
  onGranted: () => void
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
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/members/${userId}/pathway-access/grant`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ pathway_id: pathwayId, notes: notes.trim() || null }),
        },
      )
      if (res.ok) { setSuccess(true); onGranted() }
      else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not grant access.')
      }
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
        {success ? (
          <div className="py-4 text-center">
            <p className="text-[16px] font-semibold text-navy-900">Access granted</p>
            <p className="mt-1.5 text-[13px] text-slate-500">The member now has access to this pathway.</p>
            <button onClick={onClose} className="mt-4 rounded-xl px-4 py-2 text-[13px] font-semibold text-white" style={{ background: '#38A09E' }}>Done</button>
          </div>
        ) : (
          <>
            <h2 className="mb-4 text-[16px] font-semibold text-navy-900">Grant pathway access</h2>
            {fetching ? (
              <p className="text-[13px] text-slate-400">Loading pathways…</p>
            ) : pathways.length === 0 ? (
              <p className="text-[13px] text-slate-500">No paid pathways found. Manual grants are only available for paid pathways.</p>
            ) : (
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
                    className="flex-1 rounded-xl py-2.5 text-[13px] font-semibold text-white disabled:opacity-50" style={{ background: '#38A09E' }}>
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

function PathwayAccessSection({ member, spaceSlug }: { member: MemberProfile; spaceSlug: string }) {
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
        <GrantAccessModal spaceSlug={spaceSlug} userId={member.id} onClose={() => setShowGrant(false)} onGranted={() => { setShowGrant(false); loadItems() }} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Member detail panel
// ---------------------------------------------------------------------------

function MemberDetailPanel({
  member,
  onClose,
  spaceSlug,
}: {
  member: MemberProfile
  onClose: () => void
  spaceSlug: string
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
            {/* TODO: Expose email via a creator-only members endpoint */}
            <p className="mt-0.5 text-[12px] italic text-slate-400">Email not available in this view</p>
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
        </div>

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Joined</p>
          <p className="mt-1 text-[14px] text-navy-900">{formatDate(member.joined_at)}</p>
        </div>

        {member.bio && (
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Bio</p>
            <p className="mt-1 text-[13px] leading-relaxed text-slate-600">{member.bio}</p>
          </div>
        )}

        <div className="border-t border-border pt-1">
          <PathwayAccessSection member={member} spaceSlug={spaceSlug} />
        </div>

        <div className="border-t border-border" />

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Private creator notes</p>
          <p className="mb-2 mt-0.5 text-[11px] text-slate-400">Only you can see these notes.</p>
          {/* TODO: Persist private creator notes when member notes API is available. */}
          <textarea rows={4} disabled
            placeholder="Add a private note about this person..."
            className="w-full cursor-not-allowed resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-400 placeholder-slate-300 outline-none" />
          <p className="mt-1.5 text-[11px] text-slate-400">Note saving coming soon.</p>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invite modal
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
  const [name, setName]       = useState('')
  const [email, setEmail]     = useState('')
  const [role, setRole]       = useState('learner')
  const [note, setNote]       = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [sent, setSent]       = useState(false)

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

  async function handleSubmit() {
    setError(null)
    const trimmedEmail = email.trim().toLowerCase()
    if (!trimmedEmail || !EMAIL_RE.test(trimmedEmail)) {
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
        body: JSON.stringify({ email: trimmedEmail, name: name.trim() || null, role, note: note.trim() || null }),
      })
      if (!res.ok) {
        let detail: string | null = null
        try {
          const body = await res.json()
          if (typeof body.detail === 'string') detail = body.detail
          else if (Array.isArray(body.detail) && body.detail.length > 0) {
            const first = body.detail[0]
            detail = typeof first?.msg === 'string' ? first.msg : null
          }
        } catch { /* not JSON */ }
        if (res.status === 409) setError(detail ?? 'This person already belongs to or has been invited to this collective.')
        else if (res.status === 422 || res.status === 400) setError(detail ?? 'Enter a valid email address.')
        else setError(detail ?? 'Invite could not be created. Please try again.')
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
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full" style={{ background: 'rgba(56,160,158,0.10)' }}>
              <svg width="20" height="16" viewBox="0 0 20 16" fill="none" aria-hidden="true">
                <path d="M2 8l5 5L18 2" stroke="#38A09E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-[16px] font-semibold text-navy-900">Invite created</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
              <span className="font-medium text-navy-900">{email.trim().toLowerCase()}</span> has been added to your pending invites.
            </p>
            {/* TODO: Send invitation email when email service is connected. */}
            <p className="mt-2 text-[11px] text-slate-400">No email has been sent yet — email sending coming soon.</p>
            <button onClick={onClose} className="mt-5 rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}>
              Done
            </button>
          </div>
        ) : (
          <>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-[17px] font-semibold text-navy-900">Invite person</h2>
              <button onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                aria-label="Close">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Name <span className="font-normal text-slate-400">(optional)</span></label>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="Jane Smith"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Email address <span className="font-normal text-slate-400">(required)</span></label>
                <input type="email" value={email} onChange={(e) => { setEmail(e.target.value); setError(null) }}
                  placeholder="jane@example.com"
                  className={`w-full rounded-lg border px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 ${error ? 'border-red-300' : 'border-slate-200'}`} />
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
                <label className="mb-1 block text-[12px] font-semibold text-slate-600">Personal note <span className="font-normal text-slate-400">(optional)</span></label>
                <textarea value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="A short note about why you're inviting them…"
                  rows={2}
                  className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400" />
              </div>
            </div>
            {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}
            <div className="mt-6 flex items-center justify-between gap-3">
              {/* TODO: Send invitation email when email service is connected. */}
              <p className="text-[11px] text-slate-400">No email is sent yet.</p>
              <button disabled={!email.trim() || loading} onClick={handleSubmit}
                className="shrink-0 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}>
                {loading ? 'Sending…' : 'Send invite'}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Pending invites section
// ---------------------------------------------------------------------------

function PendingInviteRow({
  invite,
  spaceSlug,
  onCancelled,
}: {
  invite: SpaceInvitation
  spaceSlug: string
  onCancelled: () => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCancel() {
    if (!confirm(`Cancel invitation to ${invite.email}?`)) return
    setCancelling(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/invitations/${invite.id}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (res.ok || res.status === 204) {
        onCancelled()
      } else {
        setError('Could not cancel invitation.')
      }
    } catch {
      setError('Something went wrong.')
    } finally {
      setCancelling(false)
    }
  }

  const displayName = invite.name || invite.email

  return (
    <li className="flex items-center gap-3 border-b border-border px-5 py-4 last:border-0">
      <Avatar name={displayName} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium text-navy-900">{displayName}</p>
        {invite.name && (
          <p className="mt-0.5 truncate text-[12px] text-slate-500">{invite.email}</p>
        )}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <RoleBadge role={invite.role} />
        <span className="hidden text-[12px] text-slate-400 sm:inline">{formatDate(invite.created_at)}</span>
      </div>
      <button
        onClick={handleCancel}
        disabled={cancelling}
        className="shrink-0 rounded-lg border border-slate-200 px-3 py-1 text-[12px] font-medium text-slate-500 transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
      >
        {cancelling ? 'Cancelling…' : 'Cancel'}
      </button>
      {error && <p className="text-[11px] text-red-500">{error}</p>}
    </li>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface Props {
  members:      MemberProfile[]
  invitations:  SpaceInvitation[]
  spaceName:    string
  spaceSlug:    string
  spaceIsPublic: boolean
}

export default function PeopleClient({ members, invitations, spaceName, spaceSlug, spaceIsPublic }: Props) {
  const router = useRouter()
  const [inviteOpen, setInviteOpen]       = useState(false)
  const [selectedMember, setSelectedMember] = useState<MemberProfile | null>(null)
  const [search, setSearch]               = useState('')

  const existingInviteEmails = useMemo(
    () => new Set(invitations.map((i) => i.email.toLowerCase())),
    [invitations],
  )

  const filteredMembers = useMemo(() => {
    if (!search.trim()) return members
    const q = search.trim().toLowerCase()
    return members.filter((m) =>
      m.display_name.toLowerCase().includes(q)
    )
  }, [members, search])

  function handleInviteSuccess() {
    router.refresh()
  }

  function handleInviteCancelled() {
    router.refresh()
    if (selectedMember) setSelectedMember(null)
  }

  // Derived stats
  const now = new Date()
  const newThisMonth = members.filter((m) => {
    const d = new Date(m.joined_at)
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()
  }).length

  return (
    <div className="w-full max-w-[1100px] space-y-8 px-8 py-8 md:px-10 md:py-10">

      {/* ── Header ── */}
      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
          {spaceName}
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">People</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Invite people, manage access, and see who belongs to this collective.
        </p>
      </div>

      {/* ── Stats ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {[
          { label: 'Active members', value: members.length },
          { label: 'Pending invites', value: invitations.length },
          { label: 'New this month', value: newThisMonth },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-white p-4">
            <p className="font-serif text-2xl text-navy-900">{value}</p>
            <p className="mt-0.5 text-[13px] text-slate-500">{label}</p>
          </div>
        ))}
      </div>

      {/* ── Section 1: Invite people ── */}
      <section>
        <SectionHeading title="Invite people" />
        <div className="space-y-4">
          <InviteLinkCard spaceSlug={spaceSlug} isPublic={spaceIsPublic} />
          <div className="flex items-center gap-4">
            <button
              onClick={() => setInviteOpen(true)}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              Invite by email
            </button>
            <p className="text-[13px] text-slate-400">
              Send a direct invite to someone with a specific role.
            </p>
          </div>
        </div>
      </section>

      {/* ── Section 2: Pending invites ── */}
      <section>
        <SectionHeading title="Pending invites" count={invitations.length} />
        <div className="rounded-2xl border border-border bg-white">
          {invitations.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <p className="text-[14px] font-medium text-slate-500">No pending invites.</p>
              <p className="mt-1 text-[13px] text-slate-400">
                Invites you send will appear here until the person joins.
              </p>
            </div>
          ) : (
            <ul>
              {invitations.map((invite) => (
                <PendingInviteRow
                  key={invite.id}
                  invite={invite}
                  spaceSlug={spaceSlug}
                  onCancelled={handleInviteCancelled}
                />
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* ── Section 3: Current people ── */}
      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <SectionHeading title="Current people" count={members.length} />
          <input
            type="text"
            placeholder="Search by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
          />
        </div>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start">

          {/* Member list card */}
          <div className="min-w-0 flex-1 rounded-2xl border border-border bg-white">
            {filteredMembers.length === 0 ? (
              <div className="px-6 py-10 text-center">
                {members.length === 0 ? (
                  <>
                    <p className="mb-1 text-[15px] font-semibold text-navy-900">No members yet.</p>
                    <p className="text-[13px] text-slate-400">Invite your first person to get started.</p>
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
                            {/* TODO: Show email once creator endpoint exposes it */}
                            <p className="mt-0.5 truncate text-[12px] italic text-slate-400">Email not available</p>
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
            <div className="w-full xl:w-[340px] xl:shrink-0">
              <MemberDetailPanel
                member={selectedMember}
                onClose={() => setSelectedMember(null)}
                spaceSlug={spaceSlug}
              />
            </div>
          )}
        </div>
      </section>

      {/* ── Footer note ── */}
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
