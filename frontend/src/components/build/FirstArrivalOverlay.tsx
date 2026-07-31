'use client'

import { useCallback, useState, useSyncExternalStore } from 'react'
import Link from 'next/link'

/**
 * A quiet welcome overlaid on Creator Studio the first time a newly
 * opened collective loads. Detection: a `fc.justOpenedCollective`
 * sessionStorage flag set at the end of Build Your Collective.
 *
 * Read via `useSyncExternalStore` so mount-time reflection of the flag
 * doesn't need setState-in-effect. Fade-in and fade-out are CSS keyframes
 * (`byp-arrival-in` / `byp-arrival-out`) so the component never has to
 * juggle transition state itself.
 */

interface Action {
  title: string
  hint: string
  href: string
}

interface Props {
  slug: string
}

function subscribeToNothing() {
  return () => {}
}

function readFlag(): string | null {
  if (typeof window === 'undefined') return null
  return window.sessionStorage.getItem('fc.justOpenedCollective')
}

function serverReadFlag(): string | null {
  return null
}

export default function FirstArrivalOverlay({ slug }: Props) {
  const flag = useSyncExternalStore(subscribeToNothing, readFlag, serverReadFlag)
  const [leaving, setLeaving] = useState(false)

  const dismiss = useCallback(() => {
    if (typeof window !== 'undefined') {
      window.sessionStorage.removeItem('fc.justOpenedCollective')
    }
    setLeaving(true)
  }, [])

  // Once the fade-out animation finishes we can stop rendering.
  const handleAnimationEnd = useCallback(() => {
    if (leaving) setLeaving(false)
  }, [leaving])

  // If we're not showing and we're not in the middle of leaving, render nothing.
  const shouldRender = flag === slug || leaving
  if (!shouldRender) return null

  const actions: Action[] = [
    { title: 'Invite your first people',   hint: 'Send an invitation to someone you love.', href: `/creator/spaces/${slug}/community` },
    { title: 'Build your first pathway',   hint: 'A first path for people to walk.',        href: `/creator/spaces/${slug}/pathways` },
    { title: 'Light your first gathering', hint: 'Set a live moment on the calendar.',       href: `/creator/spaces/${slug}/events/new` },
    { title: 'Add your first resource',    hint: 'A single thing worth returning to.',       href: `/creator-studio/resources` },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-6 py-10"
      style={{
        background: 'rgba(12, 24, 38, 0.42)',
        backdropFilter: 'blur(4px)',
        animation: leaving
          ? 'byp-arrival-out 350ms ease-in both'
          : 'byp-backdrop-in 350ms ease-out both',
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="fc-arrival-title"
      onAnimationEnd={handleAnimationEnd}
    >
      <div
        className="relative w-full max-w-[640px] overflow-hidden rounded-3xl"
        style={{
          background: '#FFFFFF',
          border: '1px solid rgba(12, 24, 38, 0.06)',
          boxShadow: '0 30px 80px rgba(12, 24, 38, 0.20)',
          animation: leaving
            ? 'byp-arrival-out 350ms ease-in both'
            : 'byp-arrival-in 400ms cubic-bezier(0.16, 1, 0.3, 1) both',
        }}
      >
        <div className="px-8 pt-10 text-center">
          <SproutGlyph />
        </div>

        <div className="px-8 pt-4 text-center">
          <h2
            id="fc-arrival-title"
            className="font-serif text-[24px] leading-tight md:text-[28px]"
            style={{ color: '#0C1826' }}
          >
            Your island has been planted.
          </h2>
          <p
            className="mx-auto mt-3 max-w-[420px] text-[14.5px] italic leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.68)', fontFamily: 'Georgia, serif' }}
          >
            It will grow as people gather, learn and create here.
          </p>
          <div
            className="mx-auto mt-6 h-[2px] w-14 rounded-full"
            style={{ background: 'linear-gradient(90deg, #38A09E 0%, #D4B048 100%)' }}
            aria-hidden="true"
          />
        </div>

        <div className="grid grid-cols-1 gap-2.5 px-6 py-8 sm:grid-cols-2 md:px-8">
          {actions.map((a) => (
            <Link
              key={a.title}
              href={a.href}
              onClick={dismiss}
              className="group flex flex-col items-start rounded-2xl px-4 py-4 text-left transition-colors"
              style={{
                background: '#FFFFFF',
                border: '1px solid rgba(12, 24, 38, 0.08)',
              }}
            >
              <span
                className="mb-2 h-[2px] w-6 rounded-full transition-all duration-500 group-hover:w-10"
                style={{
                  background: 'linear-gradient(90deg, #38A09E 0%, transparent 100%)',
                }}
              />
              <span
                className="text-[13.5px] font-semibold leading-snug"
                style={{ color: '#0C1826' }}
              >
                {a.title}
              </span>
              <span
                className="mt-1 text-[12.5px] leading-relaxed italic"
                style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
              >
                {a.hint}
              </span>
            </Link>
          ))}
        </div>

        <div
          className="border-t px-6 py-4 text-center"
          style={{ borderColor: 'rgba(12, 24, 38, 0.06)' }}
        >
          <button
            type="button"
            onClick={dismiss}
            className="text-[13px] font-medium transition-opacity hover:opacity-70"
            style={{ color: 'rgba(12, 24, 38, 0.62)' }}
          >
            Enter creator studio
          </button>
        </div>
      </div>
    </div>
  )
}

function SproutGlyph() {
  return (
    <svg
      viewBox="0 0 60 60"
      className="mx-auto h-14 w-14"
      fill="none"
      stroke="#38A09E"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M30 48 L 30 30" />
      <path d="M30 34 C 20 34 16 26 18 20 C 26 22 30 28 30 34 Z" fill="rgba(56, 160, 158, 0.10)" />
      <path d="M30 30 C 40 30 44 22 42 16 C 34 18 30 24 30 30 Z" fill="rgba(212, 176, 72, 0.10)" stroke="#D4B048" />
      <path d="M18 50 Q 30 46 42 50" stroke="rgba(12, 24, 38, 0.35)" />
    </svg>
  )
}
