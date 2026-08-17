'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { apiUrl } from '@/lib/api'

interface CheckoutButtonProps {
  pathwayId: string
  paymentOptionId?: string | null
  paymentOptionScheduleId?: string | null
  label?: string
  isAuthenticated?: boolean
  /** When true, the Stripe success redirect lands on the truthful
   *  ``/checkout/success`` page instead of the pathway checkout page.
   *  Set this for finite payment plans — the pathway page's success
   *  branch says "Payment received", which is a lie during a
   *  ``mode=setup`` Checkout Session. */
  useFinitePlanSuccessPage?: boolean
}

export function CheckoutButton({
  pathwayId,
  paymentOptionId,
  paymentOptionScheduleId,
  label = 'Unlock pathway',
  isAuthenticated = true,
  useFinitePlanSuccessPage = false,
}: CheckoutButtonProps) {
  const pathname = usePathname()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // For anonymous visitors on single-price pathways, show auth CTAs
  if (!isAuthenticated) {
    const encodedNext = encodeURIComponent(pathname)
    return (
      <div className="space-y-2">
        <Link
          href={`/signup?next=${encodedNext}`}
          className="block w-full rounded-full px-5 py-3 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Create account to continue
        </Link>
        <Link
          href={`/login?next=${encodedNext}`}
          className="block w-full rounded-full border border-slate-200 px-5 py-2.5 text-center text-[14px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
        >
          Already have an account? Log in
        </Link>
      </div>
    )
  }

  async function handleClick() {
    setLoading(true)
    setError(null)
    try {
      const base = window.location.origin + window.location.pathname
      // {CHECKOUT_SESSION_ID} is a Stripe template variable — replaced at redirect time
      const successUrl = useFinitePlanSuccessPage
        // FIP4A — finite-plan setup Sessions land on the truthful
        // /checkout/success page. That page's copy explicitly
        // waits for the first invoice.payment_succeeded webhook
        // before claiming access, matching the actual state at
        // the moment of Stripe redirect.
        ? `${window.location.origin}/checkout/success?session_id={CHECKOUT_SESSION_ID}`
        : `${base}?success=true&session_id={CHECKOUT_SESSION_ID}`
      const cancelUrl = `${base}?cancelled=true`

      const res = await fetch(apiUrl('/api/checkout/pathway'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pathway_id: pathwayId,
          success_url: successUrl,
          cancel_url: cancelUrl,
          ...(paymentOptionId ? { payment_option_id: paymentOptionId } : {}),
          ...(paymentOptionScheduleId ? { payment_option_schedule_id: paymentOptionScheduleId } : {}),
        }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        const detail = (data as { detail?: string }).detail
        if (res.status === 409) {
          // Already purchased — reload so the server component shows the access-granted state
          window.location.reload()
          return
        }
        setError(detail ?? 'Something went wrong. Please try again.')
        return
      }

      const { checkout_url } = await res.json() as { checkout_url: string }
      window.location.href = checkout_url
    } catch {
      setError('Could not start checkout. Please check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className="w-full rounded-full px-5 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
      >
        {loading ? 'Redirecting to checkout…' : label}
      </button>
      {error && (
        <p className="text-center text-[12px] text-red-500">{error}</p>
      )}
    </div>
  )
}
