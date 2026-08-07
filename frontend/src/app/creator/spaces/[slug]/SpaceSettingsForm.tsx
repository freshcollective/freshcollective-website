'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

interface SpaceData {
  slug: string
  name: string
  tagline: string | null
  description: string | null
  is_public: boolean
  status: string
}

const STATUS_OPTIONS = [
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'archived', label: 'Archived' },
]

export default function SpaceSettingsForm({ space }: { space: SpaceData }) {
  const router = useRouter()
  const [name, setName] = useState(space.name)
  const [tagline, setTagline] = useState(space.tagline ?? '')
  const [description, setDescription] = useState(space.description ?? '')
  const [isPublic, setIsPublic] = useState(space.is_public)
  const [status, setStatus] = useState(space.status)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name, tagline: tagline || null, description: description || null, is_public: isPublic, status }),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : detail } catch {}
        throw new Error(detail)
      }
      setSaved(true)
      router.refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800">Space name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800">Tagline</label>
        <input
          value={tagline}
          onChange={(e) => setTagline(e.target.value)}
          placeholder="A short phrase that captures the spirit of this collective"
          className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={4}
          placeholder="What will members find here? What is the intention of this collective?"
          className="w-full resize-none rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
        />
      </div>

      <div>
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

      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={isPublic}
          onClick={() => setIsPublic((p) => !p)}
          className={[
            'relative h-5 w-9 rounded-full transition-colors',
            isPublic ? 'bg-teal-500' : 'bg-slate-200',
          ].join(' ')}
        >
          <span
            className={[
              'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
              isPublic ? 'translate-x-4' : 'translate-x-0.5',
            ].join(' ')}
          />
        </button>
        <span className="text-sm text-black">
          {isPublic ? 'Publicly visible' : 'Members only'}
        </span>
      </div>

      <div className="flex items-center gap-4 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-navy-900 px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        {saved && <span className="text-sm text-teal-600">Saved</span>}
        {error && <span className="text-sm text-red-500">{error}</span>}
      </div>
    </form>
  )
}
