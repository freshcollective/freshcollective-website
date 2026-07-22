'use client'

import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'

/**
 * Collective Home — the Atlas v1.2 replacement for the retired
 * IslandArtworkPanel. Shows where the collective lives, what its current
 * atmosphere and colour palette are, and offers two doors back into the
 * ritual: change Location, or edit collective identity.
 */

interface Props {
  slug: string
  location: {
    name: string
    description: string | null
    hero_artwork_url: string | null
  } | null
  atmosphereNames: string[]
  colourPalette: {
    name: string
    palette: { primary: string; secondary: string; accent: string; background: string }
  } | null
}

export default function CollectiveHomePanel({
  slug, location, atmosphereNames, colourPalette,
}: Props) {
  const artworkUrl = resolveMediaUrl(location?.hero_artwork_url ?? undefined)

  return (
    <section
      className="overflow-hidden rounded-2xl bg-white"
      style={{ border: '1px solid rgba(56,160,158,0.18)', borderTop: '3px solid rgba(191,152,48,0.55)' }}
    >
      <div className="px-6 pt-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Collective Home</h2>
        <p className="text-[14px] italic" style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
          Every collective belongs somewhere in the Fresh Collective world.
        </p>
      </div>

      <div className="px-6 pt-6 pb-6">
        {location ? (
          <>
            {/* Hero */}
            <div
              className="mb-5 w-full overflow-hidden rounded-2xl bg-white"
              style={{
                aspectRatio: '3 / 2',
                border: '1px solid rgba(12,24,38,0.08)',
                boxShadow: '0 8px 24px rgba(12,24,38,0.06)',
              }}
            >
              {artworkUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={artworkUrl}
                  alt={location.name}
                  style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'center', display: 'block' }}
                />
              ) : (
                <ArtworkPlaceholder label={location.name} />
              )}
            </div>

            <div className="mb-5">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: '#38A09E' }}>
                Location
              </p>
              <h3 className="font-serif text-[22px]" style={{ color: '#0C1826' }}>
                {location.name}
              </h3>
              {location.description && (
                <p
                  className="mt-2 text-[14px] italic leading-relaxed"
                  style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
                >
                  {location.description}
                </p>
              )}
            </div>

            <div className="grid gap-5 md:grid-cols-2">
              <div>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: '#38A09E' }}>
                  Atmosphere
                </p>
                {atmosphereNames.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {atmosphereNames.map((a) => (
                      <span
                        key={a}
                        className="rounded-full px-2.5 py-1 text-[11.5px] font-medium"
                        style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}
                      >
                        {a}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-[13px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
                    Not chosen yet.
                  </p>
                )}
              </div>

              <div>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: '#38A09E' }}>
                  Colour palette
                </p>
                {colourPalette ? (
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1.5" aria-hidden="true">
                      {[
                        colourPalette.palette.primary,
                        colourPalette.palette.secondary,
                        colourPalette.palette.accent,
                        colourPalette.palette.background,
                      ].map((c, i) => (
                        <span
                          key={i}
                          className="block h-4 w-4 rounded-full"
                          style={{ background: c, border: i === 3 ? '1px solid rgba(12,24,38,0.10)' : 'none' }}
                        />
                      ))}
                    </div>
                    <p
                      className="text-[13.5px] italic"
                      style={{ color: '#0C1826', fontFamily: 'Georgia, serif' }}
                    >
                      {colourPalette.name}
                    </p>
                  </div>
                ) : (
                  <p className="text-[13px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
                    Not chosen yet.
                  </p>
                )}
              </div>
            </div>

            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href={`/build-your-collective?mode=change-location&slug=${slug}`}
                className="rounded-full px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)', letterSpacing: '0.06em' }}
              >
                Relocate Collective
              </Link>
              <Link
                href={`/build-your-collective?mode=edit-identity&slug=${slug}`}
                className="rounded-full px-4 py-2.5 text-[13px] font-medium transition-colors hover:bg-black/[4%]"
                style={{
                  background: '#FFFFFF',
                  border: '1px solid rgba(12,24,38,0.14)',
                  color: '#0C1826',
                }}
              >
                Edit Collective Identity
              </Link>
            </div>
          </>
        ) : (
          <div
            className="rounded-2xl px-6 py-10 text-center"
            style={{
              background: 'rgba(56,160,158,0.04)',
              border: '1px dashed rgba(56,160,158,0.30)',
            }}
          >
            <p className="mb-2 font-serif text-[18px]" style={{ color: '#0C1826' }}>
              This collective has not chosen a Location yet.
            </p>
            <p
              className="mx-auto mb-6 max-w-md text-[14px] italic leading-relaxed"
              style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}
            >
              Choose a Location from the Fresh Collective world — the Atlas artwork becomes the visual home for your collective.
            </p>
            <Link
              href={`/build-your-collective?mode=change-location&slug=${slug}`}
              className="inline-flex items-center rounded-full px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)', letterSpacing: '0.06em' }}
            >
              Choose a Location
            </Link>
          </div>
        )}
      </div>
    </section>
  )
}

function ArtworkPlaceholder({ label }: { label: string }) {
  return (
    <svg viewBox="0 0 400 260" preserveAspectRatio="xMidYMid slice" className="h-full w-full" aria-hidden="true">
      <defs>
        <radialGradient id="ch-ph" cx="0.5" cy="0.5" r="0.65">
          <stop offset="0%" stopColor="#E5F0EF" />
          <stop offset="60%" stopColor="#F4F7F6" />
          <stop offset="100%" stopColor="#FBFDFC" />
        </radialGradient>
      </defs>
      <rect width="400" height="260" fill="url(#ch-ph)" />
      <text x="200" y="140" textAnchor="middle" fill="rgba(12,24,38,0.45)" fontFamily="Georgia, serif" fontStyle="italic" fontSize="14">
        {label}
      </text>
    </svg>
  )
}
