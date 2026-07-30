'use client'

/**
 * PROTOTYPE — Ways to Connect
 * ============================================================
 *
 * TEMPORARY. Delete this whole `_prototype` folder when the real
 * Ways to Connect surface ships. See ../page.tsx for the mount
 * point and ./mockIntroductions.ts for the fixture.
 *
 * This is not a social network, a directory or a recommendation
 * feed. It is a thoughtful host quietly introducing two members
 * who already share meaningful common ground. The page never
 * shows more than three introductions and never manufactures one
 * to fill space.
 *
 * State is local to this component: enabling / disabling Open
 * to Connections, dismissing an introduction, sending an
 * introduction request, or accepting an incoming request all
 * live in useState here. In production these become real backend
 * calls into the introduction recommendation service (see the
 * TODO markers inline).
 */

import { useState } from 'react'
import {
  INCOMING_INTRODUCTION,
  OUTGOING_INTRODUCTIONS,
  SHARED_ICON,
  type MockIntroduction,
  type SharedItem,
} from './mockIntroductions'


type CardStatus = 'idle' | 'sent' | 'dismissed'
type View = 'introductions' | 'conversation'

interface ConversationState {
  intro: MockIntroduction
  banner: string | null   // small transient message from the ••• menu
}


export default function WaysToConnectPrototype() {
  const [openToConnections, setOpenToConnections] = useState(true)
  const [outgoingStatus, setOutgoingStatus]       = useState<Record<string, CardStatus>>({})
  const [incomingHandled, setIncomingHandled]     = useState(false)
  const [view, setView]                           = useState<View>('introductions')
  const [conversation, setConversation]           = useState<ConversationState | null>(null)

  function markOutgoing(id: string, status: CardStatus) {
    setOutgoingStatus((prev) => ({ ...prev, [id]: status }))
  }

  function acceptIncoming() {
    setIncomingHandled(true)
    setConversation({ intro: INCOMING_INTRODUCTION, banner: null })
    setView('conversation')
  }

  function declineIncoming() {
    setIncomingHandled(true)
  }

  function closeConversation() {
    setView('introductions')
    setConversation(null)
  }

  // Currently-visible outgoing candidates. Dismissed cards drop out;
  // sent cards remain visible in a quiet "sent" state.
  const visibleOutgoing = OUTGOING_INTRODUCTIONS
    .filter((i) => outgoingStatus[i.id] !== 'dismissed')

  if (view === 'conversation' && conversation) {
    return (
      <ConversationView
        conversation={conversation}
        setBanner={(msg) => setConversation({ ...conversation, banner: msg })}
        onClose={closeConversation}
      />
    )
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-6 pb-24 pt-10 md:px-10 md:pt-14">
      {/* ── Open to Connections status band ─────────────────────
          In production this setting lives in /settings/preferences
          (a member preference), but for the prototype the toggle
          sits at the top of the page so the demo can show both
          on and off states. TODO(settings): move canonical control
          to /settings/preferences and read via /api/auth/me. */}
      <OpenToConnectionsBand
        enabled={openToConnections}
        onToggle={() => setOpenToConnections((v) => !v)}
      />

      {/* Content below only renders when the member is opted-in.
          When disabled we show only the status band — no matches,
          no invitations to enable. */}
      {openToConnections && (
        <>
          {/* Incoming introduction request — one mock item so the
              demo shows what receiving an introduction feels like. */}
          {!incomingHandled && (
            <IncomingRequestCard
              intro={INCOMING_INTRODUCTION}
              onAccept={acceptIncoming}
              onDecline={declineIncoming}
            />
          )}

          {/* Outgoing candidates. TODO(rec-engine): replace the
              mock fixture with a call to the introduction
              recommendation service. It returns up to three
              candidates covering the three intent types
              (right-now, shared-journey, thoughtful). */}
          <section aria-label="Introductions" className="mt-10">
            <div className="mb-6 max-w-2xl">
              <h2 className="font-serif text-[22px] leading-tight text-navy-900 md:text-[24px]">
                Introductions
              </h2>
              <p className="mt-1.5 text-[13.5px] italic leading-relaxed"
                style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}>
                A few members who already share meaningful common
                ground with you.
              </p>
            </div>

            {visibleOutgoing.length === 0 ? (
              <EmptyIntroductions />
            ) : (
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
                {visibleOutgoing.map((intro) => (
                  <IntroductionCard
                    key={intro.id}
                    intro={intro}
                    status={outgoingStatus[intro.id] ?? 'idle'}
                    onIntroduce={() => markOutgoing(intro.id, 'sent')}
                    onDismiss={() => markOutgoing(intro.id, 'dismissed')}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Open to Connections — status band with a live toggle.
// ---------------------------------------------------------------------------

function OpenToConnectionsBand({
  enabled, onToggle,
}: {
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <section
      aria-label="Open to Connections"
      className="rounded-2xl border p-5 md:p-6"
      style={{
        borderColor: enabled ? 'rgba(56,160,158,0.25)' : 'rgba(12,24,38,0.08)',
        background: enabled ? 'rgba(56,160,158,0.04)' : '#FFFFFF',
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: enabled ? '#38A09E' : 'rgba(12,24,38,0.45)' }}>
            {enabled ? 'Open to Connections' : 'Connections are paused'}
          </p>
          <p className="mt-2 text-[14px] leading-relaxed text-navy-700">
            {enabled ? (
              <>
                Allow Fresh Collective to introduce you to members
                who already share meaningful things in common with
                you. You may be introduced to them, and you may
                appear on their Ways to Connect page.
              </>
            ) : (
              <>
                You won&rsquo;t appear on anyone else&rsquo;s Ways
                to Connect page, and no introductions will appear
                here. Enable to be introduced only where genuine
                shared experience already exists.
              </>
            )}
          </p>
        </div>

        <button
          type="button"
          onClick={onToggle}
          aria-pressed={enabled}
          className={
            'shrink-0 rounded-full px-4 py-2 text-[13px] font-semibold transition-colors ' +
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ' +
            (enabled
              ? 'border border-teal-500/40 bg-white text-teal-700 hover:bg-teal-500/10'
              : 'text-white hover:opacity-90')
          }
          style={
            enabled
              ? {}
              : {
                  background:
                    'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  letterSpacing: '0.04em',
                }
          }
        >
          {enabled ? 'Turn off' : 'Turn on'}
        </button>
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Incoming request — the "someone would like an introduction" affordance.
// ---------------------------------------------------------------------------

function IncomingRequestCard({
  intro, onAccept, onDecline,
}: {
  intro: MockIntroduction
  onAccept: () => void
  onDecline: () => void
}) {
  return (
    <section
      aria-label={`Introduction request from ${intro.otherName}`}
      className="mt-8 rounded-2xl border p-6"
      style={{
        borderColor: 'rgba(56,160,158,0.30)',
        background: '#FFFFFF',
        boxShadow: '0 6px 20px rgba(12,24,38,0.05)',
      }}
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-navy-500">
        Introduction request
      </p>
      <h3 className="mt-2 font-serif text-[20px] leading-tight text-navy-900">
        {intro.otherName} would like an introduction
      </h3>
      <p className="mt-3 text-[13.5px] italic leading-relaxed"
        style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
        You already share:
      </p>
      <SharedItemList items={intro.sharedItems} className="mt-2" />

      <div className="mt-6 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onAccept}
          className="rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            letterSpacing: '0.04em',
          }}
        >
          Accept
        </button>
        <button
          type="button"
          onClick={onDecline}
          className="rounded-full border border-slate-200 bg-white px-5 py-2 text-[13px] font-medium text-navy-600 transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
        >
          Not now
        </button>
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Introduction card (outgoing candidate).
// ---------------------------------------------------------------------------

function IntroductionCard({
  intro, status, onIntroduce, onDismiss,
}: {
  intro: MockIntroduction
  status: CardStatus
  onIntroduce: () => void
  onDismiss: () => void
}) {
  return (
    <article
      aria-labelledby={`intro-${intro.id}-name`}
      className="flex flex-col rounded-2xl border border-slate-200 bg-white p-6 transition-shadow hover:shadow-[0_8px_24px_rgba(12,24,38,0.06)]"
    >
      <h3 id={`intro-${intro.id}-name`}
        className="font-serif text-[20px] leading-tight text-navy-900">
        {intro.otherName}
      </h3>

      <p className="mt-3 text-[13px] font-medium uppercase tracking-[0.08em] text-navy-500">
        You both share
      </p>
      <SharedItemList items={intro.sharedItems} className="mt-2 flex-1" />

      {status === 'idle' && (
        <div className="mt-6 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onIntroduce}
            className="rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
            style={{
              background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
              letterSpacing: '0.04em',
            }}
          >
            Introduce Me
          </button>
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-500 transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
          >
            Not Right Now
          </button>
        </div>
      )}

      {status === 'sent' && (
        <p
          className="mt-6 rounded-xl px-4 py-3 text-[13px] italic leading-relaxed"
          style={{
            background: 'rgba(56,160,158,0.06)',
            color: '#1E6E6C',
            fontFamily: 'Georgia, serif',
          }}
          aria-live="polite"
        >
          Introduction request sent. {intro.otherName} will see it
          next time they open Ways to Connect.
        </p>
      )}
    </article>
  )
}


// ---------------------------------------------------------------------------
// Shared-item list — simple bullet dots on cards, semantic emojis
// in the conversation intro panel. `variant='panel'` opts in.
// ---------------------------------------------------------------------------

function SharedItemList({
  items, className, variant = 'card',
}: {
  items: SharedItem[]
  className?: string
  variant?: 'card' | 'panel'
}) {
  return (
    <ul className={['space-y-1', className].filter(Boolean).join(' ')}>
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-[14px] leading-snug text-navy-700">
          {variant === 'panel' ? (
            <span aria-hidden="true" className="w-4 shrink-0 text-center">
              {SHARED_ICON[item.kind]}
            </span>
          ) : (
            <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full"
              style={{ background: 'rgba(12,24,38,0.35)' }} />
          )}
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  )
}


// ---------------------------------------------------------------------------
// Empty state — no introductions available right now.
// ---------------------------------------------------------------------------

function EmptyIntroductions() {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center">
      <p className="max-w-md mx-auto font-serif text-[16px] italic leading-relaxed"
        style={{ color: 'rgba(12,24,38,0.65)' }}>
        No introductions right now.
      </p>
      <p className="mx-auto mt-3 max-w-md text-[13.5px] leading-relaxed text-navy-500">
        Fresh Collective only introduces people who already share
        meaningful common ground. When that emerges, an
        introduction will quietly appear here.
      </p>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Conversation view — mock private conversation with the permanent
// introduction panel at the top and the ••• menu (Mute / End /
// Report). Presented inline within the page for the prototype; in
// production this opens as a normal private message thread with
// the intro panel pinned above the messages.
// ---------------------------------------------------------------------------

function ConversationView({
  conversation, setBanner, onClose,
}: {
  conversation: ConversationState
  setBanner: (msg: string | null) => void
  onClose: () => void
}) {
  const { intro, banner } = conversation
  const [menuOpen, setMenuOpen] = useState(false)

  function selectMenu(action: 'mute' | 'end' | 'report') {
    setMenuOpen(false)
    if (action === 'mute') {
      setBanner("You've muted this introduction. You won't be notified of new messages.")
      return
    }
    if (action === 'end') {
      // Quietly closes the conversation. The other person is not
      // notified — this is the normal way to end an introduction.
      onClose()
      return
    }
    if (action === 'report') {
      setBanner('Reported to Fresh Collective. Someone from Community Care will be in touch.')
      return
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 pb-24 pt-10 md:px-10 md:pt-14">
      <button
        type="button"
        onClick={onClose}
        className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-navy-500 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded"
      >
        ← Back to Ways to Connect
      </button>

      {/* Permanent introduction panel at the top of the
          conversation. Reads as "here's why we're here" and stays
          for the life of the conversation so members returning
          later still see the shared context. */}
      <section
        aria-label="Introduction context"
        className="rounded-2xl border p-6 md:p-7"
        style={{
          borderColor: 'rgba(56,160,158,0.22)',
          background:
            'linear-gradient(135deg, rgba(56,160,158,0.06), rgba(85,184,182,0.04))',
        }}
      >
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}>
          Welcome
        </p>
        <p className="mt-2 text-[14px] leading-relaxed text-navy-700">
          Fresh Collective introduced you because you already share:
        </p>
        <SharedItemList items={intro.sharedItems} variant="panel" className="mt-3" />
        <p className="mt-4 text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
          This is simply an opportunity to get to know one another.
        </p>
      </section>

      {/* Conversation area — placeholder in the prototype. In
          production this is the real private message thread
          between the two members. */}
      <section
        aria-label={`Conversation with ${intro.otherName}`}
        className="mt-6 rounded-2xl border border-slate-200 bg-white"
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <div>
            <p className="font-serif text-[16px] text-navy-900">
              {intro.otherName}
            </p>
            <p className="text-[12px] text-navy-500">
              Private conversation
            </p>
          </div>

          <ConversationMenu
            open={menuOpen}
            onToggle={() => setMenuOpen((v) => !v)}
            onSelect={selectMenu}
          />
        </header>

        {banner && (
          <div
            aria-live="polite"
            className="border-b border-slate-100 px-5 py-3 text-[13px]"
            style={{ background: 'rgba(56,160,158,0.05)', color: '#1E6E6C' }}
          >
            {banner}
          </div>
        )}

        <div className="min-h-[240px] px-5 py-16 text-center">
          <p className="text-[13.5px] italic leading-relaxed"
            style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
            The conversation belongs to the two of you from here.
            {' '}
            No prompts, no ice-breakers.
          </p>
          {/* TODO(messaging): mount the real private conversation
              thread component once introductions integrate with
              the platform's messaging surface. */}
        </div>
      </section>
    </div>
  )
}


function ConversationMenu({
  open, onToggle, onSelect,
}: {
  open: boolean
  onToggle: () => void
  onSelect: (action: 'mute' | 'end' | 'report') => void
}) {
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        aria-label="Conversation options"
        aria-expanded={open}
        className="flex h-8 w-8 items-center justify-center rounded-full text-navy-500 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
      >
        <span aria-hidden="true" className="text-[18px] leading-none">•••</span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-9 z-10 min-w-[180px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg"
        >
          <MenuItem onClick={() => onSelect('mute')}>Mute</MenuItem>
          <MenuItem onClick={() => onSelect('end')}>End introduction</MenuItem>
          <MenuItem onClick={() => onSelect('report')} danger>Report concern</MenuItem>
        </div>
      )}
    </div>
  )
}

function MenuItem({
  children, onClick, danger,
}: {
  children: React.ReactNode
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={
        'block w-full px-4 py-2.5 text-left text-[13.5px] transition-colors ' +
        'focus-visible:outline-none focus-visible:bg-slate-50 ' +
        (danger
          ? 'text-[#A64526] hover:bg-red-50'
          : 'text-navy-700 hover:bg-slate-50')
      }
    >
      {children}
    </button>
  )
}
