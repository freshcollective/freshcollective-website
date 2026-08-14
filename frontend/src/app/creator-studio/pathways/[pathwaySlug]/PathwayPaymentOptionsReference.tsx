'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

/**
 * Pathway → Payment Options reference block.
 *
 * Replaces the legacy Pathway-scoped Payment Option CRUD. The
 * Pathway is no longer treated as the "owner" of a Payment Option —
 * PaymentOption is a Collective-level object that may grant access
 * to this Pathway (alongside others).
 *
 * Reads
 * ``GET /api/creator/spaces/{slug}/pathways/{pathway_slug}/payment-option-references``
 * — one row per Payment Option that lists this Pathway in a grant.
 */

interface Reference {
  payment_option_id: string
  payment_option_name: string
  payment_option_status: 'draft' | 'published' | 'archived'
  grant_kind: string
  sessions_per_week: number | null
  total_sessions: number | null
}

function statusBadge(status: Reference['payment_option_status']) {
  const map: Record<string, { label: string; className: string }> = {
    draft: { label: 'Draft', className: 'bg-slate-100 text-slate-600' },
    published: { label: 'Published', className: 'bg-teal-50 text-teal-700 ring-1 ring-teal-200' },
    archived: { label: 'Archived', className: 'bg-slate-100 text-slate-400' },
  }
  const cfg = map[status] ?? map.draft
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider ${cfg.className}`}
    >
      {cfg.label}
    </span>
  )
}

export default function PathwayPaymentOptionsReference({
  spaceSlug, pathwaySlug,
}: {
  spaceSlug: string
  pathwaySlug: string
}) {
  const [rows, setRows] = useState<Reference[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(
      apiUrl(
        `/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-option-references`,
      ),
      { credentials: 'include' },
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}`)
        return r.json() as Promise<Reference[]>
      })
      .then(setRows)
      .catch((err) => setError(String(err?.message ?? err)))
  }, [spaceSlug, pathwaySlug])

  return (
    <section
      className="mt-8 rounded-xl bg-white p-6"
      style={{ border: '1px solid #E2E8F0' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl text-navy-900">Payment Options</h2>
          <p className="mt-1 text-[13px] text-slate-600">
            Payment Options are now managed centrally at the Collective level.
            This Pathway can be included in one or more of them.
          </p>
        </div>
        <Link
          href="/creator-studio/payment-options"
          className="inline-flex items-center rounded-md bg-teal-600 px-3.5 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-700"
        >
          Manage Payment Options →
        </Link>
      </div>

      <div className="mt-5">
        {error && (
          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-800">
            Couldn't load references: {error}
          </p>
        )}
        {rows === null && !error && (
          <p className="text-[13px] text-slate-500">Loading…</p>
        )}
        {rows && rows.length === 0 && (
          <p className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-[13px] italic text-slate-600">
            This Pathway isn't included in any Payment Option yet.
            Create one from <strong>Commerce → Payment Options</strong>.
          </p>
        )}
        {rows && rows.length > 0 && (
          <>
            <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
              This Pathway is included in
            </p>
            <ul className="space-y-1.5">
              {rows.map((r) => (
                <li key={r.payment_option_id}>
                  <Link
                    href={`/creator-studio/payment-options/${r.payment_option_id}`}
                    className="flex items-center justify-between rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2 text-[13.5px] text-navy-900 transition-colors hover:border-teal-300 hover:bg-teal-50/40"
                  >
                    <span>{r.payment_option_name}</span>
                    {statusBadge(r.payment_option_status)}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  )
}
