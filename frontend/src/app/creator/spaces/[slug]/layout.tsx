'use client'

import Link from 'next/link'
import { useParams, usePathname } from 'next/navigation'

const SECTIONS = [
  { label: 'Pathways', path: 'pathways' },
  { label: 'Events', path: 'events' },
  { label: 'Community', path: 'community' },
  { label: 'Settings', path: '' },
]

export default function SpaceCreatorLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ slug: string }>()
  const pathname = usePathname()
  const base = `/creator/spaces/${params.slug}`

  return (
    <div className="mx-auto max-w-6xl px-6 py-10 md:px-10">
      {/* Space sub-nav */}
      <nav className="mb-8 flex items-center gap-1 border-b border-border pb-0">
        {SECTIONS.map((s) => {
          const href = s.path ? `${base}/${s.path}` : base
          const active = s.path ? pathname.startsWith(href) : pathname === base
          return (
            <Link
              key={s.label}
              href={href}
              className={[
                'border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                active
                  ? 'border-navy-900 text-navy-900'
                  : 'border-transparent text-slate-500 hover:text-navy-700',
              ].join(' ')}
            >
              {s.label}
            </Link>
          )
        })}
        <div className="ml-auto pb-3">
          <Link
            href={`/spaces/${params.slug}`}
            className="text-xs text-teal-600 hover:underline"
            target="_blank"
          >
            View Space ↗
          </Link>
        </div>
      </nav>
      {children}
    </div>
  )
}
