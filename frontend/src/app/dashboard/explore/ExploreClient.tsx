'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import type { PublicSpaceCard } from '@/types/platform'

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function CollectiveCard({
  space,
  isJoined,
}: {
  space: PublicSpaceCard
  isJoined: boolean
}) {
  const href = `/spaces/${space.slug}`

  return (
    <div
      className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"
    >
      {/* Teal accent bar */}
      <div
        className="h-[3px] w-full"
        style={{ background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 100%)' }}
      />

      <div className="flex flex-1 flex-col p-5">

        {/* Badges */}
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {isJoined && (
            <span
              className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
            >
              Already joined
            </span>
          )}
          {space.has_upcoming_event && (
            <span className="flex items-center gap-1 text-[10px] font-medium text-teal-600">
              <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              Live event soon
            </span>
          )}
        </div>

        {/* Name + tagline */}
        <h3
          className="mb-1.5 font-semibold leading-snug text-navy-900 transition-colors group-hover:text-teal-700"
          style={{ fontSize: '1.0625rem', letterSpacing: '-0.02em' }}
        >
          {space.name}
        </h3>
        {space.tagline && (
          <p className="mb-4 flex-1 text-[13px] leading-relaxed text-slate-500">
            {space.tagline}
          </p>
        )}

        {/* Meta */}
        <div className="mt-auto border-t border-border pt-4">
          <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-slate-400">
            {space.creator_name && (
              <span>
                by <span className="font-medium text-slate-600">{space.creator_name}</span>
              </span>
            )}
            {space.pathway_count > 0 && (
              <span>
                {space.pathway_count} {space.pathway_count === 1 ? 'pathway' : 'pathways'}
              </span>
            )}
            {space.member_count > 0 && (
              <span>
                {space.member_count} {space.member_count === 1 ? 'member' : 'members'}
              </span>
            )}
          </div>

          <Link
            href={href}
            className="inline-flex items-center gap-1 text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
          >
            {isJoined ? 'Continue' : 'View collective'}
            <span className="transition-transform group-hover:translate-x-0.5">→</span>
          </Link>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({ isCreatorOrAdmin }: { isCreatorOrAdmin?: boolean }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-16 text-center">
      <p className="mb-2 text-[16px] font-semibold text-navy-900">
        No collectives are open yet.
      </p>
      <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
        New collectives will appear here as creators publish them.
      </p>
      {isCreatorOrAdmin && (
        <Link
          href="/creator-studio/create"
          className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Create a collective
        </Link>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  spaces:      PublicSpaceCard[]
  joinedSlugs: string[]
  isCreatorOrAdmin?: boolean
}

export default function ExploreClient({ spaces, joinedSlugs, isCreatorOrAdmin }: Props) {
  const [search, setSearch] = useState('')

  const joinedSet = useMemo(() => new Set(joinedSlugs), [joinedSlugs])

  const filtered = useMemo(() => {
    if (!search.trim()) return spaces
    const q = search.trim().toLowerCase()
    return spaces.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.tagline ?? '').toLowerCase().includes(q) ||
        (s.creator_name ?? '').toLowerCase().includes(q),
    )
  }, [spaces, search])

  // Joined spaces first, then by name
  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const aJoined = joinedSet.has(a.slug) ? 0 : 1
      const bJoined = joinedSet.has(b.slug) ? 0 : 1
      if (aJoined !== bJoined) return aJoined - bJoined
      return a.name.localeCompare(b.name)
    })
  }, [filtered, joinedSet])

  if (spaces.length === 0) {
    return <EmptyState isCreatorOrAdmin={isCreatorOrAdmin} />
  }

  return (
    <div>
      {/* Search */}
      <div className="mb-8">
        <input
          type="text"
          placeholder="Search by name, topic, or creator…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-md rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 shadow-sm outline-none transition-colors focus:border-teal-400 focus:ring-0"
        />
      </div>

      {/* Already joined section */}
      {joinedSet.size > 0 && !search.trim() && (
        <div className="mb-8">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            Your collectives
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {sorted
              .filter((s) => joinedSet.has(s.slug))
              .map((space) => (
                <CollectiveCard key={space.id} space={space} isJoined />
              ))}
          </div>
        </div>
      )}

      {/* All collectives / search results */}
      {(search.trim() || joinedSet.size === 0 || sorted.some((s) => !joinedSet.has(s.slug))) && (
        <div>
          {joinedSet.size > 0 && !search.trim() && (
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              More collectives
            </p>
          )}

          {sorted.filter((s) => search.trim() || !joinedSet.has(s.slug)).length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-[14px] text-slate-400">No collectives match your search.</p>
              <button
                onClick={() => setSearch('')}
                className="mt-3 text-[13px] text-teal-600 hover:underline"
              >
                Clear search
              </button>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {sorted
                .filter((s) => search.trim() || !joinedSet.has(s.slug))
                .map((space) => (
                  <CollectiveCard
                    key={space.id}
                    space={space}
                    isJoined={joinedSet.has(space.slug)}
                  />
                ))}
            </div>
          )}
        </div>
      )}

      {/* TODO: Connect join flow once member enrollment API is available. */}
      <p className="mt-10 text-center text-[12px] text-slate-400">
        To join a collective, visit its page. Paid collectives require payment — payment
        integration coming soon.
      </p>
    </div>
  )
}
