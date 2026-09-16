'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import type { CreatorBillingResponse } from '@/types/platform'
import { creatorFacingPlanName } from '@/lib/creatorPlanDisplay'

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

  // Route to the Platform Owner card only when the admin has NO
  // active CreatorSubscription. Admins WITH a plan (e.g. Fresh
  // Collective's founder on Founding Creator) fall through and see
  // the real plan card — production incident 2026-09-15 where this
  // branch fired on ``is_platform_owner`` alone and buried the real
  // Founding Creator plan behind "no creator subscription plan
  // attached" copy that contradicted the DB.
  if (billing.is_platform_owner && billing.current_plan === null) {
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
            {creatorFacingPlanName(plan.slug, plan.name)}
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
          <dt className="text-[12px] font-medium text-slate-500">Transaction fee</dt>
          <dd className="mt-1 text-[15px] text-navy-900">
            {plan.transaction_fee_basis_points != null
              ? `${(plan.transaction_fee_basis_points / 100).toFixed(
                  plan.transaction_fee_basis_points % 100 === 0 ? 0 : 2,
                )}% on member sales`
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
      {billing.is_platform_owner && (
        <p
          className="mt-4 text-[12.5px] italic"
          style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
        >
          Platform Owner privileges also apply to this account.
        </p>
      )}

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
  return <BillingInvoicesList />
}

interface InvoiceRow {
  id: string
  number: string | null
  created_at: string
  amount_paid_cents: number
  amount_due_cents: number
  currency: string
  status: string
  hosted_invoice_url: string | null
  invoice_pdf: string | null
}

function BillingInvoicesList() {
  // Client-side fetch — the Billing History tab is inside a client
  // component (AccountTabbedShell) and only renders when the user
  // selects the tab, so paying for a server round-trip on every
  // Account page visit would waste latency.
  const [state, setState] = useState<{
    loading: boolean
    invoices: InvoiceRow[] | null
    billedViaStripe: boolean
    error: string | null
  }>({ loading: true, invoices: null, billedViaStripe: false, error: null })

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await fetch(
          typeof window !== 'undefined'
            ? `${window.location.origin}/api/creator/billing/invoices`
            : '/api/creator/billing/invoices',
          { credentials: 'include' },
        )
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
        const body = (await res.json()) as {
          invoices: InvoiceRow[]
          billed_via_stripe: boolean
        }
        if (!cancelled) {
          setState({
            loading: false,
            invoices: body.invoices,
            billedViaStripe: body.billed_via_stripe,
            error: null,
          })
        }
      } catch (e) {
        if (!cancelled) {
          setState({
            loading: false,
            invoices: null,
            billedViaStripe: false,
            error: e instanceof Error ? e.message : 'Could not load invoices.',
          })
        }
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  if (state.loading) {
    return (
      <section
        className="rounded-2xl bg-white p-8 text-center"
        style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
      >
        <p className="text-[13px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
          Loading invoices…
        </p>
      </section>
    )
  }

  if (state.error) {
    return (
      <section
        className="rounded-2xl bg-white p-6"
        style={{ border: '1px solid rgba(179,36,36,0.24)' }}
      >
        <p className="text-[13.5px] text-red-800">
          Could not load invoices — {state.error}
        </p>
      </section>
    )
  }

  // Not billed via Stripe (Founding Creator, Community, no plan).
  if (!state.billedViaStripe) {
    return (
      <section
        className="rounded-2xl bg-white p-8 text-center"
        style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
      >
        <p className="font-serif text-[17px] leading-snug text-navy-900">
          No billing history.
        </p>
        <p
          className="mx-auto mt-2 max-w-md text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
        >
          Your current plan is not billed via Stripe, so there are no invoices to display.
        </p>
        <p className="mt-4 text-[12px] text-slate-500">
          Looking for collective payments? Those are under{' '}
          <Link href="/creator-studio/payments" className="text-teal-700 hover:underline">Payments</Link>.
        </p>
      </section>
    )
  }

  const invoices = state.invoices ?? []
  if (invoices.length === 0) {
    return (
      <section
        className="rounded-2xl bg-white p-8 text-center"
        style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
      >
        <p className="font-serif text-[17px] leading-snug text-navy-900">
          No invoices yet.
        </p>
        <p
          className="mx-auto mt-2 max-w-md text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}
        >
          Your first Fresh Collective invoice will appear here once
          it&apos;s issued.
        </p>
      </section>
    )
  }

  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white p-2 md:p-4"
    >
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-slate-500">
            <th className="px-3 py-2.5">Date</th>
            <th className="px-3 py-2.5">Description</th>
            <th className="px-3 py-2.5 text-right">Amount</th>
            <th className="px-3 py-2.5">Status</th>
            <th className="px-3 py-2.5 text-right">Receipt</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {invoices.map((inv) => (
            <tr key={inv.id}>
              <td className="px-3 py-3 text-navy-900">
                {formatInvoiceDate(inv.created_at)}
              </td>
              <td className="px-3 py-3 text-navy-900">
                Fresh Collective subscription
                {inv.number && (
                  <span className="ml-2 text-[11px] text-slate-500">
                    · {inv.number}
                  </span>
                )}
              </td>
              <td className="px-3 py-3 text-right text-navy-900">
                {formatMoney(inv.amount_paid_cents || inv.amount_due_cents, inv.currency)}
              </td>
              <td className="px-3 py-3">
                <InvoiceStatusBadge status={inv.status} />
              </td>
              <td className="px-3 py-3 text-right">
                {inv.hosted_invoice_url ? (
                  <a
                    href={inv.hosted_invoice_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[12.5px] font-semibold text-teal-700 hover:underline"
                  >
                    View →
                  </a>
                ) : (
                  <span className="text-[12px] text-slate-400">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 px-3 pb-2 text-[11.5px] italic text-slate-500">
        Invoices are issued by Stripe on behalf of Fresh Collective.
        View or download the full receipt via the link.
      </p>
    </section>
  )
}

function InvoiceStatusBadge({ status }: { status: string }) {
  const cfg =
    status === 'paid'          ? { label: 'Paid',          fg: '#0f766e', bg: 'rgba(56,160,158,0.12)' } :
    status === 'open'          ? { label: 'Open',          fg: '#7C2D12', bg: '#FFF7ED' } :
    status === 'draft'         ? { label: 'Draft',         fg: '#334155', bg: '#F1F5F9' } :
    status === 'uncollectible' ? { label: 'Uncollectible', fg: '#7F1D1D', bg: '#FEF2F2' } :
    status === 'void'          ? { label: 'Void',          fg: '#334155', bg: '#F1F5F9' } :
                                 { label: status,          fg: '#334155', bg: '#F1F5F9' }
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
      style={{ color: cfg.fg, background: cfg.bg }}
    >
      {cfg.label}
    </span>
  )
}

function formatInvoiceDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-AU', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

function formatMoney(cents: number, currency: string): string {
  const symbol = currency === 'AUD' || currency === 'USD' ? '$' : `${currency} `
  const dollars = cents / 100
  return `${symbol}${Number.isInteger(dollars) ? dollars.toFixed(0) : dollars.toFixed(2)}`
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
