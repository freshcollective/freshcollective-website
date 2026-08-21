import Container from '@/components/layout/Container'

const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.82)'
const WARM_GOLD = '#EDBE5D'

// Short white section between the hero and the friction section.
// Deliberately quiet — it exists to state the product in one sentence
// and then get out of the way. No card, no eyebrow, no coloured
// ground; the padding is tight because the friction section
// immediately below carries the next moment of visual weight.
export default function HomeWhatThisIs() {
  return (
    <section
      className="py-10 md:py-14"
      style={{ background: '#FFFFFF' }}
    >
      <Container>
        <div className="mx-auto max-w-[760px]">
          <h2
            className="font-serif leading-[1.08]"
            style={{
              fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
              letterSpacing: '-0.03em',
              color: NAVY,
            }}
          >
            Bring your business and your{' '}
            <span style={{ color: WARM_GOLD }}>people</span> together.
          </h2>

          <p
            className="mt-6 text-[17px] leading-[1.8]"
            style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
          >
            Fresh Collective gives your community one place to learn,
            gather, talk, access resources and pay for what you offer.
            Use it online, in person, or both. Your Collective is
            yours — but it also sits inside a wider world people can
            explore.
          </p>
        </div>
      </Container>
    </section>
  )
}
