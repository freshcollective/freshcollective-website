'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { CreatorStep } from '@/types/platform'

const TYPE_LABELS: Record<string, string> = {
  text: 'Text',
  video: 'Video',
  reflection: 'Reflection',
  exercise: 'Exercise',
  audio: 'Audio',
}

export default function StepList({
  steps: initialSteps,
  spaceSlug,
  pathwaySlug,
}: {
  steps: CreatorStep[]
  spaceSlug: string
  pathwaySlug: string
}) {
  const router = useRouter()
  const [steps, setSteps] = useState(initialSteps)
  const [addingTitle, setAddingTitle] = useState('')
  const [addingOpen, setAddingOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [moving, setMoving] = useState<string | null>(null)

  const base = `/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}`

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!addingTitle.trim()) return
    setCreating(true)
    try {
      const res = await fetch(`${base}/steps`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: addingTitle.trim(), content_type: 'text' }),
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      setSteps((prev) => [...prev, data])
      setAddingTitle('')
      setAddingOpen(false)
      router.push(`/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${data.slug}`)
    } catch {
      // silent — user can retry
    } finally {
      setCreating(false)
    }
  }

  async function move(index: number, dir: -1 | 1) {
    const next = [...steps]
    const other = index + dir
    if (other < 0 || other >= next.length) return
    ;[next[index], next[other]] = [next[other], next[index]]
    setSteps(next)
    setMoving(next[index].id)
    try {
      await fetch(`${base}/steps/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: next.map((s) => s.id) }),
      })
    } finally {
      setMoving(null)
    }
  }

  async function deleteStep(step: CreatorStep) {
    if (!confirm(`Delete "${step.title}"? This cannot be undone.`)) return
    const res = await fetch(`${base}/steps/${step.slug}`, { method: 'DELETE' })
    if (res.ok) {
      setSteps((prev) => prev.filter((s) => s.id !== step.id))
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {steps.length === 0 && !addingOpen && (
        <p className="text-sm text-slate-400">No steps yet. Add the first one.</p>
      )}

      {steps.map((step, i) => (
        <div key={step.id} className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
          <div className="flex flex-col gap-0.5">
            <button
              onClick={() => move(i, -1)}
              disabled={i === 0 || moving === step.id}
              className="text-slate-300 hover:text-slate-500 disabled:opacity-20"
              aria-label="Move up"
            >
              ↑
            </button>
            <button
              onClick={() => move(i, 1)}
              disabled={i === steps.length - 1 || moving === step.id}
              className="text-slate-300 hover:text-slate-500 disabled:opacity-20"
              aria-label="Move down"
            >
              ↓
            </button>
          </div>
          <span className="w-5 shrink-0 text-center text-sm text-slate-300">{i + 1}</span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-navy-900">{step.title}</p>
            <p className="text-xs text-slate-400">
              {TYPE_LABELS[step.content_type] ?? step.content_type}
              {step.estimated_minutes ? ` · ${step.estimated_minutes} min` : ''}
              {!step.is_required ? ' · optional' : ''}
            </p>
          </div>
          <Link
            href={`/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${step.slug}`}
            className="shrink-0 rounded-lg border border-navy-200 px-3 py-1.5 text-xs font-medium text-navy-700 hover:border-navy-400 hover:bg-navy-50"
          >
            Edit
          </Link>
          <button
            onClick={() => deleteStep(step)}
            className="shrink-0 text-xs text-slate-300 hover:text-red-400"
            aria-label="Delete step"
          >
            ✕
          </button>
        </div>
      ))}

      {addingOpen ? (
        <form onSubmit={handleAdd} className="flex items-center gap-2 pt-1">
          <input
            autoFocus
            value={addingTitle}
            onChange={(e) => setAddingTitle(e.target.value)}
            placeholder="Step title"
            className="flex-1 rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
          <button
            type="submit"
            disabled={creating || !addingTitle.trim()}
            className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 hover:opacity-90"
          >
            {creating ? '…' : 'Add'}
          </button>
          <button
            type="button"
            onClick={() => { setAddingOpen(false); setAddingTitle('') }}
            className="text-sm text-slate-400 hover:text-slate-600"
          >
            Cancel
          </button>
        </form>
      ) : (
        <button
          onClick={() => setAddingOpen(true)}
          className="mt-1 self-start text-sm text-teal-600 hover:underline"
        >
          + Add step
        </button>
      )}
    </div>
  )
}
