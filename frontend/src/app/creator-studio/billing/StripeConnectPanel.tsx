'use client'

/**
 * Creator Studio → Billing → the Stripe Connect panel.
 *
 * Replaces the old "Automatic creator payouts — coming later" row. A thin
 * renderer: every state, every string and every button label comes from
 * ``describeConnect`` in ``lib/stripeConnectPanel``, and every request
 * sequence from ``lib/stripeConnectActions``. Nothing here re-derives state
 * from local conditions — the backend already projected it from Stripe's
 * own fields, and a second opinion would eventually disagree with the
 * first.
 *
 * Deliberately not shown: the Stripe account id, the mode, bank details,
 * and raw requirement or error payloads. A creator needs to know what to do
 * next, not what Stripe's JSON looks like.
 */

import { useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { CreatorStripeConnectStatus } from '@/types/platform'
import {
  continueConnect,
  loadStatus,
  refreshStatus,
  sequenceFor,
  startConnect,
  type ConnectTransport,
} from '@/lib/stripeConnectActions'
import {
  describeConnect,
  feeAcknowledgement,
  feeDisclosure,
  type ConnectPanelTone,
} from '@/lib/stripeConnectPanel'
import ConnectEarnings from './ConnectEarnings'

async function request<T>(path: string, method: 'GET' | 'POST'): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch { /* keep the status line */ }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

const transport: ConnectTransport = {
  get: (path) => request(path, 'GET'),
  post: (path) => request(path, 'POST'),
}

const TONE_STYLES: Record<ConnectPanelTone, { background: string; color: string }> = {
  neutral: { background: '#F1F5F9', color: '#475569' },
  progress: { background: '#E0F2FE', color: '#075985' },
  attention: { background: '#FEF9C3', color: '#854D0E' },
  good: { background: '#DCFCE7', color: '#166534' },
  stopped: { background: '#FEE2E2', color: '#991B1B' },
}

export default function StripeConnectPanel({
  initialStatus,
  planFeeBasisPoints,
}: {
  /**
   * Server-rendered so the panel arrives with its state rather than
   * flashing a spinner. Null when that fetch failed, which is a "try
   * again" state and not an empty one.
   */
  initialStatus: CreatorStripeConnectStatus | null
  /** Drives the fee disclosure's 0%-plan wording. */
  planFeeBasisPoints: number | null
}) {
  const [status, setStatus] = useState<CreatorStripeConnectStatus | null>(initialStatus)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // One guard for every action. Minting a link is cheap, but creating an
  // account is not something to do twice, and a creator double-clicking is
  // the normal case rather than the edge one.
  const inFlight = useRef(false)

  async function run(work: () => Promise<void>) {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (e) {
      // The creator stays on Fresh Collective with something actionable —
      // never a half-navigated dead end.
      setError(
        e instanceof Error ? e.message : 'Something went wrong. Please try again.',
      )
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  function onPrimary() {
    if (!status) return
    const sequence = sequenceFor(status.state)
    if (sequence === 'none') return
    void run(async () => {
      const url = sequence === 'start'
        ? await startConnect(transport)
        : await continueConnect(transport)
      // Straight to Stripe. The URL is never stored — it expires in five
      // minutes, so a remembered one would usually be dead.
      window.location.href = url
    })
  }

  function onRefresh() {
    void run(async () => {
      setStatus(await refreshStatus(transport))
    })
  }

  function onAcknowledge() {
    void run(async () => {
      setStatus(
        await transport.post<CreatorStripeConnectStatus>(
          '/api/creator/stripe-connect/acknowledge-fees',
        ),
      )
    })
  }

  // The server fetch failed. Offer a retry rather than a blank panel, and
  // never guess at a state — "we don't know" is the honest answer here.
  if (!status) {
    return (
      <div className="rounded-xl bg-slate-50 px-4 py-3">
        <p className="text-[13px] font-medium text-navy-900">Your payouts</p>
        <p className="mt-1 text-[12px] text-black">
          {error ?? 'We couldn’t check your Stripe setup just now.'}
        </p>
        <button
          type="button"
          onClick={() => void run(async () => { setStatus(await loadStatus(transport)) })}
          disabled={busy}
          className="mt-2 rounded-lg border border-slate-300 px-3 py-1.5 text-[12px] font-medium text-navy-900 hover:bg-white disabled:opacity-60"
        >
          {busy ? 'Checking…' : 'Try again'}
        </button>
      </div>
    )
  }

  const view = describeConnect(status)
  const tone = TONE_STYLES[view.tone]
  const ack = feeAcknowledgement(status, planFeeBasisPoints)

  return (
    <div className="rounded-xl bg-slate-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-medium text-navy-900">{view.headline}</p>
          <p className="mt-1 max-w-prose text-[12px] text-black">{view.body}</p>
        </div>
        <span
          className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={tone}
        >
          {view.badge}
        </span>
      </div>

      {view.scheduleNote && (
        <p className="mt-2 text-[12px] text-black">{view.scheduleNote}</p>
      )}

      {/* Where the money actually goes today. Kept adjacent to the status so
          "Connected" can never be read on its own as "FC is paying me this
          way now". */}
      {view.routingNote && (
        <p className="mt-2 text-[12px] text-black">{view.routingNote}</p>
      )}

      {(view.action !== 'none' || view.showRefresh) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {view.action !== 'none' && view.actionLabel && (
            <button
              type="button"
              onClick={onPrimary}
              disabled={busy}
              className="rounded-lg bg-navy-900 px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-60"
            >
              {busy ? 'Opening Stripe…' : view.actionLabel}
            </button>
          )}
          {view.showRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={busy}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-[12px] font-medium text-navy-900 hover:bg-white disabled:opacity-60"
            >
              {busy ? 'Checking…' : 'Refresh status'}
            </button>
          )}
        </div>
      )}

      {error && (
        <p className="mt-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      <div className="mt-3 border-t border-slate-200 pt-3">
        <p className="max-w-prose text-[12px] text-black">
          {feeDisclosure(planFeeBasisPoints)}
        </p>

        {/* Acknowledgement. A precondition Fresh Collective must have before it
            will route a creator's sales — and one the creator controls. The
            note under the button matters: agreeing must not read as switching
            payouts on, because it does not. */}
        {ack.required ? (
          <div className="mt-2">
            <p className="max-w-prose text-[12px] text-black">{ack.prompt}</p>
            <button
              type="button"
              onClick={onAcknowledge}
              disabled={busy}
              className="mt-2 rounded-lg border border-slate-300 px-3 py-1.5 text-[12px] font-medium text-navy-900 hover:bg-white disabled:opacity-60"
            >
              {busy ? 'Saving…' : ack.actionLabel}
            </button>
            <p className="mt-1 max-w-prose text-[12px] text-black">
              {ack.note}
            </p>
          </div>
        ) : (
          <p className="mt-2 text-[12px] text-black">
            Thanks — you’ve confirmed you understand how the fees work.
          </p>
        )}
      </div>

      {/* Only worth offering once there could be something to show. */}
      {status.connect_routing_enabled && <ConnectEarnings />}
    </div>
  )
}
