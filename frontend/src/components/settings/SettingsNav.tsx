'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV_ITEMS = [
  { label: 'Profile', href: '/settings/profile' },
  { label: 'Membership', href: '/settings/membership' },
  { label: 'Preferences', href: '/settings/preferences' },
  { label: 'Security', href: '/settings/security' },
]

export default function SettingsNav() {
  const pathname = usePathname()

  return (
    <nav>
      {/* Mobile: horizontal scroll tabs */}
      <div className="mb-8 flex gap-1 overflow-x-auto rounded-xl border border-border bg-surface p-1 md:hidden">
        {NAV_ITEMS.map((item) => {
          const active = pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={[
                'shrink-0 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-navy-900 text-white'
                  : 'text-slate-500 hover:text-navy-700',
              ].join(' ')}
            >
              {item.label}
            </Link>
          )
        })}
      </div>

      {/* Desktop: vertical sidebar */}
      <div className="hidden md:flex md:flex-col md:gap-1">
        {NAV_ITEMS.map((item) => {
          const active = pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={[
                'rounded-lg px-4 py-2.5 text-sm font-medium transition-colors',
                active
                  ? 'bg-navy-50 text-navy-900'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-navy-700',
              ].join(' ')}
            >
              {item.label}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
