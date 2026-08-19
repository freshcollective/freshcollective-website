'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

/**
 * Payment Options index — one card per option.
 *
 * Design goals from the U1 brief:
 *   * one row per Payment Option (not per Pathway / per Series)
 *   * make clear at a glance: name, status, what's included,
 *     access details, payment methods, purchasability
 *   * do NOT hard-code EMBODY vocabulary — the shape reads for
 *     "Standard Ticket · Women's Winter Circle · $45 once" just
 *     as cleanly as for "Awaken · EMBODY Term · $200"
 */

interface GrantTarget {
  id: string
  title: string
  slug: string | null
}

interface Grant {
  id: string
  grant_kind: 'pathway' | 'event_series' | 'gathering'
  pathway_id: string | null
  series_id: string | null
  event_id: string | null
  sessions_per_week: number | null
  total_sessions: number | null
  valid_from_override: string | null
  valid_until_override: string | null
  position: number
  target: GrantTarget | null
}

interface Schedule {
  id: string
  name: string
  schedule_type: 'pay_in_full' | 'recurring_installments' | 'manual'
  status: 'draft' | 'published' | 'archived'
  total_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  /** FIP4C — mirrors the backend-authoritative "can members
   *  actually check out through this schedule right now?" flag.
   *  Driven by ``spaces.routes._schedule_is_member_checkoutable``
   *  and reflects both the platform-level
   *  ``FINITE_PLAN_MEMBER_CHECKOUT_ENABLED`` gate and per-option
   *  eligibility. UI consumers use this to render truthful copy in
   *  both gate positions. */
  is_member_checkoutable?: boolean
}

export interface PaymentOptionRow {
  id: string
  name: string
  description: string | null
  status: 'draft' | 'published' | 'archived'
  payment_type: 'free' | 'one_time' | 'term_pass' | 'subscription'
  currency: string
  effective_price_cents: number | null
  grants: Grant[]
  schedules: Schedule[]
  purchasability:
    | 'ready'
    | 'configured_not_yet_checkoutable'
    | 'needs_attention'
    | 'draft'
    | 'archived'
    | 'unknown'
  purchasability_notes: string[]
}

function formatMoney(cents: number, currency: string): string {
  const symbol = currency === 'AUD' || currency === 'USD' ? '$' : `${currency} `
  const dollars = cents / 100
  return `${symbol}${Number.isInteger(dollars) ? dollars : dollars.toFixed(2)}`
}

function statusPill(status: PaymentOptionRow['status']) {
  const map: Record<string, { label: string; className: string }> = {
    draft: { label: 'Draft', className: 'bg-slate-100 text-slate-600' },
    published: { label: 'Published', className: 'bg-teal-50 text-teal-700 ring-1 ring-teal-200' },
    archived: { label: 'Archived', className: 'bg-slate-100 text-slate-400' },
  }
  const cfg = map[status] ?? map.draft
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${cfg.className}`}
    >
      {cfg.label}
    </span>
  )
}

function purchasabilityBadge(row: PaymentOptionRow) {
  if (row.purchasability === 'ready') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">
        <span aria-hidden>●</span> Ready to sell
      </span>
    )
  }
  if (row.purchasability === 'configured_not_yet_checkoutable') {
    // FIP4C — this state now fires almost exclusively for finite
    // payment plans while the platform-level
    // ``FINITE_PLAN_MEMBER_CHECKOUT_ENABLED`` gate is off. Old copy
    // ("checkout coming later") implied unfinished platform work,
    // which is no longer true — FIP4A/FIP4B shipped. The truthful
    // reading is "you're done authoring; the platform gate for this
    // payment method is currently off". When the gate is on, the
    // option graduates to ``ready`` and this badge doesn't render.
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-700 ring-1 ring-amber-200">
        Configured — checkout not enabled
      </span>
    )
  }
  if (row.purchasability === 'needs_attention') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-red-50 px-2 py-1 text-[11px] font-medium text-red-700 ring-1 ring-red-200">
        Needs attention
      </span>
    )
  }
  if (row.purchasability === 'draft') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-600">
        Draft
      </span>
    )
  }
  if (row.purchasability === 'archived') return null
  return null
}

/** Human-friendly "What's included" list. Uses each grant's
 *  ``target.title`` snapshot from the server so the UI never has to
 *  guess which Pathway / Series a grant points at. */
function includedList(row: PaymentOptionRow): { key: string; label: string; kind: string }[] {
  return row.grants.map((g) => {
    const label = g.target?.title ?? `${g.grant_kind} (missing target)`
    return { key: g.id, label, kind: g.grant_kind }
  })
}

/** Access allowance summary — only meaningful for Series grants
 *  today. Shown once per Series-carrying option. */
function accessSummary(row: PaymentOptionRow): string | null {
  const seriesGrants = row.grants.filter((g) => g.grant_kind === 'event_series')
  if (!seriesGrants.length) return null
  const parts: string[] = []
  for (const g of seriesGrants) {
    if (g.sessions_per_week != null) parts.push(`${g.sessions_per_week} Gathering/week`)
    if (g.total_sessions != null) parts.push(`${g.total_sessions} total`)
  }
  return parts.length ? parts.join(' · ') : null
}

/** Human summary of the payment methods on this option — one line
 *  per published schedule, plus a muted line for draft schedules so
 *  the Creator can see everything without opening the editor. */
function paymentSummary(row: PaymentOptionRow): { key: string; text: string; dim: boolean }[] {
  if (!row.schedules.length) return []
  return row.schedules.map((s) => {
    const dim = s.status !== 'published'
    let text = ''
    if (s.schedule_type === 'pay_in_full') {
      const amt = s.total_amount_cents != null ? formatMoney(s.total_amount_cents, s.currency) : '—'
      text = `${amt} pay in full`
    } else if (s.schedule_type === 'recurring_installments') {
      const each = s.installment_amount_cents != null
        ? formatMoney(s.installment_amount_cents, s.currency)
        : '—'
      const cadence =
        s.interval === 'week' ? '/week' :
        s.interval === 'fortnight' ? '/fortnight' :
        s.interval === 'month' ? '/month' :
        s.interval ? `/${s.interval}` : ''
      const count = s.installment_count != null ? ` × ${s.installment_count}` : ''
      text = `${each}${cadence}${count}`
    } else if (s.schedule_type === 'manual') {
      text = 'Manual arrangement'
    }
    if (dim) text = `${text} (${s.status})`
    return { key: s.id, text, dim }
  })
}

export default function PaymentOptionsIndexClient({ spaceSlug }: { spaceSlug: string }) {
  const [rows, setRows] = useState<PaymentOptionRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [includeArchived, setIncludeArchived] = useState(false)

  useEffect(() => {
    const url = apiUrl(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options` +
      (includeArchived ? '?include_archived=true' : ''),
    )
    setRows(null)
    setError(null)
    fetch(url, { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
        return r.json() as Promise<PaymentOptionRow[]>
      })
      .then(setRows)
      .catch((err) => setError(String(err?.message ?? err)))
  }, [spaceSlug, includeArchived])

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-[13px] text-red-800">
        Couldn't load Payment Options: {error}
      </div>
    )
  }

  if (rows === null) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-[13px] text-slate-500">
        Loading Payment Options…
      </div>
    )
  }

  if (!rows.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
        <p className="font-serif text-lg text-navy-900">No Payment Options yet.</p>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-600">
          A Payment Option bundles one or more experiences from this Collective and
          sets how members can pay for the bundle.
        </p>
        <div className="mt-5">
          <Link
            href="/creator-studio/payment-options/new"
            className="inline-flex items-center rounded-md bg-teal-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-teal-700"
          >
            Create a Payment Option
          </Link>
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="mb-3 flex items-center justify-between text-[12px]">
        <label className="inline-flex items-center gap-2 text-slate-600">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
            className="rounded border-slate-300"
          />
          Include archived
        </label>
        <p className="text-slate-500">{rows.length} Payment Option{rows.length === 1 ? '' : 's'}</p>
      </div>

      <ul className="space-y-3">
        {rows.map((row) => {
          const included = includedList(row)
          const access = accessSummary(row)
          const payments = paymentSummary(row)
          return (
            <li key={row.id}>
              <Link
                href={`/creator-studio/payment-options/${row.id}`}
                className="block rounded-xl border border-slate-200 bg-white p-5 transition-colors hover:border-teal-300 hover:bg-teal-50/30"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="font-serif text-lg text-navy-900">{row.name}</h3>
                      {statusPill(row.status)}
                    </div>
                    {row.description && (
                      <p className="mt-1 line-clamp-2 text-[13px] text-slate-600">{row.description}</p>
                    )}
                  </div>
                  <div className="shrink-0">{purchasabilityBadge(row)}</div>
                </div>

                <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
                  <section>
                    <h4 className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
                      Includes
                    </h4>
                    {included.length ? (
                      <ul className="mt-1.5 space-y-0.5 text-[13px] text-navy-900">
                        {included.map((it) => (
                          <li key={it.key}>
                            {it.label}
                            {it.kind === 'event_series' && (
                              <span className="ml-1.5 text-[11px] text-slate-500">· Series</span>
                            )}
                            {it.kind === 'gathering' && (
                              <span className="ml-1.5 text-[11px] text-slate-500">· Gathering</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1.5 text-[13px] italic text-slate-400">Nothing selected yet</p>
                    )}
                  </section>

                  <section>
                    <h4 className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
                      Access
                    </h4>
                    <p className="mt-1.5 text-[13px] text-navy-900">
                      {access ?? <span className="italic text-slate-400">—</span>}
                    </p>
                  </section>

                  <section>
                    <h4 className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
                      Payment
                    </h4>
                    {payments.length ? (
                      <ul className="mt-1.5 space-y-0.5 text-[13px]">
                        {payments.map((p) => (
                          <li key={p.key} className={p.dim ? 'text-slate-400' : 'text-navy-900'}>
                            {p.text}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1.5 text-[13px] italic text-slate-400">No payment method</p>
                    )}
                  </section>
                </div>

                {row.purchasability_notes.length > 0 && (
                  <ul className="mt-3 space-y-1 text-[12px] text-slate-500">
                    {row.purchasability_notes.map((n, i) => (
                      <li key={i}>· {n}</li>
                    ))}
                  </ul>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
    </>
  )
}
