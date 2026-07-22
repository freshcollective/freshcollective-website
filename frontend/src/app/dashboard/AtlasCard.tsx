/**
 * Shared card primitives for the member dashboard.
 *
 * The dashboard uses one iconic card grammar (3:2 artwork + serif name +
 * italic tagline + meta + CTA) across every section: the collectives you
 * belong to, the collectives you created, Explore Collectives, and the
 * Creator Studio tile. Keeping the pieces in one file means any future
 * refinement to card chrome happens in one place, not four.
 */

// The Atlas card treatment — border + soft shadow used by every card on
// the dashboard.
export const ATLAS_CARD_STYLE: React.CSSProperties = {
  border: '1px solid rgba(12, 24, 38, 0.06)',
  boxShadow: '0 6px 20px rgba(12, 24, 38, 0.06)',
}

export function AtlasArtwork({
  url, fallbackBg, alt, overlay,
}: {
  url: string | null
  fallbackBg: string
  alt: string
  overlay?: React.ReactNode
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
        className="font-serif text-[20px] leading-tight"
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
          style={{ color: '#38A09E' }}
        >
          {cta}
        </span>
      </div>
    </div>
  )
}
