import { getActiveCreatorSpace, getCreatorResources, getCreatorPathways, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorPathway, CreatorResource, CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import ResourcesManager from './ResourcesManager'

export default async function ResourcesPage() {
  const space = await getActiveCreatorSpace()
  const [resources, pathways, spaceDetail]: [CreatorResource[], CreatorPathway[], CreatorSpaceDetail | null] = space
    ? await Promise.all([
        getCreatorResources(space.slug),
        getCreatorPathways(space.slug),
        getCreatorSpace(space.slug) as Promise<CreatorSpaceDetail | null>,
      ])
    : [[], [], null]

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {space ? (
        <CollectiveArtworkHeader
          collectiveName={space.name}
          sectionTitle="Resources"
          meta="Standalone links, files, guides and tools for your members."
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
        />
      ) : (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Resources</h1>
        </div>
      )}

      {/* Pathway resources info — gold accent, matches member-facing pathway colour */}
      <div
        className="mb-6 flex items-start gap-3 rounded-2xl border px-5 py-4"
        style={{ borderColor: 'rgba(214,177,63,0.40)', background: 'rgba(226,193,79,0.07)' }}
      >
        <span className="mt-0.5 text-[15px]" style={{ color: '#D6B13F' }}>◫</span>
        <div>
          <p className="text-[13px] font-semibold" style={{ color: '#7A5A00' }}>Pathway resources</p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-black">
            Pathway resources appear automatically for members who have access to that pathway.
            Resources attached inside pathway steps are managed within each pathway.
          </p>
        </div>
      </div>

      {!space ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="text-[14px] leading-relaxed text-black">
            Set up your collective first to start adding resources.
          </p>
        </div>
      ) : (
        <ResourcesManager spaceSlug={space.slug} initialResources={resources} pathways={pathways} />
      )}

    </div>
  )
}
