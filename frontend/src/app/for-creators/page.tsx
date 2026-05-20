import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'

export default function ForCreatorsPage() {
  return (
    <SiteShell>
      <div
        className="flex min-h-[calc(100vh-4rem)] items-center py-16 sm:py-24"
        style={{ background: '#FFFFFF' }}
      >
        <Container>
          <div className="mx-auto max-w-[640px]">

            {/* Main navy card */}
            <div
              className="relative overflow-hidden rounded-2xl"
              style={{
                background: '#071824',
                border: '1px solid rgba(56,160,158,0.20)',
                boxShadow:
                  '0 0 0 1px rgba(56,160,158,0.06), 0 8px 40px rgba(7,24,36,0.22), 0 0 60px rgba(56,160,158,0.05)',
                padding: 'clamp(2.5rem, 6vw, 4rem) clamp(2rem, 6vw, 3.5rem)',
              }}
            >
              {/* Teal radial glow */}
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0"
                style={{
                  background:
                    'radial-gradient(ellipse 70% 50% at 60% -5%, rgba(56,160,158,0.22) 0%, transparent 65%)',
                }}
              />

              <div className="relative z-10">

                {/* Eyebrow */}
                <div className="mb-6 flex items-center gap-3">
                  <div
                    className="h-[2px] w-6 shrink-0 rounded-full"
                    style={{ background: 'rgba(143,227,226,0.45)' }}
                  />
                  <span
                    className="text-[10.5px] font-semibold uppercase tracking-[0.20em]"
                    style={{ color: 'rgba(255,255,255,0.38)' }}
                  >
                    For Creators
                  </span>
                </div>

                {/* Heading */}
                <h1
                  className="mb-5 font-serif"
                  style={{
                    fontSize: 'clamp(2rem, 5vw, 3.25rem)',
                    lineHeight: '1.08',
                    letterSpacing: '-0.03em',
                  }}
                >
                  <span style={{ color: '#ffffff' }}>Build the collective</span>
                  <br />
                  <span
                    style={{
                      backgroundImage:
                        'linear-gradient(90deg, #38A09E 0%, #FFFFFF 60%)',
                      WebkitBackgroundClip: 'text',
                      backgroundClip: 'text',
                      WebkitTextFillColor: 'transparent',
                      color: 'transparent',
                    }}
                  >
                    you want to see.
                  </span>
                </h1>

                {/* Supporting copy */}
                <p
                  className="mb-8"
                  style={{
                    fontSize: 'clamp(0.9375rem, 1.4vw, 1.0625rem)',
                    lineHeight: '1.80',
                    color: 'rgba(255,255,255,0.52)',
                    maxWidth: '440px',
                    letterSpacing: '-0.01em',
                  }}
                >
                  Create a creator-led learning space with pathways, gatherings,
                  resources, and community in one intentional place.
                </p>

                {/* Pricing card */}
                <div
                  className="mb-8"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(66,199,198,0.16)',
                    borderRadius: '14px',
                    padding: '20px 24px',
                  }}
                >
                  <p
                    style={{
                      fontSize: '10.5px',
                      fontWeight: 700,
                      letterSpacing: '0.18em',
                      textTransform: 'uppercase',
                      color: '#7FDAD9',
                      marginBottom: '10px',
                    }}
                  >
                    Founding creator access
                  </p>
                  <p
                    style={{
                      fontSize: 'clamp(1.375rem, 3vw, 1.75rem)',
                      fontWeight: 660,
                      letterSpacing: '-0.03em',
                      color: '#ffffff',
                      lineHeight: 1.1,
                      marginBottom: '6px',
                    }}
                  >
                    14-day free trial
                  </p>
                  <p
                    style={{
                      fontSize: '17px',
                      fontWeight: 400,
                      color: 'rgba(255,255,255,0.55)',
                      letterSpacing: '-0.01em',
                      marginBottom: '8px',
                    }}
                  >
                    then{' '}
                    <span style={{ fontWeight: 600, color: 'rgba(255,255,255,0.80)' }}>
                      $19/month
                    </span>
                  </p>
                  <p
                    style={{
                      fontSize: '13px',
                      color: 'rgba(255,255,255,0.38)',
                      letterSpacing: '-0.01em',
                    }}
                  >
                    8% Fresh Collective transaction fee
                  </p>
                  <p
                    className="mt-3"
                    style={{
                      fontSize: '12px',
                      color: 'rgba(255,255,255,0.30)',
                      letterSpacing: '-0.01em',
                      lineHeight: 1.6,
                    }}
                  >
                    Upgrade options and reduced transaction fees will be available as you grow.
                  </p>
                </div>

                {/* CTAs */}
                {/* TODO: Replace /signup with dedicated creator onboarding route once it exists */}
                <div className="flex flex-wrap items-center gap-3">
                  <Link
                    href="/signup"
                    className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
                    style={{
                      background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                      boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
                    }}
                  >
                    Start building
                  </Link>
                  <Link
                    href="/spaces"
                    className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold transition-all hover:-translate-y-px"
                    style={{
                      background: 'rgba(255,255,255,0.07)',
                      border: '1px solid rgba(255,255,255,0.14)',
                      color: 'rgba(255,255,255,0.75)',
                      backdropFilter: 'blur(8px)',
                    }}
                  >
                    Explore collectives
                  </Link>
                </div>

              </div>
            </div>

          </div>
        </Container>
      </div>
    </SiteShell>
  )
}
