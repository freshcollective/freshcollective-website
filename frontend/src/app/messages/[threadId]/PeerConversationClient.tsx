'use client'

import { useState } from 'react'
import MemberImage from '@/components/ui/MemberImage'
import OverflowMenu from '@/components/ui/OverflowMenu'
import {
  blockPeer,
  fetchPeerThread,
  participantName,
  REPORT_CATEGORIES,
  reportPeer,
  sendPeerMessage,
  unblockPeer,
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
  previewOnly = false,
  previewOpen,
}: {
  initialThread: PeerThreadDetail
  currentUserId: string
  /** Admin visual-QA harness only. Suppresses every network call —
   *  send, block, unblock and report all become no-ops — so each state
   *  can be reviewed without writing anything or submitting a report.
   *  Serialisable, because the preview page is a server component.
   *  Never set in production. */
  previewOnly?: boolean
  /** Opens the harness directly into the safety menu or the report
   *  form, which are otherwise only reachable by clicking. */
  previewOpen?: 'menu' | 'report'
}) {
  const [thread, setThread] = useState(initialThread)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Safety controls are deliberately out of the way until asked for:
  // a conversation should not carry a visible threat of moderation.
  // No ``safetyOpen`` any more: the menu owns its own open state, and
  // owns closing on Escape and on an outside click — neither of which
  // the hand-rolled panel did.
  const [confirmBlock, setConfirmBlock] = useState(false)
  const [reporting, setReporting] = useState(previewOpen === 'report')
  const [reportCategory, setReportCategory] = useState<string>('')
  const [reportNote, setReportNote] = useState('')
  const [caseNumber, setCaseNumber] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const name = participantName(thread.other)
  // "Block Maya" rather than "Block Maya Fuller": a menu row is short,
  // and the confirmation that follows still names her in full.
  const firstName = name.split(/\s+/)[0] || name

  async function reload() {
    if (previewOnly) return
    setThread(await fetchPeerThread(thread.thread_id))
  }

  async function doBlock() {
    setBusy(true)
    setError(null)
    try {
      if (!previewOnly) await blockPeer(thread.thread_id)
      await reload()
      setConfirmBlock(false)
    } catch {
      setError('That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function doUnblock() {
    setBusy(true)
    setError(null)
    try {
      if (!previewOnly) await unblockPeer(thread.thread_id)
      // Re-read rather than assuming: if the other person has also
      // blocked, the conversation stays closed and the server is the
      // only thing that knows.
      await reload()
    } catch {
      setError('That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function doReport(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!reportCategory || busy) return
    setBusy(true)
    setError(null)
    try {
      // Nothing is submitted in the harness — the acknowledgement is
      // shown with a placeholder reference so the final state can be
      // reviewed.
      const number = previewOnly
        ? 'FC-PREVIEW'
        : await reportPeer(
            thread.thread_id, reportCategory, reportNote.trim() || undefined,
          )
      setCaseNumber(number)
      setReporting(false)
      setReportCategory('')
      setReportNote('')
    } catch {
      setError('We couldn’t send that. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const body = draft.trim()
    if (!body || sending) return

    setSending(true)
    setError(null)
    try {
      if (previewOnly) {
        // Appended locally so spacing and alternation can be reviewed;
        // nothing is persisted and nothing is re-read.
        setThread({
          ...thread,
          messages: [
            ...thread.messages,
            {
              id: `preview-${thread.messages.length + 1}`,
              sender_user_id: currentUserId,
              body,
              created_at: new Date().toISOString(),
              is_read: false,
            },
          ],
        })
        setDraft('')
        return
      }
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
        <h1 className="flex-1 font-serif text-[20px]" style={{ color: '#0C1826' }}>
          {name}
        </h1>
        {/* Still quiet — a single control in the corner, not a row of
            moderation buttons over the conversation. But outlined, so
            it reads as something you can press. Three grey dots on
            nothing read as punctuation, and the menu went unfound.

            Block and Report stay behind it: they belong to the
            conversation, not in it. */}
        <div className="shrink-0">
          <OverflowMenu
            appearance="outlined"
            triggerLabel="More"
            ariaLabel="Conversation options"
            defaultOpen={previewOpen === 'menu'}
            items={
              thread.blocked_by_me
                // Already blocked: offering Block again says nothing.
                // Unblock lives in the conversation body, where the
                // blocked state explains itself.
                ? [
                    {
                      label: `Report ${firstName}`,
                      onClick: () => { setReporting(true); setConfirmBlock(false) },
                    },
                  ]
                : [
                    {
                      label: `Block ${firstName}`,
                      onClick: () => { setConfirmBlock(true); setReporting(false) },
                    },
                    {
                      label: `Report ${firstName}`,
                      onClick: () => { setReporting(true); setConfirmBlock(false) },
                    },
                  ]
            }
          />
        </div>
      </div>

      {confirmBlock && (
        <div
          className="mt-3 rounded-xl p-4"
          style={{ background: '#FAFAF8', border: '1px solid rgba(12,24,38,0.12)' }}
        >
          <p className="text-[13.5px] leading-[1.55]" style={{ color: '#0C1826' }}>
            Block {name}?
          </p>
          <p
            className="mt-1.5 text-[12.5px] leading-[1.55]"
            style={{ color: 'rgba(12, 24, 38, 0.62)' }}
          >
            You won&rsquo;t be able to message each other, and you
            won&rsquo;t appear to each other in Ways to Connect. Your
            existing conversation will remain. {name} won&rsquo;t be told.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={doBlock}
              disabled={busy}
              className="rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              style={{ background: '#0C1826' }}
            >
              {busy ? 'Blocking…' : 'Block'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmBlock(false)}
              className="text-[13px] font-medium"
              style={{ color: 'rgba(12, 24, 38, 0.6)' }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {reporting && (
        <form
          onSubmit={doReport}
          className="mt-3 rounded-xl p-4"
          style={{ background: '#FAFAF8', border: '1px solid rgba(12,24,38,0.12)' }}
        >
          <p className="text-[13.5px]" style={{ color: '#0C1826' }}>
            Tell Fresh Collective what happened
          </p>
          <label htmlFor="report-category" className="sr-only">
            What kind of problem is it?
          </label>
          <select
            id="report-category"
            value={reportCategory}
            onChange={(e) => setReportCategory(e.target.value)}
            required
            className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13.5px]"
          >
            <option value="">Choose a reason…</option>
            {REPORT_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
          <label htmlFor="report-note" className="sr-only">
            Anything you&rsquo;d like to add
          </label>
          <textarea
            id="report-note"
            value={reportNote}
            onChange={(e) => setReportNote(e.target.value)}
            rows={3}
            placeholder="Anything you'd like to add…"
            required={reportCategory === 'something_else'}
            className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13.5px]"
          />
          <p
            className="mt-2 text-[12px] leading-[1.5]"
            style={{ color: 'rgba(12, 24, 38, 0.62)' }}
          >
            A person at Fresh Collective will read this. {name} won&rsquo;t
            be told you reported them. Reporting doesn&rsquo;t block
            them — you can do that separately.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={busy || !reportCategory}
              className="rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              {busy ? 'Sending…' : 'Send report'}
            </button>
            <button
              type="button"
              onClick={() => setReporting(false)}
              className="text-[13px] font-medium"
              style={{ color: 'rgba(12, 24, 38, 0.6)' }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {caseNumber && (
        <div
          role="status"
          className="mt-3 rounded-xl p-4"
          style={{
            background: 'rgba(56,160,158,0.06)',
            border: '1px solid rgba(56,160,158,0.24)',
          }}
        >
          <p className="text-[13.5px]" style={{ color: '#0C1826' }}>
            Thank you for telling us.
          </p>
          <p
            className="mt-1 text-[12.5px] leading-[1.55]"
            style={{ color: 'rgba(12, 24, 38, 0.62)' }}
          >
            Someone at Fresh Collective will look into it. Your
            reference is {caseNumber}.
          </p>
          {!thread.blocked_by_me && (
            <button
              type="button"
              onClick={() => { setCaseNumber(null); setConfirmBlock(true) }}
              className="mt-2 text-[13px] font-semibold transition-opacity hover:opacity-70"
              style={{ color: '#2F8F8D' }}
            >
              Would you also like to block {name}?
            </button>
          )}
        </div>
      )}

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

      {!thread.can_send ? (
        /* Composer replaced, not disabled-looking: a greyed-out box
           reads as something broken. The blocker is told plainly and
           offered the way back; the person who was blocked is told only
           that the conversation is closed, never by whom — which is why
           this branches on ``blocked_by_me`` rather than on who is
           viewing. */
        <div
          className="mt-6 rounded-xl p-4"
          style={{ background: '#FAFAF8', border: '1px solid rgba(12,24,38,0.10)' }}
        >
          {thread.blocked_by_me ? (
            <>
              <p className="text-[13.5px]" style={{ color: '#0C1826' }}>
                You&rsquo;ve blocked {name}.
              </p>
              <p
                className="mt-1 text-[12.5px] leading-[1.55]"
                style={{ color: 'rgba(12, 24, 38, 0.62)' }}
              >
                Neither of you can send messages, and you won&rsquo;t
                appear to each other in Ways to Connect. Your
                conversation is still here.
              </p>
              <button
                type="button"
                onClick={doUnblock}
                disabled={busy}
                className="mt-3 text-[13px] font-semibold transition-opacity hover:opacity-70 disabled:opacity-60"
                style={{ color: '#2F8F8D' }}
              >
                {busy ? 'Unblocking…' : `Unblock ${name}`}
              </button>
            </>
          ) : (
            <p
              className="text-[13.5px] leading-[1.55]"
              style={{ color: 'rgba(12, 24, 38, 0.70)' }}
            >
              You can&rsquo;t send messages in this conversation. Your
              history is still here.
            </p>
          )}
          {error && (
            <p className="mt-2 text-[12.5px]" style={{ color: '#B4483C' }}>
              {error}
            </p>
          )}
        </div>
      ) : (
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
      )}
    </div>
  )
}
