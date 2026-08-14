'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import type { SpaceMembership } from '@/types/platform'

interface Props {
  memberships: SpaceMembership[]
  currentSlug: string
  currentName: string
  userRole: string
  isAuthenticated?: boolean
}

export default function CollectiveSwitcher({
  memberships,
  currentSlug,
  currentName,
  userRole,
  isAuthenticated = true,
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

      {/* Trigger */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-slate-50"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <span className="font-serif text-[15px] text-navy-900 leading-none">{currentName}</span>
        <svg
          className={`mt-px h-3 w-3 shrink-0 text-slate-400 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute left-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-xl bg-white"
          style={{
            border: '1px solid rgba(0,0,0,0.09)',
            boxShadow: '0 4px 24px rgba(7,24,36,0.12), 0 1px 4px rgba(7,24,36,0.06)',
          }}
        >
          {/* Teal accent line */}
          <div className="h-[3px] w-full" style={{ background: 'linear-gradient(90deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 60%, transparent 100%)' }} />

          {isAuthenticated ? (
            <>
              {/* My collectives section */}
              <div className="px-3 pt-3 pb-1">
                <p className="px-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-black">
                  My collectives
                </p>
              </div>

              <div className="px-3 pb-2">
                {/* Current collective — always highlighted */}
                <Link
                  href={`/spaces/${currentSlug}`}
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-2.5 transition-colors"
                  style={{ background: 'var(--fc-accent-tint, rgba(56,160,158,0.07))' }}
                >
                  <span
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white"
                    style={{ background: 'var(--fc-accent, #38A09E)' }}
                  >
                    {currentName.charAt(0).toUpperCase()}
                  </span>
                  <span className="flex-1 truncate text-[13px] font-semibold text-navy-900">
                    {currentName}
                  </span>
                  <svg
                    className="h-3.5 w-3.5 shrink-0"
                    style={{ color: 'var(--fc-accent, #0d9488)' }}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </Link>

                {otherMemberships.map((m) => (
                  <Link
                    key={m.space_id}
                    href={`/spaces/${m.space_slug}`}
                    onClick={() => setOpen(false)}
                    className="mt-0.5 flex items-center gap-2.5 rounded-lg px-2 py-2.5 transition-colors hover:bg-slate-50"
                  >
                    <span
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white"
                      style={{ background: '#94A3B8' }}
                    >
                      {m.space_name.charAt(0).toUpperCase()}
                    </span>
                    <span className="truncate text-[13px] text-black">{m.space_name}</span>
                  </Link>
                ))}
              </div>

              {/* Divider + utility links */}
              <div className="border-t px-3 py-2" style={{ borderColor: 'rgba(0,0,0,0.06)' }}>
                <Link
                  href="/spaces"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] text-black transition-colors hover:bg-slate-50 hover:text-navy-700"
                >
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                    <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" strokeLinecap="round" />
                  </svg>
                  Explore collectives
                </Link>

                {isCreatorOrAdmin && (
                  <Link
                    href="/creator-studio"
                    onClick={() => setOpen(false)}
                    className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] text-black transition-colors hover:bg-slate-50 hover:text-navy-700"
                  >
                    <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
                    </svg>
                    Creator Studio
                  </Link>
                )}

                <Link
                  href="/dashboard"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] text-black transition-colors hover:bg-slate-50 hover:text-navy-700"
                >
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                  </svg>
                  Your World
                </Link>
              </div>
            </>
          ) : (
            /* Anonymous visitor: current collective + explore + log in */
            <div className="px-3 py-2">
              <Link
                href={`/spaces/${currentSlug}`}
                onClick={() => setOpen(false)}
                className="flex items-center gap-2.5 rounded-lg px-2 py-2.5 transition-colors"
                style={{ background: 'rgba(56,160,158,0.07)' }}
              >
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white"
                  style={{ background: 'var(--fc-accent, #38A09E)' }}
                >
                  {currentName.charAt(0).toUpperCase()}
                </span>
                <span className="flex-1 truncate text-[13px] font-semibold text-navy-900">
                  {currentName}
                </span>
              </Link>

              <div className="mt-1 border-t pt-1" style={{ borderColor: 'rgba(0,0,0,0.06)' }}>
                <Link
                  href="/spaces"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] text-black transition-colors hover:bg-slate-50 hover:text-navy-700"
                >
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                    <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" strokeLinecap="round" />
                  </svg>
                  Explore collectives
                </Link>

                <Link
                  href="/login"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] text-black transition-colors hover:bg-slate-50 hover:text-navy-700"
                >
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                  </svg>
                  Log in
                </Link>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
