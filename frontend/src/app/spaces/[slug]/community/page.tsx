import { getCommunityFeed, getMemberChannels, getSpace, getSpaceMembers, getMe, type ChannelSummaryLite } from '@/lib/serverApi'
import CommunityFeed from '@/components/community/CommunityFeed'
import ChannelSelector from '@/components/community/ChannelSelector'
import ChannelHeader from '@/components/community/ChannelHeader'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { MemberProfile, PostSummary, SpaceResponse } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ channel?: string }>
}

export default async function SpaceCommunityPage({ params, searchParams }: Props) {
  const { slug } = await params
  const { channel: channelFromUrl } = await searchParams

  const [space, members, me, channels] = await Promise.all([
    getSpace(slug) as Promise<SpaceResponse | null>,
    getSpaceMembers(slug) as Promise<MemberProfile[]>,
    getMe() as Promise<{ id: string; role: string } | null>,
    getMemberChannels(slug),
  ])

  // Pick the active Channel from the URL, falling back to the
  // system Common Room (or the first accessible Channel if — impossibly —
  // Common Room is missing).
  const defaultChannel = channels.find((c) => c.is_default) ?? channels[0] ?? null
  const activeChannel: ChannelSummaryLite | null = channelFromUrl
    ? (channels.find((c) => c.slug === channelFromUrl) ?? defaultChannel)
    : defaultChannel
  const activeSlug = activeChannel?.slug ?? 'general'

  const posts: PostSummary[] = await getCommunityFeed(slug, activeSlug)

  const memberCount = members.filter((m) => m.space_role === 'learner').length
  const leaderCount = members.filter((m) => m.space_role === 'creator' || m.space_role === 'moderator').length

  const canModerate = !!(me && (
    me.role === 'admin' ||
    me.role === 'creator' ||
    members.some((m) => m.id === me.id && (m.space_role === 'creator' || m.space_role === 'moderator'))
  ))

  const memberNamesById: Record<string, string> = {}
  for (const m of members) memberNamesById[m.id] = m.display_name

  const channelArchived = !!activeChannel?.is_archived
  const canPost = !channelArchived && (activeChannel?.member_posting_allowed || canModerate)

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">

      {/* ── Left column: intro + channel selector + composer + feed ── */}
      <div className="min-w-0">

        {/* Intro card */}
        <div
          className="mb-5 overflow-hidden rounded-2xl px-7 py-7"
          style={{
            background: '#071824',
            border: '1px solid rgba(66,199,198,0.10)',
            boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
          }}
        >
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
          />
          <h2 className="mb-2 leading-snug">
            <span
              className="inline-block text-2xl font-semibold"
              style={{
                background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Conversations
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: '#FFFFFF' }}>
            Explore the places where conversations unfold across this collective.
          </p>
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
            This Channel has been archived. It remains readable but no new
            conversations can be started here.
          </div>
        )}

        <CommunityFeed
          key={activeSlug}
          spaceSlug={slug}
          channelSlug={activeSlug}
          posts={posts}
          memberNamesById={memberNamesById}
          canModerate={canModerate}
          canPin={canModerate}
          canEdit={canModerate}
          viewerId={me?.id}
          canCompose={canPost}
          showUnansweredFilter={canModerate}
        />
      </div>

      {/* ── Right column: banner + stats + Important panel (desktop only) ── */}
      <aside className="hidden lg:block">
        <div className="sticky top-6">
          <CollectiveSidebarPanel
            space={space}
            memberCount={memberCount}
            leaderCount={leaderCount}
          />
        </div>
      </aside>

    </div>
  )
}
