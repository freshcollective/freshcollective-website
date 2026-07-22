import EventForm from '../EventForm'
import { getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'

export default async function NewEventPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const pathways: CreatorPathway[] = await getCreatorPathways(slug)
  return (
    <div className="max-w-xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">Create Gathering</h1>
      </div>
      <EventForm spaceSlug={slug} pathways={pathways} />
    </div>
  )
}
