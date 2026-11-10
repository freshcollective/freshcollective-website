import ClosingInvitation from '@/components/marketing/ClosingInvitation'

/**
 * The invitation at the foot of a Guide.
 *
 * The homepage's ``ClosingInvitation``, with the Guide's copy — not a
 * second navy card that happens to look similar. This used to carry
 * its own styling and drifted from the homepage in every detail that
 * matters: no gold hairline, no teal glow, a flat navy surface and
 * plain pill buttons instead of the hero pair.
 *
 * No new prop was needed. ``ClosingInvitation`` already renders its
 * heading as an ``h2`` — which is what a Guide needs, since the
 * article title is the page's one ``h1`` — and ``buttonVariant="hero"``
 * is the teal-gradient primary with the white secondary that the
 * homepage uses.
 *
 * Kept as a component rather than inlined at the two call sites so
 * the copy has one home: the public article and the admin preview
 * must end the same way, or the preview stops being a preview.
 */
export default function GuideClosingBand() {
  return (
    <ClosingInvitation
      headingLines={['Ready to give your work a home?']}
      body="Set up your Collective in about 15 minutes. Start with who it's for and how it should feel."
      primaryCta={{ label: 'Start your Collective', href: '/for-creators#plans' }}
      secondaryCta={{ label: 'Take a look around', href: '/spaces' }}
      buttonVariant="hero"
    />
  )
}
