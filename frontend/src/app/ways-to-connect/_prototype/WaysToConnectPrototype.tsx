'use client'

/**
 * PROTOTYPE — Ways to Connect (visual refinement pass)
 * ============================================================
 *
 * TEMPORARY. Delete this whole `_prototype` folder when the real
 * Ways to Connect surface ships. See ../page.tsx for the mount
 * point and ./mockIntroductions.ts for the fixture.
 *
 * Ways to Connect is a thoughtful host quietly introducing three
 * members who already share meaningful common ground. Never more
 * than three. Never manufactured to fill space. Never a
 * directory, never a feed, never scored.
 *
 * This iteration foregrounds the *people*: each card leads with
 * a portrait sitting in a warm atmospheric wash, then names the
 * person, then explains why they've been introduced in one
 * natural sentence, then offers the action. The internal intent
 * types (right-now / shared-journey / thoughtful) become quiet
 * human eyebrows; they never appear as system labels.
 */

import { useState } from 'react'
import {
  INCOMING_INTRODUCTION,
  INTENT_FRAMING,
  OUTGOING_INTRODUCTIONS,
  SHARED_ICON,
  type IntentType,
  type MockIntroduction,
  type SharedItem,
} from './mockIntroductions'


type CardStatus = 'idle' | 'sent' | 'dismissed'
type View = 'introductions' | 'conversation'

interface ConversationState {
  intro: MockIntroduction
  banner: string | null
}


// ---------------------------------------------------------------------------
// Portrait palette per intent — three warm human atmospheres so
// the three cards feel deliberately different without becoming
// categorised badges. All within one editorial family.
// ---------------------------------------------------------------------------

interface Portrait {
  /** Card-scale washed background behind the portrait area. */
  wash:    string
  /** Portrait circle fill (subtle deeper tone of the wash). */
  circle:  string
  /** Ink colour for the portrait initials. */
  ink:     string
  /** Ambient tint for the whole card background — very soft. */
  cardBg:  string
  /** Border colour when the card is at rest. */
  cardBorder: string
}

const PORTRAIT_BY_INTENT: Record<IntentType, Portrait> = {
  // Timely — warm apricot / peach, brighter for immediacy.
  'right-now': {
    wash:       'radial-gradient(ellipse at 50% 55%, rgba(243,196,168,0.55), rgba(214,144,110,0.35) 70%, transparent 100%)',
    circle:     'linear-gradient(150deg, #F3C4A8 0%, #D6906E 100%)',
    ink:        '#7C3F1E',
    cardBg:     'rgba(243, 196, 168, 0.08)',
    cardBorder: 'rgba(214, 144, 110, 0.20)',
  },
  // Accumulated — sage / eucalyptus, grounded and slow.
  'shared-journey': {
    wash:       'radial-gradient(ellipse at 50% 55%, rgba(180,217,184,0.50), rgba(123,178,135,0.32) 70%, transparent 100%)',
    circle:     'linear-gradient(150deg, #C6DEC0 0%, #7BB287 100%)',
    ink:        '#2E4B34',
    cardBg:     'rgba(180, 217, 184, 0.08)',
    cardBorder: 'rgba(123, 178, 135, 0.22)',
  },
  // Curated — lavender / soft violet, considered and quiet.
  'thoughtful': {
    wash:       'radial-gradient(ellipse at 50% 55%, rgba(198,165,204,0.50), rgba(138,110,151,0.32) 70%, transparent 100%)',
    circle:     'linear-gradient(150deg, #D4C1DA 0%, #A78BB4 100%)',
    ink:        '#4B2E5A',
    cardBg:     'rgba(198, 165, 204, 0.09)',
    cardBorder: 'rgba(138, 110, 151, 0.22)',
  },
}


// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

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

  function closeConversation() {
    setView('introductions')
    setConversation(null)
  }

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
    <div className="mx-auto w-full max-w-5xl px-6 pb-24 pt-8 md:px-10 md:pt-10">
      {/* Compact preference strip — a reassuring status, not a
          prompt. Full explanation lives behind a small disclosure
          via "Manage". TODO(settings): move canonical control to
          /settings/preferences. */}
      <OpenToConnectionsStrip
        enabled={openToConnections}
        onToggle={() => setOpenToConnections((v) => !v)}
      />

      {openToConnections && !incomingHandled && (
        <IncomingInvitation
          intro={INCOMING_INTRODUCTION}
          onAccept={acceptIncoming}
          onDecline={() => setIncomingHandled(true)}
        />
      )}

      {openToConnections ? (
        <section aria-label="Introductions" className="mt-12">
          <header className="mb-8 max-w-xl">
            <h2 className="font-serif text-[24px] leading-tight text-navy-900 md:text-[28px]">
              People you may enjoy meeting
            </h2>
            <p
              className="mt-2 text-[14.5px] italic leading-relaxed"
              style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
            >
              Three thoughtful introductions, grounded in what you
              already share.
            </p>
          </header>

          {visibleOutgoing.length === 0 ? (
            <EmptyIntroductions />
          ) : (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
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
      ) : (
        <PausedState onEnable={() => setOpenToConnections(true)} />
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Open to Connections — compact reassuring strip.
// ---------------------------------------------------------------------------

function OpenToConnectionsStrip({
  enabled, onToggle,
}: {
  enabled: boolean
  onToggle: () => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <section
      aria-label="Open to Connections"
      className="rounded-xl border px-4 py-3 md:px-5"
      style={{
        borderColor: enabled ? 'rgba(56,160,158,0.22)' : 'rgba(12,24,38,0.10)',
        background: enabled ? 'rgba(56,160,158,0.04)' : '#FFFFFF',
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 shrink-0 rounded-full"
            style={{ background: enabled ? '#38A09E' : 'rgba(12,24,38,0.35)' }}
          />
          <p className="text-[13.5px]" style={{ color: 'rgba(12,24,38,0.75)' }}>
            <span className="font-medium text-navy-900">
              {enabled ? 'Open to Connections' : 'Connections are paused'}
            </span>
            <span className="mx-2 text-navy-300">·</span>
            <span className="italic" style={{ fontFamily: 'Georgia, serif' }}>
              {enabled
                ? "You're open to thoughtful introductions based on meaningful shared experiences."
                : "You won't appear in anyone else's introductions, and none will appear here."}
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="shrink-0 text-[13px] font-medium text-navy-500 underline underline-offset-2 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded"
        >
          Manage
        </button>
      </div>

      {expanded && (
        <div className="mt-3 border-t pt-3" style={{ borderColor: 'rgba(12,24,38,0.06)' }}>
          <p className="mb-3 text-[13px] leading-relaxed text-navy-700">
            {enabled
              ? "You may be introduced to members with genuine shared experiences, and you may appear on their Ways to Connect page. Introductions never happen without both of you being open to them."
              : "Enable to be introduced only where genuine shared experience already exists. You can turn this off again at any time."}
          </p>
          <button
            type="button"
            onClick={onToggle}
            className="text-[13px] font-medium text-navy-500 underline underline-offset-2 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded"
          >
            {enabled ? 'Turn off Open to Connections' : 'Turn on Open to Connections'}
          </button>
        </div>
      )}
    </section>
  )
}


// ---------------------------------------------------------------------------
// Paused state — visible only when Open to Connections is off.
// ---------------------------------------------------------------------------

function PausedState({ onEnable }: { onEnable: () => void }) {
  return (
    <section className="mt-16">
      <div className="mx-auto max-w-lg text-center">
        <p
          className="font-serif text-[20px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.68)' }}
        >
          Connections are paused.
        </p>
        <p className="mt-3 text-[14px] leading-relaxed text-navy-500">
          Enable Open to Connections and Fresh Collective will
          introduce you to a small number of members you already
          share meaningful common ground with.
        </p>
        <button
          type="button"
          onClick={onEnable}
          className="mt-6 rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            letterSpacing: '0.04em',
          }}
        >
          Turn on Open to Connections
        </button>
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Incoming invitation — warm portrait invitation, not a form.
// ---------------------------------------------------------------------------

function IncomingInvitation({
  intro, onAccept, onDecline,
}: {
  intro: MockIntroduction
  onAccept: () => void
  onDecline: () => void
}) {
  const portrait = PORTRAIT_BY_INTENT[intro.intent]

  return (
    <section
      aria-label={`Introduction request from ${intro.otherName}`}
      className="mt-8 overflow-hidden rounded-2xl border md:flex md:items-center md:gap-6 md:pl-6"
      style={{
        borderColor: portrait.cardBorder,
        background: `linear-gradient(135deg, ${portrait.cardBg}, rgba(255,255,255,0.4))`,
      }}
    >
      <div
        className="relative flex h-40 items-center justify-center md:h-44 md:w-40 md:shrink-0 md:rounded-2xl"
        style={{ background: portrait.wash }}
      >
        <PortraitCircle name={intro.otherName} portrait={portrait} size={104} />
      </div>

      <div className="flex-1 px-6 py-6 md:pl-0 md:pr-8 md:py-8">
        <p
          className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: 'rgba(12,24,38,0.55)' }}
        >
          Invitation
        </p>
        <h3 className="font-serif text-[22px] leading-tight text-navy-900 md:text-[24px]">
          {intro.otherName} would like an introduction
        </h3>
        <p
          className="mt-3 max-w-lg text-[14.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.72)', fontFamily: 'Georgia, serif' }}
        >
          {intro.reasonSentence}
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onAccept}
            className="rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
            style={{
              background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
              letterSpacing: '0.04em',
            }}
          >
            Accept introduction
          </button>
          <button
            type="button"
            onClick={onDecline}
            className="rounded-full px-4 py-2 text-[13px] font-medium text-navy-500 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
          >
            Not now
          </button>
        </div>
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Introduction card — portrait-led editorial composition.
// ---------------------------------------------------------------------------

function IntroductionCard({
  intro, status, onIntroduce, onDismiss,
}: {
  intro: MockIntroduction
  status: CardStatus
  onIntroduce: () => void
  onDismiss: () => void
}) {
  const portrait = PORTRAIT_BY_INTENT[intro.intent]
  const eyebrow  = INTENT_FRAMING[intro.intent]
  const chips    = intro.sharedItems.slice(0, 3)

  return (
    <article
      aria-labelledby={`intro-${intro.id}-name`}
      className="flex flex-col overflow-hidden rounded-2xl border transition-shadow hover:shadow-[0_10px_28px_rgba(12,24,38,0.08)]"
      style={{
        borderColor: portrait.cardBorder,
        background: `linear-gradient(180deg, ${portrait.cardBg} 0%, rgba(255,255,255,1) 55%)`,
      }}
    >
      {/* Portrait area — the human being leads. */}
      <div
        className="relative flex h-40 items-center justify-center"
        style={{ background: portrait.wash }}
      >
        <PortraitCircle name={intro.otherName} portrait={portrait} size={96} />
      </div>

      {/* Body */}
      <div className="flex flex-1 flex-col px-6 pb-6 pt-5">
        <p
          className="text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: 'rgba(12,24,38,0.55)' }}
        >
          {eyebrow}
        </p>
        <h3
          id={`intro-${intro.id}-name`}
          className="mt-1 font-serif text-[22px] leading-tight text-navy-900"
        >
          {intro.otherName}
        </h3>
        <p
          className="mt-3 text-[14px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.68)', fontFamily: 'Georgia, serif' }}
        >
          {intro.reasonSentence}
        </p>

        {chips.length > 0 && (
          <ul className="mt-4 flex flex-wrap gap-1.5">
            {chips.map((chip, i) => (
              <li
                key={i}
                className="inline-flex items-center gap-1 rounded-full bg-white/80 px-2.5 py-1 text-[11.5px] font-medium text-navy-700"
                style={{ border: `1px solid ${portrait.cardBorder}` }}
              >
                <span aria-hidden="true" className="text-[10px]" style={{ color: portrait.ink }}>
                  {SHARED_ICON[chip.kind]}
                </span>
                <span>{chip.label}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Actions anchored at the bottom of the card. */}
        <div className="mt-6 flex flex-1 items-end">
          {status === 'idle' && (
            <div className="flex w-full items-center justify-between gap-3">
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
                className="text-[13px] text-navy-500 underline underline-offset-2 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded"
              >
                Not right now
              </button>
            </div>
          )}

          {status === 'sent' && (
            <p
              aria-live="polite"
              className="rounded-xl px-4 py-3 text-[13px] italic leading-relaxed"
              style={{
                background: 'rgba(56,160,158,0.08)',
                color: '#1E6E6C',
                fontFamily: 'Georgia, serif',
              }}
            >
              Introduction sent. {intro.otherName} will see it next
              time they open Ways to Connect.
            </p>
          )}
        </div>
      </div>
    </article>
  )
}


// ---------------------------------------------------------------------------
// Portrait circle — polished avatar placeholder in a warm palette.
// Not a photo, not a utility circle; serif initial on a warm
// gradient with a white outer ring. Ready to swap for a real
// profile photo later without changing card geometry.
// ---------------------------------------------------------------------------

function PortraitCircle({
  name, portrait, size,
}: {
  name: string
  portrait: Portrait
  size: number
}) {
  const initial = name.trim().charAt(0).toUpperCase() || '?'
  return (
    <div
      className="rounded-full bg-white shadow-[0_6px_18px_rgba(12,24,38,0.15)]"
      style={{ padding: 4, width: size + 8, height: size + 8 }}
      aria-hidden="true"
    >
      <div
        className="flex items-center justify-center rounded-full"
        style={{
          width: size,
          height: size,
          background: portrait.circle,
          color: portrait.ink,
          fontFamily: 'Georgia, serif',
          fontSize: Math.round(size * 0.42),
          lineHeight: 1,
        }}
      >
        {initial}
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Empty state — no introductions available.
// ---------------------------------------------------------------------------

function EmptyIntroductions() {
  return (
    <div
      className="rounded-2xl border px-6 py-10 text-center"
      style={{ borderColor: 'rgba(12,24,38,0.08)', background: 'rgba(56,160,158,0.03)' }}
    >
      <p
        className="mx-auto max-w-md font-serif text-[17px] italic leading-relaxed"
        style={{ color: 'rgba(12,24,38,0.68)' }}
      >
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
// introduction panel and the ••• menu. Unchanged in behaviour;
// portrait treatment added at the top so the reader sees who
// they're conversing with.
// ---------------------------------------------------------------------------

function ConversationView({
  conversation, setBanner, onClose,
}: {
  conversation: ConversationState
  setBanner: (msg: string | null) => void
  onClose: () => void
}) {
  const { intro, banner } = conversation
  const portrait = PORTRAIT_BY_INTENT[intro.intent]
  const [menuOpen, setMenuOpen] = useState(false)

  function selectMenu(action: 'mute' | 'end' | 'report') {
    setMenuOpen(false)
    if (action === 'mute') {
      setBanner("You've muted this introduction. You won't be notified of new messages.")
      return
    }
    if (action === 'end') {
      onClose()
      return
    }
    if (action === 'report') {
      setBanner('Reported to Fresh Collective. Someone from Community Care will be in touch.')
      return
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 pb-24 pt-8 md:px-10 md:pt-10">
      <button
        type="button"
        onClick={onClose}
        className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-navy-500 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded"
      >
        ← Back to Ways to Connect
      </button>

      {/* Permanent introduction panel — the shared context that
          stays visible for the life of the conversation. */}
      <section
        aria-label="Introduction context"
        className="overflow-hidden rounded-2xl border"
        style={{
          borderColor: portrait.cardBorder,
          background: `linear-gradient(135deg, ${portrait.cardBg}, rgba(255,255,255,0.5))`,
        }}
      >
        <div
          className="flex items-center gap-5 px-6 py-6 md:px-8"
          style={{ background: portrait.wash }}
        >
          <PortraitCircle name={intro.otherName} portrait={portrait} size={72} />
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
              Welcome
            </p>
            <h2 className="mt-1 font-serif text-[22px] leading-tight text-navy-900">
              You and {intro.otherName}
            </h2>
          </div>
        </div>
        <div className="px-6 py-5 md:px-8">
          <p className="text-[14px] leading-relaxed text-navy-700">
            Fresh Collective introduced you because you already
            share:
          </p>
          <SharedItemList items={intro.sharedItems} className="mt-3" />
          <p
            className="mt-4 text-[13.5px] italic leading-relaxed"
            style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}
          >
            This is simply an opportunity to get to know one another.
          </p>
        </div>
      </section>

      {/* Conversation area — placeholder for the prototype. */}
      <section
        aria-label={`Conversation with ${intro.otherName}`}
        className="mt-6 rounded-2xl border border-slate-200 bg-white"
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <div>
            <p className="font-serif text-[16px] text-navy-900">
              {intro.otherName}
            </p>
            <p className="text-[12px] text-navy-500">Private conversation</p>
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
          <p
            className="text-[13.5px] italic leading-relaxed"
            style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}
          >
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


// ---------------------------------------------------------------------------
// Shared-item list — used only in the conversation intro panel now.
// Bullet-list variant on cards was replaced by chips + reason
// sentence per the visual refinement pass.
// ---------------------------------------------------------------------------

function SharedItemList({
  items, className,
}: {
  items: SharedItem[]
  className?: string
}) {
  return (
    <ul className={['space-y-1.5', className].filter(Boolean).join(' ')}>
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-[14px] leading-snug text-navy-700">
          <span aria-hidden="true" className="w-4 shrink-0 text-center">
            {SHARED_ICON[item.kind]}
          </span>
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  )
}
