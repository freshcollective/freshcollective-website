import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * The main header switches layout before it runs out of room.
 *
 * It used to switch at ``lg`` (1024px) and the failure was not
 * graceful: the brand lockup and the auth cluster are both
 * ``shrink-0``, so the nav is the only item that can give — but its
 * links are ``whitespace-nowrap``, so the nav box shrank below its
 * contents and the links overflowed it instead of shrinking. Nothing
 * clipped them, and being ``justify-center`` the spill was symmetric,
 * so "Your World" landed on the wordmark and "Creator Studio" on the
 * notification bell. Measured in Chromium at 1024px: 14.1px over each
 * side, identically — the signature of centre-justified overflow.
 *
 * The threshold is now 1152px, which is ``max-w-6xl`` — the width at
 * which Container stops growing. That matters: above it the row's
 * geometry is fixed, so there is no width-dependent squeeze left.
 *
 * Measured against the built stylesheet after the change (nav needs
 * 634px, box 702px at 1152-1279 and 670px from 1280):
 *
 *   375 → 1151px   drawer, no overflow
 *   1152px         bar, +68px box slack, 49.9px clearance each side
 *   1280-1920px    bar, +36px box slack, 49.9px clearance each side
 *
 * Also measured across fonts, since the stack is all system fonts and
 * resolves differently per platform. Worst case of every font × width
 * combination tested was 6.1px of *clearance* — DejaVu Sans is tight
 * but does not overlap; Arial metrics and Noto Sans are comfortable.
 *
 * These tests pin the structural invariants that make the overlap
 * impossible rather than re-measuring layout, which node:test cannot
 * do. The numbers above are what the Chromium runs produced.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

const HEADER = 'components/layout/WorldHeader.tsx'

/** Source with comments stripped: the docstring above the component
 *  discusses ``lg``, ``xl:gap-8`` and the overlap it caused by name, so
 *  a substring search would match the explanation. */
function code(path: string): string {
  return read(path)
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

/** The className string of the element carrying a given marker.
 *
 *  Markers must be unique: the drawer's profile row also contains
 *  "items-center gap-3", and the hamburger button "items-center
 *  justify-center", so looser markers match two elements and the
 *  assertions silently test the wrong one. */
function classesContaining(source: string, marker: string): string[] {
  return [...source.matchAll(/className="([^"]*)"/g)]
    .map((m) => m[1])
    .filter((c) => c.includes(marker))
}

describe('the three visibility switches share one threshold', () => {
  // This is the invariant worth protecting above all others. Moving the
  // nav without the auth cluster would show the destinations while the
  // bell, avatar and logout vanished; moving the nav without the drawer
  // wrapper would show both at once, or neither.

  test('exactly three elements switch, and all three use min-[1152px]', () => {
    const source = code(HEADER)
    const switches = [...source.matchAll(/min-\[(\d+)px\]:(flex|hidden)/g)]
    assert.equal(switches.length, 3, 'expected exactly three visibility switches')
    for (const [, px] of switches) {
      assert.equal(px, '1152', 'every switch must use the same breakpoint')
    }
  })

  test('two reveal the desktop row and one hides the drawer', () => {
    const source = code(HEADER)
    const kinds = [...source.matchAll(/min-\[1152px\]:(flex|hidden)/g)].map((m) => m[1])
    assert.deepEqual(kinds.sort(), ['flex', 'flex', 'hidden'])
  })

  test('no lg-based visibility switch survives anywhere', () => {
    // A single leftover ``lg:flex`` would reintroduce the 1024-1151
    // band with one element appearing 128px before the others.
    const source = code(HEADER)
    assert.ok(!/\blg:(flex|hidden|block)\b/.test(source), 'an lg visibility switch remains')
  })

  test('the nav and the auth cluster reveal together', () => {
    const source = code(HEADER)
    const nav = classesContaining(source, 'min-w-0 flex-1 items-center justify-center')
    const auth = classesContaining(source, 'hidden shrink-0 items-center gap-3')
    assert.equal(nav.length, 1, 'expected one desktop nav')
    assert.equal(auth.length, 1, 'expected one auth cluster')
    assert.match(nav[0], /min-\[1152px\]:flex/)
    assert.match(auth[0], /min-\[1152px\]:flex/)
  })

  test('the drawer hides at the same width the row appears', () => {
    const source = code(HEADER)
    assert.match(source, /className="min-\[1152px\]:hidden"/)
  })
})

describe('the breakpoint is where the container stops growing', () => {
  test('1152px matches Container’s max-w-6xl', () => {
    // Not an arbitrary number. Above it the content box is fixed at
    // 1072px, so the row's geometry no longer depends on the viewport.
    // If Container's max width ever changes, this pairing has to be
    // revisited, which is why both are asserted together.
    assert.match(read('components/layout/Container.tsx'), /max-w-6xl/)
    assert.match(code(HEADER), /min-\[1152px\]/)
  })
})

describe('navigation spacing is uniform across desktop widths', () => {
  test('the nav keeps gap-4 and takes no wider gap at xl', () => {
    // ``xl:gap-8`` added 80px to what the nav needed (five gaps) while
    // Container's own xl:gap-8 took another 32px off the nav box,
    // leaving the 1280px-and-up band 9.9px from overlapping.
    const nav = classesContaining(code(HEADER), 'min-w-0 flex-1 items-center justify-center')[0]
    assert.match(nav, /\bgap-4\b/)
    assert.ok(!/\bxl:gap-8\b/.test(nav), 'the nav must not widen its gap at xl')
  })

  test('Container keeps its own responsive gap', () => {
    // Deliberately unchanged — it separates the three sections, and
    // only the nav's internal gap was inflating the requirement.
    const source = code(HEADER)
    const container = source.match(/<Container className="([^"]*)"/)
    assert.ok(container, 'Container className not found')
    assert.match(container[1], /gap-4 xl:gap-8/)
  })
})

describe('nothing is hidden from anyone', () => {
  test('both navs render the same items array', () => {
    // The drawer is the only navigation below 1152px, so it has to
    // carry every destination the bar does — Creator Studio included.
    const source = code(HEADER)
    assert.equal(
      (source.match(/items\.map\(\(\{ href, label \}\)/g) ?? []).length,
      2,
      'expected the bar and the drawer to map the same items array',
    )
  })

  test('the drawer also carries notifications, profile and logout', () => {
    const source = code(HEADER)
    assert.match(source, /href="\/notifications"/)
    assert.match(source, /href="\/settings\/profile"/)
    assert.match(source, /handleLogout/)
  })

  test('the desktop cluster still has all three controls', () => {
    const source = code(HEADER)
    assert.match(source, /<NotificationBell/)
    assert.match(source, /<Avatar name=\{displayName\}/)
    assert.match(source, /<LogoutButton/)
  })

  test('destinations still come from the shared nav source', () => {
    // So this header cannot drift from the other nav surfaces.
    assert.match(code(HEADER), /memberNavItems\(\{/)
    assert.match(code(HEADER), /canAccessCreatorStudio\(user\)/)
  })
})

describe('active state and accessibility are preserved', () => {
  test('both navs mark the current page', () => {
    const source = code(HEADER)
    assert.equal(
      (source.match(/aria-current=\{active \? 'page' : undefined\}/g) ?? []).length,
      2,
      'both the bar and the drawer must mark the active destination',
    )
  })

  test('the active link keeps its underline treatment', () => {
    assert.match(code(HEADER), /border-b-2 border-teal-500/)
  })

  test('both navs are labelled, and distinctly', () => {
    const source = code(HEADER)
    assert.match(source, /aria-label="Member"/)
    assert.match(source, /aria-label="Member — mobile"/)
  })

  test('the drawer toggle reports its state to assistive tech', () => {
    const source = code(HEADER)
    assert.match(source, /aria-expanded=\{open\}/)
    assert.match(source, /aria-label=\{open \? 'Close menu' : 'Open menu'\}/)
  })

  test('isNavItemActive still decides the active state', () => {
    // Rather than this component inventing its own path matching.
    assert.match(code(HEADER), /isNavItemActive\(pathname, href\)/)
  })
})

describe('the layout cannot overlap by construction', () => {
  test('the nav is the flexible item and is centred', () => {
    const nav = classesContaining(code(HEADER), 'min-w-0 flex-1 items-center justify-center')[0]
    assert.match(nav, /\bflex-1\b/)
    assert.match(nav, /\bmin-w-0\b/)
    assert.match(nav, /\bjustify-center\b/)
  })

  test('the links still never wrap', () => {
    // Wrapping inside a 64px-tall header is the other failure mode;
    // the fix is the breakpoint, not letting the text reflow.
    assert.match(code(HEADER), /whitespace-nowrap/)
  })

  test('the auth cluster still refuses to shrink', () => {
    const auth = classesContaining(code(HEADER), 'hidden shrink-0 items-center gap-3')[0]
    assert.match(auth, /\bshrink-0\b/)
  })
})
