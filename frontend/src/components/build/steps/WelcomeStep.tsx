'use client'

import StepShell from '../StepShell'

interface Props {
  onBegin: () => void
}

interface GlossaryItem {
  emoji: string
  term: string
  body: string
}

const GLOSSARY: GlossaryItem[] = [
  {
    emoji: '🏝️',
    term: 'Collective',
    body: 'Your community within the Fresh Collective world.',
  },
  {
    emoji: '🌿',
    term: 'Place',
    body: 'The unique atmosphere and identity of your collective.',
  },
  {
    emoji: '🧭',
    term: 'Pathways',
    body: 'Guided experiences that help members learn and grow.',
  },
  {
    emoji: '🤝',
    term: 'Gatherings',
    body: 'Events where people come together online or in person.',
  },
  {
    emoji: '💬',
    term: 'Conversations',
    body: 'A place for members to connect and support one another.',
  },
]

/**
 * Step 0 — Orientation. The creator's first quiet moment: a warm
 * welcome, a few key terms, and reassurance that nothing here is
 * permanent. Leads gently into the Location step.
 */
export default function WelcomeStep({ onBegin }: Props) {
  return (
    <StepShell
      stepIndex={0}
      spacious
      onContinue={onBegin}
      continueLabel="Let's begin →"
    >
      <div className="mx-auto max-w-[640px] pt-2 text-center">
        <p
          className="mb-5 text-[11px] font-semibold uppercase tracking-[0.32em]"
          style={{ color: '#38A09E' }}
        >
          👋 Welcome, Creator
        </p>
        <h1
          className="font-serif text-[28px] leading-[1.2] md:text-[36px]"
          style={{ color: '#0C1826' }}
        >
          Let&rsquo;s begin shaping your collective.
        </h1>
        <p
          className="mx-auto mt-6 max-w-[520px] text-[15.5px] leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.72)', fontFamily: 'Georgia, serif' }}
        >
          Over the next few minutes, we&rsquo;ll shape the foundations of
          your collective together — its atmosphere, its voice, and the
          experiences people will share there.
        </p>
        <p
          className="mx-auto mt-3 max-w-[520px] text-[14.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
        >
          Nothing needs to be perfect. Every choice can be changed later.
        </p>

        <div
          className="mx-auto mt-10 h-[2px] w-14 rounded-full"
          style={{ background: 'linear-gradient(90deg, #38A09E 0%, #D4B048 100%)' }}
          aria-hidden="true"
        />

        <p
          className="mt-10 text-[11px] font-semibold uppercase tracking-[0.28em]"
          style={{ color: 'rgba(12, 24, 38, 0.55)' }}
        >
          A little of the language we use here
        </p>

        <ul className="mx-auto mt-6 flex max-w-[520px] flex-col gap-4 text-left">
          {GLOSSARY.map((item) => (
            <li
              key={item.term}
              className="flex items-start gap-4 rounded-2xl bg-white px-5 py-4"
              style={{
                border: '1px solid rgba(12, 24, 38, 0.06)',
                boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
              }}
            >
              <span
                className="shrink-0 text-[22px] leading-none"
                aria-hidden="true"
              >
                {item.emoji}
              </span>
              <div>
                <p
                  className="text-[14px] font-semibold leading-tight"
                  style={{ color: '#0C1826' }}
                >
                  {item.term}
                </p>
                <p
                  className="mt-1 text-[13.5px] italic leading-relaxed"
                  style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
                >
                  {item.body}
                </p>
              </div>
            </li>
          ))}
        </ul>

        <p
          className="mx-auto mt-10 max-w-[520px] text-[14.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
        >
          Today we&rsquo;re simply creating the foundations of your
          collective. Once it&rsquo;s open,{' '}
          <span
            className="font-semibold not-italic"
            style={{ color: '#38A09E', fontFamily: 'inherit' }}
          >
            World Builders
          </span>{' '}
          will guide you through bringing it to life.
        </p>
      </div>
    </StepShell>
  )
}
