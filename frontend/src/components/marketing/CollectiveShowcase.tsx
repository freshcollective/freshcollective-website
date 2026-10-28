'use client'

import Image from 'next/image'
import { useCallback, useEffect, useRef, useState } from 'react'

import Container from '@/components/layout/Container'
import {
  SHOWCASE_DEFAULT_ID,
  SHOWCASE_HEADING,
  SHOWCASE_INTRO,
  SHOWCASE_SHOTS,
} from '@/lib/collectiveShowcase'

/**
 * The Moonlit Circle showcase on /for-creators.
 *
 * One large screenshot and four previews beneath it. Choosing a
 * preview swaps the picture and its description; nothing navigates,
 * nothing reloads, nothing rotates on its own.
 *
 * **The hard part is that the four screenshots are different
 * shapes** — 1.20, 0.68, 0.98 and 1.47 — and the two useful
 * properties are in tension. Fitting each one into a shared box means
 * scaling the tall Pathway step to about two-fifths, which is exactly
 * the point at which its interface text stops being readable. Letting
 * each one size itself means the section below jumps by hundreds of
 * pixels every time somebody clicks.
 *
 * So the frame is a **fixed-height window and the image is rendered
 * at full width inside it**. Proportions are untouched — nothing is
 * cropped, stretched or letterboxed — the window simply shows as much
 * as it can and scrolls for the rest. The box never changes size, so
 * the page below cannot move at all, and the Pathway step keeps the
 * scale it needs.
 *
 * When an image is taller than the window a fade and a label say so,
 * and both disappear once the reader reaches the bottom. The window
 * takes focus and scrolls with the keyboard. For a phone, where even
 * full width is not much, "Open full size" hands the original file to
 * the browser, which already knows how to pinch and zoom — cheaper
 * and more capable than any lightbox worth writing.
 */

const NAVY = '#0C1826'
const TEAL_DEEP = '#246B6A'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'
const HAIRLINE = 'rgba(12, 24, 38, 0.12)'

/** The frame the public site uses for imagery. */
const FRAME_SHADOW =
  '0 24px 60px rgba(12, 24, 38, 0.14), 0 6px 20px rgba(12, 24, 38, 0.08)'

/**
 * The viewing window.
 *
 * 660px at desktop is set by the shallowest screenshot: Offerings is
 * 1099 × 747, which at 958px wide comes out 651px tall — so it fits
 * whole, with nine pixels to spare, and the window never looks like
 * it is hiding something for no reason. The smaller steps keep the
 * same intent at each width.
 */
const WINDOW_HEIGHT = 'h-[340px] sm:h-[440px] lg:h-[660px]'

/**
 * How much has to be hidden before the window admits it.
 *
 * A few pixels of trailing edge is not "more to explore", and saying
 * so makes the label mean less when something genuinely is cut off.
 */
const SCROLL_HINT_THRESHOLD = 24

export default function CollectiveShowcase() {
  const [selectedId, setSelectedId] = useState(SHOWCASE_DEFAULT_ID)
  const [canScroll, setCanScroll] = useState(false)
  const [atEnd, setAtEnd] = useState(false)
  const windowRef = useRef<HTMLDivElement>(null)

  const selected =
    SHOWCASE_SHOTS.find((s) => s.id === selectedId) ?? SHOWCASE_SHOTS[0]!

  const measure = useCallback(() => {
    const el = windowRef.current
    if (!el) return
    const overflowing =
      el.scrollHeight - el.clientHeight > SCROLL_HINT_THRESHOLD
    setCanScroll(overflowing)
    setAtEnd(!overflowing || el.scrollTop + el.clientHeight >= el.scrollHeight - 8)
  }, [])

  // The window's height changes at two breakpoints, so what fits is a
  // function of the viewport as well as of the picture.
  useEffect(() => {
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure])

  const select = useCallback((id: string) => {
    setSelectedId(id)
    // Start each screenshot at its top rather than wherever the last
    // one happened to be left.
    windowRef.current?.scrollTo({ top: 0 })
  }, [])

  return (
    <section className="pb-16 sm:pb-20" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className="mx-auto max-w-[680px] text-center">
          <h2
            className="font-serif leading-[1.1]"
            style={{
              fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
              letterSpacing: '-0.03em',
              color: NAVY,
            }}
          >
            {SHOWCASE_HEADING}
          </h2>
          <p
            className="mx-auto mt-5 max-w-[600px] text-[15.5px] italic leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            {SHOWCASE_INTRO}
          </p>
        </div>

        <div className="mx-auto mt-10 max-w-[960px] sm:mt-12">
          {/* ── The window ───────────────────────────────────────── */}
          <div
            className="relative overflow-hidden rounded-3xl bg-white"
            style={{ boxShadow: FRAME_SHADOW, border: `1px solid ${HAIRLINE}` }}
          >
            <div
              ref={windowRef}
              onScroll={measure}
              tabIndex={0}
              role="group"
              aria-label={`${selected.label} — screenshot. Scrollable.`}
              className={`${WINDOW_HEIGHT} overflow-y-auto overscroll-contain focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#246B6A]`}
            >
              <Image
                key={selected.id}
                src={selected.src}
                alt={selected.alt}
                width={selected.width}
                height={selected.height}
                sizes="(min-width: 1024px) 960px, 100vw"
                /* Only the one that is there before anybody clicks. */
                priority={selected.id === SHOWCASE_DEFAULT_ID}
                onLoad={measure}
                className="block h-auto w-full"
              />
            </div>

            {/* More to see. Both halves go once the bottom is reached;
                neither is announced, because the window itself is
                already reachable and scrollable without them. */}
            {canScroll && !atEnd && (
              <>
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-x-0 bottom-0 h-20"
                  style={{
                    background:
                      'linear-gradient(to top, rgba(255,255,255,0.92) 0%, rgba(255,255,255,0) 100%)',
                  }}
                />
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute bottom-3.5 left-1/2 -translate-x-1/2 rounded-full bg-white/95 px-3 py-1 text-[11.5px] font-medium"
                  style={{ color: TEAL_DEEP, border: `1px solid ${HAIRLINE}` }}
                >
                  Scroll to see more ↓
                </span>
              </>
            )}
          </div>

          {/* ── What you are looking at ──────────────────────────── */}
          <div className="mt-5 flex flex-col items-center gap-1.5 text-center">
            <p
              aria-live="polite"
              className="text-[15.5px] leading-relaxed"
              style={{ color: NAVY, fontFamily: 'Georgia, serif' }}
            >
              {selected.description}
            </p>
            <a
              href={selected.src}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-sm text-[13px] underline decoration-1 underline-offset-4 transition-colors hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
              style={{ color: TEAL_DEEP, textDecorationColor: 'rgba(36,107,106,0.35)' }}
            >
              Open full size ↗
            </a>
          </div>

          {/* ── The four previews ────────────────────────────────── */}
          {/*
            A horizontal rail that only scrolls when it has to. The
            buttons carry `aria-pressed` rather than tab semantics:
            four toggles in a group say what they are with no roving
            tabindex to get wrong, and every one of them is reachable
            with Tab on its own.
          */}
          <div
            role="group"
            aria-label="Choose a screenshot to view"
            className="mt-8 flex gap-3 overflow-x-auto pb-2 sm:mt-9 sm:justify-center sm:gap-4 sm:overflow-x-visible"
          >
            {SHOWCASE_SHOTS.map((shot) => {
              const isSelected = shot.id === selected.id
              return (
                <button
                  key={shot.id}
                  type="button"
                  onClick={() => select(shot.id)}
                  aria-pressed={isSelected}
                  className="group w-[132px] shrink-0 rounded-xl p-1.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A] sm:w-[150px]"
                  style={{
                    background: isSelected ? 'rgba(36, 107, 106, 0.07)' : 'transparent',
                  }}
                >
                  <span
                    className="block w-full overflow-hidden rounded-lg"
                    style={{
                      aspectRatio: '4 / 3',
                      // The selected state is a teal edge, not a
                      // heavy card: two pixels at full strength, one
                      // hairline otherwise.
                      boxShadow: isSelected
                        ? `0 0 0 2px ${TEAL_DEEP}`
                        : `0 0 0 1px ${HAIRLINE}`,
                    }}
                  >
                    <Image
                      src={shot.src}
                      alt=""
                      width={shot.width}
                      height={shot.height}
                      sizes="150px"
                      className="h-full w-full object-cover object-top transition-opacity group-hover:opacity-90"
                    />
                  </span>
                  <span
                    className="mt-2 block text-[13px] font-medium leading-snug"
                    style={{ color: isSelected ? TEAL_DEEP : INK_SOFT }}
                  >
                    {shot.label}
                  </span>
                </button>
              )
            })}
          </div>

        </div>
      </Container>
    </section>
  )
}
