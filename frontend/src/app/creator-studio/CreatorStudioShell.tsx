'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
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
  primarySpace: SpaceSummary | null
}

const NAV_ITEMS = [
  { href: '/creator-studio',             label: 'Overview',   exact: true },
  { href: '/creator-studio/pathways',    label: 'Pathways' },
  { href: '/creator-studio/gatherings',  label: 'Gatherings' },
  { href: '/creator-studio/resources',   label: 'Resources' },
  { href: '/creator-studio/community',   label: 'Community' },
  { href: '/creator-studio/setup',       label: 'Setup' },
  { href: '/creator-studio/settings',    label: 'Settings' },
]

function SidebarInner({
  user,
  primarySpace,
  pathname,
  onNavClick,
}: {
  user: User
  primarySpace: SpaceSummary | null
  pathname: string
  onNavClick?: () => void
}) {
  function isActive(href: string, exact?: boolean) {
    return exact ? pathname === href : pathname.startsWith(href)
  }

  return (
    <div className="flex h-full flex-col" style={{ background: '#071824' }}>

      {/* Logo + space name */}
      <div className="px-5 py-5" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <Link href="/creator-studio" className="flex items-center gap-2.5" onClick={onNavClick}>
          <div
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
            style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
          >
            <div className="h-[10px] w-[10px] rounded-sm bg-white" style={{ opacity: 0.92 }} />
          </div>
          <span
            className="text-[14px] font-semibold tracking-[-0.02em]"
            style={{ color: 'rgba(255,255,255,0.90)' }}
          >
            Creator Studio
          </span>
        </Link>
        {primarySpace && (
          <div className="mt-3 flex items-center gap-2 overflow-hidden">
            <span className="truncate text-[11.5px]" style={{ color: 'rgba(255,255,255,0.42)' }}>
              {primarySpace.name}
            </span>
            <span
              className="shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide"
              style={{
                background: primarySpace.status === 'active'
                  ? 'rgba(56,160,158,0.22)'
                  : 'rgba(255,255,255,0.08)',
                color: primarySpace.status === 'active'
                  ? '#55B8B6'
                  : 'rgba(255,255,255,0.36)',
              }}
            >
              {primarySpace.status}
            </span>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-3.5">
        <ul className="space-y-px">
          {NAV_ITEMS.map(({ href, label, exact }) => {
            const active = isActive(href, exact)
            return (
              <li key={href}>
                <Link
                  href={href}
                  onClick={onNavClick}
                  className="flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors"
                  style={{
                    color: active ? '#ffffff' : 'rgba(255,255,255,0.46)',
                    background: active ? 'rgba(56,160,158,0.16)' : 'transparent',
                  }}
                >
                  {label}
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-5 py-4" style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
        <Link
          href="/dashboard"
          className="mb-3 block text-[11.5px] transition-opacity hover:opacity-80"
          style={{ color: 'rgba(255,255,255,0.34)' }}
        >
          ← Back to platform
        </Link>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[11.5px]" style={{ color: 'rgba(255,255,255,0.38)' }}>
            {user.name ?? user.email}
          </span>
          <LogoutButton className="shrink-0 text-[11px] text-white/30 transition-colors hover:text-white" />
        </div>
      </div>

    </div>
  )
}

export default function CreatorStudioShell({ children, user, primarySpace }: Props) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="flex min-h-screen" style={{ background: '#F7F8FA' }}>

      {/* Desktop sidebar */}
      <aside
        className="hidden w-[220px] shrink-0 md:block"
        style={{ position: 'sticky', top: 0, height: '100vh' }}
      >
        <SidebarInner user={user} primarySpace={primarySpace} pathname={pathname} />
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
              primarySpace={primarySpace}
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
          style={{ background: '#071824', borderBottom: '1px solid rgba(255,255,255,0.08)' }}
        >
          <Link href="/creator-studio" className="flex items-center gap-2">
            <div
              className="flex h-5 w-5 items-center justify-center rounded"
              style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
            >
              <div className="h-[8px] w-[8px] rounded-sm bg-white" style={{ opacity: 0.92 }} />
            </div>
            <span className="text-[13px] font-semibold" style={{ color: 'rgba(255,255,255,0.90)' }}>
              Creator Studio
            </span>
          </Link>
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded"
            style={{ color: 'rgba(255,255,255,0.60)' }}
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
