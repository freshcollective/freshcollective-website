import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'

/**
 * CollectivePageHeader (file name kept as CollectiveArtworkHeader.tsx
 * for backwards compat) — the shared collective-context header used at
 * the top of every collective-specific Creator Studio page.
 *
 * The header renders the collective's own artwork as a wide plate
 * (16:5) with the collective name as an uppercase eyebrow and the
 * current section as a serif title. It answers, on every page: *which
 * collective am I in, and what am I looking at right now?*
 *
 * Since the sidebar no longer carries an active-collective card, this
 * header is the single visual anchor for collective identity.
 *
 * Artwork fallback chain:
 *   1. Location hero artwork (Atlas v1.2 — first choice)
 *   2. Location thumbnail (Atlas v1.2 — second choice)
 *   3. Collective banner (legacy `cover_image_url`)
 *   4. Soft neutral gradient (no artwork exists)
 *
 * Variants:
 *   - default (~200-260px) — the standard page header
 *   - slim    (~120-140px) — for highly focused writing pages (step
 *                            editor) where the document should sit
 *                            close to the fold
 */

interface Location {
  name?: string
  hero_artwork_url?: string | null
  thumbnail_artwork_url?: string | null
}

interface Props {
  /** Uppercase eyebrow — the collective's own name. */
  collectiveName: string
  /** Serif title — the section the creator is inside ("Pathways",
   *  the pathway title, the step title, etc.). */
  sectionTitle: string
  /** Optional metadata line ("22 steps · 6 sections · Draft"). */
  meta?: React.ReactNode
  /** Optional right-aligned primary action (button / link). */
  action?: React.ReactNode
  /** Optional back link rendered above the artwork band. */
  backLink?: { href: string; label: string }
  /** The active collective's Location, if any. */
  location?: Location | null
  /** Uploaded collective banner, used as a fallback when no Location
   *  artwork is available. */
  coverImageUrl?: string | null
  /** Header size. ``slim`` is used by the step editor. */
  variant?: 'default' | 'slim'
}

export default function CollectiveArtworkHeader({
  collectiveName, sectionTitle, meta, action, backLink,
  location, coverImageUrl, variant = 'default',
}: Props) {
  const artwork = resolveMediaUrl(
    location?.hero_artwork_url
      ?? location?.thumbnail_artwork_url
      ?? coverImageUrl
      ?? undefined,
  )

  const isSlim = variant === 'slim'

  return (
    <div className="mb-6">
      {backLink && (
        <Link
          href={backLink.href}
          className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-medium text-slate-500 transition-colors hover:text-slate-700"
        >
          ← {backLink.label}
        </Link>
      )}

      <div
        className="relative overflow-hidden rounded-2xl"
        style={{
          aspectRatio: isSlim ? '16 / 3' : '16 / 5',
          maxHeight: isSlim ? 140 : 260,
          minHeight: isSlim ? 100 : 160,
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

        <div
          className={`relative flex h-full flex-col justify-end ${
            isSlim ? 'px-5 py-4 md:px-8 md:py-5' : 'px-6 py-6 md:px-10 md:py-8'
          }`}
        >
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <p
                className={`mb-1.5 font-semibold uppercase ${
                  isSlim ? 'text-[10px] tracking-[0.22em]' : 'text-[10.5px] tracking-[0.24em] mb-2'
                }`}
                style={{ color: artwork ? 'rgba(255,255,255,0.85)' : 'rgba(12,24,38,0.55)' }}
              >
                {collectiveName}
              </p>
              <h1
                className={`font-serif leading-tight ${
                  isSlim ? 'text-[20px] md:text-[24px]' : 'text-[26px] md:text-[32px]'
                }`}
                style={{ color: artwork ? '#FFFFFF' : '#0C1826' }}
              >
                {sectionTitle}
              </h1>
              {meta && (
                <div
                  className={`italic leading-relaxed ${
                    isSlim ? 'mt-1 text-[12px]' : 'mt-2 text-[13px]'
                  }`}
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
    </div>
  )
}
