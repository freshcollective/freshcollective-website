/**
 * World Management colour hierarchy — the design rule for every WM surface.
 *
 * Every accent on a World Management page (Mother World, Collectives,
 * Creators, Members, Commerce, and every future page) belongs to one of
 * these four hues. Prefer teal before introducing any other accent. Do
 * NOT add a fifth accent colour without a compelling product reason.
 *
 * ┌──────────────┬──────────────────────────────────────┬──────────────┐
 * │ Priority     │ Meaning                              │ Frequency    │
 * ├──────────────┼──────────────────────────────────────┼──────────────┤
 * │ 🟢 teal      │ Primary / Positive / Active          │ Most often   │
 * │              │ - Primary actions                    │              │
 * │              │ - Healthy states                     │              │
 * │              │ - Revenue                            │              │
 * │              │ - Creators                           │              │
 * │              │ - Active selections                  │              │
 * │              │ - Success states                     │              │
 * │              │ - Primary icons                      │              │
 * ├──────────────┼──────────────────────────────────────┼──────────────┤
 * │ 🔵 navy      │ Information / Neutral                │ Second most  │
 * │              │ - Members                            │              │
 * │              │ - General information                │              │
 * │              │ - Neutral metrics (Gross Volume)     │              │
 * │              │ - Informational badges               │              │
 * │              │ - Secondary icons                    │              │
 * ├──────────────┼──────────────────────────────────────┼──────────────┤
 * │ 🟡 gold      │ Ownership / Premium / Important      │ Sparingly    │
 * │              │ - Owner                              │              │
 * │              │ - Premium or featured items          │              │
 * │              │ - World-level settings               │              │
 * │              │ - Important notices                  │              │
 * │              │ - Test mode information              │              │
 * │              │ - Non-critical warnings              │              │
 * ├──────────────┼──────────────────────────────────────┼──────────────┤
 * │ 🪸 coral     │ Attention Required                   │ Rarely       │
 * │              │ - Pending creator payouts            │              │
 * │              │ - Failed payments                    │              │
 * │              │ - Refunds                            │              │
 * │              │ - Health warnings                    │              │
 * │              │ - Over limits                        │              │
 * │              │ - Errors                             │              │
 * │              │ - Anything requiring caretaker       │              │
 * │              │   action                             │              │
 * └──────────────┴──────────────────────────────────────┴──────────────┘
 *
 * **Principles:**
 * - Prefer teal before introducing any other accent colour.
 * - Use navy as the default neutral accent.
 * - Gold should feel premium and uncommon — reserve it for owner,
 *   platform-wide notices, and test-mode reminders.
 * - Coral should immediately draw attention because it is used
 *   sparingly. Never use coral for decorative accents; only when a
 *   caretaker genuinely needs to act.
 * - If in doubt, teal.
 *
 * **Conditional coral (the "attention" pattern):**
 * Some cards toggle between neutral and coral based on whether the value
 * itself represents an action item. Example: `Pending creator payouts`
 * reads as navy when zero (nothing owed) and shifts to coral only when
 * there is a real balance a caretaker should act on. Follow the same
 * conditional pattern anywhere else this idea repeats — coral should
 * always earn its presence.
 *
 * **Alignment with Mother World HUE:**
 * These constants match the Mother World HUE palette already used across
 * Collectives, Creators, and Members. They are grouped here so a page
 * author can see the hierarchy at a glance and pick the right accent
 * for each surface without re-deriving it from a screenshot.
 */

export const WM_HUE = {
  teal: {
    dot:    '#22a598',
    text:   '#0f766e',
    bg:     'rgba(56, 160, 158, 0.10)',
    border: 'rgba(56, 160, 158, 0.30)',
  },
  navy: {
    dot:    '#4c78d4',
    text:   '#1e40af',
    bg:     'rgba(56, 116, 180, 0.10)',
    border: 'rgba(56, 116, 180, 0.30)',
  },
  gold: {
    dot:    '#d4b048',
    text:   '#8A6A15',
    bg:     'rgba(212, 176, 72, 0.10)',
    border: 'rgba(212, 176, 72, 0.28)',
  },
  coral: {
    dot:    '#d66057',
    text:   '#a63c30',
    bg:     'rgba(214, 96, 87, 0.08)',
    border: 'rgba(214, 96, 87, 0.28)',
  },
} as const

export type WMHue = keyof typeof WM_HUE
