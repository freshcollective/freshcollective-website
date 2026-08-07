import { getActiveCreatorSpace, getCreatorPasses, getCreatorSpace } from '@/lib/serverApi'
import type { AccessPassAdminSummary, CreatorSpaceDetail } from '@/types/platform'
import PrimaryActionLink from '@/components/creator/PrimaryActionLink'
import PassesClient from './PassesClient'

export default async function CreatorPassesPage() {
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">Select a collective first.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Choose a collective from My World to see member passes.
          </p>
          <PrimaryActionLink href="/creator-studio" showIcon={false}>
            Go to My World
          </PrimaryActionLink>
        </div>
      </div>
    )
  }

  const [passes, spaceDetail]: [AccessPassAdminSummary[], CreatorSpaceDetail | null] = await Promise.all([
    getCreatorPasses(activeSpace.slug),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
  ])

  return (
    <PassesClient
      passes={passes}
      spaceName={activeSpace.name}
      spaceSlug={activeSpace.slug}
      headerLocation={spaceDetail?.location ?? null}
      headerCoverImageUrl={spaceDetail?.cover_image_url ?? null}
    />
  )
}
