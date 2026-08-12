'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { CreatorEvent, CreatorGatheringSeriesSummary, CreatorPathway } from '@/types/platform'
import { Switch } from '@/components/platform'
import {
  GATHERING_TYPES,
  ATTENDANCE_FORMATS,
  ACCESS_TYPES,
  gatheringDescription,
  normaliseAccessType,
  type AccessTypeValue,
} from '@/lib/gatheringTypes'

// Access types that imply "booking is required" — invitation_only
// funnels every attendee through a caretaker add; paid_separately is
// intrinsically ticketed. We flip Require Booking on automatically and
// disable the toggle so a caretaker can't leave the Gathering in an
// impossible state (e.g. Paid without booking).
const ACCESS_REQUIRES_BOOKING: readonly AccessTypeValue[] = [
  'invitation_only',
  'paid_separately',
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

// Toggle used to live here inline; it duplicated (and mis-sized) the
// shared platform Switch. Replaced with `Switch` so thumb positioning
// stays consistent with the rest of the platform. The small local
// adapter below preserves the `(v: boolean) => void` callsite ergonomics
// without every caller reaching for `e.target.checked`.
function Toggle({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <Switch
      checked={checked}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
    />
  )
}

/**
 * Section — subtle editorial grouping used throughout the form.
 * Uppercase teal label + optional italic subtitle, then a spaced
 * column of controls. Kept understated so the whole form still reads
 * as one calm surface, not a wizard.
 */
function Section({
  title, subtitle, children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="border-t border-border pt-6 first:border-t-0 first:pt-0">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
        {title}
      </p>
      {subtitle && (
        <p className="mt-1 text-[13px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
          {subtitle}
        </p>
      )}
      <div className="mt-4 flex flex-col gap-4">
        {children}
      </div>
    </section>
  )
}

export default function EventForm({
  spaceSlug,
  event,
  pathways = [],
  series = [],
  initialSeriesId = null,
}: {
  spaceSlug: string
  event?: CreatorEvent
  pathways?: CreatorPathway[]
  /** Gathering Series in the current Collective. Used for the
   *  "Belongs to Series" picker and to enable the ``included_with_series``
   *  access type when relevant. */
  series?: CreatorGatheringSeriesSummary[]
  /** Preselect a Series id on the new-event form. Set when the
   *  Creator arrives via "New Gathering in Series" from the Series
   *  editor (query param). */
  initialSeriesId?: string | null
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

  // Gatherings 2.0 — identity + attendance + access.
  const [gatheringType, setGatheringType] = useState<string>(event?.gathering_type ?? 'other')
  const [attendanceFormat, setAttendanceFormat] = useState<'online' | 'in_person' | 'hybrid'>(
    (event?.attendance_format as 'online' | 'in_person' | 'hybrid' | undefined) ?? 'online'
  )
  const [venueName, setVenueName] = useState(event?.venue_name ?? '')
  const [venueAddress, setVenueAddress] = useState(event?.venue_address ?? '')
  const [accessInstructions, setAccessInstructions] = useState(event?.access_instructions ?? '')
  const [accessType, setAccessType] = useState<AccessTypeValue>(
    normaliseAccessType(event?.booking_access_type)
  )
  const [bookingRequiredPathwayId, setBookingRequiredPathwayId] = useState<string>(
    event?.booking_required_pathway_id ?? ''
  )
  // Semantic Gathering Series membership. Empty string means "not in
  // a Series". Attaching a Series here does NOT change the access
  // type — a Series may contain free, collective-included, and
  // series-pass Gatherings alongside each other; the Creator chooses.
  const [seriesId, setSeriesId] = useState<string>(
    event?.series_id ?? initialSeriesId ?? ''
  )

  // Booking
  const [requiresBooking, setRequiresBooking] = useState(event?.requires_booking ?? false)
  const [capacity, setCapacity] = useState<string>(event?.capacity != null ? String(event.capacity) : '')
  const [bookingClosesAt, setBookingClosesAt] = useState(
    event?.booking_closes_at ? toLocalDatetime(event.booking_closes_at) : ''
  )
  const [bookingNote, setBookingNote] = useState(event?.booking_note ?? '')

  // Standalone paid Gathering — decimal string in the form (e.g. "25.00");
  // converted to integer cents before submission. Empty on new events.
  const initialPriceDisplay =
    event?.ticket_price_cents != null ? (event.ticket_price_cents / 100).toFixed(2) : ''
  const [ticketPriceInput, setTicketPriceInput] = useState<string>(initialPriceDisplay)
  const [ticketCurrency, setTicketCurrency] = useState<string>(event?.ticket_currency ?? 'AUD')
  const [ticketPriceError, setTicketPriceError] = useState<string | null>(null)

  // Backend read-only summary; edit-lock indicators live here.
  const ticketSales = event?.ticket_sales ?? null
  const salesEnabled = ticketSales?.sales_enabled ?? false
  const hasCompletedSales = ticketSales?.has_completed_ticket_sales ?? false
  const hasActiveHolds = ticketSales?.has_active_payment_holds ?? false
  const accessTypeLocked = hasCompletedSales || hasActiveHolds
  const accessTypeLockReason = hasCompletedSales
    ? 'sales'
    : hasActiveHolds
      ? 'holds'
      : null

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

  // Which submission the caretaker asked for — set by the primary
  // buttons at the bottom of the form. `handleSubmit` derives
  // `is_published` from this, replacing the old toggle-style control.
  const [submitMode, setSubmitMode] = useState<'draft' | 'publish' | null>(null)

  // Conversation channel — new events only.
  const [createChannel, setCreateChannel] = useState(true)

  // Intelligent booking rules — some access types mandate booking, and
  // any capacity value only makes sense with booking on. We flip
  // Require Booking on automatically; the toggle is disabled when a
  // rule is forcing it so the state can't drift back out of sync.
  const capacityNum = capacity.trim() === '' ? null : Number(capacity)
  const capacityForcesBooking = capacityNum != null && capacityNum > 0
  const accessForcesBooking = ACCESS_REQUIRES_BOOKING.includes(accessType)
  const bookingRequiredByRules = capacityForcesBooking || accessForcesBooking

  useEffect(() => {
    if (bookingRequiredByRules && !requiresBooking) {
      setRequiresBooking(true)
    }
  }, [bookingRequiredByRules, requiresBooking])

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
      // Resolve the published flag from the primary button that was
      // pressed. On edit-save without a button choice (Enter key
      // etc.) we preserve the current published state.
      const targetPublished =
        submitMode === 'publish' ? true
        : submitMode === 'draft' ? false
        : isPublished

      // Standalone paid Gatherings: parse decimal price → integer cents.
      // Only require a price when actually publishing a paid Gathering;
      // drafts may save with the field empty.
      let ticketPriceCents: number | null = null
      if (accessType === 'paid_separately') {
        const trimmed = ticketPriceInput.trim()
        if (trimmed) {
          const parsed = Number(trimmed)
          if (!Number.isFinite(parsed) || parsed < 0) {
            setTicketPriceError('Enter a ticket price greater than $0.')
            setSaving(false)
            return
          }
          ticketPriceCents = Math.round(parsed * 100)
        }
        if (targetPublished && (!ticketPriceCents || ticketPriceCents <= 0)) {
          setTicketPriceError('Enter a ticket price greater than $0.')
          setSaving(false)
          return
        }
      }
      setTicketPriceError(null)

      // Out-of-range Series membership — a finite Series may
      // intentionally include intro/bonus/follow-up Gatherings, but
      // the Creator should own that decision. Confirm before saving
      // an Event whose start falls outside the chosen Series window.
      if (seriesId && startsAt) {
        const s = series.find((x) => x.id === seriesId)
        if (s) {
          const start = new Date(startsAt).getTime()
          const winStart = new Date(s.starts_at).getTime()
          const winEnd = s.ends_at ? new Date(s.ends_at).getTime() : null
          const outOfRange = Number.isFinite(start) && Number.isFinite(winStart) && (
            start < winStart || (winEnd != null && start > winEnd)
          )
          if (outOfRange) {
            const ok = window.confirm(
              `This Gathering falls outside the Series dates for "${s.title}". Add it anyway?`,
            )
            if (!ok) { setSaving(false); return }
          }
        }
      }

      const basePayload = {
        title,
        description: description || null,
        starts_at: new Date(startsAt).toISOString(),
        ends_at: endsAt ? new Date(endsAt).toISOString() : null,
        location_type: locationType,
        location_url: locationUrl || null,
        recording_url: recordingUrl || null,
        is_published: targetPublished,
        is_public: isPublic,
        requires_booking: requiresBooking,
        capacity: capacity ? parseInt(capacity, 10) : null,
        booking_closes_at: bookingClosesAt ? new Date(bookingClosesAt).toISOString() : null,
        booking_note: bookingNote || null,
        // Gatherings 2.0 vocabulary — see `lib/gatheringTypes.ts`.
        gathering_type: gatheringType,
        attendance_format: attendanceFormat,
        venue_name: venueName || null,
        venue_address: venueAddress || null,
        access_instructions: accessInstructions || null,
        booking_access_type: accessType,
        booking_required_pathway_id:
          accessType === 'included_with_pathway' ? (bookingRequiredPathwayId || null) : null,
        // Semantic Series membership. Empty string → null (not in a
        // Series). No coupling with booking_access_type here.
        series_id: seriesId || null,
        // Standalone paid Gathering: both fields null unless
        // access is paid_separately, so we never accidentally
        // persist stale ticket data on a free/included event.
        ticket_price_cents:
          accessType === 'paid_separately' ? ticketPriceCents : null,
        ticket_currency:
          accessType === 'paid_separately' ? ticketCurrency : null,
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
        const payload = isEdit
          ? basePayload
          : { ...basePayload, create_channel: createChannel }
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(payload),
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
    <form onSubmit={handleSubmit} className="flex flex-col gap-8">

      {/* ─────────── THE GATHERING ─────────── */}
      <Section title="THE GATHERING" subtitle="What is this moment?">
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
            placeholder="What will happen in this Gathering?"
            className="w-full resize-none rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800">Gathering type</label>
          <select
            value={gatheringType}
            onChange={(e) => setGatheringType(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
          >
            {GATHERING_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.icon}  {t.label}</option>
            ))}
          </select>
          <p className="mt-1.5 text-[12.5px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
            {gatheringDescription(gatheringType)}
          </p>
        </div>

        {isEdit && (
          <div>
            <label className="mb-1.5 block text-sm font-medium text-navy-800">Cover image</label>
            {thumbnailUrl ? (
              <div className="flex flex-col gap-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={thumbnailUrl}
                  alt="Gathering cover"
                  className="h-36 w-full rounded-lg object-cover"
                />
                <div className="flex gap-3">
                  <label className={[
                    'cursor-pointer rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-black transition-colors hover:border-slate-400',
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
                  <span className="text-sm text-black">
                    {thumbnailUploading ? 'Uploading…' : 'Click to upload an image'}
                  </span>
                  <span className="text-xs text-black">JPG, PNG, WebP — max 5 MB</span>
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
      </Section>

      {/* ─────────── WHEN ─────────── */}
      <Section title="WHEN">
        <div className="flex gap-4">
          <div className="flex-1">
            <label className="mb-1.5 block text-sm font-medium text-navy-800">
              {isRecurring ? 'First Gathering starts' : 'Starts'}
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

        {/* Recurring — new Gatherings only. Weekly is the only pattern
            currently supported by the backend, so the label makes that
            explicit rather than suggesting a broader picker. */}
        {!isEdit && (
          <div className="rounded-xl border border-border bg-slate-50/50 p-5">
            <div className="mb-3 flex items-center gap-3">
              <Toggle checked={isRecurring} onChange={setIsRecurring} />
              <span className="text-sm font-medium text-navy-800">Recurring series</span>
            </div>
            <p className="mb-4 text-xs italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
              Weekly recurrence is the only pattern currently supported.
            </p>

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
                            : 'border-border text-black hover:border-teal-400 hover:text-teal-700',
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
                          : 'border-border text-black hover:border-slate-400',
                      ].join(' ')}
                    >
                      After N Gatherings
                    </button>
                    <button
                      type="button"
                      onClick={() => setEndMode('date')}
                      className={[
                        'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                        endMode === 'date'
                          ? 'border-navy-900 bg-navy-900 text-white'
                          : 'border-border text-black hover:border-slate-400',
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
                      <span className="text-sm text-black">Gatherings total</span>
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
      </Section>

      {/* ─────────── WHERE ─────────── */}
      <Section title="WHERE" subtitle="How will people gather?">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800">Attendance format</label>
          <div className="flex flex-wrap gap-2">
            {ATTENDANCE_FORMATS.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => {
                  setAttendanceFormat(f.value)
                  // Keep the legacy `location_type` roughly in sync so the
                  // iCal generator + older UI paths still render correctly.
                  if (f.value === 'in_person') setLocationType('in_person')
                  else if (locationType === 'in_person') setLocationType('zoom')
                }}
                className={[
                  'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                  attendanceFormat === f.value
                    ? 'border-navy-900 bg-navy-900 text-white'
                    : 'border-border text-black hover:border-slate-400 hover:text-navy-700',
                ].join(' ')}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {(attendanceFormat === 'online' || attendanceFormat === 'hybrid') && (
          <div>
            <label className="mb-1.5 block text-sm font-medium text-navy-800">Meeting link</label>
            <input
              type="url"
              value={locationUrl}
              onChange={(e) => setLocationUrl(e.target.value)}
              placeholder="https://…"
              className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
            />
            <p className="mt-1 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
              Only shown to registered attendees.
            </p>
          </div>
        )}

        {(attendanceFormat === 'in_person' || attendanceFormat === 'hybrid') && (
          <>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-navy-800">Venue name</label>
              <input
                value={venueName}
                onChange={(e) => setVenueName(e.target.value)}
                placeholder="e.g. The Studio, King Street"
                className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-navy-800">Venue address</label>
              <textarea
                value={venueAddress}
                onChange={(e) => setVenueAddress(e.target.value)}
                rows={2}
                placeholder="Full address — shown only to registered attendees."
                className="w-full resize-none rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
              />
            </div>
          </>
        )}

        <div>
          <label className="mb-1.5 block text-sm font-medium text-navy-800">
            {attendanceFormat === 'online'
              ? 'Access instructions'
              : attendanceFormat === 'in_person'
                ? 'Arrival instructions'
                : 'Instructions for both attendance options'}
          </label>
          <textarea
            value={accessInstructions}
            onChange={(e) => setAccessInstructions(e.target.value)}
            rows={2}
            placeholder={
              attendanceFormat === 'in_person'
                ? 'Parking, entrance, what to bring…'
                : 'Anything registrants need to know about joining.'
            }
            className="w-full resize-none rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
          <p className="mt-1 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
            Only shown to registered attendees.
          </p>
        </div>
      </Section>

      {/* ─────────── ACCESS ─────────── */}
      <Section title="ACCESS" subtitle="Who may register?">
        {accessTypeLocked && (
          <div
            className="rounded-xl px-4 py-3"
            style={{ background: 'rgba(56,160,158,0.06)', border: '1px solid rgba(56,160,158,0.30)' }}
          >
            <p className="text-[13px]" style={{ color: 'rgba(12,24,38,0.75)' }}>
              {accessTypeLockReason === 'sales' ? (
                <>The access type can&rsquo;t be changed because tickets have already been sold. Existing ticket holders must keep their access.</>
              ) : (
                <>The access type can&rsquo;t be changed while a purchase is in progress. Try again after any pending checkouts have expired or been cancelled.</>
              )}
            </p>
          </div>
        )}
        {/* Belongs to Series — always rendered so the concept is
            discoverable whether or not a Series is currently
            selected. Attaching to a Series does NOT change the
            access type. Detaching, however, is blocked while access
            is "Included with a Series pass" — an unresolvable
            Series-pass gate is a broken state we would rather refuse
            to create. Silent broadening of access is deliberately
            avoided. */}
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <label
            htmlFor="event-series"
            className="mb-1 block text-[13px] font-semibold text-navy-900"
          >
            Belongs to Series
          </label>
          <p className="mb-2 text-[12px] text-slate-600">
            Optional. Group this Gathering under a Series to organise
            related sessions. This choice does not change access —
            set that below.
          </p>
          {series.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-2 text-[12.5px] text-slate-600">
              No Gathering Series in this Collective yet.{' '}
              <a
                href="/creator-studio/gatherings"
                className="font-medium text-teal-700 hover:underline"
              >
                Create one from Gatherings
              </a>
              , then come back here to attach this Gathering.
            </p>
          ) : (
            <>
              <select
                id="event-series"
                value={seriesId}
                onChange={(e) => {
                  const next = e.target.value
                  if (!next && accessType === 'included_with_series') {
                    // Refuse the change rather than silently broadening
                    // access. The Creator must pick a different access
                    // type below first.
                    return
                  }
                  setSeriesId(next)
                }}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
              >
                <option
                  value=""
                  disabled={accessType === 'included_with_series'}
                >
                  — Not in a Series —
                </option>
                {series.map((s) => (
                  <option key={s.id} value={s.id}>{s.title}</option>
                ))}
              </select>
              {accessType === 'included_with_series' && seriesId && (
                <p className="mt-2 text-[12px]" style={{ color: '#8a6a1f' }}>
                  Access is set to <strong>Included with a Series pass</strong> —
                  remove that below before detaching from the Series.
                </p>
              )}
            </>
          )}
        </div>

        <div className="flex flex-col gap-2">
          {ACCESS_TYPES
            // Only surface the Series-pass access option when this
            // Gathering actually belongs to a Series. Prevents the
            // Creator from choosing a gate that can never resolve
            // because there's no series to check the pass against.
            .filter((a) => a.value !== 'included_with_series' || !!seriesId)
            .map((a) => (
            <label
              key={a.value}
              className={[
                'flex items-start gap-3 rounded-xl border px-4 py-3 transition-colors',
                accessTypeLocked && a.value !== accessType ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
              ].join(' ')}
              style={
                accessType === a.value
                  ? { borderColor: 'rgba(56,160,158,0.6)', background: 'rgba(56,160,158,0.05)' }
                  : { borderColor: '#e2e8f0', background: 'white' }
              }
            >
              <input
                type="radio"
                name="access-type"
                checked={accessType === a.value}
                onChange={() => setAccessType(a.value)}
                disabled={accessTypeLocked && a.value !== accessType}
                className="mt-1 h-4 w-4 accent-teal-500 disabled:opacity-40"
              />
              <div>
                <p className="text-[14px] font-medium text-navy-900">{a.label}</p>
                {a.value === 'free' && (
                  <p className="mt-0.5 text-[12px] leading-relaxed text-black">
                    No payment is required. Visibility and membership requirements
                    are controlled separately.
                  </p>
                )}
                {a.value === 'included_with_collective' && (
                  <p className="mt-0.5 text-[12px] leading-relaxed text-black">
                    Only active members of this Collective may register.
                  </p>
                )}
                {a.value === 'included_with_pathway' && (
                  <p className="mt-0.5 text-[12px] leading-relaxed text-black">
                    Only members enrolled in the linked Pathway may register.
                  </p>
                )}
                {a.value === 'included_with_series' && (
                  <p className="mt-0.5 text-[12px] leading-relaxed text-black">
                    Only members holding a valid pass for the selected
                    Gathering Series may book. Weekly limits and total
                    session credits from the pass are enforced.
                  </p>
                )}
                {a.value === 'paid_separately' && (
                  <p className="mt-0.5 text-[12px] leading-relaxed text-black">
                    Anyone can buy a ticket through Stripe. A ticket grants
                    access to this Gathering only — not to the rest of the
                    Collective.
                  </p>
                )}
                {a.value === 'invitation_only' && (
                  <p className="mt-0.5 text-[12px] italic leading-relaxed" style={{ color: 'rgba(12,24,38,0.55)' }}>
                    Members register only when a Creator adds them manually.
                  </p>
                )}
              </div>
            </label>
          ))}
        </div>

        {accessType === 'paid_separately' && (
          <div
            className="rounded-xl border p-4"
            style={{ borderColor: 'rgba(56,160,158,0.35)', background: 'rgba(56,160,158,0.03)' }}
          >
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: '#38A09E' }}>
              TICKET DETAILS
            </p>
            <p className="mb-4 text-[13px] leading-relaxed text-black">
              Members and visitors will purchase a ticket for this Gathering
              through Stripe. A ticket grants access to this Gathering only.
            </p>

            <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
              <div>
                <label htmlFor="ticket-price" className="mb-1.5 block text-sm font-medium text-navy-800">
                  Ticket price
                </label>
                <div className="relative">
                  <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-500">
                    $
                  </span>
                  <input
                    id="ticket-price"
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min="0"
                    placeholder="25.00"
                    value={ticketPriceInput}
                    onChange={(e) => {
                      setTicketPriceInput(e.target.value)
                      if (ticketPriceError) setTicketPriceError(null)
                    }}
                    className="w-full rounded-lg border border-border bg-white pl-7 pr-3 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
                  />
                </div>
                {ticketPriceError && (
                  <p className="mt-1 text-[12px] text-red-600">{ticketPriceError}</p>
                )}
                <p className="mt-1 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
                  Enter a normal amount like 25 or 25.00. We store cents.
                </p>
              </div>
              <div>
                <label htmlFor="ticket-currency" className="mb-1.5 block text-sm font-medium text-navy-800">
                  Currency
                </label>
                <select
                  id="ticket-currency"
                  value={ticketCurrency}
                  onChange={(e) => setTicketCurrency(e.target.value)}
                  className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
                >
                  {['AUD', 'USD', 'GBP', 'EUR', 'NZD', 'CAD'].map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
            </div>

            {!salesEnabled && (
              <p className="mt-3 text-[12px] italic" style={{ color: '#8A6A15' }}>
                Ticket payments are currently available for testing only.
              </p>
            )}
          </div>
        )}

        {accessType === 'included_with_pathway' && (
          <div>
            <label className="mb-1.5 block text-sm font-medium text-navy-800">Linked pathway</label>
            <select
              value={bookingRequiredPathwayId}
              onChange={(e) => setBookingRequiredPathwayId(e.target.value)}
              className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
            >
              <option value="">Choose a Pathway…</option>
              {pathways.filter((p) => p.status !== 'archived').map((p) => (
                <option key={p.id} value={p.id}>{p.title}</option>
              ))}
            </select>
          </div>
        )}
      </Section>

      {/* ─────────── AVAILABILITY ─────────── */}
      <Section title="AVAILABILITY" subtitle="How many people can join?">
        <div className="rounded-xl border border-border bg-slate-50/50 p-5">
          <div className="mb-3 flex items-center gap-3">
            <Toggle
              checked={requiresBooking}
              onChange={(v) => {
                // Rule-forced booking stays on regardless of user click.
                if (bookingRequiredByRules) return
                setRequiresBooking(v)
              }}
              disabled={bookingRequiredByRules}
            />
            <span className="text-sm font-medium text-navy-800">Require booking</span>
            <span className="text-xs text-black">
              {bookingRequiredByRules
                ? 'Automatic — this Access type / capacity setting requires booking.'
                : 'Members must book a spot to attend.'}
            </span>
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
                  placeholder="e.g. You'll receive the Zoom link 24 hours before the Gathering."
                  className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
                />
              </div>
            </div>
          )}
        </div>
      </Section>

      {/* ─────────── VISIBILITY ─────────── */}
      <Section title="VISIBILITY" subtitle="Who can see this Gathering exists?">
        <div className="rounded-xl border border-border bg-slate-50/50 p-5">
          <div className="flex items-start gap-3">
            <Toggle checked={isPublic} onChange={setIsPublic} />
            <div>
              <p className="text-sm font-medium text-navy-800">Public preview</p>
              <p className="text-xs text-black">
                Allow people outside this Collective to view this Gathering.
                Registration requirements still apply.
              </p>
            </div>
          </div>
        </div>
      </Section>

      {/* ─────────── CONVERSATIONS ─────────── */}
      {!isEdit && !isRecurring && (
        <Section title="CONVERSATIONS">
          <div
            className="rounded-xl px-4 py-3"
            style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.20)' }}
          >
            <label className="flex cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                checked={createChannel}
                onChange={(e) => setCreateChannel(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-teal-500"
              />
              <div>
                <p className="text-[13.5px] font-semibold text-navy-900">
                  📅 Create Gathering Channel
                </p>
                <p className="mt-0.5 text-[12px] leading-relaxed text-black">
                  Adds a Conversations channel for this Gathering. Registered
                  attendees are joined automatically; conversations naturally
                  continue before, during, and after.
                </p>
              </div>
            </label>
          </div>
        </Section>
      )}

      {/* ─────────── PUBLICATION ─────────── */}
      <Section title="PUBLICATION">
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            type="submit"
            disabled={saving}
            onClick={() => setSubmitMode('draft')}
            className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium text-navy-900 transition-colors hover:border-navy-400 disabled:opacity-50"
          >
            {saving && submitMode === 'draft' ? 'Saving…' : 'Save as Draft'}
          </button>

          <button
            type="submit"
            disabled={saving}
            onClick={() => setSubmitMode('publish')}
            className="rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {saving && submitMode === 'publish'
              ? 'Publishing…'
              : (isRecurring ? 'Publish Series' : 'Publish Gathering')}
          </button>

          {isEdit && event?.is_published && (
            <span className="text-xs italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
              This Gathering is currently published — saving as Draft will hide it from members.
            </span>
          )}

          {error && <span className="text-sm text-red-500">{error}</span>}
        </div>
      </Section>
    </form>
  )
}
