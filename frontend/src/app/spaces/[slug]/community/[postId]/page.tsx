import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getCommunityPost, getSpaceMembers, getMe } from '@/lib/serverApi'
import PostTypeTag from '@/components/community/PostTypeTag'
import ReactionBar from '@/components/community/ReactionBar'
import ModerationMenu from '@/components/community/ModerationMenu'
import CommunityImage from '@/components/community/CommunityImage'
import MentionText from '@/components/community/MentionText'
import PollView from '@/components/community/PollView'
import Avatar from '@/components/ui/Avatar'
import { resolveMediaUrl } from '@/lib/api'
import type { PostDetail } from '@/types/platform'
import RepliesClient from './RepliesClient'

interface Props {
  params: Promise<{ slug: string; postId: string }>
}

function formatDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' })
}

const URL_REGEX = /https?:\/\/[^\s<>"]+/g

function renderBodyWithLinks(text: string, mentionedNames: string[]) {
  return text.split('\n\n').filter(Boolean).map((para, i) => {
    // Split on links; segments in-between still pass through MentionText
    // so both link + mention detection compose without collision.
    const parts: React.ReactNode[] = []
    let lastIndex = 0
    let match: RegExpExecArray | null
    const re = new RegExp(URL_REGEX.source, 'g')
    while ((match = re.exec(para)) !== null) {
      if (match.index > lastIndex) {
        parts.push(
          <MentionText
            key={`t-${i}-${lastIndex}`}
            body={para.slice(lastIndex, match.index)}
            mentionedNames={mentionedNames}
          />
        )
      }
      parts.push(
        <a
          key={`a-${i}-${match.index}`}
          href={match[0]}
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:opacity-80"
          style={{ color: 'var(--fc-accent, #0f766e)' }}
        >
          {match[0]}
        </a>
      )
      lastIndex = match.index + match[0].length
    }
    if (lastIndex < para.length) {
      parts.push(
        <MentionText
          key={`t-${i}-tail`}
          body={para.slice(lastIndex)}
          mentionedNames={mentionedNames}
        />
      )
    }
    return (
      <p key={i} className="mb-3 text-[15px] leading-[1.8] text-black">
        {parts}
      </p>
    )
  })
}

interface MemberLite {
  id: string
  display_name: string
  space_role: string
}

export default async function PostDetailPage({ params }: Props) {
  const { slug, postId } = await params
  const [post, members, me]: [
    PostDetail | null,
    MemberLite[],
    { id: string; role: string } | null,
  ] = await Promise.all([
    getCommunityPost(slug, postId),
    getSpaceMembers(slug),
    getMe(),
  ])

  if (!post) notFound()

  const canModerate = !!(me && (
    me.role === 'admin' ||
    me.role === 'creator' ||
    members.some((m) => m.id === me.id && (m.space_role === 'creator' || m.space_role === 'moderator'))
  ))

  // Member name lookup for @mention chip rendering.
  const memberNamesById: Record<string, string> = {}
  for (const m of members) memberNamesById[m.id] = m.display_name

  const mentionedNames = (post.mentioned_user_ids ?? [])
    .map((id) => memberNamesById[id])
    .filter((n): n is string => !!n)

  return (
    <div className="max-w-2xl">

      {/* Back */}
      <Link
        href={`/spaces/${slug}/community`}
        className="mb-7 inline-block text-sm text-black hover:text-navy-700"
      >
        ← Conversations
      </Link>

      {/* Post header */}
      <div className="mb-6">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <PostTypeTag type={post.post_type} />
            {post.is_pinned && (
              <span className="text-xs text-black">Pinned</span>
            )}
          </div>
          {(canModerate || (!!me && me.id !== post.author.id)) && (
            <ModerationMenu
              spaceSlug={slug}
              postId={post.id}
              canRemove={canModerate}
              hideReport={!me || me.id === post.author.id}
            />
          )}
        </div>
        {post.title && (
          <h1 className="mb-4 font-serif text-3xl leading-snug text-navy-900">
            {post.title}
          </h1>
        )}
        <div className="flex items-center gap-3">
          <Avatar name={post.author.display_name} size="sm" />
          <div>
            <p className="text-sm font-medium text-navy-800">{post.author.display_name}</p>
            <p className="text-xs text-black">{formatDate(post.created_at)}</p>
          </div>
        </div>
      </div>

      {/* Post body */}
      {post.body && (
        <div className="mb-6">
          {/<[a-z][\s\S]*>/i.test(post.body) ? (
            <div
              dangerouslySetInnerHTML={{ __html: post.body }}
              className="prose-community text-[15px] leading-[1.8] text-black [&_p]:mb-3 [&_strong]:font-semibold [&_em]:italic [&_u]:underline"
            />
          ) : (
            renderBodyWithLinks(post.body, mentionedNames)
          )}
        </div>
      )}

      {/* Post image */}
      {post.image_url && (
        <CommunityImage
          src={resolveMediaUrl(post.image_url) ?? ''}
          alt="Post image"
          className="mb-6 w-full rounded-xl object-cover"
        />
      )}

      {/* Poll — first-class Community Phase 1 content */}
      {post.poll && (
        <div className="mb-6">
          <PollView spaceSlug={slug} postId={post.id} poll={post.poll} />
        </div>
      )}

      {/* Post reactions */}
      <div className="mb-10">
        <ReactionBar spaceSlug={slug} postId={post.id} initialReactions={post.reactions} />
      </div>

      {/* Replies + composer */}
      <div className="border-t border-border pt-8">
        <RepliesClient
          spaceSlug={slug}
          postId={postId}
          comments={post.comments}
          canModerate={canModerate}
          viewerId={me?.id}
          memberNamesById={memberNamesById}
        />
      </div>

    </div>
  )
}
