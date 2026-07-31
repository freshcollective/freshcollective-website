'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import PageHero from '@/components/layout/PageHero'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import CollectiveCard from './CollectiveCard'
import type { SpaceWithMeta } from './spaceMeta'

export type { SpaceWithMeta }

// TODO: Add optional "Featured collective" or "Collective of the week" section later.

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-16 text-center">
      <p className="mb-2 text-[16px] font-semibold text-navy-900">No collectives found.</p>
      <p className="text-[14px] leading-relaxed text-black">
        Try a different theme or search term.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main experience component
// ---------------------------------------------------------------------------

interface Props {
  spaces: SpaceWithMeta[]
  joinedSlugs?: string[]
  isLoggedIn?: boolean
}

export default function ExploreCollectivesExperience({
  spaces,
  joinedSlugs = [],
  isLoggedIn = false,
}: Props) {
  const [activeTheme, setActiveTheme] = useState('All')
  const [search, setSearch] = useState('')

  const joinedSet = useMemo(() => new Set(joinedSlugs), [joinedSlugs])

  // Only show theme filter chips that at least one collective uses
  const availableThemes = useMemo(() => {
    const used = new Set(spaces.flatMap((s) => s.themes))
    return COLLECTIVE_THEMES.filter((t) => used.has(t))
  }, [spaces])

  const filtered = useMemo(() => {
    let result =
      activeTheme === 'All'
        ? spaces
        : spaces.filter((s) => s.themes.includes(activeTheme))
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.tagline ?? '').toLowerCase().includes(q) ||
          (s.creator_name ?? '').toLowerCase().includes(q),
      )
    }
    return [...result].sort((a, b) => {
      const aJ = joinedSet.has(a.slug) ? 0 : 1
      const bJ = joinedSet.has(b.slug) ? 0 : 1
      return aJ - bJ
    })
  }, [spaces, activeTheme, search, joinedSet])

  return (
    <>
      {/* ── Hero — shared PageHero primitive (see
              components/layout/PageHero.tsx). Discover Places and
              Ways to Connect use the same primitive so all three
              destinations sit in one visual family. ── */}
      <PageHero
        title="Explore collectives"
        supportingCopy={
          <>
            Each collective is a creator-led learning environment —
            with pathways, gatherings, and community in one
            intentional place. Find the one that fits where you are.
          </>
        }
      />

      {/* ── Theme filter + search ── */}
      <div
        className="sticky top-0 z-10 border-b bg-white"
        style={{ borderColor: '#EEEDE9' }}
      >
        <Container>
          <div className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
            {/* Theme chips — All + only themes used by real collectives */}
            <div className="flex items-center gap-1 overflow-x-auto">
              {['All', ...availableThemes].map((theme) => (
                <button
                  key={theme}
                  onClick={() => setActiveTheme(theme)}
                  className="flex-shrink-0 rounded-lg px-3.5 py-1.5 text-[13px] font-medium transition-all"
                  style={
                    activeTheme === theme
                      ? { background: '#0C1826', color: '#ffffff' }
                      : { color: '#000000' }
                  }
                >
                  {theme}
                </button>
              ))}
            </div>

            {/* Search */}
            <input
              type="text"
              placeholder="Search collectives…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-1.5 text-[13px] text-navy-900 placeholder-slate-400 shadow-sm outline-none transition-colors focus:border-teal-400 sm:w-52"
            />
          </div>
        </Container>
      </div>

      {/* ── Cards ── */}
      <div className="flex-1 py-10 sm:py-14" style={{ background: '#FDFCF9' }}>
        <Container>

          {/* Section label when user has joined collectives */}
          {isLoggedIn && !search.trim() && joinedSet.size > 0 && filtered.some((s) => joinedSet.has(s.slug)) && (
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
              Your collectives
            </p>
          )}

          {filtered.length > 0 ? (
            <div className="grid grid-cols-1 items-stretch gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((space) => (
                <CollectiveCard
                  key={space.id}
                  space={space}
                  isJoined={joinedSet.has(space.slug)}
                  isLoggedIn={isLoggedIn}
                />
              ))}
            </div>
          ) : (
            <EmptyState />
          )}

          {/* Note about payment */}
          {isLoggedIn && (
            <p className="mt-10 text-center text-[12px] text-black">
              Some collectives are free and some require payment. Payment integration is coming soon.
            </p>
          )}

        </Container>
      </div>
    </>
  )
}
