import Container from '@/components/layout/Container'

const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.82)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'
const TEAL_DEEP = '#246B6A'
const WARM_GOLD = '#D4B048'

interface Props {
  /** URL for the section image. Managed via the World Artwork
   *  `homepage_friction_conversation` slot; when empty, an honest
   *  placeholder frame renders so the layout is preserved. */
  imageSrc: string | null
}

// White ground, split editorial: image on the left, friction copy on
// the right. Sits after the teal product-definition band so the page
// reads: warm hero → teal chapter opening → white problem story.
export default function HomeFriction({ imageSrc }: Props) {
  return (
    <section className="py-14 md:py-20" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className="mx-auto grid max-w-[1160px] items-center gap-10 md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] md:gap-16">
          <FrictionImage src={imageSrc} />

          <div>
            <h2
              className="font-serif leading-[1.1]"
              style={{
                fontSize: 'clamp(1.75rem, 4vw, 2.5rem)',
                letterSpacing: '-0.03em',
                color: NAVY,
              }}
            >
              Maybe{' '}
              <span style={{ color: TEAL_DEEP }}>you&rsquo;ve</span>{' '}
              tried a platform before. Or maybe this is your first
              attempt.
            </h2>

            <p
              className="mt-6 text-[15.5px] leading-[1.85]"
              style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
            >
              If you&rsquo;ve tried a platform before, you know how it
              usually goes. You set it up, you brought clients in, ran a
              program, and then{' '}
              <span style={{ color: TEAL_DEEP, fontWeight: 500 }}>
                it went quiet.
              </span>{' '}
              You were the one keeping the conversation alive, prompting
              and posting, wondering why the people who were so connected
              in your sessions stopped connecting afterwards.
            </p>

            <p
              className="mt-5 text-[15.5px] leading-[1.85]"
              style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
            >
              Or maybe you&rsquo;ve never had a place online at all.
              Your people come together in person but then{' '}
              <span style={{ color: TEAL_DEEP, fontWeight: 500 }}>
                they scatter
              </span>
              , because there was nowhere for them to be together in
              between.
            </p>

            <p
              className="mt-5 text-[15.5px] leading-[1.85]"
              style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
            >
              Either way it&rsquo;s the same problem, and it isn&rsquo;t
              due to a shortage of engagement tools. The challenge is
              that people rarely open up in a room full of strangers.
              They open up when something{' '}
              <span style={{ color: WARM_GOLD, fontWeight: 500 }}>
                feels familiar.
              </span>
            </p>
          </div>
        </div>
      </Container>
    </section>
  )
}

function FrictionImage({ src }: { src: string | null }) {
  if (src) {
    return (
      <div
        className="relative w-full overflow-hidden rounded-2xl"
        style={{
          aspectRatio: '4 / 5',
          boxShadow:
            '0 24px 60px rgba(12, 24, 38, 0.14),' +
            '0 6px 20px rgba(12, 24, 38, 0.08)',
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt=""
          aria-hidden="true"
          className="absolute inset-0 h-full w-full object-cover object-center"
        />
      </div>
    )
  }
  // Honest placeholder — no invented artwork; identifies the slot so a
  // reviewer knows exactly where the real image will land.
  return (
    <div
      aria-hidden="true"
      className="relative flex w-full items-center justify-center overflow-hidden rounded-2xl"
      style={{
        aspectRatio: '4 / 5',
        background:
          'linear-gradient(160deg, #F7F4EE 0%, #EFEBE1 55%, #E7E2D3 100%)',
        border: '1px dashed rgba(12, 24, 38, 0.14)',
      }}
    >
      <div className="flex flex-col items-center gap-2 px-8 text-center">
        <span
          className="text-[10.5px] font-semibold uppercase"
          style={{ color: INK_SOFT, letterSpacing: '0.22em' }}
        >
          World Artwork slot
        </span>
        <span
          className="text-[13px] italic"
          style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
        >
          homepage_friction_conversation
        </span>
        <span
          className="text-[12px]"
          style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
        >
          Upload an editorial image of genuine human conversation.
        </span>
      </div>
    </div>
  )
}
