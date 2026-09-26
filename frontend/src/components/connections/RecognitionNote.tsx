/**
 * The quiet line Fresh Collective puts under something two people
 * genuinely shared.
 *
 * One sentence. No heading, no card, no call to action, nothing to
 * click. It appears on the Gathering or Pathway page itself, where
 * the shared thing already is, so it reads as the platform noticing
 * something rather than suggesting somebody.
 *
 * Deliberately text-only. Avatars were considered and left out of
 * this line: most members have no picture and no name, so a row of
 * identical neutral circles would say nothing while taking the width
 * a sentence needs on a phone. The sentence is the content; nothing
 * here depends on imagery to be understood.
 *
 * No profile links, no actions, no per-person affordance of any kind.
 * Knowing you will be in the same room as someone is not an
 * invitation to do anything about it.
 */

import type { SharedContext, Vantage } from '@/lib/waysToConnect'
import { contextSentence } from '@/lib/waysToConnect'

export default function RecognitionNote({
  context,
  vantage = 'here',
}: {
  context: SharedContext
  vantage?: Vantage
}) {
  const sentence = contextSentence(context, vantage)
  if (!sentence) return null

  return (
    <p
      className="flex items-start gap-2.5 break-words text-[13.5px] leading-[1.6]"
      style={{ color: 'rgba(12, 24, 38, 0.70)', fontFamily: 'Georgia, serif' }}
    >
      {/* Two overlapping rings — the same mark the destination's
          empty state uses, so the idea reads as one thing across the
          product. Decorative: the sentence carries the meaning. */}
      <svg
        viewBox="0 0 24 20"
        width="22"
        height="18"
        aria-hidden="true"
        className="mt-[3px] shrink-0"
      >
        <circle cx="9" cy="9" r="6.5" stroke="#38A09E" strokeWidth="1.2" fill="none" opacity="0.65" />
        <circle cx="15" cy="11" r="6.5" stroke="#D4B048" strokeWidth="1.2" fill="none" opacity="0.8" />
      </svg>
      <span>{sentence}</span>
    </p>
  )
}
