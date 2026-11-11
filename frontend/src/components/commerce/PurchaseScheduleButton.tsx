'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  paletteHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'
import PaymentPlanConfirmDialog from '@/components/checkout/PaymentPlanConfirmDialog'
import DiscountCodeField from '@/components/checkout/DiscountCodeField'
import type { DiscountPreview } from '@/lib/discountPreview'
import {
  planConfirmationCopy,
  type AnyPaymentSchedule,
} from '@/lib/paymentPlan'

/**
 * Kick off a unified Payment Option purchase.
 *
 * One button, two entry points: the Gathering Series sidebar and the
 * Collective joining doors on a purchase-required About page. They are
 * the same purchase — the same Payment Option, the same schedule, the
 * same fulfilment — reached from different places, so they must not be
 * two implementations. The only thing that differs is where the buyer
 * comes back to, which is why ``returnBase`` is a prop.
 *
 * Calls ``POST /api/checkout`` with:
 *   payment_option_id, payment_option_schedule_id,
 *   success_url = returnBase + ?checkout=success&session_id=…,
 *   cancel_url  = returnBase + ?checkout=cancel.
 *
 * ``payment_option_schedule_id`` is required by the endpoint. A caller
 * that offers an Option without naming a schedule gets a 422 before
 * any business logic runs — which is exactly how the first joining
 * door was written.
 *
 * The backend handles both paths:
 *   * Paid options → returns a Stripe-hosted checkout URL; we
 *     redirect to it.
 *   * Free options → already fulfilled server-side; the backend
 *     returns our own success_url as the checkout_url and we
 *     redirect there (the query flag lets the page render a
 *     "You're in" confirmation).
 *
 * Duplicate guard: the backend refuses if the buyer already
 * actively holds the same Payment Option (409). We surface the
 * detail message inline rather than silently swallowing.
 */
export default function PurchaseScheduleButton({
  returnBase, paymentOptionId, paymentOptionScheduleId, label,
  palette, schedule, optionName, discountCodesEnabled = false,
  onQuote,
}: {
  /** Path the buyer returns to, e.g. ``/spaces/embody/about``.
   *  ``?checkout=success`` / ``?checkout=cancel`` are appended. */
  returnBase: string
  paymentOptionId: string
  paymentOptionScheduleId: string
  label: string
  /** The selected schedule. When it is a finite payment plan, the
   *  member sees a confirmation step before the Stripe redirect —
   *  Stripe's setup-mode page cannot show the amount itself. */
  schedule?: AnyPaymentSchedule | null
  optionName?: string | null
  /** Whether this Collective's surface may offer a discount code.
   *  Comes from the backend, which resolves the Stage 4 flag — the
   *  browser never decides, and the default is off so a surface that
   *  has not been taught to pass it shows no code box rather than one
   *  whose every submission is refused. */
  discountCodesEnabled?: boolean
  /** Stage 4B — forwarded to the code field so the price row above
   *  can show the discounted schedule as the primary amount. */
  onQuote?: (preview: DiscountPreview | null) => void
  /** Optional Collective palette — button uses the primary hex
   *  so the CTA feels branded to the Collective. Falls back to
   *  the platform teal when the Space has no palette hydrated. */
  palette?: CollectivePaletteMeta | null
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  // Only ever a code. The amount is the server's business — see
  // ``DiscountCodeField``.
  const [discountCode, setDiscountCode] = useState<string | null>(null)
  // Stage 4B — and the quote itself, for the confirmation step. On
  // Apple Pay that dialog is the only place the member ever sees an
  // amount, so it has to be the discounted one.
  const [quote, setQuote] = useState<DiscountPreview | null>(null)

  // Only finite plans get the extra step. Pay-in-full goes straight
  // through — Stripe shows the amount for those itself.
  const needsConfirm = schedule != null && planConfirmationCopy(schedule, quote) != null

  // Stage 4 — a code may be used on a payment plan as well as a
  // pay-in-full purchase, so the gate is no longer the schedule type. It
  // is whether this Collective's surface says codes are available
  // (resolved server-side from UNIVERSAL_DISCOUNT_CODES_ENABLED) and
  // whether we know which schedule is being priced.
  //
  // The schedule id still has to be present: without it the field
  // cannot say which arrangement it is pricing, and a code box on an
  // unidentified purchase would quote a figure for the wrong one.
  const canUseCode = discountCodesEnabled && Boolean(paymentOptionScheduleId)

  function handleClick() {
    if (needsConfirm) {
      setError(null)
      setConfirming(true)
      return
    }
    void startCheckout()
  }

  async function startCheckout() {
    setBusy(true)
    setError(null)
    try {
      const base = `${window.location.origin}${returnBase}`
      const res = await fetch(apiUrl('/api/checkout'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          payment_option_id: paymentOptionId,
          payment_option_schedule_id: paymentOptionScheduleId,
          // Stage 3E.3 — the session id comes back with them, so the
          // confirmation can ask the backend *which* purchase this
          // was. `{CHECKOUT_SESSION_ID}` is Stripe's own template
          // variable, substituted at redirect; the same convention
          // `CheckoutButton` and `AcquireOffering` already use.
          //
          // A free Option never reaches Stripe and returns our own
          // success_url, so the placeholder arrives literally — the
          // endpoint treats that as "no reference" rather than
          // looking anything up.
          success_url: `${base}?checkout=success&session_id={CHECKOUT_SESSION_ID}`,
          cancel_url: `${base}?checkout=cancel`,
          ...(discountCode ? { discount_code: discountCode } : {}),
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : `Checkout failed (${res.status})`)
      }
      const data = await res.json() as { checkout_url: string }
      window.location.href = data.checkout_url
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
      setBusy(false)
      setConfirming(false)
    }
  }

  const bg = paletteHex('primary', palette) ?? '#38A09E'
  return (
    <div className="flex w-full flex-col items-stretch gap-2">
      {/* Gated on the server's answer rather than on ``needsConfirm``.
          That flag answers "does this need a confirm dialog?", which is
          false for a payment plan whose instalment metadata is
          incomplete — and offering a code box where the server refuses
          codes tells the member something untrue. */}
      {canUseCode && (
        <DiscountCodeField
          target={{
            kind: 'payment_option',
            paymentOptionId,
            paymentOptionScheduleId,
          }}
          onChange={setDiscountCode}
          onQuote={(p) => { setQuote(p); onQuote?.(p) }}
          disabled={busy}
        />
      )}
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="inline-flex w-full items-center justify-center rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
        style={{ background: bg }}
      >
        {busy ? 'Starting…' : label}
      </button>
      {error && (
        <p className="rounded-md bg-red-50 px-2 py-1 text-center text-[11px] text-red-700">
          {error}
        </p>
      )}
      {confirming && schedule && (
        <PaymentPlanConfirmDialog
          schedule={schedule}
          preview={quote}
          optionName={optionName}
          busy={busy}
          accentHex={bg}
          onConfirm={() => { void startCheckout() }}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  )
}
