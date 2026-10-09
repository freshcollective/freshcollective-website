'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import PrivateResponseArea from './PrivateResponseArea'

interface StepActionsProps {
  spaceSlug: string
  pathwaySlug: string
  stepSlug: string
  isCompleted: boolean
  initialNotes: string | null
  reflectionEnabled?: boolean
}

export default function StepActions({
  spaceSlug,
  pathwaySlug,
  stepSlug,
  isCompleted: initialCompleted,
  initialNotes,
  reflectionEnabled = true,
}: StepActionsProps) {
  const router = useRouter()
  const [notes, setNotes] = useState(initialNotes ?? '')
  const [completed, setCompleted] = useState(initialCompleted)
  const [justCompleted, setJustCompleted] = useState(false)
  const [isPending, startTransition] = useTransition()

  const base = `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}`

  async function handleComplete() {
    const res = await fetch(apiUrl(`${base}/complete`), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reflection_text: notes || null }),
    })
    if (res.ok) {
      setCompleted(true)
      setJustCompleted(true)
      startTransition(() => router.refresh())
    }
  }

  // Returns whether it saved. The "Saved." dwell and the failure
  // message now live in PrivateResponseArea, so both this panel and
  // Exercise blocks report the same thing the same way. The request
  // itself — endpoint, field, credentials — is unchanged.
  async function handleSaveNotes(): Promise<boolean> {
    const res = await fetch(apiUrl(`${base}/notes`), {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reflection_text: notes }),
    })
    return res.ok
  }

  return (
    <div className="mt-14 pt-8">

      {/* ── Pause & Reflect — a gentle pause, not a form ── */}
      {reflectionEnabled && (
        <section
          className="mb-10 rounded-2xl px-6 py-7 md:px-8 md:py-8"
          style={{
            // The rest of this section already themed off the
            // Collective's palette — the button, the "Private to you"
            // line, the text area's border — while the panel it all sat
            // in stayed platform teal. In a Collective whose palette is
            // warm, that read as a stray cool box. Fallbacks are the
            // previous literals, so a Collective with no palette set
            // looks exactly as it did.
            background: 'var(--fc-accent-tint, rgba(56,160,158,0.045))',
            border: '1px solid var(--fc-accent-line, rgba(56,160,158,0.14))',
          }}
        >
          <PrivateResponseArea
            textareaId="step-notes"
            label={<><span aria-hidden="true">🌿</span>{' '}<span>Pause &amp; Reflect</span></>}
            intro="Take a moment before moving on."
            value={notes}
            onChange={setNotes}
            onSave={handleSaveNotes}
            saveLabel="Save reflection"
            placeholder="Write as much or as little as feels right."
            rows={6}
          />
        </section>
      )}

      {/* ── Completion moment — quiet encouragement ── */}
      <div>
        {completed ? (
          <div
            className={[
              'rounded-2xl border px-6 py-5 transition-all duration-500',
              justCompleted
                ? 'border-[color:var(--fc-accent-line,rgba(56,160,158,0.30))] bg-[color:var(--fc-accent-tint,rgba(56,160,158,0.06))]'
                : 'border-border bg-surface',
            ].join(' ')}
          >
            <div className="flex items-start gap-3.5">
              <div
                className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
                style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.16))' }}
              >
                <span
                  className="text-[14px]"
                  style={{ color: 'var(--fc-accent, #0f766e)' }}
                  aria-hidden="true"
                >✓</span>
              </div>
              <div>
                <p className="font-serif text-[17px] leading-snug text-navy-900">
                  Step complete
                </p>
                {justCompleted ? (
                  <p className="mt-1 text-[13.5px] leading-relaxed text-black">
                    Beautiful. Take a moment before continuing.
                  </p>
                ) : (
                  <p className="mt-1 text-[13px] text-black">
                    You&apos;re ready whenever you are for the next step.
                  </p>
                )}
              </div>
            </div>
          </div>
        ) : (
          <button
            onClick={handleComplete}
            disabled={isPending}
            className="rounded-xl bg-navy-900 px-7 py-3 text-sm font-medium text-white transition-colors hover:bg-navy-800 disabled:opacity-60"
          >
            {isPending ? 'Saving…' : 'Mark this step complete'}
          </button>
        )}
      </div>

    </div>
  )
}
