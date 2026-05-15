'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import type { SpaceMembership } from '@/types/platform'

interface Props {
  memberships: SpaceMembership[]
  currentSlug: string
  currentName: string
  userRole: string
}

export default function CollectiveSwitcher({
  memberships,
  currentSlug,
  currentName,
  userRole,
}: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const isCreatorOrAdmin = userRole === 'creator' || userRole === 'admin'
  const activeMemberships = memberships.filter((m) => m.status === 'active')
  const otherMemberships = activeMemberships.filter((m) => m.space_slug !== currentSlug)

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-slate-50"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <span className="font-serif text-navy-900">{currentName}</span>
        <svg
          className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-60 overflow-hidden rounded-xl border border-border bg-white shadow-lg">

          {/* My collectives */}
          <div className="px-3 pt-3 pb-1.5">
            <p className="px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              My collectives
            </p>
          </div>
          <div className="px-3 pb-2">
            <Link
              href={`/spaces/${currentSlug}`}
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-teal-50"
            >
              <span className="h-2 w-2 shrink-0 rounded-full bg-teal-500" />
              <span className="truncate text-[13px] font-semibold text-navy-900">{currentName}</span>
            </Link>
            {otherMemberships.map((m) => (
              <Link
                key={m.space_id}
                href={`/spaces/${m.space_slug}`}
                onClick={() => setOpen(false)}
                className="flex items-center gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-slate-50"
              >
                <span className="h-2 w-2 shrink-0 rounded-full bg-slate-300" />
                <span className="truncate text-[13px] text-slate-600">{m.space_name}</span>
              </Link>
            ))}
          </div>

          <div className="border-t border-border px-3 py-2">
            <Link
              href="/dashboard/explore"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-lg px-2 py-2 text-[13px] text-slate-500 transition-colors hover:bg-slate-50 hover:text-navy-700"
            >
              Explore collectives
            </Link>
            {isCreatorOrAdmin && (
              <Link
                href="/creator-studio"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 rounded-lg px-2 py-2 text-[13px] text-slate-500 transition-colors hover:bg-slate-50 hover:text-navy-700"
              >
                Creator Studio
              </Link>
            )}
            <Link
              href="/dashboard"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-lg px-2 py-2 text-[13px] text-slate-500 transition-colors hover:bg-slate-50 hover:text-navy-700"
            >
              ← Dashboard
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
