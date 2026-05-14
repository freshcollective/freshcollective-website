import Link from 'next/link'
import Container from './Container'

export default function PublicFooter() {
  return (
    <footer
      className="relative"
      style={{
        background:
          'radial-gradient(circle at 20% 0%, rgba(66,199,198,0.13) 0%, transparent 34%), linear-gradient(180deg, #071824 0%, #050B14 100%)',
        borderTop: '1px solid rgba(255,255,255,0.09)',
      }}
    >
      <Container className="py-14 md:py-18">

        <div className="grid gap-10 md:grid-cols-[1fr_auto] md:items-start">

          <div>
            <div className="mb-4 flex items-center gap-2.5">
              <div
                className="flex h-6 w-6 items-center justify-center rounded-md"
                style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
              >
                <div className="h-[10px] w-[10px] rounded-sm bg-white" style={{ opacity: 0.92 }} />
              </div>
              <span
                className="text-[15px] font-semibold tracking-[-0.02em]"
                style={{ color: 'rgba(255,255,255,0.90)' }}
              >
                Fresh Collective
              </span>
            </div>
            <p
              className="max-w-[300px] text-[14px] leading-[1.78]"
              style={{ color: 'rgba(255,255,255,0.52)' }}
            >
              Creator-led collectives for transformative growth — structured pathways,
              live gatherings, and intentional community.
            </p>
          </div>

          <nav aria-label="Footer" className="flex flex-wrap gap-x-8 gap-y-2.5 pt-1">
            {[
              { href: '/spaces', label: 'Explore Collectives' },
              { href: '/about',  label: 'About' },
              { href: '/login',  label: 'Log in' },
              { href: '/signup', label: 'Join' },
            ].map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="text-[13px] transition-colors hover:text-white"
                style={{ color: 'rgba(255,255,255,0.50)' }}
              >
                {label}
              </Link>
            ))}
          </nav>

        </div>

        <div
          className="mt-10 flex items-center justify-between pt-6"
          style={{ borderTop: '1px solid rgba(255,255,255,0.09)' }}
        >
          <p className="text-[12px]" style={{ color: 'rgba(255,255,255,0.28)' }}>
            © {new Date().getFullYear()} Fresh Collective. All rights reserved.
          </p>
        </div>

      </Container>
    </footer>
  )
}
