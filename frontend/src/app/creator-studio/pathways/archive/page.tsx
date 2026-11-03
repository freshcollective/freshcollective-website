import { getActiveCreatorSpace, getCreatorPathways, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorPathway, CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import PathwayArchiveClient from './PathwayArchiveClient'

/**
 * Creator Studio → Pathways → Archived Pathways.
 *
 * Its own route, matching the Gathering archive's arrangement, so the
 * main Pathways gallery holds only what a creator is offering or
 * building.
 *
 * The list endpoint returns every status and always has, so there is
 * no new fetch and no backend change — which is also why an archived
 * Pathway was never actually lost, only hard to find.
 */

export default async function PathwayArchivePage() {
  const activeSpace = await getActiveCreatorSpace()

  const [pathways, spaceDetail]: [CreatorPathway[], CreatorSpaceDetail | null] =
    activeSpace
      ? await Promise.all([
          getCreatorPathways(activeSpace.slug) as Promise<CreatorPathway[]>,
          getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
        ])
      : [[], null]

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {activeSpace ? (
        <CollectiveArtworkHeader
          collectiveName={activeSpace.name}
          sectionTitle="Archived Pathways"
          meta={
            <>
              Pathways you&rsquo;ve archived. Their content and history are
              preserved, and you can restore them whenever you&rsquo;re ready.
            </>
          }
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
        />
      ) : (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
            Archived Pathways
          </h1>
          <p className="mt-2 text-[15px] leading-relaxed text-black">
            Pathways you&rsquo;ve archived. Their content and history are
            preserved, and you can restore them whenever you&rsquo;re ready.
          </p>
        </div>
      )}

      <PathwayArchiveClient
        initialPathways={pathways}
        activeSpace={activeSpace}
        collectiveDetail={spaceDetail}
      />

    </div>
  )
}
