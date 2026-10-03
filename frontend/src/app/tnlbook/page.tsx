/**
 * /tnlbook — public opt-in for The Natural Leader book resources.
 *
 * A legacy public Wix URL that may be printed in the book, preserved as
 * a real standalone page. Deliberately NOT a redirect to /tnlbook123:
 * the two are different steps of one flow. This page collects the
 * reader's details through MailerLite; /tnlbook123 is where the
 * resources themselves live.
 *
 * Public and signed-out. Fresh Collective stores nothing from this
 * form — it posts straight to MailerLite, which owns the subscriber
 * record and the automation that follows.
 *
 * Visual intent: a light Fresh Collective page, not a Natural Leader
 * microsite. The book supplies the identity through the cover and a
 * warm gold-50 panel; everything else is the platform's own language.
 *
 * The form itself is MailerLite's official embed, transcribed into a
 * client component — see ``MailerLiteBookForm``. Fresh Collective never
 * sees the name or email: the form posts straight to MailerLite.
 */

import type { Metadata } from 'next'
import Image from 'next/image'

import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'

import MailerLiteBookForm from './MailerLiteBookForm'

/** Reused from the Book Companion — one copy of the asset, not two. */
const BOOK_COVER = '/book-companion/natural-leader-front-cover.jpg'

export const metadata: Metadata = {
  title: 'The Natural Leader Book Resources · Fresh Collective',
  description:
    'Access the free companion resources for The Natural Leader by '
    + 'Lindsey Hilliard.',
}

export default function NaturalLeaderBookOptInPage() {
  return (
    <SiteShell>
      <section className="py-14 md:py-20">
        <Container>
          <div className="grid items-center gap-12 md:grid-cols-2 md:gap-16">
            {/* Left — heading, copy, form. First in the DOM, so it is
                also first when the grid stacks on mobile. */}
            <div className="max-w-[34rem]">
              <h1 className="mb-6 font-serif text-4xl leading-[1.15] text-navy-900 md:text-5xl">
                Get{' '}
                <em className="not-italic text-gold-500">The Natural Leader</em>{' '}
                Book Resources Now
              </h1>
              <p className="mb-9 text-lg leading-relaxed text-[#4A5568]">
                Just enter your name and email and you&apos;ll get instant
                access.
              </p>

              <div className="max-w-[26rem]">
                <MailerLiteBookForm />
              </div>
            </div>

            {/* Right — the book, on a warm panel. gold-50 is the
                existing FC token, so the warmth comes from the palette
                rather than a colour invented for this page. */}
            <div className="flex items-center justify-center rounded-2xl bg-gold-50 px-8 py-12 md:px-10 md:py-16">
              <Image
                src={BOOK_COVER}
                alt="The Natural Leader by Lindsey Hilliard — front cover"
                width={1310}
                height={2048}
                sizes="(min-width: 768px) 300px, 220px"
                className="h-auto w-[220px] rounded-lg md:w-[300px]"
                style={{ boxShadow: '0 18px 44px rgba(12,24,38,0.18)' }}
              />
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
