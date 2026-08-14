'use client'

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'

/**
 * MentionTextarea — a textarea that watches for `@` and pops a small
 * autocomplete over member suggestions from the current collective.
 *
 * On select, the token `@Display Name` is inserted into the body and
 * the member's ID is appended to `mentionedIds`. The parent form sends
 * both the body and the resolved ID list to the server.
 *
 * Scope: `spaceSlug` — search is strictly limited to this collective.
 */

export interface MemberSuggestion {
  id: string
  display_name: string
  avatar_url?: string | null
  role: string
}

interface Props {
  spaceSlug: string
  value: string
  onChange: (value: string) => void
  onMentionedIdsChange: (ids: string[]) => void
  mentionedIds: string[]
  placeholder?: string
  rows?: number
  className?: string
  ariaLabel?: string
}

// Public handle so parents can focus / clear.
export interface MentionTextareaHandle {
  focus: () => void
  clear: () => void
}

const TRIGGER_RE = /(?:^|\s)@([A-Za-z0-9_ '\-]{0,40})$/

const MentionTextarea = forwardRef<MentionTextareaHandle, Props>(function MentionTextarea({
  spaceSlug, value, onChange, onMentionedIdsChange, mentionedIds, placeholder, rows = 3, className, ariaLabel,
}: Props, ref) {
  const taRef = useRef<HTMLTextAreaElement>(null)
  const [suggestions, setSuggestions] = useState<MemberSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const [query, setQuery] = useState('')

  useImperativeHandle(ref, () => ({
    focus: () => taRef.current?.focus(),
    clear: () => {
      onChange('')
      onMentionedIdsChange([])
      setOpen(false)
      setSuggestions([])
    },
  }))

  // Fetch suggestions when the query changes (debounced).
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    const t = setTimeout(async () => {
      try {
        const url = apiUrl(`/api/spaces/${spaceSlug}/members/search?q=${encodeURIComponent(query)}&limit=8`)
        const res = await fetch(url, { credentials: 'include', signal: controller.signal })
        if (!res.ok) return
        const data = (await res.json()) as MemberSuggestion[]
        setSuggestions(data)
        setActiveIdx(0)
      } catch {
        // aborted or transient network error — leave suggestions as-is
      }
    }, 120)
    return () => { clearTimeout(t); controller.abort() }
  }, [query, open, spaceSlug])

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const next = e.target.value
    onChange(next)

    const cursor = e.target.selectionStart ?? next.length
    const before = next.slice(0, cursor)
    const m = TRIGGER_RE.exec(before)
    if (m) {
      setQuery(m[1] ?? '')
      setOpen(true)
    } else {
      setOpen(false)
    }
  }

  function select(member: MemberSuggestion) {
    const ta = taRef.current
    if (!ta) return
    const cursor = ta.selectionStart ?? value.length
    const before = value.slice(0, cursor)
    const after = value.slice(cursor)
    // Replace the in-progress "@partial" (with any leading whitespace kept).
    const replaced = before.replace(TRIGGER_RE, (whole, _typed) => {
      const leading = whole.startsWith(' ') || whole.startsWith('\n') ? whole[0] : ''
      return `${leading}@${member.display_name} `
    })
    const nextValue = replaced + after
    onChange(nextValue)
    if (!mentionedIds.includes(member.id)) {
      onMentionedIdsChange([...mentionedIds, member.id])
    }
    setOpen(false)
    setSuggestions([])
    setTimeout(() => {
      ta.focus()
      const pos = replaced.length
      ta.setSelectionRange(pos, pos)
    }, 0)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!open || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      select(suggestions[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="relative">
      <textarea
        ref={taRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        rows={rows}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className={className ?? 'w-full resize-none rounded-lg border border-border bg-surface px-4 py-3 text-sm leading-relaxed text-navy-900 placeholder:text-slate-300 focus:border-[color:var(--fc-accent,#38A09E)] focus:outline-none focus:ring-2 focus:ring-[color:var(--fc-accent-soft,rgba(56,160,158,0.10))]'}
      />
      {open && suggestions.length > 0 && (
        <div
          className="absolute z-20 mt-1 max-h-56 w-64 overflow-y-auto rounded-lg bg-white shadow-lg"
          style={{ border: '1px solid rgba(12,24,38,0.10)' }}
        >
          {suggestions.map((s, i) => (
            <button
              key={s.id}
              type="button"
              onClick={() => select(s)}
              onMouseEnter={() => setActiveIdx(i)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px]"
              style={{
                background: i === activeIdx ? 'rgba(56,160,158,0.08)' : 'transparent',
                color: '#0C1826',
              }}
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-semibold text-slate-600">
                {(s.display_name || '?').slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1 truncate">{s.display_name}</span>
              {s.role !== 'learner' && (
                <span className="text-[10px] text-slate-500 uppercase tracking-wide">{s.role}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
})

export default MentionTextarea
