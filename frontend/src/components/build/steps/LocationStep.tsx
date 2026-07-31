'use client'

import { resolveMediaUrl } from '@/lib/api'
import StepShell from '../StepShell'
import type { LocationOption } from '@/lib/build-your-collective/types'

interface Props {
  locations: LocationOption[]
  value: string | null
  onChange: (id: string) => void
  onContinue: () => void
  onBack: () => void
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
 */
export default function LocationStep({
  locations, value, onChange, onContinue, onBack,
}: Props) {
  const cornerstones = locations.filter((l) => l.location_type === 'CORNERSTONE')
  const atlas = locations.filter((l) => l.location_type === 'ATLAS')
  const community = locations.filter((l) => l.location_type === 'COMMUNITY')
  const typeCount = [cornerstones, atlas, community].filter((g) => g.length > 0).length
  const grouped = typeCount > 1

  return (
    <StepShell
      stepIndex={1}
      eyebrow="One"
      heading="Choose your island"
      whisper="Each island represents a different feeling and atmosphere. Choose the one that best reflects the experience you want to create for your members."
      onBack={onBack}
      onContinue={onContinue}
      canContinue={!!value}
    >
      {grouped ? (
        <div className="space-y-16">
          {cornerstones.length > 0 && (
            <LocationGroup
              title="Cornerstones"
              hint="Reserved for Fresh Collective's own collectives."
              locations={cornerstones}
              value={value}
              onChange={onChange}
            />
          )}
          {atlas.length > 0 && (
            <LocationGroup
              title="Islands"
              locations={atlas}
              value={value}
              onChange={onChange}
            />
          )}
          {community.length > 0 && (
            <LocationGroup
              title="Community Islands"
              hint="Simple islands where new communities begin."
              locations={community}
              value={value}
              onChange={onChange}
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
              onSelect={onChange}
            />
          ))}
        </div>
      )}
    </StepShell>
  )
}

function LocationGroup({
  title, hint, locations, value, onChange,
}: {
  title: string
  hint?: string
  locations: LocationOption[]
  value: string | null
  onChange: (id: string) => void
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
            onSelect={onChange}
          />
        ))}
      </div>
    </section>
  )
}

function LocationCard({
  loc, selected, onSelect,
}: {
  loc: LocationOption
  selected: boolean
  onSelect: (id: string) => void
}) {
  const artworkUrl = resolveMediaUrl(
    loc.thumbnail_artwork_url ?? loc.hero_artwork_url ?? undefined,
  )
  return (
    <button
      type="button"
      onClick={() => onSelect(loc.id)}
      aria-pressed={selected}
      className="group relative overflow-hidden rounded-2xl text-left transition-all"
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
        style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}
      >
        {artworkUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={artworkUrl}
            alt={loc.name}
            className="h-full w-full transition-transform duration-500 group-hover:scale-[1.02]"
            style={{ objectFit: 'cover', objectPosition: 'center', display: 'block' }}
          />
        ) : (
          <ArtworkPlaceholder label={loc.name} />
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

      <div className="px-5 py-4">
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
