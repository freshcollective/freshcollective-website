'use client'

import { useMemo, useState } from 'react'

import FeaturedGuideCard from '@/components/guides/FeaturedGuideCard'
import GuideCard from '@/components/guides/GuideCard'
import { GUIDE_CATEGORIES, type GuideCard as Card } from '@/lib/guides'
import { SERIF_HEADING } from '@/components/guides/serif'

/**
 * The filterable part of ``/guides``.
 *
 * Client-side because the whole list is already on the page — there
 * are a handful of Guides, not hundreds, and a round trip to filter
 * three categories would be slower and would lose the scroll
 * position for no benefit. When the list is long enough that this
 * stops being true, the honest fix is pagination plus a server
 * filter, not a bigger client payload.
 *
 * The filter is a group of buttons rather than links, so
 * ``aria-pressed`` can say which one is active. Tabs were the other
 * option and would be wrong: these do not switch between panels,
 * they narrow one list.
 */

const ALL = 'all'

export default function GuidesIndexClient({ guides }: { guides: Card[] }) {
  const [active, setActive] = useState<string>(ALL)

  const featured = useMemo(() => guides.find((g) => g.featured) ?? null, [guides])

  const visible = useMemo(() => {
    // The featured Guide is shown above in its own large card, so it
    // is left out of the grid rather than appearing twice. It comes
    // back when a category is chosen: at that point the big card is
    // hidden and leaving it out entirely would make a Guide vanish
    // from its own category.
    const base = active === ALL && featured
      ? guides.filter((g) => g.slug !== featured.slug)
      : guides
    return active === ALL ? base : base.filter((g) => g.category === active)
  }, [guides, active, featured])

  const filters = [{ slug: ALL, label: 'All Guides' }, ...GUIDE_CATEGORIES]

  return (
    <>
      <div
        className="mb-12 flex flex-wrap justify-center gap-2.5 md:mb-14"
        role="group"
        aria-label="Filter Guides by category"
      >
        {filters.map(({ slug, label }) => {
          const on = active === slug
          return (
            <button
              key={slug}
              type="button"
              aria-pressed={on}
              onClick={() => setActive(slug)}
              className={
                on
                  ? 'rounded-full bg-navy-950 px-5 py-2.5 text-[14.5px] font-medium text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2'
                  : 'rounded-full border border-navy-100 bg-white px-5 py-2.5 text-[14.5px] font-medium text-navy-700 transition-colors hover:border-navy-200 hover:text-navy-950 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2'
              }
            >
              {label}
            </button>
          )
        })}
      </div>

      {active === ALL && featured && (
        <div className="mb-14 md:mb-16">
          <FeaturedGuideCard guide={featured} />
        </div>
      )}

      <h2
        className="mb-6 text-[24px] leading-[1.2] text-navy-950 md:mb-8 md:text-[26px]"
        style={SERIF_HEADING}
      >
        {active === ALL
          ? 'Latest Guides'
          : filters.find((f) => f.slug === active)?.label}
      </h2>

      {visible.length === 0 ? (
        <p className="py-8 text-[16px] leading-[1.7] text-navy-700">
          Nothing here yet. More Guides are on the way.
        </p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visible.map((guide) => (
            <GuideCard key={guide.slug} guide={guide} />
          ))}
        </div>
      )}
    </>
  )
}
