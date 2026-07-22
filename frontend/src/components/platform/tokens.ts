/**
 * Fresh Collective Design Language — TypeScript Token Layer
 *
 * Mirror of the CSS custom properties in `styles/fc-tokens.css`, exposed
 * for use inside React components (motion durations, z-index constants,
 * breakpoint queries, semantic colour lookups). Whenever a value must be
 * consumed by JavaScript rather than CSS, it lives here.
 *
 * DO NOT hard-code Fresh Collective values elsewhere. Import from this file.
 */

// ---------------------------------------------------------------------------
// Colour — semantic tokens
// ---------------------------------------------------------------------------

export const colors = {
  surface: {
    page: 'var(--fc-surface-page)',
    card: 'var(--fc-surface-card)',
    canvasWarm: 'var(--fc-surface-canvas-warm)',
    inverse: 'var(--fc-surface-inverse)',
    inverseDeep: 'var(--fc-surface-inverse-deep)',
    muted: 'var(--fc-surface-muted)',
  },
  ink: {
    primary: 'var(--fc-ink-primary)',
    inverse: 'var(--fc-ink-inverse)',
    heading: 'var(--fc-ink-heading)',
    headingInverse: 'var(--fc-ink-heading-inverse)',
    disabled: 'var(--fc-ink-disabled)',
  },
  accent: {
    500: 'var(--fc-accent-500)',
    400: 'var(--fc-accent-400)',
    700: 'var(--fc-accent-700)',
    50: 'var(--fc-accent-50)',
    gradient: 'var(--fc-accent-gradient)',
  },
  status: {
    success: 'var(--fc-status-success)',
    pending: 'var(--fc-status-pending)',
    neutral: 'var(--fc-status-neutral)',
    warning: 'var(--fc-status-warning)',
    error: 'var(--fc-status-error)',
    successBg: 'var(--fc-status-success-bg)',
    pendingBg: 'var(--fc-status-pending-bg)',
    neutralBg: 'var(--fc-status-neutral-bg)',
    warningBg: 'var(--fc-status-warning-bg)',
    errorBg: 'var(--fc-status-error-bg)',
    errorText: 'var(--fc-status-error-text)',
  },
} as const

// ---------------------------------------------------------------------------
// Pathway palette — small colour hint used only for dots + drawer stripes.
// ---------------------------------------------------------------------------

export type PathwayKey =
  | 'teal' | 'navy' | 'blue' | 'lilac' | 'sage' | 'grey'

export const pathwayColor: Record<PathwayKey, string> = {
  teal:  'var(--fc-pathway-teal)',
  navy:  'var(--fc-pathway-navy)',
  blue:  'var(--fc-pathway-blue)',
  lilac: 'var(--fc-pathway-lilac)',
  sage:  'var(--fc-pathway-sage)',
  grey:  'var(--fc-pathway-grey)',
}

// ---------------------------------------------------------------------------
// Content-type palette — icon container + type badge accent.
// ---------------------------------------------------------------------------

export type TypeKey =
  | 'audio' | 'video' | 'guide' | 'file' | 'link' | 'other'

export const typeColor: Record<TypeKey, { fg: string; bg: string }> = {
  audio:  { fg: 'var(--fc-type-audio)',  bg: 'var(--fc-type-audio-bg)'  },
  video:  { fg: 'var(--fc-type-video)',  bg: 'var(--fc-type-video-bg)'  },
  guide:  { fg: 'var(--fc-type-guide)',  bg: 'var(--fc-type-guide-bg)'  },
  file:   { fg: 'var(--fc-type-file)',   bg: 'var(--fc-type-file-bg)'   },
  link:   { fg: 'var(--fc-type-link)',   bg: 'var(--fc-type-link-bg)'   },
  other:  { fg: 'var(--fc-type-other)',  bg: 'var(--fc-type-other-bg)'  },
}

// ---------------------------------------------------------------------------
// Motion — durations (ms) and easings (cubic-bezier strings).
// ---------------------------------------------------------------------------

export const motion = {
  duration: {
    hover:  120,
    card:   220,
    menu:   140,
    drawer: 240,
    modal:  180,
    toast:  220,
    page:   700,
  },
  easing: {
    out:      'cubic-bezier(0.16, 1, 0.3, 1)',
    drawer:   'cubic-bezier(0.22, 0.61, 0.36, 1)',
    standard: 'ease-out',
  },
} as const

// ---------------------------------------------------------------------------
// Z-index — layering order.
// ---------------------------------------------------------------------------

export const zIndex = {
  base: 0,
  dropdown: 30,
  sticky: 40,
  drawerBackdrop: 50,
  drawer: 51,
  modalBackdrop: 60,
  modal: 61,
  toast: 80,
  tooltip: 90,
} as const

// ---------------------------------------------------------------------------
// Breakpoints — mobile-first.
// ---------------------------------------------------------------------------

export const breakpoint = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
} as const

export const mediaQuery = {
  sm: `(min-width: ${breakpoint.sm}px)`,
  md: `(min-width: ${breakpoint.md}px)`,
  lg: `(min-width: ${breakpoint.lg}px)`,
  xl: `(min-width: ${breakpoint.xl}px)`,
} as const

// ---------------------------------------------------------------------------
// Spacing — scale in pixels. Referenced when JS must compute layout.
// ---------------------------------------------------------------------------

export const spacing = {
  0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40, 12: 48, 16: 64,
} as const

// ---------------------------------------------------------------------------
// Radius — for JS-side references (drawer corners, avatar sizes).
// ---------------------------------------------------------------------------

export const radius = {
  sm: 6, md: 8, lg: 12, xl: 16, '2xl': 20, full: 9999,
} as const
