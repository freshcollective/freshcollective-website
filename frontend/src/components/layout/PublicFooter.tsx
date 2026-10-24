import Link from 'next/link'

import { WG_DOC, wgHref } from '@/lib/worldGuide'
import Container from './Container'
import { CONTACT_INFO_EMAIL } from '@/lib/contact'
import { BrandLockup } from '@/components/brand/FreshCollectiveBrand'

export default function PublicFooter() {
  return (
    <footer
      className="relative"
      style={{
        background:
          'radial-gradient(circle at 18% 0%, rgba(66,199,198,0.22) 0%, transparent 38%), linear-gradient(180deg, #071824 0%, #050B14 100%)',
        borderTop: '1px solid rgba(255,255,255,0.09)',
      }}
    >
      <Container className="py-14 md:py-18">

        <div className="grid gap-10 md:grid-cols-[1fr_auto] md:items-start">

          <div>
            <div className="mb-4">
              <BrandLockup tone="dark" markSize={32} />
            </div>
            <p
              className="max-w-[300px] text-[14px] leading-[1.78]"
              style={{ color: '#FFFFFF' }}
            >
              A home for creator-led communities — structured pathways,
              live gatherings, and intentional community.
            </p>
          </div>

          <nav aria-label="Footer" className="flex flex-wrap gap-x-8 gap-y-2.5 pt-1">
            {[
              { href: '/spaces', label: 'Explore Collectives' },
              { href: '/login',  label: 'Log in' },
              { href: '/signup', label: 'Join' },
            ].map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="text-[13px] transition-colors hover:text-white"
                style={{ color: '#FFFFFF' }}
              >
                {label}
              </Link>
            ))}
            {/* An anchor rather than ``Link``: a mailto is not a route,
                so there is no navigation to prefetch. Styled from the
                same values as its siblings so the row reads as one
                nav. ``info@`` rather than ``support@`` because a
                footer catches general, membership and creator
                enquiries from people who are not yet members —
                somebody with a technical problem meets ``support@`` at
                the point where they are stuck. */}
            <a
              href={`mailto:${CONTACT_INFO_EMAIL}`}
              className="text-[13px] transition-colors hover:text-white"
              style={{ color: '#FFFFFF' }}
            >
              Contact
            </a>
          </nav>

          {/* Governance — the four documents someone actually reaches
              for from a footer. The other five live one click away on
              the World Guide; listing all nine here would bury the
              ones people need. */}
          <nav
            aria-label="Governance and help"
            className="flex flex-wrap gap-x-8 gap-y-2.5"
          >
            {[
              { href: '/world-guide',            label: 'World Guide' },
              { href: wgHref(WG_DOC.TERMS_OF_USE),   label: 'Terms of Use' },
              { href: wgHref(WG_DOC.PRIVACY_POLICY), label: 'Privacy Policy' },
              { href: wgHref(WG_DOC.PAYMENT_POLICY), label: 'Payments & Refunds' },
            ].map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="text-[13px] transition-colors hover:text-white"
                style={{ color: 'rgba(255,255,255,0.72)' }}
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
          <p className="text-[12px]" style={{ color: '#FFFFFF' }}>
            © {new Date().getFullYear()} Fresh Collective. All rights reserved.
          </p>
        </div>

      </Container>
    </footer>
  )
}
