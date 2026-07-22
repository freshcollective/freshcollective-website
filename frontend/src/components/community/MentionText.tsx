import React from 'react'

/**
 * MentionText — render a plain-text body with `@Display Name` tokens
 * wrapped as subtle teal chips. The mention resolution is authored
 * client-side (see MentionTextarea) and stored server-side, so this
 * component doesn't need to know user IDs — it just needs a list of
 * display names to look for.
 *
 * Kept intentionally simple: no rich text, no line-breaking, no
 * markdown. The composer strips heavy formatting; the feed rewards a
 * calm reading rhythm.
 */

interface Props {
  body: string
  mentionedNames?: string[]
  className?: string
}

export default function MentionText({ body, mentionedNames = [], className }: Props) {
  // Longest names first so "Ada Lovelace" wins over "Ada".
  const names = [...mentionedNames].sort((a, b) => b.length - a.length)

  const pattern = names.length
    ? new RegExp(`@(?:${names.map(escapeRegex).join('|')})(?=\\s|$|[.,;:!?])`, 'g')
    : null

  const parts: React.ReactNode[] = []
  if (!pattern) {
    parts.push(body)
  } else {
    let cursor = 0
    for (const match of body.matchAll(pattern)) {
      const idx = match.index ?? 0
      if (idx > cursor) parts.push(body.slice(cursor, idx))
      parts.push(
        <span
          key={`${idx}-${match[0]}`}
          className="inline-block rounded px-1 font-medium"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          {match[0]}
        </span>,
      )
      cursor = idx + match[0].length
    }
    if (cursor < body.length) parts.push(body.slice(cursor))
  }

  return <span className={className}>{parts}</span>
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
