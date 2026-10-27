'use client'

import Image from 'next/image'
import { useCallback, useRef, useState } from 'react'

import Container from '@/components/layout/Container'
import EmbedRenderer from '@/components/EmbedRenderer'
import ShowAroundInvitation from '@/components/marketing/ShowAroundInvitation'
import {
  HOME_INTRO_VIDEO_BODY,
  HOME_INTRO_VIDEO_HEADING,
  HOME_INTRO_VIDEO_PLAY_LABEL,
  HOME_INTRO_VIDEO_POSTER_ALT,
  HOME_INTRO_VIDEO_POSTER_SRC,
  HOME_INTRO_VIDEO_TITLE,
  homeIntroVideoEmbedUrl,
} from '@/lib/homeIntroVideo'

/**
 * "Take a look inside Fresh Collective" — the one-minute tour, played
 * on the homepage rather than on YouTube's.
 *
 * A facade, not an embed. Until someone asks for the video this
 * section is a local image and a button: no iframe, no YouTube
 * script, no third-party request of any kind. The player is inserted
 * on activation and nowhere else, which is what keeps a marketing
 * page that nobody clicked free of another origin's code.
 *
 * The player itself is ``EmbedRenderer`` — the component the member
 * and creator surfaces already use for video. Reusing it means this
 * section inherits the sandbox, the referrer policy, the ``allow``
 * list and the 16:9 box that were argued for once, and adds only the
 * part that did not exist: the click that comes first.
 *
 * No layout shift at any point. The frame declares ``aspect-video``
 * and both states fill it exactly, so the box is the same size before
 * the poster loads, after it loads and after the player replaces it.
 */

// Same tokens the neighbouring homepage sections declare. Local by
// convention here — HomeWhatThisIs and HomeFriction each carry their
// own copy rather than importing a shared palette module.
const NAVY = '#0C1826'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'
const TEAL_DEEP = '#246B6A'

/** The frame the homepage uses for imagery: `rounded-3xl` over a soft
 *  ambient shadow, the same pair ArtworkFeatureComposition sets. */
const FRAME_SHADOW =
  '0 24px 60px rgba(12, 24, 38, 0.14), 0 6px 20px rgba(12, 24, 38, 0.08)'

export default function HomeIntroVideo() {
  const [playing, setPlaying] = useState(false)
  const frameRef = useRef<HTMLDivElement>(null)

  const start = useCallback(() => {
    setPlaying(true)
    // Hand the keyboard to the player. Without this the focus the
    // button held is destroyed along with the button, and focus falls
    // back to <body> — so the next Tab starts from the top of the
    // page and the player's own space/arrow controls reach nothing.
    requestAnimationFrame(() => {
      frameRef.current?.querySelector('iframe')?.focus()
    })
  }, [])

  return (
    <section className="py-12 md:py-16" style={{ background: '#FFFFFF' }}>
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
            {HOME_INTRO_VIDEO_HEADING}
          </h2>
          <p
            className="mx-auto mt-5 max-w-[560px] text-[15.5px] italic leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            {HOME_INTRO_VIDEO_BODY}
          </p>
        </div>

        {/*
          880px rather than the 1160px the editorial rows use. Large
          enough to watch without leaning in, small enough that the
          section stays one moment in the page instead of becoming the
          page — which is what the brief asked for.

          Black ground under both states: the player's own frame is
          black, so matching it here means the corner between this
          radius and the player's reads as one shape rather than a
          white sliver.
        */}
        <div className="mx-auto mt-9 max-w-[880px] md:mt-11">
          <div
            ref={frameRef}
            className="relative aspect-video w-full overflow-hidden rounded-3xl bg-black"
            style={{ boxShadow: FRAME_SHADOW }}
          >
            {playing ? (
              <div className="absolute inset-0">
                <EmbedRenderer
                  url={homeIntroVideoEmbedUrl({ autoplay: true })}
                  title={HOME_INTRO_VIDEO_TITLE}
                />
              </div>
            ) : (
              <button
                type="button"
                onClick={start}
                aria-label={HOME_INTRO_VIDEO_PLAY_LABEL}
                className="group absolute inset-0 h-full w-full cursor-pointer focus:outline-none"
              >
                <Image
                  src={HOME_INTRO_VIDEO_POSTER_SRC}
                  alt={HOME_INTRO_VIDEO_POSTER_ALT}
                  fill
                  sizes="(min-width: 960px) 880px, 100vw"
                  className="object-cover object-center"
                />
                {/*
                  The focus ring.

                  It has to be its own positioned layer. An `outline`
                  on the button does compute — 4px, solid, teal — and
                  paints nothing, because the poster is an absolutely
                  positioned child and positioned descendants paint
                  over a non-positioned parent's outline. An outward
                  ring is no better: `overflow-hidden` rounds this
                  frame's corners and would cut it off.

                  Two colours rather than one, drawn as nested inset
                  shadows. The ring runs around the whole photograph,
                  crossing bright sky at the top and the navy title
                  band at the foot, and no single colour is visible
                  against both — so white carries it over the dark
                  half and teal over the light half.
                */}
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-150 group-focus-visible:opacity-100"
                  style={{
                    boxShadow: `inset 0 0 0 4px #FFFFFF, inset 0 0 0 8px ${TEAL_DEEP}`,
                  }}
                />
                {/* The play control. Teal on the page's own palette,
                    sized so it reads on a phone without covering the
                    title card behind it. */}
                <span
                  aria-hidden="true"
                  className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full transition-transform duration-200 ease-out group-hover:scale-110 group-focus-visible:scale-110 md:h-20 md:w-20"
                  style={{
                    background: TEAL_DEEP,
                    boxShadow: '0 8px 24px rgba(12, 24, 38, 0.35)',
                  }}
                >
                  {/* Optical centring: a triangle's visual centre sits
                      left of its bounding box, so it is nudged right. */}
                  <svg
                    width="22"
                    height="26"
                    viewBox="0 0 22 26"
                    fill="none"
                    className="ml-[3px] md:h-[30px] md:w-[26px]"
                  >
                    <path d="M21 13 0 26V0z" fill="#FFFFFF" />
                  </svg>
                </span>
              </button>
            )}
          </div>

          {/* The second way in, for someone who would rather be shown
              than watch. Close enough under the frame to read as part
              of this section, quiet enough that the video stays the
              thing being offered. */}
          <ShowAroundInvitation className="mt-7" />
        </div>
      </Container>
    </section>
  )
}
