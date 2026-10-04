import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import Container from '@/components/layout/Container'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import PeopleYouveCrossed from '@/components/connections/PeopleYouveCrossed'
import WaysToConnectEmptyState from '@/components/connections/WaysToConnectEmptyState'
import PeerThreadList from '@/components/messages/PeerThreadList'
import PeerConversationClient from '@/app/messages/[threadId]/PeerConversationClient'
import { viewerIsPlatformOwner } from '@/lib/platformOwner'
import { getPublicPlatformArtwork } from '@/lib/serverApi'
import {
  MAX_PREVIEW_CARDS,
  PREVIEW_SETS,
  previewSet,
  PREVIEW_VIEWER_ID,
  previewConversation,
  previewPersonRef,
  previewThreadSummaries,
  type ConversationState,
} from '@/lib/connectionPreviewFixtures'

export const metadata: Metadata = {
  title: 'Connection preview · internal',
  robots: { index: false, follow: false },
}

/** Never prerendered: the gate reads the session. */
export const dynamic = 'force-dynamic'

/**
 * Internal visual-QA harness for Ways to Connect and peer Messages.
 *
 * Why it exists: the production owner preview works, but Lindsey has no
 * genuinely eligible people yet, so both surfaces show their empty
 * states and the finished experience cannot be judged. This renders the
 * **real components** against code-only fixtures so the populated
 * experience can be reviewed without manufacturing production
 * relationships.
 *
 * Access is Platform Owner only, through the same canonical check the
 * rest of the product uses — not the URL being obscure, and not the
 * ``NODE_ENV`` guard the older ``/dev/onboarding-preview`` uses, which
 * would 404 here on production where this is needed. Everyone else,
 * signed in or not, gets the ordinary 404.
 *
 * Nothing is written and nothing is POSTed: every interactive
 * component is handed ``previewOnly``, which suppresses its network
 * calls. The fixtures live in code.
 *
 * State is in the query string rather than client state, so the harness
 * is a server component rendering the real server components directly —
 * no parallel client implementation to drift.
 */

type View = 'ways-to-connect' | 'messages' | 'conversation'

const VIEWS: { key: View; label: string }[] = [
  { key: 'ways-to-connect', label: 'Ways to Connect' },
  { key: 'messages', label: 'Messages' },
  { key: 'conversation', label: 'Conversation' },
]

const WTC_STATES = ['populated', 'empty'] as const
const CONVO_STATES: ConversationState[] = ['normal', 'blocked', 'report']

export default async function ConnectionPreviewPage({
  searchParams,
}: {
  searchParams: Promise<{
    view?: string
    state?: string
    convo?: string
    set?: string
    menu?: string
  }>
}) {
  if (!(await viewerIsPlatformOwner())) notFound()

  const params = await searchParams
  const view: View = VIEWS.some((v) => v.key === params.view)
    ? (params.view as View)
    : 'ways-to-connect'
  const wtcState = WTC_STATES.includes(params.state as (typeof WTC_STATES)[number])
    ? (params.state as (typeof WTC_STATES)[number])
    : 'populated'
  const convoState: ConversationState = CONVO_STATES.includes(
    params.convo as ConversationState,
  )
    ? (params.convo as ConversationState)
    : 'normal'

  // The real uploaded member-card artwork, so the monogram treatment
  // under review is the one members will actually see.
  const artwork = await getPublicPlatformArtwork().catch(() => [])
  const artworkByKey = new Map<string, string | null>(
    (artwork as { key: string; image_url: string | null }[]).map((a) => [
      a.key,
      a.image_url,
    ]),
  )

  // One fixture set at a time, never the whole cast: the product shows
  // at most three people, so a preview showing more would be reviewing
  // a page that cannot exist. Sliced as well as curated — the limit is
  // asserted here rather than trusted to the fixture data staying the
  // right length.
  const set = previewSet(params.set)
  const people = set.people
    .slice(0, MAX_PREVIEW_CARDS)
    .map((p) => previewPersonRef(p, artworkByKey))
  const threads = previewThreadSummaries(artworkByKey)
  const conversation = previewConversation(artworkByKey, convoState)

  // Opens the conversation menu on load, so the rows inside it can be
  // reviewed without a click — and so the blocked state can be checked
  // for the absence of Block rather than taken on trust. Independent of
  // ``convoState``, because it is worth seeing in more than one.
  const menuOpen = params.menu === 'open'

  const href = (next: Partial<Record<string, string>>) => {
    const q = new URLSearchParams({
      view,
      state: wtcState,
      convo: convoState,
      set: set.key,
      menu: menuOpen ? 'open' : 'closed',
      ...next,
    })
    return `/dev/connection-preview?${q.toString()}`
  }

  return (
    <SiteShell>
      <Banner />

      <Container>
        <div className="flex flex-col gap-3 py-5">
          <Control
            label="View"
            options={VIEWS.map((v) => ({
              label: v.label,
              href: href({ view: v.key }),
              active: view === v.key,
            }))}
          />
          {view === 'ways-to-connect' && (
            <Control
              label="Ways to Connect"
              options={WTC_STATES.map((s) => ({
                label: s === 'populated' ? 'Populated' : 'Empty',
                href: href({ state: s }),
                active: wtcState === s,
              }))}
            />
          )}
          {view === 'ways-to-connect' && wtcState === 'populated' && (
            <>
              <Control
                label="Fixture set"
                options={PREVIEW_SETS.map((s) => ({
                  label: s.label,
                  href: href({ set: s.key }),
                  active: set.key === s.key,
                }))}
              />
              {/* Preview-only. The real page has no set control and no
                  way to ask for a different three. */}
              <p className="text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
                {set.note} Three at a time, as the product shows them.
              </p>
            </>
          )}
          {view === 'conversation' && (
            <Control
              label="Options menu"
              options={[
                { label: 'Closed', href: href({ menu: 'closed' }), active: !menuOpen },
                { label: 'Open', href: href({ menu: 'open' }), active: menuOpen },
              ]}
            />
          )}
          {view === 'conversation' && (
            <Control
              label="Conversation"
              options={CONVO_STATES.map((s) => ({
                label: s === 'normal' ? 'Normal' : s === 'blocked' ? 'Blocked by me' : 'Report flow',
                href: href({ convo: s }),
                active: convoState === s,
              }))}
            />
          )}
        </div>
      </Container>

      {view === 'ways-to-connect' && (
        <>
          <PageHero
            title="Ways to Connect"
            supportingCopy="People you’ve genuinely crossed paths with."
          />
          {wtcState === 'populated' ? (
            <PeopleYouveCrossed
              people={people}
              previewOnly
              previewMessageHref="/dev/connection-preview?view=conversation"
            />
          ) : (
            <WaysToConnectEmptyState doorway={null} />
          )}
        </>
      )}

      {view === 'messages' && (
        <>
          <PageHero
            title="Messages"
            supportingCopy="Private conversations with people you’ve both said hello to."
          />
          <div className="mx-auto max-w-[680px] px-6 pb-24 pt-2 md:px-8">
            {/* Every row opens the one conversation fixture — the
                harness has a single thread, and the point is the
                journey rather than four different conversations. */}
            <PeerThreadList
              threads={threads}
              hrefFor={() => href({ view: 'conversation' })}
            />
          </div>
        </>
      )}

      {view === 'conversation' && (
        <div className="mx-auto max-w-[680px] px-6 pb-24 pt-8 md:px-8">
          <Link
            href={href({ view: 'messages' })}
            className="text-[13px] font-medium transition-opacity hover:opacity-70"
            style={{ color: '#2F8F8D' }}
          >
            ← All messages
          </Link>
          <PeerConversationClient
            initialThread={conversation}
            currentUserId={PREVIEW_VIEWER_ID}
            previewOnly
            previewOpen={
              convoState === 'report'
                ? 'report'
                : menuOpen
                  ? 'menu'
                  : undefined
            }
          />
          {convoState === 'normal' && (
            <p
              className="mt-6 text-[12.5px] italic"
              style={{ color: 'rgba(12,24,38,0.5)' }}
            >
              The ··· control in the header opens Block and Report.
            </p>
          )}
        </div>
      )}
    </SiteShell>
  )
}

function Banner() {
  return (
    <div style={{ background: '#0C1826' }}>
      <Container>
        <p
          className="py-2 text-[12px]"
          style={{ color: 'rgba(255,255,255,0.78)', letterSpacing: '0.02em' }}
        >
          Internal prototype — no data is saved.
        </p>
      </Container>
    </div>
  )
}

function Control({
  label,
  options,
}: {
  label: string
  options: { label: string; href: string; active: boolean }[]
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className="text-[11px] font-semibold uppercase tracking-[0.14em]"
        style={{ color: 'rgba(12,24,38,0.45)' }}
      >
        {label}
      </span>
      {options.map((o) => (
        <Link
          key={o.href}
          href={o.href}
          className="rounded-full px-3 py-1 text-[12.5px] font-medium transition-colors"
          style={
            o.active
              ? { background: '#0C1826', color: '#FFFFFF' }
              : {
                  background: '#FFFFFF',
                  color: '#0C1826',
                  border: '1px solid rgba(12,24,38,0.16)',
                }
          }
        >
          {o.label}
        </Link>
      ))}
    </div>
  )
}
