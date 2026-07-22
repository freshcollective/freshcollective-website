/**
 * Callout colour palette + storage resolver.
 *
 * Storage model on `pathway_step_blocks` rows of type `callout`:
 *   - `caption` holds the colour value — one of:
 *       ``palette:<role>`` (primary/secondary/accent/background)
 *         → resolves against the collective's active palette at render
 *           time; flows through when Collective Home switches palette.
 *       ``custom:#RRGGBB``
 *         → literal hex; preserved verbatim across palette changes.
 *       Legacy key (teal|gold|blue|rose|sage|grey|lilac|orange)
 *         → looks up the historical CALLOUT_COLOURS chip so pre-migration
 *           blocks render byte-identically.
 *   - `label`   optionally holds the creator's purpose key
 *                 (highlight | tip | placeholder | reflection | note)
 *
 * ``container_style`` on any block uses the same encoding.
 *
 * Legacy back-compat: older callouts (created before the new colour system)
 * store info | tip | warning in `label` and have a null `caption`. We map
 * those to default colours when rendering so existing content keeps working
 * without a migration. On first edit, the form prefills the resolved colour
 * into `caption` so the row normalises naturally.
 *
 * The purpose label is creator-facing only — it never renders on the member
 * side. It appears on the block-row badge in Creator Studio so writers can
 * tell their callouts apart at a glance.
 */

import {
  deriveSoftTint,
  parseStoredColour,
  paletteHex,
  type CollectivePaletteMeta,
} from './collectivePalette'

export type CalloutColour =
  | 'teal'
  | 'gold'
  | 'blue'
  | 'rose'
  | 'sage'
  | 'grey'
  | 'lilac'
  | 'orange'

export interface CalloutPalette {
  key: CalloutColour
  label: string  // "Soft teal", etc.
  bg: string     // soft tinted background
  border: string // subtle 1px border, tinted to match
}

export const CALLOUT_COLOURS: readonly CalloutPalette[] = [
  { key: 'teal',   label: 'Soft teal',   bg: '#EAF7F7', border: '#B8E0DE' },
  { key: 'gold',   label: 'Soft gold',   bg: '#FBF5DC', border: '#E8D89A' },
  { key: 'blue',   label: 'Soft blue',   bg: '#EFF6FF', border: '#CFE1FE' },
  { key: 'rose',   label: 'Soft rose',   bg: '#FFF1F2', border: '#FBCFD4' },
  { key: 'sage',   label: 'Soft sage',   bg: '#EFF4ED', border: '#CFDBC9' },
  { key: 'grey',   label: 'Soft grey',   bg: '#F1F5F9', border: '#E2E8F0' },
  { key: 'lilac',  label: 'Soft lilac',  bg: '#F4F0FB', border: '#D5CAE8' },
  { key: 'orange', label: 'Soft orange', bg: '#FFF1E5', border: '#FBD3B0' },
]

/**
 * Default colour for newly created callouts. Today: soft teal.
 *
 * Foundation hook for collective-level branding: future work can add a
 * `default_callout_colour` field on the Space model and pass it as the
 * `defaultColour` argument to `resolveCalloutPalette()` (and to the form's
 * initial state). Until then, every space uses this one constant — but the
 * code no longer hardcodes 'teal' in multiple places.
 */
export const DEFAULT_CALLOUT_COLOUR: CalloutColour = 'teal'

const COLOUR_BY_KEY: Record<string, CalloutPalette> = Object.fromEntries(
  CALLOUT_COLOURS.map(c => [c.key, c]),
)

// Legacy style → colour mapping. Keep existing Week 1 content visually intact.
const LEGACY_TO_COLOUR: Record<string, CalloutColour> = {
  info:    'blue',
  tip:     'teal',
  warning: 'gold',
}

/**
 * Resolve which palette to use for a callout based on its stored values.
 * Handles the three storage flavours in this order:
 *
 *   1. ``palette:<role>`` — resolved against the active collective palette.
 *   2. ``custom:#RRGGBB``  — literal hex.
 *   3. Legacy fixed key (teal, gold, …) — historical CALLOUT_COLOURS chip.
 *   4. Legacy label fallback (info/tip/warning) — reads a default colour.
 *   5. ``defaultColour`` — last-resort fallback.
 *
 * For (1) and (2) the soft ``{ bg, border }`` pair is derived from the
 * resolved hex via ``deriveSoftTint`` so callers see the same
 * ``CalloutPalette`` shape as legacy paths.
 *
 * The optional ``palette`` argument is threaded from the calling page:
 * Server Components read it from ``getSpace(slug).colour_palette``;
 * Client Components pass ``useCollectivePalette()`` in.
 */
export function resolveCalloutPalette(
  caption: string | null | undefined,
  label: string | null | undefined,
  defaultColour: CalloutColour = DEFAULT_CALLOUT_COLOUR,
  palette?: CollectivePaletteMeta | null,
): CalloutPalette {
  const parsed = parseStoredColour(caption)
  if (parsed.kind === 'palette') {
    const hex = paletteHex(parsed.role, palette)
    if (hex) {
      const { bg, border } = deriveSoftTint(hex)
      return { key: 'teal', label: '', bg, border } // ``key`` is unused downstream for palette-driven values
    }
  }
  if (parsed.kind === 'custom') {
    const { bg, border } = deriveSoftTint(parsed.hex)
    return { key: 'teal', label: '', bg, border }
  }
  if (parsed.kind === 'legacy' && COLOUR_BY_KEY[parsed.key]) {
    return COLOUR_BY_KEY[parsed.key]
  }
  if (label && LEGACY_TO_COLOUR[label]) return COLOUR_BY_KEY[LEGACY_TO_COLOUR[label]]
  return COLOUR_BY_KEY[defaultColour]
}

/**
 * Resolve the soft palette for a block's optional `container_style` wrapper,
 * or null when no container is set / the stored value isn't recognised.
 *
 * Handles ``palette:<role>``, ``custom:#hex``, and legacy fixed keys
 * (teal, gold, …). Server-safe (no "use client") so Server Components
 * can call it directly with a palette fetched from ``getSpace``.
 */
export function resolveContainerPalette(
  containerStyle: string | null | undefined,
  palette?: CollectivePaletteMeta | null,
): { bg: string; border: string } | null {
  const parsed = parseStoredColour(containerStyle)
  if (parsed.kind === 'palette') {
    const hex = paletteHex(parsed.role, palette)
    return hex ? deriveSoftTint(hex) : null
  }
  if (parsed.kind === 'custom') {
    return deriveSoftTint(parsed.hex)
  }
  if (parsed.kind === 'legacy' && COLOUR_BY_KEY[parsed.key]) {
    const match = COLOUR_BY_KEY[parsed.key]
    return { bg: match.bg, border: match.border }
  }
  return null
}

// ───────────────────────────────────────────────────────────────────────────
// Purposes — creator-only metadata, never shown to members
// ───────────────────────────────────────────────────────────────────────────

export type CalloutPurpose =
  | 'note'
  | 'tip'
  | 'important'
  | 'caution'
  | 'celebration'
  // Legacy purposes retained so previously-authored blocks still label correctly.
  | 'highlight'
  | 'placeholder'
  | 'reflection'

export interface CalloutPurposeSpec {
  key: CalloutPurpose
  label: string
  icon: string
  defaultColour: CalloutColour
}


/**
 * The five member-facing purposes exposed in the current picker plus the
 * three legacy keys kept for existing content. Icons and default palettes
 * are attached so a writer never has to configure the visual treatment
 * unless they explicitly want to override the default.
 */
export const CALLOUT_PURPOSES: readonly CalloutPurposeSpec[] = [
  { key: 'note',        label: 'Note',        icon: '📝', defaultColour: 'blue'   },
  { key: 'tip',         label: 'Tip',         icon: '💡', defaultColour: 'teal'   },
  { key: 'important',   label: 'Important',   icon: '❗', defaultColour: 'gold'   },
  { key: 'caution',     label: 'Caution',     icon: '⚠️', defaultColour: 'orange' },
  { key: 'celebration', label: 'Celebration', icon: '🎉', defaultColour: 'sage'   },

  // Legacy — still resolvable by resolveCalloutPurposeLabel, still allowed
  // as a stored value; hidden from the new picker via CALLOUT_PURPOSES_PICKER.
  { key: 'highlight',   label: 'Highlight',   icon: '✨', defaultColour: 'gold'   },
  { key: 'placeholder', label: 'Placeholder', icon: '□',  defaultColour: 'grey'   },
  { key: 'reflection',  label: 'Reflection',  icon: '❝',  defaultColour: 'lilac'  },
]


/** The subset shown in the creator picker — the five current purposes. */
export const CALLOUT_PURPOSES_PICKER: readonly CalloutPurposeSpec[] =
  CALLOUT_PURPOSES.slice(0, 5)

const PURPOSE_BY_KEY: Record<string, CalloutPurposeSpec> =
  Object.fromEntries(CALLOUT_PURPOSES.map(p => [p.key, p]))


/**
 * The icon for a given purpose key, or null if the key is not recognised
 * (including legacy info/warning strings — those don't get an icon, only
 * their palette resolves for back-compat).
 */
export function resolveCalloutPurposeIcon(label: string | null | undefined): string | null {
  if (!label) return null
  return PURPOSE_BY_KEY[label]?.icon ?? null
}


/**
 * The default colour for a purpose key. Callers use this to seed the
 * ``caption`` colour when a writer picks a purpose but has not selected
 * a colour explicitly.
 */
export function resolveCalloutPurposeDefaultColour(label: string | null | undefined): CalloutColour | null {
  if (!label) return null
  return PURPOSE_BY_KEY[label]?.defaultColour ?? null
}

// Legacy info/warning don't map cleanly to new purpose keys but should still
// read meaningfully on the creator badge until the row is re-saved.
const LEGACY_TO_PURPOSE_LABEL: Record<string, string> = {
  info:    'Highlight',
  warning: 'Placeholder',
  // 'tip' is already a valid purpose key — resolved via PURPOSE_BY_KEY
}

export function isCalloutPurpose(label: string | null | undefined): boolean {
  return !!label && label in PURPOSE_BY_KEY
}

/**
 * Initial value for the purpose dropdown when the form opens for an
 * existing callout. New-system keys pass through; legacy info/warning
 * map to their nearest new-system equivalent; anything else clears.
 */
export function normaliseCalloutPurpose(label: string | null | undefined): CalloutPurpose | '' {
  if (!label) return ''
  if (label in PURPOSE_BY_KEY) return label as CalloutPurpose
  // Legacy string values from older content.
  if (label === 'info') return 'note'
  if (label === 'warning') return 'caution'
  return ''
}

/**
 * Display label for the purpose, for use on the creator block badge.
 * Returns null if no purpose is set.
 */
export function resolveCalloutPurposeLabel(label: string | null | undefined): string | null {
  if (!label) return null
  if (label in PURPOSE_BY_KEY) return PURPOSE_BY_KEY[label].label
  if (label in LEGACY_TO_PURPOSE_LABEL) return LEGACY_TO_PURPOSE_LABEL[label]
  return null
}
