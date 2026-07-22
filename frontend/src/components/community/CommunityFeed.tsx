'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import CommunitySearch from './CommunitySearch'
import CreatePostForm, { type CreatePostFormHandle } from './CreatePostForm'
import PostCard from './PostCard'
import ScheduledPostsList, { type ScheduledPost } from './ScheduledPostsList'
import CaretakerOverview from './CaretakerOverview'
import type { PostSummary } from '@/types/platform'

/**
 * CommunityFeed — one shared feed body used by both the member-facing
 * Conversations page and the Creator Studio's Conversations view.
 * Caretaker capabilities layer in via props; ordinary members never
 * see Queue / caretaker overview / scheduling controls.
 *
 * The tab set is view-only:
 *   - Live   → Search + composer + Start here + normal feed
 *   - Queue  → composer + timeline of scheduled conversations
 *
 * A compact "Care for your space" overview sits above the tabs when
 * caretaker context is active, with pills that switch tabs / activate
 * filters. Counts come entirely from data we've already fetched;
 * nothing is estimated.
 */

interface Props {
  spaceSlug: string
  /** Slug of the Channel currently in view. Posts and search scope to it. */
  channelSlug?: string
  posts: PostSummary[]
  memberNamesById: Record<string, string>
  canModerate?: boolean
  canPin?: boolean
  canEdit?: boolean
  /** Current viewer id — passed to each PostCard so the Community Care
   *  Report action can be shown for viewers who are not the author. */
  viewerId?: string | null
  showUnansweredFilter?: boolean
  /** Creator context — expose Queue tab + composer scheduling. */
  canSchedule?: boolean
  /** Draft collectives cannot receive scheduled conversations. */
  isDraftCollective?: boolean
  /** Hide the composer entirely when the Channel is archived or when
   *  member-posting is disabled by settings. Default true. */
  canCompose?: boolean
}

export default function CommunityFeed({
  spaceSlug,
  channelSlug,
  posts, memberNamesById,
  canModerate = false, canPin = false, canEdit = false,
  viewerId,
  showUnansweredFilter = false,
  canSchedule = false,
  isDraftCollective = false,
  canCompose = true,
}: Props) {
  const [onlyUnanswered, setOnlyUnanswered] = useState(false)
  const [tab, setTab] = useState<'live' | 'queue'>('live')
  const [queueDateFilter, setQueueDateFilter] = useState<'all' | 'today'>('all')
  const [scheduled, setScheduled] = useState<ScheduledPost[] | null>(null)
  const composerRef = useRef<CreatePostFormHandle>(null)

  // Load scheduled posts once for caretakers so the overview counts and
  // the Queue timeline share a single source. The Queue timeline calls
  // back with fresh data whenever it mutates (publish/reschedule/delete).
  useEffect(() => {
    if (!canSchedule) return
    let cancelled = false
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/community/scheduled`), {
      credentials: 'include',
    })
      .then(async (res) => (res.ok ? ((await res.json()) as ScheduledPost[]) : []))
      .then((data) => { if (!cancelled) setScheduled(data) })
      .catch(() => { if (!cancelled) setScheduled([]) })
    return () => { cancelled = true }
  }, [canSchedule, spaceSlug])

  const unansweredCount = useMemo(
    () => posts.filter((p) => p.post_type === 'question' && p.comment_count === 0).length,
    [posts],
  )

  const scheduledCount = scheduled?.length ?? 0
  const publishingTodayCount = useMemo(() => {
    if (!scheduled) return 0
    const start = new Date(); start.setHours(0, 0, 0, 0)
    const end = new Date(); end.setHours(23, 59, 59, 999)
    return scheduled.filter((p) => {
      if (!p.scheduled_for) return false
      const t = Date.parse(p.scheduled_for)
      return Number.isFinite(t) && t >= start.getTime() && t <= end.getTime()
    }).length
  }, [scheduled])

  const visible = onlyUnanswered
    ? posts.filter((p) => p.post_type === 'question' && p.comment_count === 0)
    : posts

  const pinned = visible.filter((p) => p.is_pinned)
  const feed = visible.filter((p) => !p.is_pinned)

  const focusComposer = useCallback(() => {
    composerRef.current?.openComposer()
  }, [])

  return (
    <>
      {canSchedule && (
        <CaretakerOverview
          unansweredCount={showUnansweredFilter ? unansweredCount : 0}
          scheduledCount={scheduledCount}
          publishingTodayCount={publishingTodayCount}
          onOpenUnanswered={() => { setTab('live'); setOnlyUnanswered(true) }}
          onOpenQueue={() => { setTab('queue'); setQueueDateFilter('all') }}
          onOpenPublishingToday={() => { setTab('queue'); setQueueDateFilter('today') }}
        />
      )}

      {canSchedule && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
            View
          </p>
          <TabChip active={tab === 'live'} onClick={() => setTab('live')}>Live</TabChip>
          <TabChip active={tab === 'queue'} onClick={() => setTab('queue')}>
            {scheduledCount > 0 ? `Queue · ${scheduledCount}` : 'Queue'}
          </TabChip>
        </div>
      )}

      {tab === 'live' ? (
        <>
          <CommunitySearch spaceSlug={spaceSlug} channelSlug={channelSlug} />

          {showUnansweredFilter && unansweredCount > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                Care
              </p>
              <button
                type="button"
                onClick={() => setOnlyUnanswered((v) => !v)}
                className="rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
                style={onlyUnanswered
                  ? { background: 'var(--fc-accent, #0d9488)', color: '#FFFFFF' }
                  : {
                      background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                      color: 'var(--fc-accent, #0f766e)',
                    }}
              >
                Unanswered questions · {unansweredCount}
              </button>
              {onlyUnanswered && (
                <button
                  type="button"
                  onClick={() => setOnlyUnanswered(false)}
                  className="text-[12px] text-slate-500 hover:text-slate-700"
                >
                  Show all
                </button>
              )}
            </div>
          )}

          {canCompose && (
            <div className="mb-6">
              <CreatePostForm
                ref={composerRef}
                spaceSlug={spaceSlug}
                channelSlug={channelSlug}
                canPin={canPin}
                canSchedule={canSchedule}
                isDraftCollective={isDraftCollective}
              />
            </div>
          )}

          {pinned.length > 0 && (
            <section className="mb-5">
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                Start here
              </p>
              <div className="flex flex-col gap-3">
                {pinned.map((p) => (
                  <PostCard
                    key={p.id}
                    post={p}
                    spaceSlug={spaceSlug}
                    canModerate={canModerate}
                    canPin={canPin}
                    canEdit={canEdit}
                    viewerId={viewerId}
                    memberNamesById={memberNamesById}
                  />
                ))}
              </div>
            </section>
          )}

          {feed.length > 0 ? (
            <section>
              {pinned.length > 0 && (
                <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                  Recent
                </p>
              )}
              <div className="flex flex-col gap-3">
                {feed.map((p) => (
                  <PostCard
                    key={p.id}
                    post={p}
                    spaceSlug={spaceSlug}
                    canModerate={canModerate}
                    canPin={canPin}
                    canEdit={canEdit}
                    viewerId={viewerId}
                    memberNamesById={memberNamesById}
                  />
                ))}
              </div>
            </section>
          ) : (
            !pinned.length && (
              <div
                className="rounded-2xl bg-white px-7 py-10 text-center"
                style={{ border: '1px solid rgba(0,0,0,0.07)' }}
              >
                <p className="mb-2 font-serif text-xl text-navy-800">
                  {onlyUnanswered
                    ? 'No unanswered questions right now.'
                    : 'The conversation begins with you.'}
                </p>
                <p className="mx-auto max-w-sm text-[13px] leading-relaxed text-black">
                  {onlyUnanswered
                    ? 'When someone asks a Question, it will surface here until it receives its first reply.'
                    : 'Share what you are noticing, ask what you are sitting with, or respond when something touches you.'}
                </p>
              </div>
            )
          )}
        </>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="mb-1">
            <CreatePostForm
              ref={composerRef}
              spaceSlug={spaceSlug}
              channelSlug={channelSlug}
              canPin={canPin}
              canSchedule={canSchedule}
              isDraftCollective={isDraftCollective}
            />
          </div>
          <ScheduledPostsList
            spaceSlug={spaceSlug}
            items={scheduled}
            dateFilter={queueDateFilter}
            onClearDateFilter={() => setQueueDateFilter('all')}
            onItemsChanged={setScheduled}
            onStartConversation={focusComposer}
          />
        </div>
      )}
    </>
  )
}

function TabChip({ active, onClick, children }: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
      style={active
        ? { background: 'var(--fc-accent, #0d9488)', color: '#FFFFFF' }
        : {
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
            color: 'var(--fc-accent, #0f766e)',
          }}
    >
      {children}
    </button>
  )
}
