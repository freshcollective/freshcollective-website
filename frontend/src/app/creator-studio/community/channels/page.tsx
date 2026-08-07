import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorChannels,
  getCreatorEvents,
  getCreatorPathways,
  getSpaceMembers,
  type ChannelManageDetail,
} from '@/lib/serverApi'
import type { CreatorEvent, CreatorPathway, MemberProfile, SpaceSummary } from '@/types/platform'
import ManageChannelsClient from './ManageChannelsClient'

/**
 * Creator Studio → Conversations → Channels
 *
 * Caretaker surface for the channels architecture. Lists every Channel
 * in the active collective (visible + archived), and lets caretakers
 * create Open / Private / Pathway-linked Channels, edit settings, and
 * archive or restore.
 *
 * Membership management for private Channels happens inline in the
 * client component via a compact picker.
 */

export default async function ManageChannelsPage() {
  const activeSpace: SpaceSummary | null = await getActiveCreatorSpace()

  const [channels, members, pathways, events]: [
    ChannelManageDetail[],
    MemberProfile[],
    CreatorPathway[],
    CreatorEvent[],
  ] = activeSpace
    ? await Promise.all([
        getCreatorChannels(activeSpace.slug),
        getSpaceMembers(activeSpace.slug) as Promise<MemberProfile[]>,
        getCreatorPathways(activeSpace.slug) as Promise<CreatorPathway[]>,
        getCreatorEvents(activeSpace.slug) as Promise<CreatorEvent[]>,
      ])
    : [[], [], [], []]

  return (
    <div className="w-full max-w-[980px] px-8 py-8 md:px-10 md:py-10">

      {/* Navigation crumb — sits above the section header so the primary
          action (Add a Channel) reads as the main call-to-action for this
          page. Kept understated so it doesn't compete with primary CTAs. */}
      <div className="mb-4">
        <Link
          href="/creator-studio/community"
          className="inline-flex items-center gap-1 text-[12.5px] font-medium text-black transition-colors hover:text-teal-700"
        >
          ← Back to Conversations
        </Link>
      </div>

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Conversations
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Channels</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-black">
          Shape distinct places for conversation within your collective.
          Create open places everyone can enjoy, private places for smaller
          circles, or Channels linked to Pathways and Gatherings so people
          arrive when they belong.
        </p>
      </div>

      {!activeSpace ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="text-[14px] leading-relaxed text-black">
            Create a collective first — Channels live inside it.
          </p>
        </div>
      ) : (
        <ManageChannelsClient
          spaceSlug={activeSpace.slug}
          initialChannels={channels}
          members={members}
          pathways={pathways}
          events={events}
        />
      )}
    </div>
  )
}
