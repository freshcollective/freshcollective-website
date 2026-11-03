'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { useToast } from '@/components/platform'
import {
  DUPLICATE_SUCCESS_MESSAGE,
  canDuplicateGathering,
  duplicateDraftHref,
  duplicateEndpoint,
  duplicateErrorMessage,
  type DuplicableGathering,
} from '@/lib/gatheringDuplication'

/**
 * "Duplicate" on a Gathering in Creator Studio.
 *
 * Creates a new dateless draft from an existing standalone Gathering
 * and takes the creator straight to its editor. The original is not
 * touched — the endpoint reads it and writes a separate row — and the
 * wording says "draft created" rather than anything that could read as
 * "this Gathering changed".
 *
 * A Client Component because it posts and then navigates. The cards it
 * sits in are Server Components; it is rendered as a sibling of their
 * links, never a child, because an interactive control nested inside
 * an <a> is both invalid markup and unreachable by keyboard.
 */
export default function DuplicateGatheringButton({
  spaceSlug,
  event,
  variant = 'card',
}: {
  spaceSlug: string
  event: DuplicableGathering
  /** `card` for the Gatherings grid, `row` for the dense archive list. */
  variant?: 'card' | 'row'
}) {
  const router = useRouter()
  const { show } = useToast()
  const [busy, setBusy] = useState(false)

  // Belt and braces with the server's own refusal. Callers are
  // expected to check too, so this is the case where a list filter
  // changes and nobody remembers.
  if (!canDuplicateGathering(event)) return null

  async function duplicate() {
    if (busy) return
    setBusy(true)
    try {
      const res = await fetch(apiUrl(duplicateEndpoint(spaceSlug, event.id)), {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        let detail: unknown
        try { detail = (await res.json())?.detail } catch { /* not JSON */ }
        console.error(`[gathering/duplicate] ${res.status}`, detail)
        show(duplicateErrorMessage(res.status, detail), { tone: 'error' })
        setBusy(false)
        return
      }
      const created = await res.json()
      show(DUPLICATE_SUCCESS_MESSAGE, { tone: 'success' })
      // Refresh first so the list behind them reflects the new draft
      // when they navigate back; then open the draft's editor.
      router.refresh()
      router.push(duplicateDraftHref(spaceSlug, created.id))
    } catch (err) {
      console.error('[gathering/duplicate]', err)
      show(duplicateErrorMessage(0, null), { tone: 'error' })
      setBusy(false)
    }
  }

  const label = busy ? 'Duplicating…' : 'Duplicate'

  if (variant === 'row') {
    return (
      <button
        type="button"
        onClick={duplicate}
        disabled={busy}
        aria-busy={busy}
        className="shrink-0 rounded-full border px-3 py-1 text-[11.5px] font-semibold transition-colors disabled:opacity-60"
        style={{
          borderColor: 'rgba(56,160,158,0.35)',
          color: 'var(--fc-accent-700, #0f766e)',
        }}
      >
        {label}
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={duplicate}
      disabled={busy}
      aria-busy={busy}
      className="inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[11.5px] font-semibold transition-colors disabled:opacity-60"
      style={{
        borderColor: 'rgba(56,160,158,0.35)',
        background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
        color: 'var(--fc-accent-700, #0f766e)',
      }}
    >
      {label}
    </button>
  )
}
