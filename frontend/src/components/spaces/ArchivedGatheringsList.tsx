import EventCard from '@/components/spaces/EventCard'
import type { EventSummary } from '@/types/platform'

/**
 * ArchivedGatheringsList — the calm read-only counterpart to
 * GatheringsView.
 *
 * Deliberately simple: no calendar toggle, no booking mutations, no
 * term-pass widget, no series booking. Just newest-first cards rendered
 * in archive mode. Keeps the main GatheringsView complexity out of the
 * archive page so past-Gathering behaviour stays predictable.
 *
 * The server has already scoped events to `?scope=archive`, so we
 * render whatever it hands us. Ordering (newest first) is done
 * server-side to keep pagination-friendly semantics available later.
 */

interface Props {
  events: EventSummary[]
  spaceSlug: string
  timezone: string
  /** Copy shown when the list is empty. Pages provide context-
   *  appropriate wording (member vs caretaker). */
  emptyMessage?: string
}

export default function ArchivedGatheringsList({
  events,
  spaceSlug,
  timezone,
  emptyMessage = 'There are no past Gatherings to revisit yet.',
}: Props) {
  if (events.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-100 bg-white px-7 py-10 text-center">
        <p className="mb-2 font-serif text-xl text-navy-800">
          {emptyMessage}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {events.map((event) => (
        <EventCard
          key={event.id}
          event={event}
          spaceSlug={spaceSlug}
          timezone={timezone}
          archive
        />
      ))}
    </div>
  )
}
