'use client'

import { useState, useTransition } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import LogoutButton from '@/components/layout/LogoutButton'
import type { SpaceSummary } from '@/types/platform'

/**
 * Creator Studio Sidebar
 *
 * The internals of the left navigation column for `/creator-studio/*` and
 * `/creator/*` routes. Rendered by <AppShell variant="sidebar"> — this
 * component only owns the SIDEBAR CONTENT (brand, collective switcher,
 * nav sections, user footer). The shell owns the drawer/desktop behaviour.
 *
 * @see docs/fresh-design-language.md §22.2 (Working density)
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
  /**
   * When true, the item dims until an active collective exists. Preserves
   * the per-item dimming that used to be section-based under "CURRENT
   * COLLECTIVE".
   */
  requiresCollective?: boolean
}

const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: 'COLLECTIVE',
    items: [
      { href: '/creator-studio',          label: 'Dashboard',     exact: true },
      { href: '/creator-studio/settings', label: 'Settings',      activeOnPath: /^\/creator\/spaces\/[^/]+$/, requiresCollective: true },
      { href: '/creator-studio/assets',   label: 'Assets',        requiresCollective: true },
    ],
  },
  {
    label: 'LEARNING',
    items: [
      { href: '/creator-studio/pathways',  label: 'Pathways',  activeOnPath: /^\/creator\/spaces\/[^/]+\/pathways/, requiresCollective: true },
      { href: '/creator-studio/resources', label: 'Resources', requiresCollective: true },
    ],
  },
  {
    label: 'CONVERSATIONS',
    items: [
      { href: '/creator-studio/community',  label: 'Conversations', activeOnPath: /^\/creator\/spaces\/[^/]+\/community/, requiresCollective: true },
      { href: '/creator-studio/gatherings', label: 'Gatherings',  activeOnPath: /^\/creator\/spaces\/[^/]+\/events/,    requiresCollective: true },
      { href: '/creator-studio/people',     label: 'People',      requiresCollective: true },
      { href: '/creator-studio/passes',     label: 'Memberships', requiresCollective: true },
    ],
  },
  {
    label: 'MONEY',
    items: [
      { href: '/creator-studio/payments', label: 'Payments' },
      { href: '/creator-studio/billing',  label: 'Billing' },
    ],
  },
]

interface Props {
  user: User
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
  /** Platform Owner: unlimited collectives, no plan copy in the switcher. */
  isPlatformOwner: boolean
}

export default function CreatorStudioSidebar({
  user, spaces, activeSpace, collectiveLimit, isPlatformOwner,
}: Props) {
  const pathname = usePathname()

  function isActive(href: string, exact?: boolean, activeOnPath?: RegExp) {
    if (exact) return pathname === href
    if (pathname.startsWith(href)) return true
    if (activeOnPath && activeOnPath.test(pathname)) return true
    return false
  }

  const hasCollective = !!activeSpace

  return (
    <div
      className="relative flex h-full flex-col overflow-hidden"
      style={{
        background: 'linear-gradient(180deg, #073B3A 0%, #062F35 45%, #051C27 100%)',
      }}
    >
      <div
        className="pointer-events-none absolute inset-0 z-0"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(circle at 20% 0%, rgba(66,199,198,0.20), transparent 32%)',
        }}
      />

      {/* Brand + collective switcher */}
      <div
        className="relative z-10 px-5 py-5"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.09)' }}
      >
        <Link href="/creator-studio" className="flex flex-col gap-1">
          <span className="font-serif text-[18px] leading-tight text-white">
            Creator Studio
          </span>
          <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-white">
            Fresh Collective
          </span>
        </Link>
        <CollectiveSwitcher
          spaces={spaces}
          activeSpace={activeSpace}
          collectiveLimit={collectiveLimit}
          isPlatformOwner={isPlatformOwner}
        />
      </div>

      {/* Nav */}
      <nav aria-label="Creator Studio" className="relative z-10 flex-1 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map(({ label, items }, sectionIdx) => (
          <div key={label} className={sectionIdx === 0 ? 'mb-8' : 'mb-8 mt-2'}>
            <p className="mb-3 px-4 text-[13px] font-bold uppercase tracking-[0.20em] text-white/90">
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
                      className={`flex items-center rounded-xl px-4 py-2.5 text-[15px] font-medium transition-all ${
                        active
                          ? 'bg-white/[12%] text-white'
                          : dimmed
                            ? 'cursor-default text-white/[35%]'
                            : 'text-white hover:bg-white/[8%] hover:text-white'
                      }`}
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
      </nav>

      {/* User + back to platform */}
      <div
        className="relative z-10 px-5 py-5"
        style={{ borderTop: '1px solid rgba(255,255,255,0.09)' }}
      >
        <Link
          href="/dashboard"
          className="mb-4 block text-[13px] font-medium text-white transition-opacity hover:opacity-90"
        >
          ← Back to Your World
        </Link>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px] text-white">
            {user.name ?? user.email}
          </span>
          <LogoutButton className="shrink-0 text-[12px] text-white transition-colors hover:text-white/90" />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Collective switcher — extracted from the legacy shell, unchanged in
// behaviour. Selects the active collective, sets the cookie, and pushes
// the router to /creator-studio.
// ---------------------------------------------------------------------------

function CollectiveSwitcher({
  spaces, activeSpace, collectiveLimit, isPlatformOwner,
}: {
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
  isPlatformOwner: boolean
}) {
  const router = useRouter()
  const [selectedSlug, setSelectedSlug] = useState<string | null>(activeSpace?.slug ?? null)
  const [isPending, startTransition] = useTransition()

  const activeSpaceCount = spaces.filter((s) => s.status !== 'archived').length
  // Platform Owner is unlimited — never treat them as at-limit, and never
  // render "N of M collectives used" copy.
  const atLimit = !isPlatformOwner && activeSpaceCount >= collectiveLimit

  function switchTo(slug: string) {
    if (slug === selectedSlug) return
    setSelectedSlug(slug)
    startTransition(() => {
      document.cookie = `fc_creator_space=${slug}; path=/; max-age=86400`
      router.push('/creator-studio')
      // ``router.refresh()`` is required alongside ``push`` here.
      // Setting ``document.cookie`` on the client updates the next
      // fetch's header, but Next.js's Client Router Cache keeps the
      // previously-rendered ``/creator-studio`` layout tree in memory
      // — including the ``CollectivePaletteContextProvider`` fed by
      // the old cookie. Without ``refresh()`` the palette (and every
      // other server-derived value that reads the active-space
      // cookie) leaks across collective switches. Refresh invalidates
      // the router cache and forces the layout to re-run on the
      // server against the new cookie.
      router.refresh()
    })
  }

  return (
    <div className="mt-4">
      {spaces.length > 0 && (
        <div
          className="rounded-2xl p-3"
          style={{
            background: 'rgba(255,255,255,0.96)',
            border: '1px solid rgba(56,160,158,0.28)',
          }}
        >
          <p
            className="mb-2.5 px-1 text-[11px] font-bold uppercase tracking-[0.18em]"
            style={{ color: '#38A09E' }}
          >
            Collectives
          </p>
          <div className="space-y-1.5">
            {spaces.map((s) => {
              const isCurrent = s.slug === selectedSlug
              const isPendingThis = isPending && s.slug === selectedSlug
              return (
                <button
                  key={s.slug}
                  type="button"
                  onClick={() => switchTo(s.slug)}
                  disabled={isPending}
                  className="flex w-full flex-col rounded-xl px-3 py-2.5 text-left outline-none transition-colors"
                  style={{
                    background: isCurrent ? 'rgba(56,160,158,0.10)' : 'transparent',
                    border: isCurrent
                      ? '1px solid rgba(56,160,158,0.28)'
                      : '1px solid transparent',
                    opacity: isPendingThis ? 0.75 : 1,
                  }}
                  onMouseEnter={(e) => {
                    if (!isCurrent && !isPending)
                      (e.currentTarget as HTMLButtonElement).style.background = 'rgba(56,160,158,0.06)'
                  }}
                  onMouseLeave={(e) => {
                    if (!isCurrent)
                      (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                  }}
                >
                  <span
                    className="w-full truncate text-[13px] font-semibold leading-snug"
                    style={{ color: isCurrent ? '#0C1826' : '#000000' }}
                  >
                    {s.name}
                  </span>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <span
                      className="rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide"
                      style={{
                        background: s.status === 'active' ? 'rgba(56,160,158,0.14)' : 'rgba(0,0,0,0.07)',
                        color: s.status === 'active' ? '#38A09E' : '#94a3b8',
                      }}
                    >
                      {s.status === 'active' ? 'Active' : 'Draft'}
                    </span>
                    {isCurrent && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide"
                        style={{
                          background: 'rgba(56,160,158,0.12)',
                          border: '1px solid rgba(56,160,158,0.35)',
                          color: '#38A09E',
                        }}
                      >
                        {isPendingThis ? 'Switching…' : 'Current'}
                      </span>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="mt-2.5 px-1">
        {!atLimit ? (
          <Link
            href="/build-your-collective"
            className="flex items-center gap-1.5 text-[12px] font-medium transition-opacity hover:opacity-80"
            style={{ color: '#8DE8E6' }}
          >
            <span aria-hidden="true" className="text-[14px] leading-none">+</span>
            {spaces.length === 0 ? 'Build your first collective.' : 'Build another collective.'}
          </Link>
        ) : (
          <div>
            <p className="text-[11px] text-white">
              {activeSpaceCount} of {collectiveLimit} collectives used
            </p>
            <Link
              href="/creator-studio/billing"
              className="mt-0.5 block text-[11px] transition-opacity hover:opacity-80"
              style={{ color: 'rgba(141,232,230,0.70)' }}
            >
              View plan →
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}
