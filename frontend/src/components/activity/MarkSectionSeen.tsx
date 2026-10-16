'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

/**
 * Reports what a section visit actually put on screen.
 *
 * Renders nothing. Mounted by the three section pages, each passing
 * its own category and the ids it displayed.
 *
 * Two values, two different jobs:
 *
 * ``subjectIds`` is *what* was shown. It is why reading one Channel
 * does not clear another, and why viewing upcoming Gatherings does
 * not clear the archive.
 *
 * ``boundarySequence`` is *when* the page was built. Ids alone are
 * not enough: a member reading a Pathway while a second step is
 * published into it submits that same Pathway id, and the new step's
 * activity hangs off it. The boundary excludes anything numbered
 * after the render.
 *
 * **The page must capture the boundary before fetching its content.**
 * Taken afterwards it would include activity created in between —
 * activity that was never rendered — and clear it. Taken before, the
 * worst case is a badge that lingers one visit longer, which is the
 * right way round.
 *
 * No sequence is ever computed here. The client reports facts about
 * its own screen; the server decides what they mean.
 */

interface Props {
  collectiveId: string
  category: 'conversations' | 'pathways' | 'gatherings'
  subjectIds: string[]
  boundarySequence: number
}

export default function MarkSectionSeen({
  collectiveId, category, subjectIds, boundarySequence,
}: Props) {
  const router = useRouter()
  // One report per distinct render. Without this, the refresh below
  // would re-trigger the effect and loop.
  const sent = useRef<string | null>(null)

  const key = `${collectiveId}:${category}:${boundarySequence}:${subjectIds.join(',')}`

  useEffect(() => {
    // Nothing on screen, or a page that rendered before any activity
    // existed. Either way there is nothing to report, and posting
    // anyway would be the one request that could clear something
    // unseen.
    if (subjectIds.length === 0 || boundarySequence <= 0) return
    if (sent.current === key) return
    sent.current = key

    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(apiUrl('/api/activities/seen'), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            collective_id: collectiveId,
            category,
            subject_ids: subjectIds,
            boundary_sequence: boundarySequence,
          }),
        })
        // Only refresh when something actually moved — otherwise a
        // section with nothing new re-renders on every visit for no
        // reason.
        if (!cancelled && res.ok) {
          const body = await res.json().catch(() => null)
          if (body && Object.keys(body.advanced ?? {}).length > 0) {
            router.refresh()
          }
        }
      } catch {
        // Deliberately silent, and deliberately not retried. A failed
        // report costs a badge that clears on the next visit; a retry
        // loop costs far more. The cursor only moves forwards, so
        // nothing is left inconsistent.
      }
    })()
    return () => { cancelled = true }
  }, [key, collectiveId, category, subjectIds, boundarySequence, router])

  return null
}
