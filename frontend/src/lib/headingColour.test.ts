import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Headings cannot be coloured with a Tailwind utility.
 *
 * ``globals.css`` styles every heading:
 *
 *     h1, h2, h3, h4, h5, h6 { … color: var(--color-navy-950); }
 *
 * and that rule sits **outside any cascade layer**. Tailwind v4 puts
 * its utilities in ``@layer utilities``, and unlayered declarations
 * beat layered ones no matter what the specificity says — so
 * ``<h1 className="text-white">`` computes to navy. Measured on
 * production: ``h1.text-white`` → ``rgb(12, 24, 38)``, while
 * ``div.text-white``, ``p.text-white`` and ``span.text-white`` are
 * all correctly white.
 *
 * Nothing warns about this. The class is in the markup, the utility
 * is in the stylesheet, and the heading quietly renders navy — which
 * is invisible on exactly the grounds a white heading is used on.
 * It cost four of them:
 *
 *   * the Gathering Series hero, navy on a darkened photograph;
 *   * the Discover Places hero, navy on a scrimmed photograph;
 *   * the REAL Journey hero, navy on navy-950 — "The" and "Journey"
 *     invisible, only the gold ``<em>`` surviving, because an ``em``
 *     is not a heading and its own class still applied;
 *   * the invitation card, navy on a near-black panel.
 *
 * The Gathering detail hero was never affected: ``HeroOverlay`` has
 * always set ``style={{ color: textPrimary }}``, and an inline style
 * outranks an unlayered rule. That is the convention these tests
 * pin — it is the one that demonstrably works.
 *
 * If ``globals.css`` is ever wrapped in ``@layer base``, the utility
 * starts working and the ban below becomes unnecessary. It stays
 * harmless either way, so it can be lifted at leisure rather than
 * urgently.
 */

const read = (p: string) => readFileSync(p, 'utf8')

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (full.endsWith('.tsx')) out.push(full)
  }
  return out
}

const TSX = walk('src')

/**
 * A heading asking for white through a class.
 *
 * Only ``text-white`` is policed. ``text-black`` appears on a few
 * small uppercase labels and is discarded the same way, but it is
 * discarded in favour of navy-950 — a difference nobody can see, on
 * light grounds where both read fine. Those are not defects, and
 * rewriting them would be churn. White is the one that fails
 * visibly, because white is only ever asked for on a dark ground.
 */
const HEADING_WANTS_WHITE = /className="[^"]*\btext-white\b[^"]*"/

/**
 * A whole heading opening tag — ``<h2 … >``, attributes and all.
 *
 * It has to be the whole tag, not just the class attribute: an
 * inline ``style`` usually sits on the line *after* ``className``,
 * and a pattern that stops at the closing quote cannot see it. That
 * mistake reported the one heading in the app that was already
 * correct.
 */
const HEADING_TAG = /<h[1-6]\b[\s\S]*?>/g

/** ``style={{ color: … }}`` anywhere in the same tag. */
const SETS_COLOUR_INLINE = /style=\{\{[\s\S]*?\bcolor:/

/**
 * Headings that match but are not defects, each for a stated reason.
 * An allowlist rather than a looser regex, so adding to it is a
 * decision somebody makes on purpose.
 */
const ALLOWED: Record<string, string> = {
  // Unreferenced: nothing imports these two, so neither renders.
  // Reviving one means giving its headings an inline colour first.
  'src/components/home/EntryPoints.tsx': 'not imported by anything',
  'src/components/home/TransformationSection.tsx': 'not imported by anything',
}

const SERIES_PAGE = 'src/app/spaces/[slug]/gathering-series/[series-slug]/page.tsx'
const GATHERING_PAGE = 'src/app/spaces/[slug]/events/[eventId]/page.tsx'


// ---------------------------------------------------------------------------
// 1. The rule that makes the whole thing necessary
// ---------------------------------------------------------------------------

describe('why headings cannot use a colour utility', () => {
  const CSS = read('src/app/globals.css')

  test('globals.css really does colour every heading', () => {
    assert.match(CSS, /h1,\s*h2,\s*h3,\s*h4,\s*h5,\s*h6\s*\{[^}]*color:/)
  })

  test('and Tailwind is imported above it, so its utilities are layered', () => {
    assert.ok(CSS.indexOf('@import "tailwindcss"') < CSS.indexOf('h1, h2, h3'))
  })
})


// ---------------------------------------------------------------------------
// 2. No heading anywhere relies on a colour utility
// ---------------------------------------------------------------------------

describe('no rendered heading relies on text-white', () => {
  test('every white heading sets its colour inline', () => {
    const offenders: string[] = []
    for (const file of TSX) {
      if (file in ALLOWED) continue
      for (const m of read(file).matchAll(HEADING_TAG)) {
        if (!HEADING_WANTS_WHITE.test(m[0])) continue
        // `text-white` alongside an inline colour is redundant but
        // harmless — the inline value is what renders.
        if (SETS_COLOUR_INLINE.test(m[0])) continue
        offenders.push(`${file} — ${m[0].replace(/\s+/g, ' ').slice(0, 110)}`)
      }
    }
    assert.deepEqual(
      offenders,
      [],
      'These headings ask for white with a class the unlayered h1…h6 rule '
        + 'in globals.css silently discards, so they render navy. Set the '
        + 'colour inline instead — style={{ color: \'#FFFFFF\' }}:\n  '
        + offenders.join('\n  '),
    )
  })

  test('the allowlist still describes components nobody imports', () => {
    for (const file of Object.keys(ALLOWED)) {
      const name = file.split('/').pop()!.replace('.tsx', '')
      const importers = TSX.filter(
        (f) => f !== file && new RegExp(`import\\s+${name}\\s+from`).test(read(f)),
      )
      assert.deepEqual(
        importers,
        [],
        `${file} is allowlisted as unrendered, but ${importers.join(', ')} `
          + 'imports it — give its headings an inline colour and drop the entry.',
      )
    }
  })
})


// ---------------------------------------------------------------------------
// 3. The photographic banners put white where it survives
// ---------------------------------------------------------------------------

describe('photographic banners render their titles in white', () => {
  const series = read(SERIES_PAGE)
  const gathering = read(GATHERING_PAGE)

  test('the Gathering Series hero sets white inline', () => {
    // The h1 in the cover-image branch, and its inline colour.
    const covered = series.slice(series.indexOf('{coverUrl ?'), series.indexOf(') : ('))
    assert.match(covered, /<h1[\s\S]{0,220}style=\{\{\s*color:\s*'#FFFFFF'\s*\}\}/)
    assert.ok(
      !/<h1[^>]*text-white/.test(covered),
      'back on the utility that does not work',
    )
  })

  test('the Series title keeps its size, face and position', () => {
    const covered = series.slice(series.indexOf('{coverUrl ?'), series.indexOf(') : ('))
    assert.match(covered, /font-serif/)
    assert.match(covered, /text-2xl/)
    assert.match(covered, /md:text-3xl/)
    assert.match(covered, /leading-tight/)
    assert.match(covered, /absolute inset-x-0 bottom-0/)
  })

  test('the Series overlay and date line are untouched', () => {
    assert.match(series, /linear-gradient\(to top, rgba\(0,0,0,0\.86\) 0%/)
    assert.match(series, /textShadow: '0 1px 14px rgba\(0,0,0,0\.65\)'/)
    assert.match(series, /text-white\/90">\s*\{dateRange\}/)
  })

  test('the no-cover Series card is still navy, not white', () => {
    const plain = series.slice(series.indexOf(') : ('))
    assert.match(plain, /<h1 className="[^"]*text-navy-900/)
  })

  test('the Gathering hero still sets its colour inline, as it always did', () => {
    assert.match(gathering, /const textPrimary = white \? '#FFFFFF' : '#0F172A'/)
    assert.match(gathering, /<h1[\s\S]{0,160}style=\{\{ color: textPrimary \}\}/)
  })

  test('both heroes use the same white — no new colour was introduced', () => {
    for (const src of [series, gathering]) assert.ok(src.includes("'#FFFFFF'"))
  })
})


// ---------------------------------------------------------------------------
// 4. The three other headings the same defect had broken
// ---------------------------------------------------------------------------

describe('the other dark-ground headings', () => {
  const cases: [string, string][] = [
    ['the Discover Places hero', 'src/app/discover-places/[slug]/PlaceDetailView.tsx'],
    ['the REAL Journey hero', 'src/app/real-journey/page.tsx'],
    ['the invitation card', 'src/app/invites/[token]/page.tsx'],
  ]

  for (const [name, file] of cases) {
    test(`${name} sets white inline`, () => {
      const src = read(file)
      assert.match(src, /<h1[\s\S]{0,260}style=\{\{\s*color:\s*'#FFFFFF'\s*\}\}/)
    })
  }

  test('the REAL Journey gold accent still belongs to the em, not the h1', () => {
    // An <em> is not a heading, so its own utility still applies —
    // which is why "REAL" was the only readable word.
    assert.match(read('src/app/real-journey/page.tsx'), /<em className="text-gold-400">REAL<\/em>/)
  })
})
