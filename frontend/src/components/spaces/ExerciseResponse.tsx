'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import PrivateResponseArea from './PrivateResponseArea'

/**
 * The member's answer to one Exercise block, inside that block's card.
 *
 * Wraps ``PrivateResponseArea`` — the same box, save button and "Saved."
 * Pause & Reflect uses — and adds the two things specific to exercises:
 * which endpoint to talk to, and the fact that a step can hold several,
 * so each instance is addressed by its own block id.
 *
 * Loads on mount rather than being handed its value by the server. One
 * GET per exercise is a few requests on a step with several, and it
 * keeps ``renderBlocks`` from having to carry a map of member data
 * through two call sites that mostly do not want it — including the
 * Knowledge Guide and the public About pages, which must not show this
 * at all.
 *
 * Until the load resolves the box renders empty and disabled rather
 * than showing nothing: a member who starts typing into an empty box
 * that is about to be replaced by their saved text would lose what they
 * just wrote.
 */

export default function ExerciseResponse({
  spaceSlug,
  pathwaySlug,
  stepSlug,
  blockId,
}: {
  spaceSlug: string
  pathwaySlug: string
  stepSlug: string
  blockId: string
}) {
  const [value, setValue] = useState('')
  const [loaded, setLoaded] = useState(false)
  // The creator can withdraw the response area. The server is the
  // authority on that — it refuses writes either way — but knowing it
  // here lets us not render a box the member cannot use.
  const [enabled, setEnabled] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)

  const endpoint =
    `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}` +
    `/exercises/${blockId}/response`

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(apiUrl(endpoint), { credentials: 'include' })
        if (!res.ok) {
          if (!cancelled) { setLoadFailed(true); setLoaded(true) }
          return
        }
        const body = await res.json()
        if (cancelled) return
        setValue(body.response_text ?? '')
        setEnabled(body.response_enabled !== false)
        setLoaded(true)
      } catch {
        if (!cancelled) { setLoadFailed(true); setLoaded(true) }
      }
    })()
    return () => { cancelled = true }
  }, [endpoint])

  async function save(): Promise<boolean> {
    const res = await fetch(apiUrl(endpoint), {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ response_text: value }),
    })
    return res.ok
  }

  // A creator who turned the area off: the heading and instructions
  // above still render, this does not.
  if (loaded && !enabled) return null

  return (
    <div
      className="mt-5 border-t pt-5"
      style={{ borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.20))' }}
    >
      {loadFailed ? (
        <p className="text-[13px] text-amber-700" role="alert">
          Your response could not be loaded just now. Reload the page to try
          again — nothing you have saved before has been lost.
        </p>
      ) : (
        <PrivateResponseArea
          // A step can hold several exercises, so the id has to be per
          // block or the labels all point at the first box.
          textareaId={`exercise-response-${blockId}`}
          label="Your Response"
          labelClassName="font-serif text-[17px] leading-snug text-navy-900"
          value={value}
          onChange={setValue}
          onSave={save}
          saveLabel="Save response"
          placeholder="Write your response here..."
          rows={5}
          readOnly={!loaded}
        />
      )}
    </div>
  )
}
