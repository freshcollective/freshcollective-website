import type { Metadata } from 'next'

import Container from '@/components/layout/Container'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { SERIF_HEADING } from '@/components/guides/serif'
import MailerLiteStarterKitForm from './MailerLiteStarterKitForm'

/**
 * /starter-kit — the free Creator Starter Kit opt-in.
 *
 * Public and signed out. Nothing here asks for an account, and the kit
 * itself is not on this site: the PDF lives in MailerLite and arrives
 * by email, so this page's only job is to explain the workbook and
 * hand the address over.
 *
 * Double opt-in, which the copy has to respect — the success state says
 * "confirm your email", not "it's on its way", because at that moment
 * it is not. See ``MailerLiteStarterKitForm``.
 *
 * Styled to match /guides: the same navy ``PageHero`` card, centred,
 * with the gold rule. Ground is white for the same reason the Guides
 * index is — these are the two public marketing surfaces that share a
 * look.
 */

export const metadata: Metadata = {
  title: 'Creator Starter Kit',
  description:
    'A free, printable workbook for coaches, teachers and practitioners: '
    + 'what to set up, what to say to your people, and a move plan.',
}

const SUBTITLE =
  'A free workbook for coaches, teachers and practitioners ready to give '
  + 'their work a home of its own.'

/** The eight worksheets, in the order they appear in the kit. */
const INSIDE = [
  'Who it’s for, and how it should feel',
  'What your work holds',
  'Choose your set-up',
  'Before you invite anyone',
  'What to say before you move',
  'The invitation and follow-up emails',
  'Your move plan',
  'Your first week in',
]

export default function StarterKitPage() {
  return (
    <SiteShell>
      <div style={{ background: '#FFFFFF' }}>
        {/* The one h1 on the page — PageHero carries it, as it does on
            /guides. Nothing below uses h1 again. */}
        <PageHero
          title="Creator Starter Kit"
          supportingCopy={SUBTITLE}
          bandBackground="#FFFFFF"
          align="center"
          accentTone="gold"
        />

        <Container className="pb-16 pt-10 md:pb-24 md:pt-12">
          {/* Two columns from ``lg`` up, stacked below. The form column
              is narrower and fixed so the reading column keeps a
              comfortable measure on a wide screen rather than running
              to 900px. */}
          <div className="grid grid-cols-1 gap-10 lg:grid-cols-[1fr_380px] lg:gap-14">
            <div>
              <p className="text-[16.5px] leading-relaxed text-navy-900">
                Ten printable pages to work through with a pen. By the end
                you&rsquo;ll know what to set up, what to say to your people,
                and when.
              </p>

              <h2
                className="mt-10 text-[22px] text-navy-900"
                style={SERIF_HEADING}
              >
                What&rsquo;s inside
              </h2>
              {/* Plain discs and no card: this is a list of worksheets,
                  not a feature grid, and dressing it up would oversell a
                  workbook. */}
              <ul className="mt-4 space-y-2.5">
                {INSIDE.map((item) => (
                  <li
                    key={item}
                    className="flex gap-3 text-[15.5px] leading-relaxed text-[#38465A]"
                  >
                    <span
                      aria-hidden="true"
                      className="mt-[0.6em] h-[5px] w-[5px] shrink-0 rounded-full"
                      style={{ background: '#B08D2E' }}
                    />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>

              {/* ``font-serif`` on a heading is discarded by the
                  unlayered ``h1..h6`` rule in globals.css, but this is a
                  paragraph, so the utility applies. */}
              <p className="mt-10 max-w-[46ch] font-serif text-[16px] italic leading-relaxed text-[#4A5568]">
                I made this after moving my movement class, and later my
                online courses, into a home of their own. &mdash; Linds
              </p>
            </div>

            <div className="lg:pt-1">
              <div
                className="rounded-2xl bg-white p-6 sm:p-7"
                style={{
                  boxShadow:
                    '0 1px 2px rgba(15,30,55,0.04), 0 0 0 1px rgba(15,30,55,0.06)',
                }}
              >
                <h2
                  className="text-[20px] text-navy-900"
                  style={SERIF_HEADING}
                >
                  Send me the kit
                </h2>
                <div className="mt-4">
                  <MailerLiteStarterKitForm />
                </div>
              </div>
            </div>
          </div>
        </Container>
      </div>
    </SiteShell>
  )
}
