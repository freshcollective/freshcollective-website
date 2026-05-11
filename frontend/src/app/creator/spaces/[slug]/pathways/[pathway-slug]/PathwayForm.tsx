'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

interface PathwayData {
  slug: string
  title: string
  description: string | null
  status: string
  is_sequential: boolean
}

const STATUS_OPTIONS = [
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'coming_soon', label: 'Coming soon' },
  { value: 'archived', label: 'Archived' },
]

export default function PathwayForm({
  pathway,
  spaceSlug,
}: {
  pathway: PathwayData
  spaceSlug: string
}) {
  const router = useRouter()
  const [title, setTitle] = useState(pathway.title)
  const [description, setDescription] = useState(pathway.description ?? '')
  const [status, setStatus] = useState(pathway.status)
  const [isSequential, setIsSequential] = useState(pathway.is_sequential)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const res = await fetch(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, description: description || null, status, is_sequential: isSequential }),
      })
      if (!res.ok) throw new Error()
      setSaved(true)
      router.refresh()
    } catch {
      setError('Could not save. Try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800">Title</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="What is the intention of this pathway?"
          className="w-full resize-none rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
        />
      </div>

      <div className="flex items-center gap-6">
        <div className="flex-1">
          <label className="mb-1.5 block text-sm font-medium text-navy-800">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-3 pt-5">
          <button
            type="button"
            role="switch"
            aria-checked={isSequential}
            onClick={() => setIsSequential((p) => !p)}
            className={[
              'relative h-5 w-9 rounded-full transition-colors',
              isSequential ? 'bg-teal-500' : 'bg-slate-200',
            ].join(' ')}
          >
            <span
              className={[
                'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
                isSequential ? 'translate-x-4' : 'translate-x-0.5',
              ].join(' ')}
            />
          </button>
          <span className="text-sm text-slate-600">Sequential</span>
        </div>
      </div>

      <div className="flex items-center gap-4 pt-1">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-navy-900 px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-sm text-teal-600">Saved</span>}
        {error && <span className="text-sm text-red-500">{error}</span>}
      </div>
    </form>
  )
}
