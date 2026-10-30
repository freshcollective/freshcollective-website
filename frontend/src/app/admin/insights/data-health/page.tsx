'use client'

import { useEffect, useState } from 'react'

import { InsightsShell } from '@/components/admin/insights/InsightsShell'
import {
  type ReportingHealth,
  type ReportingJobRun,
  describeHealth,
  fetchHealth,
  formatCount,
} from '@/lib/insights'
import { WM_HUE } from '@/lib/wm-palette'

/**
 * Can these figures be trusted?
 *
 * Establishing that used to mean a Render Shell and a hand-built
 * diagnostic. This page answers it from the browser: whether history is
 * being recorded, when the last event arrived, whether anything has
 * happened without being recorded, how current the daily trends are, and
 * whether last night's rebuild worked.
 *
 * The hardest thing to get right here is *not* crying wolf. A quiet week
 * on a small platform is normal, and a panel that reported it as a
 * failure would teach somebody to ignore the panel — so an absence of
 * activity is stated as a fact and nothing more. The reconciliation
 * checks separate the three cases deliberately: history that predates
 * recording, history that can never be reconstructed, and a genuine gap
 * that means something is missing a producer.
 */

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'
const CARD = { background: '#FFFFFF', border: '1px solid #E7EEF0' }

export default function DataHealthPage() {
  const [health, setHealth] = useState<ReportingHealth | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then(setHealth)
      .catch((e: Error) => {
        if (e.name !== 'AbortError') setError(e.message)
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  const state = describeHealth(health, Boolean(error))

  return (
    <InsightsShell
      title="Data health"
      intro="Whether the figures elsewhere in World Insights can be relied on, and what they cannot yet tell you."
    >
      {loading && !health && (
        <p className="py-10 text-center text-[13.5px]" style={{ color: INK_MUTED }}>
          Checking…
        </p>
      )}

      {error && (
        <div
          className="rounded-2xl p-5"
          style={{
            background: 'rgba(214, 96, 87, 0.06)',
            border: '1px solid rgba(214, 96, 87, 0.28)',
          }}
        >
          <p className="text-[13.5px]" style={{ color: '#a63c30' }}>
            {error}
          </p>
        </div>
      )}

      {health && (
        <>
          <div
            className="mb-6 rounded-2xl p-5"
            style={{
              background: WM_HUE[state.hue].bg,
              border: `1px solid ${WM_HUE[state.hue].border}`,
            }}
          >
            <p
              className="font-serif text-[20px] leading-tight"
              style={{ color: WM_HUE[state.hue].text }}
            >
              {state.label}
            </p>
            {health.note && (
              <p className="mt-2 max-w-[74ch] text-[13px]" style={{ color: INK }}>
                {health.note}
              </p>
            )}
          </div>

          <Section title="Recording history">
            <Row
              label="Recording business events"
              value={health.recording_enabled ? 'On' : 'Off'}
              tone={health.recording_enabled ? 'teal' : 'coral'}
            />
            <Row
              label="Events recorded"
              value={formatCount(health.events_total)}
              tone="navy"
            />
            <Row
              label="Most recent event"
              value={
                health.latest_event_at
                  ? friendly(health.latest_event_at)
                  : 'None yet'
              }
              tone="navy"
              hint={
                health.latest_event_at
                  ? 'A gap here is normal when the platform is quiet.'
                  : 'Nothing has happened that we record yet.'
              }
            />
            <Row
              label="Recording began"
              value={
                health.activation_floor
                  ? friendly(health.activation_floor)
                  : 'Not started'
              }
              tone="navy"
              hint="Anything before this date cannot be reconstructed."
            />
          </Section>

          <Section title="Daily trends">
            <Row
              label="Stored rows"
              value={formatCount(health.aggregates.rows_total)}
              tone={health.aggregates.rows_total > 0 ? 'teal' : 'navy'}
              hint={
                health.aggregates.rows_total === 0
                  ? 'Built nightly. Live figures do not depend on these.'
                  : undefined
              }
            />
            <Row
              label="Metrics with stored history"
              value={formatCount(health.aggregates.metrics_stored)}
              tone="navy"
            />
            <Row
              label="Trends current to"
              value={health.aggregates.oldest_latest_reporting_date ?? 'Not built yet'}
              tone="navy"
              hint="The least current series, since a trend is only as fresh as its oldest part."
            />
            <JobRow label="Last rebuild" run={health.last_run} />
            <JobRow label="Last successful rebuild" run={health.last_successful_run} />
            {health.incomplete_runs.length > 0 && (
              <Row
                label="Runs that never finished"
                value={formatCount(health.incomplete_runs.length)}
                tone="coral"
                hint="A rebuild started and stopped without reporting an outcome. Re-running it is safe."
              />
            )}
          </Section>

          <Section title="What the records say">
            <p className="mb-3 max-w-[74ch] text-[12.5px]" style={{ color: INK_MUTED }}>
              Each check looks for something that happened without being
              recorded. &ldquo;Before recording&rdquo; and &ldquo;cannot be
              reconstructed&rdquo; are expected and need nothing from you; only
              &ldquo;missing&rdquo; means a gap worth investigating.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[46rem] text-[12.5px]">
                <thead>
                  <tr style={{ color: INK_SOFTER }}>
                    <th className="py-2 pr-3 text-left font-medium">Check</th>
                    <th className="py-2 pr-3 text-right font-medium">Missing</th>
                    <th className="py-2 pr-3 text-right font-medium">
                      Before recording
                    </th>
                    <th className="py-2 pr-3 text-right font-medium">
                      Cannot reconstruct
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {health.checks.map((c) => (
                    <tr
                      key={c.name}
                      style={{ borderTop: '1px solid rgba(12, 24, 38, 0.06)' }}
                    >
                      <td className="py-2 pr-3" style={{ color: INK }}>
                        {humanise(c.name)}
                        {c.note && (
                          <span
                            className="block text-[11.5px]"
                            style={{ color: INK_SOFTER }}
                          >
                            {c.note}
                          </span>
                        )}
                      </td>
                      <td
                        className="py-2 pr-3 text-right tabular-nums"
                        style={{
                          color: c.missing > 0 ? WM_HUE.coral.text : INK_MUTED,
                          fontWeight: c.missing > 0 ? 600 : 400,
                        }}
                      >
                        {formatCount(c.missing)}
                      </td>
                      <td
                        className="py-2 pr-3 text-right tabular-nums"
                        style={{ color: INK_MUTED }}
                      >
                        {formatCount(c.pre_activation)}
                      </td>
                      <td
                        className="py-2 pr-3 text-right tabular-nums"
                        style={{ color: INK_MUTED }}
                      >
                        {formatCount(c.unreconstructable)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
    </InsightsShell>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-7">
      <h3
        className="mb-3 font-serif text-[17px] leading-tight"
        style={{ color: INK }}
      >
        {title}
      </h3>
      <div className="rounded-2xl p-1.5" style={CARD}>
        {children}
      </div>
    </section>
  )
}

function Row({
  label,
  value,
  tone,
  hint,
}: {
  label: string
  value: string
  tone: 'teal' | 'navy' | 'gold' | 'coral'
  hint?: string
}) {
  return (
    <div
      className="flex flex-wrap items-baseline justify-between gap-2 px-3.5 py-2.5"
      style={{ borderBottom: '1px solid rgba(12, 24, 38, 0.05)' }}
    >
      <div>
        <p className="text-[13px]" style={{ color: INK }}>
          {label}
        </p>
        {hint && (
          <p className="text-[11.5px]" style={{ color: INK_SOFTER }}>
            {hint}
          </p>
        )}
      </div>
      <p
        className="text-[13px] tabular-nums"
        style={{ color: WM_HUE[tone].text, fontWeight: 600 }}
      >
        {value}
      </p>
    </div>
  )
}

function JobRow({
  label,
  run,
}: {
  label: string
  run: ReportingJobRun | null
}) {
  if (!run) {
    return (
      <Row
        label={label}
        value="Never"
        tone="navy"
        hint="Scheduled nightly. Live figures do not depend on it."
      />
    )
  }
  const tone =
    run.status === 'succeeded' ? 'teal' : run.status === 'failed' ? 'coral' : 'gold'
  return (
    <Row
      label={label}
      value={`${friendly(run.started_at)} — ${run.status}`}
      tone={tone}
      hint={
        run.error
          ? run.error
          : `${formatCount(run.days_processed)} day(s), ${formatCount(
              run.rows_written,
            )} figures written.`
      }
    />
  )
}

/** Timestamps arrive as naive UTC; show them in the reader's own time. */
function friendly(iso: string): string {
  const withZone = iso.endsWith('Z') ? iso : `${iso}Z`
  const d = new Date(withZone)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-AU', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** `memberships_without_a_start_event` → `Memberships without a start event`. */
function humanise(name: string): string {
  const words = name.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
