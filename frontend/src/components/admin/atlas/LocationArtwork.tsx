import { resolveMediaUrl } from '@/lib/api'

/**
 * LocationArtwork
 *
 * Renders a Location's hero or thumbnail artwork if it exists. When no
 * artwork is uploaded, renders a quiet, elegant placeholder — a soft
 * watercolour wash with a small serif label — so the Admin Portal never
 * looks like a database. Designed for both card contexts (thumbnail-first)
 * and detail contexts (hero).
 *
 * Uploading real curated artwork replaces the placeholder without any
 * consumer having to change.
 */

interface Props {
  url: string | null | undefined
  label: string
  className?: string
  /**
   * `contain` for detail pages (nothing gets cropped); `cover` for cards
   * and thumbnails so the frame fills evenly.
   */
  fit?: 'cover' | 'contain'
}

export default function LocationArtwork({ url, label, className, fit = 'cover' }: Props) {
  const displayUrl = resolveMediaUrl(url ?? undefined)

  if (displayUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={displayUrl}
        alt={label}
        className={className}
        style={{
          width: '100%',
          height: '100%',
          objectFit: fit,
          objectPosition: 'center',
          display: 'block',
        }}
      />
    )
  }

  return <Placeholder label={label} className={className} />
}

// ---------------------------------------------------------------------------

function Placeholder({ label, className }: { label: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 800 500"
      preserveAspectRatio="xMidYMid slice"
      className={className}
      style={{ display: 'block', width: '100%', height: '100%' }}
      role="img"
      aria-label={`${label} — artwork placeholder`}
    >
      <defs>
        <radialGradient id="loc-ph-wash" cx="0.5" cy="0.5" r="0.65">
          <stop offset="0%"  stopColor="#E5F0EF" />
          <stop offset="55%" stopColor="#F4F7F6" />
          <stop offset="100%" stopColor="#FBFDFC" />
        </radialGradient>
      </defs>
      <rect width="800" height="500" fill="url(#loc-ph-wash)" />

      {/* Soft contour rings — a topographic hint */}
      <g fill="none" stroke="rgba(56, 160, 158, 0.18)" strokeWidth="0.9">
        <ellipse cx="400" cy="270" rx="240" ry="130" />
        <ellipse cx="400" cy="270" rx="180" ry="100" />
        <ellipse cx="400" cy="270" rx="120" ry="70"  />
        <ellipse cx="400" cy="270" rx="60"  ry="40"  />
      </g>

      {/* A single quiet gold star at centre — the placeholder's mark */}
      <g transform="translate(400, 270)" opacity="0.75">
        <circle cx="0" cy="0" r="4" fill="#D4B048" />
      </g>

      {/* Serif label */}
      <text
        x="400" y="445"
        textAnchor="middle"
        fill="rgba(12, 24, 38, 0.55)"
        fontFamily="Georgia, serif"
        fontStyle="italic"
        fontSize="20"
      >
        {label}
      </text>
      <text
        x="400" y="470"
        textAnchor="middle"
        fill="rgba(12, 24, 38, 0.35)"
        fontFamily="Georgia, serif"
        fontStyle="italic"
        fontSize="12"
        letterSpacing="1.5"
      >
        awaiting curated artwork
      </text>
    </svg>
  )
}
