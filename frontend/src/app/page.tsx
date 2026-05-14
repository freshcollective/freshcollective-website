import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import HomeHero from '@/components/home/HomeHero'

/* ─── Dual Intent ───────────────────────────────────────────────────────────── */

function DualIntent() {
  return (
    <section
      className="py-16 sm:py-24"
      style={{ background: '#FFFFFF' }}
    >
      <Container>

        {/* Copy block */}
        <div className="mb-12 sm:mb-14" style={{ maxWidth: '620px' }}>
          <p
            className="mb-7"
            style={{ fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', color: '#38A09E' }}
          >
            For learners and creators
          </p>
          <div className="mb-6">
            <p style={{ fontSize: 'clamp(1.5rem, 2.6vw, 2.125rem)', letterSpacing: '-0.04em', lineHeight: '1.46', fontWeight: 650, color: '#0F172A' }}>
              Some people come to explore new ways of{' '}
              <span style={{
                backgroundImage: 'linear-gradient(to right, #38A09E 0%, #55C4C2 100%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}>
                living, learning, and growing.
              </span>
            </p>
            <p className="mt-4" style={{ fontSize: 'clamp(1.5rem, 2.6vw, 2.125rem)', letterSpacing: '-0.04em', lineHeight: '1.46', fontWeight: 650, color: '#0F172A' }}>
              Others come to build spaces for{' '}
              <span style={{
                backgroundImage: 'linear-gradient(to right, #38A09E 0%, #55C4C2 100%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}>
                conversation, practice, creativity, and real change.
              </span>
            </p>
            <p className="mt-5" style={{ fontSize: 'clamp(0.9rem, 1.4vw, 1rem)', color: 'rgba(15,23,42,0.42)', letterSpacing: '-0.01em', lineHeight: '1.5' }}>
              Fresh Collective brings both together.
            </p>
          </div>
        </div>

        {/* Cards */}
        <div className="grid gap-5 sm:grid-cols-2 sm:gap-6">

          {/* CARD 1 — Learners */}
          <div
            className="flex flex-col rounded-2xl p-8 sm:p-10"
            style={{
              background: '#F4FBFA',
              border: '1px solid rgba(56,160,158,0.14)',
              boxShadow: '0 1px 2px rgba(0,0,0,0.05), 0 4px 8px rgba(0,0,0,0.04), 0 16px 48px rgba(0,0,0,0.09)',
            }}
          >
            {/* Icon */}
            <div
              className="mb-6 flex h-10 w-10 items-center justify-center rounded-xl"
              style={{ background: 'rgba(56,160,158,0.10)' }}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <circle cx="10" cy="7.5" r="3" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M4 16.5c0-2.761 2.686-5 6-5s6 2.239 6 5" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </div>

            <p style={{ fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: '#38A09E', marginBottom: '6px' }}>
              For learners
            </p>
            <h3 className="mb-3" style={{ fontSize: '1.25rem', fontWeight: 660, letterSpacing: '-0.03em', color: '#08101E', lineHeight: '1.2' }}>
              Collectives to join
            </h3>
            <p className="mb-6" style={{ fontSize: '15px', lineHeight: '1.78', color: 'rgba(15,23,42,0.62)' }}>
              Discover new ideas and ways of living, leading, and creating with others on the same path.
            </p>

            <div className="mb-6" style={{ height: '1px', background: 'rgba(15,23,42,0.07)' }} />

            <div className="mb-8 space-y-5">
              {[
                { num: '1', heading: 'Meaningful conversations', body: 'Engage in thoughtful dialogue and shared learning.' },
                { num: '2', heading: 'Practical tools and practices', body: 'Access resources and practices for real life.' },
              ].map(({ num, heading, body }) => (
                <div key={num} className="flex gap-4">
                  <div
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                    style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
                  >
                    {num}
                  </div>
                  <div>
                    <p style={{ fontSize: '13.5px', fontWeight: 630, color: '#08101E', letterSpacing: '-0.01em', marginBottom: '2px' }}>{heading}</p>
                    <p style={{ fontSize: '13px', color: 'rgba(15,23,42,0.56)', lineHeight: '1.6' }}>{body}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-auto">
              <Link
                href="/spaces"
                className="inline-flex items-center text-[14.5px] font-bold transition-opacity hover:opacity-70"
                style={{ color: '#38A09E' }}
              >
                Explore Collectives →
              </Link>
            </div>
          </div>

          {/* CARD 2 — Creators */}
          <div
            className="flex flex-col rounded-2xl p-8 sm:p-10"
            style={{
              background: '#FFFBF2',
              border: '1px solid rgba(212,176,72,0.18)',
              boxShadow: '0 1px 2px rgba(0,0,0,0.05), 0 4px 8px rgba(0,0,0,0.04), 0 16px 48px rgba(0,0,0,0.09)',
            }}
          >
            {/* Icon */}
            <div
              className="mb-6 flex h-10 w-10 items-center justify-center rounded-xl"
              style={{ background: 'rgba(212,176,72,0.12)' }}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <rect x="3" y="3" width="6" height="6" rx="1.5" stroke="#C4981A" strokeWidth="1.5" strokeLinejoin="round"/>
                <rect x="11" y="3" width="6" height="6" rx="1.5" stroke="#C4981A" strokeWidth="1.5" strokeLinejoin="round"/>
                <rect x="3" y="11" width="6" height="6" rx="1.5" stroke="#C4981A" strokeWidth="1.5" strokeLinejoin="round"/>
                <path d="M14 11.5v5M11.5 14h5" stroke="#C4981A" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </div>

            <p style={{ fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: '#B8891A', marginBottom: '6px' }}>
              For creators
            </p>
            <h3 className="mb-3" style={{ fontSize: '1.25rem', fontWeight: 660, letterSpacing: '-0.03em', color: '#08101E', lineHeight: '1.2' }}>
              Create your own collective
            </h3>
            <p className="mb-6" style={{ fontSize: '15px', lineHeight: '1.78', color: 'rgba(15,23,42,0.62)' }}>
              Spread your ideas with people who are craving a different way of living, leading, and exploring life.
            </p>

            <div className="mb-6" style={{ height: '1px', background: 'rgba(15,23,42,0.07)' }} />

            <div className="mb-8 space-y-5">
              {[
                { num: '1', heading: 'Build your space', body: 'Design your collective around your purpose and vision.' },
                { num: '2', heading: 'Gather and guide people', body: 'Bring the right people together around what matters.' },
              ].map(({ num, heading, body }) => (
                <div key={num} className="flex gap-4">
                  <div
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                    style={{ background: 'rgba(212,176,72,0.12)', color: '#B8891A' }}
                  >
                    {num}
                  </div>
                  <div>
                    <p style={{ fontSize: '13.5px', fontWeight: 630, color: '#08101E', letterSpacing: '-0.01em', marginBottom: '2px' }}>{heading}</p>
                    <p style={{ fontSize: '13px', color: 'rgba(15,23,42,0.56)', lineHeight: '1.6' }}>{body}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-auto">
              <Link
                href="/signup"
                className="inline-flex items-center text-[14.5px] font-bold transition-opacity hover:opacity-70"
                style={{ color: '#B8891A' }}
              >
                Build a Collective →
              </Link>
            </div>
          </div>

        </div>

      </Container>
    </section>
  )
}

/* ─── Ecosystem Features ─────────────────────────────────────────────────────── */

/* Shared chrome bar for all mockup panels */
function PanelChrome({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-2 px-4" style={{ height: '38px', background: '#EDEEF1', borderBottom: '1px solid rgba(0,0,0,0.08)' }}>
      <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#F87171' }} />
      <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#FBBF24' }} />
      <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#34D399' }} />
      <span style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(15,23,42,0.40)', marginLeft: '10px', letterSpacing: '0.01em' }}>{title}</span>
    </div>
  )
}

function EcosystemStatement() {
  return (
    <section className="py-20 sm:py-28" style={{ background: '#FAFAF8' }}>
      <Container>

        {/* Centred heading */}
        <div className="mx-auto mb-20 max-w-[640px] text-center">
          <p style={{ fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', color: '#38A09E', marginBottom: '16px' }}>
            Platform
          </p>
          <h2 style={{ fontSize: 'clamp(2rem, 4vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 660, color: '#0F172A', marginBottom: '16px' }}>
            Fresh Collective is an{' '}
            <span style={{
              backgroundImage: 'linear-gradient(to right, #38A09E 0%, #55C4C2 100%)',
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              color: 'transparent',
            }}>
              Eco-system.
            </span>
          </h2>
          <p style={{ fontSize: '16px', lineHeight: '1.78', color: 'rgba(15,23,42,0.58)' }}>
            A connected platform for guided collectives, practical pathways, live gatherings, and creator-led learning experiences.
          </p>
        </div>

        {/* Feature rows */}
        <div className="space-y-20 sm:space-y-28">

          {/* ROW 1 — Collectives: text left, visual right */}
          <div className="grid items-center gap-12 sm:grid-cols-[42%_58%] sm:gap-16">
            <div>
              <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: 'rgba(56,160,158,0.10)' }}>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <circle cx="7" cy="7" r="2.5" stroke="#38A09E" strokeWidth="1.5"/>
                  <circle cx="13" cy="7" r="2.5" stroke="#38A09E" strokeWidth="1.5"/>
                  <path d="M2 16c0-2.21 2.239-4 5-4s5 1.79 5 4" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
                  <path d="M13 12c1.5 0 5 .9 5 4" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              </div>
              <h3 style={{ fontSize: '1.375rem', fontWeight: 660, letterSpacing: '-0.03em', color: '#0F172A', lineHeight: '1.25', marginBottom: '12px' }}>
                Collectives to join
              </h3>
              <p style={{ fontSize: '15.5px', lineHeight: '1.80', color: 'rgba(15,23,42,0.60)' }}>
                Find guided learning communities built around real practice, shared conversation, and new ways of living, leading, creating, and growing.
              </p>
            </div>

            {/* Panel 1 — Collective browse */}
            <div style={{ borderRadius: '16px', overflow: 'hidden', border: '1px solid rgba(15,23,42,0.09)', boxShadow: '0 2px 4px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06), 0 24px 64px rgba(0,0,0,0.08)' }}>
              <PanelChrome title="Explore Collectives" />
              <div style={{ background: '#fff', padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {/* Hero collective card */}
                <div style={{ borderRadius: '10px', overflow: 'hidden', border: '1px solid rgba(15,23,42,0.07)' }}>
                  <div style={{ height: '64px', background: 'linear-gradient(135deg, #0D2B2B 0%, #1A4A4A 50%, #38A09E 100%)', position: 'relative', padding: '14px 16px', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
                    <div style={{ fontSize: '9px', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.55)', marginBottom: '3px' }}>Creator-led Collective</div>
                    <div style={{ fontSize: '14px', fontWeight: 660, color: '#fff', letterSpacing: '-0.02em' }}>Living Intentionally</div>
                  </div>
                  <div style={{ padding: '12px 16px', background: '#fff' }}>
                    <div style={{ fontSize: '12px', color: 'rgba(15,23,42,0.52)', lineHeight: '1.55', marginBottom: '10px' }}>Slow down, reflect, and build a life that actually fits.</div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(15,23,42,0.45)' }}>24 members</span>
                        <span style={{ width: '3px', height: '3px', borderRadius: '50%', background: 'rgba(15,23,42,0.20)', display: 'inline-block' }} />
                        <span style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(15,23,42,0.45)' }}>3 pathways</span>
                      </div>
                      <div className="flex items-center gap-1.5" style={{ background: 'rgba(56,160,158,0.08)', borderRadius: '999px', padding: '3px 8px' }}>
                        <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#38A09E' }} />
                        <span style={{ fontSize: '10px', fontWeight: 600, color: '#38A09E' }}>Live this week</span>
                      </div>
                    </div>
                  </div>
                </div>
                {/* Two smaller collective cards */}
                <div className="grid gap-2.5" style={{ gridTemplateColumns: '1fr 1fr' }}>
                  {[
                    { name: 'Deep Work Practice', count: '18', accent: '#38A09E' },
                    { name: 'Creative Leadership', count: '31', accent: '#C4981A' },
                  ].map(({ name, count, accent }) => (
                    <div key={name} style={{ borderRadius: '8px', border: '1px solid rgba(15,23,42,0.07)', padding: '12px', background: '#FAFAF8' }}>
                      <div style={{ width: '20px', height: '3px', borderRadius: '2px', background: accent, marginBottom: '8px', opacity: 0.7 }} />
                      <div style={{ fontSize: '11.5px', fontWeight: 640, color: '#0F172A', letterSpacing: '-0.01em', marginBottom: '4px', lineHeight: '1.3' }}>{name}</div>
                      <div style={{ fontSize: '10.5px', color: 'rgba(15,23,42,0.40)' }}>{count} members</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* ROW 2 — Pathways: visual left, text right */}
          <div className="grid items-center gap-12 sm:grid-cols-[58%_42%] sm:gap-16">

            {/* Panel 2 — Pathway progress */}
            <div className="order-2 sm:order-1" style={{ borderRadius: '16px', overflow: 'hidden', border: '1px solid rgba(15,23,42,0.09)', boxShadow: '0 2px 4px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06), 0 24px 64px rgba(0,0,0,0.08)' }}>
              <PanelChrome title="The REAL Journey" />
              <div style={{ background: '#fff', display: 'flex', minHeight: '280px' }}>
                {/* Left sidebar — step list */}
                <div style={{ width: '42%', borderRight: '1px solid rgba(15,23,42,0.07)', padding: '16px' }}>
                  <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(15,23,42,0.35)', marginBottom: '12px' }}>Phases</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {[
                      { label: 'Recognise', done: true, active: false },
                      { label: 'Explore', done: true, active: false },
                      { label: 'Align', done: false, active: true },
                      { label: 'Lead', done: false, active: false },
                    ].map(({ label, done, active }) => (
                      <div key={label} className="flex items-center gap-2.5" style={{ padding: '7px 8px', borderRadius: '6px', background: active ? 'rgba(56,160,158,0.08)' : 'transparent' }}>
                        <div style={{ width: '14px', height: '14px', borderRadius: '3px', flexShrink: 0, background: done ? '#38A09E' : active ? 'rgba(56,160,158,0.15)' : 'rgba(15,23,42,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          {done && <svg width="8" height="6" viewBox="0 0 8 6" fill="none"><path d="M1 3l2 2 4-4" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                        </div>
                        <span style={{ fontSize: '12px', color: done ? '#0F172A' : active ? '#38A09E' : 'rgba(15,23,42,0.38)', fontWeight: active ? 640 : done ? 540 : 400 }}>{label}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid rgba(15,23,42,0.07)' }}>
                    <div style={{ fontSize: '10px', color: 'rgba(15,23,42,0.40)', marginBottom: '6px' }}>Overall progress</div>
                    <div style={{ height: '4px', borderRadius: '2px', background: 'rgba(15,23,42,0.08)' }}>
                      <div style={{ width: '50%', height: '100%', borderRadius: '2px', background: 'linear-gradient(to right, #38A09E, #55C4C2)' }} />
                    </div>
                    <div style={{ fontSize: '10px', color: '#38A09E', fontWeight: 600, marginTop: '5px' }}>Phase 2 of 4</div>
                  </div>
                </div>
                {/* Right — lesson content */}
                <div style={{ flex: 1, padding: '16px' }}>
                  <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#38A09E', marginBottom: '6px' }}>Current · Align</div>
                  <div style={{ fontSize: '13.5px', fontWeight: 640, color: '#0F172A', letterSpacing: '-0.02em', marginBottom: '10px', lineHeight: '1.35' }}>What does alignment actually feel like for you?</div>
                  <div style={{ fontSize: '11.5px', color: 'rgba(15,23,42,0.52)', lineHeight: '1.62', marginBottom: '14px' }}>
                    Reflect on a moment when a decision felt completely right — not exciting, just settled. What was present?
                  </div>
                  <div style={{ borderRadius: '8px', padding: '10px 12px', background: '#F4FBFA', border: '1px solid rgba(56,160,158,0.14)', marginBottom: '12px' }}>
                    <div style={{ fontSize: '10px', fontWeight: 700, color: '#38A09E', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: '5px' }}>Reflection prompt</div>
                    <div style={{ fontSize: '11.5px', color: 'rgba(15,23,42,0.60)', lineHeight: '1.55', fontStyle: 'italic' }}>"What would I choose if I wasn't afraid of it being wrong?"</div>
                  </div>
                  <div style={{ height: '1px', background: 'rgba(15,23,42,0.06)', marginBottom: '10px' }} />
                  <div style={{ fontSize: '11px', color: 'rgba(15,23,42,0.38)' }}>3 lessons · 1 reflection · Est. 20 min</div>
                </div>
              </div>
            </div>

            <div className="order-1 sm:order-2">
              <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: 'rgba(56,160,158,0.10)' }}>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <path d="M4 10h12M10 4l6 6-6 6" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <h3 style={{ fontSize: '1.375rem', fontWeight: 660, letterSpacing: '-0.03em', color: '#0F172A', lineHeight: '1.25', marginBottom: '12px' }}>
                Pathways that turn ideas into practice
              </h3>
              <p style={{ fontSize: '15.5px', lineHeight: '1.80', color: 'rgba(15,23,42,0.60)' }}>
                Move through structured learning journeys with lessons, reflections, tools, and gentle progress that helps ideas land in real life.
              </p>
            </div>
          </div>

          {/* ROW 3 — Gatherings: text left, visual right */}
          <div className="grid items-center gap-12 sm:grid-cols-[42%_58%] sm:gap-16">
            <div>
              <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: 'rgba(56,160,158,0.10)' }}>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <rect x="3" y="4" width="14" height="13" rx="2" stroke="#38A09E" strokeWidth="1.5"/>
                  <path d="M3 8h14M7 2v3M13 2v3" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              </div>
              <h3 style={{ fontSize: '1.375rem', fontWeight: 660, letterSpacing: '-0.03em', color: '#0F172A', lineHeight: '1.25', marginBottom: '12px' }}>
                Live gatherings and community rhythm
              </h3>
              <p style={{ fontSize: '15.5px', lineHeight: '1.80', color: 'rgba(15,23,42,0.60)' }}>
                Join conversations, prompts, and live sessions that create connection, accountability, and shared momentum.
              </p>
            </div>

            {/* Panel 3 — Gatherings & community */}
            <div style={{ borderRadius: '16px', overflow: 'hidden', border: '1px solid rgba(15,23,42,0.09)', boxShadow: '0 2px 4px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06), 0 24px 64px rgba(0,0,0,0.08)' }}>
              <PanelChrome title="Community" />
              <div style={{ background: '#fff', padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {/* Event card */}
                <div style={{ borderRadius: '10px', border: '1px solid rgba(56,160,158,0.18)', padding: '14px 16px', background: '#F4FBFA' }}>
                  <div className="flex items-start justify-between">
                    <div>
                      <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#38A09E', marginBottom: '4px' }}>Live Gathering</div>
                      <div style={{ fontSize: '14px', fontWeight: 650, color: '#0F172A', letterSpacing: '-0.02em', marginBottom: '2px' }}>Monthly open call</div>
                      <div style={{ fontSize: '11px', color: 'rgba(15,23,42,0.50)' }}>60 min · structured · led</div>
                    </div>
                    <div style={{ borderRadius: '8px', padding: '6px 10px', background: '#38A09E', textAlign: 'center', flexShrink: 0 }}>
                      <div style={{ fontSize: '16px', fontWeight: 700, color: '#fff', lineHeight: 1 }}>14</div>
                      <div style={{ fontSize: '9px', fontWeight: 600, color: 'rgba(255,255,255,0.75)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>May</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 mt-3">
                    {[1,2,3,4].map(i => (
                      <div key={i} style={{ width: '22px', height: '22px', borderRadius: '50%', background: `rgba(56,160,158,${0.18 + i*0.07})`, border: '2px solid #fff', marginLeft: i > 1 ? '-6px' : 0 }} />
                    ))}
                    <span style={{ fontSize: '11px', color: 'rgba(15,23,42,0.45)', marginLeft: '8px' }}>+21 attending</span>
                  </div>
                </div>
                {/* Community prompt thread */}
                <div style={{ borderRadius: '10px', border: '1px solid rgba(15,23,42,0.07)', padding: '14px 16px', background: '#FAFAF8' }}>
                  <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.13em', textTransform: 'uppercase', color: 'rgba(15,23,42,0.38)', marginBottom: '8px' }}>This week's prompt</div>
                  <div style={{ fontSize: '13px', color: '#0F172A', fontWeight: 540, lineHeight: '1.58', marginBottom: '10px', fontStyle: 'italic' }}>
                    "What would you do if you stopped waiting to feel ready?"
                  </div>
                  <div style={{ height: '1px', background: 'rgba(15,23,42,0.06)', marginBottom: '10px' }} />
                  {[
                    { initials: 'SR', text: "I'd finally start the project I've been putting off for two years.", color: '#38A09E' },
                    { initials: 'MK', text: "Honestly — I'd have that conversation I keep avoiding.", color: '#C4981A' },
                  ].map(({ initials, text, color }) => (
                    <div key={initials} className="flex items-start gap-2.5 mb-2 last:mb-0">
                      <div style={{ width: '22px', height: '22px', borderRadius: '50%', background: `${color}22`, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <span style={{ fontSize: '8.5px', fontWeight: 700, color }}>{initials}</span>
                      </div>
                      <div style={{ fontSize: '11.5px', color: 'rgba(15,23,42,0.58)', lineHeight: '1.55', paddingTop: '2px' }}>{text}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* ROW 4 — Creator tools: visual left, text right */}
          <div className="grid items-center gap-12 sm:grid-cols-[58%_42%] sm:gap-16">

            {/* Panel 4 — Creator workspace */}
            <div style={{ borderRadius: '16px', overflow: 'hidden', border: '1px solid rgba(15,23,42,0.09)', boxShadow: '0 2px 4px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06), 0 24px 64px rgba(0,0,0,0.08)' }}>
              <PanelChrome title="Creator Workspace" />
              <div style={{ background: '#fff', display: 'flex', minHeight: '280px' }}>
                {/* Sidebar nav */}
                <div style={{ width: '38%', borderRight: '1px solid rgba(15,23,42,0.07)', padding: '16px', background: '#FAFAF8' }}>
                  <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(15,23,42,0.35)', marginBottom: '10px' }}>My Collective</div>
                  {[
                    { label: 'Pathways', active: true },
                    { label: 'Events', active: false },
                    { label: 'Community', active: false },
                    { label: 'Resources', active: false },
                  ].map(({ label, active }) => (
                    <div key={label} style={{ padding: '7px 10px', borderRadius: '6px', marginBottom: '2px', background: active ? 'rgba(212,176,72,0.10)' : 'transparent', cursor: 'default' }}>
                      <span style={{ fontSize: '12px', color: active ? '#B8891A' : 'rgba(15,23,42,0.48)', fontWeight: active ? 640 : 400 }}>{label}</span>
                    </div>
                  ))}
                  <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid rgba(15,23,42,0.07)' }}>
                    <div style={{ fontSize: '10px', color: 'rgba(15,23,42,0.38)', marginBottom: '4px' }}>Members</div>
                    <div style={{ fontSize: '18px', fontWeight: 660, color: '#0F172A', letterSpacing: '-0.03em' }}>34</div>
                    <div style={{ fontSize: '10px', color: '#38A09E', fontWeight: 600 }}>+3 this week</div>
                  </div>
                </div>
                {/* Main panel — pathway list */}
                <div style={{ flex: 1, padding: '16px' }}>
                  <div className="flex items-center justify-between mb-3">
                    <div style={{ fontSize: '12px', fontWeight: 640, color: '#0F172A', letterSpacing: '-0.01em' }}>Active Pathways</div>
                    <div style={{ fontSize: '10px', fontWeight: 700, color: '#B8891A', letterSpacing: '0.05em', cursor: 'default' }}>+ New</div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {[
                      { name: 'The REAL Journey', steps: '4 phases', status: 'Published', dot: '#38A09E' },
                      { name: 'Deep Work Essentials', steps: '6 lessons', status: 'Published', dot: '#38A09E' },
                      { name: 'Creative Practice', steps: '5 lessons', status: 'Draft', dot: '#C4981A' },
                    ].map(({ name, steps, status, dot }) => (
                      <div key={name} className="flex items-center justify-between" style={{ borderRadius: '7px', padding: '9px 11px', background: '#F8F8F6', border: '1px solid rgba(15,23,42,0.06)' }}>
                        <div>
                          <div style={{ fontSize: '12px', fontWeight: 580, color: '#0F172A', marginBottom: '2px' }}>{name}</div>
                          <div style={{ fontSize: '10.5px', color: 'rgba(15,23,42,0.40)' }}>{steps}</div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: dot }} />
                          <span style={{ fontSize: '10.5px', color: 'rgba(15,23,42,0.50)', fontWeight: 500 }}>{status}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid rgba(15,23,42,0.06)' }}>
                    <div style={{ fontSize: '10.5px', color: '#B8891A', fontWeight: 600 }}>2 upcoming events · Next: May 18</div>
                  </div>
                </div>
              </div>
            </div>

            <div>
              <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: 'rgba(212,176,72,0.12)' }}>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <rect x="3" y="3" width="6" height="6" rx="1.5" stroke="#C4981A" strokeWidth="1.5" strokeLinejoin="round"/>
                  <rect x="11" y="3" width="6" height="6" rx="1.5" stroke="#C4981A" strokeWidth="1.5" strokeLinejoin="round"/>
                  <rect x="3" y="11" width="6" height="6" rx="1.5" stroke="#C4981A" strokeWidth="1.5" strokeLinejoin="round"/>
                  <path d="M14 11.5v5M11.5 14h5" stroke="#C4981A" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              </div>
              <h3 style={{ fontSize: '1.375rem', fontWeight: 660, letterSpacing: '-0.03em', color: '#0F172A', lineHeight: '1.25', marginBottom: '12px' }}>
                Tools for creators
              </h3>
              <p style={{ fontSize: '15.5px', lineHeight: '1.80', color: 'rgba(15,23,42,0.60)' }}>
                Build your own collective with pathways, events, posts, resources, and the structure to guide people through meaningful change.
              </p>
            </div>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Fresh Ideas (dark card) ───────────────────────────────────────────────── */

function FreshIdeas() {
  return (
    <section className="py-12 sm:py-20" style={{ background: '#FAFAF8' }}>
      <Container>
        {/* Wrapper — lg:pt-20 reserves space above the dark card for floating card row */}
        <div className="relative lg:pt-20">

          {/* ── Dark card ──────────────────────────────────────────────────── */}
          <div
            className="relative overflow-hidden"
            style={{
              borderRadius: '24px',
              background: '#071824',
              border: '1px solid rgba(255,255,255,0.07)',
              boxShadow: '0 48px 120px rgba(0,0,0,0.30), 0 16px 40px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.12)',
            }}
          >
            {/* Teal radial glow — top right */}
            <div
              className="pointer-events-none absolute inset-0"
              aria-hidden="true"
              style={{
                background: 'radial-gradient(ellipse 80% 60% at 90% -5%, rgba(56,160,158,0.22) 0%, transparent 65%)',
              }}
            />
            {/* Subtle secondary glow — bottom left */}
            <div
              className="pointer-events-none absolute inset-0"
              aria-hidden="true"
              style={{
                background: 'radial-gradient(ellipse 50% 55% at -5% 105%, rgba(56,160,158,0.09) 0%, transparent 60%)',
              }}
            />

            <div style={{ padding: 'clamp(2.5rem, 5vw, 4rem)' }}>

              {/* Eyebrow */}
              <div className="mb-8 flex items-center gap-3">
                <div style={{ height: '1px', width: '2rem', flexShrink: 0, background: 'rgba(85,184,182,0.55)' }} />
                <span style={{ fontSize: '12px', fontWeight: 600, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.68)' }}>
                  A different kind of space
                </span>
              </div>

              {/* Heading */}
              <h2
                style={{
                  fontSize: 'clamp(2.5rem, 4.5vw, 4.25rem)',
                  letterSpacing: '-0.04em',
                  lineHeight: '1.05',
                  fontWeight: 660,
                  marginBottom: '1.75rem',
                  maxWidth: '640px',
                }}
              >
                <span style={{ color: '#FFFFFF' }}>Fresh ideas need</span>
                <br />
                <span
                  style={{
                    backgroundImage: 'linear-gradient(90deg, #42C7C6 0%, #7FDAD9 35%, #D8F5F2 65%, #FFFFFF 90%)',
                    WebkitBackgroundClip: 'text',
                    backgroundClip: 'text',
                    color: 'transparent',
                  }}
                >
                  spaces to grow.
                </span>
              </h2>

              {/* Body */}
              <div style={{ maxWidth: '520px', marginBottom: '3.5rem' }}>
                <p
                  style={{
                    fontSize: 'clamp(0.9375rem, 1.4vw, 1.0625rem)',
                    lineHeight: '1.82',
                    color: 'rgba(255,255,255,0.52)',
                    marginBottom: '1.125rem',
                  }}
                >
                  Fresh Collective is built for ideas that are ready to move beyond content and become lived experience.
                </p>
                <p
                  style={{
                    fontSize: 'clamp(0.9375rem, 1.4vw, 1.0625rem)',
                    lineHeight: '1.82',
                    color: 'rgba(255,255,255,0.38)',
                  }}
                >
                  Not passive courses. Not scattered communities. A connected ecosystem where learning has somewhere to land, deepen, and grow.
                </p>
              </div>

              {/* Supporting points */}
              <div
                className="grid gap-8 sm:grid-cols-3"
                style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '2.5rem' }}
              >
                {[
                  { num: '01', title: 'Educators and practitioners', body: 'Creating the conditions their work needs.' },
                  { num: '02', title: 'People ready to live differently', body: 'Finding structures that turn ideas into genuine change.' },
                  { num: '03', title: 'Ideas that need room to develop', body: 'Given depth, community, and the right conditions to take root.' },
                ].map(({ num, title, body }) => (
                  <div key={num}>
                    <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.20em', textTransform: 'uppercase' as const, color: 'rgba(85,184,182,0.55)', marginBottom: '0.75rem' }}>
                      {num}
                    </div>
                    <div style={{ fontSize: '13.5px', fontWeight: 620, letterSpacing: '-0.02em', color: 'rgba(255,255,255,0.80)', lineHeight: '1.4', marginBottom: '0.5rem' }}>
                      {title}
                    </div>
                    <div style={{ fontSize: '13px', lineHeight: '1.68', color: 'rgba(255,255,255,0.36)' }}>
                      {body}
                    </div>
                  </div>
                ))}
              </div>

            </div>
          </div>

          {/* ── Floating cards — horizontal row, lg+ only ─────────────────── */}
          <div
            className="absolute hidden lg:flex"
            style={{ top: '16px', right: '0', gap: '15px' }}
          >

            {/* Card 1: Question prompt */}
            <div
              className="rounded-2xl bg-white
                border border-[rgba(15,23,42,0.09)]
                shadow-[0_8px_28px_rgba(0,0,0,0.10)]
                transition-all duration-[210ms] ease-out cursor-default
                hover:-translate-y-[5px] hover:bg-[#EFF9F9]
                hover:border-[rgba(66,199,198,0.44)]
                hover:shadow-[0_18px_50px_rgba(0,0,0,0.16)]"
              style={{ width: '210px', minHeight: '112px', padding: '18px 20px', flexShrink: 0 }}
            >
              <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase' as const, color: '#38A09E', marginBottom: '10px' }}>
                Question prompt
              </div>
              <div style={{ fontSize: '13px', fontWeight: 500, lineHeight: '1.58', letterSpacing: '-0.01em', color: '#0F172A' }}>
                &ldquo;What are you actually saying yes to?&rdquo;
              </div>
            </div>

            {/* Card 2: Live call */}
            <div
              className="rounded-2xl bg-white
                border border-[rgba(15,23,42,0.09)]
                shadow-[0_8px_28px_rgba(0,0,0,0.10)]
                transition-all duration-[210ms] ease-out cursor-default
                hover:-translate-y-[5px] hover:bg-[#EFF9F9]
                hover:border-[rgba(66,199,198,0.44)]
                hover:shadow-[0_18px_50px_rgba(0,0,0,0.16)]"
              style={{ width: '210px', minHeight: '112px', padding: '18px 20px', flexShrink: 0 }}
            >
              <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase' as const, color: '#38A09E', marginBottom: '10px' }}>
                Live call
              </div>
              <div style={{ fontSize: '14.5px', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: '1.3', color: '#0F172A', marginBottom: '4px' }}>
                Monthly gathering
              </div>
              <div style={{ fontSize: '12px', color: 'rgba(15,23,42,0.40)', letterSpacing: '-0.01em' }}>
                7:30pm
              </div>
            </div>

            {/* Card 3: Practice note */}
            <div
              className="rounded-2xl bg-[#F4FAFA]
                border border-[rgba(56,160,158,0.22)]
                shadow-[0_8px_24px_rgba(0,0,0,0.08)]
                transition-all duration-[210ms] ease-out cursor-default
                hover:-translate-y-[5px] hover:bg-[#EAF6F6]
                hover:border-[rgba(66,199,198,0.44)]
                hover:shadow-[0_18px_48px_rgba(0,0,0,0.13)]"
              style={{ width: '210px', minHeight: '112px', padding: '18px 20px', flexShrink: 0 }}
            >
              <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase' as const, color: '#38A09E', marginBottom: '10px' }}>
                Practice note
              </div>
              <div style={{ fontSize: '13px', fontWeight: 500, lineHeight: '1.58', letterSpacing: '-0.01em', color: '#0F172A' }}>
                One small experiment this week
              </div>
            </div>

          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── The Way We Feel ───────────────────────────────────────────────────────── */

function TheWayWeFeelSection() {
  return (
    <section className="py-16 sm:py-24" style={{ background: '#FAFAF8' }}>
      <Container>

        <div className="mb-12 max-w-[560px]">
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.75vw, 3.25rem)', letterSpacing: '-0.04em', lineHeight: '1.08', fontWeight: 650 }}
          >
            The way we feel changes<br />
            <span style={{ color: 'rgba(12,24,38,0.30)' }}>what becomes possible.</span>
          </h2>
        </div>

        <div className="grid gap-10 sm:grid-cols-3">
          {[
            {
              rule: 'A more settled mind.',
              body: 'When you have a framework for where you are and where you are headed, the noise quiets. Clarity is not a luxury — it is the starting point.',
              accent: 'rgba(56,160,158,0.70)',
            },
            {
              rule: 'In it with others, honestly.',
              body: 'Not a curated highlight reel. Real people moving through real phases — with enough structure that the conversations go somewhere.',
              accent: 'rgba(212,176,72,0.70)',
              offset: true,
            },
            {
              rule: 'A thread back to yourself.',
              body: 'When life is full and loud, the REAL Journey gives you something to return to — a stable, consistent thread through all of it.',
              accent: 'rgba(45,77,115,0.60)',
            },
          ].map(({ rule, body, accent, offset }) => (
            <div key={rule} className={offset ? 'sm:pt-10' : ''}>
              <div className="mb-5 h-px w-6" style={{ background: accent }} />
              <p className="mb-3 text-navy-950" style={{ fontSize: '15.5px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                {rule}
              </p>
              <p className="text-[15px] leading-[1.82] text-navy-500">{body}</p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── Where the Learning Lives ──────────────────────────────────────────────── */

function WhereTheLearningLives() {
  return (
    <section className="py-16 sm:py-24" style={{ background: '#F5F0E8' }}>
      <Container>

        <div className="mb-10">
          <div className="mb-3 flex items-center gap-3">
            <div className="h-px w-8 bg-teal-500" style={{ opacity: 0.5 }} />
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-teal-600">
              The structure
            </span>
          </div>
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.75rem, 3.25vw, 2.75rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 650 }}
          >
            Where the learning lives.
          </h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">

          <div
            className="rounded-2xl p-7 sm:col-span-2 lg:col-span-1 lg:row-span-2"
            style={{
              background: '#ffffff',
              border: '1px solid rgba(0,0,0,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
            }}
          >
            <div
              className="mb-4 select-none"
              style={{ fontSize: '5.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: 'rgba(56,160,158,0.12)' }}
              aria-hidden="true"
            >
              01
            </div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-teal-600">
              Start Here
            </p>
            <h3 className="mb-4 text-navy-950" style={{ fontSize: '1.25rem', fontWeight: 650, letterSpacing: '-0.03em', lineHeight: '1.25' }}>
              REAL Journey
            </h3>
            <p className="mb-6 text-[15px] leading-[1.82] text-navy-500">
              Four phases — Recognise, Explore, Align, Lead. The foundation every member
              begins with. Bite-sized. Stabilising. Something to return to, again and again.
            </p>
            <Link href="/real-journey" className="text-[13.5px] font-semibold text-teal-600 underline-offset-2 transition-opacity hover:opacity-70 hover:underline">
              Learn more →
            </Link>
          </div>

          <div
            className="rounded-2xl p-7"
            style={{
              background: '#ffffff',
              border: '1px solid rgba(0,0,0,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
            }}
          >
            <div
              className="mb-4 select-none"
              style={{ fontSize: '5.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: 'rgba(212,176,72,0.15)' }}
              aria-hidden="true"
            >
              02
            </div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: '#9A7420' }}>
              The Heart
            </p>
            <h3 className="mb-3 text-navy-950" style={{ fontSize: '1.125rem', fontWeight: 650, letterSpacing: '-0.03em', lineHeight: '1.25' }}>
              Live Layer
            </h3>
            <p className="mb-5 text-[15px] leading-[1.82] text-navy-500">
              Monthly live calls. Community prompts. Integration threads.
              The place where the membership comes alive.
            </p>
            <Link href="/membership" className="text-[13.5px] font-semibold underline-offset-2 transition-opacity hover:opacity-70 hover:underline" style={{ color: '#9A7420' }}>
              Explore Membership →
            </Link>
          </div>

          <div
            className="rounded-2xl p-7"
            style={{
              background: '#ffffff',
              border: '1px solid rgba(0,0,0,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05)',
            }}
          >
            <div
              className="mb-4 select-none"
              style={{ fontSize: '5.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: 'rgba(30,51,84,0.10)' }}
              aria-hidden="true"
            >
              03
            </div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-navy-400">
              The Rooms
            </p>
            <h3 className="mb-3 text-navy-950" style={{ fontSize: '1.125rem', fontWeight: 650, letterSpacing: '-0.03em', lineHeight: '1.25' }}>
              Deepening Pathways
            </h3>
            <p className="mb-5 text-[15px] leading-[1.82] text-navy-500">
              Growth, Transformation, Essence. Once you have your foundation,
              the pathways take you deeper — at your own pace.
            </p>
            <Link href="/membership" className="text-[13.5px] font-semibold text-navy-500 underline-offset-2 transition-opacity hover:opacity-70 hover:underline">
              Explore Membership →
            </Link>
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Conditions ────────────────────────────────────────────────────────────── */

function Conditions() {
  return (
    <section
      className="py-16 sm:py-24"
      style={{ background: '#F5F4F0', borderTop: '1px solid rgba(0,0,0,0.04)' }}
    >
      <Container>

        <div className="mb-12 max-w-[560px]">
          <h2
            className="text-navy-950"
            style={{ fontSize: 'clamp(1.875rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.08', fontWeight: 650 }}
          >
            The conditions matter<br />
            <span style={{ color: 'rgba(12,24,38,0.28)', fontStyle: 'italic' }}>
              as much as the content.
            </span>
          </h2>
        </div>

        <div className="grid gap-10 sm:grid-cols-3">
          {[
            {
              num: '01',
              heading: 'A pace that does not break you.',
              body: 'Everything inside Fresh Collective is designed to be returned to — not raced through. There is no urgency here. The structure holds.',
              numColor: 'rgba(56,160,158,0.25)',
            },
            {
              num: '02',
              heading: 'People building the same things.',
              body: 'You are not dropped into a general community. You are alongside people working through the same phases, the same questions, the same moments.',
              numColor: 'rgba(212,176,72,0.30)',
              offset: true,
            },
            {
              num: '03',
              heading: 'A leader who has been there.',
              body: 'Fresh Collective was built from the inside out — by someone who has moved through these phases herself, not just observed them.',
              numColor: 'rgba(30,51,84,0.20)',
            },
          ].map(({ num, heading, body, numColor, offset }) => (
            <div key={num} className={offset ? 'sm:pt-10' : ''}>
              <div
                className="mb-5 select-none"
                style={{ fontSize: '4.5rem', fontWeight: 650, lineHeight: '1', letterSpacing: '-0.06em', color: numColor }}
                aria-hidden="true"
              >
                {num}
              </div>
              <p className="mb-3 text-navy-950" style={{ fontSize: '15.5px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                {heading}
              </p>
              <p className="text-[15px] leading-[1.82] text-navy-500">{body}</p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── Good Questions ────────────────────────────────────────────────────────── */

function GoodQuestions() {
  const qa = [
    {
      q: 'What if I am already overwhelmed?',
      a: 'That is exactly the right time to start. The REAL Journey is designed for people who are already full — structured to be light enough to actually do, even when everything else is heavy.',
    },
    {
      q: 'Is this another online course I will not finish?',
      a: 'Fresh Collective is not built around consumption. It is built around consistency — short touchpoints, a live layer, and a community that keeps you moving even when motivation is low.',
    },
    {
      q: 'What is the difference between the REAL Journey and full membership?',
      a: 'The REAL Journey is the foundation — four phases, your own pace. Full membership adds the live layer and access to The Rooms. Both are meaningful starting points.',
    },
    {
      q: 'How much time do I need each week?',
      a: 'The REAL Journey is designed around bite-sized sessions. The monthly live call is 60 minutes. Most members find 30–60 minutes a week is enough to stay connected and moving.',
    },
  ]

  return (
    <section className="py-16 sm:py-24" style={{ background: '#FDFCF9' }}>
      <Container>
        <div className="grid gap-12 sm:grid-cols-[38%_62%] sm:gap-16">

          <div>
            <h2
              className="text-navy-950"
              style={{ fontSize: 'clamp(1.5rem, 2.5vw, 2.125rem)', letterSpacing: '-0.04em', lineHeight: '1.14', fontWeight: 650 }}
            >
              Good questions deserve honest answers.
            </h2>
          </div>

          <div>
            {qa.map(({ q, a }, i) => (
              <div
                key={q}
                className="py-6"
                style={{ borderTop: i === 0 ? 'none' : '1px solid rgba(0,0,0,0.05)' }}
              >
                <p className="mb-2.5 text-navy-950" style={{ fontSize: '15.5px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                  {q}
                </p>
                <p className="text-[15px] leading-[1.82] text-navy-500">{a}</p>
              </div>
            ))}
          </div>

        </div>
      </Container>
    </section>
  )
}

/* ─── Final CTA ─────────────────────────────────────────────────────────────── */

function FinalCTA() {
  return (
    <section
      className="relative overflow-hidden py-24 sm:py-32"
      style={{ background: '#060C17' }}
    >
      {/* Teal glow from below */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(ellipse 80% 55% at 50% 110%, rgba(56,160,158,0.14) 0%, transparent 65%)',
        }}
      />

      <Container className="relative">
        <div className="mx-auto max-w-[520px] text-center">

          <div className="mx-auto mb-10 h-px w-10" style={{ background: 'rgba(212,176,72,0.35)' }} />

          <h2
            className="mb-6"
            style={{
              fontSize: 'clamp(2.25rem, 4.5vw, 4rem)',
              letterSpacing: '-0.04em',
              lineHeight: '1.07',
              fontWeight: 650,
              color: '#ffffff',
            }}
          >
            Find your collective.
            <br />
            <span
              style={{
                background: 'linear-gradient(108deg, #7FCFCD 0%, #D4B048 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Or build one.
            </span>
          </h2>

          <p
            className="mb-10 text-[15.5px] leading-[1.82]"
            style={{ color: 'rgba(255,255,255,0.58)' }}
          >
            There&apos;s a collective for where you are now.
            Or build the one that doesn&apos;t exist yet.
          </p>

          <div className="flex flex-col items-center gap-4">
            <Link
              href="/spaces"
              className="inline-flex items-center rounded-xl px-9 py-4 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
              }}
            >
              Explore Collectives
            </Link>
            <Link
              href="/signup"
              className="text-[13.5px] font-medium transition-opacity hover:opacity-80"
              style={{ color: 'rgba(255,255,255,0.48)' }}
            >
              or Build a Collective →
            </Link>
          </div>

          <div className="mx-auto mt-10 h-px w-10" style={{ background: 'rgba(212,176,72,0.35)' }} />

        </div>
      </Container>
    </section>
  )
}

/* ─── Page ──────────────────────────────────────────────────────────────────── */

export default function Home() {
  return (
    <SiteShell heroHeader>
      <HomeHero />
      <DualIntent />
      <EcosystemStatement />
      <FreshIdeas />
      <TheWayWeFeelSection />
      <WhereTheLearningLives />
      <Conditions />
      <GoodQuestions />
      <FinalCTA />
    </SiteShell>
  )
}
