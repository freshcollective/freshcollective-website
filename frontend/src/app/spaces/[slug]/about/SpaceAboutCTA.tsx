'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'

type CTAState = 'idle' | 'loading' | 'joined' | 'requested' | 'error'

interface Props {
  slug: string
  isPublic: boolean
  isMember: boolean
  isLoggedIn: boolean
  hasPendingRequest: boolean
  hasPendingInvite: boolean
  canManage: boolean
}

export default function SpaceAboutCTA({
  slug,
  isPublic,
  isMember,
  isLoggedIn,
  hasPendingRequest,
  hasPendingInvite,
  canManage,
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
  const tealStyle = { background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }
  const ghostBtn = 'block w-full rounded-xl border border-slate-200 px-4 py-2 text-center text-[13px] font-medium text-slate-500 transition-colors hover:bg-slate-50'

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
        <div className="rounded-xl border border-teal-200 bg-teal-50 px-4 py-2.5 text-center text-[13px] font-medium text-teal-700">
          You have a pending invite — check your email
        </div>
        <Link href="/login" className={ghostBtn}>
          Sign in to accept
        </Link>
      </div>
    )
  }

  // Public collective — join flow
  if (isPublic) {
    if (state === 'joined') {
      return (
        <div className="rounded-xl border border-teal-200 bg-teal-50 px-4 py-2.5 text-center text-[13px] font-medium text-teal-700">
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
