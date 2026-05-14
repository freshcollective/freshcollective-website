import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'

/* ─── Hero ──────────────────────────────────────────────────────────────────── */

function CreatorHero() {
  return (
    <section
      className="relative flex overflow-hidden"
      style={{ background: '#071824', minHeight: 'clamp(560px, 70vh, 700px)' }}
    >
      {/* Teal radial glow — top right */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(ellipse 70% 60% at 88% -5%, rgba(56,160,158,0.26) 0%, transparent 65%)',
        }}
      />
      {/* Secondary glow — bottom left */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(ellipse 55% 50% at -8% 105%, rgba(38,110,108,0.15) 0%, transparent 60%)',
        }}
      />
      {/* Grain overlay */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          backgroundImage: `url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='300' height='300' filter='url(%23n)' opacity='0.025'/></svg>")`,
        }}
      />

      <div
        className="relative z-10 w-full"
        style={{ paddingTop: 'clamp(7rem, 14vw, 10rem)', paddingBottom: 'clamp(4rem, 8vw, 6rem)' }}
      >
        <Container>
          <div className="max-w-[680px]">

            <div className="mb-5 flex items-center gap-3">
              <div className="h-px w-6 shrink-0" style={{ background: 'rgba(143,227,226,0.45)' }} />
              <span
                className="text-[10.5px] font-semibold uppercase tracking-[0.20em]"
                style={{ color: 'rgba(255,255,255,0.36)' }}
              >
                For Creators
              </span>
            </div>

            <h1
              className="mb-7"
              style={{
                fontSize: 'clamp(2.75rem, 6vw, 5.5rem)',
                lineHeight: '1.03',
                letterSpacing: '-0.04em',
                fontWeight: 660,
              }}
            >
              <span style={{ display: 'block', color: '#ffffff' }}>Build the collective</span>
              <span
                style={{
                  display: 'block',
                  backgroundImage: 'linear-gradient(100deg, #42C7C6 0%, #7FDAD9 28%, #D8F5F2 55%, #FFFFFF 78%, #FFFFFF 100%)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                you wish existed.
              </span>
            </h1>

            <p
              className="mb-9"
              style={{
                fontSize: 'clamp(1rem, 1.4vw, 1.0625rem)',
                lineHeight: '1.80',
                color: 'rgba(255,255,255,0.50)',
                maxWidth: '460px',
                letterSpacing: '-0.01em',
              }}
            >
              Create an intentional learning environment around your work — with pathways, live rhythm, resources, and community designed to help people practise real change.
            </p>

            <div className="flex flex-wrap items-center gap-3">
              <Link
                href="/signup"
                className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
                }}
              >
                Start Building
              </Link>
              <Link
                href="/spaces"
                className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold transition-all hover:-translate-y-px"
                style={{
                  background: 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.16)',
                  color: 'rgba(255,255,255,0.80)',
                  backdropFilter: 'blur(8px)',
                }}
              >
                Explore Collectives
              </Link>
            </div>

            <p
              className="mt-5"
              style={{ fontSize: '13px', color: 'rgba(255,255,255,0.36)', letterSpacing: '-0.01em' }}
            >
              Founding creator access from{' '}
              <span style={{ color: 'rgba(255,255,255,0.58)', fontWeight: 500 }}>$19/month.</span>
            </p>

          </div>
        </Container>
      </div>
    </section>
  )
}

/* ─── Who This Is For ───────────────────────────────────────────────────────── */

function WhoThisIsFor() {
  const types = [
    {
      icon: (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M10 2L2 6l8 4 8-4-8-4z" stroke="#38A09E" strokeWidth="1.5" strokeLinejoin="round"/>
          <path d="M2 10l8 4 8-4" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M2 14l8 4 8-4" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      ),
      label: 'Educators and teachers',
      body: 'For people who want to guide learning in a more human, spacious way.',
    },
    {
      icon: (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <circle cx="10" cy="10" r="3" stroke="#38A09E" strokeWidth="1.5"/>
          <path d="M10 2v2M10 16v2M2 10h2M16 10h2" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
          <path d="M4.93 4.93l1.42 1.42M13.65 13.65l1.42 1.42M4.93 15.07l1.42-1.42M13.65 6.35l1.42-1.42" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      ),
      label: 'Practitioners and facilitators',
      body: 'For people holding work that is relational, embodied, reflective, or transformational.',
    },
    {
      icon: (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <circle cx="10" cy="7.5" r="2.5" stroke="#38A09E" strokeWidth="1.5"/>
          <path d="M4.5 17c0-3.038 2.462-5.5 5.5-5.5s5.5 2.462 5.5 5.5" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
          <path d="M14 4.5c.828.828.828 2.172 0 3" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      ),
      label: 'Coaches and guides',
      body: 'For people helping others move through change, growth, leadership, creativity, or transition.',
    },
    {
      icon: (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M10 3v14M3 10h14" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
          <rect x="6" y="6" width="8" height="8" rx="1.5" stroke="#38A09E" strokeWidth="1.5"/>
        </svg>
      ),
      label: 'Thought leaders and builders',
      body: 'For people creating new ways of living, leading, learning, healing, or working.',
    },
  ]

  return (
    <section className="py-20 sm:py-28" style={{ background: '#FFFFFF' }}>
      <Container>

        <div className="mb-14 max-w-[600px]">
          <p style={{ fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase' as const, color: '#38A09E', marginBottom: '16px' }}>
            Who this is for
          </p>
          <h2 style={{ fontSize: 'clamp(1.875rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 660, color: '#0F172A', marginBottom: '16px' }}>
            For people with work that wants to move.
          </h2>
          <p style={{ fontSize: 'clamp(0.9375rem, 1.3vw, 1.0625rem)', lineHeight: '1.78', color: 'rgba(15,23,42,0.58)' }}>
            This is for the people carrying ideas, practices, frameworks, questions, and ways of seeing that need more than a post, a course, or a download.
          </p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 sm:gap-6">
          {types.map(({ icon, label, body }) => (
            <div
              key={label}
              className="rounded-2xl p-7"
              style={{
                background: '#FAFAF8',
                border: '1px solid rgba(15,23,42,0.07)',
                boxShadow: '0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04)',
              }}
            >
              <div
                className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl"
                style={{ background: 'rgba(56,160,158,0.09)' }}
              >
                {icon}
              </div>
              <h3 style={{ fontSize: '1.0625rem', fontWeight: 660, letterSpacing: '-0.025em', color: '#0F172A', marginBottom: '8px', lineHeight: '1.3' }}>
                {label}
              </h3>
              <p style={{ fontSize: '14.5px', lineHeight: '1.72', color: 'rgba(15,23,42,0.60)' }}>
                {body}
              </p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── What You Can Build ────────────────────────────────────────────────────── */

function WhatYouCanBuild() {
  const features = [
    {
      title: 'Pathways',
      desc: 'Structure your ideas into guided journeys people can move through over time.',
    },
    {
      title: 'Live gatherings',
      desc: 'Host conversations, workshops, circles, Q&A sessions, or community touchpoints.',
    },
    {
      title: 'Resources',
      desc: 'Share tools, prompts, reflections, files, practices, and supporting materials.',
    },
    {
      title: 'Community',
      desc: 'Create a focused environment where people can connect around the same work.',
    },
    {
      title: 'Creator workspace',
      desc: 'Manage your collective, organise your content, and guide the experience with clarity.',
    },
  ]

  return (
    <section className="py-20 sm:py-28" style={{ background: '#F3FAFA' }}>
      <Container>
        <div className="grid items-center gap-12 sm:grid-cols-[45fr_55fr] sm:gap-16">

          {/* ── Visual panel ──────────────────────────────────────────────────── */}
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
                background: 'radial-gradient(ellipse 80% 55% at 55% 15%, rgba(56,160,158,0.26) 0%, transparent 65%)',
              }}
            />

            <div style={{ padding: '28px', position: 'relative' }}>

              {/* Badge */}
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
                  Creator workspace
                </span>
              </div>

              {/* Workspace chrome */}
              <div
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.10)',
                  borderRadius: '14px',
                  overflow: 'hidden',
                  marginBottom: '12px',
                }}
              >
                {/* Chrome bar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '10px 14px', background: 'rgba(0,0,0,0.18)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'rgba(255,255,255,0.15)' }} />
                  <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'rgba(255,255,255,0.15)' }} />
                  <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'rgba(255,255,255,0.15)' }} />
                  <span style={{ fontSize: '10px', fontWeight: 600, color: 'rgba(255,255,255,0.30)', marginLeft: '8px', letterSpacing: '0.02em' }}>My Collective</span>
                </div>
                {/* Workspace body */}
                <div style={{ display: 'flex', minHeight: '200px' }}>
                  {/* Sidebar */}
                  <div style={{ width: '38%', borderRight: '1px solid rgba(255,255,255,0.06)', padding: '14px' }}>
                    <div style={{ fontSize: '9px', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.28)', marginBottom: '10px' }}>Sections</div>
                    {[
                      { label: 'Pathways', active: true },
                      { label: 'Gatherings', active: false },
                      { label: 'Resources', active: false },
                      { label: 'Community', active: false },
                    ].map(({ label, active }) => (
                      <div
                        key={label}
                        style={{
                          padding: '6px 9px',
                          borderRadius: '6px',
                          marginBottom: '2px',
                          background: active ? 'rgba(56,160,158,0.18)' : 'transparent',
                        }}
                      >
                        <span style={{ fontSize: '11.5px', color: active ? '#7FDAD9' : 'rgba(255,255,255,0.38)', fontWeight: active ? 640 : 400 }}>{label}</span>
                      </div>
                    ))}
                    <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                      <div style={{ fontSize: '9.5px', color: 'rgba(255,255,255,0.28)', marginBottom: '4px' }}>Members</div>
                      <div style={{ fontSize: '18px', fontWeight: 660, color: 'rgba(255,255,255,0.88)', letterSpacing: '-0.03em' }}>12</div>
                      <div style={{ fontSize: '9.5px', color: '#7FDAD9', fontWeight: 600 }}>+2 this week</div>
                    </div>
                  </div>
                  {/* Main content */}
                  <div style={{ flex: 1, padding: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                      <div style={{ fontSize: '11.5px', fontWeight: 640, color: 'rgba(255,255,255,0.80)', letterSpacing: '-0.01em' }}>Pathways</div>
                      <div style={{ fontSize: '10px', fontWeight: 700, color: '#7FDAD9', letterSpacing: '0.05em' }}>+ New</div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {[
                        { name: 'Your first pathway', modules: '4 modules', status: 'Published' },
                        { name: 'Deep dive series', modules: '6 modules', status: 'Draft' },
                      ].map(({ name, modules, status }) => (
                        <div
                          key={name}
                          style={{
                            borderRadius: '7px',
                            padding: '9px 11px',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,255,255,0.07)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                          }}
                        >
                          <div>
                            <div style={{ fontSize: '11.5px', fontWeight: 580, color: 'rgba(255,255,255,0.78)', marginBottom: '2px' }}>{name}</div>
                            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.32)' }}>{modules}</div>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                            <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: status === 'Published' ? '#42C7C6' : 'rgba(255,255,255,0.25)' }} />
                            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.38)', fontWeight: 500 }}>{status}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Two bottom cards */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '14px 15px' }}>
                  <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: '#7FDAD9', marginBottom: '6px' }}>
                    Next gathering
                  </div>
                  <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', lineHeight: '1.5' }}>
                    Monthly open circle
                  </div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '14px 15px' }}>
                  <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.32)', marginBottom: '6px' }}>
                    Community
                  </div>
                  <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', lineHeight: '1.5' }}>
                    4 posts this week
                  </div>
                </div>
              </div>

            </div>
          </div>

          {/* ── Feature list ──────────────────────────────────────────────────── */}
          <div>

            <div className="mb-6 flex items-center gap-3">
              <div style={{ height: '1px', width: '2rem', flexShrink: 0, background: 'rgba(56,160,158,0.45)' }} />
              <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase' as const, color: '#38A09E' }}>
                What you can build
              </span>
            </div>

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
              A collective gives your work{' '}
              <span
                style={{
                  backgroundImage: 'linear-gradient(100deg, #0F8F8D 0%, #26B9B7 45%, #67D8D6 100%)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                somewhere to live.
              </span>
            </h2>

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
              Every piece of your work has a place. Build the structure once, and let it hold people well over time.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {features.map(({ title, desc }) => (
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
                      background: 'rgba(56,160,158,0.10)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    <div style={{ width: '12px', height: '12px', borderRadius: '3px', background: '#38A09E' }} />
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

/* ─── Why Not Just a Course ─────────────────────────────────────────────────── */

function WhyNotJustACourse() {
  const principles = [
    {
      heading: 'Structure without pressure',
      body: 'Give people a clear path without rushing them through it.',
      icon: (
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
          <path d="M4 11h14M11 4l7 7-7 7" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      ),
    },
    {
      heading: 'Community without noise',
      body: 'Create focused conversation around the work, not endless distraction.',
      icon: (
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
          <circle cx="8" cy="9" r="3" stroke="#38A09E" strokeWidth="1.5"/>
          <path d="M3 18c0-2.761 2.239-5 5-5h.5" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
          <circle cx="15" cy="12" r="2.5" stroke="#38A09E" strokeWidth="1.5"/>
          <path d="M11 19c0-2.209 1.791-4 4-4s4 1.791 4 4" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      ),
    },
    {
      heading: 'Practice without performance',
      body: 'Help people return, reflect, and apply what they are learning in real life.',
      icon: (
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
          <path d="M11 4v14M7 8l4-4 4 4" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M5 17h12" stroke="#38A09E" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      ),
    },
  ]

  return (
    <section className="py-20 sm:py-28" style={{ background: '#FFFFFF' }}>
      <Container>

        <div className="mb-16 max-w-[580px]">
          <p style={{ fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase' as const, color: '#38A09E', marginBottom: '16px' }}>
            A different kind of platform
          </p>
          <h2
            style={{
              fontSize: 'clamp(2rem, 4vw, 3.25rem)',
              letterSpacing: '-0.04em',
              lineHeight: '1.07',
              fontWeight: 660,
              color: '#0F172A',
              marginBottom: '1.25rem',
            }}
          >
            Not just content.
            <br />
            <span
              style={{
                backgroundImage: 'linear-gradient(100deg, #0F8F8D 0%, #26B9B7 45%, #67D8D6 100%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}
            >
              A living environment.
            </span>
          </h2>
          <p style={{ fontSize: 'clamp(0.9375rem, 1.3vw, 1.0625rem)', lineHeight: '1.78', color: 'rgba(15,23,42,0.58)' }}>
            Most platforms are built around content delivery. Fresh Collective is built around integration — the space between learning something and actually living it.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-3">
          {principles.map(({ heading, body, icon }) => (
            <div
              key={heading}
              className="rounded-2xl p-7"
              style={{
                background: '#FAFAF8',
                border: '1px solid rgba(15,23,42,0.07)',
                boxShadow: '0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04)',
              }}
            >
              <div
                className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl"
                style={{ background: 'rgba(56,160,158,0.09)' }}
              >
                {icon}
              </div>
              <h3 style={{ fontSize: '1.0625rem', fontWeight: 660, letterSpacing: '-0.025em', color: '#0F172A', marginBottom: '8px', lineHeight: '1.3' }}>
                {heading}
              </h3>
              <p style={{ fontSize: '14.5px', lineHeight: '1.72', color: 'rgba(15,23,42,0.60)' }}>
                {body}
              </p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── How It Works ──────────────────────────────────────────────────────────── */

function HowItWorks() {
  const steps = [
    {
      num: '1',
      heading: 'Shape your collective',
      body: 'Name the purpose, audience, and change your work supports.',
    },
    {
      num: '2',
      heading: 'Create your first pathway',
      body: 'Turn your ideas into a guided learning journey.',
    },
    {
      num: '3',
      heading: 'Add rhythm',
      body: 'Bring in live gatherings, prompts, and community touchpoints.',
    },
    {
      num: '4',
      heading: 'Invite people in',
      body: 'Open the doors when the structure is ready enough to hold them.',
    },
  ]

  return (
    <section className="py-20 sm:py-28" style={{ background: '#FAFAF8' }}>
      <Container>

        <div className="mb-14 text-center">
          <p style={{ fontSize: '10.5px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase' as const, color: '#38A09E', marginBottom: '16px' }}>
            How it works
          </p>
          <h2 style={{ fontSize: 'clamp(1.875rem, 3.5vw, 3rem)', letterSpacing: '-0.04em', lineHeight: '1.1', fontWeight: 660, color: '#0F172A' }}>
            Start simple. Build with depth.
          </h2>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 sm:gap-6 lg:grid-cols-4">
          {steps.map(({ num, heading, body }) => (
            <div
              key={num}
              className="rounded-2xl p-7"
              style={{
                background: '#FFFFFF',
                border: '1px solid rgba(15,23,42,0.07)',
                boxShadow: '0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04)',
              }}
            >
              <div
                className="mb-5 flex h-9 w-9 items-center justify-center rounded-full text-[13px] font-bold"
                style={{
                  background: 'rgba(56,160,158,0.10)',
                  color: '#38A09E',
                }}
              >
                {num}
              </div>
              <h3 style={{ fontSize: '1rem', fontWeight: 660, letterSpacing: '-0.025em', color: '#0F172A', marginBottom: '8px', lineHeight: '1.3' }}>
                {heading}
              </h3>
              <p style={{ fontSize: '14px', lineHeight: '1.72', color: 'rgba(15,23,42,0.58)' }}>
                {body}
              </p>
            </div>
          ))}
        </div>

      </Container>
    </section>
  )
}

/* ─── Creator CTA ───────────────────────────────────────────────────────────── */

function CreatorCTA() {
  return (
    <section className="py-20 sm:py-28" style={{ background: '#FAFAF8' }}>
      <Container>

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

          {/* Teal radial glow */}
          <div
            className="pointer-events-none absolute inset-0"
            aria-hidden="true"
            style={{
              background: 'radial-gradient(ellipse 75% 55% at 50% -10%, rgba(56,160,158,0.18) 0%, transparent 65%)',
            }}
          />

          <div className="relative z-10 flex flex-col items-center text-center">

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
              <span style={{ display: 'block', color: '#ffffff' }}>Build the one</span>
              <span
                style={{
                  display: 'block',
                  backgroundImage: 'linear-gradient(100deg, #42C7C6 0%, #7FDAD9 30%, #D8F5F2 58%, #FFFFFF 82%, #FFFFFF 100%)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                that does not exist yet.
              </span>
            </h2>

            <p
              className="mb-8"
              style={{
                fontSize: 'clamp(0.9375rem, 1.3vw, 1rem)',
                lineHeight: '1.80',
                color: 'rgba(255,255,255,0.52)',
                maxWidth: '400px',
                letterSpacing: '-0.01em',
              }}
            >
              Start simple. Build your first collective around the work you know matters.
            </p>

            {/* Pricing block */}
            <div
              className="mb-8 flex flex-col items-center"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(66,199,198,0.18)',
                borderRadius: '16px',
                padding: '20px 32px',
              }}
            >
              <p style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase' as const, color: '#7FDAD9', marginBottom: '8px' }}>
                Founding creator access
              </p>
              <p style={{ fontSize: 'clamp(2.25rem, 4vw, 3rem)', fontWeight: 660, letterSpacing: '-0.04em', color: '#ffffff', lineHeight: 1 }}>
                $19
                <span style={{ fontSize: '1.125rem', fontWeight: 500, color: 'rgba(255,255,255,0.45)', letterSpacing: '-0.01em' }}>/month</span>
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-3">
              <Link
                href="/signup"
                className="inline-flex items-center rounded-xl px-8 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
                }}
              >
                Start Building
              </Link>

              <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.30)', letterSpacing: '0.02em', userSelect: 'none' as const }}>
                or
              </span>

              <Link
                href="/"
                className="inline-flex items-center rounded-xl px-8 py-3.5 text-[15px] font-semibold transition-all hover:-translate-y-px hover:bg-[#E8FAFA]"
                style={{
                  background: '#ffffff',
                  color: '#38A09E',
                  border: '1px solid rgba(56,160,158,0.22)',
                  boxShadow: '0 2px 12px rgba(0,0,0,0.14)',
                }}
              >
                Back to Home
              </Link>
            </div>

            <div className="mt-10 h-px w-10" style={{ background: 'rgba(212,176,72,0.40)' }} />

          </div>
        </div>

      </Container>
    </section>
  )
}

/* ─── Page ──────────────────────────────────────────────────────────────────── */

export default function ForCreatorsPage() {
  return (
    <SiteShell heroHeader>
      <CreatorHero />
      <WhoThisIsFor />
      <WhatYouCanBuild />
      <WhyNotJustACourse />
      <HowItWorks />
      <CreatorCTA />
    </SiteShell>
  )
}
