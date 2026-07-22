'use client'

import { useState } from 'react'

const INK        = '#0C1826'
const INK_MUTED  = 'rgba(12, 24, 38, 0.60)'
const CARD_BG    = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'

// The caretaker writes their own message. No templates, no automation,
// no impersonation. Deliberately minimal.
export default function ContactCard({ email, name }: { email: string; name: string | null }) {
  const [copied, setCopied] = useState(false)
  const subject = name ? `Hello ${name.split(/\s+/)[0]}` : 'Hello'
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(email)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }
  return (
    <section
      className="rounded-2xl px-6 py-5 md:px-7 md:py-6"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <h2 className="mb-3 font-serif text-[20px] leading-tight" style={{ color: INK }}>
        Contact
      </h2>
      <p className="text-[13.5px] leading-relaxed" style={{ color: INK_MUTED }}>
        Reach them directly. World Management doesn't send anything on your behalf.
      </p>
      <div
        className="mt-4 flex items-center justify-between gap-3 rounded-xl px-3.5 py-2.5"
        style={{ background: '#F5F8FA', border: '1px solid #E7EEF0' }}
      >
        <span className="min-w-0 truncate text-[13px]" style={{ color: INK }}>
          {email}
        </span>
        <button
          type="button"
          onClick={copy}
          className="shrink-0 rounded-full px-3 py-1 text-[11.5px] font-semibold transition-colors hover:bg-white"
          style={{ border: '1px solid #E7EEF0', color: INK }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <a
        href={`mailto:${email}?subject=${encodeURIComponent(subject)}`}
        className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-semibold transition-opacity hover:opacity-80"
        style={{ color: '#0f766e' }}
      >
        Open in mail client →
      </a>
    </section>
  )
}
