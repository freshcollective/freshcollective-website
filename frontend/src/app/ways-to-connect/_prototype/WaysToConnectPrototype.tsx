'use client'

/**
 * PROTOTYPE — Ways to Connect (unified four-card grid)
 * ============================================================
 *
 * TEMPORARY. Delete this whole `_prototype` folder when the real
 * Ways to Connect surface ships. See ../page.tsx for the mount
 * point and ./mockIntroductions.ts for the fixture.
 *
 * The page is fundamentally about meeting people. Every card
 * follows the same geometry:
 *
 *   1. Square (1:1) visual area — the member's profile photo
 *      when visible, otherwise a warm-neutral polished initial.
 *      No shared-Collective / Place artwork here; the person
 *      is the visual.
 *   2. Person's name — primary heading (font-serif 20px).
 *   3. Reason sentence — italic Georgia serif natural language
 *      explaining the shared common ground.
 *   4. Actions area — Say hello (suggestions) or Accept / Not now
 *      (incoming invitation). The incoming invitation is marked
 *      by a small teal "Invitation" eyebrow above the name and
 *      lives in the same grid, first slot.
 *
 * Grid: 4 columns on wide desktop, 2 on tablet, 1 on mobile.
 *
 * The `ConversationView` placeholder is unchanged pending a
 * separate messaging-surface integration and still uses the
 * legacy intent-based portrait treatment.
 */

import { useState } from 'react'
import {
  INCOMING_INTRODUCTION,
  OUTGOING_INTRODUCTIONS,
  SHARED_ICON,
  type IntentType,
  type MockIntroduction,
  type SharedItem,
} from './mockIntroductions'


type SentStatus = 'idle' | 'sent'
type View = 'introductions' | 'conversation'

interface ConversationState {
  intro: MockIntroduction
  banner: string | null
}


// ---------------------------------------------------------------------------
// Warm-neutral portrait treatment used by the initial fallback.
// A soft warm-stone gradient with a subtle top-left highlight;
// deliberately neutral so it never reads as a category badge.
// ---------------------------------------------------------------------------

const PORTRAIT_INITIAL_BG =
  'radial-gradient(ellipse at 28% 26%, rgba(255,255,255,0.55), transparent 60%),' +
  'linear-gradient(155deg, #EFEDE7 0%, #D8D3CA 100%)'
const PORTRAIT_INITIAL_INK = '#2E3B47'
const PORTRAIT_PHOTO_BG = '#F1EFEB'


// ---------------------------------------------------------------------------
// Intent-based palette retained only for ConversationView (unchanged
// per scope). New card surfaces do not reference it.
// ---------------------------------------------------------------------------

interface IntentPortrait {
  wash:       string
  circle:     string
  ink:        string
  cardBg:     string
  cardBorder: string
}

const PORTRAIT_BY_INTENT: Record<IntentType, IntentPortrait> = {
  'right-now': {
    wash:       'radial-gradient(ellipse at 50% 55%, rgba(243,196,168,0.55), rgba(214,144,110,0.35) 70%, transparent 100%)',
    circle:     'linear-gradient(150deg, #F3C4A8 0%, #D6906E 100%)',
    ink:        '#7C3F1E',
    cardBg:     'rgba(243, 196, 168, 0.08)',
    cardBorder: 'rgba(214, 144, 110, 0.20)',
  },
  'shared-journey': {
    wash:       'radial-gradient(ellipse at 50% 55%, rgba(180,217,184,0.50), rgba(123,178,135,0.32) 70%, transparent 100%)',
    circle:     'linear-gradient(150deg, #C6DEC0 0%, #7BB287 100%)',
    ink:        '#2E4B34',
    cardBg:     'rgba(180, 217, 184, 0.08)',
    cardBorder: 'rgba(123, 178, 135, 0.22)',
  },
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
  const [outgoingStatus, setOutgoingStatus]       = useState<Record<string, SentStatus>>({})
  const [incomingHandled, setIncomingHandled]     = useState(false)
  const [view, setView]                           = useState<View>('introductions')
  const [conversation, setConversation]           = useState<ConversationState | null>(null)

  function markOutgoingSent(id: string) {
    setOutgoingStatus((prev) => ({ ...prev, [id]: 'sent' }))
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

  if (view === 'conversation' && conversation) {
    return (
      <ConversationView
        conversation={conversation}
        setBanner={(msg) => setConversation({ ...conversation, banner: msg })}
        onClose={closeConversation}
      />
    )
  }

  const showIncoming = !incomingHandled

  return (
    <div className="mx-auto w-full max-w-6xl px-6 pb-24 pt-8 md:px-10 md:pt-10">
      {openToConnections ? (
        <section aria-label="Introductions">
          <header className="mb-8 max-w-2xl">
            <h2 className="font-serif text-[24px] leading-tight text-navy-900 md:text-[28px]">
              Where your paths cross
            </h2>
            <p
              className="mt-2 text-[14.5px] italic leading-relaxed"
              style={{ color: 'rgba(12, 24, 38, 0.68)', fontFamily: 'Georgia, serif' }}
            >
              Introductions rooted in the Collectives, Gatherings and
              Places you already share.
            </p>
          </header>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {showIncoming && (
              <IntroductionCard
                intro={INCOMING_INTRODUCTION}
                eyebrow="Invitation"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={acceptIncoming}
                    className="rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
                    style={{
                      background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                      letterSpacing: '0.04em',
                    }}
                  >
                    Accept introduction
                  </button>
                  <button
                    type="button"
                    onClick={() => setIncomingHandled(true)}
                    className="text-[13px] font-medium text-navy-500 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 rounded"
                  >
                    Not now
                  </button>
                </div>
              </IntroductionCard>
            )}

            {OUTGOING_INTRODUCTIONS.map((intro) => {
              const status = outgoingStatus[intro.id] ?? 'idle'
              return (
                <IntroductionCard key={intro.id} intro={intro}>
                  {status === 'sent' ? (
                    <p
                      aria-live="polite"
                      className="text-[13px] italic leading-relaxed"
                      style={{
                        color: '#1E6E6C',
                        fontFamily: 'Georgia, serif',
                      }}
                    >
                      A hello is on its way to {intro.otherName}.
                    </p>
                  ) : (
                    <button
                      type="button"
                      onClick={() => markOutgoingSent(intro.id)}
                      className="text-[13px] font-semibold transition-colors hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 rounded"
                      style={{ color: '#246B6A' }}
                    >
                      Say hello to {intro.otherName} →
                    </button>
                  )}
                </IntroductionCard>
              )
            })}
          </div>
        </section>
      ) : (
        <PausedNotice />
      )}

      <IntroductionPreferences
        enabled={openToConnections}
        onToggle={() => setOpenToConnections((v) => !v)}
      />
    </div>
  )
}


// ---------------------------------------------------------------------------
// Introduction card — one geometry for suggestions and invitations.
// ---------------------------------------------------------------------------

function IntroductionCard({
  intro, eyebrow, children,
}: {
  intro: MockIntroduction
  /** Optional small teal small-caps eyebrow above the name.
   *  Used to mark the incoming invitation ("Invitation") without
   *  changing the card's overall size or geometry. */
  eyebrow?: string
  /** Actions area rendered at the bottom of the card. Parent
   *  controls what appears here (button, sent confirmation, etc.). */
  children: React.ReactNode
}) {
  return (
    <article
      aria-labelledby={`intro-${intro.id}-name`}
      className="flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white transition-shadow hover:shadow-[0_8px_24px_rgba(12,24,38,0.06)]"
    >
      <PortraitSquare name={intro.otherName} avatarUrl={intro.avatarUrl} />

      <div className="flex flex-1 flex-col p-5">
        {eyebrow && (
          <p
            className="text-[10.5px] font-semibold uppercase tracking-[0.24em]"
            style={{ color: '#38A09E' }}
          >
            {eyebrow}
          </p>
        )}
        <h3
          id={`intro-${intro.id}-name`}
          className={
            (eyebrow ? 'mt-1 ' : '') +
            'font-serif text-[20px] leading-tight text-navy-900'
          }
        >
          {intro.otherName}
        </h3>

        <p
          className="mt-3 text-[14px] leading-relaxed text-navy-700"
          style={{ fontFamily: 'Georgia, serif' }}
        >
          {intro.reasonSentence}
        </p>

        <div className="mt-auto pt-5">
          {children}
        </div>
      </div>
    </article>
  )
}


// ---------------------------------------------------------------------------
// Square portrait — profile photo when visible, otherwise a warm
// polished initial on a neutral gradient. Only two states — no
// shared-context artwork stands in for a missing photo.
// ---------------------------------------------------------------------------

function PortraitSquare({
  name, avatarUrl,
}: {
  name: string
  avatarUrl: string | null
}) {
  const [imgFailed, setImgFailed] = useState(false)
  const initial = name.trim().charAt(0).toUpperCase() || '?'
  const showPhoto = avatarUrl !== null && !imgFailed

  return (
    <div
      className="relative w-full overflow-hidden"
      style={{
        aspectRatio: '1 / 1',
        background: showPhoto ? PORTRAIT_PHOTO_BG : PORTRAIT_INITIAL_BG,
      }}
    >
      {showPhoto ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={avatarUrl}
          alt={`${name}'s profile photo`}
          className="absolute inset-0 h-full w-full object-cover object-center"
          onError={() => setImgFailed(true)}
        />
      ) : (
        <div
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-center"
        >
          <span
            className="font-serif leading-none text-[56px] sm:text-[64px] lg:text-[52px]"
            style={{ color: PORTRAIT_INITIAL_INK }}
          >
            {initial}
          </span>
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Paused notice — visible in place of the grid when the member has
// closed introductions. The preferences section below still renders.
// ---------------------------------------------------------------------------

function PausedNotice() {
  return (
    <section aria-label="Introductions paused" className="max-w-2xl">
      <h2 className="font-serif text-[24px] leading-tight text-navy-900 md:text-[28px]">
        Introductions are quiet for now.
      </h2>
      <p
        className="mt-3 text-[14.5px] italic leading-relaxed"
        style={{ color: 'rgba(12, 24, 38, 0.68)', fontFamily: 'Georgia, serif' }}
      >
        You&rsquo;ve paused introductions, so you won&rsquo;t appear
        in anyone else&rsquo;s Ways to Connect and none will appear
        here. Reopen them any time below.
      </p>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Preferences — quiet footer section beneath the grid.
// ---------------------------------------------------------------------------

function IntroductionPreferences({
  enabled, onToggle,
}: {
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <section
      aria-label="Introduction preferences"
      className="mt-16 border-t pt-8"
      style={{ borderColor: 'rgba(12, 24, 38, 0.08)' }}
    >
      <p
        className="text-[10.5px] font-semibold uppercase tracking-[0.24em]"
        style={{ color: '#38A09E' }}
      >
        Introduction preferences
      </p>
      <div className="mt-3 max-w-2xl">
        <p
          className="text-[14px] leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.76)' }}
        >
          {enabled
            ? "You're open to thoughtful introductions based on meaningful shared experiences. You may appear on someone else's Ways to Connect, and they may appear here — never without both of you being open to it."
            : "Introductions are paused. You won't appear in anyone else's Ways to Connect, and none will appear here."}
        </p>
        <button
          type="button"
          onClick={onToggle}
          className="mt-3 text-[13px] font-semibold transition-colors hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 rounded"
          style={{ color: '#246B6A' }}
        >
          {enabled ? 'Pause introductions →' : 'Reopen introductions →'}
        </button>
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Conversation view — UNCHANGED per scope. Retains the intent-based
// portrait treatment pending a separate messaging-surface integration.
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
          <ConversationPortrait name={intro.otherName} avatarUrl={intro.avatarUrl} portrait={portrait} size={72} />
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
            Fresh Collective introduced you because you already share:
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


// Retained portrait treatment for ConversationView only.
function ConversationPortrait({
  name, avatarUrl, portrait, size,
}: {
  name: string
  avatarUrl: string | null
  portrait: IntentPortrait
  size: number
}) {
  const [imgFailed, setImgFailed] = useState(false)
  const initial = name.trim().charAt(0).toUpperCase() || '?'
  const showPhoto = avatarUrl !== null && !imgFailed
  return (
    <div
      className="rounded-full bg-white shadow-[0_6px_18px_rgba(12,24,38,0.15)]"
      style={{ padding: 4, width: size + 8, height: size + 8 }}
    >
      <div
        className="overflow-hidden rounded-full"
        style={{
          width: size,
          height: size,
          background: showPhoto ? '#F1F5F4' : portrait.circle,
        }}
      >
        {showPhoto ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={avatarUrl}
            alt={`${name}'s profile photo`}
            className="h-full w-full object-cover object-center"
            onError={() => setImgFailed(true)}
          />
        ) : (
          <div
            aria-hidden="true"
            className="flex h-full w-full items-center justify-center"
            style={{
              color: portrait.ink,
              fontFamily: 'Georgia, serif',
              fontSize: Math.round(size * 0.42),
              lineHeight: 1,
            }}
          >
            {initial}
          </div>
        )}
      </div>
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
