'use client'

import { useState } from 'react'
import MemberCard from '@/components/spaces/MemberCard'
import type { MemberProfile } from '@/types/platform'

interface Props {
  leaders: MemberProfile[]
  learners: MemberProfile[]
}

export default function MembersView({ leaders, learners }: Props) {
  const [query, setQuery] = useState('')

  const q = query.toLowerCase().trim()
  const filteredLeaders = q
    ? leaders.filter(m => m.display_name.toLowerCase().includes(q))
    : leaders
  const filteredLearners = q
    ? learners.filter(m => m.display_name.toLowerCase().includes(q))
    : learners

  const noResults = q && filteredLeaders.length === 0 && filteredLearners.length === 0

  return (
    <div>
      {/* ── Toolbar: search + invite ── */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search members…"
          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2 text-[14px] text-navy-900 placeholder:text-slate-400 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        />
        {/* TODO (invite): wire to invitation flow once member-facing invite is available */}
        <button
          disabled
          title="Invite functionality coming soon"
          className="shrink-0 cursor-not-allowed rounded-xl border border-slate-200 bg-white px-4 py-2 text-[13px] font-medium text-slate-400"
        >
          + Invite member
        </button>
      </div>

      {noResults && (
        <div className="rounded-2xl border border-border bg-white px-6 py-8 text-center">
          <p className="text-sm text-slate-400">No members match &ldquo;{query}&rdquo;.</p>
        </div>
      )}

      {!noResults && (
        <>
          {filteredLeaders.length > 0 && (
            <section className="mb-8">
              <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Creators &amp; moderators
              </h2>
              <div className="flex flex-col gap-3">
                {filteredLeaders.map((m) => (
                  <MemberCard key={m.id} member={m} />
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
              {!q && learners.length > 0
                ? `${learners.length} ${learners.length === 1 ? 'Member' : 'Members'}`
                : 'Members'}
            </h2>
            {filteredLearners.length > 0 ? (
              <div className="flex flex-col gap-3">
                {filteredLearners.map((m) => (
                  <MemberCard key={m.id} member={m} />
                ))}
              </div>
            ) : !q ? (
              <div className="rounded-2xl border border-teal-100 bg-white px-6 py-8 text-center">
                <p className="text-sm text-slate-400">No members yet — be the first to join.</p>
              </div>
            ) : null}
          </section>
        </>
      )}
    </div>
  )
}
