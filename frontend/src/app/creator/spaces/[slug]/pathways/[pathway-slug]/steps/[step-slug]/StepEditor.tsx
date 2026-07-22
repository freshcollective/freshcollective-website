'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { CreatorStep } from '@/types/platform'

const CONTENT_TYPES = [
  { value: 'text', label: 'Text' },
  { value: 'video', label: 'Video' },
  { value: 'audio', label: 'Audio' },
  { value: 'reflection', label: 'Reflection' },
  { value: 'exercise', label: 'Exercise' },
]

export default function StepEditor({
  step,
  spaceSlug,
  pathwaySlug,
}: {
  step: CreatorStep
  spaceSlug: string
  pathwaySlug: string
}) {
  const router = useRouter()
  const [title, setTitle] = useState(step.title)
  const [contentType, setContentType] = useState(step.content_type)
  const [contentBody, setContentBody] = useState(step.content_body ?? '')
  const [contentUrl, setContentUrl] = useState(step.content_url ?? '')
  const [estimatedMinutes, setEstimatedMinutes] = useState(step.estimated_minutes?.toString() ?? '')
  const [isRequired, setIsRequired] = useState(step.is_required)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const showBody = ['text', 'reflection', 'exercise'].includes(contentType)
  const showUrl = ['video', 'audio'].includes(contentType)

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${step.slug}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            title,
            content_type: contentType,
            content_body: showBody ? contentBody || null : null,
            content_url: showUrl ? contentUrl || null : null,
            estimated_minutes: estimatedMinutes ? parseInt(estimatedMinutes) : null,
            is_required: isRequired,
          }),
        },
      )
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : detail } catch {}
        throw new Error(detail)
      }
      setSaved(true)
      router.refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSave} className="flex flex-col gap-8">
      {/* Title */}
      <div>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          placeholder="Step title"
          className="w-full border-0 border-b border-border bg-transparent pb-2 font-serif text-2xl text-navy-900 placeholder-slate-300 focus:outline-none focus:border-navy-300"
        />
      </div>

      {/* Content type selector */}
      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-black">Content type</p>
        <div className="flex flex-wrap gap-2">
          {CONTENT_TYPES.map((ct) => (
            <button
              key={ct.value}
              type="button"
              onClick={() => setContentType(ct.value as CreatorStep['content_type'])}
              className={[
                'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                contentType === ct.value
                  ? 'border-navy-900 bg-navy-900 text-white'
                  : 'border-border text-black hover:border-slate-400 hover:text-navy-700',
              ].join(' ')}
            >
              {ct.label}
            </button>
          ))}
        </div>
      </div>

      {/* Body content */}
      {showBody && (
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-black">Content</p>
          <textarea
            value={contentBody}
            onChange={(e) => setContentBody(e.target.value)}
            rows={16}
            placeholder="Write the step content here. Use plain text — markdown is supported."
            className="w-full resize-none rounded-xl border border-border bg-white px-5 py-4 font-mono text-sm leading-relaxed text-navy-900 placeholder-slate-300 focus:outline-none focus:ring-1 focus:ring-navy-200"
          />
        </div>
      )}

      {/* URL for video/audio */}
      {showUrl && (
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-black">
            {contentType === 'video' ? 'Video URL' : 'Audio URL'}
          </p>
          <input
            type="url"
            value={contentUrl}
            onChange={(e) => setContentUrl(e.target.value)}
            placeholder={contentType === 'video' ? 'https://vimeo.com/…' : 'https://…'}
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>
      )}

      {/* Metadata row */}
      <div className="flex flex-wrap items-center gap-6 rounded-xl border border-border bg-surface px-5 py-4">
        <div>
          <label className="mb-1 block text-xs text-black">Est. minutes</label>
          <input
            type="number"
            min={1}
            max={999}
            value={estimatedMinutes}
            onChange={(e) => setEstimatedMinutes(e.target.value)}
            placeholder="—"
            className="w-20 rounded-lg border border-border bg-white px-3 py-1.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={isRequired}
            onClick={() => setIsRequired((p) => !p)}
            className={[
              'relative h-5 w-9 rounded-full transition-colors',
              isRequired ? 'bg-teal-500' : 'bg-slate-200',
            ].join(' ')}
          >
            <span
              className={[
                'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
                isRequired ? 'translate-x-4' : 'translate-x-0.5',
              ].join(' ')}
            />
          </button>
          <span className="text-sm text-black">Required</span>
        </div>
      </div>

      {/* Save */}
      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-navy-900 px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save step'}
        </button>
        {saved && <span className="text-sm text-teal-600">Saved</span>}
        {error && <span className="text-sm text-red-500">{error}</span>}
      </div>

    </form>
  )
}
