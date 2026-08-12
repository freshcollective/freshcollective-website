'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type {
  CreatorEvent,
  CreatorGatheringSeries,
  CreatorPathway,
  CreatorSeriesPaymentOption,
  GatheringSeriesStatus,
} from '@/types/platform'
import {
  Button,
  FormField,
  Input,
  Modal,
  Select,
  TextArea,
  useToast,
} from '@/components/platform'
import ImagePickerField from '@/components/creator/ImagePickerField'

/**
 * Series editor client.
 *
 * Three cards, in order:
 *   1. About this Series — title, description, dates, cover, status
 *   2. Gatherings in this Series — list + attach existing + create new
 *   3. Payment Options — list + editor modal
 *
 * State kept minimal: each card owns its slice, all mutations round-
 * trip through the creator API and reload the tree via
 * ``router.refresh()`` — a simple, boring pattern that keeps
 * multi-step edits (attach → view → detach) coherent without a
 * bespoke state store.
 */

interface Props {
  spaceSlug: string
  initialSeries: CreatorGatheringSeries
  initialGatherings: CreatorEvent[]
  initialPaymentOptions: CreatorSeriesPaymentOption[]
  pathways: CreatorPathway[]
}

const STATUS_LABEL: Record<GatheringSeriesStatus, string> = {
  draft: 'Draft',
  published: 'Published',
  archived: 'Archived',
}

// ---------------------------------------------------------------------------
// Date helpers — <input type="date"> ↔ naive ISO string.
// ---------------------------------------------------------------------------

/** Extract the ``YYYY-MM-DD`` slice from a naive ISO datetime, or
 *  ``''`` when null/invalid. String-based on purpose: parsing via
 *  ``new Date(iso)`` would apply the browser's local zone to a naive
 *  server value and could roll the date. The stored value is
 *  already ``YYYY-MM-DDTHH:MM:SS``; we only need the first ten chars. */
function isoToDateInput(iso: string | null): string {
  if (!iso) return ''
  const s = String(iso).trim()
  return /^\d{4}-\d{2}-\d{2}/.test(s) ? s.slice(0, 10) : ''
}

/** ``YYYY-MM-DD`` → naive ISO. See notes on the twin in
 *  ``GatheringSeriesBand.tsx`` — same rationale for avoiding
 *  ``new Date(...)`` here. */
function dateInputToNaiveIso(dateStr: string, atEndOfDay = false): string | null {
  const s = dateStr.trim()
  if (!s || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return null
  return `${s}T${atEndOfDay ? '23:59:59' : '00:00:00'}`
}

function fmtDateShort(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit',
  })
}

/** Full-context date+time used in the Add-existing modal so the
 *  Creator sees title + full date (with year) + time in every row.
 *  E.g. "Thu 13 Aug 2026 · 6:00 pm". */
function fmtDateTimeFull(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  }).replace(', ', ' \u00b7 ')
}

function fmtPrice(cents: number | null, currency: string): string {
  if (cents == null) return ''
  return `$${Math.round(cents / 100)} ${currency}`
}

/**
 * Resolve a Creator-facing error message from a failed API response.
 * Only surfaces ``body.detail`` verbatim for statuses we intentionally
 * raise with user-facing text (400 validation errors, 409 conflicts).
 * Bare framework messages ("Not Found", "Internal Server Error") never
 * leak. The underlying detail is always console-logged for debugging.
 */
async function friendlyApiError(
  res: Response, context: string, fallback: string,
): Promise<string> {
  let detail: unknown
  try { detail = (await res.json())?.detail } catch { /* not JSON */ }
  console.error(`[${context}] ${res.status}`, detail)
  const isUserFacingStatus = res.status === 400 || res.status === 409
  if (isUserFacingStatus && typeof detail === 'string' && detail.trim()) {
    return detail
  }
  return fallback
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export default function SeriesEditorClient({
  spaceSlug, initialSeries, initialGatherings, initialPaymentOptions, pathways,
}: Props) {
  return (
    <div className="pb-24">
      <AboutSeriesCard spaceSlug={spaceSlug} initial={initialSeries} />
      <SeriesGatheringsCard
        spaceSlug={spaceSlug}
        seriesId={initialSeries.id}
        seriesSlug={initialSeries.slug}
        seriesTitle={initialSeries.title}
        seriesStartsAt={initialSeries.starts_at}
        seriesEndsAt={initialSeries.ends_at}
        initialGatherings={initialGatherings}
      />
      <SeriesPaymentOptionsCard
        spaceSlug={spaceSlug}
        seriesSlug={initialSeries.slug}
        seriesEnds={initialSeries.ends_at}
        pathways={pathways}
        initialOptions={initialPaymentOptions}
      />
      <SeriesDangerZone
        spaceSlug={spaceSlug}
        series={initialSeries}
      />
    </div>
  )
}

/**
 * Series lifecycle controls.
 *
 * Restrained on purpose — this sits at the bottom of the editor,
 * not competing with the everyday save/publish actions above.
 *
 * Never-published draft → **Delete this Series** (permanent). The
 * backend auto-detaches any attached Gatherings; the Gatherings
 * themselves are not deleted. Historical AccessPass references
 * (if any) block delete server-side as a safety net.
 *
 * Anything that has ever been public → **Archive this Series**
 * (soft: sets status='archived'; slug and history preserved so
 * shared links, bookings and passes remain resolvable).
 */
function SeriesDangerZone({
  spaceSlug, series,
}: {
  spaceSlug: string
  series: CreatorGatheringSeries
}) {
  const router = useRouter()
  const { show } = useToast()
  const [busy, setBusy] = useState(false)
  const hasEverPublished = series.published_at != null
  const isArchived = series.status === 'archived'

  async function hardDelete() {
    if (!window.confirm(
      `Delete "${series.title}" permanently?\n\nThis Series is a draft and has never been published. Any attached Gatherings will be removed from the Series but not deleted.`,
    )) return
    setBusy(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${series.slug}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) {
        show(
          await friendlyApiError(res, 'gathering-series/delete',
            'We couldn\u2019t delete this Series. Please try again.'),
          { tone: 'error' },
        )
        return
      }
      show('Series deleted.', { tone: 'success' })
      router.push('/creator-studio/gatherings')
    } finally {
      setBusy(false)
    }
  }

  async function archive() {
    if (!window.confirm(
      `Archive "${series.title}"?\n\nMembers will no longer see it, but historical bookings, passes, and links keep working.`,
    )) return
    setBusy(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${series.slug}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'archived' }),
        },
      )
      if (!res.ok) {
        show(
          await friendlyApiError(res, 'gathering-series/archive',
            'We couldn\u2019t archive this Series. Please try again.'),
          { tone: 'error' },
        )
        return
      }
      show('Series archived.', { tone: 'success' })
      router.refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="mt-10 rounded-2xl border p-5 md:p-6"
      style={{
        borderColor: 'rgba(12,24,38,0.08)',
        background: 'rgba(12,24,38,0.015)',
      }}
    >
      <p
        className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em]"
        style={{ color: 'rgba(12,24,38,0.55)' }}
      >
        Danger zone
      </p>
      {hasEverPublished ? (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold text-navy-900">
              {isArchived ? 'This Series is archived' : 'Archive this Series'}
            </h3>
            <p className="mt-1 max-w-lg text-[12.5px] text-slate-600">
              {isArchived
                ? 'Members no longer see it. Historical passes and bookings still resolve to this Series.'
                : 'Members will no longer see it. Historical passes and bookings keep working. Once published, a Series cannot be permanently deleted.'}
            </p>
          </div>
          {!isArchived && (
            <button
              type="button"
              onClick={() => void archive()}
              disabled={busy}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:border-slate-400 hover:text-slate-900 disabled:opacity-50"
            >
              {busy ? 'Working\u2026' : 'Archive this Series'}
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold text-navy-900">
              Delete this Series
            </h3>
            <p className="mt-1 max-w-lg text-[12.5px] text-slate-600">
              Permanent. Attached Gatherings will be removed from the
              Series but not deleted. Available because this Series has
              never been published.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void hardDelete()}
            disabled={busy}
            className="rounded-lg border border-red-200 bg-white px-4 py-2 text-[13px] font-medium text-red-700 transition-colors hover:border-red-300 hover:text-red-800 disabled:opacity-50"
          >
            {busy ? 'Working\u2026' : 'Delete this Series'}
          </button>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// 1. About this Series
// ---------------------------------------------------------------------------

function AboutSeriesCard({
  spaceSlug, initial,
}: {
  spaceSlug: string
  initial: CreatorGatheringSeries
}) {
  const router = useRouter()
  const { show } = useToast()
  const [title, setTitle] = useState(initial.title)
  const [description, setDescription] = useState(initial.description ?? '')
  const [startsAt, setStartsAt] = useState(isoToDateInput(initial.starts_at))
  const [endsAt, setEndsAt] = useState(isoToDateInput(initial.ends_at))
  const [cover, setCover] = useState<string | null>(initial.cover_image_url)
  const [status, setStatus] = useState<GatheringSeriesStatus>(initial.status)
  const [saving, setSaving] = useState(false)

  async function save(patch: Record<string, unknown>) {
    setSaving(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${initial.slug}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        },
      )
      if (!res.ok) {
        show(
          await friendlyApiError(res, 'gathering-series/save',
            'We couldn\u2019t save this Series. Please try again.'),
          { tone: 'error' },
        )
        return false
      }
      show('Saved.', { tone: 'success' })
      router.refresh()
      return true
    } finally {
      setSaving(false)
    }
  }

  async function onSave() {
    const startsIso = dateInputToNaiveIso(startsAt)
    if (!title.trim() || !startsIso) return
    await save({
      title: title.trim(),
      description: description.trim() || null,
      starts_at: startsIso,
      // Explicit null when blank — turns a finite Series ongoing.
      // End dates are inclusive-of-day: 23:59:59 keeps a pass valid
      // through the final calendar day of the term.
      ends_at: dateInputToNaiveIso(endsAt, true),
      cover_image_url: cover,
    })
  }

  async function onStatusChange(next: GatheringSeriesStatus) {
    setStatus(next)
    await save({ status: next })
  }

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 md:p-8">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-serif text-[18px] text-navy-900">About this Series</h2>
          <p className="mt-1 text-[13.5px] text-slate-600">
            Title, description, dates, cover and status.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={status}
            onChange={(e) => void onStatusChange(e.target.value as GatheringSeriesStatus)}
          >
            <option value="draft">{STATUS_LABEL.draft}</option>
            <option value="published">{STATUS_LABEL.published}</option>
            <option value="archived">{STATUS_LABEL.archived}</option>
          </Select>
        </div>
      </header>

      <div className="grid gap-5 md:grid-cols-2">
        <FormField label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />
        </FormField>
        <FormField label="Description" helper="Optional. Short and human.">
          <TextArea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={1000} />
        </FormField>
        <FormField label="Start date">
          <input
            type="date"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
          />
        </FormField>
        <FormField
          label="End date"
          helper={endsAt ? 'Leave blank for an ongoing Series.' : 'Ongoing — no defined end.'}
        >
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
              min={startsAt || undefined}
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
            />
            {endsAt && (
              <button
                type="button"
                onClick={() => setEndsAt('')}
                className="rounded-lg border border-slate-200 px-3 py-2 text-[12px] font-medium text-slate-600 hover:border-teal-300 hover:text-teal-700"
                title="Clear end date — make Series ongoing"
              >
                Clear
              </button>
            )}
          </div>
        </FormField>
        <div className="md:col-span-2">
          <FormField label="Cover image" helper="Optional. Wide 16:9 works best.">
            <ImagePickerField
              spaceSlug={spaceSlug}
              value={cover}
              onChange={setCover}
            />
          </FormField>
        </div>
      </div>

      <div className="mt-6 flex justify-end">
        <Button variant="primary" onClick={() => void onSave()} disabled={saving || !title.trim() || !startsAt.trim()}>
          {saving ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// 2. Gatherings in this Series
// ---------------------------------------------------------------------------

const ACCESS_LABEL: Record<string, string> = {
  free: 'Free',
  included_with_collective: 'Included with Collective',
  included_with_pathway: 'Included with Pathway',
  included_with_series: 'Included with a Series pass',
  paid_separately: 'Paid separately',
  invitation_only: 'Invitation only',
}

function SeriesGatheringsCard({
  spaceSlug, seriesId, seriesSlug, seriesTitle, seriesStartsAt, seriesEndsAt, initialGatherings,
}: {
  spaceSlug: string
  seriesId: string
  seriesSlug: string
  seriesTitle: string
  seriesStartsAt: string
  seriesEndsAt: string | null
  initialGatherings: CreatorEvent[]
}) {
  const router = useRouter()
  const { show } = useToast()
  const [attachOpen, setAttachOpen] = useState(false)

  async function detach(eventId: string) {
    const target = initialGatherings.find((g) => g.id === eventId)
    // Series-pass gathering can't be detached without first changing
    // its access type — the backend would refuse and we would rather
    // tell the Creator up front where to make that change.
    if (target && target.booking_access_type === 'included_with_series') {
      show(
        'This Gathering is set to "Included with a Series pass". Change its access type first, then remove it from the Series.',
        { tone: 'error' },
      )
      return
    }
    if (!window.confirm(
      `Remove this Gathering from "${seriesTitle}"?\n\nThe Gathering itself is not deleted.`,
    )) return
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/events/${eventId}`),
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_id: null }),
      },
    )
    if (!res.ok) {
      show(
        await friendlyApiError(res, 'gathering-series/detach',
          'We couldn\u2019t remove this Gathering from the Series. Please try again.'),
        { tone: 'error' },
      )
      return
    }
    show('Removed from Series.', { tone: 'success' })
    router.refresh()
  }

  // Access-type distribution across attached Gatherings — surfaces a
  // helpful line like "12 Series pass · 6 Pathway access" so the
  // Creator can spot Gatherings still using an older gating model.
  // Only rendered when there is actual mixing to report.
  const accessCounts = new Map<string, number>()
  for (const g of initialGatherings) {
    const k = g.booking_access_type || 'included_with_collective'
    accessCounts.set(k, (accessCounts.get(k) ?? 0) + 1)
  }
  const accessBreakdown = Array.from(accessCounts.entries())
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 md:p-8">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-[18px] text-navy-900">Gatherings in this Series</h2>
          <p className="mt-1 text-[13.5px] text-slate-600">
            Add existing Gatherings or create new ones as part of this Series.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="tertiary" onClick={() => setAttachOpen(true)}>
            Add existing
          </Button>
          <Link
            href={`/creator/spaces/${spaceSlug}/events/new?series_id=${encodeURIComponent(seriesId)}`}
            className="inline-flex items-center rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            New Gathering in Series
          </Link>
        </div>
      </header>

      {/* Mixed-access summary. Only shown when > 1 access type is
          present, so a homogeneous Series stays uncluttered. Helps
          the Creator identify Gatherings still on an older model. */}
      {accessBreakdown.length > 1 && (
        <div
          className="mb-4 rounded-xl border px-4 py-2.5 text-[12.5px]"
          style={{
            borderColor: 'rgba(214,177,63,0.35)',
            background: 'rgba(214,177,63,0.06)',
            color: '#8a6a1f',
          }}
        >
          Mixed access in this Series:{' '}
          {accessBreakdown.map(([k, n], i) => (
            <span key={k}>
              <strong className="font-semibold">{n}</strong>{' '}
              {ACCESS_LABEL[k] ?? k}
              {i < accessBreakdown.length - 1 ? ' \u00b7 ' : ''}
            </span>
          ))}
        </div>
      )}

      {initialGatherings.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-center">
          <p className="text-[13.5px] text-slate-700">No Gatherings in this Series yet.</p>
          <p className="mx-auto mt-1 max-w-md text-[12.5px] text-slate-500">
            Attach existing ones or create Gatherings as part of the Series.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100">
          {initialGatherings.map((g) => (
            <li key={g.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/creator/spaces/${spaceSlug}/events/${g.id}?from_series=${encodeURIComponent(seriesSlug)}`}
                    className="truncate text-[14.5px] font-semibold text-navy-900 hover:text-teal-700 hover:underline"
                  >
                    {g.title}
                  </Link>
                  <span
                    className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
                    style={{
                      background: g.is_published ? 'rgba(56,160,158,0.10)' : 'rgba(214,177,63,0.14)',
                      color: g.is_published ? '#0f766e' : '#8a6a1f',
                    }}
                  >
                    {g.is_published ? 'Published' : 'Draft'}
                  </span>
                </div>
                <p className="mt-0.5 text-[12.5px] text-slate-600">
                  {fmtDateTime(g.starts_at)}
                  {' · '}
                  <span className="text-slate-500">{ACCESS_LABEL[g.booking_access_type] ?? g.booking_access_type}</span>
                </p>
              </div>
              {g.booking_access_type === 'included_with_series' ? (
                <div className="flex flex-col items-end gap-1">
                  <button
                    type="button"
                    onClick={() => void detach(g.id)}
                    className="cursor-not-allowed rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-400"
                    title="Change access type first — a Series pass gate cannot exist outside its Series."
                  >
                    Remove from Series
                  </button>
                  <Link
                    href={`/creator/spaces/${spaceSlug}/events/${g.id}?from_series=${encodeURIComponent(seriesSlug)}`}
                    className="text-[11px] text-teal-700 hover:underline"
                  >
                    Change access first →
                  </Link>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => void detach(g.id)}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:border-red-200 hover:text-red-600"
                >
                  Remove from Series
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {attachOpen && (
        <AttachExistingModal
          spaceSlug={spaceSlug}
          seriesId={seriesId}
          seriesStartsAt={seriesStartsAt}
          seriesEndsAt={seriesEndsAt}
          excludedIds={new Set(initialGatherings.map((g) => g.id))}
          onClose={() => setAttachOpen(false)}
          onAttached={() => router.refresh()}
        />
      )}
    </section>
  )
}

/** True when an Event's start falls outside a finite Series window.
 *  Ongoing series (no ends_at) never mark an Event as out-of-range. */
function isEventOutOfRange(
  eventStartsAt: string,
  seriesStartsAt: string,
  seriesEndsAt: string | null,
): boolean {
  const start = new Date(eventStartsAt).getTime()
  const winStart = new Date(seriesStartsAt).getTime()
  const winEnd = seriesEndsAt ? new Date(seriesEndsAt).getTime() : null
  if (Number.isNaN(start) || Number.isNaN(winStart)) return false
  if (start < winStart) return true
  if (winEnd != null && start > winEnd) return true
  return false
}

function AttachExistingModal({
  spaceSlug, seriesId, seriesStartsAt, seriesEndsAt, excludedIds,
  onClose, onAttached,
}: {
  spaceSlug: string
  seriesId: string
  seriesStartsAt: string
  seriesEndsAt: string | null
  excludedIds: Set<string>
  onClose: () => void
  onAttached: () => void
}) {
  const { show } = useToast()
  const [loading, setLoading] = useState(true)
  const [events, setEvents] = useState<CreatorEvent[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  // Optional post-selection choice: whether to also swap each
  // selected Gathering's access to ``included_with_series``. Default
  // keeps existing settings — attaching to a Series does NOT
  // silently change access. See the "Attach" flow copy below.
  const [switchToSeriesPass, setSwitchToSeriesPass] = useState(false)

  useEffect(() => {
    let cancelled = false
    // Restricted to ``scope=upcoming`` — showing archive events as
    // candidates surfaced years-old cancelled test rows during
    // browser review, which is confusing for someone building a
    // Series. Upcoming captures the intent (a current or future
    // Series) without pulling stale data.
    fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/events?scope=upcoming`),
      { credentials: 'include' },
    )
      .then((r) => r.ok ? r.json() : [])
      .then((data: CreatorEvent[]) => {
        if (cancelled) return
        const eligible = data.filter(
          (e) => !excludedIds.has(e.id)
            && (e.series_id == null || e.series_id === '')
            && e.status !== 'cancelled',
        )
        // In-range first, then out-of-range; ties broken by start.
        eligible.sort((a, b) => {
          const aOut = isEventOutOfRange(a.starts_at, seriesStartsAt, seriesEndsAt)
          const bOut = isEventOutOfRange(b.starts_at, seriesStartsAt, seriesEndsAt)
          if (aOut !== bOut) return aOut ? 1 : -1
          return a.starts_at.localeCompare(b.starts_at)
        })
        setEvents(eligible)
        setLoading(false)
      })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [spaceSlug, excludedIds, seriesStartsAt, seriesEndsAt])

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  async function attach() {
    if (selectedIds.size === 0) return
    // Confirm before attaching any Gatherings outside the Series
    // window — finite Series may intentionally carry outliers
    // (intro session, bonus session) but the Creator should own
    // that choice rather than have it happen silently.
    const chosen = events.filter((e) => selectedIds.has(e.id))
    const outOfRange = chosen.filter(
      (e) => isEventOutOfRange(e.starts_at, seriesStartsAt, seriesEndsAt),
    )
    if (outOfRange.length > 0) {
      const list = outOfRange.map((e) => `\u2022 ${e.title} \u2014 ${fmtDateTimeFull(e.starts_at)}`).join('\n')
      const ok = window.confirm(
        `${outOfRange.length === 1
          ? 'This Gathering falls outside the Series dates. Add it anyway?'
          : `${outOfRange.length} of your selections fall outside the Series dates. Add them anyway?`}\n\n${list}`,
      )
      if (!ok) return
    }
    setSaving(true)
    try {
      // Sequential PATCHes through the existing validated endpoint —
      // the invariant guard + per-request ownership check are
      // preserved. A dedicated bulk endpoint isn't warranted for
      // Creator-driven cohort sizes (typically < 30 rows).
      //
      // If the Creator opted to switch access, we send BOTH
      // ``series_id`` and ``booking_access_type`` in the same PATCH.
      // The backend guards the invariant on the resulting state, so
      // the two changes commit together.
      let succeeded = 0
      let failedFirst: string | null = null
      for (const ev of chosen) {
        const patch: Record<string, unknown> = { series_id: seriesId }
        if (switchToSeriesPass) patch.booking_access_type = 'included_with_series'
        const res = await fetch(
          apiUrl(`/api/creator/spaces/${spaceSlug}/events/${ev.id}`),
          {
            method: 'PATCH',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patch),
          },
        )
        if (res.ok) {
          succeeded += 1
        } else if (failedFirst == null) {
          failedFirst = await friendlyApiError(
            res, 'gathering-series/attach',
            'One Gathering couldn\u2019t be added. Please try again.',
          )
        }
      }
      if (failedFirst && succeeded === 0) {
        show(failedFirst, { tone: 'error' })
        return
      }
      if (failedFirst) {
        show(`Added ${succeeded} \u2014 but not all: ${failedFirst}`, { tone: 'error' })
      } else {
        show(
          succeeded === 1 ? 'Added to Series.' : `Added ${succeeded} to Series.`,
          { tone: 'success' },
        )
      }
      onAttached()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const inRange = events.filter((e) => !isEventOutOfRange(e.starts_at, seriesStartsAt, seriesEndsAt))
  const outRange = events.filter((e) => isEventOutOfRange(e.starts_at, seriesStartsAt, seriesEndsAt))
  const outRangeSelectedCount = outRange.filter((e) => selectedIds.has(e.id)).length

  return (
    <Modal
      open
      onClose={onClose}
      title="Add existing Gatherings"
      size="lg"
      actions={
        <>
          <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void attach()}
            disabled={selectedIds.size === 0 || saving}
          >
            {saving
              ? 'Adding\u2026'
              : selectedIds.size === 0
                ? 'Add to Series'
                : `Add ${selectedIds.size} to Series`}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {loading ? (
          <p className="py-4 text-center text-[13px] text-slate-500">Loading&hellip;</p>
        ) : events.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-[13px] text-slate-600">
            No unattached upcoming Gatherings. Create a new one in this Series instead.
          </p>
        ) : (
          <div className="space-y-4">
            <p className="text-[12.5px] text-slate-600">
              Tick each Gathering you&rsquo;d like to add. Gatherings in
              the Series date range are listed first.
            </p>
            {inRange.length > 0 && (
              <EventCheckboxList
                heading="Within Series dates"
                items={inRange}
                selectedIds={selectedIds}
                onToggle={toggle}
              />
            )}
            {outRange.length > 0 && (
              <EventCheckboxList
                heading="Outside Series dates"
                subheading={'Intro or follow-up Gatherings can still be attached — you\u2019ll be asked to confirm.'}
                items={outRange}
                selectedIds={selectedIds}
                onToggle={toggle}
                muted
              />
            )}
          </div>
        )}
        {outRangeSelectedCount > 0 && (
          <p className="text-[12px]" style={{ color: '#8a6a1f' }}>
            {outRangeSelectedCount} selected {outRangeSelectedCount === 1 ? 'Gathering falls' : 'Gatherings fall'} outside
            the Series dates &mdash; you&rsquo;ll be asked to confirm.
          </p>
        )}
        {selectedIds.size > 0 && (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-2 text-[13px] font-semibold text-navy-900">
              Access for the selected Gatherings
            </p>
            <div className="space-y-2">
              <label className="flex cursor-pointer items-start gap-2 text-[13px] text-navy-900">
                <input
                  type="radio"
                  name="attach-access"
                  checked={!switchToSeriesPass}
                  onChange={() => setSwitchToSeriesPass(false)}
                  className="mt-1 h-4 w-4 accent-teal-500"
                />
                <span>
                  <span className="font-medium">Keep existing access settings</span>
                  <span className="mt-0.5 block text-[12px] text-slate-600">
                    Free, Collective-included, Pathway-gated &mdash; unchanged.
                  </span>
                </span>
              </label>
              <label className="flex cursor-pointer items-start gap-2 text-[13px] text-navy-900">
                <input
                  type="radio"
                  name="attach-access"
                  checked={switchToSeriesPass}
                  onChange={() => setSwitchToSeriesPass(true)}
                  className="mt-1 h-4 w-4 accent-teal-500"
                />
                <span>
                  <span className="font-medium">Use this Series pass</span>
                  <span className="mt-0.5 block text-[12px] text-slate-600">
                    Change each selected Gathering&rsquo;s access to
                    <em> Included with a Series pass</em>.
                  </span>
                </span>
              </label>
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}

function EventCheckboxList({
  heading, subheading, items, selectedIds, onToggle, muted = false,
}: {
  heading: string
  subheading?: string
  items: CreatorEvent[]
  selectedIds: Set<string>
  onToggle: (id: string) => void
  muted?: boolean
}) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {heading}
      </p>
      {subheading && (
        <p className="mb-2 text-[12px] italic text-slate-500">{subheading}</p>
      )}
      <ul className={`divide-y divide-slate-100 rounded-xl border border-slate-100 ${muted ? 'bg-slate-50/50' : ''}`}>
        {items.map((e) => (
          <li key={e.id}>
            <label className="flex cursor-pointer items-start gap-3 px-4 py-2.5">
              <input
                type="checkbox"
                checked={selectedIds.has(e.id)}
                onChange={() => onToggle(e.id)}
                className="mt-1 h-4 w-4 shrink-0 accent-teal-500"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-medium text-navy-900">
                  {e.title}
                </p>
                <p className="mt-0.5 text-[12.5px] text-slate-600">
                  {fmtDateTimeFull(e.starts_at)}
                  {e.booking_access_type && e.booking_access_type !== 'included_with_collective' && (
                    <> · <span className="text-slate-500">{ACCESS_LABEL[e.booking_access_type] ?? e.booking_access_type}</span></>
                  )}
                </p>
              </div>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 3. Payment Options
// ---------------------------------------------------------------------------

function SeriesPaymentOptionsCard({
  spaceSlug, seriesSlug, seriesEnds, pathways, initialOptions,
}: {
  spaceSlug: string
  seriesSlug: string
  seriesEnds: string | null
  pathways: CreatorPathway[]
  initialOptions: CreatorSeriesPaymentOption[]
}) {
  const [editingId, setEditingId] = useState<string | 'new' | null>(null)

  const active = initialOptions.filter((o) => o.status !== 'archived')

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 md:p-8">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-[18px] text-navy-900">Payment Options</h2>
          <p className="mt-1 max-w-lg text-[13.5px] text-slate-600">
            How people can join this Series. Each option grants a term
            pass; you can optionally include Pathway access.
          </p>
        </div>
        <Button variant="primary" onClick={() => setEditingId('new')}>
          New Payment Option
        </Button>
      </header>

      {active.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-center">
          <p className="text-[13.5px] text-slate-700">No Payment Options yet.</p>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100">
          {active.map((o) => {
            const pw = pathways.find((p) => p.id === o.grants_pathway_id) ?? null
            return (
              <li key={o.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-[14.5px] font-semibold text-navy-900">{o.name}</p>
                    <span
                      className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
                      style={{
                        background: o.status === 'published'
                          ? 'rgba(56,160,158,0.10)'
                          : 'rgba(214,177,63,0.14)',
                        color: o.status === 'published' ? '#0f766e' : '#8a6a1f',
                      }}
                    >
                      {o.status}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[12.5px] text-slate-600">
                    {o.sessions_per_week ? <>{o.sessions_per_week} / week · </> : null}
                    {o.total_sessions ? <>{o.total_sessions} sessions · </> : null}
                    {fmtPrice(o.effective_price_cents ?? o.calculated_total_cents, o.currency)}
                  </p>
                  {pw && (
                    <p className="mt-0.5 text-[12px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
                      Includes Pathway: <span className="font-medium text-navy-900">{pw.title}</span>
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setEditingId(o.id)}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-600 hover:border-teal-300 hover:text-teal-700"
                >
                  Edit
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {editingId && (
        <SeriesPaymentOptionModal
          spaceSlug={spaceSlug}
          seriesSlug={seriesSlug}
          seriesEnds={seriesEnds}
          pathways={pathways}
          existing={
            editingId === 'new' ? null
              : initialOptions.find((o) => o.id === editingId) ?? null
          }
          onClose={() => setEditingId(null)}
        />
      )}
    </section>
  )
}

function SeriesPaymentOptionModal({
  spaceSlug, seriesSlug, seriesEnds, pathways, existing, onClose,
}: {
  spaceSlug: string
  seriesSlug: string
  seriesEnds: string | null
  pathways: CreatorPathway[]
  existing: CreatorSeriesPaymentOption | null
  onClose: () => void
}) {
  const router = useRouter()
  const { show } = useToast()
  const isEdit = existing != null

  const [name, setName] = useState(existing?.name ?? '')
  const [description, setDescription] = useState(existing?.description ?? '')
  const [totalSessions, setTotalSessions] = useState<string>(
    existing?.total_sessions?.toString() ?? '',
  )
  const [sessionsPerWeek, setSessionsPerWeek] = useState<string>(
    existing?.sessions_per_week?.toString() ?? '',
  )
  const [pricePerSession, setPricePerSession] = useState<string>(
    existing?.price_per_session_cents != null
      ? (existing.price_per_session_cents / 100).toString()
      : '',
  )
  const [overrideTotal, setOverrideTotal] = useState<string>(
    existing?.override_total_cents != null
      ? (existing.override_total_cents / 100).toString()
      : '',
  )
  const [currency, setCurrency] = useState<string>(existing?.currency ?? 'AUD')
  const [status, setStatus] = useState<'draft' | 'published' | 'archived'>(
    existing?.status ?? 'draft',
  )
  // "Also include Pathway access" — user-facing wording; wires to
  // ``grants_pathway_id`` under the hood.
  const [grantsPathway, setGrantsPathway] = useState<boolean>(!!existing?.grants_pathway_id)
  const [grantsPathwayId, setGrantsPathwayId] = useState<string>(
    existing?.grants_pathway_id ?? (pathways[0]?.id ?? ''),
  )

  // Term end date. If the Series has an end date, we don't ask the
  // Creator to duplicate it — the AccessPass webhook already
  // precedences series.ends_at over option.term_end_date. When the
  // Series is ongoing, the option MUST carry its own end date OR the
  // Creator must explicitly confirm the "no end / perpetual" state.
  const seriesIsOngoing = seriesEnds == null
  const [optionEndDate, setOptionEndDate] = useState<string>(
    existing?.term_end_date ?? '',
  )
  const [perpetualConfirmed, setPerpetualConfirmed] = useState<boolean>(
    isEdit && !existing?.term_end_date && seriesIsOngoing,
  )
  const perpetualState = seriesIsOngoing && !optionEndDate

  const [saving, setSaving] = useState(false)

  const calcTotal = useMemo(() => {
    const t = parseInt(totalSessions || '0', 10)
    const p = parseFloat(pricePerSession || '0')
    if (t > 0 && p > 0) return Math.round(t * p * 100)
    return null
  }, [totalSessions, pricePerSession])

  async function save() {
    if (!name.trim()) return
    if (perpetualState && !perpetualConfirmed) {
      show(
        'Confirm "no end date" — this creates a perpetual pass.',
        { tone: 'error' },
      )
      return
    }
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        description: description.trim() || null,
        payment_type: 'term_pass',
        status,
        currency: currency.toUpperCase(),
        total_sessions: totalSessions ? parseInt(totalSessions, 10) : null,
        sessions_per_week: sessionsPerWeek ? parseInt(sessionsPerWeek, 10) : null,
        price_per_session_cents: pricePerSession
          ? Math.round(parseFloat(pricePerSession) * 100)
          : null,
        override_total_cents: overrideTotal
          ? Math.round(parseFloat(overrideTotal) * 100)
          : null,
        calculated_total_cents: calcTotal,
        // On finite series, we intentionally leave option.term_end_date
        // null and let the AccessPass webhook derive valid_until from
        // series.ends_at. On ongoing series, the option carries its
        // own end date (or perpetual).
        term_end_date: seriesIsOngoing ? (optionEndDate || null) : null,
        grants_pathway_id: grantsPathway ? grantsPathwayId : null,
      }
      const url = isEdit
        ? apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${seriesSlug}/payment-options/${existing!.id}`)
        : apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${seriesSlug}/payment-options`)
      const res = await fetch(url, {
        method: isEdit ? 'PATCH' : 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        show(
          await friendlyApiError(res, 'series-payment-option/save',
            'We couldn\u2019t save this Payment Option. Please try again.'),
          { tone: 'error' },
        )
        return
      }
      show('Saved.', { tone: 'success' })
      router.refresh()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  async function archive() {
    if (!isEdit) return
    if (!window.confirm('Archive this Payment Option? It will no longer appear for members.')) return
    setSaving(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${seriesSlug}/payment-options/${existing!.id}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) {
        show(
          await friendlyApiError(res, 'series-payment-option/archive',
            'We couldn\u2019t archive this Payment Option. Please try again.'),
          { tone: 'error' },
        )
        return
      }
      show('Archived.', { tone: 'success' })
      router.refresh()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? 'Edit Payment Option' : 'New Payment Option'}
      size="lg"
      actions={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          {isEdit ? (
            <Button variant="tertiary" onClick={() => void archive()} disabled={saving}>
              Archive
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="tertiary" onClick={onClose} disabled={saving}>Cancel</Button>
            <Button
              variant="primary"
              onClick={() => void save()}
              disabled={!name.trim() || saving}
            >
              {saving ? 'Saving\u2026' : isEdit ? 'Save' : 'Create'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-8">

        {/* ── The pass ─────────────────────────────────────────────── */}
        <ModalSection
          title="The pass"
          hint="Name and describe this way of joining the Series."
        >
          <div className="space-y-4">
            <FormField label="Name">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Awaken"
                autoFocus
                maxLength={200}
              />
            </FormField>
            <FormField label="Description" helper="Optional. Short and useful.">
              <TextArea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                maxLength={1000}
              />
            </FormField>
          </div>
        </ModalSection>

        {/* ── Price ─────────────────────────────────────────────────── */}
        <ModalSection
          title="Price"
          hint="Set the total price. The default is calculated from sessions × price per session; you can override it."
        >
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <FormField label="Sessions / week">
                <Input
                  type="number"
                  value={sessionsPerWeek}
                  onChange={(e) => setSessionsPerWeek(e.target.value)}
                  min="1"
                />
              </FormField>
              <FormField label="Total sessions">
                <Input
                  type="number"
                  value={totalSessions}
                  onChange={(e) => setTotalSessions(e.target.value)}
                  min="1"
                />
              </FormField>
              <FormField label="Price / session">
                <Input
                  type="number"
                  value={pricePerSession}
                  onChange={(e) => setPricePerSession(e.target.value)}
                  min="0"
                  step="0.01"
                />
              </FormField>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <FormField
                label="Total price"
                helper="Calculated from total sessions × price per session."
              >
                <Input
                  value={calcTotal != null ? `$${(calcTotal / 100).toFixed(2)}` : '\u2014'}
                  readOnly
                />
              </FormField>
              <FormField
                label="Custom total price (optional)"
                helper="Overrides the calculated total if set."
              >
                <Input
                  type="number"
                  value={overrideTotal}
                  onChange={(e) => setOverrideTotal(e.target.value)}
                  min="0"
                  step="0.01"
                />
              </FormField>
              <FormField label="Currency">
                <Select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  <option value="AUD">AUD</option>
                  <option value="USD">USD</option>
                  <option value="GBP">GBP</option>
                  <option value="EUR">EUR</option>
                  <option value="NZD">NZD</option>
                </Select>
              </FormField>
            </div>
          </div>
        </ModalSection>

        {/* ── What's included ──────────────────────────────────────── */}
        <ModalSection
          title="What's included"
          hint="Access window and any Pathway granted with this pass."
        >
          <div className="space-y-4">
            {seriesIsOngoing ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <p className="mb-2 text-[13px] font-semibold text-navy-900">
                  When does this pass expire?
                </p>
                <p className="mb-3 text-[12.5px] text-slate-600">
                  This Series is ongoing, so this pass must set its own
                  end date &mdash; or explicitly confirm no end.
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <FormField label="Access end date">
                    <input
                      type="date"
                      value={optionEndDate}
                      onChange={(e) => {
                        setOptionEndDate(e.target.value)
                        setPerpetualConfirmed(false)
                      }}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
                    />
                  </FormField>
                  <div className="flex items-end">
                    <label className="flex items-center gap-2 text-[13px] text-slate-700">
                      <input
                        type="checkbox"
                        checked={perpetualConfirmed}
                        onChange={(e) => {
                          setPerpetualConfirmed(e.target.checked)
                          if (e.target.checked) setOptionEndDate('')
                        }}
                        className="h-4 w-4 accent-teal-500"
                      />
                      No end &mdash; perpetual pass
                    </label>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-[13px] text-slate-600">
                Access ends when the Series ends
                {seriesEnds ? ` (${fmtDateShort(seriesEnds)})` : ''}.
              </p>
            )}

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <label className="flex items-center gap-2 text-[13px] font-semibold text-navy-900">
                <input
                  type="checkbox"
                  checked={grantsPathway}
                  onChange={(e) => setGrantsPathway(e.target.checked)}
                  className="h-4 w-4 accent-teal-500"
                />
                Also include Pathway access
              </label>
              <p className="mt-1 text-[12px] text-slate-600">
                When checked, buying this pass also grants access to the
                chosen Pathway for the duration of the Series.
              </p>
              {grantsPathway && (
                <div className="mt-3">
                  <Select
                    value={grantsPathwayId}
                    onChange={(e) => setGrantsPathwayId(e.target.value)}
                    disabled={pathways.length === 0}
                  >
                    {pathways.length === 0 ? (
                      <option value="">No Pathways available</option>
                    ) : (
                      pathways.map((p) => (
                        <option key={p.id} value={p.id}>{p.title}</option>
                      ))
                    )}
                  </Select>
                </div>
              )}
            </div>
          </div>
        </ModalSection>

        {/* ── How members can pay ──────────────────────────────────── */}
        <ModalSection
          title="How members can pay"
          hint="Offer different ways to pay without changing what members receive."
        >
          {isEdit ? (
            <SchedulesSection
              spaceSlug={spaceSlug}
              seriesSlug={seriesSlug}
              optionId={existing!.id}
              totalCents={calcTotal ?? (existing?.effective_price_cents ?? null)}
              currency={currency}
            />
          ) : (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-4 text-[12.5px] text-slate-600">
              Save this pass first, then add ways to pay such as
              \u201CPay in full\u201D or \u201CWeekly instalments\u201D.
            </p>
          )}
        </ModalSection>

        {/* ── Publishing ───────────────────────────────────────────── */}
        <ModalSection
          title="Publishing"
          hint="Drafts are only visible to you. Publish when you&rsquo;re ready for members to see this pass."
        >
          <FormField label="Status">
            <Select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
              <option value="draft">Draft</option>
              <option value="published">Published</option>
              <option value="archived">Archived</option>
            </Select>
          </FormField>
        </ModalSection>
      </div>
    </Modal>
  )
}

/** Simple two-line section header used inside the PO modal. */
function ModalSection({
  title, hint, children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section>
      <p className="mb-1 text-[13px] font-semibold text-navy-900">{title}</p>
      {hint && (
        <p className="mb-3 text-[12.5px] text-slate-600">{hint}</p>
      )}
      {children}
    </section>
  )
}


// ---------------------------------------------------------------------------
// Payment schedules — inside the PO modal
//
// Access is defined by the Payment Option above; a *schedule* is a
// way to pay for that same access. Regardless of which schedule the
// member picks, the resulting AccessPass entitlement is identical
// (same series eligibility, same credits, same window, same
// included Pathway). The schedule affects only the Stripe cadence.
//
// The Pathway-side authoring lives in ``PathwaySettingsClient``;
// reusing that DOM would have meant refactoring 500+ lines of
// expanded/edit state. This is a compact per-schedule row + a
// "+ Add payment schedule" affordance that talks to the mirror
// series-scoped endpoints.
// ---------------------------------------------------------------------------

type ScheduleRow = {
  id: string
  payment_option_id: string
  name: string
  description: string | null
  schedule_type: 'pay_in_full' | 'recurring_installments' | 'manual'
  status: 'draft' | 'published' | 'archived'
  total_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  position: number
}

function SchedulesSection({
  spaceSlug, seriesSlug, optionId, totalCents, currency,
}: {
  spaceSlug: string
  seriesSlug: string
  optionId: string
  totalCents: number | null
  currency: string
}) {
  const { show } = useToast()
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<ScheduleRow[]>([])
  const [creatingKind, setCreatingKind] = useState<'pay_in_full' | 'recurring_installments' | null>(null)
  // Bumped after each successful mutation so the next fetch effect
  // re-runs. Keeping this separate from ``rows`` avoids the
  // set-state-in-effect lint warning that ``async function load()
  // { setLoading(true); ... }`` would trigger.
  const [reloadTick, setReloadTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${seriesSlug}/payment-options/${optionId}/schedules`),
      { credentials: 'include' },
    )
      .then((r) => r.ok ? r.json() : [])
      .then((data: ScheduleRow[]) => {
        if (cancelled) return
        setRows(data)
        setLoading(false)
      })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [spaceSlug, seriesSlug, optionId, reloadTick])
  const reload = () => setReloadTick((t) => t + 1)

  async function archive(id: string) {
    if (!window.confirm('Remove this payment schedule?')) return
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${seriesSlug}/payment-options/${optionId}/schedules/${id}`),
      { method: 'DELETE', credentials: 'include' },
    )
    if (!res.ok) {
      show(
        await friendlyApiError(res, 'series-schedule/archive',
          'We couldn\u2019t remove this schedule. Please try again.'),
        { tone: 'error' },
      )
      return
    }
    show('Schedule removed.', { tone: 'success' })
    reload()
  }

  async function publishToggle(row: ScheduleRow) {
    const next = row.status === 'published' ? 'draft' : 'published'
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${seriesSlug}/payment-options/${optionId}/schedules/${row.id}`),
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: next }),
      },
    )
    if (!res.ok) {
      show(
        await friendlyApiError(res, 'series-schedule/publish',
          'We couldn\u2019t update this schedule. Please try again.'),
        { tone: 'error' },
      )
      return
    }
    show(next === 'published' ? 'Published.' : 'Moved to draft.', { tone: 'success' })
    reload()
  }

  const active = rows.filter((r) => r.status !== 'archived')

  return (
    <section>
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          How can members pay?
        </p>
        <span className="text-[11.5px] text-slate-500">
          Same access, different payment cadence.
        </span>
      </div>
      <p className="mb-3 text-[12.5px] text-slate-600">
        Offer different ways to pay without changing what members receive.
      </p>

      {loading ? (
        <p className="py-3 text-[12.5px] text-slate-500">Loading&hellip;</p>
      ) : active.length === 0 ? (
        <p className="mb-3 rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-4 text-[12.5px] text-slate-600">
          No payment schedules yet. Add one below.
        </p>
      ) : (
        <ul className="mb-3 divide-y divide-slate-100 rounded-xl border border-slate-100">
          {active.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-medium text-navy-900">
                  {r.name}
                </p>
                <p className="mt-0.5 text-[12.5px] text-slate-600">
                  {scheduleDisplayLine(r)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void publishToggle(r)}
                className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider transition-colors"
                style={
                  r.status === 'published'
                    ? { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
                    : { background: 'rgba(214,177,63,0.14)', color: '#8a6a1f' }
                }
                title="Toggle draft / published"
              >
                {r.status}
              </button>
              <button
                type="button"
                onClick={() => void archive(r.id)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-600 hover:border-red-200 hover:text-red-600"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {creatingKind == null ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="tertiary" onClick={() => setCreatingKind('pay_in_full')}>
            + Pay in full
          </Button>
          <Button variant="tertiary" onClick={() => setCreatingKind('recurring_installments')}>
            + Weekly instalments
          </Button>
        </div>
      ) : (
        <NewScheduleForm
          kind={creatingKind}
          spaceSlug={spaceSlug}
          seriesSlug={seriesSlug}
          optionId={optionId}
          defaultTotalCents={totalCents}
          defaultCurrency={currency}
          onCancel={() => setCreatingKind(null)}
          onCreated={() => { setCreatingKind(null); reload() }}
        />
      )}
    </section>
  )
}

function scheduleDisplayLine(r: ScheduleRow): string {
  const curr = r.currency || 'AUD'
  if (r.schedule_type === 'pay_in_full') {
    return r.total_amount_cents != null
      ? `$${Math.round(r.total_amount_cents / 100)} ${curr} once`
      : 'Pay in full'
  }
  if (r.schedule_type === 'recurring_installments') {
    const per = r.installment_amount_cents != null
      ? `$${Math.round(r.installment_amount_cents / 100)} ${curr}`
      : ''
    const n = r.installment_count ?? 0
    const cadence = r.interval === 'week' ? 'weekly'
      : r.interval === 'fortnight' ? 'fortnightly'
      : r.interval === 'month' ? 'monthly'
      : (r.interval || 'per interval')
    return per && n ? `${per} × ${n} ${cadence} payments` : `${cadence} instalments`
  }
  return 'Manual'
}

function NewScheduleForm({
  kind, spaceSlug, seriesSlug, optionId, defaultTotalCents, defaultCurrency,
  onCancel, onCreated,
}: {
  kind: 'pay_in_full' | 'recurring_installments'
  spaceSlug: string
  seriesSlug: string
  optionId: string
  defaultTotalCents: number | null
  defaultCurrency: string
  onCancel: () => void
  onCreated: () => void
}) {
  const { show } = useToast()
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState(
    kind === 'pay_in_full' ? 'Pay in full' : 'Weekly',
  )
  const [total, setTotal] = useState<string>(
    defaultTotalCents != null ? (defaultTotalCents / 100).toString() : '',
  )
  const [count, setCount] = useState<string>('10')
  const [per, setPer] = useState<string>(
    defaultTotalCents != null ? (defaultTotalCents / 100 / 10).toFixed(0) : '',
  )

  async function create() {
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        schedule_type: kind,
        status: 'draft',
        currency: defaultCurrency,
      }
      if (kind === 'pay_in_full') {
        payload.total_amount_cents = total ? Math.round(parseFloat(total) * 100) : null
      } else {
        const n = parseInt(count, 10)
        const perCents = per ? Math.round(parseFloat(per) * 100) : null
        payload.installment_count = Number.isFinite(n) ? n : null
        payload.installment_amount_cents = perCents
        payload.total_amount_cents = perCents != null && Number.isFinite(n) ? perCents * n : null
        payload.interval = 'week'
        payload.stripe_interval = 'week'
        payload.stripe_interval_count = 1
      }
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series/${seriesSlug}/payment-options/${optionId}/schedules`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!res.ok) {
        show(
          await friendlyApiError(res, 'series-schedule/create',
            'We couldn\u2019t add this schedule. Please try again.'),
          { tone: 'error' },
        )
        return
      }
      show('Schedule added.', { tone: 'success' })
      onCreated()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="mb-2 text-[13px] font-semibold text-navy-900">
        {kind === 'pay_in_full' ? 'New — Pay in full' : 'New — Weekly instalments'}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <FormField label="Label shown to members">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={kind === 'pay_in_full' ? 'Pay in full' : 'Weekly'}
            maxLength={200}
          />
        </FormField>
        {kind === 'pay_in_full' ? (
          <FormField label="Amount charged once">
            <Input
              type="number"
              value={total}
              onChange={(e) => setTotal(e.target.value)}
              min="0"
              step="0.01"
              placeholder="e.g. 420"
            />
          </FormField>
        ) : (
          <>
            <FormField label="Amount per week">
              <Input
                type="number"
                value={per}
                onChange={(e) => setPer(e.target.value)}
                min="0"
                step="0.01"
                placeholder="e.g. 42"
              />
            </FormField>
            <FormField label="Number of payments">
              <Input
                type="number"
                value={count}
                onChange={(e) => setCount(e.target.value)}
                min="1"
              />
            </FormField>
          </>
        )}
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="tertiary" onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button
          variant="primary"
          onClick={() => void create()}
          disabled={saving || !name.trim()}
        >
          {saving ? 'Adding\u2026' : 'Add schedule'}
        </Button>
      </div>
    </div>
  )
}
