'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function CreatePathwayButton({ slug }: { slug: string }) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    setCreating(true)
    setError(null)
    try {
      const res = await fetch(`/api/creator/spaces/${slug}/pathways`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim() }),
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      router.push(`/creator/spaces/${slug}/pathways/${data.slug}`)
      router.refresh()
    } catch {
      setError('Could not create pathway. Try again.')
      setCreating(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="shrink-0 rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:opacity-90"
      >
        + New pathway
      </button>
    )
  }

  return (
    <form onSubmit={handleCreate} className="flex shrink-0 items-center gap-2">
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Pathway title"
        className="rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
      />
      <button
        type="submit"
        disabled={creating || !title.trim()}
        className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 hover:opacity-90"
      >
        {creating ? '…' : 'Create'}
      </button>
      <button
        type="button"
        onClick={() => { setOpen(false); setTitle(''); setError(null) }}
        className="text-sm text-slate-400 hover:text-slate-600"
      >
        Cancel
      </button>
      {error && <span className="text-xs text-red-500">{error}</span>}
    </form>
  )
}
