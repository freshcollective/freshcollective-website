import Image from 'next/image'

/**
 * The kit as three printed pages on a desk.
 *
 * Exported pages of the PDF itself — the cover square to the reader
 * with two worksheets fanned behind it, so the thing being offered
 * is visible before anyone types an address. The pages are real
 * pages, not a mockup: whatever the workbook actually looks like is
 * what this shows.
 *
 * All three exports are the same A4-at-96dpi size, which is what
 * lets one width and one aspect drive the whole stack — the backs
 * take the cover's width and differ only in rotation.
 *
 * The fan is wider than the cover, because the backs rotate out
 * beyond it, and the wrapper is sized to the *cover* — so the
 * stickout has to stay inside the page on its own.
 *
 * **The binding width is 1024px, not 320px.** It is the moment the
 * two-column layout arrives: the stack goes from centred in a full
 * width column to hard against the left edge of a narrow one, with
 * only the container's 40px gutter beside it. A first attempt put
 * the left page 46px off-screen there and nowhere else, because
 * every wider desktop has margin to spare and every narrower screen
 * centres the stack. Hence the gentler angles and ``lg:pl-8``, both
 * measured at 1024 rather than guessed at 1440.
 *
 * Rotation is about the *bottom* of each page, which swings the top
 * corners roughly twice as far sideways as rotating about the
 * centre would. That is what makes a tilt of a few degrees reach as
 * far as it does, and it is why these numbers do not look like they
 * ought to be enough.
 *
 * Nothing above this clips, so a tilt that outgrew its room would
 * be cut off by the viewport rather than scroll the page — which is
 * why the widths are swept rather than eyeballed.
 */

/** Intrinsic size of every export: A4 at 96dpi. */
const PAGE_W = 794
const PAGE_H = 1123

/**
 * Rendered cover width per breakpoint, smallest first.
 *
 * Phones get the smaller stack, above the reading copy rather than
 * beside it — the single column puts it there for free, since this
 * sits at the top of the left column.
 */
const SIZES = '(min-width: 1024px) 236px, (min-width: 640px) 208px, 176px'

/**
 * None of the three is lazy, because all three are above the fold on
 * a phone and Next flagged a lazy back page as the LCP element. The
 * cover takes ``priority`` (preload + high fetch priority) since it
 * is the one carrying meaning; the backs are merely ``eager``, so
 * they do not queue behind the viewport but do not compete with the
 * header artwork for bandwidth either. Optimised, the three come to
 * about 93KB at the widths actually rendered.
 */

/** Paper: a hairline edge and a barely-there corner, on all three. */
const SHEET = 'h-auto w-full rounded-[3px]'

const SHEET_RING = '0 0 0 1px rgba(15,30,55,0.09)'

export default function KitPreview() {
  // Centred until the two-column layout arrives. Left-aligning it at
  // tablet width puts the fanned-out left page into the page gutter,
  // because the stack sits at the column's left edge and the tilt
  // reaches ~40px beyond it; centred, the stack reads as a figure
  // above the text, which is what it is.
  return (
    <div className="mb-9 flex justify-center lg:mb-12 lg:justify-start lg:pl-8">
      {/* ``group`` so the fan opens a little as a whole rather than
          each page answering the pointer for itself. */}
      <div className="group relative w-[176px] sm:w-[208px] lg:w-[236px]">
        {/* Back left. Decorative: the cover below carries the only
            description that tells a reader anything, and three alt
            texts for one object would be read out as three objects. */}
        <Image
          src="/starter-kit/page-9.png"
          alt=""
          aria-hidden="true"
          width={PAGE_W}
          height={PAGE_H}
          sizes={SIZES}
          loading="eager"
          className={
            `absolute left-0 top-0 z-0 origin-bottom -translate-x-[6%] translate-y-[1%] -rotate-[7deg] ${SHEET} `
            + 'motion-safe:transition-transform motion-safe:duration-300 motion-safe:ease-out '
            + 'motion-safe:group-hover:-translate-x-[9%] motion-safe:group-hover:-rotate-[10deg]'
          }
          style={{ boxShadow: `${SHEET_RING}, 0 8px 20px rgba(12,24,38,0.10)` }}
        />
        {/* Back right. */}
        <Image
          src="/starter-kit/page-3.png"
          alt=""
          aria-hidden="true"
          width={PAGE_W}
          height={PAGE_H}
          sizes={SIZES}
          loading="eager"
          className={
            `absolute left-0 top-0 z-10 origin-bottom translate-x-[5%] translate-y-[2%] rotate-[6deg] ${SHEET} `
            + 'motion-safe:transition-transform motion-safe:duration-300 motion-safe:ease-out '
            + 'motion-safe:group-hover:translate-x-[8%] motion-safe:group-hover:rotate-[9deg]'
          }
          style={{ boxShadow: `${SHEET_RING}, 0 8px 20px rgba(12,24,38,0.10)` }}
        />
        {/* The cover, square to the reader and in front. Deeper
            shadow than the backs so the stack has an order to it. */}
        <Image
          src="/starter-kit/cover.png"
          alt="The Creator Starter Kit cover, with sunset islands"
          width={PAGE_W}
          height={PAGE_H}
          sizes={SIZES}
          priority
          className={
            `relative z-20 ${SHEET} `
            + 'motion-safe:transition-transform motion-safe:duration-300 motion-safe:ease-out '
            + 'motion-safe:group-hover:-translate-y-[3px]'
          }
          style={{ boxShadow: `${SHEET_RING}, 0 16px 36px rgba(12,24,38,0.18)` }}
        />
      </div>
    </div>
  )
}
