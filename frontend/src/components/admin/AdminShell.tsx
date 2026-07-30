'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

interface NavItem {
  href: string
  label: string
  exact?: boolean
}

// World Management — information architecture per the "living world"
// philosophy: this is not a SaaS dashboard, it's a caretaker's view of
// the people, places and moments that make up Fresh Collective.
//
// Routes are deliberately preserved (e.g. /admin/users, /admin/revenue)
// so existing bookmarks, deep links and backend endpoints keep working;
// only the caretaker-facing labels change.
const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: '🌍 OUR WORLD',
    items: [
      { href: '/admin/overview',            label: 'Mother World', exact: true },
      { href: '/admin/atlas',               label: 'Atlas' },
      { href: '/admin/physical-locations',  label: 'Physical Locations' },
      { href: '/admin/collectives',         label: 'Collectives' },
      { href: '/admin/creators',    label: 'Creators' },
      { href: '/admin/users',       label: 'Members' },
    ],
  },
  {
    label: '💰 COMMERCE',
    items: [
      { href: '/admin/revenue',  label: 'Commerce' },
      { href: '/admin/payments', label: 'Transactions' },
      { href: '/admin/billing',  label: 'Creator Subscriptions' },
      { href: '/admin/pricing',  label: 'Fresh Collective Plans' },
    ],
  },
  {
    label: '🤝 CARE',
    items: [
      { href: '/admin/moderation',  label: 'Community Care' },
      { href: '/admin/world-guide', label: 'World Guide' },
      { href: '/admin/settings',    label: 'World Settings' },
      { href: '/admin/audit',       label: 'World History' },
    ],
  },
]

// Admin-personal nav — belongs to the signed-in administrator, not to
// the platform. Rendered as its own visually-separated block below the
// world-management sections.
const ADMIN_ACCOUNT_ITEMS: NavItem[] = [
  { href: '/admin/account', label: 'Your account' },
]

function SidebarContent({
  pathname,
  userEmail,
  onNav,
}: {
  pathname: string
  userEmail: string
  onNav?: () => void
}) {
  const router = useRouter()

  async function handleLogout() {
    await fetch(apiUrl('/api/auth/logout'), { method: 'POST', credentials: 'include' }).catch(() => {})
    router.push('/')
    router.refresh()
  }

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4" style={{ borderBottom: '1px solid #E2E8F0' }}>
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-teal-500">
          <div className="h-3 w-3 rounded-sm bg-white" />
        </div>
        <div>
          <div className="text-[13px] font-bold text-[#0F172A] leading-none">Fresh Collective</div>
          <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-widest text-teal-600">World Management</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {NAV_SECTIONS.map(({ label, items }) => (
          <div key={label} className="mb-4">
            <p className="mb-1 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-[#000000]">
              {label}
            </p>
            <div className="space-y-0.5">
              {items.map(({ href, label: itemLabel, exact }) => {
                const active = exact
                  ? pathname === href
                  : pathname === href || pathname.startsWith(href + '/')
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={onNav}
                    className={`flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                      active
                        ? 'bg-teal-50 text-teal-700'
                        : 'text-[#000000] hover:bg-[#F1F5F9] hover:text-[#0F172A]'
                    }`}
                    style={active ? { border: '1px solid rgba(56,160,158,0.2)' } : { border: '1px solid transparent' }}
                  >
                    {itemLabel}
                  </Link>
                )
              })}
            </div>
          </div>
        ))}

        {/* Admin-personal section — visually separated from the
             world-management sections above. Belongs to the signed-in
             admin, not to the platform. */}
        <div className="mt-4 border-t border-[#E2E8F0] pt-4">
          <p className="mb-1 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-[#000000]">
            ADMIN
          </p>
          <div className="space-y-0.5">
            {ADMIN_ACCOUNT_ITEMS.map(({ href, label: itemLabel }) => {
              const active = pathname === href || pathname.startsWith(href + '/')
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={onNav}
                  className={`flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                    active
                      ? 'bg-teal-50 text-teal-700'
                      : 'text-[#000000] hover:bg-[#F1F5F9] hover:text-[#0F172A]'
                  }`}
                  style={active ? { border: '1px solid rgba(56,160,158,0.2)' } : { border: '1px solid transparent' }}
                >
                  {itemLabel}
                </Link>
              )
            })}
          </div>
        </div>
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 space-y-2" style={{ borderTop: '1px solid #E2E8F0' }}>
        <p className="truncate text-[11px] text-[#000000]">{userEmail}</p>
        <Link
          href="/"
          className="block text-[12px] text-[#000000] transition-colors hover:text-[#0F172A]"
        >
          ← Back to site
        </Link>
        <button
          type="button"
          onClick={handleLogout}
          className="block text-[12px] text-[#000000] transition-colors hover:text-red-500"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}

export default function AdminShell({
  children,
  userEmail,
}: {
  children: React.ReactNode
  userEmail: string
}) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="flex min-h-screen bg-[#F8F9FA]">
      {/* Desktop sidebar */}
      <aside
        className="hidden lg:block w-52 shrink-0"
        style={{
          position: 'sticky',
          top: 0,
          height: '100vh',
          borderRight: '1px solid #E2E8F0',
          overflowY: 'auto',
        }}
      >
        <SidebarContent pathname={pathname} userEmail={userEmail} />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setMobileOpen(false)}
          />
          <aside
            className="absolute left-0 top-0 bottom-0 w-52"
            style={{ borderRight: '1px solid #E2E8F0' }}
          >
            <SidebarContent
              pathname={pathname}
              userEmail={userEmail}
              onNav={() => setMobileOpen(false)}
            />
          </aside>
        </div>
      )}

      {/* Main */}
      <div className="flex flex-1 flex-col min-w-0">
        {/* Mobile header */}
        <header
          className="lg:hidden flex items-center gap-3 px-4 py-3 bg-white"
          style={{ borderBottom: '1px solid #E2E8F0' }}
        >
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-1.5 hover:bg-[#F1F5F9]"
            aria-label="Open menu"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M3 12h18M3 6h18M3 18h18" />
            </svg>
          </button>
          <span className="text-[14px] font-semibold text-[#0F172A]">Admin</span>
        </header>

        {/* Mobile desktop notice */}
        <div
          className="lg:hidden px-4 py-2 text-center text-[12px] text-amber-700"
          style={{ background: '#FFFBEB', borderBottom: '1px solid #FCD34D' }}
        >
          Fresh Collective Admin is best managed on desktop.
        </div>

        <main className="flex-1 p-5 lg:p-8">{children}</main>
      </div>
    </div>
  )
}
