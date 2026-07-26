'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import LogoutButton from '@/components/layout/LogoutButton'

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
 * To switch collectives, a Creator returns to Your World.
 *
 * Information architecture:
 *   - THE COLLECTIVE / OFFERINGS / COMMUNITY / COMMERCE group everything
 *     that belongs to the currently-active collective. Switching
 *     collectives (via Your World) changes what these destinations show.
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
}

/**
 * Standalone nav — sits above the grouped sections. "Your World" is
 * the place a creator chooses which collective to work in, so it does
 * not belong under any of the collective-scoped groups.
 */
const STANDALONE_NAV: NavItem[] = [
  { href: '/creator-studio', label: 'Your World', exact: true },
]

const COLLECTIVE_NAV: { label: string; items: NavItem[] }[] = [
  {
    label: '🌿 COLLECTIVES',
    items: [
      { href: '/creator-studio/home',     label: 'Collective Overview', requiresCollective: true },
      { href: '/creator-studio/settings', label: 'Collective Settings', activeOnPath: /^\/creator\/spaces\/[^/]+$/, requiresCollective: true },
      { href: '/creator-studio/assets',   label: 'Media Library',       requiresCollective: true },
    ],
  },
  {
    label: '📖 OFFERINGS',
    items: [
      { href: '/creator-studio/pathways',  label: 'Pathways',   activeOnPath: /^\/creator\/spaces\/[^/]+\/pathways/, requiresCollective: true },
      { href: '/creator-studio/resources', label: 'Resources',  requiresCollective: true },
    ],
  },
  {
    label: '🤝 COMMUNITY',
    items: [
      { href: '/creator-studio/community',  label: 'Conversations', activeOnPath: /^\/creator\/spaces\/[^/]+\/community/, requiresCollective: true },
      { href: '/creator-studio/gatherings', label: 'Gatherings',    activeOnPath: /^\/creator\/spaces\/[^/]+\/events/,    requiresCollective: true },
      { href: '/creator-studio/people',     label: 'People',        requiresCollective: true },
      { href: '/creator-studio/passes',     label: 'Memberships',   requiresCollective: true },
    ],
  },
  {
    label: '💰 COMMERCE',
    items: [
      { href: '/creator-studio/payments', label: 'Payments' },
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
}

export default function CreatorStudioSidebar({ user, hasCollective }: Props) {
  const pathname = usePathname()

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
              {items.map(({ href, label: itemLabel, exact, activeOnPath, requiresCollective }) => {
                const active = isActive(href, exact, activeOnPath)
                const dimmed = (requiresCollective ?? false) && !hasCollective
                return (
                  <li key={href}>
                    <Link
                      href={dimmed ? '/creator-studio/create' : href}
                      className={`flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
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
                      {itemLabel}
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
        <Link
          href="/dashboard"
          className="block text-[12px] text-slate-600 transition-colors hover:text-slate-800"
        >
          ← Back to Your World
        </Link>
        <LogoutButton className="block text-[12px] text-slate-600 transition-colors hover:text-red-500" />
      </div>
    </div>
  )
}
