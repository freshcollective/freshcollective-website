import { strict as assert } from 'node:assert'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  atmosphereWords,
  collectiveAboutHref,
  exploreIslandLabel,
  islandHref,
  islandPalette,
  islandStoryParagraphs,
  islandTagline,
} from './islandPage.ts'

const SRC = join(process.cwd(), 'src')
const PAGE = join(SRC, 'app', 'spaces', '[slug]', 'island', 'page.tsx')
const ABOUT = join(SRC, 'app', 'spaces', '[slug]', 'about', 'page.tsx')
const HEADER = join(SRC, 'components', 'spaces', 'CollectiveIdentityHeader.tsx')
const page = () => readFileSync(PAGE, 'utf8')

// Moon Lagoon, as the Atlas holds it.
const MOON_TAGLINE = 'Sheltered waters where people arrive, rest and begin again.'
const MOON_STORY = [
  'The water here is unusually still.',
  'People often arrive here searching for answers.',
  'More often, they discover the right questions instead.',
].join('\n\n')

describe('routes', () => {
  it('the island page is Collective-scoped', () => {
    // So changing islands never breaks a link.
    assert.equal(islandHref('moonlit-circle'), '/spaces/moonlit-circle/island')
    assert.ok(existsSync(PAGE), PAGE)
  })

  it('back goes to the Collective About page', () => {
    assert.equal(
      collectiveAboutHref('moonlit-circle'), '/spaces/moonlit-circle/about',
    )
  })

  it('the explore label names the island', () => {
    assert.equal(exploreIslandLabel('Moon Lagoon'), 'Explore Moon Lagoon')
    assert.equal(exploreIslandLabel(null), 'Explore this island')
    assert.equal(exploreIslandLabel('  '), 'Explore this island')
  })
})

describe('the island story', () => {
  it('splits the atlas entry into paragraphs', () => {
    assert.deepEqual(islandStoryParagraphs(MOON_STORY), [
      'The water here is unusually still.',
      'People often arrive here searching for answers.',
      'More often, they discover the right questions instead.',
    ])
  })

  it('folds a soft wrap inside a paragraph', () => {
    // A single newline is a wrap in the stored text, not a break.
    assert.deepEqual(
      islandStoryParagraphs('One line\nwrapped here.\n\nSecond paragraph.'),
      ['One line wrapped here.', 'Second paragraph.'],
    )
  })

  it('tolerates windows and padded blank lines', () => {
    assert.deepEqual(
      islandStoryParagraphs('A.\n   \nB.\n\n\nC.'),
      ['A.', 'B.', 'C.'],
    )
  })

  it('falls back to the short description', () => {
    // An island with a tagline and no atlas entry still says
    // something rather than showing an empty section.
    assert.deepEqual(islandStoryParagraphs(null, MOON_TAGLINE), [MOON_TAGLINE])
  })

  it('is empty when there is nothing', () => {
    assert.deepEqual(islandStoryParagraphs(null), [])
    assert.deepEqual(islandStoryParagraphs('', ''), [])
    assert.deepEqual(islandStoryParagraphs('   ', '  '), [])
  })

  it('never interprets markup', () => {
    // Plain text with newlines is what the field is, and the page
    // renders these as text nodes. No second rich-text system.
    const out = islandStoryParagraphs('A <b>bold</b> claim.')
    assert.deepEqual(out, ['A <b>bold</b> claim.'])
  })
})

describe('the tagline', () => {
  it('is the short description when there is a story below it', () => {
    assert.equal(islandTagline(MOON_TAGLINE, MOON_STORY), MOON_TAGLINE)
  })

  it('is omitted when it IS the story below', () => {
    // Showing the same sentence twice reads as a mistake.
    assert.equal(islandTagline(MOON_TAGLINE, null), null)
    assert.equal(islandTagline(MOON_TAGLINE, '   '), null)
  })

  it('is omitted when absent', () => {
    assert.equal(islandTagline(null, MOON_STORY), null)
  })
})

describe('atmosphere words', () => {
  it('uses the Collective\'s own atmosphere', () => {
    // The set the Collective header already shows a member, so it is
    // the one they recognise as the feeling of their place.
    assert.deepEqual(
      atmosphereWords(['Calm', 'Reflective', 'Peaceful', 'Curious', 'Creative']),
      ['Calm', 'Reflective', 'Peaceful', 'Curious', 'Creative'],
    )
  })

  it('falls back to the island when the Collective chose none', () => {
    assert.deepEqual(atmosphereWords([], ['Still', 'Quiet']), ['Still', 'Quiet'])
    assert.deepEqual(atmosphereWords(null, ['Still']), ['Still'])
  })

  it('is empty when neither has any', () => {
    assert.deepEqual(atmosphereWords(null), [])
    assert.deepEqual(atmosphereWords([], []), [])
  })

  it('drops blanks rather than rendering an empty pill', () => {
    assert.deepEqual(atmosphereWords(['Calm', '  ', '']), ['Calm'])
  })
})

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------

const PALETTES = {
  // Deep teal — Moonlit Circle's shape.
  teal: { key: 'moonlit', name: 'Moonlit', palette: { primary: '#0F5E5C' } },
  // A bright, pale primary: the case that makes a naive tint unreadable.
  sunrise: { key: 'sunrise', name: 'Sunrise', palette: { primary: '#D97A3F' } },
  // Very pale.
  snow: { key: 'snow', name: 'Snow & Sky', palette: { primary: '#A0B4C4' } },
  // Deep purple.
  violet: { key: 'violet', name: 'Violet', palette: { primary: '#4C1D95' } },
  rose: { key: 'rose', name: 'Rose', palette: { primary: '#BE185D' } },
}

function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) throw new Error(`not a hex: ${hex}`)
  const n = parseInt(m[1], 16)
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * lin((n >> 16) & 255)
    + 0.7152 * lin((n >> 8) & 255)
    + 0.0722 * lin(n & 255)
}

function ratio(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la > lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

describe('the Collective palette styles the page', () => {
  it('every palette produces a different heading colour', () => {
    // The requirement that one Collective's test cannot satisfy: the
    // same component must respond to whichever palette is active,
    // with no per-Collective code.
    const headings = Object.values(PALETTES).map(
      (p) => islandPalette(p).headingColor,
    )
    assert.equal(new Set(headings).size, headings.length, headings.join(' '))
  })

  it('every palette produces a different feeling-card background', () => {
    const backgrounds = Object.values(PALETTES).map(
      (p) => islandPalette(p).cardBackground,
    )
    assert.equal(new Set(backgrounds).size, backgrounds.length)
  })

  it('the heading is legible on the page for every palette', () => {
    // Including the pale ones. `readableOnWhite` deepens the hue until
    // it clears AA rather than giving up and going grey.
    for (const [name, p] of Object.entries(PALETTES)) {
      const { headingColor } = islandPalette(p)
      assert.ok(
        ratio(headingColor, '#ffffff') >= 4.5,
        `${name}: ${headingColor} is ${ratio(headingColor, '#ffffff').toFixed(2)}:1 on white`,
      )
    }
  })

  it('the feeling card text is legible on its own background', () => {
    for (const [name, p] of Object.entries(PALETTES)) {
      const { cardBackground, cardText } = islandPalette(p)
      assert.ok(
        ratio(cardText, cardBackground) >= 4.5,
        `${name}: ${cardText} on ${cardBackground} is `
        + `${ratio(cardText, cardBackground).toFixed(2)}:1`,
      )
    }
  })

  it('the pill text is the card text, so it inherits that contrast', () => {
    for (const p of Object.values(PALETTES)) {
      const out = islandPalette(p)
      assert.equal(out.pillText, out.cardText)
    }
  })

  it('pills are lifted the right way for a dark or light card', () => {
    const dark = islandPalette(PALETTES.violet)
    const light = islandPalette(PALETTES.snow)
    assert.ok(dark.pillBackground.startsWith('rgba(255,255,255'))
    assert.ok(light.pillBackground.startsWith('rgba(15,23,42'))
  })

  it('a Collective with no palette falls back to Fresh Collective teal', () => {
    for (const absent of [null, undefined, { key: 'x', name: 'x', palette: {} }]) {
      const out = islandPalette(absent as never)
      assert.ok(out.headingColor.startsWith('#'))
      assert.ok(out.cardBackground.startsWith('#'))
      assert.equal(out.fromPalette, false)
    }
    assert.equal(islandPalette(PALETTES.teal).fromPalette, true)
  })

  it('an unparseable palette hex still yields readable ink', () => {
    // `paletteHex` validates, so a junk value never reaches the
    // colour maths — it falls back like an absent palette. Asserted
    // because "a slightly off colour beats a blank space" is the
    // documented posture of the helpers underneath.
    const out = islandPalette(
      { key: 'x', name: 'x', palette: { primary: 'not-a-colour' } } as never,
    )
    assert.ok(out.headingColor.startsWith('#'), out.headingColor)
    assert.ok(out.cardBackground.startsWith('#'), out.cardBackground)
    assert.ok(ratio(out.cardText, out.cardBackground) >= 4.5)
    assert.equal(out.fromPalette, false)
  })
})

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

/**
 * The page is a Server Component and this harness has no DOM, so its
 * structure is asserted against the source. Shape checks over the
 * decisions that matter: which image, which colours, what is absent.
 */
describe('the page structure', () => {
  it('has the approved sections in order', () => {
    const source = page()
    // Markers unique to the rendered JSX. `island.name` alone also
    // appears in generateMetadata, above everything.
    const order = [
      'aria-label="Breadcrumb"',
      'Your island',
      '<h1',
      'About this island',
      'The feeling of this place',
      'Back to {space.name}',
    ]
    let last = -1
    for (const marker of order) {
      const at = source.indexOf(marker)
      assert.ok(at > -1, `missing ${marker}`)
      assert.ok(at > last, `${marker} is out of order`)
      last = at
    }
  })

  it('uses the island artwork, never the creator banner', () => {
    // The banner is the Collective's branding; this page celebrates
    // the place the Collective chose.
    const source = page()
    assert.ok(/island\.hero_artwork_url \?\? island\.thumbnail_artwork_url/.test(source))
    assert.ok(
      !/cover_image_url|header_image_url|headerImageFor/.test(source),
      'the page is using the creator banner',
    )
  })

  it('shows one image and no decoration', () => {
    // Comments are stripped first: they say the page has no patterns
    // and no illustration, and a bare substring check failed on the
    // prose promising it.
    const source = page()
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      .replace(/^\s*\/\/.*$/gm, '')
    assert.equal((source.match(/<img/g) ?? []).length, 1, 'more than one image')
    for (const banned of ['leaf', 'botanical', 'pattern', '<svg', 'background-image']) {
      assert.ok(
        !new RegExp(banned, 'i').test(source),
        `the page renders ${banned}`,
      )
    }
  })

  it('does not distort the artwork', () => {
    const source = page()
    assert.ok(/object-cover/.test(source))
    assert.ok(/aspectRatio: '16 \/ 9'/.test(source))
    assert.ok(/loading="lazy"/.test(source))
  })

  it('the heading card is the navy Explore plate, not the artwork', () => {
    const source = page()
    const header = source.slice(source.indexOf('<header'), source.indexOf('</header>'))
    assert.ok(/background: '#071824'/.test(header))
    assert.ok(/rounded-2xl/.test(header))
    assert.ok(!/<img/.test(header), 'the artwork became the heading background')
  })

  it('the introductory label is not the banned eyebrow', () => {
    // CLAUDE.md bans small uppercase teal eyebrow labels above
    // headings platform-wide. The mockup asked for "YOUR ISLAND"; it
    // is rendered sentence-case in white instead — see the report.
    const source = page()
    assert.ok(/Your island/.test(source))
    assert.ok(!/YOUR ISLAND/.test(source), 'the uppercase eyebrow is back')
    // The label's own element. A 400-character window caught the
    // accent LINE above it, which is PageHero's own treatment and is
    // allowed — the ban is on uppercase teal *labels*.
    const at = source.indexOf('Your island')
    const open = source.lastIndexOf('<p', at)
    const label = source.slice(open, at)
    assert.ok(!/uppercase/.test(label), `the label is uppercased: ${label}`)
    assert.ok(!/38A09E|teal/i.test(label), `the label is tinted teal: ${label}`)
  })

  it('both palette-driven surfaces read the resolved colours', () => {
    const source = page()
    assert.ok(/color: colours\.headingColor/.test(source))
    assert.ok(/background: colours\.cardBackground/.test(source))
    assert.ok(/color: colours\.cardText/.test(source))
    assert.ok(/background: colours\.pillBackground/.test(source))
    assert.ok(
      !/#38A09E'[,\s]*\n?\s*\}\}\s*\n?\s*>\s*\n?\s*About this island/.test(source),
      'the About heading is hardcoded teal',
    )
  })

  it('never names or swatches the palette to a member', () => {
    // Comments stripped: the module docstring names the Colour
    // Palette by way of explaining what styles the page, which is
    // not the same as showing a member a swatch.
    const source = page()
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      .replace(/^\s*\/\/.*$/gm, '')
      .replace(/^\s*\*.*$/gm, '')
    assert.ok(
      !/colour_palette_key|palette\.name|Colour Palette/.test(source),
      'the palette is named or swatched to a member',
    )
    // And no swatch element.
    assert.ok(!/palette\.palette|secondary|accent'/.test(source))
  })

  it('omits a section rather than showing it empty', () => {
    const source = page()
    assert.ok(/story\.length > 0 && \(/.test(source))
    assert.ok(/feelings\.length > 0 && \(/.test(source))
    assert.ok(/\{artwork && \(/.test(source))
  })

  it('reads the space payload and writes nothing', () => {
    const source = page()
    assert.ok(/getSpace\(slug\)/.test(source))
    for (const forbidden of ["method: 'POST'", "method: 'PATCH'", "method: 'DELETE'"]) {
      assert.ok(!source.includes(forbidden), `the page performs a ${forbidden}`)
    }
  })

  it('inherits access rather than inventing it', () => {
    // No second endpoint, and a Collective that does not resolve is
    // indistinguishable from one that does not exist.
    const source = page()
    assert.ok(/if \(!space\) notFound\(\)/.test(source))
    assert.ok(/if \(!island\?\.name\) notFound\(\)/.test(source))
    assert.ok(
      !/getPublicCollectiveAbout/.test(source),
      'the page added a public fallback — that payload has no story',
    )
  })

  it('does not index a private Collective\'s island', () => {
    const source = page()
    assert.ok(/space\.is_public \? undefined : \{ index: false, follow: false \}/.test(source))
  })
})

describe('the two entry points', () => {
  it('the About island card offers the link', () => {
    const about = readFileSync(ABOUT, 'utf8')
    assert.ok(/exploreIslandLabel\(locationName\)/.test(about))
    assert.ok(/href=\{islandHref\(slug\)\}/.test(about))
  })

  it('the About card still shows the island artwork', () => {
    // Preserved from Phase 1: it reads Location artwork whatever the
    // header shows.
    const about = readFileSync(ABOUT, 'utf8')
    assert.ok(
      /sidebarArtworkUrl = resolveMediaUrl\(\s*\n?\s*space\.location\?\.thumbnail_artwork_url/
        .test(about),
      'the island card no longer leads with Location artwork',
    )
  })

  it('the link is withheld where the page would be empty', () => {
    // The public About shim has a name and artwork but no story,
    // atmosphere or palette.
    const about = readFileSync(ABOUT, 'utf8')
    assert.ok(/const canExploreIsland = privateSpace !== null/.test(about))
    assert.ok(/\{canExploreIsland && locationName && \(/.test(about))
  })

  it('it is a plain link, not a wrapped card', () => {
    // The card already contains links and avatars; nesting them in an
    // anchor is invalid markup and unreachable by keyboard.
    const about = readFileSync(ABOUT, 'utf8')
    const block = about.slice(about.indexOf('{canExploreIsland && locationName && ('))
    const link = block.slice(0, block.indexOf('</Link>'))
    assert.ok(/<Link/.test(link))
    assert.ok(/focus-visible:underline/.test(link), 'no visible focus state')
  })

  it('the header location name links to the island', () => {
    const header = readFileSync(HEADER, 'utf8')
    assert.ok(/href=\{islandHref\(collectiveSlug\)\}/.test(header))
    assert.ok(/focus-visible:underline/.test(header))
  })

  it('the header keeps everything else exactly as it was', () => {
    const header = readFileSync(HEADER, 'utf8')
    // Phase 1's image rule, the logo, the tagline, the atmosphere
    // labels and the gold accent all stay.
    assert.ok(/selectCollectiveHeaderImage\(\{/.test(header))
    assert.ok(/logoResolved/.test(header))
    assert.ok(/atmosphereLabels/.test(header))
    assert.ok(/E7C65A/.test(header), 'the gold accent line went')
  })

  it('a header with no slug leaves the name as plain text', () => {
    // Nothing breaks for a caller that has not threaded it.
    const header = readFileSync(HEADER, 'utf8')
    assert.ok(/collectiveSlug \? \(/.test(header))
    assert.ok(/<span style=\{\{ color: 'rgba\(255,255,255,0\.90\)' \}\}>/.test(header))
  })
})

describe('World Artwork and Atlas curation are untouched', () => {
  it('the page never writes a Location or island field', () => {
    const source = page()
    for (const forbidden of ['island_artwork', 'atlas_entry =', 'hero_artwork_url =']) {
      assert.ok(!source.includes(forbidden), `the page touches ${forbidden}`)
    }
  })

  it('the Atlas admin and Place and Feel are not rewired', () => {
    for (const path of [
      join(SRC, 'app', 'admin', 'atlas', '[key]', 'LocationDetailClient.tsx'),
      join(SRC, 'app', 'admin', 'atlas', 'page.tsx'),
    ]) {
      assert.ok(
        !/islandPage/.test(readFileSync(path, 'utf8')),
        `${path} was rewired`,
      )
    }
  })
})
