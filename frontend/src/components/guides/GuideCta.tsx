import type { GuideArticle } from '@/lib/guides'
import { safeHref } from '@/lib/safeHref'
import { SERIF_HEADING } from './serif'

/**
 * A Guide's own call to action, at the end of the article.
 *
 * The end rather than mid-article: interrupting the reading column
 * needs a rule for *which* paragraph it breaks, and any such rule
 * misbehaves on a short Guide with one heading. Here it reaches
 * someone who finished, and never pushes the article apart.
 *
 * Shaped like the mockup's mid-article card — rounded, a tinted
 * thumbnail tile on the left, serif heading, one line, one action —
 * so the MailerLite form that replaces the button in a later week
 * drops into the same card without a redesign.
 *
 * Renders nothing unless all four fields are set. The database
 * enforces all-or-nothing too, so this is the display half of a
 * guarantee rather than the only check.
 */
export default function GuideCta({ guide }: { guide: GuideArticle }) {
  const href = safeHref(guide.cta_href)
  if (!guide.cta_heading || !guide.cta_text || !guide.cta_label || !href) {
    return null
  }

  const external = /^https?:\/\//i.test(href)

  return (
    <section
      className="my-12 flex flex-col gap-6 rounded-2xl bg-white px-6 py-7 sm:flex-row sm:items-center md:px-8"
      style={{
        boxShadow:
          '0 1px 3px rgba(15,30,55,0.05), 0 0 0 1px rgba(15,30,55,0.08)',
      }}
      aria-labelledby="guide-cta-heading"
    >
      <div
        aria-hidden="true"
        className="flex h-[108px] w-[108px] shrink-0 items-center justify-center rounded-xl bg-gold-50 px-3 text-center font-serif text-[14px] leading-[1.3] text-gold-600"
      >
        {guide.cta_label}
      </div>

      <div className="min-w-0">
        <h2
          id="guide-cta-heading"
          className="text-[21px] leading-[1.28] text-navy-950 md:text-[23px]"
          style={SERIF_HEADING}
        >
          {guide.cta_heading}
        </h2>
        <p className="mt-2 text-[15.5px] leading-[1.65] text-navy-700">
          {guide.cta_text}
        </p>
        <a
          href={href}
          {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
          className="mt-5 inline-flex items-center justify-center rounded-full bg-teal-700 px-6 py-2.5 text-[14.5px] font-semibold text-white transition-colors hover:bg-teal-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2"
        >
          {guide.cta_label}
        </a>
      </div>
    </section>
  )
}
