'use client'

import { useState } from 'react'
import MemberImage from '@/components/ui/MemberImage'
import {
  fetchPeerThread,
  participantName,
  sendPeerMessage,
  type PeerThreadDetail,
} from '@/lib/peerMessages'

/**
 * A private conversation between two members.
 *
 * Plain text, deliberately. Bodies are rendered as text nodes — never
 * ``dangerouslySetInnerHTML`` — so nothing a member types can become
 * markup here, and the backend strips tags before storing as well. Two
 * independent reasons the same message is safe.
 *
 * No typing indicators, no read receipts, no reactions, no attachments:
 * this is the continuation of saying hello, not a chat product.
 */
export default function PeerConversationClient({
  initialThread,
  currentUserId,
}: {
  initialThread: PeerThreadDetail
  currentUserId: string
}) {
  const [thread, setThread] = useState(initialThread)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const name = participantName(thread.other)

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const body = draft.trim()
    if (!body || sending) return

    setSending(true)
    setError(null)
    try {
      await sendPeerMessage(thread.thread_id, body)
      // Re-read rather than appending the local draft: the server
      // sanitises the body, so what is stored can differ from what was
      // typed, and the thread should show what the other person will
      // actually see.
      setThread(await fetchPeerThread(thread.thread_id))
      setDraft('')
    } catch {
      setError('That didn’t send. Please try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mt-5">
      <div className="flex items-center gap-3">
        <span className="h-11 w-11 shrink-0 overflow-hidden rounded-full">
          <MemberImage image={thread.other.image} className="h-11 w-11" />
        </span>
        <h1 className="font-serif text-[20px]" style={{ color: '#0C1826' }}>
          {name}
        </h1>
      </div>

      <ul className="mt-6 flex flex-col gap-3">
        {thread.messages.length === 0 && (
          <li
            className="rounded-2xl bg-white px-5 py-6 text-center text-[13.5px] italic"
            style={{
              color: 'rgba(12, 24, 38, 0.6)',
              fontFamily: 'Georgia, serif',
              border: '1px solid rgba(12,24,38,0.08)',
            }}
          >
            You&rsquo;re connected. Say whatever feels right to start.
          </li>
        )}
        {thread.messages.map((message) => {
          const mine = message.sender_user_id === currentUserId
          return (
            <li
              key={message.id}
              className={mine ? 'flex justify-end' : 'flex justify-start'}
            >
              <div
                className="max-w-[80%] rounded-2xl px-4 py-2.5 text-[14px] leading-[1.5]"
                style={
                  mine
                    ? { background: 'rgba(56,160,158,0.12)', color: '#0C1826' }
                    : {
                        background: '#FFFFFF',
                        color: '#0C1826',
                        border: '1px solid rgba(12,24,38,0.08)',
                      }
                }
              >
                {/* A text node. Never dangerouslySetInnerHTML. */}
                {message.body}
              </div>
            </li>
          )
        })}
      </ul>

      <form onSubmit={submit} className="mt-6">
        <label htmlFor="peer-message" className="sr-only">
          Message {name}
        </label>
        <textarea
          id="peer-message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          placeholder={`Write to ${name}…`}
          className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
        />
        {error && (
          <p className="mt-2 text-[12.5px]" style={{ color: '#B4483C' }}>
            {error}
          </p>
        )}
        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            disabled={sending || draft.trim().length === 0}
            className="rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>
      </form>
    </div>
  )
}
