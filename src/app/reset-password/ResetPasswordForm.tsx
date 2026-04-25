'use client'

import { useActionState } from 'react'
import { useFormStatus } from 'react-dom'
import Link from 'next/link'
import Button from '@/components/ui/Button'
import { resetPassword, type AuthState } from '@/lib/auth/actions'

function SubmitButton() {
  const { pending } = useFormStatus()
  return (
    <Button type="submit" variant="primary" size="md" className="w-full" disabled={pending}>
      {pending ? (
        <span className="flex items-center justify-center gap-2">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
          Updating password…
        </span>
      ) : (
        'Set new password'
      )}
    </Button>
  )
}

export default function ResetPasswordForm({ token }: { token: string }) {
  const [state, formAction] = useActionState<AuthState, FormData>(resetPassword, null)

  return (
    <div
      className="w-full max-w-sm rounded-xl border border-border bg-surface p-8 md:p-10"
      style={{ boxShadow: 'var(--fc-shadow-md)' }}
    >
      <div className="mb-8">
        <div className="mb-4 h-px w-6 bg-gold-500" />
        <h1 className="mb-2 font-serif text-3xl text-navy-900">Set new password.</h1>
        <p className="text-sm text-[#718096]">Choose a new password for your account.</p>
      </div>

      {state?.error && (
        <div
          role="alert"
          className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {state.error}{' '}
          {state.error.includes('invalid or has expired') && (
            <Link href="/forgot-password" className="font-medium underline underline-offset-2">
              Request a new link
            </Link>
          )}
        </div>
      )}

      <form action={formAction} className="space-y-5">
        <input type="hidden" name="token" value={token} />

        <div>
          <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-navy-900">
            New password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            placeholder="At least 8 characters"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <div>
          <label
            htmlFor="confirmPassword"
            className="mb-1.5 block text-sm font-medium text-navy-900"
          >
            Confirm new password
          </label>
          <input
            id="confirmPassword"
            name="confirmPassword"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            placeholder="Repeat your new password"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <SubmitButton />
      </form>
    </div>
  )
}
