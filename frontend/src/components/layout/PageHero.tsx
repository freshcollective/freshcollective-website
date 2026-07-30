import type { ReactNode } from 'react'
import Container from './Container'

/**
 * PageHero — shared contained navy hero for member-facing
 * discovery destinations.
 *
 * Used by:
 *   /spaces           (Explore Collectives)
 *   /discover-places  (Discover Places)
 *   /ways-to-connect  (Ways to Connect)
 *
 * Deliberately NOT used by:
 *   /dashboard        — Your World's full-bleed personal welcome
 *                        band lives in the dashboard page itself.
 *   /spaces/[slug]/*  — the per-Collective identity header carries
 *                        location artwork and belongs to that
 *                        Collective's chrome.
 *
 * Three variants — enough for the whole set today without
 * introducing over-configuration.
 *
 *   title             — the heading text, always rendered in the
 *                        teal→white gradient.
 *   supportingCopy    — the white paragraph below the heading.
 *   accentLine        — the small teal→transparent line above the
 *                        heading. Defaults on; pass ``false`` to
 *                        omit if a page wants a starker feel later.
 *   children          — optional slot rendered inside the card,
 *                        below the supporting copy (for pages that
 *                        want to compose a small strip of content
 *                        inside the hero).
 *
 * The card sits inside a Container and a page-background band so
 * the hero has room to breathe both above and below. Consumers
 * don't need to wrap it themselves.
 */

interface Props {
  title: string
  supportingCopy?: ReactNode
  accentLine?: boolean
  children?: ReactNode
}

export default function PageHero({
  title,
  supportingCopy,
  accentLine = true,
  children,
}: Props) {
  return (
    <div className="py-8 sm:py-10" style={{ background: '#FDFCF9' }}>
      <Container>
        <div
          className="overflow-hidden rounded-2xl px-8 py-10 sm:px-10 sm:py-12"
          style={{
            background: '#071824',
            border: '1px solid rgba(56,160,158,0.22)',
            boxShadow:
              '0 0 0 1px rgba(56,160,158,0.08), 0 8px 32px rgba(7,24,36,0.18), 0 0 48px rgba(56,160,158,0.06)',
          }}
        >
          {accentLine && (
            <div
              className="mb-5 h-[2px] w-8 rounded-full"
              style={{
                background:
                  'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.2) 100%)',
              }}
              aria-hidden="true"
            />
          )}

          <h1
            className="mb-3 font-serif"
            style={{
              fontSize: 'clamp(2rem, 4vw, 3rem)',
              lineHeight: '1.1',
              letterSpacing: '-0.03em',
            }}
          >
            <span
              style={{
                display: 'inline-block',
                background: 'linear-gradient(90deg, #38A09E 0%, #FFFFFF 55%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              {title}
            </span>
          </h1>

          {supportingCopy && (
            <p
              className="max-w-[560px] text-[15px] leading-[1.78]"
              style={{ color: '#FFFFFF' }}
            >
              {supportingCopy}
            </p>
          )}

          {children && <div className="mt-6">{children}</div>}
        </div>
      </Container>
    </div>
  )
}
