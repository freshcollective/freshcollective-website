/**
 * One shared experience on the Ways to Connect destination.
 *
 * The hierarchy is the argument: the thing shared is the headline,
 * the Collective and timing sit under it as context, the people come
 * third in a plain sentence, and the only action goes back into the
 * shared thing. A member reading this should feel pointed at a
 * Gathering, not at a person.
 *
 * A row rather than a tile, and a list rather than a grid. One
 * recognition in a grid reads as a failed grid; one recognition in a
 * list reads as one recognition, which is exactly what it is and what
 * most members will have for a long time.
 */

import Link from 'next/link'
import type { SharedContext } from '@/lib/waysToConnect'
import { contextSentence } from '@/lib/waysToConnect'
import { formatGatheringFullDate, formatGatheringTime } from '@/lib/dateTime'

/** "EMBODY · Thursday, 8 October 2026, 19:00 AEDT".
 *
 *  Always rendered in the Collective's own timezone. A Gathering's
 *  `starts_at` is stored naive, so formatting it against the
 *  rendering machine's clock would quietly give a member in another
 *  country the wrong evening. */
function metaLine(context: SharedContext): string {
  if (context.kind === 'pathway') return context.collective.name
  const tz = context.collective.timezone
  const day = formatGatheringFullDate(context.starts_at, tz)
  const time = formatGatheringTime(context.starts_at, tz)
  return `${context.collective.name} · ${day}, ${time}`
}

function href(context: SharedContext): string {
  return context.kind === 'gathering'
    ? `/spaces/${context.collective.slug}/events/${context.id}`
    : `/spaces/${context.collective.slug}/pathways/${context.slug}`
}

function actionLabel(context: SharedContext): string {
  return context.kind === 'gathering' ? 'View Gathering' : 'Open Pathway'
}

export default function SharedContextCard({
  context,
}: {
  context: SharedContext
}) {
  const sentence = contextSentence(context, 'there')

  return (
    <li
      className="rounded-2xl bg-white px-5 py-5 md:px-6 md:py-6"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.07)',
        boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
      }}
    >
      <h3
        className="font-serif text-[17px] leading-snug break-words md:text-[18px]"
        style={{ color: '#0C1826' }}
      >
        {context.title}
      </h3>

      <p
        className="mt-1 text-[12.5px] break-words"
        style={{ color: 'rgba(12, 24, 38, 0.52)' }}
      >
        {metaLine(context)}
      </p>

      {sentence && (
        <p
          className="mt-3 text-[14px] leading-[1.65] break-words"
          style={{ color: 'rgba(12, 24, 38, 0.78)', fontFamily: 'Georgia, serif' }}
        >
          {sentence}
        </p>
      )}

      <Link
        href={href(context)}
        className="mt-4 inline-flex max-w-full items-center gap-1.5 text-[13px] font-semibold transition-opacity hover:opacity-70"
        style={{ color: '#2F8F8D' }}
      >
        {/* The accessible name names the thing, not just the verb —
            "View Gathering" repeated down a list tells a screen
            reader nothing about which one. */}
        {actionLabel(context)}
        <span className="sr-only"> — {context.title}</span>
        <span aria-hidden="true">→</span>
      </Link>
    </li>
  )
}
