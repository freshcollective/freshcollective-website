# Design Principles — Fresh Collective

## Brand Feel

Every design decision should support this feeling:

| Quality | What it means in practice |
|---|---|
| **Calm** | No visual noise. White space does the work. |
| **Warm** | Soft tones, approachable type, nothing cold or corporate. |
| **Intelligent** | Considered layout. Nothing gratuitous. Type hierarchy that guides the eye. |
| **Spacious** | Generous padding and margins. Let content breathe. |
| **Grounded** | Stable layouts. No tricks. Reliable and predictable structure. |
| **Feminine but not soft** | Refined, not pastel-heavy. Elegant, not delicate. |
| **Premium but human** | High quality without feeling untouchable or distant. |
| **Simple** | Every element earns its place. Remove what doesn't serve. |
| **Practical** | Designed to be used, not admired. |

---

## Visual Style

### Colour Palette

**Approved direction:** white or near-white background, with navy, teal, and gold accents and supporting tints/shades.

| Role | Colour | Value |
|---|---|---|
| **Background** | Warm off-white | `#FAFAF8` |
| **Surface** (cards, header) | White | `#FFFFFF` |
| **Navy** (headings, depth, footer) | Deep navy | `#1C2B4A` |
| **Teal** (buttons, links, active states) | Brand teal | `#3D8B8A` |
| **Gold** (warmth, emphasis, premium details) | Warm gold | `#B8902A` |
| **Border** | Warm grey | `#E2DDD5` |
| **Text: secondary** | Slate | `#4A5568` |
| **Text: muted** | Light slate | `#718096` |

Each of the three accent colours (navy, teal, gold) has a full tint/shade range defined in `src/app/globals.css` for use in cards, hover states, backgrounds, and borders.

**Palette feel:** calm, spacious, premium, grounded. Warm without being beige. Feminine without being pastel. Navy is depth, not dominance — the background stays light.

Avoid:
- Dark, heavy dashboard palettes (navy should accent, not fill)
- Bright cyan, harsh blue, mustard, orange-gold, hot pink, or purple
- Colour combinations that feel busy or corporate
- Overly beige or greige palettes

### Typography
- Use elegant, readable typefaces
- Clear hierarchy: heading, subheading, body, caption
- Do not use too many font weights
- Favour generous line height for readability

### Spacing
- Use generous padding and margins throughout
- Cards and sections should feel spacious, not cramped
- Content should never feel crammed together

### Components
- Rounded cards — consistent corner radius across the UI
- Soft shadows where needed (subtle, not heavy)
- Clean dividers or whitespace to separate sections (not hard lines)

### Animation and Motion
- Use gentle animation only when it supports a sense of calm
- No animation for its own sake
- No jarring transitions, pop-ins, or distractions
- Favour fade and ease transitions

---

## Layout Philosophy

- Light, not dark — the dashboard and member area should feel airy and open
- Uncluttered — show the member one clear thing at a time where possible
- Progressive disclosure — simple on the surface, depth available underneath
- Mobile-first — design for phone first, then expand to desktop
- Content-first — layout serves the content, not the other way around

---

## Accessibility

- Sufficient colour contrast on all text
- Keyboard navigable components
- Screen reader compatible structure
- Do not rely on colour alone to convey meaning
- Accessible form labels and error states

---

## Tone of Voice

Copy on the platform should feel: **warm, clear, direct, grounded, emotionally intelligent.**

Write to one woman, not a crowd.

### What to avoid

| Avoid | Use instead |
|---|---|
| Corporate jargon ("leverage", "synergy", "optimise") | Plain, human language |
| Generic AI language (vague, hollow, filler phrases) | Specific, real, earned language |
| Overpromising ("transform your life in 7 days") | Honest, grounded outcomes |
| Cold or transactional tone | Warm, connected, inviting |
| Long blocks of copy | Short sentences. White space. Room to breathe. |

### Copy principles

- Short sentences
- Active voice
- Specificity over generality
- One idea per sentence where possible
- Avoid unnecessary adverbs and intensifiers
- Do not hedge excessively
- Trust the reader's intelligence

---

## What This Platform Should Never Feel Like

- A heavy online course portal
- A corporate SaaS dashboard
- A cluttered content library
- A cold or transactional product
- A platform that overwhelms or rushes the member
