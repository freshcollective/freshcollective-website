'use client'

/**
 * PROTOTYPE — Ways to Connect (unified four-card grid + editorial
 * conversation placeholder + session-scoped persistence)
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
 *   4. Actions area — Say hello (suggestions), Accept / Not now
 *      (incoming invitation), or Continue conversation (an
 *      already-accepted introduction).
 *
 * Grid: 4 columns on wide desktop, 2 on tablet, 1 on mobile.
 *
 * The `ConversationView` placeholder uses the same visual
 * language (white cards, subtle borders, PortraitSquare, no emoji,
 * no chips, no decorative gradients). Messages typed here are
 * persisted for the current browser session only.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  INCOMING_INTRODUCTION,
  OUTGOING_INTRODUCTIONS,
  type MockIntroduction,
} from './mockIntroductions'


type View = 'introductions' | 'conversation'

interface OutgoingMessage {
  id: string
  text: string
  sentAt: number
}


// ---------------------------------------------------------------------------
// TODO(messaging-backend): DELETE THIS ENTIRE BLOCK when the real
// conversations + messaging service arrives.
//
// Session-scoped prototype persistence. Backed by sessionStorage so
// accepted invitations, sent-hello marks, and typed messages survive
// refresh within the same browser tab. State is cleared automatically
// when the tab or window closes. Not appropriate for production — no
// server persistence, no cross-tab sync, no real message delivery.
//
// State shape is deliberately narrow so the replacement service can
// map it to real records without needing shape parity:
//   incoming[introId]  — lifecycle of an incoming invitation
//   outgoingHelloed    — outgoing suggestions the member has replied to
//   messages[introId]  — locally-composed messages, only ever the
//                        current member's; the other party never
//                        appears here in the prototype.
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'fc.prototype.ways-to-connect.v1'

type IncomingLifecycle = 'accepted' | 'declined' | 'ended'

interface PrototypeState {
  incoming: Record<string, IncomingLifecycle>
  outgoingHelloed: string[]
  messages: Record<string, OutgoingMessage[]>
}

const EMPTY_STATE: PrototypeState = {
  incoming: {},
  outgoingHelloed: [],
  messages: {},
}

function loadPrototypeState(): PrototypeState {
  if (typeof window === 'undefined') return EMPTY_STATE
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return EMPTY_STATE
    const parsed = JSON.parse(raw) as Partial<PrototypeState>
    return {
      incoming: parsed.incoming ?? {},
      outgoingHelloed: parsed.outgoingHelloed ?? [],
      messages: parsed.messages ?? {},
    }
  } catch {
    return EMPTY_STATE
  }
}

function savePrototypeState(state: PrototypeState): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // sessionStorage disabled or over quota — silently drop for the
    // prototype. The real service will surface persistence errors.
  }
}

function usePrototypeState() {
  // Server render + first client paint use EMPTY_STATE so hydration
  // matches. The effect below swaps in the persisted state — briefly
  // gated by ``hydrated`` so we don't flash a stale invitation card
  // for someone the member already accepted in this session.
  const [state, setState] = useState<PrototypeState>(EMPTY_STATE)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    setState(loadPrototypeState())
    setHydrated(true)
  }, [])

  const update = useCallback(
    (patch: (prev: PrototypeState) => PrototypeState) => {
      setState((prev) => {
        const next = patch(prev)
        savePrototypeState(next)
        return next
      })
    },
    [],
  )

  return { state, hydrated, update }
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
// Root
// ---------------------------------------------------------------------------

export default function WaysToConnectPrototype() {
  const [openToConnections, setOpenToConnections] = useState(true)
  const { state, hydrated, update } = usePrototypeState()
  const [view, setView] = useState<View>('introductions')
  const [conversationIntroId, setConversationIntroId] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  // ── Lifecycle handlers ───────────────────────────────────────────────
  const acceptIncoming = useCallback(
    (intro: MockIntroduction) => {
      update((prev) => ({
        ...prev,
        incoming: { ...prev.incoming, [intro.id]: 'accepted' },
      }))
      setConversationIntroId(intro.id)
      setBanner(null)
      setView('conversation')
    },
    [update],
  )

  const declineIncoming = useCallback(
    (introId: string) => {
      update((prev) => ({
        ...prev,
        incoming: { ...prev.incoming, [introId]: 'declined' },
      }))
    },
    [update],
  )

  const openConversation = useCallback((intro: MockIntroduction) => {
    setConversationIntroId(intro.id)
    setBanner(null)
    setView('conversation')
  }, [])

  const closeConversation = useCallback(() => {
    setView('introductions')
    setConversationIntroId(null)
    setBanner(null)
  }, [])

  const endIntroduction = useCallback(
    (introId: string) => {
      update((prev) => {
        // Ending an introduction clears the messages too — the
        // conversation no longer exists to hold them.
        const nextMessages = { ...prev.messages }
        delete nextMessages[introId]
        return {
          ...prev,
          incoming: { ...prev.incoming, [introId]: 'ended' },
          messages: nextMessages,
        }
      })
      setView('introductions')
      setConversationIntroId(null)
      setBanner(null)
    },
    [update],
  )

  const markOutgoingHelloed = useCallback(
    (introId: string) => {
      update((prev) =>
        prev.outgoingHelloed.includes(introId)
          ? prev
          : { ...prev, outgoingHelloed: [...prev.outgoingHelloed, introId] },
      )
    },
    [update],
  )

  const sendMessage = useCallback(
    (introId: string, text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      const msg: OutgoingMessage = { id: newId(), text: trimmed, sentAt: Date.now() }
      update((prev) => ({
        ...prev,
        messages: {
          ...prev.messages,
          [introId]: [...(prev.messages[introId] ?? []), msg],
        },
      }))
    },
    [update],
  )

  // ── Derived data ─────────────────────────────────────────────────────
  const incomingState = state.incoming[INCOMING_INTRODUCTION.id]
  const showIncomingInvitation = incomingState === undefined
  const activeConversations: MockIntroduction[] =
    incomingState === 'accepted' ? [INCOMING_INTRODUCTION] : []
  const outgoingHelloedSet = new Set(state.outgoingHelloed)

  const currentConversation =
    conversationIntroId !== null
      ? activeConversations.find((c) => c.id === conversationIntroId) ?? null
      : null

  // ── Render ───────────────────────────────────────────────────────────

  // Brief hydration gate — avoids flashing James as an invitation
  // for a member who has already accepted him this session. The
  // placeholder is exactly the same size as the main container so
  // there is no cumulative layout shift.
  if (!hydrated) {
    return (
      <div
        aria-hidden="true"
        className="mx-auto w-full max-w-6xl px-6 pb-24 pt-8 md:px-10 md:pt-10"
        style={{ minHeight: 480 }}
      />
    )
  }

  if (view === 'conversation' && currentConversation) {
    return (
      <ConversationView
        intro={currentConversation}
        messages={state.messages[currentConversation.id] ?? []}
        banner={banner}
        setBanner={setBanner}
        onSendMessage={(text) => sendMessage(currentConversation.id, text)}
        onEndIntroduction={() => endIntroduction(currentConversation.id)}
        onClose={closeConversation}
      />
    )
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-6 pb-24 pt-8 md:px-10 md:pt-10">
      {openToConnections ? (
        <>
          {activeConversations.length > 0 && (
            <YourConversations
              conversations={activeConversations}
              onOpen={openConversation}
            />
          )}

          <section
            aria-label="Introductions"
            className={activeConversations.length > 0 ? 'mt-14' : ''}
          >
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
              {showIncomingInvitation && (
                <IntroductionCard
                  intro={INCOMING_INTRODUCTION}
                  eyebrow="Invitation"
                >
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => acceptIncoming(INCOMING_INTRODUCTION)}
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
                      onClick={() => declineIncoming(INCOMING_INTRODUCTION.id)}
                      className="text-[13px] font-medium text-navy-500 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 rounded"
                    >
                      Not now
                    </button>
                  </div>
                </IntroductionCard>
              )}

              {OUTGOING_INTRODUCTIONS.map((intro) => {
                const helloed = outgoingHelloedSet.has(intro.id)
                return (
                  <IntroductionCard key={intro.id} intro={intro}>
                    {helloed ? (
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
                        onClick={() => markOutgoingHelloed(intro.id)}
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
        </>
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
// Your conversations — quiet section listing accepted introductions.
// Same card geometry as the intro grid so the visual family holds.
// ---------------------------------------------------------------------------

function YourConversations({
  conversations, onOpen,
}: {
  conversations: MockIntroduction[]
  onOpen: (intro: MockIntroduction) => void
}) {
  return (
    <section aria-label="Your conversations">
      <header className="mb-8 max-w-2xl">
        <h2 className="font-serif text-[24px] leading-tight text-navy-900 md:text-[28px]">
          Your conversations
        </h2>
        <p
          className="mt-2 text-[14.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.68)', fontFamily: 'Georgia, serif' }}
        >
          Introductions you&rsquo;ve accepted. Continue when it feels right.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {conversations.map((intro) => (
          <IntroductionCard key={intro.id} intro={intro} eyebrow="Conversation">
            <button
              type="button"
              onClick={() => onOpen(intro)}
              className="text-[13px] font-semibold transition-colors hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 rounded"
              style={{ color: '#246B6A' }}
            >
              Continue conversation →
            </button>
          </IntroductionCard>
        ))}
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Introduction card — one geometry for suggestions, invitations,
// and accepted conversations.
// ---------------------------------------------------------------------------

function IntroductionCard({
  intro, eyebrow, children,
}: {
  intro: MockIntroduction
  /** Optional small teal small-caps eyebrow above the name.
   *  Used to mark state ("Invitation", "Conversation") without
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
// Conversation view — the moment after accepting an introduction.
//
// Message state is owned by the parent (persisted via sessionStorage);
// this component is purely presentational for messages. The composer
// dispatches through `onSendMessage`, and `onEndIntroduction` marks
// the lifecycle so the invitation and any past messages are cleared
// for the rest of the session.
// ---------------------------------------------------------------------------

function ConversationView({
  intro, messages, banner, setBanner,
  onSendMessage, onEndIntroduction, onClose,
}: {
  intro: MockIntroduction
  messages: OutgoingMessage[]
  banner: string | null
  setBanner: (msg: string | null) => void
  onSendMessage: (text: string) => void
  onEndIntroduction: () => void
  onClose: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  function selectMenu(action: 'mute' | 'end' | 'report') {
    setMenuOpen(false)
    if (action === 'mute') {
      setBanner("You've muted this introduction. You won't be notified of new messages.")
      return
    }
    if (action === 'end') {
      onEndIntroduction()
      return
    }
    if (action === 'report') {
      setBanner('Reported to Fresh Collective. Someone from Community Care will be in touch.')
      return
    }
  }

  // Keep the newest message in view when the thread grows.
  useEffect(() => {
    if (messages.length === 0) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  return (
    <div className="mx-auto w-full max-w-4xl px-6 pb-24 pt-8 md:px-10 md:pt-10">
      <button
        type="button"
        onClick={onClose}
        className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-navy-500 transition-colors hover:text-navy-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded"
      >
        ← Back to Ways to Connect
      </button>

      {/* Welcome card — matches the introduction cards' language */}
      <section
        aria-label="Introduction context"
        className="overflow-hidden rounded-2xl border border-slate-200 bg-white md:flex md:items-stretch"
      >
        <div className="mx-auto w-full max-w-[240px] md:mx-0 md:w-[36%] md:max-w-none md:shrink-0">
          <PortraitSquare name={intro.otherName} avatarUrl={intro.avatarUrl} />
        </div>

        <div className="flex-1 p-6 md:p-8">
          <p
            className="text-[10.5px] font-semibold uppercase tracking-[0.24em]"
            style={{ color: '#38A09E' }}
          >
            Welcome
          </p>
          <h2 className="mt-2 font-serif text-[24px] leading-tight text-navy-900 md:text-[28px]">
            {intro.otherName}
          </h2>

          <p className="mt-5 text-[14px] leading-relaxed text-navy-700">
            Fresh Collective introduced you because you already share:
          </p>
          <ul className="mt-3 space-y-1.5">
            {intro.sharedItems.map((item, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-[14px] leading-snug text-navy-700"
              >
                <span
                  aria-hidden="true"
                  className="mt-[0.4em] inline-block h-[3px] w-[3px] shrink-0 rounded-full"
                  style={{ background: 'rgba(12, 24, 38, 0.35)' }}
                />
                <span>{item.label}</span>
              </li>
            ))}
          </ul>

          <p
            className="mt-6 text-[14px] italic leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.68)', fontFamily: 'Georgia, serif' }}
          >
            There&rsquo;s nothing expected from here. Say hello if
            and when it feels right.
          </p>
        </div>
      </section>

      {/* Conversation panel — messaging-app rhythm */}
      <section
        aria-label={`Conversation with ${intro.otherName}`}
        className="mt-6 flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white"
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

        {messages.length === 0 ? (
          <div
            className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center"
            style={{ minHeight: 320 }}
          >
            <p className="font-serif text-[17px] leading-snug text-navy-900">
              No messages yet.
            </p>
            <p
              className="mt-3 max-w-sm text-[14px] italic leading-relaxed"
              style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}
            >
              This space is now yours. Say hello whenever you&rsquo;re ready.
            </p>
          </div>
        ) : (
          <ul
            role="log"
            aria-live="polite"
            aria-relevant="additions"
            aria-label={`Messages with ${intro.otherName}`}
            className="flex flex-col gap-3 px-5 py-6 md:px-6"
            style={{ minHeight: 320 }}
          >
            {messages.map((m) => (
              <li key={m.id} className="flex justify-end">
                <div
                  className="max-w-[78%] rounded-2xl px-4 py-2.5"
                  style={{
                    background: 'rgba(56, 160, 158, 0.10)',
                    border: '1px solid rgba(56, 160, 158, 0.22)',
                  }}
                >
                  <p
                    className="whitespace-pre-wrap text-[14px] leading-relaxed text-navy-900"
                  >
                    {m.text}
                  </p>
                  <p
                    className="mt-1 text-right text-[10.5px]"
                    style={{ color: 'rgba(12, 24, 38, 0.48)' }}
                  >
                    <time dateTime={new Date(m.sentAt).toISOString()}>
                      Just now
                    </time>
                  </p>
                </div>
              </li>
            ))}
            <div ref={bottomRef} aria-hidden="true" />
          </ul>
        )}

        <MessageComposer onSend={onSendMessage} />
      </section>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Message composer — prototype-only.
//
// Local text state, no backend. Send is enabled once the trimmed
// text is non-empty. Enter sends; Shift+Enter inserts a newline
// (native textarea behaviour). The textarea auto-grows up to a
// modest cap so long messages don't push the composer off-screen.
// IME composition is respected — Enter during a composition never
// sends.
// ---------------------------------------------------------------------------

const COMPOSER_MAX_HEIGHT = 140  // px — ~6 lines

function MessageComposer({
  onSend,
}: {
  onSend: (text: string) => void
}) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const trimmed = text.trim()
  const canSend = trimmed.length > 0

  function resizeTextarea() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, COMPOSER_MAX_HEIGHT)}px`
  }

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setText(e.target.value)
    resizeTextarea()
  }

  function submit() {
    if (!canSend) return
    onSend(trimmed)
    setText('')
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.focus()
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    const composing = (e.nativeEvent as KeyboardEvent).isComposing
    if (e.key === 'Enter' && !e.shiftKey && !composing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex items-end gap-2 border-t border-slate-100 bg-white p-3">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder="Type a message…"
        aria-label="Message"
        rows={1}
        className="flex-1 resize-none rounded-xl border border-slate-200 bg-white px-4 py-2 text-[14px] leading-snug text-navy-900 placeholder:text-slate-400 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        style={{ maxHeight: COMPOSER_MAX_HEIGHT }}
      />
      <button
        type="button"
        onClick={submit}
        disabled={!canSend}
        aria-disabled={!canSend}
        className="shrink-0 rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45"
        style={{
          background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
          letterSpacing: '0.04em',
        }}
      >
        Send
      </button>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Small id helper for prototype message keys. Prefers the browser's
// crypto.randomUUID() when available (it always is in the runtime
// we support) and falls back to a random-string composite so the
// call site can stay a pure function.
// ---------------------------------------------------------------------------

function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
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
          className="absolute right-0 top-9 z-10 min-w-[200px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg"
        >
          <MenuItem onClick={() => onSelect('mute')}>Mute conversation</MenuItem>
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
