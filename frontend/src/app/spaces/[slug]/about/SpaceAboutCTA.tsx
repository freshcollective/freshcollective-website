'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { isPaidPricingType } from '@/lib/pricing'
import type { PricingType } from '@/types/platform'

type CTAState = 'idle' | 'loading' | 'joined' | 'requested' | 'error'

interface Props {
  slug: string
  isPublic: boolean
  isMember: boolean
  isLoggedIn: boolean
  hasPendingRequest: boolean
  hasPendingInvite: boolean
  canManage: boolean
  pricingType: PricingType
  /** When set, membership is auto-managed by Fresh Collective. Non-members
   *  see a soft restricted state — no join button, no self-service CTA. */
  autoGrantRole?: string | null
}

export default function SpaceAboutCTA({
  slug,
  isPublic,
  isMember,
  isLoggedIn,
  hasPendingRequest,
  hasPendingInvite,
  canManage,
  pricingType,
  autoGrantRole,
}: Props) {
  const router = useRouter()
  const [state, setState] = useState<CTAState>('idle')
  const [error, setError] = useState<string | null>(null)

  async function handleJoin() {
    setState('loading')
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/spaces/${slug}/join`), {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) {
        setState('joined')
        router.push(`/spaces/${slug}/community`)
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not join. Please try again.')
        setState('error')
      }
    } catch {
      setError('Something went wrong. Please try again.')
      setState('error')
    }
  }

  async function handleRequestAccess() {
    setState('loading')
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/spaces/${slug}/request-access`), {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) {
        setState('requested')
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not send request. Please try again.')
        setState('error')
      }
    } catch {
      setError('Something went wrong. Please try again.')
      setState('error')
    }
  }

  const tealBtn = 'block w-full rounded-xl px-4 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90'
  // Palette-aware primary CTA. Falls back to Fresh Collective teal.
  const tealStyle = {
    background:
      'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)',
  }
  const ghostBtn = 'block w-full rounded-xl border border-slate-200 px-4 py-2 text-center text-[13px] font-medium text-black transition-colors hover:bg-slate-50'

  // Auto-managed collectives (e.g. World Builders) — non-members see
  // a soft restricted state. No self-service join, no request-access,
  // no speculative "become a Creator" CTA. Members fall through to the
  // normal "Enter collective" flow below.
  if (autoGrantRole && !isMember) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-center text-[13px] text-slate-600">
        Access to this collective is managed automatically by Fresh Collective.
      </div>
    )
  }

  // Already a member
  if (isMember) {
    return (
      <div className="flex flex-col gap-2">
        <Link href={`/spaces/${slug}`} className={tealBtn} style={tealStyle}>
          Enter collective
        </Link>
        {canManage && (
          <Link href="/creator-studio" className={ghostBtn}>
            Manage collective
          </Link>
        )}
      </div>
    )
  }

  // Not logged in
  if (!isLoggedIn) {
    return (
      <div className="flex flex-col gap-2">
        <Link
          href={`/login?next=/spaces/${slug}/about`}
          className={tealBtn}
          style={tealStyle}
        >
          {isPublic ? 'Join collective' : 'Request access'}
        </Link>
      </div>
    )
  }

  // Has pending invite
  if (hasPendingInvite) {
    return (
      <div className="flex flex-col gap-2">
        <div
          className="rounded-xl border px-4 py-2.5 text-center text-[13px] font-medium"
          style={{
            borderColor: 'var(--fc-accent-line, #99f6e4)',
            background: 'var(--fc-accent-soft, #f0fdfa)',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          You have a pending invite — check your email
        </div>
        <Link href="/login" className={ghostBtn}>
          Sign in to accept
        </Link>
      </div>
    )
  }

  // Invite-only pricing — no self-service join or request
  if (pricingType === 'invite_only') {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-center text-[13px] font-medium text-slate-500">
        Invite only
      </div>
    )
  }

  // Coming-soon pricing — no join button yet
  if (pricingType === 'coming_soon') {
    return (
      <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-2.5 text-center text-[13px] font-medium text-amber-700">
        Paid access coming soon
      </div>
    )
  }

  // Paid collective — show informational button; payment not yet connected
  if (isPaidPricingType(pricingType)) {
    return (
      <div className="flex flex-col gap-2">
        <div
          className="block w-full rounded-xl px-4 py-2.5 text-center text-[14px] font-semibold text-white opacity-60"
          style={tealStyle}
        >
          Join — payment coming soon
        </div>
        <p className="text-center text-[11px] text-black">
          Payment processing is being set up. Check back soon.
        </p>
      </div>
    )
  }

  // Public collective — join flow
  if (isPublic) {
    if (state === 'joined') {
      return (
        <div
          className="rounded-xl border px-4 py-2.5 text-center text-[13px] font-medium"
          style={{
            borderColor: 'var(--fc-accent-line, #99f6e4)',
            background: 'var(--fc-accent-soft, #f0fdfa)',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          Joined! Redirecting…
        </div>
      )
    }
    return (
      <div className="flex flex-col gap-2">
        <button
          onClick={handleJoin}
          disabled={state === 'loading'}
          className={tealBtn + ' disabled:opacity-60'}
          style={tealStyle}
        >
          {state === 'loading' ? 'Joining…' : 'Join collective'}
        </button>
        {error && <p className="text-center text-[12px] text-red-500">{error}</p>}
      </div>
    )
  }

  // Private collective — request access flow
  if (hasPendingRequest || state === 'requested') {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-center text-[13px] font-medium text-slate-500">
        Request pending
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        onClick={handleRequestAccess}
        disabled={state === 'loading'}
        className={tealBtn + ' disabled:opacity-60'}
        style={tealStyle}
      >
        {state === 'loading' ? 'Sending…' : 'Request access'}
      </button>
      {error && <p className="text-center text-[12px] text-red-500">{error}</p>}
    </div>
  )
}
