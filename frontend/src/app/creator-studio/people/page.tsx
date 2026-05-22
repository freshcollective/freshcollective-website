import Link from 'next/link'
import { getActiveCreatorSpace, getSpaceMembers, getCreatorInvitations } from '@/lib/serverApi'
import type { MemberProfile, SpaceInvitation } from '@/types/platform'
import PeopleClient from './PeopleClient'

export default async function CreatorPeoplePage() {
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">Select a collective first.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Choose a collective from the sidebar to see the people connected to it.
          </p>
          <Link
            href="/creator-studio"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Back to Studio Home
          </Link>
        </div>
      </div>
    )
  }

  // TODO: Replace with a creator-specific members endpoint once built.
  // The public /api/spaces/{slug}/members endpoint only returns active members
  // and does not include email addresses.
  const [members, invitations]: [MemberProfile[], SpaceInvitation[]] = await Promise.all([
    getSpaceMembers(activeSpace.slug),
    getCreatorInvitations(activeSpace.slug),
  ])

  return (
    <PeopleClient
      members={members}
      invitations={invitations}
      spaceName={activeSpace.name}
      spaceSlug={activeSpace.slug}
      spaceIsPublic={activeSpace.is_public}
    />
  )
}
