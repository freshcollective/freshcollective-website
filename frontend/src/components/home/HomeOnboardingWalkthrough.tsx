'use client'

import { useState, useCallback } from 'react'
import Container from '@/components/layout/Container'

const NAVY = '#0C1826'
const WARM_OFF_WHITE = '#F7F4EE'
const BODY_ON_NAVY = 'rgba(247, 244, 238, 0.80)'
const TEAL_DEEP = '#246B6A'
const WARM_GOLD = '#EDBE5D'

interface StepDef {
  artKey: string
  /** Container aspect ratio matched to the source crop so no
   *  meaningful UI is lost at rendering time. */
  aspectRatio: string
  /** Where to align the image inside its container. `top` for the
   *  taller portraits so headings stay visible. */
  imagePosition: 'top' | 'center'
  heading: string
  copy: string
}

const STEPS: readonly StepDef[] = [
  {
    artKey: 'homepage_onboarding_begin_shaping',
    aspectRatio: '1047 / 800',
    imagePosition: 'top',
    heading: 'Begin with the idea',
    copy:
      "We don\u2019t drop you into an empty dashboard. We start by " +
      "helping you shape what this Collective is here to be \u2014 and " +
      "explain the language as you go.",
  },
  {
    artKey: 'homepage_onboarding_shape_the_feeling',
    aspectRatio: '1089 / 780',
    imagePosition: 'center',
    heading: 'Design how it should feel',
    copy:
      "Before colours or settings, we ask about the experience. How " +
      "should people feel when they arrive?",
  },
  {
    artKey: 'homepage_onboarding_choose_island',
    aspectRatio: '939 / 990',
    imagePosition: 'top',
    heading: 'Give it a vibe of its own',
    copy:
      "Choose an island that fits the atmosphere you\u2019re creating " +
      "\u2014 a vibe made visual for your members to recognise and " +
      "want to return to.",
  },
  {
    artKey: 'homepage_onboarding_practical_settings',
    aspectRatio: '999 / 1300',
    imagePosition: 'top',
    heading: 'Then do the practical bits',
    copy:
      "Name it, choose who can find it, and decide how people step in. " +
      "The practical setup comes after you\u2019ve set up the feeling.",
  },
]

interface Props {
  /** Pre-resolved URLs for each step's PlatformArtwork slot. The parent
   *  server component resolves these via `artFor()` and passes them
   *  down so this interactive component doesn't need direct backend
   *  access. */
  screenshotUrls: Record<string, string | null>
}

export default function HomeOnboardingWalkthrough({ screenshotUrls }: Props) {
  const [activeIndex, setActiveIndex] = useState(0)
  const active = STEPS[activeIndex]
  const activeSrc = screenshotUrls[active.artKey] ?? null

  const onKey = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
      e.preventDefault()
      setActiveIndex((i) => (i + 1) % STEPS.length)
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
      e.preventDefault()
      setActiveIndex((i) => (i - 1 + STEPS.length) % STEPS.length)
    } else if (e.key === 'Home') {
      e.preventDefault()
      setActiveIndex(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      setActiveIndex(STEPS.length - 1)
    }
  }, [])

  return (
    <section
      className="pt-6 pb-20 md:pt-8 md:pb-24"
      style={{ background: NAVY }}
    >
      <Container>
        <div className="mx-auto max-w-[820px] text-center">
          <p
            className="text-[15px] leading-[1.4] sm:text-[17px]"
            style={{ color: BODY_ON_NAVY, fontFamily: 'Georgia, serif' }}
          >
            Most platforms hand you an empty dashboard and a blinking
            cursor...
          </p>
          <h2
            className="mt-3 font-serif leading-[1.1]"
            style={{
              fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
              letterSpacing: '-0.03em',
              color: WARM_OFF_WHITE,
            }}
          >
            We ask about your{' '}
            <span style={{ color: WARM_GOLD }}>vision</span> instead.
          </h2>
          <p
            className="mx-auto mt-6 max-w-[640px] text-[15.5px] leading-relaxed"
            style={{ color: BODY_ON_NAVY, fontFamily: 'Georgia, serif' }}
          >
            In about 10–15 minutes, you&rsquo;ll shape the beginnings of
            your Collective — who it&rsquo;s for, how people will be
            welcomed, what it should feel like and the practical choices
            underneath it. Nothing is permanent. You can change any of
            it later.
          </p>
        </div>

        <div
          role="tablist"
          aria-label="Creator onboarding walkthrough"
          onKeyDown={onKey}
          className="mx-auto mt-14 grid max-w-[1200px] items-start gap-10 md:mt-16 md:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] md:gap-14"
        >
          <div
            role="tabpanel"
            id={`onboarding-panel-${active.artKey}`}
            aria-labelledby={`onboarding-tab-${active.artKey}`}
            className="w-full"
          >
            <ScreenshotShowcase step={active} src={activeSrc} />
          </div>

          {/* Step selector — vertical list beside the screenshot on
              desktop; stacks below on mobile. Inactive buttons use
              high-contrast white type so they remain fully legible
              against navy (deliberately no "muted grey" state — the
              user needs to be able to read all four choices). Active
              step flips to a warm off-white card with teal heading +
              navy body so its selected state is unmistakable. */}
          <ol className="flex flex-col gap-3">
            {STEPS.map((step, i) => (
              <li key={step.artKey}>
                <StepButton
                  step={step}
                  active={i === activeIndex}
                  onSelect={() => setActiveIndex(i)}
                />
              </li>
            ))}
          </ol>
        </div>
      </Container>
    </section>
  )
}

function ScreenshotShowcase({
  step,
  src,
}: {
  step: StepDef
  src: string | null
}) {
  const positionClass =
    step.imagePosition === 'top' ? 'object-top' : 'object-center'
  return (
    <div
      className="relative w-full overflow-hidden rounded-2xl bg-white transition-all duration-300"
      style={{
        aspectRatio: step.aspectRatio,
        border: '1px solid rgba(255, 255, 255, 0.08)',
        boxShadow:
          '0 24px 60px rgba(0, 0, 0, 0.35), 0 6px 20px rgba(0, 0, 0, 0.18)',
      }}
      key={step.artKey}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={`Fresh Collective creator onboarding — ${step.heading}`}
          className={`absolute inset-0 h-full w-full object-cover ${positionClass}`}
        />
      ) : (
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{
            background:
              'linear-gradient(160deg, #F7F4EE 0%, #EFEBE1 55%, #E7E2D3 100%)',
          }}
        >
          <div className="flex flex-col items-center gap-2 px-8 text-center">
            <span
              className="text-[10.5px] font-semibold uppercase"
              style={{ color: NAVY, letterSpacing: '0.22em', opacity: 0.55 }}
            >
              Product screenshot
            </span>
            <span
              className="text-[13px] italic"
              style={{ color: NAVY, fontFamily: 'Georgia, serif', opacity: 0.65 }}
            >
              {step.heading}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function StepButton({
  step,
  active,
  onSelect,
}: {
  step: StepDef
  active: boolean
  onSelect: () => void
}) {
  // Interactive state via Tailwind classes rather than inline `style`
  // so hover / focus can override cleanly. Base colours + shadows are
  // set through classes for the same reason. `group-hover` on the
  // chevron below tracks the button's hover state.
  //
  // Screenshot activation is click-only (`onClick`) — hover never
  // swaps the showcase, so the user isn't jumped between screens
  // just by mousing over the list.
  const base =
    'group flex w-full cursor-pointer flex-col rounded-xl border px-5 py-4 text-left transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7FDAD9] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0C1826]'
  const activeStyles =
    'border-[rgba(255,255,255,0.95)] bg-white shadow-[0_14px_32px_rgba(0,0,0,0.25),0_2px_6px_rgba(0,0,0,0.15)]'
  const inactiveStyles =
    'border-[rgba(255,255,255,0.16)] bg-transparent hover:-translate-y-0.5 hover:border-[rgba(127,218,217,0.55)] hover:bg-[rgba(255,255,255,0.04)] hover:shadow-[0_10px_24px_rgba(0,0,0,0.20)]'

  return (
    <button
      type="button"
      role="tab"
      id={`onboarding-tab-${step.artKey}`}
      aria-selected={active}
      aria-controls={`onboarding-panel-${step.artKey}`}
      tabIndex={active ? 0 : -1}
      onClick={onSelect}
      className={`${base} ${active ? activeStyles : inactiveStyles}`}
    >
      <div className="flex items-center justify-between gap-3">
        <h3
          className="font-serif text-[17px] leading-tight md:text-[18px]"
          style={{
            color: active ? TEAL_DEEP : '#FFFFFF',
            letterSpacing: '-0.01em',
          }}
        >
          {step.heading}
        </h3>
        {/* Inactive cards carry a small teal chevron at the far right
            — a quiet affordance that this row is a selector, not a
            block of copy. Removed on the active card so the selected
            state reads as "arrived", not "next". */}
        {!active && (
          <span
            aria-hidden="true"
            className="shrink-0 text-[16px] leading-none transition-transform duration-200 group-hover:translate-x-0.5"
            style={{ color: 'rgba(127, 218, 217, 0.75)' }}
          >
            →
          </span>
        )}
      </div>
      <p
        className="mt-2 text-[13.5px] leading-relaxed"
        style={{
          color: active ? NAVY : 'rgba(255, 255, 255, 0.82)',
          fontFamily: 'Georgia, serif',
        }}
      >
        {step.copy}
      </p>
    </button>
  )
}
