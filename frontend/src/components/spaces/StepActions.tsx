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
      setTimeout(() => setNotesSaved(false), 2000)
    }
  }

  return (
    <div className="mt-10 border-t border-border pt-8">
      <div className="mb-6">
        <label className="mb-2 block text-sm font-medium text-navy-700">
          Your notes
        </label>
        <p className="mb-3 text-xs text-slate-400">
          Private to you. Write as much or as little as you like.
        </p>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={5}
          placeholder="What are you noticing?"
          className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm leading-relaxed text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100 resize-none"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            onClick={handleSaveNotes}
            disabled={!notes.trim()}
            className="text-xs text-slate-400 underline-offset-2 hover:text-teal-600 hover:underline disabled:cursor-not-allowed disabled:opacity-40"
          >
            Save notes
          </button>
          {notesSaved && (
            <span className="text-xs text-teal-500">Saved</span>
          )}
        </div>
      </div>

      <div>
        {completed ? (
          <div className="flex items-center gap-2 text-sm font-medium text-teal-600">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-100 text-xs">
              ✓
            </span>
            Step complete
          </div>
        ) : (
          <button
            onClick={handleComplete}
            disabled={isPending}
            className="rounded-full bg-teal-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-teal-600 disabled:opacity-60"
          >
            {isPending ? 'Saving…' : 'Mark complete'}
          </button>
        )}
      </div>
    </div>
  )
}
