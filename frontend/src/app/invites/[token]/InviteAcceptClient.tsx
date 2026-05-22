'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'

interface Props {
  token: string
  spaceSlug: string
  spaceName: string
  inviteEmail: string
  isLoggedIn: boolean
  emailMatches: boolean
  currentUserEmail: string | null
}

export default function InviteAcceptClient({
  token,
  spaceSlug,
  inviteEmail,
  isLoggedIn,
  emailMatches,
  currentUserEmail,
}: Props) {
  const router = useRouter()
  const [state, setState] = useState<'idle' | 'loading' | 'accepted' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  const tealBtn =
    'w-full rounded-xl px-4 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60'
  const tealStyle = { background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }

  // Not logged in — redirect to login preserving the token
  if (!isLoggedIn) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-center text-[13px] text-slate-500">
          Sign in to accept this invitation.
        </p>
        <Link
          href={`/login?next=/invites/${token}`}
          className={tealBtn + ' block text-center'}
          style={tealStyle}
        >
          Sign in to accept
        </Link>
        <Link
          href={`/signup?next=/invites/${token}`}
          className="block w-full rounded-xl border border-slate-200 px-4 py-2.5 text-center text-[14px] font-medium text-slate-600 transition-colors hover:bg-slate-50"
        >
          Create an account
        </Link>
      </div>
    )
  }

  // Logged in but wrong email
  if (!emailMatches) {
    return (
      <div className="flex flex-col gap-3">
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-800">
          This invite was sent to <strong>{inviteEmail}</strong>. You&apos;re signed in as{' '}
          <strong>{currentUserEmail}</strong>.
          <br />
          <br />
          Please sign in with the invited email address to accept.
        </div>
        <Link
          href={`/login?next=/invites/${token}`}
          className={tealBtn + ' block text-center'}
          style={tealStyle}
        >
          Sign in with invited email
        </Link>
      </div>
    )
  }

  // Accepted state
  if (state === 'accepted') {
    return (
      <div className="flex flex-col gap-3">
        <div className="rounded-xl border border-teal-200 bg-teal-50 px-4 py-3 text-center text-[14px] font-medium text-teal-700">
          Welcome! You&apos;ve joined the collective.
        </div>
        <button
          onClick={() => router.push(`/spaces/${spaceSlug}/community`)}
          className={tealBtn}
          style={tealStyle}
        >
          Enter collective
        </button>
      </div>
    )
  }

  async function handleAccept() {
    setState('loading')
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/invites/${token}/accept`), {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) {
        setState('accepted')
      } else {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : 'Could not accept invite.')
        setState('error')
      }
    } catch {
      setError('Something went wrong. Please try again.')
      setState('error')
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        onClick={handleAccept}
        disabled={state === 'loading'}
        className={tealBtn}
        style={tealStyle}
      >
        {state === 'loading' ? 'Accepting…' : 'Accept invitation'}
      </button>
      {error && <p className="text-center text-[12px] text-red-500">{error}</p>}
    </div>
  )
}
