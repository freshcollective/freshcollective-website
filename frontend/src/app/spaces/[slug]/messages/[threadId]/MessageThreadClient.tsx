'use client'

import { useEffect, useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { MessageThreadDetail, DirectMessageItem } from '@/types/platform'

function formatTime(isoStr: string): string {
  const d = new Date(isoStr)
  const now = new Date()
  const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffMin < 1440) return d.toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit' })
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

interface Props {
  initialThread: MessageThreadDetail
  currentUserId: string
  spaceSlug: string
}

export default function MessageThreadClient({ initialThread, currentUserId, spaceSlug }: Props) {
  const [messages, setMessages] = useState<DirectMessageItem[]>(initialThread.messages)
  const [body, setBody]         = useState('')
  const [sending, setSending]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Mark as read on mount
  useEffect(() => {
    fetch(apiUrl(`/api/spaces/${spaceSlug}/messages/${initialThread.thread_id}/read`), {
      method: 'POST', credentials: 'include',
    }).catch(() => {})
  }, [initialThread.thread_id, spaceSlug])

  // Scroll to bottom whenever messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend() {
    const text = body.trim()
    if (!text) return
    setSending(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/spaces/${spaceSlug}/messages/${initialThread.thread_id}/reply`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ body: text }),
        },
      )
      if (res.ok) {
        const updated: MessageThreadDetail = await res.json()
        setMessages(updated.messages)
        setBody('')
      } else {
        const data = await res.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'Could not send message.')
      }
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setSending(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col gap-0">
      {/* Message list */}
      <div className="mb-4 max-h-[60vh] min-h-[200px] overflow-y-auto rounded-2xl border border-border bg-white p-5">
        {messages.length === 0 ? (
          <p className="text-center text-[13px] text-black">No messages yet.</p>
        ) : (
          <div className="space-y-4">
            {messages.map((msg) => {
              const isMe = msg.sender_id === currentUserId
              return (
                <div key={msg.id} className={`flex ${isMe ? 'justify-end' : 'justify-start'}`}>
                  <div className={[
                    'max-w-[80%] rounded-2xl px-4 py-2.5',
                    isMe
                      ? 'rounded-br-sm text-white'
                      : 'rounded-bl-sm bg-slate-100 text-navy-900',
                  ].join(' ')}
                    style={isMe ? { background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' } : undefined}>
                    {!isMe && (
                      <p className="mb-0.5 text-[11px] font-semibold" style={{ color: 'var(--fc-accent, #0f766e)' }}>{msg.sender_name}</p>
                    )}
                    <p className="whitespace-pre-wrap text-[14px] leading-relaxed">{msg.body}</p>
                    <p className={`mt-1 text-right text-[10px] ${isMe ? 'text-white' : 'text-black'}`}>
                      {formatTime(msg.created_at)}
                    </p>
                  </div>
                </div>
              )
            })}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="rounded-2xl border border-border bg-white p-4">
        <textarea
          value={body}
          onChange={e => { setBody(e.target.value); setError(null) }}
          onKeyDown={handleKeyDown}
          placeholder="Write a reply… (Enter to send, Shift+Enter for new line)"
          rows={3}
          className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-[color:var(--fc-accent,#2dd4bf)]"
        />
        {error && <p className="mt-1.5 text-[12px] text-red-500">{error}</p>}
        <div className="mt-2.5 flex items-center justify-between">
          <p className="text-[11px] text-black">Enter to send · Shift+Enter for new line</p>
          <button
            onClick={handleSend}
            disabled={!body.trim() || sending}
            className="rounded-xl px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
          >
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
}
