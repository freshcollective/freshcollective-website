/**
 * The serif face, as an inline style.
 *
 * ``globals.css`` carries an **unlayered** rule —
 * ``h1, h2, h3, h4, h5, h6 { font-family: var(--font-sans); … }`` —
 * and an unlayered element selector outranks every Tailwind utility,
 * which live in a cascade layer. So ``className="font-serif"`` on a
 * heading is silently discarded and the heading renders sans. It
 * looks like it works right up until you compare it with the design.
 *
 * This is the same trap ``headingColour.test.ts`` already pins for
 * ``text-white``, and the same fix: set it inline, where nothing can
 * outrank it. Read from the ``--font-serif`` token rather than
 * spelling Georgia out again, so the stack has one definition.
 *
 * Only needed on ``h1``–``h6``. Body copy, standfirsts and block
 * quotes are not headings, so ``className="font-serif"`` works on
 * them normally.
 */
export const SERIF_HEADING = { fontFamily: 'var(--font-serif)' } as const
