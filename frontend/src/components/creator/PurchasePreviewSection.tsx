'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  type OptionGroup,
  type PreviewArrangement,
  type PreviewKind,
  type PurchasePreview,
  type StatusTone,
  accessExplanation,
  alsoIncluded,
  arrangementExplanation,
  arrangementKey,
  arrangementPaymentLine,
  arrangementStatus,
  arrangementTitle,
  arrangementTotalLine,
  arrangementUpfrontWarning,
  groupByOption,
  includedKindLabel,
} from '@/lib/purchasePreview'

/**
 * "How members can access this" — read-only, Stage 1B.1.
 *
 * One component for the Pathway editor and the Gathering editor,
 * because the question is the same one and the answer comes from the
 * same resolver. Everything shown here is derived server-side; this
 * file renders and words it, and offers no control that writes.
 *
 * It replaces the Pathway editor's old Payment Options reference
 * block, which listed Option names and statuses but no prices,
 * schedules or purchasability — so a creator could read it and still
 * not know what a member would pay, or whether they could pay at all.
 * Two adjacent sections both listing Payment Options would be the
 * duplication this stage was told to avoid, so this supersedes it
 * rather than sitting beside it.
 */

const TONE_CLASSES: Record<StatusTone, string> = {
  available: 'bg-teal-50 text-teal-700 ring-1 ring-teal-200',
  draft: 'bg-slate-100 text-slate-600',
  archived: 'bg-slate-100 text-slate-400',
  pending: 'bg-amber-50 text-amber-800 ring-1 ring-amber-200',
  attention: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',
}

function StatusBadge({ arrangement }: { arrangement: PreviewArrangement }) {
  const { label, tone } = arrangementStatus(arrangement)
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  )
}

/** One payment arrangement: what it is, what it costs, whether it
 *  sells. No control — the row is prose and a badge. */
function ArrangementRow({
  arrangement, kind, title,
}: {
  arrangement: PreviewArrangement
  kind: PreviewKind
  /** Overridden for a schedule inside an Option group, where the
   *  Option's name is already the group heading. */
  title: string
}) {
  const total = arrangementTotalLine(arrangement)
  const upfrontWarning = arrangementUpfrontWarning(arrangement)
  const explanation = arrangementExplanation(arrangement, kind)

  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5 px-3.5 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-medium text-navy-900">{title}</p>
        <p className="mt-0.5 text-[13.5px] text-navy-800">
          {arrangementPaymentLine(arrangement)}
          {total && (
            <span className="text-slate-500"> &middot; {total}</span>
          )}
        </p>
        {upfrontWarning && (
          /* Amber, and worded as a discrepancy rather than an error:
             the schedule sells perfectly well, it is the deposit that
             does nothing. Rendered above the availability explanation
             because it is about money the creator thinks they are
             collecting. */
          <p className="mt-1.5 rounded-md bg-amber-50 px-2.5 py-2 text-[12.5px] leading-relaxed text-amber-900">
            {upfrontWarning}
          </p>
        )}
        {explanation && (
          <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">
            {explanation}
          </p>
        )}
      </div>
      <StatusBadge arrangement={arrangement} />
    </div>
  )
}

function OptionCard({
  group, preview,
}: {
  group: OptionGroup
  preview: PurchasePreview
}) {
  const extras = alsoIncluded(group, preview)
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-slate-100 bg-slate-50/60 px-3.5 py-2.5">
        <p className="text-[13.5px] font-semibold text-navy-900">{group.name}</p>
        <Link
          href={`/creator-studio/payment-options/${group.payment_option_id}`}
          className="text-[12.5px] font-medium text-teal-700 underline-offset-2 transition-colors hover:text-teal-800 hover:underline"
        >
          Edit this option
        </Link>
      </div>
      {extras.length > 0 && (
        <p className="border-b border-slate-100 px-3.5 py-2 text-[12.5px] text-slate-600">
          Also includes{' '}
          {extras
            .map((inc) => inc.title ?? includedKindLabel(inc.kind))
            .join(', ')}
          .
        </p>
      )}
      <div className="divide-y divide-slate-100">
        {group.schedules.map((schedule, i) => (
          <ArrangementRow
            key={arrangementKey(schedule, i)}
            arrangement={schedule}
            kind={preview.experience_kind}
            title={
              schedule.schedule_name
              ?? (schedule.schedule_type === 'recurring_installments'
                ? 'Payment plan'
                : 'Pay in full')
            }
          />
        ))}
      </div>
    </div>
  )
}

export default function PurchasePreviewSection({
  spaceSlug, kind, experienceId, heading, helperText,
}: {
  spaceSlug: string
  kind: PreviewKind
  experienceId: string
  heading: string
  helperText: string
}) {
  // One state value, stamped with the experience it describes, rather
  // than a data slot cleared at the top of the effect. Clearing
  // synchronously in the effect body is a cascading render, and the
  // stamp also makes a late response for a previous experience
  // unrenderable rather than merely unlikely.
  const [loaded, setLoaded] = useState<{
    id: string
    data: PurchasePreview | null
    error: string | null
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(
      apiUrl(
        `/api/creator/spaces/${spaceSlug}/purchase-preview/${kind}/${experienceId}`,
      ),
      { credentials: 'include' },
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status))
        return (await r.json()) as PurchasePreview
      })
      .then((data) => {
        if (!cancelled) setLoaded({ id: experienceId, data, error: null })
      })
      .catch(() => {
        if (!cancelled) {
          setLoaded({
            id: experienceId,
            data: null,
            error: 'Could not load purchase arrangements.',
          })
        }
      })
    return () => { cancelled = true }
  }, [spaceSlug, kind, experienceId])

  const current = loaded?.id === experienceId ? loaded : null
  const preview = current?.data ?? null
  const error = current?.error ?? null

  const direct = preview?.arrangements.find((a) => a.source === 'direct') ?? null
  const groups = preview ? groupByOption(preview) : []
  const isEmpty = preview != null && preview.arrangements.length === 0

  return (
    <section
      className="mt-8 rounded-xl bg-white p-6"
      style={{ border: '1px solid #E2E8F0' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-[560px]">
          <h2 className="font-serif text-xl text-navy-900">{heading}</h2>
          <p className="mt-1 text-[13px] leading-relaxed text-slate-600">
            {helperText}
          </p>
        </div>
        <Link
          href="/creator-studio/payment-options"
          className="inline-flex items-center rounded-md bg-teal-600 px-3.5 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-700"
        >
          Manage Payment Options &rarr;
        </Link>
      </div>

      <div className="mt-5">
        {error && (
          <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[12.5px] text-slate-700">
            {error}
          </p>
        )}

        {preview === null && !error && (
          <p className="text-[13px] text-slate-500">Loading&hellip;</p>
        )}

        {isEmpty && preview && (() => {
          const { text, isGap } = accessExplanation(preview)
          return (
            <p
              className={
                isGap
                  ? 'rounded-md border border-amber-200 bg-amber-50 px-3.5 py-3 text-[13px] leading-relaxed text-amber-900'
                  : 'rounded-md border border-dashed border-slate-300 bg-slate-50 px-3.5 py-3 text-[13px] leading-relaxed text-slate-600'
              }
            >
              {text}
            </p>
          )
        })()}

        {preview && preview.arrangements.length > 0 && (
          <div className="space-y-3">
            {direct && (
              <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                <ArrangementRow
                  arrangement={direct}
                  kind={preview.experience_kind}
                  title={arrangementTitle(direct, preview.experience_kind)}
                />
              </div>
            )}
            {groups.map((group) => (
              <OptionCard
                key={group.payment_option_id}
                group={group}
                preview={preview}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
