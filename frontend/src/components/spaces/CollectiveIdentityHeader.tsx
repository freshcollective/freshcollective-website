import { resolveMediaUrl } from '@/lib/api'

/**
 * CollectiveIdentityHeader
 *
 * Atlas v1.2 — the shared collective header. The chosen Atlas Location
 * is the primary visual identity: its hero artwork fills the band and a
 * "LOCATION" eyebrow names it, then the collective's own identity
 * (optional logo, name, tagline, atmosphere) sits over the artwork.
 *
 * When the collective has no Location assigned, the header falls back
 * to the previous banner behaviour (uploaded cover image, or the teal
 * gradient). This keeps legacy collectives visually intact.
 *
 * Deliberately isolated as one presentational component so the whole
 * experiment can be refined or reverted from a single file.
 */

interface Location {
  name: string
  hero_artwork_url: string | null
  thumbnail_artwork_url?: string | null
}

interface Props {
  collectiveName: string
  tagline: string | null
  logoUrl?: string | null
  coverImageUrl?: string | null
  location?: Location | null
  atmosphereLabels?: string[]
}

export default function CollectiveIdentityHeader({
  collectiveName,
  tagline,
  logoUrl,
  coverImageUrl,
  location,
  atmosphereLabels = [],
}: Props) {
  const locationArt = resolveMediaUrl(
    location?.hero_artwork_url ?? undefined,
  )
  const legacyBanner = resolveMediaUrl(coverImageUrl ?? undefined)
  const backgroundImage = locationArt ?? legacyBanner
  const logoResolved = resolveMediaUrl(logoUrl ?? undefined)

  return (
    <div
      className="relative overflow-hidden px-6 py-10 md:px-10 md:py-16"
      style={{
        background:
          'radial-gradient(rgba(66,199,198,0.07) 1px, transparent 1px), ' +
          'radial-gradient(ellipse at 78% 20%, rgba(66,199,198,0.38), transparent 48%), ' +
          'radial-gradient(ellipse at 10% 80%, rgba(56,160,158,0.22), transparent 42%), ' +
          'linear-gradient(135deg, #071824 0%, #092030 40%, #073B3A 100%)',
        backgroundSize: '22px 22px, auto, auto, auto',
        boxShadow: '0 8px 40px rgba(7,24,36,0.28)',
      }}
    >
      {backgroundImage && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={backgroundImage}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 h-full w-full object-cover"
          />
          {/* Scrim — deeper on the left so text is always readable */}
          <div
            className="absolute inset-0"
            style={{
              background:
                'linear-gradient(105deg, rgba(7,24,36,0.78) 0%, rgba(7,42,50,0.55) 55%, rgba(7,59,58,0.45) 100%)',
            }}
          />
        </>
      )}

      <div className="relative mx-auto max-w-6xl">
        {/* Location eyebrow — only present when the collective has one */}
        {location?.name && (
          <>
            <p
              className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.28em]"
              style={{ color: 'rgba(255,255,255,0.72)' }}
            >
              Location
            </p>
            <p
              className="mb-6 font-serif text-[15px] italic md:text-[16px]"
              style={{ color: 'rgba(255,255,255,0.90)' }}
            >
              {location.name}
            </p>
          </>
        )}

        {/* Soft gold accent line kept for continuity with the previous header */}
        <div
          className="mb-4 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
          aria-hidden="true"
        />

        <div className="flex items-center gap-3">
          {logoResolved && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logoResolved}
              alt=""
              aria-hidden="true"
              className="h-10 w-10 shrink-0 rounded-lg object-contain md:h-12 md:w-12"
              style={{
                background: 'rgba(255,255,255,0.94)',
                padding: 4,
                boxShadow: '0 4px 12px rgba(7,24,36,0.22)',
              }}
            />
          )}
          <h1
            className="font-serif text-3xl md:text-4xl"
            style={backgroundImage ? { color: '#FFFFFF' } : {
              background: 'linear-gradient(120deg, #55D7D2 0%, #FFFFFF 55%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            {collectiveName}
          </h1>
        </div>

        {tagline && (
          <p
            className="mt-2 text-[14.5px] leading-relaxed md:text-[15px]"
            style={{ color: 'rgba(255,255,255,0.92)' }}
          >
            {tagline}
          </p>
        )}

        {atmosphereLabels.length > 0 && (
          <p
            className="mt-3 text-[12.5px] italic tracking-wide"
            style={{
              color: 'rgba(255,255,255,0.75)',
              fontFamily: 'Georgia, serif',
            }}
          >
            {atmosphereLabels.join(' • ')}
          </p>
        )}
      </div>
    </div>
  )
}
