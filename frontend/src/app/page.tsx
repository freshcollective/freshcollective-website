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
          {/* Secondary glow — bottom left */}
          <div
            className="pointer-events-none absolute inset-0"
            aria-hidden="true"
            style={{
              background: 'radial-gradient(ellipse 50% 55% at -5% 105%, rgba(56,160,158,0.09) 0%, transparent 60%)',
            }}
          />

          <div style={{ padding: 'clamp(3rem, 5.5vw, 5rem)' }}>

            {/* Eyebrow */}
            <div className="mb-10 flex items-center gap-3">
              <div style={{ height: '1px', width: '2rem', flexShrink: 0, background: 'rgba(85,184,182,0.60)' }} />
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
                marginBottom: '2.25rem',
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
            <div style={{ maxWidth: '560px' }}>
              <p
                style={{
                  fontSize: 'clamp(1rem, 1.5vw, 1.125rem)',
                  lineHeight: '1.85',
                  color: 'rgba(255,255,255,0.88)',
                  marginBottom: '1.25rem',
                  letterSpacing: '-0.01em',
                }}
              >
                Fresh Collective is built for ideas that are ready to move beyond content and become lived experience.
              </p>
              <p
                style={{
                  fontSize: 'clamp(1rem, 1.5vw, 1.125rem)',
                  lineHeight: '1.85',
                  color: 'rgba(255,255,255,0.72)',
                  letterSpacing: '-0.01em',
                }}
              >
                Not more noise. Not passive learning. A place where meaningful work can be held, practised, shared, and grown over time.
              </p>
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
    <section className="py-16 sm:py-20" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className="text-center">

          {/* Eyebrow */}
          <div className="mb-6 flex items-center justify-center gap-3">
            <div style={{ height: '1px', width: '1.5rem', flexShrink: 0, background: 'rgba(56,160,158,0.45)' }} />
            <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', color: '#38A09E' }}>
              The real shift
            </span>
            <div style={{ height: '1px', width: '1.5rem', flexShrink: 0, background: 'rgba(56,160,158,0.45)' }} />
          </div>

          {/* Heading */}
          <h2
            style={{
              fontSize: 'clamp(2.25rem, 4vw, 3.75rem)',
              letterSpacing: '-0.04em',
              lineHeight: '1.08',
              fontWeight: 660,
              marginBottom: '1.5rem',
            }}
          >
            <span style={{ display: 'block', color: '#0F172A' }}>The way we feel changes</span>
            <span
              style={{
                display: 'block',
                backgroundImage: 'linear-gradient(100deg, #1BA7A5 0%, #42C7C6 38%, #8FE3E2 68%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}
            >
              what becomes possible.
            </span>
          </h2>

          {/* Supporting line */}
          <p
            style={{
              fontSize: 'clamp(0.9375rem, 1.3vw, 1.0625rem)',
              lineHeight: '1.78',
              color: 'rgba(15,23,42,0.52)',
              maxWidth: '480px',
              margin: '0 auto',
              letterSpacing: '-0.01em',
            }}
          >
            Growth lands differently when the body feels safe, the pace feels human, and the work has somewhere to go.
          </p>

        </div>
      </Container>
    </section>
  )
}

/* ─── Where the Learning Lives ──────────────────────────────────────────────── */

function WhereTheLearningLives() {
  const features: { title: string; desc: string; iconBg: string; iconColor: string }[] = [
    {
      title: 'The REAL Journey',
      desc: 'A clear pathway through Recognise, Explore, Align, and Lead.',
      iconBg: 'rgba(56,160,158,0.12)',
      iconColor: '#38A09E',
    },
    {
      title: 'Live Layer',
      desc: 'Monthly gatherings, community prompts, and shared conversation.',
      iconBg: 'rgba(212,176,72,0.14)',
      iconColor: '#C4981A',
    },
    {
      title: 'Deepening Pathways',
      desc: 'Focused rooms for Growth, Transformation, Essence, and what comes next.',
      iconBg: 'rgba(56,160,158,0.12)',
      iconColor: '#38A09E',
    },
    {
      title: 'Practical Tools',
      desc: 'Reflections, practices, and resources designed for real life.',
      iconBg: 'rgba(56,160,158,0.12)',
      iconColor: '#38A09E',
    },
    {
      title: 'Community Rhythm',
      desc: 'A place to return to, reconnect, and keep going with others.',
      iconBg: 'rgba(56,160,158,0.12)',
      iconColor: '#38A09E',
    },
  ]

  return (
    <section className="py-20 sm:py-28" style={{ background: '#F3FAFA' }}>
      <Container>
        <div className="grid items-center gap-12 sm:grid-cols-[45%_55%] sm:gap-16">

          {/* ── Visual panel ────────────────────────────────────────────────── */}
          <div
            className="relative overflow-hidden"
            style={{
              borderRadius: '20px',
              background: 'linear-gradient(155deg, #0A1F20 0%, #0D2B2B 55%, #091C1C 100%)',
              minHeight: '420px',
              boxShadow: '0 24px 64px rgba(0,0,0,0.20), 0 4px 16px rgba(0,0,0,0.10)',
            }}
          >
            {/* Teal glow */}
            <div
              className="pointer-events-none absolute inset-0"
              aria-hidden="true"
              style={{
                background: 'radial-gradient(ellipse 80% 55% at 55% 15%, rgba(56,160,158,0.28) 0%, transparent 65%)',
              }}
            />

            <div style={{ padding: '28px', position: 'relative' }}>

              {/* Label badge */}
              <div
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '7px',
                  background: 'rgba(56,160,158,0.14)',
                  border: '1px solid rgba(85,184,182,0.22)',
                  borderRadius: '8px',
                  padding: '5px 12px',
                  marginBottom: '22px',
                }}
              >
                <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#42C7C6' }} />
                <span style={{ fontSize: '10.5px', fontWeight: 600, letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: '#7FDAD9' }}>
                  Guided pathway
                </span>
              </div>

              {/* REAL Journey card */}
              <div
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.10)',
                  borderRadius: '14px',
                  padding: '18px 20px',
                  marginBottom: '12px',
                }}
              >
                <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: '#42C7C6', marginBottom: '12px' }}>
                  REAL Journey
                </div>
                <div style={{ display: 'flex', gap: '7px', marginBottom: '14px' }}>
                  {(['R', 'E', 'A', 'L'] as const).map((letter, i) => (
                    <div
                      key={letter}
                      style={{
                        flex: 1, height: '36px', borderRadius: '8px',
                        background: i === 0 ? 'rgba(56,160,158,0.28)' : 'rgba(255,255,255,0.05)',
                        border: `1px solid ${i === 0 ? 'rgba(56,160,158,0.40)' : 'rgba(255,255,255,0.06)'}`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      <span style={{ fontSize: '12px', fontWeight: 700, color: i === 0 ? '#7FDAD9' : 'rgba(255,255,255,0.28)' }}>
                        {letter}
                      </span>
                    </div>
                  ))}
                </div>
                <div style={{ height: '3px', borderRadius: '2px', background: 'rgba(255,255,255,0.07)' }}>
                  <div style={{ height: '3px', width: '28%', borderRadius: '2px', backgroundImage: 'linear-gradient(90deg, #38A09E, #55C4C2)' }} />
                </div>
              </div>

              {/* Two smaller cards */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: '12px',
                    padding: '14px 15px',
                  }}
                >
                  <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: '#D4B048', marginBottom: '6px' }}>
                    Live Layer
                  </div>
                  <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', lineHeight: '1.5' }}>
                    Monthly gathering
                  </div>
                </div>
                <div
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: '12px',
                    padding: '14px 15px',
                  }}
                >
                  <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.32)', marginBottom: '6px' }}>
                    Practice
                  </div>
                  <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', lineHeight: '1.5' }}>
                    One experiment this week
                  </div>
                </div>
              </div>

            </div>
          </div>

          {/* ── Text + feature list ──────────────────────────────────────────── */}
          <div>

            {/* Eyebrow */}
            <div className="mb-6 flex items-center gap-3">
              <div style={{ height: '1px', width: '2rem', flexShrink: 0, background: 'rgba(56,160,158,0.45)' }} />
              <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase' as const, color: '#38A09E' }}>
                The structure
              </span>
            </div>

            {/* Heading */}
            <h2
              style={{
                fontSize: 'clamp(1.75rem, 2.8vw, 2.75rem)',
                letterSpacing: '-0.04em',
                lineHeight: '1.1',
                fontWeight: 660,
                color: '#0F172A',
                marginBottom: '1.25rem',
              }}
            >
              Everything your collective needs to become{' '}
              <span
                style={{
                  backgroundImage: 'linear-gradient(100deg, #1BA7A5 0%, #42C7C6 50%, #8FE3E2 100%)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                lived practice.
              </span>
            </h2>

            {/* Supporting line */}
            <p
              style={{
                fontSize: 'clamp(0.9375rem, 1.2vw, 1rem)',
                lineHeight: '1.78',
                color: 'rgba(15,23,42,0.54)',
                marginBottom: '2rem',
                letterSpacing: '-0.01em',
                maxWidth: '420px',
              }}
            >
              Fresh Collective brings together the structure, rhythm, and community that help ideas move from insight into everyday life.
            </p>

            {/* Feature rows */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {features.map(({ title, desc, iconBg, iconColor }) => (
                <div
                  key={title}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '14px',
                    padding: '14px 16px',
                    background: '#FFFFFF',
                    border: '1px solid rgba(15,23,42,0.07)',
                    borderRadius: '12px',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
                  }}
                >
                  <div
                    style={{
                      width: '32px', height: '32px', borderRadius: '8px',
                      background: iconBg,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    <div style={{ width: '12px', height: '12px', borderRadius: '3px', background: iconColor }} />
                  </div>
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 650, color: '#0F172A', letterSpacing: '-0.02em', lineHeight: '1.3', marginBottom: '2px' }}>
                      {title}
                    </div>
                    <div style={{ fontSize: '13px', color: 'rgba(15,23,42,0.56)', lineHeight: '1.55', letterSpacing: '-0.01em' }}>
                      {desc}
                    </div>
                  </div>
                </div>
              ))}
            </div>

          </div>
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
      a: 'That is exactly the right time to start. Fresh Collective is designed to be light enough to enter gently, while still giving you structure, rhythm, and something steady to return to.',
    },
    {
      q: 'Is this another online course I will not finish?',
      a: 'No. Fresh Collective is built around practice, rhythm, and community — not passive consumption. You are not here to race through content. You are here to let the work land.',
    },
    {
      q: 'What types of collectives are available to join?',
      a: 'Fresh Collective is designed for collectives centred around intentional growth, creativity, leadership, wellbeing, embodiment, learning, and new ways of living. As the platform grows, you will be able to explore different collectives and choose the ones that feel most relevant to where you are.',
    },
    {
      q: 'What is the difference between a collective and a pathway?',
      a: 'A collective is the wider learning environment. A pathway is a structured journey inside it. You can join a collective for the community, the rhythm, the live gatherings, and the pathways that help you go deeper.',
    },
    {
      q: 'How much time do I need each week?',
      a: 'Enough to stay connected, not enough to overwhelm you. Most pathways are designed around small, steady touchpoints that can fit into real life.',
    },
    {
      q: 'Can I build my own collective?',
      a: 'Yes. Fresh Collective is also for creators, educators, practitioners, and guides who want to build intentional learning environments around their work.',
    },
    {
      q: 'How do I create my own collective?',
      a: 'You can create a collective around your work, ideas, practice, or area of expertise. A collective can include pathways, resources, live gatherings, prompts, and community conversation. The creator experience is designed to help you build a thoughtful learning environment, not just upload content.',
    },
    {
      q: 'What is the cost?',
      a: 'Pricing will depend on the collective. Some may be free, some may be paid, and some may include different access options depending on what is included. Each collective will clearly show its pricing before you join.',
    },
  ]

  return (
    <section className="py-20 sm:py-28" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className="grid gap-12 sm:grid-cols-[38%_62%] sm:gap-16">

          {/* Left: heading */}
          <div>
            <div className="mb-6 flex items-center gap-3">
              <div style={{ height: '1px', width: '2rem', flexShrink: 0, background: 'rgba(56,160,158,0.45)' }} />
              <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', color: '#38A09E' }}>
                Questions
              </span>
            </div>

            <h2
              style={{
                fontSize: 'clamp(1.875rem, 3vw, 2.875rem)',
                letterSpacing: '-0.04em',
                lineHeight: '1.1',
                fontWeight: 660,
              }}
            >
              <span style={{ display: 'block', color: '#0F172A' }}>Good questions deserve</span>
              <span
                style={{
                  display: 'block',
                  backgroundImage: 'linear-gradient(100deg, #1BA7A5 0%, #42C7C6 38%, #8FE3E2 68%, #FFFFFF 100%)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                honest answers.
              </span>
            </h2>
          </div>

          {/* Right: accordion */}
          <div className="flex flex-col gap-3 pr-2 sm:pr-8">
            {qa.map(({ q, a }) => (
              <details
                key={q}
                className="group rounded-2xl border border-[rgba(66,199,198,0.14)] bg-[#F7FCFC]
                  shadow-[0_1px_6px_rgba(0,0,0,0.06)]
                  hover:bg-[#F1FAFA]
                  open:border-[rgba(56,160,158,0.32)] open:shadow-[0_4px_24px_rgba(56,160,158,0.09)]"
              >
                <summary className="flex cursor-pointer list-none select-none items-center justify-between gap-4 px-6 py-5">
                  <span style={{ fontSize: '15px', fontWeight: 620, color: '#0F172A', letterSpacing: '-0.02em', lineHeight: '1.4' }}>
                    {q}
                  </span>
                  <div
                    className="shrink-0 transition-transform duration-200 group-open:rotate-180"
                    style={{
                      width: '28px', height: '28px', borderRadius: '50%',
                      background: 'rgba(56,160,158,0.09)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                      <path d="M2.5 4.5L6 8L9.5 4.5" stroke="#38A09E" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </div>
                </summary>
                <div style={{ padding: '0 1.5rem 1.25rem' }}>
                  <div style={{ height: '1px', background: 'rgba(56,160,158,0.12)', marginBottom: '1rem' }} />
                  <p style={{ fontSize: '15px', lineHeight: '1.78', color: 'rgba(15,23,42,0.60)', letterSpacing: '-0.01em' }}>
                    {a}
                  </p>
                </div>
              </details>
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
    <section className="py-20 sm:py-28" style={{ background: '#FAFAF8' }}>
      <Container>

        {/* Card */}
        <div
          className="relative overflow-hidden"
          style={{
            borderRadius: '28px',
            background: '#071824',
            border: '1px solid rgba(255,255,255,0.07)',
            boxShadow: '0 8px 48px rgba(0,0,0,0.28), 0 2px 12px rgba(0,0,0,0.18)',
            padding: 'clamp(3rem, 5.5vw, 5.5rem) clamp(2rem, 6vw, 5rem)',
          }}
        >

          {/* Teal radial glow — top-centre */}
          <div
            className="pointer-events-none absolute inset-0"
            aria-hidden="true"
            style={{
              background: 'radial-gradient(ellipse 75% 55% at 50% -10%, rgba(56,160,158,0.18) 0%, transparent 65%)',
            }}
          />

          {/* Content */}
          <div className="relative z-10 flex flex-col items-center text-center">

            {/* Gold rule */}
            <div className="mb-8 h-px w-10" style={{ background: 'rgba(212,176,72,0.40)' }} />

            <h2
              className="mb-5"
              style={{
                fontSize: 'clamp(2.5rem, 5vw, 4.25rem)',
                letterSpacing: '-0.04em',
                lineHeight: '1.06',
                fontWeight: 660,
              }}
            >
              <span style={{ display: 'block', color: '#ffffff' }}>Find your collective.</span>
              <span
                style={{
                  display: 'block',
                  backgroundImage: 'linear-gradient(100deg, #42C7C6 0%, #7FDAD9 30%, #D8F5F2 58%, #FFFFFF 82%, #FFFFFF 100%)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                Or build one.
              </span>
            </h2>

            <p
              className="mb-10"
              style={{
                fontSize: 'clamp(0.9375rem, 1.3vw, 1rem)',
                lineHeight: '1.80',
                color: 'rgba(255,255,255,0.52)',
                maxWidth: '400px',
                letterSpacing: '-0.01em',
              }}
            >
              There&apos;s a collective for where you are now.
              Or build the one that doesn&apos;t exist yet.
            </p>

            {/* Buttons */}
            <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-3">
              <Link
                href="/spaces"
                className="inline-flex items-center rounded-xl px-8 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
                }}
              >
                Explore Collectives
              </Link>

              <span
                style={{
                  fontSize: '13px',
                  color: 'rgba(255,255,255,0.30)',
                  letterSpacing: '0.02em',
                  userSelect: 'none',
                }}
              >
                or
              </span>

              <Link
                href="/signup"
                className="inline-flex items-center rounded-xl px-8 py-3.5 text-[15px] font-semibold transition-all hover:-translate-y-px hover:bg-[#E8FAFA]"
                style={{
                  background: '#ffffff',
                  color: '#38A09E',
                  border: '1px solid rgba(56,160,158,0.22)',
                  boxShadow: '0 2px 12px rgba(0,0,0,0.14)',
                }}
              >
                Build a Collective
              </Link>
            </div>

            {/* Gold rule */}
            <div className="mt-10 h-px w-10" style={{ background: 'rgba(212,176,72,0.40)' }} />

          </div>
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
      <GoodQuestions />
      <FinalCTA />
    </SiteShell>
  )
}
