'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type {
  CreatorGatheringSeriesSummary,
  GatheringSeriesStatus,
} from '@/types/platform'
import {
  Button,
  FormField,
  Input,
  Modal,
  TextArea,
  useToast,
} from '@/components/platform'

/**
 * Gathering Series band on the Gatherings index.
 *
 * Sits above the events list. Compact: header + inline list of the
 * Creator's existing Series, and a "New Series" affordance that opens
 * a lightweight modal (title + start + optional end + optional
 * description) and then routes into the Series editor.
 *
 * A Gathering Series is deliberately not equated with "paid term" in
 * this UI — a Series simply groups related Gatherings. Payment /
 * access configuration is authored later, on the Series editor.
 */

interface Props {
  spaceSlug: string
  series: CreatorGatheringSeriesSummary[]
}

const STATUS_LABEL: Record<GatheringSeriesStatus, string> = {
  draft: 'Draft',
  published: 'Published',
  archived: 'Archived',
}

function statusStyle(s: GatheringSeriesStatus): React.CSSProperties {
  if (s === 'published') return { background: 'rgba(56,160,158,0.10)', color: '#0f766e' }
  if (s === 'archived')  return { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.55)' }
  return { background: 'rgba(214,177,63,0.14)', color: '#8a6a1f' }
}

/** Human-readable date range for a Series. Ongoing when ``ends_at``
 *  is null — surfaced explicitly so a Creator never sees a blank
 *  "End: —" or similar. */
function seriesDateSummary(startsAt: string, endsAt: string | null): string {
  const start = new Date(startsAt).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  if (!endsAt) return `Starts ${start} · Ongoing`
  const end = new Date(endsAt).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  return `${start} – ${end}`
}

export default function GatheringSeriesBand({ spaceSlug, series }: Props) {
  const [newOpen, setNewOpen] = useState(false)

  return (
    <section className="mb-8 rounded-2xl border border-border bg-white p-5 md:p-6">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-[18px] text-navy-900">Gathering Series</h2>
          <p className="mt-1 max-w-lg text-[13px] text-black">
            Group related Gatherings — a term, a program, or an ongoing
            circle. Everything from access to payment is authored on
            the Series itself.
          </p>
        </div>
        <Button variant="primary" onClick={() => setNewOpen(true)}>
          New Series
        </Button>
      </header>

      {series.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-center">
          <p className="text-[13.5px] text-slate-700">
            No Gathering Series yet.
          </p>
          <p className="mx-auto mt-1 max-w-md text-[12.5px] text-slate-500">
            Create one to group related Gatherings and offer term passes.
          </p>
        </div>
      ) : (
        // Card grid — Pathway-sibling visual language. Each Series
        // renders as a self-contained card (rounded-2xl, hover
        // shadow lift, cover band on top for visual anchor, footer
        // with status pill + metadata). Deliberately does NOT
        // borrow Pathway-specific metadata (step count, price, etc.);
        // Series metadata (dates, gathering count, PO count) is what
        // sits in the footer.
        <ul className="grid gap-4 sm:grid-cols-2">
          {series.map((s) => {
            const cover = resolveMediaUrl(s.cover_image_url ?? undefined)
            const dateSummary = seriesDateSummary(s.starts_at, s.ends_at)
            return (
              <li key={s.id}>
                <Link
                  href={`/creator-studio/gathering-series/${s.slug}`}
                  className="group flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-sm transition-all hover:-translate-y-1 hover:border-teal-200/60 hover:shadow-lg"
                >
                  {/*
                    Cover band. Uses the Series's own cover image
                    when one is set; falls back to a soft gradient
                    when the Series has no cover. Date range sits
                    as an overlay pill so it stays legible over any
                    photograph.
                  */}
                  {cover ? (
                    <div className="relative h-32 w-full overflow-hidden">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={cover}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                      {/* Bottom-to-top gradient for legibility of the overlay pill. */}
                      <div
                        aria-hidden="true"
                        className="absolute inset-0"
                        style={{
                          background:
                            'linear-gradient(to top, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.10) 45%, rgba(0,0,0,0) 100%)',
                        }}
                      />
                      <span
                        className="absolute bottom-3 left-3 inline-flex items-center rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-white"
                        style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(2px)' }}
                      >
                        {dateSummary}
                      </span>
                    </div>
                  ) : (
                    <div
                      className="relative h-24 w-full"
                      style={{
                        background: 'linear-gradient(135deg, rgba(56,160,158,0.14) 0%, rgba(85,184,182,0.08) 100%)',
                      }}
                    >
                      <div className="absolute inset-0 flex items-end p-4">
                        <p
                          className="text-[11.5px] font-semibold uppercase tracking-wider"
                          style={{ color: '#0f766e' }}
                        >
                          {dateSummary}
                        </p>
                      </div>
                    </div>
                  )}

                  <div className="flex flex-1 flex-col p-4">
                    <div className="mb-3 flex items-start justify-between gap-2">
                      <h3 className="font-serif text-[16px] leading-snug text-navy-900">
                        {s.title}
                      </h3>
                      <span
                        className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
                        style={statusStyle(s.status)}
                      >
                        {STATUS_LABEL[s.status]}
                      </span>
                    </div>
                    <div className="mt-auto flex items-center justify-between gap-3 border-t border-border pt-3">
                      <span className="text-[11.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
                        {s.gathering_count} Gathering{s.gathering_count === 1 ? '' : 's'}
                        {s.payment_option_count > 0 && (
                          <> · {s.payment_option_count} Payment Option{s.payment_option_count === 1 ? '' : 's'}</>
                        )}
                      </span>
                      <span
                        className="text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800"
                      >
                        Open →
                      </span>
                    </div>
                  </div>
                </Link>
              </li>
            )
          })}
        </ul>
      )}

      {newOpen && (
        <NewSeriesModal
          spaceSlug={spaceSlug}
          onClose={() => setNewOpen(false)}
        />
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

/** Convert a ``YYYY-MM-DD`` value from an <input type="date"> into a
 *  naive ISO datetime string. Deliberately does NOT involve
 *  ``new Date(...)`` — that would apply the browser's local
 *  timezone (e.g. Sydney "2026-07-13" becomes UTC "2026-07-12T14:00Z"),
 *  which is exactly the drift we want to avoid for a term boundary.
 *
 *  ``atEndOfDay`` composes ``23:59:59`` so an end date is inclusive
 *  of the whole day: a Sep-19 end lets a Series-pass hold through
 *  Sep-19, not expire at midnight-start-of-Sep-19.
 */
export function dateToNaiveIso(dateStr: string, atEndOfDay = false): string | null {
  const s = dateStr.trim()
  if (!s || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return null
  return `${s}T${atEndOfDay ? '23:59:59' : '00:00:00'}`
}

function NewSeriesModal({
  spaceSlug, onClose,
}: {
  spaceSlug: string
  onClose: () => void
}) {
  const router = useRouter()
  const { show } = useToast()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const [saving, setSaving] = useState(false)

  // Explicit validation state so a disabled Create button never leaves
  // the Creator guessing which field is incomplete.
  const missingTitle = !title.trim()
  const missingStart = !startsAt.trim()
  const endBeforeStart = !!(endsAt.trim() && startsAt.trim() && endsAt < startsAt)
  const canCreate = !missingTitle && !missingStart && !endBeforeStart && !saving
  const validationMessage =
    saving ? null
    : missingTitle && missingStart ? 'Enter a title and a start date.'
    : missingTitle ? 'Enter a title.'
    : missingStart ? 'Enter a start date.'
    : endBeforeStart ? 'End date must be on or after the start date.'
    : null

  async function create() {
    const startsIso = dateToNaiveIso(startsAt)
    if (!title.trim() || !startsIso) return
    setSaving(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/gathering-series`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: title.trim(),
            description: description.trim() || null,
            starts_at: startsIso,
            ends_at: dateToNaiveIso(endsAt, true),
          }),
        },
      )
      if (!res.ok) {
        // Log the underlying API detail for debugging but NEVER
        // surface it verbatim — bare messages like FastAPI's default
        // "Not Found" would leak to the Creator as toast copy.
        let detail: unknown
        try { detail = (await res.json())?.detail } catch { /* not JSON */ }
        console.error(
          '[gathering-series] create failed',
          { status: res.status, detail },
        )
        show(
          'We couldn\u2019t create this Gathering Series. Please try again.',
          { tone: 'error' },
        )
        // Modal stays open so the Creator can retry without re-typing.
        return
      }
      const created = await res.json()
      router.push(`/creator-studio/gathering-series/${created.slug}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="New Gathering Series">
      <div className="space-y-4">
        <FormField label="Title">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. EMBODY Spring Term"
            autoFocus
            maxLength={300}
          />
        </FormField>
        <FormField
          label="Description"
          helper="Optional. A short summary of what this Series is."
        >
          <TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            maxLength={1000}
          />
        </FormField>
        <div className="grid gap-3 sm:grid-cols-2">
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
            helper="Optional. Leave blank for an ongoing Series."
          >
            <input
              type="date"
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
              min={startsAt || undefined}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
            />
          </FormField>
        </div>
        {validationMessage && (
          <p className="text-[12px]" style={{ color: '#8a6a1f' }}>
            {validationMessage}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void create()}
            disabled={!canCreate}
          >
            {saving ? 'Creating…' : 'Create Series'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
