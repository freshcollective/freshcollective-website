import { starterKitHref } from '@/lib/guides'
import { SERIF_HEADING } from './serif'

/**
 * The Creator Starter Kit, in the two places it appears.
 *
 * Both read one setting — ``guide_settings.starter_kit_url``, edited
 * at ``/admin/guides`` — so they cannot disagree about whether the
 * kit exists. **While that setting is empty, both render `null`**:
 * nothing in the DOM, no placeholder, no disabled button and no
 * "coming soon". Filling the setting in switches both on; clearing it
 * takes both away.
 *
 * The gate lives in ``starterKitHref`` rather than in each component,
 * so "is there a kit" has one answer and a test can assert it without
 * rendering anything.
 *
 * Gold rather than teal, deliberately. The design language reserves
 * gold for marketing emphasis, and this is the one offer on an
 * otherwise unsold page — teal would make it read as ordinary
 * navigation.
 */

const BAND_COPY = {
  heading: 'The free Creator Starter Kit',
  text: 'A printable plan for setting up your Collective and bringing your people with you.',
  action: 'Get the kit',
}

const CARD_COPY = {
  heading: 'Free Creator Starter Kit',
  text: 'A printable plan for moving your people to a home of their own.',
  action: 'Get the kit',
}

/** The wide band at the foot of ``/guides``. */
export function StarterKitBand({ url }: { url: string | null }) {
  const href = starterKitHref(url)
  if (!href) return null

  return (
    <section
      className="flex flex-col gap-6 rounded-2xl bg-gold-50 px-7 py-8 md:flex-row md:items-center md:justify-between md:px-10 md:py-9"
      aria-labelledby="starter-kit-band-heading"
    >
      <div className="max-w-[58ch]">
        <h2
          id="starter-kit-band-heading"
          className="text-[23px] leading-[1.25] text-navy-950 md:text-[25px]"
          style={SERIF_HEADING}
        >
          {BAND_COPY.heading}
        </h2>
        <p className="mt-2 text-[15.5px] leading-[1.65] text-navy-700">
          {BAND_COPY.text}
        </p>
      </div>
      <a
        href={href}
        className="inline-flex shrink-0 items-center justify-center rounded-full bg-gold-600 px-7 py-3 text-[15px] font-semibold text-white transition-colors hover:bg-gold-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-gold-400 focus-visible:ring-offset-2"
      >
        {BAND_COPY.action}
      </a>
    </section>
  )
}

/** The card in a Guide's side column, under "On this page". */
export function StarterKitCard({ url }: { url: string | null }) {
  const href = starterKitHref(url)
  if (!href) return null

  return (
    <aside
      className="rounded-2xl bg-gold-50 px-6 py-6"
      aria-labelledby="starter-kit-card-heading"
    >
      <h2
        id="starter-kit-card-heading"
        className="text-[18px] leading-[1.3] text-navy-950"
        style={SERIF_HEADING}
      >
        {CARD_COPY.heading}
      </h2>
      <p className="mt-2 text-[14px] leading-[1.6] text-navy-700">
        {CARD_COPY.text}
      </p>
      <a
        href={href}
        className="mt-4 inline-flex items-center gap-1.5 rounded-sm text-[14.5px] font-semibold text-gold-600 transition-colors hover:text-gold-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-gold-400 focus-visible:ring-offset-2"
      >
        {CARD_COPY.action}
        <span aria-hidden="true">→</span>
      </a>
    </aside>
  )
}
