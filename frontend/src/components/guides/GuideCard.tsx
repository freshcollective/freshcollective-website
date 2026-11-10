import Link from 'next/link'

import { categoryLabel, guidePath, readingTimeLabel, type GuideCard as Card } from '@/lib/guides'
import { SERIF_HEADING } from './serif'

/**
 * One Guide in a grid.
 *
 * Two shapes from one component, because they are the same card at
 * two sizes and keeping them apart would mean two places to change
 * the meta line.
 *
 *   default  — image band, meta, serif title, standfirst. The
 *              "Latest Guides" grid.
 *   compact  — the same without the standfirst. "Keep reading",
 *              where three cards sit under a finished article and
 *              the titles are the whole decision.
 *
 * The page ground is white, so the card's edge is carried by a
 * hairline ring rather than by contrast with a tinted page. That is
 * `elev-1` from the design language, which pairs a 1px ring with the
 * shadow precisely so a card still reads on a white surface.
 */

/** A calm tinted panel where a Guide has no hero yet. */
const PLACEHOLDER_TINTS = [
  'bg-teal-50',
  'bg-navy-50',
  'bg-gold-50',
] as const

function tintFor(slug: string): string {
  // Deterministic from the slug, so a card does not change colour
  // between renders or between the grid and "Keep reading".
  let sum = 0
  for (let i = 0; i < slug.length; i++) sum = (sum + slug.charCodeAt(i)) % 997
  return PLACEHOLDER_TINTS[sum % PLACEHOLDER_TINTS.length]
}

export default function GuideCard({
  guide,
  compact = false,
}: {
  guide: Card
  compact?: boolean
}) {
  return (
    <Link
      href={guidePath(guide.slug)}
      className="group flex h-full flex-col overflow-hidden rounded-2xl bg-white transition-all duration-200 hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2"
      style={{
        boxShadow:
          '0 1px 2px rgba(15,30,55,0.04), 0 0 0 1px rgba(15,30,55,0.08)',
      }}
    >
      <div className={`relative aspect-[16/9] w-full overflow-hidden ${tintFor(guide.slug)}`}>
        {guide.hero_image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={guide.hero_image_url}
            alt={guide.hero_image_alt ?? ''}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        )}
      </div>

      <div className="flex flex-1 flex-col px-5 py-5">
        <p className="mb-2 text-[13px] text-navy-500">
          {categoryLabel(guide.category)} · {readingTimeLabel(guide.reading_time_minutes)}
        </p>
        <h3
          className="text-[19px] leading-[1.32] text-navy-950 transition-colors group-hover:text-teal-800"
          style={SERIF_HEADING}
        >
          {guide.title}
        </h3>
        {!compact && guide.standfirst && (
          <p className="mt-2.5 text-[14.5px] leading-[1.65] text-navy-700">
            {guide.standfirst}
          </p>
        )}
      </div>
    </Link>
  )
}
