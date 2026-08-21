import Container from '@/components/layout/Container'

const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'
const TEAL = '#38A09E'
// The homepage's one sanctioned use of warm gold outside the hero.
// Only applied to the emotional pivot word here ("alone.") — this
// section's promise is trust that a creator won't be dropped into a
// silent room. Sparse use is deliberate.
const WARM_GOLD = '#D4B048'

// The real screenshot is managed through World Artwork under the
// `homepage_world_builders` slot. The section falls back to an honest
// "Product screenshot pending" placeholder — never a stock or
// atmospheric image — until that slot is populated.

interface Props {
  artFor: (key: string) => string | null
}

export default function HomeWorldBuilders({ artFor }: Props) {
  const screenshotSrc = artFor('homepage_world_builders')
  return (
    <section className="py-14 md:py-16" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className="mx-auto grid max-w-[1160px] items-center gap-14 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.15fr)] md:gap-20">
          <div>
            <h2
              className="font-serif leading-[1.08]"
              style={{
                fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
                letterSpacing: '-0.03em',
                color: NAVY,
              }}
            >
              You don&rsquo;t need to build{' '}
              <span style={{ color: WARM_GOLD }}>alone.</span>
            </h2>
            <p
              className="mt-6 max-w-[480px] text-[15.5px] leading-relaxed"
              style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
            >
              Every creator has access to World Builders — a working
              Collective where you can experience Fresh Collective as a
              member, learn alongside other creators, get support and ask
              the questions that come with building a community.
            </p>
            <p
              className="mt-5 max-w-[480px] text-[15.5px] leading-relaxed"
              style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
            >
              It means the first Collective you spend time inside is one
              that&rsquo;s already alive — so you know what you&rsquo;re
              building toward, and you&rsquo;re not doing it in a room by
              yourself.
            </p>
          </div>

          <WorldBuildersScreenshot src={screenshotSrc} />
        </div>
      </Container>
    </section>
  )
}

function WorldBuildersScreenshot({ src }: { src: string | null }) {
  if (src) {
    return (
      <div
        className="relative w-full overflow-hidden rounded-2xl"
        style={{
          aspectRatio: '16 / 10',
          border: '1px solid rgba(12, 24, 38, 0.08)',
          boxShadow: '0 12px 40px rgba(12, 24, 38, 0.10)',
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt="World Builders — the working Collective every creator joins"
          className="absolute inset-0 h-full w-full object-cover object-top"
        />
      </div>
    )
  }
  return (
    <div
      aria-hidden="true"
      className="relative flex w-full items-center justify-center overflow-hidden rounded-2xl"
      style={{
        aspectRatio: '16 / 10',
        background:
          'linear-gradient(160deg, #F7F4EE 0%, #EFEBE1 55%, #E7E2D3 100%)',
        border: '1px dashed rgba(12, 24, 38, 0.14)',
        boxShadow: '0 12px 40px rgba(12, 24, 38, 0.10)',
      }}
    >
      <div className="flex flex-col items-center gap-2 px-8 text-center">
        <span
          className="text-[10.5px] font-semibold uppercase"
          style={{ color: TEAL, letterSpacing: '0.22em' }}
        >
          Product screenshot
        </span>
        <span
          className="text-[14px] italic"
          style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
        >
          World Builders — the Collective every creator joins
        </span>
      </div>
    </div>
  )
}
