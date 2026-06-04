'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { CreatorEvent } from '@/types/platform'

const LOCATION_TYPES = [
  { value: 'zoom', label: 'Zoom / online' },
  { value: 'in_person', label: 'In person' },
  { value: 'async_recorded', label: 'Recorded / async' },
]

const WEEKDAYS = [
  { value: 0, label: 'Sun' },
  { value: 1, label: 'Mon' },
  { value: 2, label: 'Tue' },
  { value: 3, label: 'Wed' },
  { value: 4, label: 'Thu' },
  { value: 5, label: 'Fri' },
  { value: 6, label: 'Sat' },
]

function toLocalDatetime(iso: string) {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={[
        'relative h-5 w-9 rounded-full transition-colors',
        checked ? 'bg-teal-500' : 'bg-slate-200',
      ].join(' ')}
    >
      <span
        className={[
          'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-4' : 'translate-x-0.5',
        ].join(' ')}
      />
    </button>
  )
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

  // Core fields
  const [title, setTitle] = useState(event?.title ?? '')
  const [description, setDescription] = useState(event?.description ?? '')
  const [startsAt, setStartsAt] = useState(event ? toLocalDatetime(event.starts_at) : '')
  const [endsAt, setEndsAt] = useState(event?.ends_at ? toLocalDatetime(event.ends_at) : '')
  const [locationType, setLocationType] = useState<string>(event?.location_type ?? 'zoom')
  const [locationUrl, setLocationUrl] = useState(event?.location_url ?? '')
  const [recordingUrl, setRecordingUrl] = useState(event?.recording_url ?? '')
  const [isPublished, setIsPublished] = useState(event?.is_published ?? false)
  const [isPublic, setIsPublic] = useState(event?.is_public ?? false)

  // Booking
  const [requiresBooking, setRequiresBooking] = useState(event?.requires_booking ?? false)
  const [capacity, setCapacity] = useState<string>(event?.capacity != null ? String(event.capacity) : '')
  const [bookingClosesAt, setBookingClosesAt] = useState(
    event?.booking_closes_at ? toLocalDatetime(event.booking_closes_at) : ''
  )
  const [bookingNote, setBookingNote] = useState(event?.booking_note ?? '')

  // Recurrence (new events only)
  const [isRecurring, setIsRecurring] = useState(false)
  const [selectedDays, setSelectedDays] = useState<number[]>([])
  const [seriesLabel, setSeriesLabel] = useState('')
  const [endMode, setEndMode] = useState<'count' | 'date'>('count')
  const [endAfterN, setEndAfterN] = useState<string>('4')
  const [repeatUntil, setRepeatUntil] = useState<string>('')

  // Thumbnail (edit mode only)
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(event?.thumbnail_url ?? null)
  const [thumbnailUploading, setThumbnailUploading] = useState(false)
  const [thumbnailError, setThumbnailError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggleDay(day: number) {
    setSelectedDays(prev =>
      prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day]
    )
  }

  async function handleThumbnailUpload(file: File) {
    setThumbnailUploading(true)
    setThumbnailError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${event!.id}/thumbnail`), {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setThumbnailUrl(data.thumbnail_url)
    } catch {
      setThumbnailError('Upload failed. Please try again.')
    } finally {
      setThumbnailUploading(false)
    }
  }

  async function handleThumbnailRemove() {
    setThumbnailUploading(true)
    setThumbnailError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${event!.id}/thumbnail`), {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setThumbnailUrl(null)
    } catch {
      setThumbnailError('Could not remove image.')
    } finally {
      setThumbnailUploading(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const basePayload = {
        title,
        description: description || null,
        starts_at: new Date(startsAt).toISOString(),
        ends_at: endsAt ? new Date(endsAt).toISOString() : null,
        location_type: locationType,
        location_url: locationUrl || null,
        recording_url: recordingUrl || null,
        is_published: isPublished,
        is_public: isPublic,
        requires_booking: requiresBooking,
        capacity: capacity ? parseInt(capacity, 10) : null,
        booking_closes_at: bookingClosesAt ? new Date(bookingClosesAt).toISOString() : null,
        booking_note: bookingNote || null,
      }

      if (!isEdit && isRecurring) {
        // Bulk creation endpoint
        if (selectedDays.length === 0) {
          throw new Error('Select at least one day of the week.')
        }
        const recurrence: Record<string, unknown> = {
          pattern: 'weekly',
          days_of_week: selectedDays,
          series_label: seriesLabel || null,
        }
        if (endMode === 'count') {
          recurrence.end_after_n = parseInt(endAfterN, 10)
        } else {
          if (!repeatUntil) throw new Error('Enter an end date.')
          recurrence.repeat_until = new Date(repeatUntil).toISOString()
        }
        const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/bulk`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ ...basePayload, recurrence }),
        })
        if (!res.ok) {
          let detail = `HTTP ${res.status}`
          try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : detail } catch {}
          throw new Error(detail)
        }
      } else {
        // Single event create or edit
        const url = apiUrl(isEdit
          ? `/api/creator/spaces/${spaceSlug}/events/${event!.id}`
          : `/api/creator/spaces/${spaceSlug}/events`)
        const method = isEdit ? 'PATCH' : 'POST'
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(basePayload),
        })
        if (!res.ok) {
          let detail = `HTTP ${res.status}`
          try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : detail } catch {}
          throw new Error(detail)
        }
      }

      router.push(`/creator/spaces/${spaceSlug}/events`)
      router.refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save event.')
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
          <label className="mb-1.5 block text-sm font-medium text-navy-800">
            {isRecurring ? 'First session starts' : 'Starts'}
          </label>
          <input
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            required
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>
        <div className="flex-1">
          <label className="mb-1.5 block text-sm font-medium text-navy-800">
            {isRecurring ? 'Duration (ends)' : 'Ends'}
          </label>
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
        <Toggle checked={isPublished} onChange={setIsPublished} />
        <span className="text-sm text-slate-600">{isPublished ? 'Published' : 'Draft'}</span>
      </div>

      {/* ── Visibility section ── */}
      <div className="rounded-xl border border-border bg-slate-50/50 p-5">
        <p className="mb-3 text-sm font-semibold text-navy-800">Visibility</p>
        <div className="flex items-start gap-3">
          <Toggle checked={isPublic} onChange={setIsPublic} />
          <div>
            <p className="text-sm font-medium text-navy-800">Public preview</p>
            <p className="text-xs text-slate-400">
              Non-members can see this gathering. They must join to book a spot.
            </p>
          </div>
        </div>
      </div>

      {/* ── Recurrence section (new events only) ── */}
      {!isEdit && (
        <div className="rounded-xl border border-border bg-slate-50/50 p-5">
          <div className="mb-4 flex items-center gap-3">
            <Toggle checked={isRecurring} onChange={setIsRecurring} />
            <span className="text-sm font-medium text-navy-800">Recurring series</span>
            <span className="text-xs text-slate-400">Repeat this session weekly</span>
          </div>

          {isRecurring && (
            <div className="flex flex-col gap-4">
              <div>
                <p className="mb-2 text-sm font-medium text-navy-800">Repeats on</p>
                <div className="flex flex-wrap gap-2">
                  {WEEKDAYS.map((d) => (
                    <button
                      key={d.value}
                      type="button"
                      onClick={() => toggleDay(d.value)}
                      className={[
                        'rounded-full border px-3 py-1 text-sm transition-colors',
                        selectedDays.includes(d.value)
                          ? 'border-teal-600 bg-teal-600 text-white'
                          : 'border-border text-slate-500 hover:border-teal-400 hover:text-teal-700',
                      ].join(' ')}
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-2 text-sm font-medium text-navy-800">Series name</p>
                <input
                  value={seriesLabel}
                  onChange={(e) => setSeriesLabel(e.target.value)}
                  placeholder="e.g. Weekly Accountability Call"
                  className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
                />
              </div>

              <div>
                <p className="mb-2 text-sm font-medium text-navy-800">Ends</p>
                <div className="mb-3 flex gap-3">
                  <button
                    type="button"
                    onClick={() => setEndMode('count')}
                    className={[
                      'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                      endMode === 'count'
                        ? 'border-navy-900 bg-navy-900 text-white'
                        : 'border-border text-slate-500 hover:border-slate-400',
                    ].join(' ')}
                  >
                    After N sessions
                  </button>
                  <button
                    type="button"
                    onClick={() => setEndMode('date')}
                    className={[
                      'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                      endMode === 'date'
                        ? 'border-navy-900 bg-navy-900 text-white'
                        : 'border-border text-slate-500 hover:border-slate-400',
                    ].join(' ')}
                  >
                    On a date
                  </button>
                </div>
                {endMode === 'count' ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min="2"
                      max="52"
                      value={endAfterN}
                      onChange={(e) => setEndAfterN(e.target.value)}
                      className="w-24 rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
                    />
                    <span className="text-sm text-slate-500">sessions total</span>
                  </div>
                ) : (
                  <input
                    type="date"
                    value={repeatUntil}
                    onChange={(e) => setRepeatUntil(e.target.value)}
                    className="rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
                  />
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Thumbnail section (edit only) ── */}
      {isEdit && (
        <div className="rounded-xl border border-border bg-slate-50/50 p-5">
          <p className="mb-3 text-sm font-semibold text-navy-800">Cover image</p>
          {thumbnailUrl ? (
            <div className="flex flex-col gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={thumbnailUrl}
                alt="Event thumbnail"
                className="h-36 w-full rounded-lg object-cover"
              />
              <div className="flex gap-3">
                <label className={[
                  'cursor-pointer rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-slate-400',
                  thumbnailUploading ? 'opacity-50 cursor-not-allowed' : '',
                ].join(' ')}>
                  Replace
                  <input
                    type="file"
                    accept="image/*"
                    className="sr-only"
                    disabled={thumbnailUploading}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) handleThumbnailUpload(f)
                    }}
                  />
                </label>
                <button
                  type="button"
                  disabled={thumbnailUploading}
                  onClick={handleThumbnailRemove}
                  className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:border-red-300 disabled:opacity-50"
                >
                  Remove
                </button>
              </div>
              {thumbnailError && <p className="text-xs text-red-500">{thumbnailError}</p>}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <label className={[
                'flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-white px-4 py-6 text-center transition-colors hover:border-slate-400',
                thumbnailUploading ? 'opacity-50 cursor-not-allowed' : '',
              ].join(' ')}>
                <span className="text-sm text-slate-400">
                  {thumbnailUploading ? 'Uploading…' : 'Click to upload an image'}
                </span>
                <span className="text-xs text-slate-300">JPG, PNG, WebP — max 5 MB</span>
                <input
                  type="file"
                  accept="image/*"
                  className="sr-only"
                  disabled={thumbnailUploading}
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) handleThumbnailUpload(f)
                  }}
                />
              </label>
              {thumbnailError && <p className="text-xs text-red-500">{thumbnailError}</p>}
            </div>
          )}
        </div>
      )}

      {/* ── Booking section ── */}
      <div className="rounded-xl border border-border bg-slate-50/50 p-5">
        <div className="mb-4 flex items-center gap-3">
          <Toggle checked={requiresBooking} onChange={setRequiresBooking} />
          <span className="text-sm font-medium text-navy-800">Require booking</span>
          <span className="text-xs text-slate-400">Members must book a spot to attend</span>
        </div>

        {requiresBooking && (
          <div className="flex flex-col gap-4">
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="mb-1.5 block text-sm font-medium text-navy-800">Capacity</label>
                <input
                  type="number"
                  min="1"
                  value={capacity}
                  onChange={(e) => setCapacity(e.target.value)}
                  placeholder="Unlimited"
                  className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
                />
              </div>
              <div className="flex-1">
                <label className="mb-1.5 block text-sm font-medium text-navy-800">Booking closes</label>
                <input
                  type="datetime-local"
                  value={bookingClosesAt}
                  onChange={(e) => setBookingClosesAt(e.target.value)}
                  className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
                />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-navy-800">Booking note</label>
              <input
                value={bookingNote}
                onChange={(e) => setBookingNote(e.target.value)}
                placeholder="e.g. You'll receive the Zoom link 24 hours before the session."
                className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
              />
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-navy-900 px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'Saving…' : isEdit ? 'Save changes' : isRecurring ? 'Create series' : 'Create event'}
        </button>
        {error && <span className="text-sm text-red-500">{error}</span>}
      </div>
    </form>
  )
}
