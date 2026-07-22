import Link from 'next/link'
import {
  getCommunityFeed,
  getMe,
  getMemberChannels,
  getSpace,
  getSpaceMembers,
  type ChannelSummaryLite,
} from '@/lib/serverApi'
import type { MemberProfile, PostSummary, SpaceResponse } from '@/types/platform'
import CommunityFeed from '@/components/community/CommunityFeed'
import ChannelSelector from '@/components/community/ChannelSelector'
import ChannelHeader from '@/components/community/ChannelHeader'

/**
 * Legacy creator route — kept as an alias so bookmarked links still
 * resolve. Same experience as `/creator-studio/community`, targeting
 * the collective named in the URL rather than the currently-selected
 * one from the cookie.
 */

interface Props {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ channel?: string }>
}

export default async function CreatorCommunityPage({ params, searchParams }: Props) {
  const { slug } = await params
  const { channel: channelFromUrl } = await searchParams

  const [channels, space, members, me]: [
    ChannelSummaryLite[],
    SpaceResponse | null,
    MemberProfile[],
    { id: string; role: string } | null,
  ] = await Promise.all([
    getMemberChannels(slug),
    getSpace(slug) as Promise<SpaceResponse | null>,
    getSpaceMembers(slug) as Promise<MemberProfile[]>,
    getMe() as Promise<{ id: string; role: string } | null>,
  ])

  const defaultChannel = channels.find((c) => c.is_default) ?? channels[0] ?? null
  const activeChannel: ChannelSummaryLite | null = channelFromUrl
    ? (channels.find((c) => c.slug === channelFromUrl) ?? defaultChannel)
    : defaultChannel
  const activeSlug = activeChannel?.slug ?? 'general'
  const channelArchived = !!activeChannel?.is_archived

  const posts: PostSummary[] = await (getCommunityFeed(slug, activeSlug) as Promise<PostSummary[]>)

  const memberNamesById: Record<string, string> = {}
  for (const m of members) memberNamesById[m.id] = m.display_name

  const isDraft = space?.status !== 'active'

  return (
    <div className="max-w-2xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">Conversations</h1>
        <p className="mt-1 text-sm text-black">
          Start conversations, respond to members and care for the people who gather here.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {isDraft ? (
            <span
              className="inline-flex items-center rounded-full px-4 py-2 text-[13px] font-medium"
              style={{
                background: 'rgba(212,176,72,0.14)',
                color: '#8A6A15',
                border: '1px solid rgba(212,176,72,0.35)',
              }}
            >
              Draft — no member view yet
            </span>
          ) : (
            <Link
              href={`/spaces/${slug}/community${activeSlug && activeSlug !== 'general' ? `?channel=${activeSlug}` : ''}`}
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
      </div>

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
        spaceSlug={slug}
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
    </div>
  )
}
