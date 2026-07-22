import Link from 'next/link'
import PublicHeader from './PublicHeader'

/**
 * Shared visual shell for the /login and /signup pages.
 *
 * One coherent entry-experience: full-bleed Atlas artwork, deep navy
 * overlay, transparent header, two-column composition on desktop
 * (welcome copy left, auth card right), minimal footer.
 *
 * The forms themselves are not abstracted — /login and /signup keep
 * their own card components so field logic, validation, and API calls
 * stay explicit and independently maintainable.
 */
export default function AuthPageShell({
  welcomeTitle,
  welcomeSubtitle,
  children,
}: {
  welcomeTitle: React.ReactNode
  welcomeSubtitle: string
  /** The auth card (login form or signup form). */
  children: React.ReactNode
}) {
  return (
    <div
      className="relative flex min-h-screen w-full flex-col overflow-x-hidden"
      style={{ background: '#050B14' }}
    >
      {/* ─────── Full-bleed world background + navy overlay ─────── */}
      <div className="absolute inset-0" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/world/login-hero.png"
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          style={{ objectPosition: 'center 40%' }}
        />
        {/* Deep navy → teal gradient overlay. Heavier on the right so the
            auth card sits on the darker area for maximum contrast; lighter
            on the left so a hint of the world imagery breathes through
            under the welcome copy. */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(115deg, rgba(5,11,20,0.62) 0%, rgba(7,24,36,0.78) 45%, rgba(7,24,36,0.90) 100%)',
          }}
        />
        {/* Subtle top+bottom vignette keeps header + footer readable
            regardless of image content in those regions. */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(180deg, rgba(5,11,20,0.35) 0%, transparent 25%, transparent 75%, rgba(5,11,20,0.45) 100%)',
          }}
        />
      </div>

      {/* ─────── Transparent overlay header ─────── */}
      <PublicHeader overlay />

      {/* ─────── Two-column content ─────── */}
      <main className="relative z-10 flex flex-1 items-center px-6 pt-28 pb-16 md:px-10 md:pt-32 md:pb-24">
        <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 items-center gap-12 lg:grid-cols-[1.15fr_460px] lg:gap-16">

          {/* Left: welcome copy — desktop only. Hidden on tablet/mobile so
              the auth card gets full attention on small screens. */}
          <div className="hidden lg:flex lg:flex-col lg:justify-center">
            <div
              className="mb-5 h-[2px] w-10 rounded-full"
              style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
              aria-hidden="true"
            />
            <h1
              className="font-serif text-[44px] leading-[1.08] tracking-[-0.01em]"
              style={{ color: '#FFFFFF' }}
            >
              {welcomeTitle}
            </h1>
            <p
              className="mt-5 max-w-[440px] text-[16px] italic leading-relaxed"
              style={{ color: 'rgba(255, 255, 255, 0.82)', fontFamily: 'Georgia, serif' }}
            >
              {welcomeSubtitle}
            </p>
          </div>

          {/* Right: auth card */}
          <div className="flex items-center justify-center lg:justify-end">
            {children}
          </div>

        </div>
      </main>

      {/* ─────── Minimal footer, over the darkened background ─────── */}
      <footer className="relative z-10 px-6 pb-6 pt-4 md:px-10">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-3 text-[12px]">
          <p style={{ color: 'rgba(255, 255, 255, 0.55)' }}>
            © {new Date().getFullYear()} Fresh Collective
          </p>
          <nav aria-label="Legal" className="flex gap-6">
            <Link
              href="/privacy"
              className="transition-opacity hover:opacity-100"
              style={{ color: 'rgba(255, 255, 255, 0.62)' }}
            >
              Privacy
            </Link>
            <Link
              href="/terms"
              className="transition-opacity hover:opacity-100"
              style={{ color: 'rgba(255, 255, 255, 0.62)' }}
            >
              Terms
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  )
}

/**
 * Teal-to-white gradient span used for the accent portion of the welcome
 * heading on both /login and /signup. Exported so each page can decide
 * exactly which words carry the accent.
 */
export function AuthTitleAccent({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        background: 'linear-gradient(120deg, #55D7D2 0%, #FFFFFF 55%)',
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundClip: 'text',
      }}
    >
      {children}
    </span>
  )
}
