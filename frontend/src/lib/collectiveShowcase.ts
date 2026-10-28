/**
 * "See what you can create." — four real screenshots of Moonlit
 * Circle, the demonstration Collective, shown on /for-creators.
 *
 * Copy and asset metadata live here rather than in the component for
 * the same reason the creator FAQ and the About story do: a test can
 * assert they survived an edit.
 *
 * Two things are deliberate and easy to undo by accident:
 *
 *   * **These are static files.** Nothing here reaches Moonlit
 *     Circle's API, and nothing links into it. The Collective is
 *     private and stays private; what is public is four approved
 *     pictures of it. No entry in this list may become a URL into
 *     ``/spaces/moonlit-circle``.
 *   * **The real pixel dimensions.** They are recorded so the frame
 *     can reserve its box and ``next/image`` can reason about the
 *     aspect without measuring. The four shapes are genuinely
 *     different — 1.20, 0.68, 0.98 and 1.47 — and the gallery is
 *     built around that rather than cropping them into agreement.
 */

export interface ShowcaseShot {
  id: string
  /** Tab label on the preview control. */
  label: string
  /** The line that changes under the frame when this is selected. */
  description: string
  src: string
  alt: string
  width: number
  height: number
}

export const SHOWCASE_HEADING = 'See what you can create.'

export const SHOWCASE_INTRO =
  'Every Collective has its own personality. Here’s a little look '
  + 'inside Moonlit Circle, a demonstration Collective created on '
  + 'Fresh Collective.'

/** The one shown before anybody chooses. */
export const SHOWCASE_DEFAULT_ID = 'collective-home'

export const SHOWCASE_SHOTS: readonly ShowcaseShot[] = [
  {
    id: 'collective-home',
    label: 'Your Collective',
    description: 'A beautiful home for your community.',
    src: '/for-creators/collective-home.webp',
    alt:
      'Moonlit Circle’s Collective Home: an island banner over the '
      + 'Collective’s name and tagline, its navigation, and tiles for '
      + 'Gatherings, Pathways and Offerings.',
    width: 1097,
    height: 911,
  },
  {
    id: 'pathway-step',
    label: 'Pathways',
    description:
      'Create guided experiences with videos, exercises and reflections.',
    src: '/for-creators/pathway-step.webp',
    alt:
      'A Pathway step called “Create Your Evening Ritual”, with the '
      + 'Pathway’s step navigation beside it, an embedded video, an '
      + 'exercise block and a reflection prompt.',
    width: 1070,
    height: 1579,
  },
  {
    id: 'gatherings',
    label: 'Gatherings',
    description:
      'Bring people together with sessions, events and bookable experiences.',
    src: '/for-creators/gatherings.webp',
    alt:
      'The “Sunday Slow Down” Gathering Series: its banner artwork, '
      + 'description, ways to join, and a schedule of upcoming '
      + 'sessions.',
    width: 1045,
    height: 1068,
  },
  {
    id: 'offerings',
    label: 'Offerings',
    description: 'Share free and paid digital resources.',
    src: '/for-creators/offerings.webp',
    alt:
      'Moonlit Circle’s Offerings: a paid PDF guide and a free audio '
      + 'meditation, each with cover artwork, alongside the '
      + 'Collective’s sidebar.',
    width: 1099,
    height: 747,
  },
]

/** Convenience for the component and its tests. */
export function showcaseShot(id: string): ShowcaseShot {
  const shot = SHOWCASE_SHOTS.find((s) => s.id === id)
  if (!shot) throw new Error(`unknown showcase shot: ${id}`)
  return shot
}
