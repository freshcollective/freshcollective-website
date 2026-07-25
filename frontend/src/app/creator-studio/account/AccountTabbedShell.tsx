'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import type { CreatorBillingResponse } from '@/types/platform'

type AccountTab = 'profile' | 'plan' | 'billing' | 'settings'

const TAB_ORDER: { key: AccountTab; label: string; helper: string }[] = [
  { key: 'profile',  label: 'Profile',          helper: 'Your public profile — the person members see, across every collective you tend.' },
  { key: 'plan',     label: 'Plan',             helper: 'Your Fresh Collective subscription and what it includes.' },
  { key: 'billing',  label: 'Billing History',  helper: 'Invoices and receipts for your Fresh Collective subscription.' },
  { key: 'settings', label: 'Account Settings', helper: 'Email, password, notifications and sign-out.' },
]

function isValidTab(v: string | null): v is AccountTab {
  return v === 'profile' || v === 'plan' || v === 'billing' || v === 'settings'
}

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

interface Props {
  user: User
  billing: CreatorBillingResponse | null
}

export default function AccountTabbedShell({ user, billing }: Props) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const initialTab = isValidTab(searchParams.get('tab')) ? (searchParams.get('tab') as AccountTab) : 'profile'
  const [tab, setTab] = useState<AccountTab>(initialTab)

  function selectTab(next: AccountTab) {
    setTab(next)
    const params = new URLSearchParams(searchParams.toString())
    if (next === 'profile') params.delete('tab')
    else params.set('tab', next)
    const qs = params.toString()
    router.replace(qs ? `?${qs}` : '?', { scroll: false })
  }

  const activeHelper = TAB_ORDER.find((t) => t.key === tab)?.helper

  return (
    <>
      {/* Tab bar — matches the Collective Settings pattern */}
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {TAB_ORDER.map(({ key, label }) => {
          const isActive = key === tab
          return (
            <button
              key={key}
              type="button"
              onClick={() => selectTab(key)}
              aria-current={isActive ? 'page' : undefined}
              className="rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors"
              style={
                isActive
                  ? {
                      background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                      color: '#ffffff',
                      border: '1px solid rgba(56,160,158,0.35)',
                    }
                  : {
                      background: 'white',
                      color: '#0f766e',
                      border: '1px solid rgba(56,160,158,0.20)',
                    }
              }
            >
              {label}
            </button>
          )
        })}
      </div>

      {activeHelper && (
        <p
          className="mb-6 max-w-2xl text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
        >
          {activeHelper}
        </p>
      )}

      {tab === 'profile' && <ProfileTab user={user} />}
      {tab === 'plan' && <PlanTab billing={billing} />}
      {tab === 'billing' && <BillingHistoryTab />}
      {tab === 'settings' && <SettingsTab user={user} />}
    </>
  )
}

// ---------------------------------------------------------------------------

function ProfileTab({ user }: { user: User }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-7">
      <div className="mb-5">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Your profile
        </p>
      </div>
      <dl className="space-y-4">
        <div>
          <dt className="text-[12px] font-medium text-slate-500">Name</dt>
          <dd className="mt-1 text-[15px] text-navy-900">
            {user.name ?? <span className="italic text-slate-400">Not set</span>}
          </dd>
        </div>
        <div>
          <dt className="text-[12px] font-medium text-slate-500">Email</dt>
          <dd className="mt-1 text-[15px] text-navy-900">{user.email}</dd>
        </div>
      </dl>
      <div className="mt-6 border-t border-slate-100 pt-5">
        <Link
          href="/settings/profile"
          className="inline-flex items-center rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Edit profile →
        </Link>
        <p className="mt-3 text-[12px] italic text-slate-500" style={{ fontFamily: 'Georgia, serif' }}>
          Your profile applies across every collective you tend.
        </p>
      </div>
    </section>
  )
}

function PlanTab({ billing }: { billing: CreatorBillingResponse | null }) {
  if (!billing) {
    return (
      <div
        className="rounded-2xl border border-slate-200 bg-white p-6"
        style={{ borderColor: 'rgba(166, 69, 38, 0.24)' }}
      >
        <p className="text-[14.5px] font-semibold" style={{ color: '#A64526' }}>
          Plan details couldn&apos;t be loaded.
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-600">
          Please refresh in a moment.
        </p>
      </div>
    )
  }

  if (billing.is_platform_owner) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-7">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Account type
        </p>
        <h2 className="mt-2 font-serif text-[22px] leading-tight text-navy-900">
          Platform Owner
        </h2>
        <p
          className="mt-2 max-w-md text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
        >
          Your account is the Fresh Collective Platform Owner. There is no creator subscription plan attached to this account — you have unlimited access.
        </p>
      </section>
    )
  }

  const plan = billing.current_plan
  const sub  = billing.subscription

  if (!plan) {
    return (
      <section
        className="rounded-2xl bg-white p-6"
        style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
      >
        <p className="font-serif text-[16px] text-navy-900">
          No active plan.
        </p>
        <p
          className="mt-2 text-[13px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
        >
          Once you subscribe to a plan, its details will appear here.
        </p>
      </section>
    )
  }

  const usageCount = billing.usage?.collectives_used ?? 0
  const limit = plan.collective_limit ?? null

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-7">
      <div className="mb-6">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Current plan
        </p>
        <div className="mt-2 flex flex-wrap items-baseline gap-3">
          <h2 className="font-serif text-[24px] leading-tight text-navy-900">
            {plan.name}
          </h2>
          {sub && (
            <span
              className="rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.12em]"
              style={{
                background: sub.status === 'active' ? 'rgba(56,160,158,0.12)' : 'rgba(12,24,38,0.06)',
                color: sub.status === 'active' ? '#0f766e' : 'rgba(12,24,38,0.62)',
              }}
            >
              {sub.status}
            </span>
          )}
        </div>
      </div>

      <dl className="grid gap-5 md:grid-cols-2">
        <div>
          <dt className="text-[12px] font-medium text-slate-500">Price</dt>
          <dd className="mt-1 text-[15px] text-navy-900">
            {plan.monthly_price_cents != null
              ? `$${(plan.monthly_price_cents / 100).toFixed(0)} ${plan.currency ?? 'AUD'} / month`
              : <span className="italic text-slate-400">Not set</span>}
          </dd>
        </div>
        <div>
          <dt className="text-[12px] font-medium text-slate-500">Collectives</dt>
          <dd className="mt-1 text-[15px] text-navy-900">
            {limit != null
              ? `${usageCount} of ${limit} used`
              : `${usageCount} used · unlimited`}
          </dd>
        </div>
      </dl>

      <div className="mt-6 border-t border-slate-100 pt-5">
        <Link
          href="/creator-studio/billing"
          className="inline-flex items-center rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Manage plan →
        </Link>
      </div>
    </section>
  )
}

function BillingHistoryTab() {
  // Billing history for the creator's own Fresh Collective subscription
  // is not currently exposed by the backend as a dedicated invoice
  // list. Present a truthful empty state per user request rather than
  // mock data.
  return (
    <section
      className="rounded-2xl bg-white p-8 text-center"
      style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
    >
      <p className="font-serif text-[17px] leading-snug text-navy-900">
        Nothing to show yet.
      </p>
      <p
        className="mx-auto mt-2 max-w-md text-[13.5px] italic leading-relaxed"
        style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
      >
        Once we begin issuing creator-subscription invoices, they&apos;ll appear here.
      </p>
      <p className="mt-4 text-[12px] text-slate-500">
        Looking for collective payments? Those are under{' '}
        <Link href="/creator-studio/payments" className="text-teal-700 hover:underline">Payments</Link>.
      </p>
    </section>
  )
}

function SettingsTab({ user }: { user: User }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-7">
      <div className="mb-5">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Account
        </p>
      </div>

      <dl className="space-y-4">
        <div>
          <dt className="text-[12px] font-medium text-slate-500">Email</dt>
          <dd className="mt-1 text-[15px] text-navy-900">{user.email}</dd>
        </div>
      </dl>

      <div className="mt-6 space-y-2 border-t border-slate-100 pt-5">
        <SettingsLink
          href="/settings/security"
          label="Password &amp; security"
          desc="Change your password or update two-factor authentication."
        />
        <SettingsLink
          href="/settings/preferences"
          label="Notification preferences"
          desc="Choose what Fresh Collective can send you and when."
        />
        <SettingsLink
          href="/settings/membership"
          label="Membership settings"
          desc="Manage your personal Fresh Collective membership."
        />
      </div>

      <div className="mt-6 border-t border-slate-100 pt-5">
        <form action="/api/auth/logout" method="POST">
          <button
            type="submit"
            className="text-[13px] font-medium text-slate-600 transition-colors hover:text-red-500"
          >
            Sign out
          </button>
        </form>
      </div>
    </section>
  )
}

function SettingsLink({
  href, label, desc,
}: {
  href: string
  label: string
  desc: string
}) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between rounded-xl bg-white px-5 py-3 text-left transition-colors hover:bg-slate-50"
      style={{ border: '1px solid rgba(12, 24, 38, 0.06)' }}
    >
      <div className="min-w-0">
        <p className="text-[14px] font-medium text-navy-900" dangerouslySetInnerHTML={{ __html: label }} />
        <p className="mt-0.5 text-[13px] text-slate-600">{desc}</p>
      </div>
      <span aria-hidden="true" className="shrink-0 text-teal-700">→</span>
    </Link>
  )
}
