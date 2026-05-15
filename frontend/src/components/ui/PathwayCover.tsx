import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl } from '@/lib/api'

interface Props {
  slug: string
  title: string
  coverImageUrl?: string | null
  isComingSoon?: boolean
  showLabel?: boolean
}

export default function PathwayCover({
  slug,
  title,
  coverImageUrl,
  isComingSoon = false,
  showLabel = true,
}: Props) {
  const cs = getPathwayCoverStyle(slug)
  const resolvedImageUrl = resolveMediaUrl(coverImageUrl)
  const hasImage = Boolean(resolvedImageUrl)

  const titleColor = hasImage ? '#FFFFFF' : (isComingSoon ? '#152236' : cs.titleColor)
  const labelColor = hasImage ? 'rgba(255,255,255,0.70)' : (isComingSoon ? '#2E8584' : cs.labelColor)
  const labelText = isComingSoon ? 'Coming Soon' : 'Pathway'

  return (
    // padding-bottom 56.25% = 16:9 aspect ratio
    <div className="relative w-full overflow-hidden" style={{ paddingBottom: '56.25%' }}>

      {/* CSS artwork — shown when no image */}
      {!hasImage && (
        <div
          className="absolute inset-0"
          style={{
            background: isComingSoon
              ? 'radial-gradient(rgba(56,160,158,0.07) 1px, transparent 1px), linear-gradient(135deg, #EAF8F7 0%, #E8F5F4 55%, #F4FAFA 100%)'
              : cs.background,
            backgroundSize: isComingSoon ? '18px 18px, auto' : (cs.backgroundSize ?? 'auto'),
          }}
        />
      )}

      {/* Uploaded image */}
      {hasImage && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={resolvedImageUrl!}
            alt={title}
            className="absolute inset-0 h-full w-full object-cover"
          />
          {/* Gradient scrim for title legibility */}
          <div
            className="absolute inset-0"
            style={{
              background:
                'linear-gradient(to top, rgba(7,24,36,0.72) 0%, rgba(7,24,36,0.18) 55%, transparent 80%)',
            }}
          />
        </>
      )}

      {/* Coming-soon tint over CSS art */}
      {isComingSoon && !hasImage && (
        <div className="absolute inset-0" style={{ background: 'rgba(240,252,250,0.42)' }} />
      )}

      {/* Title / label overlay */}
      <div className="absolute inset-0 flex flex-col justify-end p-4 pb-4">
        {showLabel && (
          <span
            className="mb-1 block text-[9px] font-bold uppercase tracking-[0.20em]"
            style={{ color: labelColor }}
          >
            {labelText}
          </span>
        )}
        <p
          className="font-serif text-[17px] leading-snug line-clamp-2"
          style={{ color: titleColor }}
        >
          {title}
        </p>
      </div>
    </div>
  )
}
