'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import type { CreatorEvent } from '@/types/platform'

const LOCATION_TYPES = [
  { value: 'zoom', label: 'Zoom / online' },
  { value: 'in_person', label: 'In person' },
  { value: 'async_recorded', label: 'Recorded / async' },
]

function toLocalDatetime(iso: string) {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function EventForm({
  spaceSlug,
  event,
}: {
  spaceSlug: string
  event?: CreatorEvent
}) {
  const router = useRouter()
  const isEdit = !!event

  const [title, setTitle] = useState(event?.title ?? '')
  const [description, setDescription] = useState(event?.description ?? '')
  const [startsAt, setStartsAt] = useState(event ? toLocalDatetime(event.starts_at) : '')
  const [endsAt, setEndsAt] = useState(event?.ends_at ? toLocalDatetime(event.ends_at) : '')
  const [locationType, setLocationType] = useState<string>(event?.location_type ?? 'zoom')
  const [locationUrl, setLocationUrl] = useState(event?.location_url ?? '')
  const [recordingUrl, setRecordingUrl] = useState(event?.recording_url ?? '')
  const [isPublished, setIsPublished] = useState(event?.is_published ?? false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const url = isEdit
        ? `/api/creator/spaces/${spaceSlug}/events/${event!.id}`
        : `/api/creator/spaces/${spaceSlug}/events`
      const method = isEdit ? 'PATCH' : 'POST'
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          description: description || null,
          starts_at: new Date(startsAt).toISOString(),
          ends_at: endsAt ? new Date(endsAt).toISOString() : null,
          location_type: locationType,
          location_url: locationUrl || null,
          recording_url: recordingUrl || null,
          is_published: isPublished,
        }),
      })
      if (!res.ok) throw new Error()
      router.push(`/creator/spaces/${spaceSlug}/events`)
      router.refresh()
    } catch {
      setError('Could not save event. Try again.')
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
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
          placeholder="What will happen in this session?"
          className="w-full resize-none rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
        />
      </div>

      <div className="flex gap-4">
        <div className="flex-1">
          <label className="mb-1.5 block text-sm font-medium text-navy-800">Starts</label>
          <input
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            required
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>
        <div className="flex-1">
          <label className="mb-1.5 block text-sm font-medium text-navy-800">Ends</label>
          <input
            type="datetime-local"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800">Location type</label>
        <div className="flex flex-wrap gap-2">
          {LOCATION_TYPES.map((lt) => (
            <button
              key={lt.value}
              type="button"
              onClick={() => setLocationType(lt.value)}
              className={[
                'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                locationType === lt.value
                  ? 'border-navy-900 bg-navy-900 text-white'
                  : 'border-border text-slate-500 hover:border-slate-400 hover:text-navy-700',
              ].join(' ')}
            >
              {lt.label}
            </button>
          ))}
        </div>
      </div>

      {locationType !== 'in_person' && (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800">
            {locationType === 'zoom' ? 'Zoom link' : 'Recording URL'}
          </label>
          <input
            type="url"
            value={locationType === 'zoom' ? locationUrl : recordingUrl}
            onChange={(e) =>
              locationType === 'zoom' ? setLocationUrl(e.target.value) : setRecordingUrl(e.target.value)
            }
            placeholder="https://…"
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>
      )}

      {locationType === 'in_person' && (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800">Location details</label>
          <input
            value={locationUrl}
            onChange={(e) => setLocationUrl(e.target.value)}
            placeholder="Address or venue name"
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={isPublished}
          onClick={() => setIsPublished((p) => !p)}
          className={[
            'relative h-5 w-9 rounded-full transition-colors',
            isPublished ? 'bg-teal-500' : 'bg-slate-200',
          ].join(' ')}
        >
          <span
            className={[
              'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
              isPublished ? 'translate-x-4' : 'translate-x-0.5',
            ].join(' ')}
          />
        </button>
        <span className="text-sm text-slate-600">{isPublished ? 'Published' : 'Draft'}</span>
      </div>

      <div className="flex items-center gap-4 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-navy-900 px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create event'}
        </button>
        {error && <span className="text-sm text-red-500">{error}</span>}
      </div>
    </form>
  )
}
