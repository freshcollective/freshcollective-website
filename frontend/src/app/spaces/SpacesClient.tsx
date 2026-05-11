'use client'

import { useState } from 'react'
import Link from 'next/link'

export interface DisplaySpace {
  id: string
  slug: string
  name: string
  tagline: string | null
  description: string | null
  pathway_count: number
  member_count: number
  creator_name: string | null
  has_upcoming_event: boolean
  category: string
  accentColor: string
  isReal: boolean
  isFlagship: boolean
}

const CATEGORIES = ['All', 'Inner Work', 'Wellbeing', 'Creativity', 'Leadership', 'Reflection']

const CARD_SHADOW = '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)'

function FlagshipCard({ space }: { space: DisplaySpace }) {
  const href = space.isReal ? `/spaces/${space.slug}` : '/signup'

  return (
    <div
      className="group relative overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5 hover:shadow-xl"
      style={{
        border: '1px solid rgba(56,160,158,0.20)',
        boxShadow: '0 1px 4px rgba(0,0,0,0.04), 0 12px 32px rgba(56,160,158,0.08)',
      }}
    >
      {/* Accent bar */}
      <div className="h-[3px] w-full" style={{ background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 60%, #C9A83C 100%)' }} />

      <div className="p-7 sm:p-8">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span
                className="rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em]"
                style={{ background: 'rgba(201,168,60,0.10)', color: '#9A7420' }}
              >
                Flagship Space
              </span>
              {space.has_upcoming_event && (
                <span className="flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-teal-600" style={{ background: 'rgba(56,160,158,0.07)' }}>
                  <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
                  Live event soon
                </span>
              )}
            </div>

            <h2
              className="mb-2 text-navy-950"
              style={{ fontSize: 'clamp(1.375rem, 2.5vw, 1.875rem)', letterSpacing: '-0.03em', lineHeight: '1.15', fontWeight: 650 }}
            >
              {space.name}
            </h2>

            {space.tagline && (
              <p className="mb-4 text-[15px] leading-[1.65] text-navy-500">{space.tagline}</p>
            )}

            {space.description && (
              <p className="mb-6 max-w-[520px] text-[14px] leading-[1.75] text-navy-400">{space.description}</p>
            )}

            <div className="mb-6 flex flex-wrap items-center gap-4 text-[12.5px] text-navy-400">
              {space.creator_name && (
                <span>
                  by <span className="font-medium text-navy-600">{space.creator_name}</span>
                </span>
              )}
              {space.pathway_count > 0 && (
                <span>{space.pathway_count} pathway{space.pathway_count !== 1 ? 's' : ''}</span>
              )}
              {space.member_count > 0 && (
                <span>{space.member_count} member{space.member_count !== 1 ? 's' : ''}</span>
              )}
            </div>
          </div>

          <div
            className="hidden h-16 w-16 flex-shrink-0 items-center justify-center rounded-2xl sm:flex"
            style={{ background: 'linear-gradient(135deg, rgba(56,160,158,0.10) 0%, rgba(85,184,182,0.06) 100%)', border: '1px solid rgba(56,160,158,0.14)' }}
          >
            <div className="h-7 w-7 rounded-lg" style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }} />
          </div>
        </div>

        <Link
          href={href}
          className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            boxShadow: 'var(--fc-shadow-btn)',
          }}
        >
          Explore Space
          <span className="text-teal-100">→</span>
        </Link>
      </div>
    </div>
  )
}

function SpaceCard({ space }: { space: DisplaySpace }) {
  const href = space.isReal ? `/spaces/${space.slug}` : '/signup'

  return (
    <div
      className="group flex flex-col overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5"
      style={{
        border: '1px solid rgba(0,0,0,0.07)',
        boxShadow: CARD_SHADOW,
      }}
    >
      {/* Accent bar */}
      <div className="h-[3px] w-full" style={{ background: space.accentColor }} />

      <div className="flex flex-1 flex-col p-5">
        <div className="mb-3 flex items-center justify-between gap-2">
          <span
            className="rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]"
            style={{
              background: `${space.accentColor}15`,
              color: space.accentColor,
            }}
          >
            {space.category}
          </span>
          {space.has_upcoming_event && (
            <span className="flex items-center gap-1 text-[10px] font-medium text-teal-600">
              <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
              Live soon
            </span>
          )}
        </div>

        <h3
          className="mb-2 font-semibold leading-snug text-navy-950"
          style={{ fontSize: '1.0625rem', letterSpacing: '-0.02em' }}
        >
          {space.name}
        </h3>

        {space.tagline && (
          <p className="mb-4 flex-1 text-[13.5px] leading-[1.65] text-navy-400">
            {space.tagline}
          </p>
        )}

        <div
          className="mt-auto border-t pt-4"
          style={{ borderColor: 'rgba(0,0,0,0.06)' }}
        >
          <div className="mb-3.5 flex flex-wrap items-center gap-3 text-[12px] text-navy-400">
            {space.creator_name && (
              <span>
                by <span className="font-medium text-navy-600">{space.creator_name}</span>
              </span>
            )}
            <span className="text-navy-200">·</span>
            {space.pathway_count > 0 && (
              <span>{space.pathway_count} pathway{space.pathway_count !== 1 ? 's' : ''}</span>
            )}
            {space.member_count > 0 && (
              <>
                <span className="text-navy-200">·</span>
                <span>{space.member_count} members</span>
              </>
            )}
          </div>

          <Link
            href={href}
            className="inline-flex items-center gap-1 text-[13px] font-semibold text-navy-700 transition-colors group-hover:text-navy-950"
          >
            Explore Space
            <span className="transition-transform group-hover:translate-x-0.5">→</span>
          </Link>
        </div>
      </div>
    </div>
  )
}

export default function SpacesClient({ spaces }: { spaces: DisplaySpace[] }) {
  const [activeCategory, setActiveCategory] = useState('All')

  const flagship = spaces.find((s) => s.isFlagship)
  const rest = spaces.filter((s) => !s.isFlagship)

  const filteredRest = activeCategory === 'All'
    ? rest
    : rest.filter((s) => s.category === activeCategory)

  const showFlagship = activeCategory === 'All' || flagship?.category === activeCategory

  return (
    <div>
      {/* Category filter */}
      <div className="border-b border-[#EEEDE9] bg-white">
        <div className="mx-auto w-full max-w-6xl px-6 md:px-10">
          <div className="flex items-center gap-1 overflow-x-auto py-3">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                className="flex-shrink-0 rounded-lg px-3.5 py-1.5 text-[13px] font-medium transition-all"
                style={
                  activeCategory === cat
                    ? { background: '#0C1826', color: '#ffffff' }
                    : { color: '#6B7A8D' }
                }
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Spaces */}
      <div className="py-12 sm:py-16" style={{ background: '#FDFCF9' }}>
        <div className="mx-auto w-full max-w-6xl px-6 md:px-10">

          {/* Flagship */}
          {showFlagship && flagship && (
            <div className="mb-8">
              <FlagshipCard space={flagship} />
            </div>
          )}

          {/* Grid */}
          {filteredRest.length > 0 ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredRest.map((space) => (
                <SpaceCard key={space.id} space={space} />
              ))}
            </div>
          ) : (
            !showFlagship && (
              <div className="py-16 text-center">
                <p className="text-[15px] text-navy-400">No spaces in this category yet.</p>
              </div>
            )
          )}

        </div>
      </div>
    </div>
  )
}
