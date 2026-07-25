import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorPathways, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorPathway, CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import PathwaysClient from './PathwaysClient'

export default async function PathwaysPage() {
  const activeSpace = await getActiveCreatorSpace()

  const [pathways, spaceDetail]: [CreatorPathway[], CreatorSpaceDetail | null] = activeSpace
    ? await Promise.all([
        getCreatorPathways(activeSpace.slug),
        getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
      ])
    : [[], null]

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {activeSpace && (
        <CollectiveArtworkHeader
          collectiveName={activeSpace.name}
          sectionTitle="Pathways"
          meta={<>Create guided journeys people can move through over time.</>}
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
          action={
            <Link
              href="/creator-studio/pathways/new"
              className="inline-flex items-center rounded-full px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                letterSpacing: '0.06em',
              }}
            >
              + Create pathway
            </Link>
          }
        />
      )}

      {!activeSpace && (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Pathways</h1>
          <p className="mt-2 text-[15px] leading-relaxed text-black">
            Create guided journeys people can move through over time.
          </p>
        </div>
      )}

      <PathwaysClient initialPathways={pathways} activeSpace={activeSpace} />

    </div>
  )
}
