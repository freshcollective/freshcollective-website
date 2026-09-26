/**
 * The destination's body: shared experiences, grouped by what they
 * are, never by who is in them.
 *
 * Three groups in the order a member is likely to act on them — what
 * is about to happen, what they are in the middle of, what already
 * did. A group with nothing in it renders nothing at all; an empty
 * heading is a promise the page cannot keep.
 *
 * The same person may appear under several headings, because those
 * are several different things they share. Collapsing them into one
 * row per person would turn this page into a directory, which is the
 * one thing it must never become.
 */

import type { GroupedContexts } from '@/lib/waysToConnect'
import SharedContextCard from './SharedContextCard'

function Group({
  title,
  blurb,
  children,
}: {
  title: string
  blurb: string
  children: React.ReactNode
}) {
  return (
    <section className="mt-10 first:mt-0">
      <h2
        className="font-serif text-[15px] tracking-[0.01em]"
        style={{ color: '#0C1826' }}
      >
        {title}
      </h2>
      <p className="mt-1 text-[12.5px]" style={{ color: 'rgba(12, 24, 38, 0.5)' }}>
        {blurb}
      </p>
      <ul className="mt-4 flex flex-col gap-3">{children}</ul>
    </section>
  )
}

export default function SharedContextGroups({
  grouped,
  truncated = false,
}: {
  grouped: GroupedContexts
  truncated?: boolean
}) {
  return (
    <div className="mx-auto max-w-[720px] px-6 pb-24 pt-2 md:px-8">
      {grouped.comingUp.length > 0 && (
        <Group
          title="Coming up"
          blurb="Gatherings you’ll be at alongside other people."
        >
          {grouped.comingUp.map((c) => (
            <SharedContextCard key={`g-${c.id}`} context={c} />
          ))}
        </Group>
      )}

      {grouped.pathways.length > 0 && (
        <Group
          title="Shared pathways"
          blurb="Journeys you and others are both moving through."
        >
          {grouped.pathways.map((c) => (
            <SharedContextCard key={`p-${c.id}`} context={c} />
          ))}
        </Group>
      )}

      {grouped.recent.length > 0 && (
        <Group
          title="Recent crossings"
          blurb="Gatherings you were at alongside other people."
        >
          {grouped.recent.map((c) => (
            <SharedContextCard key={`r-${c.id}`} context={c} />
          ))}
        </Group>
      )}

      {truncated && (
        /* Deliberately no count, no total, no "load more". There is
           nothing to page to — this is a readable selection of what
           is current, not the first screen of a list of members. */
        <p
          className="mt-8 text-center text-[12.5px] italic"
          style={{ color: 'rgba(12, 24, 38, 0.5)', fontFamily: 'Georgia, serif' }}
        >
          Showing a selection of what you’re currently sharing.
        </p>
      )}
    </div>
  )
}
