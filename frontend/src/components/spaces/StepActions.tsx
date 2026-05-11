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
}

export default function StepActions({
  spaceSlug,
  pathwaySlug,
  stepSlug,
  isCompleted: initialCompleted,
  initialNotes,
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
    <div className="mt-12 pt-10">

      {/* Reflection space */}
      <div className="mb-8">
        <div className="mb-1 h-px w-6 bg-gold-400" />
        <label className="mb-1 block font-serif text-lg text-navy-800" htmlFor="step-notes">
          Your reflection
        </label>
        <p className="mb-4 text-sm text-slate-400">
          Private to you. Write as much or as little as feels right.
        </p>
        <textarea
          id="step-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={6}
          placeholder="What are you noticing? What feels true right now?"
          className="w-full resize-none rounded-xl border border-border bg-white px-5 py-4 text-[15px] leading-relaxed text-navy-900 placeholder:text-slate-300 focus:border-teal-300 focus:outline-none focus:ring-2 focus:ring-teal-100 transition-colors"
          style={{ fontFamily: 'inherit' }}
        />
        <div className="mt-2.5 flex items-center justify-between">
          <button
            onClick={handleSaveNotes}
            disabled={!notes.trim()}
            className="text-xs text-slate-400 underline-offset-2 transition-colors hover:text-teal-600 hover:underline disabled:cursor-not-allowed disabled:opacity-30"
          >
            Save notes
          </button>
          {notesSaved && (
            <span className="text-xs text-teal-500">Saved.</span>
          )}
        </div>
      </div>

      {/* Completion */}
      <div>
        {completed ? (
          <div
            className={[
              'rounded-xl border px-6 py-5 transition-all duration-500',
              justCompleted
                ? 'border-teal-200 bg-teal-50/60'
                : 'border-border bg-surface',
            ].join(' ')}
          >
            <div className="flex items-center gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-teal-100">
                <span className="text-sm text-teal-600">✓</span>
              </div>
              <div>
                <p className="text-sm font-medium text-teal-700">Step complete</p>
                {justCompleted && (
                  <p className="text-xs text-teal-500 mt-0.5">
                    Well done. Keep going when you&apos;re ready.
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
