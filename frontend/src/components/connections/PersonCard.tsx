/**
 * One person the member has genuinely crossed paths with.
 *
 * The person is the subject. The shared Gatherings and Pathways are
 * listed underneath as the reason they are here — evidence for a
 * claim, not the claim itself. That ordering is the whole product
 * decision: a page organised around shared experiences reads as an
 * activity feed, and this is meant to read as an introduction.
 *
 * Geometry follows the historical prototype, which had it right:
 * square portrait, name, one factual sentence, one action. What the
 * prototype did not do — and should have — is show the evidence on
 * the card; it kept the shared list hidden until after you accepted.
 * Putting it next to the claim is the improvement.
 *
 * What is deliberately absent: any link to a profile, any count, any
 * "3 things in common", any badge for the *kind* of overlap. Nothing
 * on this card ranks this person against the other two.
 *
 * `Say hello` is a two-step action — press, confirm, send — because
 * it is a message about the member to another human, and a single tap
 * that cannot be taken back is the wrong weight for that. Work Item
 * 5a renders the interaction without persisting it; `onSendHello` is
 * where 5b attaches.
 */

'use client'

import { useState } from 'react'
import MemberImage from '@/components/ui/MemberImage'
import { personCardType as T } from './personCardType'
import { useRouter } from 'next/navigation'
import {
  openConversation,
  primaryCollective,
  reasonSentence,
  sayHello,
  type PersonRef,
} from '@/lib/waysToConnect'

type HelloState = 'idle' | 'confirming' | 'sending' | 'sent'

export default function PersonCard({
  person,
  onSendHello,
  previewOnly = false,
  previewMessageHref,
}: {
  person: PersonRef
  /** Override for the send. Only the preview harness passes this; in
   *  the product the card calls the API itself, because the page that
   *  renders it is a server component and cannot hand down a function.
   *  Supplying a no-op is how a review context runs the confirm step
   *  without persisting anything. */
  onSendHello?: (personId: string) => Promise<void>
  /** Admin visual-QA harness only. Suppresses every network call so
   *  the card can be reviewed in each relationship state without
   *  writing anything or POSTing anywhere. Serialisable on purpose —
   *  the preview page is a server component and cannot hand down a
   *  function. Never set in production. */
  previewOnly?: boolean
  /** Where Message → goes in the harness, since there is no real
   *  thread to open. */
  previewMessageHref?: string
}) {
  const router = useRouter()
  const [state, setState] = useState<HelloState>('idle')
  const [error, setError] = useState<string | null>(null)
  // The server's answer, once this card has sent one. Until then the
  // relationship is whatever the page was told — the backend owns this,
  // and an optimistic local flag must not outrank it on re-render.
  const [sentNow, setSentNow] = useState(false)
  const [opening, setOpening] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)

  const relationship = person.relationship ?? 'none'
  const isMutual = relationship === 'mutual'
  const isIncoming = relationship === 'incoming'
  // Outgoing either because the page said so, or because this card just
  // sent one and the payload has not been refetched yet.
  const isOutgoing = relationship === 'outgoing' || (sentNow && !isMutual)

  // Unnamed members never become a card — the API does not feature
  // them — so this is a guard against a future caller, not a state
  // the product reaches.
  const name = person.display_name
  if (!name) return null

  const collective = primaryCollective(person)
  const reason = reasonSentence(person)

  async function openMessage() {
    setOpening(true)
    setOpenError(null)
    try {
      if (previewOnly) {
        if (previewMessageHref) router.push(previewMessageHref)
        setOpening(false)
        return
      }
      const threadId = await openConversation(person.id)
      router.push(`/messages/${threadId}`)
    } catch {
      setOpenError('We couldn’t open that conversation. Please try again.')
      setOpening(false)
    }
  }

  async function send() {
    setState('sending')
    setError(null)
    try {
      if (previewOnly) {
        // Nothing persisted; the card still transitions so the state
        // change can be reviewed.
      } else if (onSendHello) {
        await onSendHello(person.id)
      } else {
        await sayHello(person.id)
      }
      setSentNow(true)
      setState('sent')
    } catch {
      setError('That didn’t send. Please try again.')
      setState('confirming')
    }
  }

  return (
    <li
      // A person card is this wide. Full width on a phone, where the
      // viewport is the constraint; a fixed width from `sm` up, so the
      // card never stretches to fill space the layout happens to have.
      //
      // 288px is the proportion the three-card state was designed at:
      // three of these plus two 20px gaps come to 904px inside a 916px
      // content area, which leaves a little slack. Sized to *fit*
      // three rather than to fill exactly — a row that measures the
      // container precisely wraps the moment a scrollbar or a rounding
      // difference takes a pixel, and a wrapped third card is the very
      // thing this layout exists to avoid.
      //
      // From `md`, not `sm`: at 640px two fixed cards miss a single row
      // by four pixels and wrap into two lonely 288px cards on a wide-
      // ish screen. Below 768px the card simply takes the width it is
      // given, which is what a phone and a small tablet want anyway.
      className="flex w-full flex-col overflow-hidden rounded-2xl bg-white md:w-[288px]"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.07)',
        boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
      }}
    >
      {/* One frame, whatever is in it: their photo, their alphabet
          card, or their letter — resolved server-side. */}
      <MemberImage image={person.image} className="w-full" />

      <div className="flex flex-1 flex-col p-5">
        <h3 className={T.name.className} style={T.name.style}>
          {name}
        </h3>

        {reason && (
          <p
            className={`mt-2 ${T.reason.className}`}
            style={T.reason.style}
          >
            {reason}
          </p>
        )}

        {person.shared.length > 0 && (
          <div className="mt-4">
            <p
              className={T.sharedLabel.className}
              style={T.sharedLabel.style}
            >
              Shared
            </p>
            <ul className="mt-1.5 space-y-1">
              {person.shared.map((thing) => (
                <li
                  key={`${thing.kind}-${thing.id}`}
                  className={`flex items-start gap-2 ${T.evidence.className}`}
                  style={T.evidence.style}
                >
                  <span aria-hidden="true" className="mt-[7px] shrink-0">
                    <span
                      className="block h-[3px] w-[3px] rounded-full"
                      style={{ background: 'rgba(12, 24, 38, 0.35)' }}
                    />
                  </span>
                  <span>{thing.title}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Action area, pinned to the bottom so cards of different
            heights still line their buttons up. */}
        <div className="mt-auto pt-5">
          {/* Mutual first: once two people have both said hello, the
              card stops asking anything of them. Deliberately no
              "Message" action — the existing messaging model is
              creator↔member inside a Collective and has no peer
              thread, so offering one here would be a promise the
              backend cannot keep. See the 5b report. */}
          {isMutual ? (
            <div>
              <p
                aria-live="polite"
                className={T.state.className}
                style={T.state.style}
              >
                <span aria-hidden="true">✓</span> Connected
                <span className="sr-only"> — you and {name} have both said hello</span>
              </p>
              {/* Only reachable in the mutual state, which is the whole
                  authorisation story: the backend get-or-creates the
                  thread and refuses with a 404 unless both hello rows
                  exist, so this button cannot be the thing that grants
                  access. Pressing it opens the conversation; it does
                  not send anything. */}
              <button
                type="button"
                onClick={openMessage}
                disabled={opening}
                className={`mt-2 rounded transition-opacity hover:opacity-70 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ${T.action.className}`}
                style={T.action.style}
              >
                {opening ? 'Opening…' : 'Message →'}
                <span className="sr-only"> — {name}</span>
              </button>
              {openError && (
                <p className={`mt-2 ${T.error.className}`} style={T.error.style}>
                  {openError}
                </p>
              )}
            </div>
          ) : isOutgoing || state === 'sent' ? (
            /* Pending, and not a button: there is nothing useful to do
               with a second click, and a disabled-looking control reads
               as something that failed. */
            <p
              aria-live="polite"
              className={T.state.className}
              style={T.state.style}
            >
              Hello sent
              <span className="sr-only"> — waiting for {name}</span>
            </p>
          ) : state === 'confirming' || state === 'sending' ? (
            <div>
              <p className={T.prompt.className} style={T.prompt.style}>
                {isIncoming ? `Say hello back to ${name}?` : `Say hello to ${name}?`}
              </p>
              <p
                className={`mt-1.5 ${T.supporting.className}`}
                style={T.supporting.style}
              >
                {isIncoming
                  ? `${name} has already said hello, so this connects you both.`
                  : `This lets ${name} know you’re open to connecting.`}
              </p>
              {error && (
                <p className={`mt-2 ${T.error.className}`} style={T.error.style}>
                  {error}
                </p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={send}
                  disabled={state === 'sending'}
                  className={`rounded-full px-4 py-2 transition-opacity hover:opacity-90 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ${T.actionPrimary.className}`}
                  style={{
                    ...T.actionPrimary.style,
                    background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  }}
                >
                  {state === 'sending' ? 'Sending…' : 'Send hello'}
                </button>
                <button
                  type="button"
                  onClick={() => { setState('idle'); setError(null) }}
                  className={`rounded transition-colors hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ${T.actionQuiet.className}`}
                  style={T.actionQuiet.style}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Somebody has greeted the viewer. Said plainly, above
                  the action, so the card reads as a person waiting
                  rather than another recommendation. */}
              {isIncoming && (
                <p
                  className={`mb-2 ${T.state.className}`}
                  style={T.state.style}
                >
                  {/* No inner weight span: the state role is already
                      semibold, and emphasising the name inside an
                      already-emphasised line was one of the three
                      weights this element used to render in. */}
                  <span aria-hidden="true">👋</span> {name} said hello
                </p>
              )}
              <button
                type="button"
                onClick={() => setState('confirming')}
                className={`rounded transition-opacity hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ${T.action.className}`}
                style={T.action.style}
              >
                {isIncoming ? 'Say hello back' : 'Say hello'}
                {/* Names who, so a screen reader hears "Say hello —
                    Sarah" rather than the same two words three times. */}
                <span className="sr-only"> — {name}</span>
              </button>
            </>
          )}
        </div>
      </div>

      {collective && (
        <p
          className={`border-t px-5 py-2.5 ${T.footer.className}`}
          style={{
            ...T.footer.style,
            borderColor: 'rgba(12, 24, 38, 0.06)',
          }}
        >
          {/* Also a privacy statement: it says where this person can
              already see the member. */}
          {collective.name}
        </p>
      )}
    </li>
  )
}
