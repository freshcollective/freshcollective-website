'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { DASHBOARD_PATH } from '@/lib/routes'
import { formatMoneyCents } from '@/lib/formatMoney'
import {
  paletteHex,
  rgbaFromHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'

/**
 * What you just bought — shown once, on the page you came back to.
 *
 * A Payment Option can contain several experiences, and checkout
 * returns the member to whichever one they started from. That page can
 * only speak for itself: buying a bundle of a Gathering and a Pathway,
 * they saw "You're in" on the Gathering and no sign the Pathway
 * existed. This says what the purchase actually was.
 *
 * Temporary by design. It is not part of the page — it appears because
 * a `session_id` came back in the URL, and it goes when the member
 * dismisses it. Nothing about the underlying page changes.
 *
 * It is also strictly a reader. The backend endpoint grants nothing,
 * books nothing and retries nothing, so revisiting an old success URL
 * shows what is true now and has no other effect. That matters for a
 * refunded purchase: the booking it mentions will say it was
 * cancelled, because the status is read live while the contents come
 * from the purchase.
 */

interface IncludedItem {
  kind: string
  title: string
  url: string
  status: string
  starts_at: string | null
}

interface Summary {
  transaction_id: string
  option_name: string | null
  space_name: string | null
  space_slug: string | null
  /** pending | fulfilling | fulfilled | failed | refunded */
  state: string
  amount_cents: number | null
  currency: string | null
  payment_mode: string
  installments_paid: number | null
  installments_expected: number | null
  installment_amount_cents: number | null
  total_expected_cents: number | null
  interval: string | null
  items: IncludedItem[]
}

/** Stripe can redirect before its webhook has finished. Bounded, so a
 *  purchase that never settles stops asking rather than spinning for
 *  ever — and a timeout says "still being finalised", never "failed". */
const POLL_MS = 2000
const MAX_POLLS = 15

const KIND_ICON: Record<string, string> = {
  pathway: '🌿',
  gathering: '📅',
  event_series: '🗓️',
  offering: '📄',
}

function formatWhen(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString(undefined, {
    weekday: 'long', day: 'numeric', month: 'long',
    hour: 'numeric', minute: '2-digit',
  })
}

export default function PurchaseConfirmation({
  sessionId, palette,
}: {
  sessionId: string
  palette?: CollectivePaletteMeta | null
}) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const [gaveUp, setGaveUp] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const polls = useRef(0)
  const alive = useRef(true)

  const primary = paletteHex('primary', palette ?? null) ?? '#0f766e'

  const load = useCallback(async (): Promise<string | null> => {
    const res = await fetch(
      apiUrl(`/api/checkout/purchase-summary?session_id=${encodeURIComponent(sessionId)}`),
      { credentials: 'include' },
    )
    if (res.status === 404 || res.status === 401) {
      // Not this member's purchase, or no reference to look up. Say
      // nothing rather than guessing — the page beneath is correct.
      if (alive.current) setNotFound(true)
      return 'stop'
    }
    if (!res.ok) return null
    const data = await res.json() as Summary
    if (alive.current) setSummary(data)
    return data.state
  }, [sessionId])

  useEffect(() => {
    alive.current = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      if (!alive.current) return
      let state: string | null = null
      try {
        state = await load()
      } catch {
        // A failed request is not evidence either way; try again
        // within the budget.
      }
      if (!alive.current) return
      if (state === 'stop') return
      // Terminal states stop the loop. "fulfilling" and a failed read
      // keep it going until the budget runs out.
      if (state && state !== 'pending' && state !== 'fulfilling') return
      polls.current += 1
      if (polls.current >= MAX_POLLS) {
        setGaveUp(true)
        return
      }
      timer = setTimeout(tick, POLL_MS)
    }

    void tick()
    return () => {
      // No requests after this component goes away.
      alive.current = false
      if (timer) clearTimeout(timer)
    }
  }, [load])

  if (dismissed || notFound) return null
  if (!summary) return null

  const { state } = summary
  if (state === 'failed') {
    return (
      <Shell primary={primary} onDismiss={() => setDismissed(true)}>
        <h2 className="font-serif text-[18px] text-navy-900">
          That payment didn&rsquo;t go through
        </h2>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-700">
          Nothing has been charged. You can try again whenever you like.
        </p>
      </Shell>
    )
  }

  const title = summary.option_name || 'your purchase'

  if (state === 'pending' || state === 'fulfilling') {
    return (
      <Shell primary={primary} onDismiss={() => setDismissed(true)}>
        <h2 className="font-serif text-[18px] text-navy-900">
          {state === 'pending'
            ? 'Confirming your payment…'
            : `Setting up ${title}…`}
        </h2>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-700">
          {gaveUp
            ? 'This is taking a little longer than usual. Your purchase is still being finalised — we&rsquo;ll email you the moment it&rsquo;s ready.'
            : 'This usually takes a few seconds.'}
        </p>
      </Shell>
    )
  }

  const refunded = state === 'refunded'

  return (
    <Shell primary={primary} onDismiss={() => setDismissed(true)}>
      <h2 className="font-serif text-[18px] text-navy-900">
        {refunded
          ? `Your ${title} purchase was refunded`
          : `Your ${title} is ready!`}
      </h2>

      <PaymentLine summary={summary} refunded={refunded} />

      {summary.items.length > 0 && (
        <>
          <p className="mt-4 mb-2 text-[12px] font-semibold uppercase tracking-[0.1em] text-slate-500">
            Included in your purchase
          </p>
          <ul className="space-y-2">
            {summary.items.map((item) => (
              <li
                key={`${item.kind}-${item.url}`}
                className="rounded-xl border px-3 py-2.5"
                style={{
                  borderColor: rgbaFromHex(primary, 0.14),
                  background: rgbaFromHex(primary, 0.05),
                }}
              >
                <p className="text-[13.5px] font-semibold text-navy-900 break-words">
                  <span aria-hidden className="mr-1.5">
                    {KIND_ICON[item.kind] ?? '•'}
                  </span>
                  {item.title}
                </p>
                {formatWhen(item.starts_at) && (
                  <p className="mt-0.5 text-[12px] text-slate-600">
                    {formatWhen(item.starts_at)}
                  </p>
                )}
                <p className="mt-0.5 text-[12px] text-slate-600">
                  {item.status}
                </p>
                <Link
                  href={item.url}
                  className="mt-1.5 inline-block text-[12.5px] font-semibold underline"
                  style={{ color: primary }}
                >
                  {item.kind === 'gathering' ? 'View Gathering' : 'Open'}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      <Link
        href={DASHBOARD_PATH}
        className="mt-4 inline-flex w-full items-center justify-center rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white"
        style={{ background: primary }}
      >
        Go to Your World
      </Link>
    </Shell>
  )
}

/** The payment, stated honestly — a first instalment is not a
 *  programme paid for. Every figure comes from the backend, which
 *  reads the PurchasePlan; nothing is multiplied here. */
function PaymentLine({
  summary, refunded,
}: { summary: Summary; refunded: boolean }) {
  if (refunded) {
    return (
      <p className="mt-2 text-[13px] leading-relaxed text-slate-700">
        This purchase has been refunded. Anything below that is still
        available to you is marked as such.
      </p>
    )
  }
  const paid = formatMoneyCents(summary.amount_cents, summary.currency)
  if (summary.payment_mode !== 'plan') {
    return (
      <p className="mt-2 text-[13px] leading-relaxed text-slate-700">
        Payment received{paid ? `: ${paid}` : ''}.
      </p>
    )
  }
  const each = formatMoneyCents(
    summary.installment_amount_cents, summary.currency,
  )
  const total = formatMoneyCents(summary.total_expected_cents, summary.currency)
  const cadence = summary.interval === 'week' ? 'weekly'
    : summary.interval === 'month' ? 'monthly'
      : summary.interval ?? 'scheduled'
  const remaining =
    summary.installments_expected != null && summary.installments_paid != null
      ? Math.max(0, summary.installments_expected - summary.installments_paid)
      : null
  return (
    <div className="mt-2 text-[13px] leading-relaxed text-slate-700">
      <p>Payment plan established. First payment{paid ? `: ${paid}` : ''} received.</p>
      {summary.installments_expected != null && (
        <p className="mt-1">
          {summary.installments_expected} {cadence} payments of {each}
          {total ? `. ${total} total.` : '.'}
          {remaining != null && remaining > 0
            ? ` ${remaining} remaining.`
            : ''}
        </p>
      )}
    </div>
  )
}

function Shell({
  primary, onDismiss, children,
}: {
  primary: string
  onDismiss: () => void
  children: React.ReactNode
}) {
  return (
    <section
      role="status"
      aria-live="polite"
      className="mb-4 rounded-2xl border bg-white p-5 shadow-sm"
      style={{ borderColor: rgbaFromHex(primary, 0.2) }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">{children}</div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss purchase confirmation"
          className="shrink-0 rounded-full px-2 py-1 text-[12px] font-semibold text-slate-500 transition-colors hover:bg-slate-100"
        >
          Close
        </button>
      </div>
    </section>
  )
}
