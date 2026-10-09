'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { formatGatheringFullDate, formatGatheringTimeShort } from '@/lib/dateTime'
import {
  paletteHex,
  rgbaFromHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'
import {
  confirmLabel,
  patternDescription,
  previewHeadline,
  previewNotes,
  resultHeadline,
  resultNeedsAttention,
  sessionCount,
  type OccurrenceOutcome,
  type RegularSessionsResponse,
  type ReservationPreview,
  type ReservationResult,
  type SchedulePattern,
} from '@/lib/regularSessions'

/**
 * Reserve your regular sessions.
 *
 * A member with a term pass tells us which weekly slots are theirs —
 * Mondays at 6, Thursdays at 6 — and every remaining matching session
 * is reserved in one action, instead of twenty trips to twenty
 * Gathering pages.
 *
 * Three steps, deliberately, with nothing happening until the third:
 *
 *   choose    the weekly slots, with how many sessions each covers
 *   preview   exactly what will happen, date by date, including the
 *             dates that cannot be reserved and why
 *   confirm   the server re-decides everything and reports what it
 *             actually did
 *
 * The preview is not a formality. A term can contain a full session, a
 * session the member already holds, and a session their weekly
 * allowance will not stretch to — and the member is owed all three
 * before they press a button, not a count that quietly shrinks
 * afterwards. Equally, the preview is not a promise: the confirmation
 * re-runs every check against locked rows, and when something moved in
 * between it is named rather than dropped.
 *
 * Individual booking is untouched. Everything created here is an
 * ordinary booking, so cancelling one Monday leaves the rest alone.
 */

type Phase =
  | { kind: 'loading' }
  | { kind: 'unavailable' }
  | { kind: 'choosing' }
  | { kind: 'previewing' }
  | { kind: 'preview'; preview: ReservationPreview }
  | { kind: 'reserving'; preview: ReservationPreview }
  | { kind: 'done'; result: ReservationResult }
  | { kind: 'error'; message: string }

function errorMessage(body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  return typeof detail === 'string' && detail.trim()
    ? detail
    : 'Something went wrong. Please try again.'
}

/** "Monday, 1 March 2027 · 6:00pm" */
function occurrenceLine(o: OccurrenceOutcome, timezone: string): string {
  return `${formatGatheringFullDate(o.starts_at, timezone)} · ${formatGatheringTimeShort(o.starts_at, timezone)}`
}

function DateList({
  occurrences, timezone, tone, showReason,
}: {
  occurrences: OccurrenceOutcome[]
  timezone: string
  tone: 'default' | 'muted' | 'warn'
  showReason?: boolean
}) {
  if (occurrences.length === 0) return null
  const colour =
    tone === 'warn' ? '#A64526' : tone === 'muted' ? 'rgba(12,24,38,0.56)' : '#0C1826'
  return (
    <ul className="mt-2 space-y-1">
      {occurrences.map((o) => (
        <li key={`${o.event_id}-${o.reason ?? 'ok'}`} className="text-[12.5px]" style={{ color: colour }}>
          {occurrenceLine(o, timezone)}
          {showReason && o.message ? (
            <span className="block text-[11.5px]" style={{ color: 'rgba(12,24,38,0.56)' }}>
              {o.message}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

export default function RegularSessions({
  spaceSlug, seriesSlug, palette, justPurchased = false,
}: {
  spaceSlug: string
  seriesSlug: string
  palette: CollectivePaletteMeta | null
  /** True on return from a successful purchase — the moment this is
   *  most useful, so the card opens expanded rather than waiting to be
   *  found. It stays available on every later visit either way. */
  justPurchased?: boolean
}) {
  const primary = paletteHex('primary', palette) ?? '#0f766e'
  const borderColour = rgbaFromHex(primary, 0.24)
  const bgColour = rgbaFromHex(primary, 0.05)

  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  const [data, setData] = useState<RegularSessionsResponse | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [expanded, setExpanded] = useState(justPurchased)

  const base = `/api/spaces/${spaceSlug}/gathering-series/${seriesSlug}/regular-sessions`

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(apiUrl(base), { credentials: 'include' })
        if (!res.ok) {
          if (!cancelled) setPhase({ kind: 'unavailable' })
          return
        }
        const body = (await res.json()) as RegularSessionsResponse
        if (cancelled) return
        setData(body)
        setPhase(
          body.patterns.length === 0
            ? { kind: 'unavailable' }
            : { kind: 'choosing' },
        )
      } catch {
        if (!cancelled) setPhase({ kind: 'unavailable' })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [base])

  const toggle = useCallback((key: string) => {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }, [])

  const timezone = data?.timezone ?? 'Australia/Melbourne'

  const selectedTotal = useMemo(() => {
    if (!data) return 0
    return data.patterns
      .filter((p) => selected.includes(p.key))
      .reduce((n, p) => n + p.occurrence_count - p.already_booked_count, 0)
  }, [data, selected])

  async function runPreview() {
    if (selected.length === 0) return
    setPhase({ kind: 'previewing' })
    try {
      const res = await fetch(apiUrl(`${base}/preview`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern_keys: selected }),
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        setPhase({ kind: 'error', message: errorMessage(body) })
        return
      }
      setPhase({ kind: 'preview', preview: body as ReservationPreview })
    } catch {
      setPhase({ kind: 'error', message: 'Could not reach the server.' })
    }
  }

  async function confirm(preview: ReservationPreview) {
    setPhase({ kind: 'reserving', preview })
    try {
      const res = await fetch(apiUrl(`${base}/reserve`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pattern_keys: preview.selected_keys,
          // What the member was actually shown, so the server can name
          // anything that stopped being available in between.
          expected_event_ids: preview.will_reserve.map((o) => o.event_id),
        }),
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        setPhase({ kind: 'error', message: errorMessage(body) })
        return
      }
      setPhase({ kind: 'done', result: body as ReservationResult })
    } catch {
      setPhase({ kind: 'error', message: 'Could not reach the server.' })
    }
  }

  // A Series with nothing ahead to reserve says nothing at all rather
  // than offering an empty control.
  if (phase.kind === 'unavailable') return null

  return (
    <div
      className="rounded-2xl border px-5 py-5"
      style={{ borderColor: borderColour, background: bgColour }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-serif text-lg text-navy-900">
            Reserve your regular sessions
          </p>
          <p className="mt-1 text-[13px]" style={{ color: 'rgba(12,24,38,0.70)' }}>
            {justPurchased
              ? 'Your access is confirmed. Choose the sessions you usually come to and reserve them all at once.'
              : 'Choose the sessions you usually come to and reserve the rest of the term at once.'}
          </p>
        </div>
        {!expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="shrink-0 rounded-lg px-3 py-1.5 text-[12.5px] font-semibold"
            style={{ background: primary, color: '#FFFFFF' }}
          >
            Choose
          </button>
        )}
      </div>

      {expanded && phase.kind === 'loading' && (
        <p className="mt-4 text-[13px] text-slate-600">Loading the schedule…</p>
      )}

      {expanded && phase.kind === 'error' && (
        <div className="mt-4">
          <p className="text-[13px]" style={{ color: '#A64526' }}>{phase.message}</p>
          <button
            type="button"
            onClick={() => setPhase({ kind: 'choosing' })}
            className="mt-3 rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold text-navy-900"
            style={{ borderColor: borderColour }}
          >
            Start again
          </button>
        </div>
      )}

      {/* ── Step 1: choose the weekly slots ─────────────────────────── */}
      {expanded && (phase.kind === 'choosing' || phase.kind === 'previewing') && data && (
        <div className="mt-4">
          <fieldset>
            <legend className="sr-only">Your regular sessions</legend>
            <ul className="space-y-2">
              {data.patterns.map((p: SchedulePattern) => {
                const checked = selected.includes(p.key)
                return (
                  <li key={p.key}>
                    <label
                      className="flex cursor-pointer items-start gap-3 rounded-xl border bg-white px-3 py-2.5"
                      style={{ borderColor: checked ? primary : 'rgba(12,24,38,0.12)' }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(p.key)}
                        className="mt-0.5 h-4 w-4"
                        style={{ accentColor: primary }}
                      />
                      <span className="min-w-0">
                        <span className="block text-[13.5px] font-medium text-navy-900">
                          {p.label}
                        </span>
                        <span className="block text-[12px] text-slate-600">
                          {patternDescription(p)}
                        </span>
                      </span>
                    </label>
                  </li>
                )
              })}
            </ul>
          </fieldset>

          <p className="mt-3 text-[11.5px] text-slate-600">
            Times are shown in this Collective&rsquo;s timezone ({timezone.replace(/_/g, ' ')}).
          </p>

          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              onClick={runPreview}
              disabled={selected.length === 0 || phase.kind === 'previewing'}
              className="rounded-lg px-4 py-2 text-[13px] font-semibold disabled:opacity-50"
              style={{ background: primary, color: '#FFFFFF' }}
            >
              {phase.kind === 'previewing' ? 'Checking…' : 'Review'}
            </button>
            {selected.length > 0 && phase.kind === 'choosing' && (
              <span className="text-[12.5px] text-slate-600">
                Up to {sessionCount(selectedTotal)}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── Step 2: the preview, in full ────────────────────────────── */}
      {expanded && (phase.kind === 'preview' || phase.kind === 'reserving') && (
        <div className="mt-4">
          <p className="text-[13.5px] font-medium text-navy-900">
            {previewHeadline(phase.preview)}
          </p>
          {previewNotes(phase.preview).map((note) => (
            <p key={note} className="mt-1 text-[12.5px] text-slate-600">{note}</p>
          ))}

          {phase.preview.will_reserve.length > 0 && (
            <div className="mt-3">
              <p className="text-[12px] font-semibold uppercase tracking-[0.1em] text-slate-600">
                To be reserved
              </p>
              <DateList
                occurrences={phase.preview.will_reserve}
                timezone={phase.preview.timezone}
                tone="default"
              />
            </div>
          )}

          {phase.preview.already_booked.length > 0 && (
            <div className="mt-3">
              <p className="text-[12px] font-semibold uppercase tracking-[0.1em] text-slate-600">
                Already reserved
              </p>
              <DateList
                occurrences={phase.preview.already_booked}
                timezone={phase.preview.timezone}
                tone="muted"
              />
            </div>
          )}

          {phase.preview.unavailable.length > 0 && (
            <div className="mt-3">
              <p
                className="text-[12px] font-semibold uppercase tracking-[0.1em]"
                style={{ color: '#A64526' }}
              >
                Cannot be reserved
              </p>
              <DateList
                occurrences={phase.preview.unavailable}
                timezone={phase.preview.timezone}
                tone="warn"
                showReason
              />
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => confirm(phase.preview)}
              disabled={
                phase.kind === 'reserving' ||
                phase.preview.new_reservation_count === 0
              }
              className="rounded-lg px-4 py-2 text-[13px] font-semibold disabled:opacity-50"
              style={{ background: primary, color: '#FFFFFF' }}
            >
              {phase.kind === 'reserving'
                ? 'Reserving…'
                : confirmLabel(phase.preview)}
            </button>
            <button
              type="button"
              onClick={() => setPhase({ kind: 'choosing' })}
              disabled={phase.kind === 'reserving'}
              className="rounded-lg border px-3 py-2 text-[12.5px] font-semibold text-navy-900 disabled:opacity-50"
              style={{ borderColor: borderColour }}
            >
              Change selection
            </button>
          </div>
        </div>
      )}

      {/* ── Step 3: what actually happened ──────────────────────────── */}
      {expanded && phase.kind === 'done' && (
        <div className="mt-4">
          <p className="text-[13.5px] font-medium text-navy-900">
            {resultHeadline(phase.result)}
          </p>

          {phase.result.changed_since_preview.length > 0 && (
            <div className="mt-3">
              <p
                className="text-[12px] font-semibold uppercase tracking-[0.1em]"
                style={{ color: '#A64526' }}
              >
                Changed while you were deciding
              </p>
              <DateList
                occurrences={phase.result.changed_since_preview}
                timezone={phase.result.timezone}
                tone="warn"
                showReason
              />
            </div>
          )}

          {resultNeedsAttention(phase.result) &&
            phase.result.unavailable.length > 0 && (
            <div className="mt-3">
              <p
                className="text-[12px] font-semibold uppercase tracking-[0.1em]"
                style={{ color: '#A64526' }}
              >
                Left unreserved
              </p>
              <DateList
                occurrences={phase.result.unavailable}
                timezone={phase.result.timezone}
                tone="warn"
                showReason
              />
            </div>
          )}

          {phase.result.reserved.length > 0 && (
            <div className="mt-3">
              <p className="text-[12px] font-semibold uppercase tracking-[0.1em] text-slate-600">
                Reserved
              </p>
              <DateList
                occurrences={phase.result.reserved}
                timezone={phase.result.timezone}
                tone="default"
              />
            </div>
          )}

          <p className="mt-3 text-[11.5px] text-slate-600">
            Each of these is an ordinary reservation — you can cancel any
            single session from its Gathering page without affecting the
            others.
          </p>

          <button
            type="button"
            onClick={() => {
              setSelected([])
              setPhase({ kind: 'choosing' })
            }}
            className="mt-3 rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold text-navy-900"
            style={{ borderColor: borderColour }}
          >
            Choose more sessions
          </button>
        </div>
      )}
    </div>
  )
}
