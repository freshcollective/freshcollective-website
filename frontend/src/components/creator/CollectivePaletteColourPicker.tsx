'use client'

/**
 * CollectivePaletteColourPicker
 *
 * The shared "pick a colour" surface for every creator-authored block
 * that used to have its own hard-coded chip row: callout tint,
 * container tint, button colour, About-page accents, etc.
 *
 * Two-row layout:
 *
 *   [ Your palette ]
 *   ▢ Primary   ▢ Secondary   ▢ Accent   ▢ Background     (swatches)
 *
 *   [ More colours ▾ ]  ← native <input type="color"> + validated hex
 *
 * A picked palette swatch stores ``palette:<role>`` — the block
 * flows through when the creator later switches Collective Home to a
 * different palette. A picked hex from "More colours…" stores
 * ``custom:#RRGGBB`` — the value is preserved verbatim across future
 * palette changes.
 *
 * ``allowClear`` shows a "None" chip that stores ``null`` — used by
 * the container-tint picker (where "no container" is a valid state)
 * and *not* used by the callout picker (a callout always has a
 * colour).
 *
 * The picker only cares about the storage encoding. It does not know
 * whether the caller will render the value as a solid fill (button)
 * or a soft tint (callout/container) — the caller resolves that at
 * render time via ``resolveHex()`` + ``deriveSoftTint()`` from
 * ``@/lib/collectivePalette``.
 */

import { useEffect, useRef, useState } from 'react'
import { useCollectivePalette } from '@/components/collective/CollectivePaletteContext'
import {
  PALETTE_ROLES,
  PALETTE_ROLE_LABEL,
  encodeCustomHex,
  encodePaletteRole,
  isValidHex,
  parseStoredColour,
  type PaletteRole,
} from '@/lib/collectivePalette'


interface Props {
  /** Stored value: ``palette:role``, ``custom:#hex``, legacy key, or null. */
  value: string | null
  onChange: (next: string | null) => void
  /** Show a "None" chip that stores null. Default: false. */
  allowClear?: boolean
  /** Optional label above the swatch row. Default: "Your palette". */
  label?: string
  /** Aria-label for the whole group; default is derived from ``label``. */
  ariaLabel?: string
}


export default function CollectivePaletteColourPicker({
  value, onChange, allowClear = false, label = 'Your palette', ariaLabel,
}: Props) {
  const palette = useCollectivePalette()
  const parsed = parseStoredColour(value)

  const [customOpen, setCustomOpen] = useState(false)
  const customRef = useRef<HTMLDivElement | null>(null)
  const [hexDraft, setHexDraft] = useState<string>(
    parsed.kind === 'custom' ? parsed.hex : '',
  )
  const [hexError, setHexError] = useState<string | null>(null)

  // Close the "More colours" popover on outside click / Escape.
  useEffect(() => {
    if (!customOpen) return
    function onDown(e: MouseEvent) {
      if (!customRef.current) return
      if (!customRef.current.contains(e.target as Node)) setCustomOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setCustomOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [customOpen])

  function pickPaletteRole(role: PaletteRole) {
    onChange(encodePaletteRole(role))
    setCustomOpen(false)
  }

  function pickCustomHex(hex: string) {
    const cleaned = hex.trim()
    if (!isValidHex(cleaned)) {
      setHexError('Please enter a valid hex colour (e.g. #3A6B7A).')
      return
    }
    setHexError(null)
    onChange(encodeCustomHex(cleaned))
  }

  const currentCustomHex = parsed.kind === 'custom' ? parsed.hex : ''
  const selectedRole: PaletteRole | null = parsed.kind === 'palette' ? parsed.role : null
  const isLegacy = parsed.kind === 'legacy'

  return (
    <div className="flex flex-col gap-2" aria-label={ariaLabel ?? label}>
      {palette ? (
        <>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
              {label}
            </span>
            {palette.name && (
              <span className="text-[11.5px] italic text-slate-500">
                {palette.name}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
            {allowClear && (
              <ClearSwatch
                selected={parsed.kind === 'none'}
                onSelect={() => onChange(null)}
              />
            )}
            {PALETTE_ROLES.map((role) => (
              <PaletteSwatch
                key={role}
                role={role}
                hex={palette.palette[role]}
                selected={selectedRole === role}
                onSelect={() => pickPaletteRole(role)}
              />
            ))}
            <MoreColoursButton
              currentCustomHex={currentCustomHex}
              customSelected={parsed.kind === 'custom'}
              open={customOpen}
              onToggle={() => setCustomOpen((v) => !v)}
            />
          </div>
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {allowClear && (
            <ClearSwatch
              selected={parsed.kind === 'none'}
              onSelect={() => onChange(null)}
            />
          )}
          <MoreColoursButton
            currentCustomHex={currentCustomHex}
            customSelected={parsed.kind === 'custom'}
            open={customOpen}
            onToggle={() => setCustomOpen((v) => !v)}
          />
        </div>
      )}

      {isLegacy && (
        <p className="text-[11.5px] italic text-slate-500">
          Using a preset colour from a previous version. Pick a palette or custom colour to update this block.
        </p>
      )}

      {customOpen && (
        <div
          ref={customRef}
          className="mt-1 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
        >
          <input
            type="color"
            value={isValidHex(hexDraft) ? hexDraft : (currentCustomHex || '#38A09E')}
            onChange={(e) => {
              const v = e.target.value
              setHexDraft(v)
              setHexError(null)
              // Live-apply so the caller can preview.
              if (isValidHex(v)) onChange(encodeCustomHex(v))
            }}
            className="h-8 w-10 cursor-pointer rounded border border-slate-200 p-0"
            aria-label="Visual colour picker"
          />
          <input
            type="text"
            value={hexDraft || currentCustomHex}
            onChange={(e) => setHexDraft(e.target.value)}
            onBlur={() => {
              if (hexDraft) pickCustomHex(hexDraft)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                pickCustomHex(hexDraft)
              }
            }}
            className="w-28 rounded border border-slate-200 px-2 py-1 text-[13px] font-mono text-navy-900 outline-none focus:border-teal-400"
            placeholder="#3A6B7A"
            aria-label="Hex colour code"
          />
          {hexError && (
            <span className="text-[11.5px] text-red-600">{hexError}</span>
          )}
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PaletteSwatch({
  role, hex, selected, onSelect,
}: {
  role: PaletteRole
  hex: string
  selected: boolean
  onSelect: () => void
}) {
  const label = PALETTE_ROLE_LABEL[role]
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`${label} — ${hex}`}
      title={`${label} · ${hex}`}
      className={`flex h-8 w-8 items-center justify-center rounded-full border-2 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
        selected ? 'border-navy-900 shadow-inner' : 'border-white shadow'
      }`}
      style={{ background: hex }}
    >
      {selected && (
        <svg width="12" height="10" viewBox="0 0 12 10" aria-hidden="true">
          <path d="M1.5 5 L4.5 8 L10.5 2" stroke="#FFFFFF" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  )
}


function ClearSwatch({ selected, onSelect }: { selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      aria-label="No colour"
      title="No colour"
      className={`flex h-8 w-8 items-center justify-center rounded-full border-2 bg-white transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
        selected ? 'border-navy-900' : 'border-slate-300'
      }`}
    >
      <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
        <line x1="3" y1="17" x2="17" y2="3" stroke="#94a3b8" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </button>
  )
}


function MoreColoursButton({
  currentCustomHex, customSelected, open, onToggle,
}: {
  currentCustomHex: string
  customSelected: boolean
  open: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-pressed={customSelected}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
        customSelected
          ? 'border-navy-900 bg-white text-navy-900'
          : 'border-slate-300 bg-white text-slate-700 hover:border-teal-300 hover:text-teal-700'
      }`}
      title={customSelected ? `Custom colour ${currentCustomHex}` : 'Pick a custom colour'}
    >
      {customSelected && currentCustomHex ? (
        <span
          className="inline-block h-3.5 w-3.5 rounded-full border border-white shadow"
          style={{ background: currentCustomHex }}
          aria-hidden="true"
        />
      ) : (
        <span aria-hidden="true" className="text-[13px]">＋</span>
      )}
      More colours…
    </button>
  )
}
