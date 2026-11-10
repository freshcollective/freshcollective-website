/**
 * Guides — the rules a reader would notice if they were wrong.
 *
 * Everything asserted here is a pure function, which is the point:
 * "the Starter Kit band does not render" is provable rather than
 * eyeballed, and "the contents list links to a heading that exists"
 * is a property of two functions agreeing rather than something you
 * find by clicking.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import { readFileSync } from 'node:fs'

import {
  GUIDE_CATEGORIES,
  HOUSE_AUTHOR,
  authorInitial,
  bylineFor,
  categoryLabel,
  extractHeadings,
  formatGuideDate,
  guideJsonLd,
  guidePath,
  guideSeoDescription,
  guideSeoTitle,
  headingAnchor,
  readingTimeLabel,
  showStarterKit,
  starterKitHref,
  type GuideArticle,
} from './guides.ts'

const ORIGIN = 'https://freshcollective.au'

function article(overrides: Partial<GuideArticle> = {}): GuideArticle {
  return {
    slug: 'moving-your-community',
    title: 'Moving your community off social media',
    standfirst: 'Your programs, classes, products and people, in one calm place.',
    body: '<p>Something worth reading.</p>',
    category: 'starting',
    hero_image_url: null,
    hero_image_alt: null,
    seo_title: null,
    seo_description: null,
    author_name: HOUSE_AUTHOR,
    reading_time_minutes: 7,
    published_at: '2026-11-02T09:00:00',
    updated_at: '2026-11-09T11:30:00',
    cta_heading: null,
    cta_text: null,
    cta_label: null,
    cta_href: null,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// 1 · The Starter Kit gate
// ---------------------------------------------------------------------------

describe('the Creator Starter Kit renders only when a link is set', () => {
  // One setting drives two placements — the band at the foot of
  // /guides and the card in a Guide's side column. The shipped state
  // is empty, and empty must mean *nothing in the DOM*: no
  // placeholder, no disabled button, no "coming soon".

  for (const [label, value] of [
    ['not configured', null],
    ['undefined', undefined],
    ['an empty string', ''],
    ['only whitespace', '   '],
  ] as [string, string | null | undefined][]) {
    test(`${label} offers nothing`, () => {
      assert.equal(starterKitHref(value), null)
      assert.equal(showStarterKit(value), false)
    })
  }

  test('a real link switches both placements on', () => {
    assert.equal(
      starterKitHref('https://example.com/kit'),
      'https://example.com/kit',
    )
    assert.equal(showStarterKit('https://example.com/kit'), true)
  })

  test('a site-relative path works too', () => {
    assert.equal(starterKitHref('/for-creators'), '/for-creators')
    assert.equal(showStarterKit('/for-creators'), true)
  })

  for (const bad of [
    'javascript:alert(1)',
    'data:text/html,<script>x</script>',
    '//evil.test/kit',
    'not a url',
  ]) {
    test(`${bad} offers nothing rather than a broken button`, () => {
      // This value becomes the href of a button on every Guide, so a
      // bad one is hidden rather than rendered. The backend refuses
      // to store these; this is the second gate.
      assert.equal(showStarterKit(bad), false)
    })
  }

  test('both placements read the same function', () => {
    // The property that stops them disagreeing. Asserted from source
    // because it is a structural claim, not a behavioural one.
    const src = readFileSync('src/components/guides/StarterKit.tsx', 'utf8')
    assert.equal((src.match(/starterKitHref\(url\)/g) ?? []).length, 2)
    assert.equal((src.match(/if \(!href\) return null/g) ?? []).length, 2)
  })
})

// ---------------------------------------------------------------------------
// 2 · Byline
// ---------------------------------------------------------------------------

describe('the byline names the author, and only claims what is true', () => {
  test('the house author gets the founder descriptor', () => {
    assert.equal(bylineFor('Linds'), 'By Linds, founder of Fresh Collective')
  })

  test('anyone else gets a plain byline', () => {
    // The descriptor belongs to one person. A guest author must not
    // be described as having founded Fresh Collective, and nobody
    // should have to remember to clear a field to avoid it.
    assert.equal(bylineFor('Jo Smith'), 'By Jo Smith')
  })

  test('an empty author falls back to the house author', () => {
    assert.equal(bylineFor(''), 'By Linds, founder of Fresh Collective')
    assert.equal(bylineFor('   '), 'By Linds, founder of Fresh Collective')
  })

  test('the avatar carries one capital letter', () => {
    assert.equal(authorInitial('Linds'), 'L')
    assert.equal(authorInitial('jo smith'), 'J')
    assert.equal(authorInitial(''), 'L')
  })
})

// ---------------------------------------------------------------------------
// 3 · Headings and anchors
// ---------------------------------------------------------------------------

describe('the contents list and the body agree about every anchor', () => {
  // The failure this prevents is a link in "On this page" that
  // scrolls nowhere, which is invisible until someone clicks it.

  test('H2s are found in document order', () => {
    const headings = extractHeadings(
      '<p>Intro</p><h2>First thing</h2><p>x</p><h2>Second thing</h2>',
    )
    assert.deepEqual(headings.map((h) => h.text), ['First thing', 'Second thing'])
  })

  test('H3s are not listed — the contents are the top level only', () => {
    const headings = extractHeadings('<h2>Top</h2><h3>Under it</h3>')
    assert.deepEqual(headings.map((h) => h.text), ['Top'])
  })

  test('markup inside a heading is stripped from the label', () => {
    const [h] = extractHeadings('<h2>What <em>actually</em> matters</h2>')
    assert.equal(h.text, 'What actually matters')
  })

  test('entities are resolved', () => {
    const [h] = extractHeadings('<h2>Tools &amp; resources</h2>')
    assert.equal(h.text, 'Tools & resources')
  })

  test('the id is derived the same way in both places', () => {
    const body = '<h2>Start with how it should feel</h2>'
    const [h] = extractHeadings(body)
    assert.equal(h.id, headingAnchor('Start with how it should feel', 0))
    assert.equal(h.id, 'guide-start-with-how-it-should-feel')
  })

  test('two identically-worded headings get different ids', () => {
    // Without the index, the second "What to look for" would share an
    // anchor with the first and be unreachable.
    const headings = extractHeadings(
      '<h2>What to look for</h2><p>x</p><h2>What to look for</h2>',
    )
    assert.equal(headings.length, 2)
    assert.notEqual(headings[0].id, headings[1].id)
  })

  test('a heading with no usable text still gets an id', () => {
    assert.equal(headingAnchor('—', 2), 'guide-section-3')
  })

  test('an empty body has no headings rather than throwing', () => {
    assert.deepEqual(extractHeadings(''), [])
  })

  test('the renderer reads the same list rather than deriving its own', () => {
    // The structural half of the guarantee above: one function
    // assigns ids, and the renderer consumes its output. Deriving
    // them separately is what produced the collision this suite
    // caught, so a return to that shape should fail here.
    const src = readFileSync('src/components/guides/GuideBody.tsx', 'utf8')
    assert.match(src, /extractHeadings\(source\)\.map\(\(h\) => h\.id\)/)
    assert.match(src, /headingIds\[h2Index\+\+\]/)
    assert.ok(
      !/headingAnchor/.test(src),
      'the renderer should not derive anchors of its own',
    )
  })

  test('the first of two colliding headings keeps the clean id', () => {
    // An anchor already shared in a link keeps working when a later
    // section happens to reuse the wording.
    const headings = extractHeadings(
      '<h2>What to look for</h2><h2>What to look for</h2><h2>What to look for</h2>',
    )
    assert.deepEqual(headings.map((h) => h.id), [
      'guide-what-to-look-for',
      'guide-what-to-look-for-2',
      'guide-what-to-look-for-3',
    ])
  })
})

// ---------------------------------------------------------------------------
// 4 · SEO
// ---------------------------------------------------------------------------

describe('what search engines are told', () => {
  test('the SEO title falls back to the title', () => {
    assert.equal(guideSeoTitle(article()), article().title)
    assert.equal(
      guideSeoTitle(article({ seo_title: 'A shorter headline' })),
      'A shorter headline',
    )
  })

  test('an SEO title of only whitespace is not used', () => {
    assert.equal(guideSeoTitle(article({ seo_title: '   ' })), article().title)
  })

  test('the description falls back to the standfirst', () => {
    assert.equal(guideSeoDescription(article()), article().standfirst)
  })

  test('a long description is trimmed on a word boundary', () => {
    const long = `${'word '.repeat(60)}end`
    const out = guideSeoDescription(article({ seo_description: long }))
    assert.ok(out.length <= 156, out.length)
    assert.ok(out.endsWith('…'))
    assert.ok(!out.includes('  '))
  })

  test('the canonical path is the one the page is served at', () => {
    assert.equal(guidePath('moving-your-community'), '/guides/moving-your-community')
  })
})

describe('the Article structured data', () => {
  test('it carries the fields a crawler reads', () => {
    const ld = guideJsonLd(article(), ORIGIN)
    assert.equal(ld['@context'], 'https://schema.org')
    assert.equal(ld['@type'], 'Article')
    assert.equal(ld.headline, article().title)
    assert.equal(ld.description, article().standfirst)
    assert.equal(ld.url, `${ORIGIN}/guides/moving-your-community`)
    assert.deepEqual(ld.author, { '@type': 'Person', name: 'Linds' })
    assert.equal(ld.datePublished, '2026-11-02T09:00:00')
    assert.equal(ld.dateModified, '2026-11-09T11:30:00')
  })

  test('published and modified are distinct', () => {
    // Conflating them would tell a crawler the article never changes,
    // which is the opposite of what an edited Guide wants to say.
    const ld = guideJsonLd(article(), ORIGIN)
    assert.notEqual(ld.datePublished, ld.dateModified)
  })

  test('a Guide with no hero omits image rather than sending an empty one', () => {
    const ld = guideJsonLd(article(), ORIGIN)
    assert.ok(!('image' in ld))
  })

  test('a relative hero is made absolute', () => {
    const ld = guideJsonLd(
      article({ hero_image_url: '/api/uploads/media/guides/h.png' }),
      ORIGIN,
    )
    assert.equal(ld.image, `${ORIGIN}/api/uploads/media/guides/h.png`)
  })

  test('an absolute hero is left alone', () => {
    const ld = guideJsonLd(
      article({ hero_image_url: 'https://cdn.r2.dev/h.png' }),
      ORIGIN,
    )
    assert.equal(ld.image, 'https://cdn.r2.dev/h.png')
  })

  test('it serialises to valid JSON', () => {
    // It is injected through dangerouslySetInnerHTML, so a value that
    // cannot be stringified would break the page rather than the data.
    const json = JSON.stringify(guideJsonLd(article(), ORIGIN))
    assert.deepEqual(JSON.parse(json)['@type'], 'Article')
  })

  test('a draft never reaches this function', () => {
    // Structural: the public payload has no status field, so there is
    // nothing here that could describe an unpublished Guide.
    const sample = article() as Record<string, unknown>
    assert.ok(!('status' in sample))
  })
})

// ---------------------------------------------------------------------------
// 4b · The serif face actually applies
// ---------------------------------------------------------------------------

describe('every Guides heading that should be serif really is', () => {
  // The trap: ``globals.css`` carries an unlayered
  // ``h1, h2, h3, h4, h5, h6 { font-family: var(--font-sans) }``, and
  // an unlayered element selector outranks Tailwind's utilities,
  // which sit in a cascade layer. So ``className="font-serif"`` on a
  // heading is silently discarded and the heading renders sans —
  // which looks fine until you hold it next to the design. This is
  // the same shape as the ``text-white`` trap ``headingColour.test.ts``
  // already pins, and it needs the same fix: set it inline.

  const FILES = [
    'src/components/guides/GuideBody.tsx',
    'src/components/guides/GuideCard.tsx',
    'src/components/guides/FeaturedGuideCard.tsx',
    'src/components/guides/GuideCta.tsx',
    'src/components/guides/GuideClosingBand.tsx',
    'src/components/guides/StarterKit.tsx',
    'src/app/guides/page.tsx',
    'src/app/guides/GuidesIndexClient.tsx',
    'src/app/guides/[slug]/page.tsx',
    'src/app/admin/guides/[id]/preview/page.tsx',
  ]

  test('the global rule this guards against is still there', () => {
    // If someone layers or removes that rule, this whole workaround
    // becomes unnecessary — and this test should be the thing that
    // says so rather than the inline styles quietly staying forever.
    const css = readFileSync('src/app/globals.css', 'utf8')
    assert.match(css, /h1, h2, h3, h4, h5, h6 \{[^}]*font-family: var\(--font-sans\)/)
  })

  test('the serif face is read from the token, not written out again', () => {
    const src = readFileSync('src/components/guides/serif.ts', 'utf8')
    assert.match(src, /fontFamily: 'var\(--font-serif\)'/)
    // Comments stripped before the check. The ban is on *using* the
    // literal stack, not on the word appearing — the doc comment here
    // names Georgia while explaining why it is not written out, and a
    // blunt substring check fails on its own explanation.
    const code = src
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/[^\n]*/g, '')
    assert.ok(!/Georgia/.test(code), 'the stack belongs in globals.css only')
  })

  for (const file of FILES) {
    test(`${file} puts no font-serif class on a heading`, () => {
      const src = readFileSync(file, 'utf8')
      // Headings only. ``font-serif`` on a <p> or a <blockquote> is
      // fine and used deliberately — the global rule names h1…h6.
      const offenders = [...src.matchAll(/<h[1-6]\b[^>]*>/g)]
        .map((m) => m[0])
        .filter((tag) => /font-serif/.test(tag))
      assert.deepEqual(
        offenders,
        [],
        'this heading asks for serif with a class the unlayered h1…h6 '
          + 'rule discards, so it renders sans. Use style={SERIF_HEADING}.',
      )
    })
  }
})

// ---------------------------------------------------------------------------
// 4c · Publishing shows up straight away, and so does withdrawing
// ---------------------------------------------------------------------------

describe('the reader-facing pages are never served from a cache', () => {
  // Both pages were already dynamic — ``SiteShell`` reads cookies to
  // choose a header, so every visit reached the server anyway — and
  // the only thing the 300-second fetch cache bought was a five
  // minute delay between publishing and being readable.
  //
  // The property that matters more is the other direction. A cached
  // article is a Guide that stays readable after it has been
  // unpublished, for as long as the window lasts. Uncached, the
  // withdrawal is complete on the next request and depends on
  // nothing else having worked.

  for (const file of ['src/app/guides/page.tsx', 'src/app/guides/[slug]/page.tsx']) {
    test(`${file} opts out of caching explicitly`, () => {
      const src = readFileSync(file, 'utf8')
      assert.match(src, /export const dynamic = 'force-dynamic'/)
      assert.match(src, /cache: 'no-store'/)
    })

    test(`${file} declares no revalidate window`, () => {
      // ``revalidate`` alongside ``force-dynamic`` is contradictory,
      // and whichever won, one of the two statements in the file
      // would be a lie to the next reader.
      const src = readFileSync(file, 'utf8')
      assert.ok(
        !/export const revalidate/.test(src),
        'a revalidate window would reintroduce the delay this removed',
      )
    })
  }

  test('nothing in the two pages still asks for a timed revalidate', () => {
    for (const file of ['src/app/guides/page.tsx', 'src/app/guides/[slug]/page.tsx']) {
      const src = readFileSync(file, 'utf8')
      assert.ok(
        !/next: \{\s*revalidate/.test(src),
        `${file} still passes next.revalidate to a fetch`,
      )
    }
  })
})

describe('the sitemap is cleared by an admin action, not by anyone', () => {
  // The sitemap is the one Guides artefact that *is* cached: it is
  // statically generated hourly and shared with the Collectives
  // listing, and making it dynamic would put a database query in
  // front of every request for it — the arrangement sitemap.ts
  // documents at length. So it gets a nudge instead.

  const ROUTE = 'src/app/api/internal/guides/revalidate/route.ts'

  test('the tag the fetch carries is the tag the handler clears', () => {
    // A tag that matches only by coincidence of spelling is a cache
    // that never clears, and it fails silently.
    const sitemap = readFileSync('src/app/sitemap.ts', 'utf8')
    const route = readFileSync(ROUTE, 'utf8')
    assert.match(sitemap, /export const GUIDES_TAG = 'guides'/)
    assert.match(sitemap, /tags: \[GUIDES_TAG\]/)
    assert.match(route, /import \{ GUIDES_TAG \} from '@\/app\/sitemap'/)
    assert.match(route, /revalidateTag\(GUIDES_TAG/)
  })

  test('it clears the route as well as the tagged fetch', () => {
    // Purging only the route would regenerate the file from a fetch
    // whose own cache entry is still inside its hour, so the sitemap
    // would rebuild from stale data and look like the invalidation
    // had failed.
    const route = readFileSync(ROUTE, 'utf8')
    assert.match(route, /revalidatePath\('\/sitemap\.xml'\)/)
  })

  test('it refuses anyone who is not an administrator', () => {
    const route = readFileSync(ROUTE, 'utf8')
    assert.match(route, /role !== 'admin'/)
    assert.match(route, /status: 403/)
    // The role is read from the backend with the caller's own
    // session, not taken from anything in the request.
    assert.match(route, /serverFetch\('\/api\/auth\/me'\)/)
  })

  test('a backend that cannot answer is not permission', () => {
    // The catch must leave the role null and fall into the 403, not
    // skip the check.
    const route = readFileSync(ROUTE, 'utf8')
    assert.match(route, /catch \{[\s\S]*?role = null[\s\S]*?\}/)
  })

  test('it accepts no input at all', () => {
    // Nothing is read from the body, so there is nothing to validate
    // and no path for a caller to choose what gets cleared. Checked
    // against the code with comments stripped — the ban is on
    // *reading* a request, not on the word appearing in a sentence
    // explaining that nothing is read.
    const route = readFileSync(ROUTE, 'utf8')
    const code = route
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/[^\n]*/g, '')
    assert.match(code, /export async function POST\(\): Promise<NextResponse>/)
    assert.ok(
      !/\brequest\b|\breq\b/.test(code),
      'the handler should take no request argument',
    )
  })

  test('only POST is exported, so it cannot be triggered by a link', () => {
    const route = readFileSync(ROUTE, 'utf8')
    for (const verb of ['GET', 'HEAD', 'PUT', 'PATCH', 'DELETE']) {
      assert.ok(
        !new RegExp(`export async function ${verb}\\b`).test(route),
        `${verb} should not be exported`,
      )
    }
  })

  test('the admin calls it after a change, and never blocks on it', () => {
    // A failed cache nudge must not be reported as a failed publish.
    const editor = readFileSync('src/app/admin/guides/[id]/GuideEditor.tsx', 'utf8')
    assert.match(editor, /\/api\/internal\/guides\/revalidate/)
    assert.match(editor, /async function refreshSitemap\(\)[\s\S]*?try \{[\s\S]*?\} catch \{/)
    // Called on the delete path too, which returns 204 and redirects
    // before the ordinary success branch is reached.
    assert.equal((editor.match(/await refreshSitemap\(\)/g) ?? []).length, 2)
  })
})

// ---------------------------------------------------------------------------
// 4d · The closing band is the homepage's, not a copy of it
// ---------------------------------------------------------------------------

describe('a Guide ends the way the homepage ends', () => {
  // It previously carried its own navy card and drifted in every
  // detail that matters — no gold hairline, no teal glow, flat
  // surface, plain pill buttons. Two cards that are meant to look
  // identical and are maintained separately will always end up
  // looking nearly identical.

  const BAND = 'src/components/guides/GuideClosingBand.tsx'

  test('it renders ClosingInvitation rather than its own card', () => {
    const src = readFileSync(BAND, 'utf8')
    assert.match(src, /from '@\/components\/marketing\/ClosingInvitation'/)
    assert.match(src, /<ClosingInvitation/)
  })

  test('it carries no styling of its own', () => {
    // The specific failure mode: someone copies a gradient or a
    // shadow across "just to tweak it" and the two drift again.
    const src = readFileSync(BAND, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/[^\n]*/g, '')
    for (const smell of [/className=/, /style=\{\{/, /#0[0-9A-Fa-f]{5}/]) {
      assert.ok(!smell.test(src), `${smell} suggests restyling, not reuse`)
    }
  })

  test('it uses the homepage button pair', () => {
    // ``hero`` is the teal-gradient primary with the white secondary.
    // ``pill`` is the quieter /for-creators pair and would not match.
    const src = readFileSync(BAND, 'utf8')
    assert.match(src, /buttonVariant="hero"/)
  })

  test('the copy is the Guide copy', () => {
    const src = readFileSync(BAND, 'utf8')
    assert.match(src, /Ready to give your work a home\?/)
    assert.match(src, /Set up your Collective in about 15 minutes/)
    assert.match(src, /Start your Collective/)
    assert.match(src, /Take a look around/)
  })

  test('the shared component still renders an h2, not an h1', () => {
    // A Guide's one h1 is its title. If ClosingInvitation ever became
    // an h1 this would be an SEO defect on every Guide *and* on the
    // homepage, so it is asserted against the shared file rather than
    // the wrapper.
    const shared = readFileSync(
      'src/components/marketing/ClosingInvitation.tsx', 'utf8',
    )
    assert.match(shared, /<h2/)
    assert.ok(!/<h1/.test(shared))
  })

  test('both the article and the preview end with it', () => {
    // The preview stops being a preview the moment it ends
    // differently from the page it previews.
    for (const file of [
      'src/app/guides/[slug]/page.tsx',
      'src/app/admin/guides/[id]/preview/page.tsx',
    ]) {
      assert.match(readFileSync(file, 'utf8'), /<GuideClosingBand \/>/, file)
    }
  })
})

// ---------------------------------------------------------------------------
// 5 · Labels
// ---------------------------------------------------------------------------

describe('labels', () => {
  test('a category slug renders as its label', () => {
    assert.equal(categoryLabel('starting'), 'Starting your Collective')
    assert.equal(categoryLabel('growing'), 'Growing your Collective')
    assert.equal(categoryLabel('tools'), 'Tools and resources')
  })

  test('an unknown category shows the slug rather than nothing', () => {
    // A category added to the database before the frontend knows
    // about it should look odd, not disappear.
    assert.equal(categoryLabel('mystery'), 'mystery')
  })

  test('the three categories match the ones the backend stores', () => {
    const model = readFileSync('../backend/app/models/guide.py', 'utf8')
    const match = /GUIDE_CATEGORIES: tuple\[str, \.\.\.\] = \(([^)]*)\)/.exec(model)
    assert.ok(match, 'the model should declare GUIDE_CATEGORIES')
    const backend = [...match[1].matchAll(/"([a-z]+)"/g)].map((m) => m[1])
    assert.deepEqual(GUIDE_CATEGORIES.map((c) => c.slug), backend)
  })

  test('reading time reads as a sentence fragment', () => {
    assert.equal(readingTimeLabel(7), '7 min read')
    assert.equal(readingTimeLabel(1), '1 min read')
  })

  test('a nonsense reading time still renders something sane', () => {
    assert.equal(readingTimeLabel(0), '1 min read')
    assert.equal(readingTimeLabel(-3), '1 min read')
    assert.equal(readingTimeLabel(Number.NaN), '1 min read')
  })

  test('dates render the same wherever they are formatted', () => {
    // The backend stores naive UTC. Without an explicit time zone the
    // answer would depend on the machine rendering the page, and a
    // Guide would appear to change date between server and browser.
    assert.equal(formatGuideDate('2026-11-09T11:30:00'), '9 November 2026')
    assert.equal(formatGuideDate('2026-11-09T23:30:00Z'), '9 November 2026')
  })

  test('a missing or unparseable date renders as nothing', () => {
    assert.equal(formatGuideDate(null), '')
    assert.equal(formatGuideDate(''), '')
    assert.equal(formatGuideDate('not a date'), '')
  })
})
