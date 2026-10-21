'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { MemberOffering } from '@/types/platform'

interface Props {
  offering: MemberOffering
  spaceSlug: string
}

/**
 * The one control that acquires an Offering, free or paid.
 *
 * Both journeys begin at the same button, because to the person
 * pressing it they are the same act — "I want this" — and the price is
 * already on screen above it. What differs is what happens next:
 *
 *   free  →  POST .../acquire  →  it's theirs, in one request
 *   paid  →  POST /api/checkout/offering  →  Stripe  →  webhook
 *
 * Signed out
 * ----------
 * Not a disabled button and not a wall. The established Pathway and
 * Gathering journey is shown instead: create an account or log in, with
 * ``?next=`` pointing back at this page, then press it again. Copied in
 * behaviour from ``components/checkout/CheckoutButton`` so the three
 * acquisition journeys on the platform feel like one.
 *
 * Already owned
 * -------------
 * The button becomes a way in rather than a second purchase. The
 * backend refuses a repurchase independently (409 ``already_owned``),
 * so this is the pleasant version of a guarantee rather than the
 * guarantee itself.
 *
 * The membership notice
 * ---------------------
 * Shown **above** the button, before anything is committed, because
 * joining a Collective is part of what the person is agreeing to. The
 * server decides whether to show it at all — somebody who already
 * belongs sees nothing, which is the "avoid unnecessary messaging"
 * rule, and a Collective that computes its own membership promises
 * nothing it would not deliver.
 */
export default function AcquireOffering({ offering, spaceSlug }: Props) {
  const pathname = usePathname()
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ joined: boolean } | null>(null)

  const isPaid = offering.pricing_kind === 'one_time'
  const collectiveName = offering.collective.name

  // ── Already theirs ──────────────────────────────────────────────
  if (offering.viewer_owns) {
    return (
      <div className="mt-4 space-y-2">
        <div className="rounded-xl border border-teal-200 bg-teal-50/60 px-3 py-2.5">
          <p className="text-[13.5px] font-semibold text-teal-800">
            It&rsquo;s in Your Collection
          </p>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-teal-900/80">
            Your downloads are listed on this page. If the creator
            updates a file, you get the new version at no extra cost.
          </p>
        </div>
        <Link
          href="/dashboard/collection"
          className="block w-full rounded-full border border-slate-200 px-5 py-2.5 text-center text-[13.5px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
        >
          View Your Collection
        </Link>
      </div>
    )
  }

  // ── Just acquired, this page load ───────────────────────────────
  if (done) {
    return (
      <div className="mt-4 space-y-2">
        <div className="rounded-xl border border-teal-200 bg-teal-50/60 px-3 py-3">
          <p className="text-[14px] font-semibold text-teal-800">
            ✨ It&rsquo;s yours!
          </p>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-teal-900/80">
            Your Offering has been added to Your Collection.
          </p>
          {done.joined && (
            <p className="mt-2 text-[12.5px] leading-relaxed text-teal-900/80">
              🌿 You&rsquo;ve also joined {collectiveName}. Welcome!
            </p>
          )}
        </div>
        <Link
          href="/dashboard/collection"
          className="block w-full rounded-full border border-slate-200 px-5 py-2.5 text-center text-[13.5px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
        >
          View Your Collection
        </Link>
      </div>
    )
  }

  // ── Refused, with a reason the server gave us ───────────────────
  if (!offering.can_acquire && offering.acquire_blocked) {
    return (
      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
        <p
          className="text-[13px] leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.7)' }}
        >
          {offering.acquire_message}
        </p>
      </div>
    )
  }

  const notice = offering.will_join_collective ? (
    <p
      className="mb-3 rounded-xl px-3 py-2.5 text-[12.5px] leading-relaxed"
      style={{
        background: 'rgba(56,160,158,0.07)',
        border: '1px solid rgba(56,160,158,0.18)',
        color: 'rgba(12,24,38,0.78)',
      }}
    >
      🌿 When you get this Offering, you&rsquo;ll also become a member of{' '}
      <strong className="font-semibold">{collectiveName}</strong>, where
      you can explore more from this creator.
    </p>
  ) : null

  // ── Signed out: the account step, then back here ────────────────
  if (offering.requires_account) {
    const next = encodeURIComponent(pathname)
    return (
      <div className="mt-4">
        {notice}
        <div className="space-y-2">
          <Link
            href={`/signup?next=${next}`}
            className="block w-full rounded-full px-5 py-3 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create account to continue
          </Link>
          <Link
            href={`/login?next=${next}`}
            className="block w-full rounded-full border border-slate-200 px-5 py-2.5 text-center text-[14px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Already have an account? Log in
          </Link>
        </div>
      </div>
    )
  }

  async function acquireFree() {
    const res = await fetch(
      apiUrl(`/api/spaces/${spaceSlug}/offerings/${offering.slug}/acquire`),
      { method: 'POST', credentials: 'include' },
    )
    if (!res.ok) {
      const data = await res.json().catch(() => ({})) as {
        detail?: { message?: string } | string
      }
      const detail = typeof data.detail === 'string'
        ? data.detail
        : data.detail?.message
      setError(detail ?? 'We couldn’t add this just now. Please try again.')
      return
    }
    const body = await res.json() as {
      already_owned: boolean
      joined_collective: boolean
    }
    setDone({ joined: body.joined_collective })
    // Refresh the server component so the file list switches to
    // download links. The success panel above is already showing, so
    // this fills in behind it rather than replacing it.
    router.refresh()
  }

  async function startPaidCheckout() {
    const origin = window.location.origin
    const base = `${origin}${pathname}`
    const res = await fetch(apiUrl('/api/checkout/offering'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        space_slug: spaceSlug,
        offering_slug: offering.slug,
        // {CHECKOUT_SESSION_ID} is a Stripe template variable, replaced
        // at redirect time.
        success_url: `${base}?purchased=true&session_id={CHECKOUT_SESSION_ID}`,
        cancel_url: `${base}?cancelled=true`,
      }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({})) as {
        detail?: { reason?: string; message?: string } | string
      }
      const detail = typeof data.detail === 'string'
        ? data.detail
        : data.detail?.message
      if (
        res.status === 409
        && typeof data.detail === 'object'
        && data.detail?.reason === 'already_owned'
      ) {
        // They own it after all — another tab, or a webhook that landed
        // while this page was open. Re-render rather than report an
        // error, and the owned branch above takes over.
        router.refresh()
        return
      }
      setError(detail ?? 'We couldn’t start checkout. Please try again.')
      return
    }
    const { checkout_url } = await res.json() as { checkout_url: string }
    window.location.href = checkout_url
  }

  async function onClick() {
    setBusy(true)
    setError(null)
    try {
      if (isPaid) {
        await startPaidCheckout()
      } else {
        await acquireFree()
      }
    } catch {
      setError('Something went wrong. Please check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  const label = isPaid ? 'Purchase Offering' : 'Get this Offering'
  const busyLabel = isPaid ? 'Redirecting to checkout…' : 'Adding to Your Collection…'

  return (
    <div className="mt-4">
      {notice}
      <button
        type="button"
        onClick={() => { void onClick() }}
        disabled={busy}
        className="w-full rounded-full px-5 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
      >
        {busy ? busyLabel : label}
      </button>
      {error && (
        <p className="mt-2 text-center text-[12px] text-red-500">{error}</p>
      )}
      {isPaid && (
        <p
          className="mt-2 text-center text-[11.5px]"
          style={{ color: 'rgba(12,24,38,0.52)' }}
        >
          Secure payment through Stripe.
        </p>
      )}
    </div>
  )
}
