'use client'

import { useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'
import StepShell from '../StepShell'
import IslandDetailModal from '../IslandDetailModal'
import type { LocationOption } from '@/lib/build-your-collective/types'

interface Props {
  locations: LocationOption[]
  value: string | null
  onChange: (id: string) => void
  onContinue: () => void
  onBack: () => void
  onSkip?: () => void
}

/**
 * The island picker (internally an Atlas Location). Every Collective
 * chooses one island — the visual and emotional representation of
 * its feeling and atmosphere. Cards are large, artwork-first, and
 * read as visual invitations, not admin rows.
 *
 * The backend already filters by plan: Community sees only COMMUNITY,
 * Creator/Pro see only ATLAS, Platform Owner sees all three types.
 * When more than one type comes back, we render each as its own
 * labelled group so it's visually clear which options are which.
 *
 * Cards open an ``IslandDetailModal`` for a full artwork + Atlas Entry
 * preview. Selection only happens from inside the modal — never on
 * card click — so a creator can explore islands without committing.
 */
export default function LocationStep({
  locations, value, onChange, onContinue, onBack, onSkip,
}: Props) {
  const cornerstones = locations.filter((l) => l.location_type === 'CORNERSTONE')
  const atlas = locations.filter((l) => l.location_type === 'ATLAS')
  const community = locations.filter((l) => l.location_type === 'COMMUNITY')
  const typeCount = [cornerstones, atlas, community].filter((g) => g.length > 0).length
  const grouped = typeCount > 1

  const [openId, setOpenId] = useState<string | null>(null)
  const openLocation = openId ? locations.find((l) => l.id === openId) ?? null : null

  const handleChoose = (id: string) => {
    onChange(id)
    setOpenId(null)
  }

  return (
    <StepShell
      stepIndex={2}
      heading="Choose your island"
      whisper="Your island is the visual home of your collective — the atmosphere and feeling made into a place. The artwork, mood and setting all belong to it. Choose the island that fits the feeling you just described; your members will return to it every time they visit."
      onBack={onBack}
      onContinue={onContinue}
      canContinue={!!value}
      onSkip={onSkip}
    >
      {grouped ? (
        <div className="space-y-16">
          {cornerstones.length > 0 && (
            <LocationGroup
              title="Cornerstones"
              hint="Reserved for Fresh Collective's own collectives."
              locations={cornerstones}
              value={value}
              onOpen={setOpenId}
            />
          )}
          {atlas.length > 0 && (
            <LocationGroup
              title="Islands"
              locations={atlas}
              value={value}
              onOpen={setOpenId}
            />
          )}
          {community.length > 0 && (
            <LocationGroup
              title="Community Islands"
              hint="Simple islands where new communities begin."
              locations={community}
              value={value}
              onOpen={setOpenId}
            />
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {locations.map((loc) => (
            <LocationCard
              key={loc.id}
              loc={loc}
              selected={value === loc.id}
              onOpen={setOpenId}
            />
          ))}
        </div>
      )}

      <IslandDetailModal
        open={openLocation !== null}
        location={openLocation}
        isCurrent={openLocation !== null && openLocation.id === value}
        onChoose={handleChoose}
        onClose={() => setOpenId(null)}
      />
    </StepShell>
  )
}

function LocationGroup({
  title, hint, locations, value, onOpen,
}: {
  title: string
  hint?: string
  locations: LocationOption[]
  value: string | null
  onOpen: (id: string) => void
}) {
  return (
    <section>
      <div className="mb-4">
        <h3
          className="text-[11px] font-semibold uppercase tracking-[0.28em]"
          style={{ color: '#38A09E' }}
        >
          {title}
        </h3>
        {hint && (
          <p
            className="mt-1 text-[12.5px] italic"
            style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
          >
            {hint}
          </p>
        )}
      </div>
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {locations.map((loc) => (
          <LocationCard
            key={loc.id}
            loc={loc}
            selected={value === loc.id}
            onOpen={onOpen}
          />
        ))}
      </div>
    </section>
  )
}

function LocationCard({
  loc, selected, onOpen,
}: {
  loc: LocationOption
  selected: boolean
  onOpen: (id: string) => void
}) {
  const artworkUrl = resolveMediaUrl(
    loc.thumbnail_artwork_url ?? loc.hero_artwork_url ?? undefined,
  )
  return (
    <button
      type="button"
      onClick={() => onOpen(loc.id)}
      aria-haspopup="dialog"
      aria-label={
        selected
          ? `Explore ${loc.name} (your current island)`
          : `Explore ${loc.name}`
      }
      className="group relative flex flex-col overflow-hidden rounded-2xl text-left transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fc-accent-500)]/50 focus-visible:ring-offset-2"
      style={{
        background: '#FFFFFF',
        border: selected
          ? '1px solid rgba(56, 160, 158, 0.55)'
          : '1px solid rgba(12, 24, 38, 0.08)',
        boxShadow: selected
          ? '0 12px 32px rgba(56, 160, 158, 0.14), 0 2px 6px rgba(12, 24, 38, 0.04)'
          : '0 1px 3px rgba(12, 24, 38, 0.04)',
        transform: selected ? 'translateY(-2px)' : 'none',
      }}
    >
      <div
        className="relative w-full overflow-hidden"
        // 5:4 matches the dominant Location.hero_artwork_url source
        // aspect, standardising the treatment across admin viewer,
        // modal and this picker. Combined with ``object-contain`` the
        // whole artwork is always shown.
        style={{ aspectRatio: '5 / 4', background: '#F4F7F6' }}
      >
        {artworkUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={artworkUrl}
            alt={loc.name}
            className="h-full w-full transition-transform duration-500 group-hover:scale-[1.02]"
            // ``contain`` matches the Atlas admin viewer so square /
            // portrait source artwork is shown in full rather than
            // cropped to the card's 3:2 frame. The neutral background
            // handles any letterboxing.
            style={{ objectFit: 'contain', objectPosition: 'center', display: 'block' }}
          />
        ) : (
          <ArtworkPlaceholder label={loc.name} />
        )}
        {selected && (
          <span
            className="absolute left-3 top-3 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
            style={{
              background: 'rgba(255,255,255,0.94)',
              color: '#246B6A',
              border: '1px solid rgba(56, 160, 158, 0.35)',
            }}
          >
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path d="M2.5 6.2l2.4 2.4L9.7 3.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Current
          </span>
        )}
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 transition-all duration-500"
          style={{
            height: 3,
            background: selected
              ? 'linear-gradient(90deg, #38A09E 0%, #55B8B6 100%)'
              : 'transparent',
          }}
        />
      </div>

      <div className="flex flex-1 flex-col px-5 py-4">
        <p className="font-serif text-[17px] leading-tight" style={{ color: '#0C1826' }}>
          {loc.name}
        </p>
        {loc.description && (
          <p
            className="mt-1.5 line-clamp-2 text-[12.5px] leading-relaxed italic"
            style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
          >
            {loc.description}
          </p>
        )}
        <p
          className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-semibold uppercase tracking-[0.14em] transition-colors"
          style={{ color: '#38A09E' }}
        >
          Explore this island
          <span
            aria-hidden="true"
            className="transition-transform group-hover:translate-x-0.5"
          >
            →
          </span>
        </p>
      </div>
    </button>
  )
}

function ArtworkPlaceholder({ label }: { label: string }) {
  return (
    <svg viewBox="0 0 400 260" preserveAspectRatio="xMidYMid slice" className="h-full w-full" aria-hidden="true">
      <defs>
        <radialGradient id={`loc-ph-${label}`} cx="0.5" cy="0.5" r="0.65">
          <stop offset="0%" stopColor="#E5F0EF" />
          <stop offset="60%" stopColor="#F4F7F6" />
          <stop offset="100%" stopColor="#FBFDFC" />
        </radialGradient>
      </defs>
      <rect width="400" height="260" fill={`url(#loc-ph-${label})`} />
      <g fill="none" stroke="rgba(56, 160, 158, 0.18)" strokeWidth="0.9">
        <ellipse cx="200" cy="140" rx="120" ry="60" />
        <ellipse cx="200" cy="140" rx="80" ry="40" />
      </g>
      <text x="200" y="220" textAnchor="middle" fill="rgba(12,24,38,0.45)" fontFamily="Georgia, serif" fontStyle="italic" fontSize="14">
        {label}
      </text>
    </svg>
  )
}
