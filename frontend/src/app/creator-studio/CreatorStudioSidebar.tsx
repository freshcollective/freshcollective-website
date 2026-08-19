'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import LogoutButton from '@/components/layout/LogoutButton'
import { apiUrl } from '@/lib/api'

/**
 * Creator Studio Sidebar — navigation only.
 *
 * The active-collective identity now lives entirely in the page header
 * (see ``CollectiveArtworkHeader``). The sidebar is intentionally
 * navigation-only so there is exactly one visual anchor for "which
 * collective am I in": the wide artwork band on every page. Removing
 * the sidebar's own collective card also removes the second source of
 * truth that used to drift out of sync with the page.
 *
 * To switch collectives, a Creator returns to My World.
 *
 * Information architecture:
 *   - THE COLLECTIVE / OFFERINGS / COMMUNITY / COMMERCE group everything
 *     that belongs to the currently-active collective. Switching
 *     collectives (via My World) changes what these destinations show.
 *   - ACCOUNT sits separately at the bottom because it belongs to the
 *     signed-in creator across ALL of their collectives.
 *
 * Consumed by:
 *   - app/creator-studio/layout.tsx
 *   - app/creator/layout.tsx
 */

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

interface NavItem {
  href: string
  label: string
  exact?: boolean
  activeOnPath?: RegExp
  /** Dims until an active collective exists. */
  requiresCollective?: boolean
  /** When set, the item only renders when the current plan unlocks
   *  paid offers (Creator / Pro / Organisation / Platform Owner).
   *  Community-plan sidebar therefore doesn't include it at all. */
  requiresPaidOffers?: boolean
  /** Feature intentionally on hold. Item still renders — visibly
   *  muted with a "Coming later" suffix and non-navigable — so
   *  Creators know the surface exists without being encouraged to
   *  step into an unfinished feature. Existing direct URLs remain
   *  functional (backend + routes are untouched); only Creator-
   *  facing prompts are removed. */
  paused?: boolean
  /** Optional badge feed — see ``sidebarBadges`` in the component.
   *  Currently only ``payment_plans_attention`` (FIP4C) is defined. */
  badge?: 'payment_plans_attention'
}

/**
 * Standalone nav — sits above the grouped sections. "My World" is
 * the creator's own management space where they choose which collective
 * to work in; it doesn't belong under any of the collective-scoped
 * groups. Distinct from Your World (the Member home at /dashboard),
 * which the "Back to Your World" band above the brand links to.
 */
const STANDALONE_NAV: NavItem[] = [
  { href: '/creator-studio', label: 'My World', exact: true },
]

const COLLECTIVE_NAV: { label: string; items: NavItem[] }[] = [
  {
    label: '🌿 COLLECTIVES',
    items: [
      { href: '/creator-studio/home',     label: 'Collective Overview', requiresCollective: true },
      { href: '/creator-studio/settings', label: 'Collective Settings', activeOnPath: /^\/creator\/spaces\/[^/]+$/, requiresCollective: true },
      // One unified surface for uploaded files + external links. Replaces
      // the old "Media Library" and "Resources" entries.
      { href: '/creator-studio/library',  label: 'Library',             requiresCollective: true },
    ],
  },
  {
    // OFFERINGS collects the things a Creator makes available to
    // members. Pathways + Gatherings today; later this group may
    // grow to include a Marketplace-style category (Products /
    // Digital Products) for downloadable resources — the label
    // and grouping are chosen to stay honest about that future
    // extensibility without pre-empting it in the UI.
    label: '📖 OFFERINGS',
    items: [
      { href: '/creator-studio/pathways',   label: 'Pathways',   activeOnPath: /^\/creator\/spaces\/[^/]+\/pathways/, requiresCollective: true },
      { href: '/creator-studio/gatherings', label: 'Gatherings', activeOnPath: /^\/creator\/spaces\/[^/]+\/events/,    requiresCollective: true },
    ],
  },
  {
    // COMMUNITY is now activity-only: conversations + people. The
    // scheduled Gatherings surface moved to Offerings alongside
    // Pathways because a Gathering is something the Creator offers.
    label: '🤝 COMMUNITY',
    items: [
      { href: '/creator-studio/community', label: 'Conversations', activeOnPath: /^\/creator\/spaces\/[^/]+\/community/, requiresCollective: true },
      { href: '/creator-studio/people',    label: 'People',        requiresCollective: true },
    ],
  },
  {
    label: '💰 COMMERCE',
    items: [
      // Central Payment Options — the active commerce authoring
      // surface. Collective-scoped; supersedes the older nested
      // Pathway / Series Payment Option CRUD (which is now a
      // reference-only view inside those editors).
      { href: '/creator-studio/payment-options', label: 'Payment Options', requiresCollective: true },
      // Payments received — transaction history + money in. Named
      // "Payments received" (not just "Payments") to distinguish
      // from "Payment Options" (what Creators offer) and avoid
      // "Payment" doubling up on both sides of the sidebar.
      { href: '/creator-studio/payments',        label: 'Payments received' },
      // Payment Plans (FIP4C) — plan-level view of member finite-
      // instalment agreements. Sits next to Payments received so the
      // two concepts (ledger vs. agreement) live side-by-side in
      // Commerce without blurring. Renders a small numeric badge when
      // any authorised-scope plans are in payment_problem / suspended
      // so creators learn about attention states without having to
      // visit the page first.
      { href: '/creator-studio/payment-plans',   label: 'Payment Plans', badge: 'payment_plans_attention' as const },
      // Access — renamed from "Memberships". Route is /access;
      // /passes redirects here for backwards compatibility.
      { href: '/creator-studio/access',          label: 'Access',          requiresCollective: true },
      // Offer Pages remain on hold. Muted + non-navigable + "Coming
      // later" suffix so Creators know the surface exists without
      // being invited into it. Data + backend endpoints + migrations
      // are all preserved; direct URLs still resolve for
      // development / recovery.
      { href: '/creator-studio/offers',          label: 'Offer Pages',     requiresCollective: true, paused: true },
    ],
  },
]

const ACCOUNT_NAV: NavItem[] = [
  { href: '/creator-studio/account', label: 'Account' },
]

interface Props {
  user: User
  /** Whether the creator has at least one collective. Controls
   *  dimming of collective-scoped nav items; when false, links stay
   *  visible but visually muted and route to the create flow. */
  hasCollective: boolean
  /** When true, commercial-only sidebar entries (e.g. Offer Pages)
   *  are included. Community plan → false → entry is not rendered
   *  at all. Platform Owner → always true. */
  paidOffersEnabled?: boolean
}

export default function CreatorStudioSidebar({
  user, hasCollective, paidOffersEnabled = false,
}: Props) {
  const pathname = usePathname()

  // FIP4C — sidebar badges. One-shot fetch on mount + a lightweight
  // re-fetch when the tab regains focus so returning from Stripe
  // Checkout / member repair updates the count without a full
  // navigation. Deliberately no polling / websocket — the count is a
  // convenience indicator, not a live dashboard.
  const [attentionCount, setAttentionCount] = useState<number>(0)
  useEffect(() => {
    const load = () => {
      fetch(apiUrl('/api/creator/payment-plans/attention-count'), {
        credentials: 'include',
      })
        .then((r) => (r.ok ? r.json() as Promise<{ count: number }> : null))
        .then((body) => { if (body) setAttentionCount(body.count) })
        .catch(() => { /* non-fatal — badge just stays hidden */ })
    }
    load()
    const onVis = () => { if (document.visibilityState === 'visible') load() }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  const sidebarBadges: Record<NonNullable<NavItem['badge']>, number> = {
    payment_plans_attention: attentionCount,
  }

  function isActive(href: string, exact?: boolean, activeOnPath?: RegExp) {
    if (exact) return pathname === href
    if (pathname.startsWith(href)) return true
    if (activeOnPath && activeOnPath.test(pathname)) return true
    return false
  }

  return (
    <div className="flex h-full flex-col bg-white" style={{ borderRight: '1px solid #E2E8F0' }}>

      {/* ── Brand ── */}
      <div
        className="flex items-center gap-2.5 px-5 py-4"
        style={{ borderBottom: '1px solid #E2E8F0' }}
      >
        <span
          aria-hidden="true"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          <span className="h-3 w-3 rounded-sm bg-white/95" />
        </span>
        <div>
          <div className="text-[13px] font-semibold leading-none" style={{ color: '#0F172A' }}>
            Fresh Collective
          </div>
          <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Creator Studio
          </div>
        </div>
      </div>

      {/* ── Back to Your World ── prominent exit to Member Your World.
           Sits above the nav so it's the clearest way out of Creator
           Studio; visually distinct from the nav so it never blends in
           as "just another item." */}
      <div className="px-4 pt-4">
        <Link
          href="/dashboard"
          className="group flex items-center gap-2 rounded-lg px-3 py-2.5 text-[13px] font-semibold transition-colors"
          style={{
            background: 'rgba(56, 160, 158, 0.08)',
            border: '1px solid rgba(56, 160, 158, 0.24)',
            color: '#0f766e',
          }}
        >
          <span
            aria-hidden="true"
            className="transition-transform group-hover:-translate-x-0.5"
          >
            ←
          </span>
          <span>Back to Your World</span>
        </Link>
      </div>

      {/* ── Nav ── */}
      <nav aria-label="Creator Studio" className="flex-1 overflow-y-auto px-3 py-4">

        {/* Standalone — sits above the grouped sections, no eyebrow. */}
        <ul className="mb-5 space-y-0.5">
          {STANDALONE_NAV.map(({ href, label: itemLabel, exact, activeOnPath }) => {
            const active = isActive(href, exact, activeOnPath)
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={`flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                    active
                      ? 'bg-teal-50 text-teal-700'
                      : 'text-slate-900 hover:bg-slate-50 hover:text-slate-900'
                  }`}
                  style={active
                    ? { border: '1px solid rgba(56,160,158,0.20)' }
                    : { border: '1px solid transparent' }}
                  aria-current={active ? 'page' : undefined}
                >
                  {itemLabel}
                </Link>
              </li>
            )
          })}
        </ul>

        {COLLECTIVE_NAV.map(({ label, items }) => (
          <div key={label} className="mb-5">
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-700">
              {label}
            </p>
            <ul className="space-y-0.5">
              {items
                // Plan-gated items (e.g. Offer Pages) are omitted
                // entirely on plans that can't use them — dimming
                // would still hint at a feature the plan doesn't
                // include. If we ever want an "Upgrade" nudge, it
                // belongs on My World, not here. Paused items
                // bypass this filter because they should be visible
                // to everyone (regardless of plan) as "Coming later".
                .filter(({ requiresPaidOffers, paused }) =>
                  paused || !requiresPaidOffers || paidOffersEnabled,
                )
                .map(({ href, label: itemLabel, exact, activeOnPath, requiresCollective, paused, badge }) => {
                const active = !paused && isActive(href, exact, activeOnPath)
                const dimmed = (requiresCollective ?? false) && !hasCollective
                const badgeCount = badge ? sidebarBadges[badge] : 0
                // Paused items render as a passive muted line — no
                // Link, no navigation, "Coming later" suffix so the
                // reason for the muted state is legible.
                if (paused) {
                  return (
                    <li key={href}>
                      <span
                        className="flex items-center rounded-lg px-3 py-2 text-[13px] font-medium text-slate-400 cursor-default"
                        style={{ border: '1px solid transparent' }}
                        aria-disabled="true"
                        title="This feature is on hold and will return in a future release."
                      >
                        <span>{itemLabel}</span>
                        <span className="ml-2 text-[10.5px] uppercase tracking-wider text-slate-400">
                          · Coming later
                        </span>
                      </span>
                    </li>
                  )
                }
                return (
                  <li key={href}>
                    <Link
                      href={dimmed ? '/creator-studio/create' : href}
                      className={`flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                        active
                          ? 'bg-teal-50 text-teal-700'
                          : dimmed
                            ? 'cursor-default text-slate-300'
                            : 'text-slate-900 hover:bg-slate-50 hover:text-slate-900'
                      }`}
                      style={active
                        ? { border: '1px solid rgba(56,160,158,0.20)' }
                        : { border: '1px solid transparent' }}
                      tabIndex={dimmed ? -1 : undefined}
                      aria-current={active ? 'page' : undefined}
                      aria-disabled={dimmed}
                    >
                      <span>{itemLabel}</span>
                      {badgeCount > 0 && (
                        <span
                          aria-label={`${badgeCount} need${badgeCount === 1 ? 's' : ''} attention`}
                          className="inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-[10.5px] font-semibold"
                          style={{
                            background: 'rgba(180, 83, 9, 0.14)',
                            color: '#8A6A15',
                            border: '1px solid rgba(180, 83, 9, 0.28)',
                          }}
                        >
                          {badgeCount}
                        </span>
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}

        {/* ── Account-scoped nav ── visually separated from the
             collective-scoped groups above. */}
        <div
          className="mt-6 pt-4"
          style={{ borderTop: '1px solid #E2E8F0' }}
        >
          <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-700">
            ACCOUNT
          </p>
          <ul className="space-y-0.5">
            {ACCOUNT_NAV.map(({ href, label: itemLabel }) => {
              const active = pathname.startsWith(href)
              return (
                <li key={href}>
                  <Link
                    href={href}
                    className={`flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                      active
                        ? 'bg-teal-50 text-teal-700'
                        : 'text-slate-900 hover:bg-slate-50 hover:text-slate-900'
                    }`}
                    style={active
                      ? { border: '1px solid rgba(56,160,158,0.20)' }
                      : { border: '1px solid transparent' }}
                    aria-current={active ? 'page' : undefined}
                  >
                    {itemLabel}
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      </nav>

      {/* ── Footer ── */}
      <div
        className="space-y-2 px-5 py-4"
        style={{ borderTop: '1px solid #E2E8F0' }}
      >
        <p className="truncate text-[11px] text-slate-500">
          {user.name ?? user.email}
        </p>
        <LogoutButton className="block text-[12px] text-slate-600 transition-colors hover:text-red-500" />
      </div>
    </div>
  )
}
