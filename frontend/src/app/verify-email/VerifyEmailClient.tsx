'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

type State =
  | { kind: 'idle' }
  | { kind: 'verifying' }
  | { kind: 'success' }
  | { kind: 'error'; message: string }

export default function VerifyEmailClient() {
  const params = useSearchParams()
  const token = params.get('token') ?? ''
  const [state, setState] = useState<State>({ kind: 'idle' })

  useEffect(() => {
    if (!token) {
      setState({
        kind: 'error',
        message:
          'This verification link is missing a token. Please open the link from your email.',
      })
      return
    }
    let cancelled = false
    setState({ kind: 'verifying' })
    ;(async () => {
      try {
        const res = await fetch('/api/auth/verify-email', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        })
        if (cancelled) return
        if (res.ok) {
          setState({ kind: 'success' })
        } else {
          setState({
            kind: 'error',
            message:
              'This verification link is invalid or has expired. Please request a new one from your dashboard.',
          })
        }
      } catch {
        if (cancelled) return
        setState({
          kind: 'error',
          message:
            'We couldn’t reach Fresh Collective to verify your email. Please try again shortly.',
        })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <main
      className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-16"
      style={{ color: '#0C1826' }}
    >
      <h1 className="font-serif text-[28px] leading-tight md:text-[32px]">
        Verifying your email
      </h1>

      {state.kind === 'verifying' || state.kind === 'idle' ? (
        <p className="mt-4 text-[16px] opacity-80">One moment…</p>
      ) : null}

      {state.kind === 'success' ? (
        <div className="mt-6">
          <p className="text-[17px] leading-relaxed">
            Email verified 🌿 You’re all set.
          </p>
          <p className="mt-3 text-[15px] opacity-80">
            You can now join Collectives, book Gatherings, and take part in
            everything Fresh Collective has to offer.
          </p>
          <div className="mt-6">
            <Link
              href="/dashboard"
              className="inline-block rounded-full px-5 py-2 text-[15px] font-medium"
              style={{ background: '#0C1826', color: '#FAFAF8' }}
            >
              Continue to your dashboard
            </Link>
          </div>
        </div>
      ) : null}

      {state.kind === 'error' ? (
        <div className="mt-6">
          <p className="text-[16px] leading-relaxed" style={{ color: '#7A4A3A' }}>
            {state.message}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/dashboard"
              className="inline-block rounded-full px-5 py-2 text-[15px] font-medium"
              style={{ background: '#0C1826', color: '#FAFAF8' }}
            >
              Go to your dashboard
            </Link>
            <Link
              href="/login"
              className="inline-block rounded-full border px-5 py-2 text-[15px] font-medium"
              style={{ borderColor: '#0C1826', color: '#0C1826' }}
            >
              Sign in
            </Link>
          </div>
        </div>
      ) : null}
    </main>
  )
}
