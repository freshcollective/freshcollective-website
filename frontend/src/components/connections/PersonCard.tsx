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
import {
  primaryCollective,
  reasonSentence,
  type PersonRef,
} from '@/lib/waysToConnect'

type HelloState = 'idle' | 'confirming' | 'sending' | 'sent'

export default function PersonCard({
  person,
  onSendHello,
}: {
  person: PersonRef
  /** Absent during 5a: the card keeps its own local state so the
   *  interaction can be reviewed, and nothing is persisted. */
  onSendHello?: (personId: string) => Promise<void>
}) {
  const [state, setState] = useState<HelloState>('idle')
  const [error, setError] = useState<string | null>(null)

  // Unnamed members never become a card — the API does not feature
  // them — so this is a guard against a future caller, not a state
  // the product reaches.
  const name = person.display_name
  if (!name) return null

  const collective = primaryCollective(person)
  const reason = reasonSentence(person)

  async function send() {
    setState('sending')
    setError(null)
    try {
      await onSendHello?.(person.id)
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
        <h3
          className="font-serif text-[19px] leading-tight break-words"
          style={{ color: '#0C1826' }}
        >
          {name}
        </h3>

        {reason && (
          <p
            className="mt-2 text-[14px] leading-[1.6] break-words"
            style={{ color: 'rgba(12, 24, 38, 0.78)', fontFamily: 'Georgia, serif' }}
          >
            {reason}
          </p>
        )}

        {person.shared.length > 0 && (
          <div className="mt-4">
            <p
              className="text-[11px] font-semibold uppercase tracking-[0.14em]"
              style={{ color: 'rgba(12, 24, 38, 0.42)' }}
            >
              Shared
            </p>
            <ul className="mt-1.5 space-y-1">
              {person.shared.map((thing) => (
                <li
                  key={`${thing.kind}-${thing.id}`}
                  className="flex items-start gap-2 text-[13.5px] leading-snug break-words"
                  style={{ color: 'rgba(12, 24, 38, 0.72)' }}
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
          {state === 'sent' ? (
            <p
              aria-live="polite"
              className="text-[13px]"
              style={{ color: '#1E6E6C', fontFamily: 'Georgia, serif' }}
            >
              Hello sent
            </p>
          ) : state === 'confirming' || state === 'sending' ? (
            <div>
              <p
                className="text-[13.5px] leading-[1.55]"
                style={{ color: '#0C1826', fontFamily: 'Georgia, serif' }}
              >
                Say hello to {name}?
              </p>
              <p
                className="mt-1.5 text-[12.5px] leading-[1.55]"
                style={{ color: 'rgba(12, 24, 38, 0.6)' }}
              >
                This lets {name} know you’re open to connecting. You
                won’t be able to message unless {name} says hello back.
              </p>
              {error && (
                <p className="mt-2 text-[12.5px]" style={{ color: '#B4483C' }}>
                  {error}
                </p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={send}
                  disabled={state === 'sending'}
                  className="rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
                  style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                >
                  {state === 'sending' ? 'Sending…' : 'Send hello'}
                </button>
                <button
                  type="button"
                  onClick={() => { setState('idle'); setError(null) }}
                  className="rounded text-[13px] font-medium transition-colors hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
                  style={{ color: 'rgba(12, 24, 38, 0.6)' }}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setState('confirming')}
              className="rounded text-[13px] font-semibold transition-opacity hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
              style={{ color: '#2F8F8D' }}
            >
              Say hello
              {/* Names who, so a screen reader hears "Say hello —
                  Sarah" rather than the same two words three times. */}
              <span className="sr-only"> — {name}</span>
            </button>
          )}
        </div>
      </div>

      {collective && (
        <p
          className="border-t px-5 py-2.5 text-[11.5px]"
          style={{
            borderColor: 'rgba(12, 24, 38, 0.06)',
            color: 'rgba(12, 24, 38, 0.45)',
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
