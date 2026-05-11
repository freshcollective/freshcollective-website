import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import { getPublicSpaces } from '@/lib/serverApi'
import SpacesClient, { type DisplaySpace } from './SpacesClient'
import type { PublicSpaceCard } from '@/types/platform'

// ---------------------------------------------------------------------------
// Static metadata for known spaces (category, accent colour, flagship flag)
// ---------------------------------------------------------------------------

const SPACE_META: Record<string, Pick<DisplaySpace, 'category' | 'accentColor' | 'isFlagship'>> = {
  'fresh-collective': { category: 'Inner Work', accentColor: '#38A09E', isFlagship: true },
}

function getDefaultMeta(slug: string): Pick<DisplaySpace, 'category' | 'accentColor' | 'isFlagship'> {
  return SPACE_META[slug] ?? { category: 'Inner Work', accentColor: '#38A09E', isFlagship: false }
}

function toDisplaySpace(card: PublicSpaceCard): DisplaySpace {
  const meta = getDefaultMeta(card.slug)
  return { ...card, ...meta, isReal: true }
}

// ---------------------------------------------------------------------------
// Seeded example spaces (fictional, for editorial richness)
// ---------------------------------------------------------------------------

const SEEDED_SPACES: DisplaySpace[] = [
  {
    id: 'seed-body',
    slug: 'the-body-in-motion',
    name: 'The Body in Motion',
    tagline: 'A somatic practice for reconnecting with your body',
    description: 'Guided movement, breathwork, and body literacy for women who have been living from the neck up. A slow, grounded return to physical intelligence.',
    pathway_count: 3,
    member_count: 24,
    creator_name: 'Mara Lindqvist',
    has_upcoming_event: true,
    category: 'Wellbeing',
    accentColor: '#4A8E6E',
    isReal: false,
    isFlagship: false,
  },
  {
    id: 'seed-letters',
    slug: 'letters-to-myself',
    name: 'Letters to Myself',
    tagline: 'A reflective journaling practice for the long game',
    description: 'Structured prompts and guided inquiry for people who want to understand themselves better — slowly, carefully, over time.',
    pathway_count: 2,
    member_count: 31,
    creator_name: 'Caitlin Marsh',
    has_upcoming_event: false,
    category: 'Reflection',
    accentColor: '#B8922A',
    isReal: false,
    isFlagship: false,
  },
  {
    id: 'seed-thread',
    slug: 'the-creative-thread',
    name: 'The Creative Thread',
    tagline: 'For makers, writers, and visual artists finding their practice',
    description: 'A structured space for creative people building a sustainable, meaningful practice. Pathways through craft, resistance, and creative identity.',
    pathway_count: 4,
    member_count: 52,
    creator_name: 'Priya Mehta',
    has_upcoming_event: true,
    category: 'Creativity',
    accentColor: '#C06B3A',
    isReal: false,
    isFlagship: false,
  },
  {
    id: 'seed-company',
    slug: 'in-good-company',
    name: 'In Good Company',
    tagline: 'Leadership and community for people building something that matters',
    description: 'A space for founders, leaders, and community builders who want to lead with more clarity, less ego, and better judgment.',
    pathway_count: 3,
    member_count: 19,
    creator_name: 'James Osei',
    has_upcoming_event: false,
    category: 'Leadership',
    accentColor: '#3A5C8E',
    isReal: false,
    isFlagship: false,
  },
  {
    id: 'seed-still',
    slug: 'still-moving',
    name: 'Still / Moving',
    tagline: 'Contemplative practice for an accelerated world',
    description: 'Meditation, stillness, and reflective inquiry for people who sense that slowing down is not optional — it is the work itself.',
    pathway_count: 2,
    member_count: 38,
    creator_name: 'Yuki Tanaka',
    has_upcoming_event: false,
    category: 'Reflection',
    accentColor: '#7E6E9A',
    isReal: false,
    isFlagship: false,
  },
]

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function SpacesPage() {
  const apiSpaces = await getPublicSpaces()

  const realSpaces = apiSpaces.map(toDisplaySpace)
  const realSlugs = new Set(realSpaces.map((s) => s.slug))

  // Merge: real spaces first, then seeds that don't duplicate a real slug
  const allSpaces: DisplaySpace[] = [
    ...realSpaces,
    ...SEEDED_SPACES.filter((s) => !realSlugs.has(s.slug)),
  ]

  // Ensure flagship appears first
  allSpaces.sort((a, b) => {
    if (a.isFlagship) return -1
    if (b.isFlagship) return 1
    return 0
  })

  return (
    <SiteShell>

      {/* Hero */}
      <section className="relative overflow-hidden pb-0 pt-16 sm:pt-24" style={{ background: '#FAFAF8' }}>
        {/* Grid */}
        <div
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
          style={{
            backgroundImage:
              'linear-gradient(rgba(12,24,38,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(12,24,38,0.025) 1px, transparent 1px)',
            backgroundSize: '56px 56px',
          }}
        />
        {/* Glows */}
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          <div style={{
            position: 'absolute', top: '-30%', right: '-5%',
            width: '700px', height: '700px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(56,160,158,0.08) 0%, transparent 60%)',
            filter: 'blur(70px)',
          }} />
          <div style={{
            position: 'absolute', bottom: '-20%', left: '-5%',
            width: '500px', height: '500px', borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(201,168,60,0.05) 0%, transparent 60%)',
            filter: 'blur(80px)',
          }} />
        </div>

        <Container className="relative">
          <div className="max-w-[620px] pb-12 sm:pb-16">

            <div className="mb-5 flex items-center gap-3">
              <div className="h-px w-8 bg-teal-400" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-600">
                Learning spaces
              </span>
            </div>

            <h1
              className="mb-6 text-navy-950"
              style={{
                fontSize: 'clamp(2.5rem, 5vw, 4.25rem)',
                lineHeight: '1.06',
                letterSpacing: '-0.045em',
                fontWeight: 660,
              }}
            >
              Explore spaces.
            </h1>

            <p className="text-[16px] leading-[1.82] text-navy-500" style={{ maxWidth: '500px' }}>
              Each space is a creator-led learning environment — structured pathways,
              live events, and community built into one intentional place.
              Browse and find the one that fits where you are.
            </p>

          </div>
        </Container>
      </section>

      {/* Filter + Grid (client) */}
      <SpacesClient spaces={allSpaces} />

    </SiteShell>
  )
}
