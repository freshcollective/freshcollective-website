'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

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
  const [notesSaved, setNotesSaved] = useState(false)
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

  async function handleSaveNotes() {
    const res = await fetch(apiUrl(`${base}/notes`), {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reflection_text: notes }),
    })
    if (res.ok) {
      setNotesSaved(true)
      setTimeout(() => setNotesSaved(false), 2500)
    }
  }

  return (
    <div className="mt-14 pt-8">

      {/* ── Pause & Reflect — a gentle pause, not a form ── */}
      {reflectionEnabled && (
        <section
          className="mb-10 rounded-2xl px-6 py-7 md:px-8 md:py-8"
          style={{
            background: 'rgba(56,160,158,0.045)',
            border: '1px solid rgba(56,160,158,0.14)',
          }}
        >
          <div className="mb-4">
            <label
              htmlFor="step-notes"
              className="font-serif text-[20px] leading-snug text-navy-900"
            >
              <span aria-hidden="true">🌿</span>{' '}
              <span>Pause &amp; Reflect</span>
            </label>
            <p
              className="mt-1 text-[12px] font-medium uppercase tracking-[0.14em]"
              style={{ color: 'var(--fc-accent, #0f766e)' }}
            >
              Private to you
            </p>
          </div>

          <p className="mb-5 text-[15px] leading-relaxed text-navy-900/80">
            Take a moment before moving on.
          </p>

          <ul className="mb-5 space-y-1.5 text-[14.5px] leading-relaxed text-black">
            <li>What stood out?</li>
            <li>What challenged you?</li>
            <li>What feels important enough to remember?</li>
          </ul>

          <textarea
            id="step-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={6}
            placeholder="Write as much or as little as feels right."
            className="w-full resize-none rounded-xl border bg-white px-5 py-4 text-[15px] leading-relaxed text-navy-900 placeholder:text-slate-300 transition-colors focus:outline-none focus:ring-2"
            style={{
              borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.20))',
              fontFamily: 'inherit',
            }}
          />
          <div className="mt-3 flex items-center justify-between">
            <button
              onClick={handleSaveNotes}
              disabled={!notes.trim()}
              className="rounded-full px-4 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              style={{
                background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)',
              }}
            >
              Save reflection
            </button>
            {notesSaved && (
              <span
                className="text-[12px]"
                style={{ color: 'var(--fc-accent, #0f766e)' }}
              >
                Saved.
              </span>
            )}
          </div>
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
