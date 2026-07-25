import { resolveMediaUrl } from '@/lib/api'

/**
 * CollectiveArtworkHeader — the contextual band that anchors every
 * Creator Studio destination inside the collective being tended.
 *
 * The band renders the collective's own artwork as a wide plate (16:5)
 * with the collective name as an uppercase eyebrow and the section
 * name as a serif title. It answers, on every page: *which collective
 * am I in, and what am I creating right now?*
 *
 * Artwork fallback chain:
 *   1. Location hero artwork (Atlas v1.2 — first choice)
 *   2. Collective banner (legacy `cover_image_url`)
 *   3. Soft neutral gradient (no artwork exists)
 *
 * Deliberately kept short vertically (~200-240px) so the section
 * content stays close to the fold.
 */

interface Location {
  name: string
  hero_artwork_url?: string | null
  thumbnail_artwork_url?: string | null
}

interface Props {
  /** Uppercase eyebrow — usually the collective's own name. */
  collectiveName: string
  /** Serif title — the section the creator is inside ("Pathways",
   *  the pathway title, etc.). */
  sectionTitle: string
  /** Optional right-aligned metadata line ("22 steps · 6 sections · Draft"). */
  meta?: React.ReactNode
  /** Optional right-aligned primary action (button / link). */
  action?: React.ReactNode
  /** The active collective's Location, if any. */
  location?: Location | null
  /** Uploaded collective banner, used as a fallback when no Location
   *  artwork is available. */
  coverImageUrl?: string | null
}

export default function CollectiveArtworkHeader({
  collectiveName, sectionTitle, meta, action, location, coverImageUrl,
}: Props) {
  const artwork = resolveMediaUrl(
    location?.hero_artwork_url
      ?? location?.thumbnail_artwork_url
      ?? coverImageUrl
      ?? undefined,
  )

  return (
    <div
      className="relative mb-8 overflow-hidden rounded-2xl"
      style={{
        aspectRatio: '16 / 5',
        maxHeight: 260,
        minHeight: 160,
        background: artwork
          ? '#0C1826'
          : 'linear-gradient(135deg, rgba(56,160,158,0.14) 0%, rgba(85,184,182,0.06) 100%)',
        border: artwork ? undefined : '1px solid rgba(12,24,38,0.06)',
      }}
    >
      {artwork && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={artwork}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 h-full w-full object-cover"
          />
          {/* Scrim so the eyebrow + serif title remain readable at any
              artwork luminance. Deeper on the left where text sits. */}
          <div
            className="absolute inset-0"
            aria-hidden="true"
            style={{
              background:
                'linear-gradient(100deg, rgba(7,24,36,0.78) 0%, rgba(7,42,50,0.52) 55%, rgba(7,59,58,0.34) 100%)',
            }}
          />
        </>
      )}

      <div className="relative flex h-full flex-col justify-end px-6 py-6 md:px-10 md:py-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p
              className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.24em]"
              style={{ color: artwork ? 'rgba(255,255,255,0.85)' : 'rgba(12,24,38,0.55)' }}
            >
              {collectiveName}
            </p>
            <h1
              className="font-serif text-[26px] leading-tight md:text-[32px]"
              style={{ color: artwork ? '#FFFFFF' : '#0C1826' }}
            >
              {sectionTitle}
            </h1>
            {meta && (
              <div
                className="mt-2 text-[13px] italic leading-relaxed"
                style={{
                  color: artwork ? 'rgba(255,255,255,0.80)' : 'rgba(12,24,38,0.60)',
                  fontFamily: 'Georgia, serif',
                }}
              >
                {meta}
              </div>
            )}
          </div>
          {action && (
            <div className="shrink-0">{action}</div>
          )}
        </div>
      </div>
    </div>
  )
}
