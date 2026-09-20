/**
 * Shared card primitives for member surfaces.
 *
 * One iconic card grammar — 3:2 artwork + serif name + italic tagline +
 * meta + CTA — used by every section of the member dashboard (the
 * collectives you belong to, the ones you created, Explore Collectives,
 * the Creator Studio tile) and by the Collective Home. Keeping the
 * pieces in one file means a refinement to card chrome happens once,
 * not five times.
 *
 * Lives under ``components/collective/`` rather than beside the
 * dashboard because it is no longer the dashboard's alone.
 *
 * Colour: the CTA reads ``var(--fc-accent)``, so inside a Collective
 * (where ``CollectiveThemeProvider`` is mounted) it takes that
 * Collective's palette, and everywhere else it falls back to Fresh
 * Collective teal. Fresh Collective provides the structure; the
 * Collective provides the personality.
 */

// The Atlas card treatment — border + soft shadow used by every card on
// the dashboard.
export const ATLAS_CARD_STYLE: React.CSSProperties = {
  border: '1px solid rgba(12, 24, 38, 0.06)',
  boxShadow: '0 6px 20px rgba(12, 24, 38, 0.06)',
}

export function AtlasArtwork({
  url, fallbackBg, alt, overlay, priority = false,
}: {
  url: string | null
  fallbackBg: string
  alt: string
  overlay?: React.ReactNode
  /** Skip lazy-loading for artwork that is above the fold. */
  priority?: boolean
}) {
  return (
    <div
      className="relative w-full overflow-hidden"
      style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}
    >
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt={alt}
          // The wrapper fixes a 3:2 box, so the intrinsic size only has
          // to carry that ratio — it stops the browser reserving zero
          // height before the bytes arrive, which is where the layout
          // shift came from.
          width={1200}
          height={800}
          loading={priority ? undefined : 'lazy'}
          decoding="async"
          className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
        />
      ) : (
        <div className="absolute inset-0" style={{ background: fallbackBg }} />
      )}
      {overlay}
    </div>
  )
}

export function AtlasCardBody({
  name, description, meta, cta,
}: {
  name: string
  description?: string | null
  meta?: string | null
  cta: string
}) {
  return (
    <div className="px-6 pt-5 pb-6">
      <h3
        // Clamped for the same reason the description is: one long
        // Collective name must not push a card taller than its
        // neighbours and stagger the grid.
        className="line-clamp-2 font-serif text-[20px] leading-tight"
        style={{ color: '#0C1826' }}
      >
        {name}
      </h3>
      {description && (
        <p
          className="mt-2 line-clamp-2 text-[13.5px] leading-relaxed italic"
          style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
        >
          {description}
        </p>
      )}
      <div className="mt-4 flex items-baseline justify-between gap-3">
        <p className="text-[12px]" style={{ color: 'rgba(12, 24, 38, 0.50)' }}>
          {meta ?? '\u00A0'}
        </p>
        <span
          className="text-[12px] font-semibold transition-colors"
          style={{ color: 'var(--fc-accent, #38A09E)' }}
        >
          {cta}
        </span>
      </div>
    </div>
  )
}
