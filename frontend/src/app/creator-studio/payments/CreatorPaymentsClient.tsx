'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import RevokeAccessModal, { type RevokeResult } from './RevokeAccessModal'

interface CreatorPaymentSummary {
  total_gross_amount_cents: number
  total_platform_fee_cents: number
  total_creator_net_amount_cents: number
  pending_payout_cents: number
  /** Cumulative refunded amount across in-scope rows (rows whose
   *  payment historically succeeded — includes fully-refunded rows
   *  in the base set so Gross remains a historical figure). */
  total_refunded_amount_cents: number
  /** Gross Sales minus Refunds — what the collective has actually
   *  retained after refunds. */
  total_net_retained_amount_cents: number
  succeeded_count: number
  refunded_count: number
  /** Sub-count of ``refunded_count`` — rows currently in the
   *  ``partially_refunded`` state (some money kept, some returned). */
  partially_refunded_count: number
  disputed_count: number
  pending_count: number
}

interface CreatorPaymentTransaction {
  id: string
  transaction_type: string
  status: string
  payment_provider: string | null
  payer_user_id: string | null
  payer_name: string | null
  payer_email: string | null
  space_id: string | null
  space_name: string | null
  pathway_id: string | null
  payment_option_id: string | null
  payment_option_name: string | null
  payment_option_schedule_id: string | null
  currency: string
  gross_amount_cents: number
  platform_fee_basis_points: number
  platform_fee_cents: number
  net_creator_amount_cents: number | null
  /** FIP4C — plan context. Populated on finite-plan instalment rows;
   *  NULL on pay-in-full rows. Used to render a compact
   *  "Payment plan · Instalment 2 of 6" badge without exposing any
   *  Stripe / provider ids. Each instalment row stays its own ledger
   *  entry — no aggregation, no fake combined transaction. */
  purchase_plan_id: string | null
  installment_number: number | null
  /** Cumulative refunded amount on this transaction (Stripe's
   *  ``charge.amount_refunded``). Zero when there has been no refund.
   *  Payment ``status`` reflects the state — ``succeeded`` / ``partially_refunded``
   *  / ``refunded`` — and is monotonic (never downgrades on out-of-
   *  order webhook events). */
  refunded_amount_cents: number
  /** Timestamp of the most recent refund event, or null. */
  last_refunded_at: string | null
  /** Grant lifecycle indicator, orthogonal to Stripe payment status.
   *  Values: intact | partially_revoked | fully_revoked | no_grant_records.
   *  Derived server-side from the AccessPass + reachable
   *  PathwayEntitlement rows for the transaction. Determines whether
   *  the Revoke access button shows (intact + partially_revoked) and
   *  which "Access revoked" chip renders. */
  grant_state: 'intact' | 'partially_revoked' | 'fully_revoked' | 'no_grant_records'
  /** Earliest admin revoke timestamp across the grant universe. NULL
   *  for intact / no_grant_records. */
  grant_revoked_at: string | null
  notes: string | null
  created_at: string
}

function PlanContextBadge({ row }: { row: CreatorPaymentTransaction }) {
  if (!row.purchase_plan_id) return null
  const inst = row.installment_number
  return (
    <span
      className="ml-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium text-slate-600"
      style={{ borderColor: '#E2E8F0', background: '#F8FAFC' }}
      title="This payment belongs to a finite payment plan agreement."
    >
      Payment plan{inst != null ? ` · Instalment ${inst}` : ''}
    </span>
  )
}

function providerLabel(row: CreatorPaymentTransaction): string {
  if (row.payment_provider === 'manual') return 'Manual'
  if (row.payment_provider === 'stripe') return row.status === 'succeeded' ? 'Card' : 'Card (pending)'
  return row.payment_provider ?? '—'
}

function fmt(cents: number, currency: string) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
  }).format(cents / 100)
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function labelType(t: string) {
  return t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Small secondary chip next to the payment StatusBadge. Present only
 *  when access has been administratively touched — silent for
 *  ``intact`` and ``no_grant_records`` so intact rows stay quiet. */
function GrantStateChip({ state }: { state: CreatorPaymentTransaction['grant_state'] }) {
  if (state === 'fully_revoked') {
    return (
      <span
        className="ml-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-semibold"
        style={{ background: '#FEF2F2', color: '#B91C1C', borderColor: '#FCA5A5' }}
        title="Every access grant from this purchase has been revoked."
      >
        Access revoked
      </span>
    )
  }
  if (state === 'partially_revoked') {
    return (
      <span
        className="ml-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-semibold"
        style={{ background: '#FFFBEB', color: '#B45309', borderColor: '#FDE68A' }}
        title="Some grants from this purchase have been revoked; others remain active."
      >
        Access partially revoked
      </span>
    )
  }
  return null
}

/** Show the Revoke access action when: caller is a platform admin,
 *  the purchase is not plan-anchored (endpoint 409s otherwise), and
 *  something remains to revoke (``intact`` or ``partially_revoked``).
 *  Deliberately NOT keyed on ``row.status`` — refund status and
 *  grant state are separate concepts; a refunded payment with
 *  active grants must still be revocable here. */
function canRevoke(row: CreatorPaymentTransaction, isPlatformOwner: boolean): boolean {
  if (!isPlatformOwner) return false
  if (row.purchase_plan_id) return false
  return row.grant_state === 'intact' || row.grant_state === 'partially_revoked'
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    succeeded:          'bg-teal-50 text-teal-700 border-teal-200',
    pending:            'bg-amber-50 text-amber-700 border-amber-200',
    failed:             'bg-red-50 text-red-700 border-red-200',
    refunded:           'bg-slate-100 text-slate-600 border-slate-200',
    partially_refunded: 'bg-orange-50 text-orange-700 border-orange-200',
    disputed:           'bg-purple-50 text-purple-700 border-purple-200',
    cancelled:          'bg-slate-100 text-slate-500 border-slate-200',
  }
  const cls = styles[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function SummaryCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: boolean
}) {
  return (
    <div className="rounded-xl bg-white p-4" style={{ border: '1px solid #E2E8F0' }}>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-black">{label}</p>
      <p className={`text-[1.35rem] font-bold leading-none ${accent ? 'text-teal-600' : 'text-[#0F172A]'}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-[11px] text-black">{sub}</p>}
    </div>
  )
}

// (Removed the outdated ``PRICING_OPTIONS`` card grid — the "Coming
//  soon" pricing marketing block predates Commerce → Payment Options.
//  The Payments page is now transaction-led; how members can pay is
//  authored in ``/creator-studio/payment-options``.)

export default function CreatorPaymentsClient({
  feeBasisPoints,
  currency,
  stripeEnabled,
  stripeTestMode,
  isPlatformOwner,
  headerCollectiveName,
  headerLocation,
  headerCoverImageUrl,
}: {
  feeBasisPoints: number
  currency: string
  stripeEnabled: boolean
  stripeTestMode: boolean
  isPlatformOwner: boolean
  headerCollectiveName: string | null
  headerLocation: { name?: string; hero_artwork_url?: string | null; thumbnail_artwork_url?: string | null } | null
  headerCoverImageUrl: string | null
}) {
  const [summary, setSummary] = useState<CreatorPaymentSummary | null>(null)
  const [rows, setRows] = useState<CreatorPaymentTransaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [revokingRow, setRevokingRow] = useState<CreatorPaymentTransaction | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  async function loadRows() {
    const [sumRes, rowsRes] = await Promise.all([
      fetch(apiUrl('/api/creator/payments/summary'), { credentials: 'include' }),
      fetch(apiUrl('/api/creator/payments'), { credentials: 'include' }),
    ])
    if (!sumRes.ok) throw new Error(`Error ${sumRes.status}`)
    if (!rowsRes.ok) throw new Error(`Error ${rowsRes.status}`)
    const [sum, txns] = await Promise.all([
      sumRes.json() as Promise<CreatorPaymentSummary>,
      rowsRes.json() as Promise<CreatorPaymentTransaction[]>,
    ])
    setSummary(sum)
    setRows(txns)
  }

  useEffect(() => {
    loadRows()
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function handleRevoked(result: RevokeResult) {
    // Summarise the outcome. Idempotent second call reads
    // "This purchase's access was already revoked. No changes made."
    if (result.already_revoked) {
      setToast("This purchase's access was already revoked. No changes made.")
    } else {
      const bits: string[] = []
      bits.push(`${result.access_passes_revoked} access pass${result.access_passes_revoked === 1 ? '' : 'es'} revoked`)
      if (result.entitlements_revoked > 0) {
        bits.push(`${result.entitlements_revoked} pathway entitlement${result.entitlements_revoked === 1 ? '' : 's'} revoked`)
      }
      if (result.grant_records_revoked > 0) {
        bits.push(`${result.grant_records_revoked} grant record${result.grant_records_revoked === 1 ? '' : 's'} marked`)
      }
      if (result.future_bookings_released > 0) {
        bits.push(`${result.future_bookings_released} future booking${result.future_bookings_released === 1 ? '' : 's'} released back to capacity`)
      }
      if (result.membership_removed) {
        bits.push('Collective membership removed')
      }
      setToast(`Revoked · ${bits.join(' · ')}.`)
    }
    setRevokingRow(null)
    // Refresh the ledger so the chips + button eligibility update.
    loadRows().catch(() => { /* non-fatal: page will retry on next mount */ })
  }

  const feeDisplay = `${(feeBasisPoints / 100).toFixed(0)}%`
  const displayCurrency = rows[0]?.currency ?? currency

  return (
    <div className="w-full max-w-[1100px] px-6 py-8 md:px-10 md:py-10">

      {headerCollectiveName ? (
        <CollectiveArtworkHeader
          collectiveName={headerCollectiveName}
          sectionTitle="Payments received"
          meta="Real payment activity — money in from member purchases, with fees and estimated payouts across your collectives."
          location={headerLocation}
          coverImageUrl={headerCoverImageUrl}
        />
      ) : (
        <div className="mb-6">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Payments received</h1>
        </div>
      )}

      {/* Platform payment status */}
      {stripeEnabled ? (
        <div
          className="mb-6 rounded-2xl p-5"
          style={{ background: '#F0FDFB', border: '1px solid #99E6E4' }}
        >
          <div className="flex items-start gap-3">
            <div
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
              style={{ background: '#38A09E' }}
            >
              ✓
            </div>
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[14px] font-semibold" style={{ color: '#0F766E' }}>
                  Payments are live
                </p>
                {stripeTestMode && (
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                    style={{ background: '#FDE68A', color: '#78350F' }}
                  >
                    Test mode
                  </span>
                )}
              </div>
              <p className="mt-1 text-[13px] leading-relaxed" style={{ color: '#0F766E' }}>
                Purchases are processed through Fresh Collective during this phase — you do
                not need to connect your own Stripe account. Configure what members can buy in{' '}
                <strong>Commerce → Payment Options</strong>.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div
          className="mb-6 rounded-2xl p-5"
          style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
        >
          <div className="flex items-start gap-3">
            <div
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
              style={{ background: '#FEF3C7', color: '#92400E' }}
            >
              !
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-semibold" style={{ color: '#92400E' }}>
                Payments are not configured yet
              </p>
              <p className="mt-1 text-[13px] leading-relaxed" style={{ color: '#78350F' }}>
                The Fresh Collective platform Stripe account has not been set up.
                Members cannot make purchases until this is resolved. Contact Fresh
                Collective support.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Creator plan / platform ownership */}
      <div
        className="mb-6 rounded-2xl p-5"
        style={{ background: '#F0FDFB', border: '1px solid #99E6E4' }}
      >
        {isPlatformOwner ? (
          <>
            <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: '#38A09E' }}>
              Account type
            </p>
            <p className="font-serif text-[1.1rem] font-semibold text-[#0F172A]">
              Fresh Collective — Platform Owner
            </p>
            <div className="mt-3 flex flex-wrap gap-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-black">Transaction fee</p>
                <p className="text-[14px] font-semibold" style={{ color: '#0F766E' }}>$0 / 0%</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-black">Payout</p>
                <p className="text-[14px] font-semibold text-[#0F172A]">Not applicable</p>
              </div>
            </div>
            <p className="mt-3 text-[12px]" style={{ color: '#000000' }}>
              Platform-owned collective — no Fresh Collective transaction fee applies. Sales go directly to Fresh Collective with no deduction.
            </p>
          </>
        ) : (
          <>
            <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: '#38A09E' }}>
              Your creator plan
            </p>
            <p className="font-serif text-[1.1rem] font-semibold text-[#0F172A]">
              Founding Creator Access
            </p>
            <div className="mt-3 flex flex-wrap gap-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-black">Trial</p>
                <p className="text-[14px] font-semibold text-[#0F172A]">14 days free</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-black">Then</p>
                <p className="text-[14px] font-semibold text-[#0F172A]">$19 / month</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-black">Transaction fee</p>
                <p className="text-[14px] font-semibold text-[#0F172A]">{feeDisplay} per sale</p>
              </div>
            </div>
            <p className="mt-3 text-[12px]" style={{ color: '#000000' }}>
              No hidden fees. The transaction fee covers payment processing and platform infrastructure.
            </p>
          </>
        )}
      </div>

      {/* Transaction history heading */}
      <div className="mb-4">
        <h2 className="text-[15px] font-semibold text-[#0F172A]">Transaction history</h2>
        <p className="mt-0.5 text-[13px]" style={{ color: '#000000' }}>
          Actual payments processed through Fresh Collective. Complimentary
          and manual access grants live on <strong>Access</strong> and are not
          shown here.
        </p>
      </div>

      {stripeTestMode && (
        <div
          className="mb-4 flex items-center gap-2 rounded-xl px-4 py-2.5 text-[12px]"
          style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
        >
          <span className="font-semibold" style={{ color: '#92400E' }}>Test mode — sandbox data only.</span>
          <span style={{ color: '#78350F' }}>Any card transactions here were made with Stripe test cards and did not move real money.</span>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-[14px] text-black">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          Loading payments…
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Summary cards */}
          {isPlatformOwner ? (
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
              <SummaryCard
                label="Gross Sales"
                value={summary ? fmt(summary.total_gross_amount_cents, displayCurrency) : '—'}
                sub="historical, before refunds"
              />
              <SummaryCard
                label="Refunds"
                value={summary ? fmt(summary.total_refunded_amount_cents, displayCurrency) : '—'}
                sub="cumulative refunded"
              />
              <SummaryCard
                label="Total Revenue"
                value={summary ? fmt(summary.total_net_retained_amount_cents, displayCurrency) : '—'}
                sub="Gross minus Refunds"
                accent
              />
            </div>
          ) : (
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <SummaryCard
                label="Gross Sales"
                value={summary ? fmt(summary.total_gross_amount_cents, displayCurrency) : '—'}
                sub="historical, before refunds"
              />
              <SummaryCard
                label="Refunds"
                value={summary ? fmt(summary.total_refunded_amount_cents, displayCurrency) : '—'}
                sub="cumulative refunded"
              />
              <SummaryCard
                label="FC Fee"
                value={summary ? fmt(summary.total_platform_fee_cents, displayCurrency) : '—'}
                sub="platform fee retained"
                accent
              />
              <SummaryCard
                label="Est. Creator Earnings"
                value={summary ? fmt(summary.total_creator_net_amount_cents, displayCurrency) : '—'}
                sub={`after ${feeDisplay} fee`}
              />
            </div>
          )}

          {/* Payout note */}
          <div
            className="mb-6 flex items-start gap-2 rounded-xl px-4 py-3 text-[12px] text-black"
            style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}
          >
            <span className="mt-0.5 shrink-0 text-black">ℹ</span>
            {isPlatformOwner ? (
              <span>
                <span className="font-semibold text-[#0F172A]">Platform-owned collective — no Fresh Collective transaction fee applies.</span>{' '}
                Sales go directly to the Fresh Collective Stripe account. No payout tracking or disbursement is required.
              </span>
            ) : (
              <span>
                Your creator earnings are tracked as pending payout. Automatic payouts via Stripe
                Connect are coming in a future update — for now, payouts are handled manually by
                Fresh Collective. Your transaction fee is{' '}
                <span className="font-semibold text-[#0F172A]">{feeDisplay}</span>{' '}
                per sale.
              </span>
            )}
          </div>

          {/* Empty state */}
          {rows.length === 0 ? (
            <div
              className="rounded-2xl p-10 text-center"
              style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
            >
              <p className="text-[15px] font-medium text-[#0F172A]">No payments yet.</p>
              <p className="mt-2 text-[13px] text-black">
                When a member purchases a Payment Option through Fresh
                Collective, the payment appears here.
              </p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
              {/* Desktop table */}
              <div className="hidden overflow-x-auto lg:block">
                <table className="w-full text-left">
                  <thead>
                    <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                      {['Date', 'Member', 'Collective', 'Purchase', 'Source', 'Gross', 'FC Fee', 'Est. Creator', 'Status', ''].map((h, idx) => (
                        <th key={`${h}-${idx}`} className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-black">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr
                        key={row.id}
                        className={row.status !== 'succeeded' ? 'opacity-60' : undefined}
                        style={{ borderBottom: i < rows.length - 1 ? '1px solid #F1F5F9' : undefined }}
                      >
                        <td className="px-3 py-3 text-[12px] text-black whitespace-nowrap">{fmtDate(row.created_at)}</td>
                        <td className="px-3 py-3 text-[12px] text-navy-900">
                          {row.payer_name || row.payer_email || (
                            <span className="italic text-slate-400">Unknown</span>
                          )}
                        </td>
                        <td className="px-3 py-3 text-[12px] text-black">
                          {row.space_name || <span className="italic text-slate-400">—</span>}
                        </td>
                        <td className="px-3 py-3 text-[12px] text-navy-900">
                          <span className="align-middle">
                            {row.payment_option_name || (
                              // Legacy transactions without a Payment Option — render the
                              // transaction type as a fallback so old rows still read.
                              <span className="text-slate-500">{labelType(row.transaction_type)}</span>
                            )}
                          </span>
                          <PlanContextBadge row={row} />
                        </td>
                        <td className="px-3 py-3 text-[12px] text-slate-600 whitespace-nowrap">
                          {providerLabel(row)}
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap">
                          <p className="text-[12px] font-semibold text-[#0F172A]">
                            {fmt(row.gross_amount_cents, row.currency)}
                          </p>
                          {row.refunded_amount_cents > 0 && (
                            <>
                              <p className="mt-0.5 text-[11px]" style={{ color: '#B45309' }}>
                                Refunded −{fmt(row.refunded_amount_cents, row.currency)}
                              </p>
                              <p className="text-[11px] font-semibold" style={{ color: '#38A09E' }}>
                                Net {fmt(row.gross_amount_cents - row.refunded_amount_cents, row.currency)}
                              </p>
                            </>
                          )}
                        </td>
                        <td className="px-3 py-3 text-[12px] text-black whitespace-nowrap">
                          {fmt(row.platform_fee_cents, row.currency)}
                        </td>
                        <td className="px-3 py-3 text-[12px] font-semibold whitespace-nowrap" style={{ color: '#38A09E' }}>
                          {row.net_creator_amount_cents != null ? fmt(row.net_creator_amount_cents, row.currency) : '—'}
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap">
                          <StatusBadge status={row.status} />
                          <GrantStateChip state={row.grant_state} />
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap text-right">
                          {canRevoke(row, isPlatformOwner) && (
                            <button
                              type="button"
                              onClick={() => setRevokingRow(row)}
                              className="rounded-full border border-red-200 px-2.5 py-1 text-[11px] font-semibold text-red-600 transition-colors hover:bg-red-50"
                            >
                              Revoke access
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="divide-y divide-[#F1F5F9] lg:hidden">
                {rows.map((row) => (
                  <div key={row.id} className={`p-4${row.status !== 'succeeded' ? ' opacity-60' : ''}`}>
                    <div className="mb-2 flex items-start justify-between gap-2">
                      <div>
                        <p className="text-[13px] font-medium text-[#0F172A]">
                          {row.payment_option_name ?? labelType(row.transaction_type)}
                          <PlanContextBadge row={row} />
                        </p>
                        <p className="text-[11px] text-black">
                          {row.payer_name || row.payer_email || 'Unknown member'} · {fmtDate(row.created_at)} · {providerLabel(row)}
                        </p>
                      </div>
                      <div className="text-right">
                        <StatusBadge status={row.status} />
                        <div className="mt-1"><GrantStateChip state={row.grant_state} /></div>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[12px]">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Gross</p>
                        <p className="font-semibold text-[#0F172A]">{fmt(row.gross_amount_cents, row.currency)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-black">FC Fee</p>
                        <p className="text-black">{fmt(row.platform_fee_cents, row.currency)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Creator Net</p>
                        <p style={{ color: '#38A09E' }}>
                          {row.net_creator_amount_cents != null ? fmt(row.net_creator_amount_cents, row.currency) : '—'}
                        </p>
                      </div>
                    </div>
                    {row.refunded_amount_cents > 0 && (
                      <div className="mt-2 grid grid-cols-2 gap-2 text-[12px]">
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Refunded</p>
                          <p style={{ color: '#B45309' }}>
                            −{fmt(row.refunded_amount_cents, row.currency)}
                          </p>
                        </div>
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Net retained</p>
                          <p className="font-semibold" style={{ color: '#38A09E' }}>
                            {fmt(row.gross_amount_cents - row.refunded_amount_cents, row.currency)}
                          </p>
                        </div>
                      </div>
                    )}
                    {canRevoke(row, isPlatformOwner) && (
                      <div className="mt-3 text-right">
                        <button
                          type="button"
                          onClick={() => setRevokingRow(row)}
                          className="rounded-full border border-red-200 px-3 py-1 text-[11.5px] font-semibold text-red-600 transition-colors hover:bg-red-50"
                        >
                          Revoke access
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Ephemeral success/idempotency notice — sits above the table
          so the state change is obvious after Revoke. Auto-clears when
          the operator opens another modal or reloads. */}
      {toast && (
        <div
          className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-full px-4 py-2 text-[12.5px] font-medium text-white shadow-lg"
          style={{ background: '#0F172A' }}
          onClick={() => setToast(null)}
          role="status"
        >
          {toast}
        </div>
      )}

      {revokingRow && (
        <RevokeAccessModal
          txnId={revokingRow.id}
          memberLabel={
            revokingRow.payer_name
            || revokingRow.payer_email
            || 'Unknown member'
          }
          purchaseLabel={
            revokingRow.payment_option_name
            || labelType(revokingRow.transaction_type)
          }
          amountLabel={fmt(revokingRow.gross_amount_cents, revokingRow.currency)}
          onClose={() => setRevokingRow(null)}
          onRevoked={handleRevoked}
        />
      )}
    </div>
  )
}
