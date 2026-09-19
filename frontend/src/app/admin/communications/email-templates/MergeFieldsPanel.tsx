'use client'

/**
 * The fields this email can fill in — and only this email.
 *
 * The list comes from the template's own declaration, so a field that
 * would render empty is never offered. Nothing internal appears here:
 * the API returns the member-facing name, never the context key behind
 * it, which is why an internal rename cannot invalidate saved copy.
 */

import { useState } from 'react'
import { mergeToken } from '@/lib/emailTemplates'
import type { MergeFieldOut } from '@/lib/emailTemplates'
import { CARD_BG, CARD_BORDER, HAIRLINE, INK, INK_MUTED, INK_SOFTER, SERIF_ITALIC } from './tokens'

export default function MergeFieldsPanel({ fields }: { fields: MergeFieldOut[] }) {
  const [copied, setCopied] = useState<string | null>(null)

  async function copy(token: string) {
    try {
      await navigator.clipboard.writeText(token)
      setCopied(token)
      setTimeout(() => setCopied((c) => (c === token ? null : c)), 1600)
    } catch {
      // Clipboard access can be refused; the token is visible and
      // selectable either way, so there is nothing to recover from.
    }
  }

  return (
    <div className="rounded-xl" style={{ background: CARD_BG, border: CARD_BORDER }}>
      <div className="px-4 py-3" style={{ borderBottom: HAIRLINE }}>
        <h3 className="text-[13px] font-semibold" style={{ color: INK }}>
          Available fields
        </h3>
      </div>
      {fields.length === 0 ? (
        <p className="px-4 py-4 text-[13px]" style={SERIF_ITALIC}>
          This email fills nothing in — every word of it is written here.
        </p>
      ) : (
        <ul className="flex flex-col">
          {fields.map((f, i) => {
            const token = mergeToken(f)
            return (
              <li
                key={f.name}
                className="flex flex-col gap-1 px-4 py-3"
                style={i > 0 ? { borderTop: HAIRLINE } : undefined}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium" style={{ color: INK }}>
                    {humanName(f.name)}
                  </span>
                  <button
                    type="button"
                    onClick={() => copy(token)}
                    title="Copy"
                    className="rounded px-1.5 py-0.5 font-mono text-[11px] transition-colors hover:bg-[rgba(56,160,158,0.10)]"
                    style={{ color: '#0f766e', background: 'rgba(56,160,158,0.06)' }}
                  >
                    {copied === token ? 'Copied' : token}
                  </button>
                </div>
                {f.description && (
                  <span className="text-[12px]" style={{ color: INK_MUTED }}>
                    {f.description}
                  </span>
                )}
                <span className="text-[12px]" style={{ color: INK_SOFTER }}>
                  e.g. {f.sample}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** `collective_name` → `Collective name`. */
function humanName(name: string): string {
  const words = name.split('_')
  return words
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ')
}
