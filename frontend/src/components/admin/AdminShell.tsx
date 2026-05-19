'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

const NAV_ITEMS = [
  { href: '/admin/sales', label: 'Sales Overview', exact: true },
  { href: '/admin/sales/leads', label: 'Leads' },
  { href: '/admin/sales/opportunities', label: 'Opportunities' },
  { href: '/admin/sales/tasks', label: 'Tasks' },
  { href: '/admin/sales/subscriptions', label: 'Subscriptions' },
  { href: '/admin/sales/pricing', label: 'Pricing' },
  { href: '/admin/billing', label: 'Creator Billing' },
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
          <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-widest text-teal-600">Admin</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
        {NAV_ITEMS.map(({ href, label, exact }) => {
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
                  : 'text-[#475569] hover:bg-[#F1F5F9] hover:text-[#0F172A]'
              }`}
              style={active ? { border: '1px solid rgba(56,160,158,0.2)' } : { border: '1px solid transparent' }}
            >
              {label}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 space-y-2" style={{ borderTop: '1px solid #E2E8F0' }}>
        <p className="truncate text-[11px] text-[#94A3B8]">{userEmail}</p>
        <Link
          href="/"
          className="block text-[12px] text-[#64748B] transition-colors hover:text-[#0F172A]"
        >
          ← Back to site
        </Link>
        <button
          type="button"
          onClick={handleLogout}
          className="block text-[12px] text-[#64748B] transition-colors hover:text-red-500"
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

        <main className="flex-1 p-5 lg:p-8">{children}</main>
      </div>
    </div>
  )
}
