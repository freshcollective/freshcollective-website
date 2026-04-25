'use client'

import { useActionState } from 'react'
import { useFormStatus } from 'react-dom'
import Link from 'next/link'
import Button from '@/components/ui/Button'
import { login, type AuthState } from '@/lib/auth/actions'

function SubmitButton() {
  const { pending } = useFormStatus()
  return (
    <Button type="submit" variant="primary" size="md" className="w-full" disabled={pending}>
      {pending ? (
        <span className="flex items-center justify-center gap-2">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
          Signing in…
        </span>
      ) : (
        'Log in'
      )}
    </Button>
  )
}

export default function LoginForm({ nextUrl }: { nextUrl?: string }) {
  const [state, formAction] = useActionState<AuthState, FormData>(login, null)

  return (
    <div
      className="w-full max-w-sm rounded-xl border border-border bg-surface p-8 md:p-10"
      style={{ boxShadow: 'var(--fc-shadow-md)' }}
    >
      <div className="mb-8">
        <div className="mb-4 h-px w-6 bg-gold-500" />
        <h1 className="mb-2 font-serif text-3xl text-navy-900">Welcome back.</h1>
        <p className="text-sm text-[#718096]">
          Don&apos;t have an account?{' '}
          <Link
            href="/signup"
            className="text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
          >
            Sign up
          </Link>
        </p>
      </div>

      {state?.error && (
        <div
          role="alert"
          className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {state.error}
        </div>
      )}

      <form action={formAction} className="space-y-5">
        {nextUrl && <input type="hidden" name="next" value={nextUrl} />}

        <div>
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-navy-900">
            Email address
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@example.com"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label htmlFor="password" className="text-sm font-medium text-navy-900">
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-xs text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            placeholder="••••••••"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <SubmitButton />
      </form>
    </div>
  )
}
