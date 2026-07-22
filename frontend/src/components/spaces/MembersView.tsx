'use client'

import { useState } from 'react'
import MemberCard from '@/components/spaces/MemberCard'
import { apiUrl } from '@/lib/api'
import type { MemberProfile } from '@/types/platform'

// ---------------------------------------------------------------------------
// Invite modal
// ---------------------------------------------------------------------------

interface InviteModalProps {
  spaceSlug: string
  onClose: () => void
}

function InviteModal({ spaceSlug, onClose }: InviteModalProps) {
  const [email, setEmail]   = useState('')
  const [name, setName]     = useState('')
  const [note, setNote]     = useState('')
  const [sending, setSending] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError]   = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) { setError('Email is required.'); return }
    setSending(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/invitations`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: email.trim(), name: name.trim() || null, note: note.trim() || null }),
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Failed (${res.status})`)
      }
      setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(7,24,36,0.55)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-[15px] font-semibold text-navy-900">Invite member</h2>
          <button onClick={onClose} className="text-black transition-colors hover:text-navy-900" aria-label="Close">✕</button>
        </div>

        {success ? (
          <div className="px-6 py-8 text-center">
            <p className="mb-1 text-[15px] font-semibold text-navy-900">Invitation sent</p>
            <p className="text-[13px] text-black">They will receive an invitation to join this collective.</p>
            <button
              onClick={onClose}
              className="mt-5 inline-flex rounded-xl px-6 py-2 text-[13px] font-semibold text-white"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
            <div>
              <label htmlFor="inv-email" className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                Email address <span style={{ color: '#38A09E' }} aria-hidden="true">*</span>
              </label>
              <input
                id="inv-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                required
                className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>
            <div>
              <label htmlFor="inv-name" className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                Name <span className="font-normal text-black">(optional)</span>
              </label>
              <input
                id="inv-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Their first name"
                className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>
            <div>
              <label htmlFor="inv-note" className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                Personal note <span className="font-normal text-black">(optional)</span>
              </label>
              <textarea
                id="inv-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                placeholder="Add a personal message to the invitation."
                className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {error && (
              <p className="rounded-xl px-4 py-2.5 text-[13px]"
                style={{ background: 'rgba(239,68,68,0.06)', color: '#dc2626', border: '1px solid rgba(239,68,68,0.18)' }}>
                {error}
              </p>
            )}

            <div className="flex items-center gap-3 pt-1">
              <button
                type="submit"
                disabled={sending}
                className="inline-flex items-center rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-all hover:opacity-90 disabled:opacity-60"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {sending ? 'Sending…' : 'Send invitation'}
              </button>
              <button type="button" onClick={onClose} className="text-[13px] text-black transition-colors hover:text-navy-900">
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  leaders: MemberProfile[]
  learners: MemberProfile[]
  spaceSlug: string
  canInvite: boolean
  showMemberDirectory?: boolean
  learnerCount?: number
}

export default function MembersView({ leaders, learners, spaceSlug, canInvite, showMemberDirectory = true, learnerCount }: Props) {
  const [query, setQuery]       = useState('')
  const [inviteOpen, setInviteOpen] = useState(false)

  const q = query.toLowerCase().trim()
  const filteredLeaders  = q ? leaders.filter(m => m.display_name.toLowerCase().includes(q))  : leaders
  const filteredLearners = q ? learners.filter(m => m.display_name.toLowerCase().includes(q)) : learners

  const noResults = q && filteredLeaders.length === 0 && filteredLearners.length === 0

  return (
    <>
      {inviteOpen && <InviteModal spaceSlug={spaceSlug} onClose={() => setInviteOpen(false)} />}

      {/* ── Toolbar: search + invite ── */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search members…"
          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2 text-[14px] text-navy-900 placeholder:text-slate-400 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        />
        {canInvite && (
          <button
            onClick={() => setInviteOpen(true)}
            className="shrink-0 rounded-xl border border-teal-200 bg-white px-4 py-2 text-[13px] font-medium text-teal-700 transition-colors hover:bg-teal-50"
          >
            + Invite member
          </button>
        )}
      </div>

      {noResults && (
        <div className="rounded-2xl border border-border bg-white px-6 py-8 text-center">
          <p className="text-sm text-black">No members match &ldquo;{query}&rdquo;.</p>
        </div>
      )}

      {!noResults && (
        <>
          {filteredLeaders.length > 0 && (
            <section className="mb-8">
              <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
                Creators &amp; moderators
              </h2>
              <div className="flex flex-col gap-3">
                {filteredLeaders.map((m) => (
                  <MemberCard key={m.id} member={m} spaceSlug={spaceSlug} />
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
              {!q && learners.length > 0
                ? `${learners.length} ${learners.length === 1 ? 'Member' : 'Members'}`
                : !showMemberDirectory && learnerCount !== undefined
                  ? `${learnerCount} ${learnerCount === 1 ? 'Member' : 'Members'}`
                  : 'Members'}
            </h2>
            {!showMemberDirectory && !canInvite ? (
              <div className="rounded-2xl border border-teal-100 bg-white px-6 py-8 text-center">
                <p className="text-sm text-black">
                  {learnerCount !== undefined && learnerCount > 0
                    ? `${learnerCount} ${learnerCount === 1 ? 'person is' : 'people are'} in this collective.`
                    : 'Member details are visible to collective leaders only.'}
                </p>
              </div>
            ) : filteredLearners.length > 0 ? (
              <div className="flex flex-col gap-3">
                {filteredLearners.map((m) => (
                  <MemberCard key={m.id} member={m} spaceSlug={spaceSlug} />
                ))}
              </div>
            ) : !q ? (
              <div className="rounded-2xl border border-teal-100 bg-white px-6 py-8 text-center">
                <p className="text-sm text-black">No members yet — be the first to join.</p>
              </div>
            ) : null}
          </section>
        </>
      )}
    </>
  )
}
