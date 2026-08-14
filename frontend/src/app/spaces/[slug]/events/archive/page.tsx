import Link from 'next/link'
import { getSpace, getSpaceEvents } from '@/lib/serverApi'
import ArchivedGatheringsList from '@/components/spaces/ArchivedGatheringsList'
import type { EventSummary, SpaceResponse } from '@/types/platform'

/**
 * Member-facing archive of past Gatherings.
 *
 * Fetches with ?scope=archive so the backend returns only Gatherings
 * whose end time has passed, ordered newest first. Access rules
 * mirror the main list — non-members only see public rows.
 */

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceEventsArchivePage({ params }: Props) {
  const { slug } = await params

  const [space, events] = await Promise.all([
    getSpace(slug),
    getSpaceEvents(slug, 'archive'),
  ]) as [SpaceResponse | null, EventSummary[]]

  const timezone = space?.timezone ?? 'Australia/Melbourne'

  return (
    <div className="max-w-3xl">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/events`}
          className="text-sm text-black transition-colors hover:text-[color:var(--fc-accent,#0d9488)]"
        >
          ← Upcoming Gatherings
        </Link>
      </div>

      {/* Heading — matches the intro style of the main page but calmer */}
      <div className="mb-8">
        <div className="mb-3 h-[2px] w-8 rounded-full"
             style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }} />
        <h1 className="mb-2 font-serif text-2xl text-navy-900 md:text-3xl">
          Past Gatherings
        </h1>
        <p className="text-[14px] leading-relaxed text-black">
          Revisit previous Gatherings, recordings and shared resources from this Collective.
        </p>
      </div>

      <ArchivedGatheringsList
        events={events}
        spaceSlug={slug}
        timezone={timezone}
        emptyMessage="There are no past Gatherings to revisit yet."
      />
    </div>
  )
}
