'use client'

import { useEffect, useMemo, useRef } from 'react'
import { resolveMediaUrl } from '@/lib/api'
import { Button } from '@/components/platform/Button'
import type { LocationOption } from '@/lib/build-your-collective/types'
import { splitParagraphs } from './islandDetailUtils'

/**
 * Island detail overlay. Opens on top of the island grid when a
 * creator clicks a card, so they can properly see the artwork and
 * read the Atlas Entry before committing. The Location row remains
 * the single source of truth — no field is duplicated onto Space.
 *
 * Behaviour:
 *   * ``onChoose`` is only offered when this island is NOT the
 *     current selection. For the current island a calm status pill
 *     is shown and the primary action becomes "Close" — the creator
 *     never has to accept their existing choice again just to keep
 *     browsing.
 *   * ESC + backdrop-click close (mirroring the Fresh Collective
 *     Modal primitive's contract; implemented locally because we
 *     need a wider, hero-forward layout than the shared Modal
 *     currently offers).
 *   * Focus moves to the primary action on open and is restored to
 *     the invoking card on close.
 */

interface Props {
  open: boolean
  location: LocationOption | null
  isCurrent: boolean
  onChoose: (id: string) => void
  onClose: () => void
}

export default function IslandDetailModal({
  open, location, isCurrent, onChoose, onClose,
}: Props) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const primaryRef = useRef<HTMLButtonElement | null>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    returnFocusRef.current = document.activeElement as HTMLElement | null
    const t = window.setTimeout(() => primaryRef.current?.focus(), 30)
    return () => {
      window.clearTimeout(t)
      // Restore focus to the invoking element (the island card) so
      // keyboard users don't get dropped at the top of the page.
      returnFocusRef.current?.focus?.()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose() }
      if (e.key === 'Tab') trapFocus(e, dialogRef.current)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [open])

  const paragraphs = useMemo(
    () => splitParagraphs(location?.atlas_entry ?? null),
    [location?.atlas_entry],
  )

  if (!open || !location) return null

  const artworkUrl = resolveMediaUrl(
    location.hero_artwork_url ?? location.thumbnail_artwork_url ?? undefined,
  )

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="island-detail-title"
      className="fixed inset-0 z-[var(--fc-z-modal)] flex items-start justify-center p-4 sm:items-center"
    >
      <div
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-black/50"
        style={{ animation: 'fc-fade-in 180ms ease-out' }}
      />
      <div
        ref={dialogRef}
        className="relative flex w-full max-w-3xl flex-col overflow-hidden rounded-[var(--fc-radius-2xl)] bg-white shadow-[var(--fc-elev-5)]"
        style={{
          animation: 'fc-modal-in 180ms ease-out',
          maxHeight: 'calc(100dvh - 2rem)',
        }}
      >
        {/* Header: artwork hero. 5:4 matches the dominant source aspect
            of Location.hero_artwork_url (15/25 active images are 5:4;
            the rest are handled by ``object-contain``). Standardises the
            Atlas artwork treatment across admin viewer, creator picker
            and this modal. */}
        <div
          className="relative w-full shrink-0 overflow-hidden"
          style={{
            aspectRatio: '5 / 4',
            background: 'linear-gradient(135deg, #E5F0EF 0%, #F4F7F6 60%, #FBFDFC 100%)',
          }}
        >
          {artworkUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={artworkUrl}
              alt={location.name}
              className="h-full w-full"
              // ``contain`` (not ``cover``) so square source artwork —
              // which the Atlas admin uploads at their natural crop —
              // is shown in full, matching what the admin sees in the
              // Atlas viewer. The soft gradient behind the image
              // handles any letterboxing.
              style={{ objectFit: 'contain', objectPosition: 'center', display: 'block' }}
            />
          ) : (
            <ArtworkPlaceholder label={location.name} />
          )}
          {/* Close button sits over the artwork; contrast-safe circle. */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="absolute right-3 top-3 grid h-9 w-9 place-items-center rounded-full bg-black/40 text-white backdrop-blur-sm transition hover:bg-black/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/80"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Body: scrolls when the Atlas Entry is long. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 md:px-10 md:py-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2
              id="island-detail-title"
              className="font-serif text-[26px] leading-tight md:text-[32px]"
              style={{ color: '#0C1826' }}
            >
              {location.name}
            </h2>
            {isCurrent && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11.5px] font-semibold uppercase tracking-[0.14em]"
                style={{
                  background: 'rgba(56, 160, 158, 0.10)',
                  color: '#246B6A',
                  border: '1px solid rgba(56, 160, 158, 0.24)',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <path d="M2.5 6.2l2.4 2.4L9.7 3.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Your current island
              </span>
            )}
          </div>

          {location.description && (
            <p
              className="mt-3 text-[14.5px] italic leading-relaxed"
              style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
            >
              {location.description}
            </p>
          )}

          <div className="mt-6">
            {paragraphs.length > 0 ? (
              <div
                className="space-y-4 text-[16px] leading-relaxed"
                style={{ color: '#152236', fontFamily: 'Georgia, serif' }}
              >
                {paragraphs.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            ) : (
              <p
                className="text-[14.5px] italic"
                style={{ color: 'rgba(12, 24, 38, 0.50)', fontFamily: 'Georgia, serif' }}
              >
                No Atlas Entry yet for this island.
              </p>
            )}
          </div>
        </div>

        {/* Actions row. Primary action varies by current-island state. */}
        <footer
          className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-6 py-4 md:px-10"
          style={{ borderColor: 'rgba(12, 24, 38, 0.08)' }}
        >
          {isCurrent ? (
            <Button ref={primaryRef} variant="primary" size="md" onClick={onClose}>
              Close
            </Button>
          ) : (
            <>
              <Button variant="tertiary" size="md" onClick={onClose}>
                Keep browsing
              </Button>
              <Button
                ref={primaryRef}
                variant="primary"
                size="md"
                onClick={() => onChoose(location.id)}
              >
                Choose this island
              </Button>
            </>
          )}
        </footer>
      </div>
    </div>
  )
}


function trapFocus(e: KeyboardEvent, container: HTMLElement | null) {
  if (!container) return
  const focusables = container.querySelectorAll<HTMLElement>(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )
  if (focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const active = document.activeElement as HTMLElement | null
  if (e.shiftKey && active === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && active === last) {
    e.preventDefault()
    first.focus()
  }
}


function ArtworkPlaceholder({ label }: { label: string }) {
  return (
    <svg viewBox="0 0 500 400" preserveAspectRatio="xMidYMid slice" className="h-full w-full" aria-hidden="true">
      <defs>
        <radialGradient id={`isl-ph-${label}`} cx="0.5" cy="0.5" r="0.65">
          <stop offset="0%" stopColor="#E5F0EF" />
          <stop offset="60%" stopColor="#F4F7F6" />
          <stop offset="100%" stopColor="#FBFDFC" />
        </radialGradient>
      </defs>
      <rect width="500" height="400" fill={`url(#isl-ph-${label})`} />
      <g fill="none" stroke="rgba(56, 160, 158, 0.18)" strokeWidth="1">
        <ellipse cx="250" cy="220" rx="160" ry="70" />
        <ellipse cx="250" cy="220" rx="105" ry="48" />
      </g>
      <text x="250" y="350" textAnchor="middle" fill="rgba(12,24,38,0.45)" fontFamily="Georgia, serif" fontStyle="italic" fontSize="18">
        {label}
      </text>
    </svg>
  )
}
