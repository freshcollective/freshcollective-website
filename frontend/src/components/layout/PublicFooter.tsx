import Link from 'next/link'
import Container from './Container'

export default function PublicFooter() {
  return (
    <footer
      className="relative"
      style={{ background: '#060C17', borderTop: '1px solid rgba(255,255,255,0.05)' }}
    >
      <Container className="py-12 md:py-16">

        <div className="grid gap-10 md:grid-cols-[1fr_auto] md:items-start">

          <div>
            <div className="mb-4 flex items-center gap-2.5">
              <div
                className="flex h-6 w-6 items-center justify-center rounded-md"
                style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
              >
                <div className="h-[10px] w-[10px] rounded-sm bg-white" style={{ opacity: 0.9 }} />
              </div>
              <span className="text-[15px] font-semibold tracking-[-0.02em] text-white">
                Fresh Collective
              </span>
            </div>
            <p className="max-w-[300px] text-[14px] leading-[1.75] text-navy-400">
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
                style={{ color: 'rgba(255,255,255,0.35)' }}
              >
                {label}
              </Link>
            ))}
          </nav>

        </div>

        <div
          className="mt-10 flex items-center justify-between pt-6"
          style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}
        >
          <p className="text-[12px]" style={{ color: 'rgba(255,255,255,0.20)' }}>
            © {new Date().getFullYear()} Fresh Collective. All rights reserved.
          </p>
        </div>

      </Container>
    </footer>
  )
}
