'use client'

import { useState, useTransition } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import LogoutButton from '@/components/layout/LogoutButton'
import type { SpaceSummary } from '@/types/platform'

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

interface Props {
  children: React.ReactNode
  user: User
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
}

interface NavItem {
  href: string
  label: string
  exact?: boolean
  // Also mark this item active when the pathname matches this pattern.
  // Used so legacy /creator/spaces/[slug]/... routes highlight the correct
  // sidebar item even though their URL doesn't start with /creator-studio/.
  activeOnPath?: RegExp
}

// Two-section nav structure
const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: 'ACCOUNT',
    items: [
      { href: '/creator-studio',         label: 'Studio Home', exact: true },
      { href: '/creator-studio/billing',  label: 'Billing' },
      { href: '/creator-studio/payments', label: 'Payments' },
    ],
  },
  {
    label: 'CURRENT COLLECTIVE',
    items: [
      { href: '/creator-studio/collective', label: 'Collective Overview' },
      { href: '/creator-studio/pathways',   label: 'Pathways',      activeOnPath: /^\/creator\/spaces\/[^/]+\/pathways/ },
      { href: '/creator-studio/gatherings', label: 'Gatherings',    activeOnPath: /^\/creator\/spaces\/[^/]+\/events/ },
      { href: '/creator-studio/resources',  label: 'Resources' },
      { href: '/creator-studio/media',      label: 'Brand Library' }, // TODO: rename route to /brand-library
      { href: '/creator-studio/community',  label: 'Community',     activeOnPath: /^\/creator\/spaces\/[^/]+\/community/ },
      { href: '/creator-studio/people',     label: 'People' },
      { href: '/creator-studio/setup',      label: 'Setup' },
      { href: '/creator-studio/settings',   label: 'Settings',      activeOnPath: /^\/creator\/spaces\/[^/]+$/ },
    ],
  },
]

// ---------------------------------------------------------------------------
// Collective switcher
// ---------------------------------------------------------------------------

function CollectiveSwitcher({
  spaces,
  activeSpace,
  collectiveLimit,
}: {
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
}) {
  const router = useRouter()
  // Optimistic selected slug — updates immediately on click so the sidebar
  // never shows the wrong collective as Current while the page is navigating.
  // The cookie/server state remains the real source of truth after re-render.
  const [selectedSlug, setSelectedSlug] = useState<string | null>(activeSpace?.slug ?? null)
  const [isPending, startTransition] = useTransition()

  // Count only non-archived spaces — matches the billing endpoint's definition
  const activeSpaceCount = spaces.filter((s) => s.status !== 'archived').length
  const atLimit = activeSpaceCount >= collectiveLimit

  function switchTo(slug: string) {
    if (slug === selectedSlug) return
    setSelectedSlug(slug)   // immediate optimistic update
    startTransition(() => {
      document.cookie = `fc_creator_space=${slug}; path=/; max-age=86400`
      router.push('/creator-studio/collective')
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
            className="mb-2.5 px-1 text-[9.5px] font-bold uppercase tracking-[0.18em]"
            style={{ color: '#38A09E' }}
          >
            Current collective
          </p>
          <div className="space-y-1.5">
            {spaces.map((s) => {
              // Use optimistic selectedSlug so the UI updates immediately on click.
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
                      (e.currentTarget as HTMLButtonElement).style.background =
                        'rgba(56,160,158,0.06)'
                  }}
                  onMouseLeave={(e) => {
                    if (!isCurrent)
                      (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                  }}
                >
                  <span
                    className="w-full truncate text-[13px] font-semibold leading-snug"
                    style={{ color: isCurrent ? '#0C1826' : '#334155' }}
                  >
                    {s.name}
                  </span>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <span
                      className="rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide"
                      style={{
                        background:
                          s.status === 'active'
                            ? 'rgba(56,160,158,0.14)'
                            : 'rgba(0,0,0,0.07)',
                        color: s.status === 'active' ? '#38A09E' : '#94a3b8',
                      }}
                    >
                      {s.status === 'active' ? 'Active' : 'Draft'}
                    </span>
                    {isCurrent && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide"
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

      {/* Create / limit */}
      <div className="mt-2.5 px-1">
        {!atLimit ? (
          <Link
            href="/creator-studio/create-collective"
            className="flex items-center gap-1.5 text-[12px] font-medium transition-opacity hover:opacity-80"
            style={{ color: '#8DE8E6' }}
          >
            <span aria-hidden="true" className="text-[14px] leading-none">+</span>
            Create new collective
          </Link>
        ) : (
          <div>
            <p className="text-[11px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              {activeSpaceCount} of {collectiveLimit} collectives used
            </p>
            <Link
              href="/creator-studio/billing"
              className="mt-0.5 block text-[10px] transition-opacity hover:opacity-80"
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

// ---------------------------------------------------------------------------
// Sidebar inner (shared between desktop and mobile)
// ---------------------------------------------------------------------------

function SidebarInner({
  user,
  spaces,
  activeSpace,
  collectiveLimit,
  pathname,
  onNavClick,
}: {
  user: User
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
  pathname: string
  onNavClick?: () => void
}) {
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
      {/* Subtle top glow */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        aria-hidden="true"
        style={{
          background:
            'radial-gradient(circle at 20% 0%, rgba(66,199,198,0.20), transparent 32%)',
        }}
      />

      {/* Logo + space name + switcher */}
      <div
        className="relative z-10 px-5 py-5"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.09)' }}
      >
        <Link href="/creator-studio" className="flex flex-col gap-1" onClick={onNavClick}>
          <span
            className="font-serif text-[18px] leading-tight"
            style={{ color: '#FFFFFF' }}
          >
            Creator Studio
          </span>
          <span
            className="text-[10px] font-bold uppercase tracking-[0.18em]"
            style={{ color: 'rgba(255,255,255,0.42)' }}
          >
            Fresh Collective
          </span>
        </Link>

        <CollectiveSwitcher spaces={spaces} activeSpace={activeSpace} collectiveLimit={collectiveLimit} />
      </div>

      {/* Nav */}
      <nav className="relative z-10 flex-1 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map(({ label, items }) => (
          <div key={label} className="mb-5">
            <p
              className="mb-1.5 px-4 text-[9px] font-bold uppercase tracking-[0.18em]"
              style={{ color: 'rgba(255,255,255,0.35)' }}
            >
              {label}
            </p>
            <ul className="space-y-0.5">
              {items.map(({ href, label: itemLabel, exact, activeOnPath }) => {
                const active = isActive(href, exact, activeOnPath)
                // Dim collective-specific items when no collective is selected
                const dimmed = label === 'CURRENT COLLECTIVE' && !hasCollective
                return (
                  <li key={href}>
                    <Link
                      href={dimmed ? '/creator-studio/create' : href}
                      onClick={onNavClick}
                      className={`flex items-center rounded-xl px-4 py-2.5 text-[15px] font-medium transition-all ${
                        active
                          ? 'bg-white/[12%] text-white'
                          : dimmed
                            ? 'cursor-default text-white/[35%]'
                            : 'text-white/[72%] hover:bg-white/[8%] hover:text-white'
                      }`}
                      tabIndex={dimmed ? -1 : undefined}
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

      {/* Footer */}
      <div
        className="relative z-10 px-5 py-5"
        style={{ borderTop: '1px solid rgba(255,255,255,0.09)' }}
      >
        <Link
          href="/dashboard"
          className="mb-4 block text-[13px] font-medium transition-opacity hover:opacity-90"
          style={{ color: 'rgba(255,255,255,0.68)' }}
        >
          ← Back to platform
        </Link>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px]" style={{ color: 'rgba(255,255,255,0.65)' }}>
            {user.name ?? user.email}
          </span>
          <LogoutButton className="shrink-0 text-[12px] text-white/60 transition-colors hover:text-white/90" />
        </div>
      </div>

    </div>
  )
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

export default function CreatorStudioShell({ children, user, spaces, activeSpace, collectiveLimit }: Props) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="flex min-h-screen" style={{ background: '#F7F8FA' }}>

      {/* Desktop sidebar */}
      <aside
        className="hidden w-[248px] shrink-0 md:block"
        style={{ position: 'sticky', top: 0, height: '100vh' }}
      >
        <SidebarInner
          user={user}
          spaces={spaces}
          activeSpace={activeSpace}
          collectiveLimit={collectiveLimit}
          pathname={pathname}
        />
      </aside>

      {/* Mobile overlay + drawer */}
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/50 md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <aside className="fixed inset-y-0 left-0 z-50 w-64 md:hidden">
            <SidebarInner
              user={user}
              spaces={spaces}
              activeSpace={activeSpace}
              collectiveLimit={collectiveLimit}
              pathname={pathname}
              onNavClick={() => setMobileOpen(false)}
            />
          </aside>
        </>
      )}

      {/* Content column */}
      <div className="flex min-w-0 flex-1 flex-col">

        {/* Mobile topbar */}
        <div
          className="flex items-center justify-between px-4 py-3 md:hidden"
          style={{
            background: '#073B3A',
            borderBottom: '1px solid rgba(255,255,255,0.09)',
          }}
        >
          <Link href="/creator-studio" className="flex flex-col">
            <span
              className="font-serif text-[16px] leading-tight"
              style={{ color: '#FFFFFF' }}
            >
              Creator Studio
            </span>
            <span
              className="text-[9px] font-bold uppercase tracking-[0.16em]"
              style={{ color: 'rgba(255,255,255,0.42)' }}
            >
              Fresh Collective
            </span>
          </Link>
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded text-white/70 transition-colors hover:text-white"
            aria-label="Open navigation"
          >
            <svg width="18" height="14" fill="none" viewBox="0 0 18 14" aria-hidden="true">
              <path
                d="M0 1h18M0 7h18M0 13h18"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        {/* Page content */}
        <main className="flex-1">{children}</main>

      </div>
    </div>
  )
}
