'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'
import Container from '@/components/layout/Container'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import type { SpaceWithMeta } from './spaceMeta'

export type { SpaceWithMeta }

// TODO: Add optional "Featured collective" or "Collective of the week" section later.

// ---------------------------------------------------------------------------
// Collective card
// ---------------------------------------------------------------------------

function CollectiveCard({
  space,
  isJoined,
}: {
  space: SpaceWithMeta
  isJoined: boolean
  isLoggedIn: boolean
}) {
  const cs = getCollectiveCoverStyle(space.slug)
  const resolvedImageUrl = resolveMediaUrl(space.cover_image_url)
  const hasImage = Boolean(resolvedImageUrl)
  const href = space.isReal ? `/spaces/${space.slug}` : '/signup'

  const titleColor = hasImage ? '#FFFFFF' : (cs.isDark ? '#FFFFFF' : '#152236')
  const taglineColor = hasImage
    ? 'rgba(255,255,255,0.72)'
    : cs.isDark
      ? 'rgba(255,255,255,0.65)'
      : '#64748B'

  const ctaLabel = isJoined ? 'Continue →' : 'Explore →'
  const primaryTheme = space.themes[0] ?? null

  return (
    <div
      className="group flex h-full w-full min-w-0 flex-col overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-1 hover:shadow-lg"
      style={{
        border: '1px solid rgba(0,0,0,0.07)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
      }}
    >
      {/* Cover area — fixed aspect ratio keeps all covers the same height */}
      <div className="relative w-full shrink-0 overflow-hidden" style={{ paddingBottom: '56.25%' }}>

        {/* CSS art layer */}
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
              src={resolvedImageUrl!}
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

        {/* Status badges — top-left */}
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
          <p className="font-serif text-[17px] leading-snug" style={{ color: titleColor }}>
            {space.name}
          </p>
          {space.tagline && (
            <p
              className="mt-0.5 line-clamp-1 text-[12px] leading-snug"
              style={{ color: taglineColor }}
            >
              {space.tagline}
            </p>
          )}
        </div>
      </div>

      {/* Card body — description preview; flex-1 pins footer to bottom regardless of content */}
      <div className="flex-1">
        {space.description && (
          <div className="px-4 pt-3">
            <p className="line-clamp-2 text-[12.5px] leading-[1.65] text-slate-500">
              {space.description}
            </p>
          </div>
        )}
      </div>

      {/* Footer row */}
      <div
        className="mt-auto flex items-center justify-between gap-3 border-t px-4 py-3"
        style={{ borderColor: 'rgba(0,0,0,0.06)' }}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-slate-400">
          {primaryTheme && (
            <span
              className="rounded px-1.5 py-0.5 text-[10px] font-medium"
              style={{ background: `${space.accentColor}18`, color: space.accentColor }}
            >
              {primaryTheme}
            </span>
          )}
          {space.creator_name && (
            <span className="hidden sm:inline">
              by <span className="font-medium text-slate-600">{space.creator_name}</span>
            </span>
          )}
          {space.pathway_count > 0 && (
            <span>{space.pathway_count} {space.pathway_count === 1 ? 'pathway' : 'pathways'}</span>
          )}
          {space.member_count > 0 && (
            <span className="hidden sm:inline">
              · {space.member_count} {space.member_count === 1 ? 'member' : 'members'}
            </span>
          )}
        </div>
        <Link
          href={href}
          className="shrink-0 text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
        >
          {ctaLabel}
        </Link>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-16 text-center">
      <p className="mb-2 text-[16px] font-semibold text-navy-900">No collectives found.</p>
      <p className="text-[14px] leading-relaxed text-slate-500">
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
      {/* ── Hero ── */}
      <div className="py-8 sm:py-10" style={{ background: '#FDFCF9' }}>
        <Container>
          <div
            className="overflow-hidden rounded-2xl px-8 py-10 sm:px-10 sm:py-12"
            style={{
              background: '#071824',
              border: '1px solid rgba(56,160,158,0.22)',
              boxShadow:
                '0 0 0 1px rgba(56,160,158,0.08), 0 8px 32px rgba(7,24,36,0.18), 0 0 48px rgba(56,160,158,0.06)',
            }}
          >
            {/* Teal accent line */}
            <div
              className="mb-5 h-[2px] w-8 rounded-full"
              style={{ background: 'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.2) 100%)' }}
            />

            <h1 className="mb-3 font-serif" style={{ fontSize: 'clamp(2rem, 4vw, 3rem)', lineHeight: '1.1', letterSpacing: '-0.03em' }}>
              <span
                style={{
                  display: 'inline-block',
                  background: 'linear-gradient(90deg, #38A09E 0%, #FFFFFF 55%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                }}
              >
                Explore collectives
              </span>
            </h1>

            <p
              className="max-w-[540px] text-[15px] leading-[1.78]"
              style={{ color: 'rgba(255,255,255,0.62)' }}
            >
              Each collective is a creator-led learning environment — with pathways, gatherings,
              and community in one intentional place. Find the one that fits where you are.
            </p>
          </div>
        </Container>
      </div>

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
                      : { color: '#6B7A8D' }
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
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
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
            <p className="mt-10 text-center text-[12px] text-slate-400">
              Some collectives are free and some require payment. Payment integration is coming soon.
            </p>
          )}

        </Container>
      </div>
    </>
  )
}
