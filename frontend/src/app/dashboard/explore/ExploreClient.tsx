'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import type { PublicSpaceCard } from '@/types/platform'

// ---------------------------------------------------------------------------
// Collective card with visual cover
// ---------------------------------------------------------------------------

function CollectiveCard({
  space,
  isJoined,
}: {
  space: PublicSpaceCard
  isJoined: boolean
}) {
  const href = `/spaces/${space.slug}`
  const cs = getCollectiveCoverStyle(space.slug)
  const hasImage = Boolean(space.cover_image_url)

  const titleColor = hasImage ? '#FFFFFF' : (cs.isDark ? '#FFFFFF' : '#152236')
  const taglineColor = hasImage
    ? 'rgba(255,255,255,0.72)'
    : cs.isDark
      ? 'rgba(255,255,255,0.65)'
      : '#64748B'

  return (
    <div className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg hover:border-teal-200/60">

      {/* Cover artwork — ~5:2 aspect */}
      <div className="relative w-full overflow-hidden" style={{ paddingBottom: '42%' }}>

        {/* CSS artwork layer */}
        {!hasImage && (
          <div
            className="absolute inset-0"
            style={{
              background: cs.background,
              backgroundSize: cs.backgroundSize ?? 'auto',
            }}
          />
        )}

        {/* Uploaded image */}
        {hasImage && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={space.cover_image_url!}
              alt={space.name}
              className="absolute inset-0 h-full w-full object-cover"
            />
            <div
              className="absolute inset-0"
              style={{
                background:
                  'linear-gradient(to top, rgba(7,24,36,0.72) 0%, rgba(7,24,36,0.18) 55%, transparent 80%)',
              }}
            />
          </>
        )}

        {/* Badges — top-left */}
        <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
          {isJoined && (
            <span
              className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(56,160,158,0.85)', color: '#FFFFFF' }}
            >
              Joined
            </span>
          )}
          {space.has_upcoming_event && (
            <span
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(7,24,36,0.45)', color: 'rgba(255,255,255,0.90)' }}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              Live soon
            </span>
          )}
        </div>

        {/* Name + tagline over cover */}
        <div className="absolute inset-x-0 bottom-0 p-4">
          <p className="font-serif text-[18px] leading-snug" style={{ color: titleColor }}>
            {space.name}
          </p>
          {space.tagline && (
            <p className="mt-0.5 text-[12px] leading-snug line-clamp-1" style={{ color: taglineColor }}>
              {space.tagline}
            </p>
          )}
        </div>
      </div>

      {/* Footer row */}
      <div className="flex items-center justify-between border-t border-border px-4 py-3">
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-slate-400">
          {space.creator_name && (
            <span>
              by <span className="font-medium text-slate-600">{space.creator_name}</span>
            </span>
          )}
          {space.pathway_count > 0 && (
            <span>{space.pathway_count} {space.pathway_count === 1 ? 'pathway' : 'pathways'}</span>
          )}
          {space.member_count > 0 && (
            <span>{space.member_count} {space.member_count === 1 ? 'member' : 'members'}</span>
          )}
        </div>
        <Link
          href={href}
          className="shrink-0 text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
        >
          {isJoined ? 'Enter →' : 'View →'}
        </Link>
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
  spaces: PublicSpaceCard[]
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
        <div className="mb-10">
          <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            Your collectives
          </p>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
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
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
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
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
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

      <p className="mt-10 text-center text-[12px] text-slate-400">
        To join a collective, visit its page. Paid collectives require payment — payment
        integration coming soon.
      </p>
    </div>
  )
}
