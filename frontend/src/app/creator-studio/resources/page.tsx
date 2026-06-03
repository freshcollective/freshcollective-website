import { getActiveCreatorSpace, getCreatorResources } from '@/lib/serverApi'
import type { CreatorResource } from '@/types/platform'
import ResourcesManager from './ResourcesManager'

export default async function ResourcesPage() {
  const space = await getActiveCreatorSpace()
  const resources: CreatorResource[] = space ? await getCreatorResources(space.slug) : []

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Resources</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Add links, files, guides, and tools that are visible to all members of your collective.
        </p>
      </div>

      {!space ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="text-[14px] leading-relaxed text-slate-500">
            Set up your collective first to start adding resources.
          </p>
        </div>
      ) : (
        <ResourcesManager spaceSlug={space.slug} initialResources={resources} />
      )}

    </div>
  )
}
