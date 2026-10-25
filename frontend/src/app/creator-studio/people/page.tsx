import { getActiveCreatorSpace, getCreatorMembers, getCreatorInvitations, getCreatorAccessRequests, getCreatorSpace, getManualMembers, getRemovedMembers } from '@/lib/serverApi'
import type { AccessRequest, CreatorMemberDetail, CreatorSpaceDetail, ManualMember, RemovedMember, SpaceInvitation } from '@/types/platform'
import PrimaryActionLink from '@/components/creator/PrimaryActionLink'
import { collectiveTimezone } from '@/lib/collectiveTimezone'
import PeopleClient from './PeopleClient'

export default async function CreatorPeoplePage() {
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">Select a collective first.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Choose a collective from My World to see the people connected to it.
          </p>
          <PrimaryActionLink href="/creator-studio" showIcon={false}>
            Go to My World
          </PrimaryActionLink>
        </div>
      </div>
    )
  }

  const [members, invitations, accessRequests, manualMembers, spaceDetail, removedMembers]: [
    CreatorMemberDetail[], SpaceInvitation[], AccessRequest[], ManualMember[], CreatorSpaceDetail | null, RemovedMember[],
  ] = await Promise.all([
    getCreatorMembers(activeSpace.slug),
    getCreatorInvitations(activeSpace.slug),
    getCreatorAccessRequests(activeSpace.slug),
    getManualMembers(activeSpace.slug),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
    getRemovedMembers(activeSpace.slug),
  ])

  return (
    <PeopleClient
      members={members}
      invitations={invitations}
      accessRequests={accessRequests}
      manualMembers={manualMembers}
      spaceName={activeSpace.name}
      spaceSlug={activeSpace.slug}
      spaceIsPublic={activeSpace.is_public}
      headerLocation={spaceDetail?.location ?? null}
      headerCoverImageUrl={spaceDetail?.cover_image_url ?? null}
      spaceTimezone={collectiveTimezone(spaceDetail)}
      removedMembers={removedMembers}
      // Blocking somebody from ever rejoining is the founder's
      // decision, so moderators never see the control. The server
      // refuses them regardless — this only avoids offering it.
      canBan={spaceDetail?.is_owner === true}
    />
  )
}
