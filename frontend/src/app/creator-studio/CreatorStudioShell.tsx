'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import LogoutButton from '@/components/layout/LogoutButton'
import { MAX_COLLECTIVES_FOR_FOUNDING_CREATOR } from '@/lib/creatorPlan'
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
}

interface NavItem {
  href: string
  label: string
  exact?: boolean
}

// Two-section nav structure
const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: 'ACCOUNT',
    items: [
      { href: '/creator-studio', label: 'Studio Home', exact: true },
    ],
  },
  {
    label: 'CURRENT COLLECTIVE',
    items: [
      { href: '/creator-studio/collective', label: 'Collective Overview' },
      { href: '/creator-studio/pathways',   label: 'Pathways' },
      { href: '/creator-studio/gatherings', label: 'Gatherings' },
      { href: '/creator-studio/resources',  label: 'Resources' },
      { href: '/creator-studio/community',  label: 'Community' },
      { href: '/creator-studio/setup',      label: 'Setup' },
      { href: '/creator-studio/settings',   label: 'Settings' },
    ],
  },
]

// ---------------------------------------------------------------------------
// Collective switcher
// ---------------------------------------------------------------------------

function CollectiveSwitcher({
  spaces,
  activeSpace,
}: {
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
}) {
  const router = useRouter()
  const atLimit = spaces.length >= MAX_COLLECTIVES_FOR_FOUNDING_CREATOR

  function switchTo(slug: string) {
    document.cookie = `fc_creator_space=${slug}; path=/; max-age=86400`
    router.push('/creator-studio/collective')
  }

  return (
    <div className="mt-4">
      {spaces.length > 0 && (
        <div
          className="rounded-xl p-3"
          style={{
            background: 'rgba(255,255,255,0.07)',
            border: '1px solid rgba(255,255,255,0.11)',
          }}
        >
          <p
            className="mb-2 px-0.5 text-[10px] font-bold uppercase tracking-[0.18em]"
            style={{ color: 'rgba(255,255,255,0.55)' }}
          >
            Current collective
          </p>
          <div className="space-y-0.5">
            {spaces.map((s) => {
              const isActive = s.slug === activeSpace?.slug
              return (
                <button
                  key={s.slug}
                  type="button"
                  onClick={() => switchTo(s.slug)}
                  className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-all ${
                    isActive ? 'bg-white/[12%]' : 'hover:bg-white/[6%]'
                  }`}
                >
                  <span
                    className="flex-1 truncate text-[13px] font-medium leading-tight"
                    style={{ color: isActive ? '#ffffff' : 'rgba(255,255,255,0.80)' }}
                  >
                    {s.name}
                  </span>
                  <span
                    className="shrink-0 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide"
                    style={{
                      background:
                        s.status === 'active'
                          ? 'rgba(66,199,198,0.28)'
                          : 'rgba(255,255,255,0.08)',
                      color:
                        s.status === 'active'
                          ? '#8DE8E6'
                          : 'rgba(255,255,255,0.58)',
                    }}
                  >
                    {s.status === 'active' ? 'Active' : 'Draft'}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Create / limit */}
      <div className="mt-3">
        {!atLimit ? (
          <Link
            href="/creator-studio/create"
            className="flex items-center gap-1.5 text-[12px] font-medium transition-opacity hover:opacity-80"
            style={{ color: '#8DE8E6' }}
          >
            <span aria-hidden="true" className="text-[14px] leading-none">+</span>
            Create new collective
          </Link>
        ) : (
          <div>
            <p className="text-[11px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              {spaces.length} of {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} used
            </p>
            <p className="mt-0.5 text-[10px]" style={{ color: 'rgba(255,255,255,0.40)' }}>
              Creator Plus coming soon
            </p>
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
  pathname,
  onNavClick,
}: {
  user: User
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  pathname: string
  onNavClick?: () => void
}) {
  function isActive(href: string, exact?: boolean) {
    return exact ? pathname === href : pathname.startsWith(href)
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
        <Link href="/creator-studio" className="flex items-center gap-3" onClick={onNavClick}>
          <div
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
            style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
          >
            <div className="h-[11px] w-[11px] rounded-sm bg-white" style={{ opacity: 0.92 }} />
          </div>
          <span className="text-[15px] font-semibold tracking-[-0.02em] text-white">
            Creator Studio
          </span>
        </Link>

        <CollectiveSwitcher spaces={spaces} activeSpace={activeSpace} />
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
              {items.map(({ href, label: itemLabel, exact }) => {
                const active = isActive(href, exact)
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

export default function CreatorStudioShell({ children, user, spaces, activeSpace }: Props) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="flex min-h-screen" style={{ background: '#F7F8FA' }}>

      {/* Desktop sidebar */}
      <aside
        className="hidden w-[232px] shrink-0 md:block"
        style={{ position: 'sticky', top: 0, height: '100vh' }}
      >
        <SidebarInner
          user={user}
          spaces={spaces}
          activeSpace={activeSpace}
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
          <Link href="/creator-studio" className="flex items-center gap-2.5">
            <div
              className="flex h-6 w-6 items-center justify-center rounded-lg"
              style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
            >
              <div className="h-[9px] w-[9px] rounded-sm bg-white" style={{ opacity: 0.92 }} />
            </div>
            <span className="text-[14px] font-semibold text-white">
              Creator Studio
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
