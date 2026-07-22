import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCommunityFeed,
  getMe,
  getMemberChannels,
  getSpaceMembers,
  type ChannelSummaryLite,
} from '@/lib/serverApi'
import type { MemberProfile, PostSummary, SpaceSummary } from '@/types/platform'
import CommunityFeed from '@/components/community/CommunityFeed'
import ChannelSelector from '@/components/community/ChannelSelector'
import ChannelHeader from '@/components/community/ChannelHeader'

/**
 * Creator Studio → Community
 *
 * The live Community experience, with caretaker controls layered on
 * top through props. Uses the same feed, composer, search, poll view,
 * mention rendering, and post cards as `/spaces/[slug]/community` —
 * this page's only job is to select the currently active collective
 * (via the `fc_creator_space` cookie honoured by getActiveCreatorSpace)
 * and pass `canModerate`/`canPin`/`canEdit`/`showUnansweredFilter`.
 */

interface Props {
  searchParams: Promise<{ channel?: string }>
}

export default async function CreatorStudioCommunityPage({ searchParams }: Props) {
  const { channel: channelFromUrl } = await searchParams
  const primarySpace: SpaceSummary | null = await getActiveCreatorSpace()

  const [channels, members, me]: [
    ChannelSummaryLite[],
    MemberProfile[],
    { id: string; role: string } | null,
  ] = primarySpace
    ? await Promise.all([
        getMemberChannels(primarySpace.slug),
        getSpaceMembers(primarySpace.slug) as Promise<MemberProfile[]>,
        getMe() as Promise<{ id: string; role: string } | null>,
      ])
    : [[], [], null]

  const defaultChannel = channels.find((c) => c.is_default) ?? channels[0] ?? null
  const activeChannel: ChannelSummaryLite | null = channelFromUrl
    ? (channels.find((c) => c.slug === channelFromUrl) ?? defaultChannel)
    : defaultChannel
  const activeSlug = activeChannel?.slug ?? 'general'
  const channelArchived = !!activeChannel?.is_archived

  const posts: PostSummary[] = primarySpace
    ? await (getCommunityFeed(primarySpace.slug, activeSlug) as Promise<PostSummary[]>)
    : []

  const memberNamesById: Record<string, string> = {}
  for (const m of members) memberNamesById[m.id] = m.display_name

  const isDraft = primarySpace?.status !== 'active'

  return (
    <div className="w-full max-w-[860px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Conversations</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-black">
          Start conversations, respond to members and care for the people who gather here.
        </p>
        {primarySpace && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {isDraft ? (
              <span
                className="inline-flex items-center rounded-full px-4 py-2 text-[13px] font-medium"
                style={{
                  background: 'rgba(212,176,72,0.14)',
                  color: '#8A6A15',
                  border: '1px solid rgba(212,176,72,0.35)',
                }}
                title="Draft collectives are not yet open to members. Publish this collective from Settings to enable the member-facing view."
              >
                Draft — no member view yet
              </span>
            ) : (
              <Link
                href={`/spaces/${primarySpace.slug}/community${activeSlug && activeSlug !== 'general' ? `?channel=${activeSlug}` : ''}`}
                className="inline-flex items-center rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
              >
                View as member →
              </Link>
            )}
            <Link
              href="/creator-studio/community/channels"
              className="inline-flex items-center rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
              style={{
                background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                color: 'var(--fc-accent, #0f766e)',
              }}
            >
              Manage Channels
            </Link>
          </div>
        )}
      </div>

      {!primarySpace ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first, then you can post prompts and start conversations.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      ) : (
        <>
          {channels.length > 0 && (
            <ChannelSelector
              channels={channels.map((c) => ({
                id: c.id, slug: c.slug, name: c.name,
                channel_type: c.channel_type, is_default: c.is_default,
                is_system: c.is_system, is_archived: c.is_archived,
                icon_emoji: c.icon_emoji, group_label: c.group_label,
              }))}
              activeSlug={activeSlug}
            />
          )}

          {activeChannel && (
            <ChannelHeader
              icon={activeChannel.icon_emoji}
              name={activeChannel.name}
              description={activeChannel.description}
              archived={channelArchived}
            />
          )}

          {channelArchived && (
            <div
              className="mb-4 rounded-2xl px-5 py-4 text-[13px]"
              style={{
                background: 'rgba(212,176,72,0.10)',
                border: '1px solid rgba(212,176,72,0.30)',
                color: '#8A6A15',
              }}
            >
              This Channel is archived. It remains readable but no new
              conversations can be started here until it is restored.
            </div>
          )}

          <CommunityFeed
            key={activeSlug}
            spaceSlug={primarySpace.slug}
            channelSlug={activeSlug}
            posts={posts}
            memberNamesById={memberNamesById}
            canModerate
            canPin
            canEdit
            viewerId={me?.id}
            showUnansweredFilter
            canSchedule
            isDraftCollective={isDraft}
            canCompose={!channelArchived}
          />
        </>
      )}

    </div>
  )
}
