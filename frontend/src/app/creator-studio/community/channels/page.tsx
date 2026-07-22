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
          Create open places everyone can enjoy, private spaces for smaller
          circles, or Channels linked to Pathways and Gatherings so people
          arrive when they belong.
        </p>
        <div className="mt-4">
          <Link
            href="/creator-studio/community"
            className="inline-flex items-center rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
            style={{
              background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
              color: 'var(--fc-accent, #0f766e)',
            }}
          >
            ← Back to Conversations
          </Link>
        </div>
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
