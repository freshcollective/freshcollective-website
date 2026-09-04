'use client'

/**
 * SEC-009 — warm banner shown on /dashboard (and anywhere else the
 * host page composes it in) when the current user has not verified
 * their email address yet. Includes a resend action.
 *
 * The banner is UI-only; every trust action is enforced by the
 * backend via ``get_verified_current_user``. This surface exists so
 * legitimate users have a clear, calm route to complete verification
 * — no scary red bar, no hostage-taking modal.
 */

import { useState } from 'react'

export default function VerifyEmailBanner({ email }: { email: string }) {
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  async function resend() {
    setState('sending')
    setError(null)
    try {
      const res = await fetch('/api/auth/verify-email/resend', {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) {
        setState('sent')
      } else {
        // 429 rate-limited, or 401 (session expired mid-flow) — surface
        // a generic-and-warm hint rather than a raw status code.
        setState('error')
        setError(
          res.status === 429
            ? "You've asked a few times just now. Try again in a minute."
            : 'We couldn’t send a fresh link right now. Please try again shortly.',
        )
      }
    } catch {
      setState('error')
      setError('We couldn’t reach Fresh Collective to resend. Please try again.')
    }
  }

  return (
    <div
      className="mx-auto max-w-[1440px] px-6 pt-6 md:px-10"
      role="status"
      aria-live="polite"
    >
      <div
        className="rounded-2xl border p-5 md:p-6"
        style={{
          borderColor: '#E4DAC6',
          background: '#F6EFE0',
          color: '#0C1826',
        }}
      >
        <p className="font-serif text-[17px] leading-snug md:text-[18px]">
          We sent a verification link to <span className="font-medium">{email}</span>.
        </p>
        <p className="mt-1 text-[14px] leading-relaxed opacity-90 md:text-[15px]">
          Verify your email to start joining Collectives and Gatherings.
        </p>

        {state === 'sent' ? (
          <p className="mt-3 text-[14px] font-medium" style={{ color: '#3A6B4E' }}>
            A fresh link is on its way — please check your inbox.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={resend}
              disabled={state === 'sending'}
              className="rounded-full px-4 py-2 text-[14px] font-medium transition disabled:opacity-60"
              style={{
                background: '#0C1826',
                color: '#FAFAF8',
              }}
            >
              {state === 'sending' ? 'Sending…' : 'Resend verification email'}
            </button>
            {state === 'error' && error ? (
              <span className="text-[13px]" style={{ color: '#7A4A3A' }}>
                {error}
              </span>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
