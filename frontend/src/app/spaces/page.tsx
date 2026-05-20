import SiteShell from '@/components/layout/SiteShell'
import { getPublicSpaces } from '@/lib/serverApi'
import ExploreCollectivesExperience from '@/components/explore/ExploreCollectivesExperience'
import { toSpaceWithMeta, type SpaceWithMeta } from '@/components/explore/spaceMeta'
import type { PublicSpaceCard } from '@/types/platform'

// ---------------------------------------------------------------------------
// Demo collectives — shown when there are no real collectives in a category.
// TODO: Remove these once the platform has enough real published collectives
//       to make the Explore page feel full without seeded content.
// ---------------------------------------------------------------------------

const SEEDED_SPACES: SpaceWithMeta[] = [
  {
    id: 'seed-body',
    slug: 'the-body-in-motion',
    name: 'The Body in Motion',
    tagline: 'A somatic practice for reconnecting with your body',
    description:
      'Guided movement, breathwork, and body literacy for women who have been living from the neck up. A slow, grounded return to physical intelligence.',
    cover_image_url: null,
    is_public: true,
    pathway_count: 3,
    member_count: 24,
    creator_name: 'Mara Lindqvist',
    has_upcoming_event: true,
    category: 'Wellbeing',
    accentColor: '#4A8E6E',
    isReal: false,
  },
  {
    id: 'seed-letters',
    slug: 'letters-to-myself',
    name: 'Letters to Myself',
    tagline: 'A reflective journaling practice for the long game',
    description:
      'Structured prompts and guided inquiry for people who want to understand themselves better — slowly, carefully, over time.',
    cover_image_url: null,
    is_public: true,
    pathway_count: 2,
    member_count: 31,
    creator_name: 'Caitlin Marsh',
    has_upcoming_event: false,
    category: 'Reflection',
    accentColor: '#B8922A',
    isReal: false,
  },
  {
    id: 'seed-thread',
    slug: 'the-creative-thread',
    name: 'The Creative Thread',
    tagline: 'For makers, writers, and visual artists finding their practice',
    description:
      'A structured space for creative people building a sustainable, meaningful practice. Pathways through craft, resistance, and creative identity.',
    cover_image_url: null,
    is_public: true,
    pathway_count: 4,
    member_count: 52,
    creator_name: 'Priya Mehta',
    has_upcoming_event: true,
    category: 'Creativity',
    accentColor: '#C06B3A',
    isReal: false,
  },
  {
    id: 'seed-company',
    slug: 'in-good-company',
    name: 'In Good Company',
    tagline: 'Leadership and community for people building something that matters',
    description:
      'A space for founders, leaders, and community builders who want to lead with more clarity, less ego, and better judgment.',
    cover_image_url: null,
    is_public: true,
    pathway_count: 3,
    member_count: 19,
    creator_name: 'James Osei',
    has_upcoming_event: false,
    category: 'Leadership',
    accentColor: '#3A5C8E',
    isReal: false,
  },
  {
    id: 'seed-still',
    slug: 'still-moving',
    name: 'Still / Moving',
    tagline: 'Contemplative practice for an accelerated world',
    description:
      'Meditation, stillness, and reflective inquiry for people who sense that slowing down is not optional — it is the work itself.',
    cover_image_url: null,
    is_public: true,
    pathway_count: 2,
    member_count: 38,
    creator_name: 'Yuki Tanaka',
    has_upcoming_event: false,
    category: 'Reflection',
    accentColor: '#7E6E9A',
    isReal: false,
  },
]

export default async function SpacesPage() {
  const apiSpaces: PublicSpaceCard[] = await getPublicSpaces()

  const realSpaces = apiSpaces.map(toSpaceWithMeta)
  const realSlugs = new Set(realSpaces.map((s) => s.slug))

  const allSpaces: SpaceWithMeta[] = [
    ...realSpaces,
    ...SEEDED_SPACES.filter((s) => !realSlugs.has(s.slug)),
  ]

  return (
    <SiteShell>
      <ExploreCollectivesExperience spaces={allSpaces} />
    </SiteShell>
  )
}
