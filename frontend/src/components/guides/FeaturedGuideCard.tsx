import Link from 'next/link'

import { categoryLabel, guidePath, readingTimeLabel, type GuideCard } from '@/lib/guides'
import { SERIF_HEADING } from './serif'

/**
 * The featured Guide, as one wide card.
 *
 * Image on one side, words on the other, at roughly half and half —
 * the one asymmetry on ``/guides`` and the reason the eye lands here
 * before the grid. Stacks image-above-words on a phone, where a
 * side-by-side split would leave the title about twelve characters
 * wide.
 */
export default function FeaturedGuideCard({ guide }: { guide: GuideCard }) {
  return (
    <Link
      href={guidePath(guide.slug)}
      className="group grid overflow-hidden rounded-2xl bg-white transition-all duration-200 hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2 md:grid-cols-2"
      style={{
        boxShadow:
          '0 1px 3px rgba(15,30,55,0.05), 0 0 0 1px rgba(15,30,55,0.08)',
      }}
    >
      <div className="relative aspect-[16/10] w-full overflow-hidden bg-teal-50 md:aspect-auto md:min-h-[320px]">
        {guide.hero_image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={guide.hero_image_url}
            alt={guide.hero_image_alt ?? ''}
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
      </div>

      <div className="flex flex-col justify-center px-6 py-8 md:px-10 md:py-12">
        <p className="mb-3 text-[13.5px] text-navy-500">
          {categoryLabel(guide.category)} · {readingTimeLabel(guide.reading_time_minutes)}
        </p>
        <h2
          className="text-[27px] leading-[1.22] tracking-[-0.02em] text-navy-950 transition-colors group-hover:text-teal-800 md:text-[32px]"
          style={SERIF_HEADING}
        >
          {guide.title}
        </h2>
        {guide.standfirst && (
          <p className="mt-4 max-w-[46ch] text-[16px] leading-[1.7] text-navy-700">
            {guide.standfirst}
          </p>
        )}
        <span className="mt-6 inline-flex items-center gap-2 text-[15px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800">
          Read the Guide
          <span aria-hidden="true" className="transition-transform group-hover:translate-x-0.5">
            →
          </span>
        </span>
      </div>
    </Link>
  )
}
