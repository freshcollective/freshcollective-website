import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync, readdirSync } from 'node:fs'

import { CREATOR_FAQ } from './creatorFaq.ts'

import {
  ABOUT_IMAGES,
  ABOUT_INTRO,
  ABOUT_INVITATION,
  ABOUT_PHOTOGRAPHER,
  ABOUT_PHOTOGRAPHER_URL,
  ABOUT_PHOTO_CREDIT,
  ABOUT_PHOTO_CREDIT_PREFIX,
  ABOUT_SECTIONS,
  ABOUT_TITLE_LINES,
  ABOUT_SIGNATURE,
  ABOUT_TITLE,
  ABOUT_VIDEO_LABEL,
  ABOUT_VIDEO_URL,
  ABOUT_VISION,
} from './aboutStory.ts'

/**
 * Contract tests for the About page.
 *
 * Two kinds. The first asserts the approved copy is intact and in
 * order — this page is a piece of personal writing and a well-meaning
 * tidy-up is the most likely way it gets damaged. The second asserts
 * what the page and its two entry points are wired to, and that
 * nothing in the Creator plans or the Creator FAQ moved as a side
 * effect.
 *
 * Source reads are comment-stripped before matching: a doc comment
 * that happens to mention a string must not stand in for the code
 * actually using it.
 */

const read = (p: string) => readFileSync(p, 'utf8')

const codeOnly = (src: string) =>
  src
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const PAGE = codeOnly(read('src/app/about/page.tsx'))
const FOOTER = codeOnly(read('src/components/layout/PublicFooter.tsx'))
const FOR_CREATORS = codeOnly(read('src/app/for-creators/page.tsx'))
const CLOSING_CARD = read('src/components/marketing/ClosingInvitation.tsx')
const HOMEPAGE = read('src/app/page.tsx')

const allParagraphs = ABOUT_SECTIONS.flatMap((s) => s.paragraphs)
const allProse = [
  ABOUT_INTRO,
  ...ABOUT_SECTIONS.flatMap((s) => [s.heading, ...s.paragraphs.map((p) => p.text)]),
  ABOUT_VIDEO_LABEL,
  ABOUT_VIDEO_URL,
  ABOUT_VISION,
  ABOUT_INVITATION,
].join('\n')

describe('the approved story', () => {
  test('it opens in the first person, introducing Linds', () => {
    assert.match(ABOUT_INTRO, /^Hi, I’m Linds\./)
    assert.match(ABOUT_INTRO, /one of the creators here/)
  })

  test('the five section headings are present, in the approved order', () => {
    assert.deepEqual(
      ABOUT_SECTIONS.map((s) => s.heading),
      [
        'It started with a gap I kept falling into',
        'And I was doing it all on my own',
        'The idea I kept coming back to',
        'Why it looks and feels the way it does',
        'What I hope you find here',
      ],
    )
  })

  test('the March 2026 walk is the turning point, told in full', () => {
    const story = allParagraphs.map((p) => p.text).join('\n')
    // The walk, the friend stopping her, and the reminder. All three,
    // because the anecdote does not work with any one of them missing.
    assert.match(story, /in March 2026, that same friend and I were out walking/)
    assert.match(story, /She stopped me and reminded me of the dream/)
    assert.match(story, /Fresh Collective got a makeover/)
  })

  test('one line is marked as the turning point, and it is the right one', () => {
    const emphasised = allParagraphs.filter((p) => p.emphasis === 'turning-point')
    assert.equal(emphasised.length, 1)
    assert.equal(
      emphasised[0].text,
      'A world of many Collectives, rather than just mine.',
    )
  })

  test('the vision statement is the approved sentence, exactly', () => {
    assert.equal(
      ABOUT_VISION,
      'A world where people can discover themselves through discovering each other.',
    )
  })

  test('it closes with the invitation and the signature', () => {
    assert.equal(ABOUT_INVITATION, 'Please come in and have a look around.')
    assert.equal(ABOUT_SIGNATURE, 'Linds')
  })

  test('the things that make it personal are all still in it', () => {
    // Named explicitly in the brief as the parts that must survive:
    // the loneliness, the silos, the breadth of her own work, and the
    // creators-only Collective she built for the same reason.
    assert.match(allProse, /It was lonely/)
    assert.match(allProse, /silo/)
    assert.match(allProse, /movement, leadership and Human Design/)
    assert.match(allProse, /World Builders Collective/)
    assert.match(allProse, /Facebook/)
  })

  test('sentences developing one thought sit together', () => {
    // The story was 36 paragraphs with a gap after almost every
    // sentence, which made a short piece read as a long one. It is
    // now 21: related sentences joined, no words changed.
    assert.equal(allParagraphs.length, 21)
    // The March 2026 walk is one connected anecdote rather than four
    // separate beats — the single clearest symptom of the old split.
    const walk = allParagraphs.find((p) => p.text.includes('out walking'))!
    assert.match(walk.text, /going on \(and on!\)/)
    assert.match(walk.text, /She stopped me and reminded me/)
  })

  test('the standalone beats that carry emphasis survive', () => {
    // Grouping must not flatten everything. A handful of lines stand
    // alone because the pause is the point, and merging them in
    // would cost the voice more than the length saved.
    const short = allParagraphs.filter((p) => p.text.length < 80)
    assert.ok(
      short.length >= 4,
      `the standalone beats were flattened; only ${short.length} remain`,
    )
    for (const beat of [
      'And someone would be there to bring it all together.',
      'So I built a place that could hold it all.',
    ]) {
      assert.ok(
        allParagraphs.some((p) => p.text === beat),
        `lost a standalone beat: ${beat}`,
      )
    }
  })

  test('the spelling is Australian', () => {
    // -ise / -isation, never -ize / -ization.
    const americanised = allProse.match(/\b\w+(?:ize[dsr]?|ization)\b/gi)
    assert.equal(americanised, null, `American spelling: ${americanised}`)
  })

  test('no price, fee or percentage is quoted anywhere in the story', () => {
    // Prices live in ``plans.ts`` and the Creator FAQ. A number
    // repeated here would be a fourth place to forget to update.
    assert.equal(allProse.match(/\$\s?\d/g), null)
    assert.equal(allProse.match(/\d+\s?%/g), null)
  })
})

describe('the two photographs', () => {
  test('both are referenced, and only those two', () => {
    assert.equal(ABOUT_IMAGES.hero.src, '/about/fig-tree-hero.jpg')
    assert.equal(ABOUT_IMAGES.portrait.src, '/about/willow-portrait.webp')

    // No third image, generated placeholder or stock substitute has
    // crept into the page. Anything the page points at under an image
    // directory must be one of the two supplied files.
    const referenced = PAGE.match(/["'](\/[\w/-]+\.(?:jpe?g|png|webp|avif|svg))["']/g) ?? []
    assert.deepEqual(referenced, [])
  })

  test('each has alt text that describes the photograph', () => {
    for (const image of [ABOUT_IMAGES.hero, ABOUT_IMAGES.portrait]) {
      assert.ok(image.alt.length > 30, `thin alt text: ${image.alt}`)
      assert.match(image.alt, /Linds/)
    }
    assert.match(ABOUT_IMAGES.hero.alt, /fig tree/)
    assert.match(ABOUT_IMAGES.portrait.alt, /willow/)
  })

  test('they are rendered through next/image, like every other page photo', () => {
    assert.match(PAGE, /from 'next\/image'/)
    // Two frames, each reserving its space with an aspect ratio so
    // the page does not jump when the photographs decode.
    assert.equal((PAGE.match(/\bfill\b/g) ?? []).length, 2)
    assert.ok((PAGE.match(/aspect-\[/g) ?? []).length >= 2)
    assert.match(PAGE, /priority/)
  })

  test('neither photograph is filtered or graded', () => {
    assert.equal(PAGE.match(/filter:|saturate\(|contrast\(|grayscale|sepia/g), null)
  })

  test('no new image-management system was introduced', () => {
    // The photographs are static files under ``public/`` served by
    // ``next/image``, which is what ``HomeHero`` already does. No
    // loader, no remote pattern, no new dependency.
    const config = read('next.config.ts')
    assert.equal(/images\s*:/.test(config), false)
    const pkg = JSON.parse(read('package.json'))
    for (const dep of Object.keys(pkg.dependencies ?? {})) {
      assert.ok(
        !/sharp|cloudinary|imgix|image-?kit/.test(dep),
        `unexpected image dependency: ${dep}`,
      )
    }
  })
})

describe('the page itself', () => {
  test('it wears the shared header and footer', () => {
    assert.match(PAGE, /SiteShell/)
    assert.match(PAGE, /<SiteShell>/)
  })

  test('the heading structure is one h1 and a h2 per section', () => {
    assert.equal((PAGE.match(/<h1\b/g) ?? []).length, 1)
    // Two in source: one rendered per story section, one for the
    // closing invitation, which is that section's heading and is now
    // set as one rather than carrying a font size of its own.
    assert.equal((PAGE.match(/<h2\b/g) ?? []).length, 2)
    assert.match(PAGE, /ABOUT_SECTIONS\.map/)
    assert.equal(ABOUT_TITLE, 'Why Fresh Collective exists')
  })

  test('the two closing buttons reuse existing destinations', () => {
    assert.match(PAGE, /HeroPrimaryCta href="\/for-creators#plans"/)
    assert.match(PAGE, /HeroSecondaryCta href="\/spaces"/)
    // "Choose your plan" on /for-creators is the destination being
    // reused; if that page ever moves its plans anchor, this fails
    // here rather than silently sending people nowhere.
    assert.match(FOR_CREATORS, /href: '\/for-creators#plans'/)
    assert.match(FOR_CREATORS, /id="plans"/)
  })

  test('it reuses the shared CTA pair rather than restyling buttons', () => {
    assert.match(PAGE, /from '@\/components\/marketing\/heroCtaButtons'/)
  })

  test('it is indexable, canonical and shares a real image', () => {
    assert.match(PAGE, /title: 'Why Fresh Collective Exists \| Our Story'/)
    assert.match(PAGE, /alternates: \{ canonical: CANONICAL \}/)
    assert.match(PAGE, /const CANONICAL = '\/about'/)
    assert.match(PAGE, /openGraph/)
    assert.match(PAGE, /card: 'summary_large_image'/)
    // Nothing switching the page to noindex.
    assert.equal(/robots/.test(PAGE), false)
    // The OG image is the hero photograph, not a new asset.
    assert.match(PAGE, /images: \[\{ url: ABOUT_IMAGES\.hero\.src/)
  })

  test('the description is the approved one', () => {
    const page = read('src/app/about/page.tsx')
    assert.match(page, /Discover why Fresh Collective was created/)
    assert.match(page, /connection, collaboration, belonging/)
  })

  test('no schema markup was bolted on for its own sake', () => {
    // The FAQ page has JSON-LD because it answers questions a search
    // engine can present. A personal essay has nothing to declare.
    assert.equal(/application\/ld\+json/.test(PAGE), false)
  })

  test('nothing private is exposed in the metadata', () => {
    const everything = read('src/app/about/page.tsx') + read('src/lib/aboutStory.ts')
    // An address would be a leak wherever it appeared, comments
    // included, so this one reads the whole file.
    assert.equal(/@[\w.-]+\.(?:com|au|org|net)/.test(everything), false)
    // A number sequence is only a leak if the page renders it. Run
    // over the whole file this matched a column of contrast
    // measurements in a comment — the regex cannot tell a phone
    // number from "0.091      0.54", and the fix is to ask the
    // question of the code rather than to blunt the pattern.
    const code = codeOnly(read('src/app/about/page.tsx')) + codeOnly(read('src/lib/aboutStory.ts'))
    assert.equal(/\+?\d[\d ]{7,}\d/.test(code), false)
  })
})

describe('the two ways in', () => {
  test('the footer links to the page, in its existing nav', () => {
    assert.match(FOOTER, /\{ href: '\/about',\s+label: 'About Fresh Collective' \}/)
    // The links that were already there are all still there.
    for (const href of ["'/spaces'", "'/login'", "'/signup'"]) {
      assert.ok(FOOTER.includes(href), `footer lost ${href}`)
    }
    assert.match(FOOTER, /aria-label="Footer"/)
    assert.match(FOOTER, /world-guide/)
  })

  test('the footer link is a Link, not a bare anchor', () => {
    assert.match(FOOTER, /from 'next\/link'/)
  })

  test('For Creators carries one quiet text link to the story', () => {
    assert.match(FOR_CREATORS, /Discover why Fresh Collective exists →/)
    assert.match(FOR_CREATORS, /href="\/about"/)
    // One link, and not a button: the page already has exactly one
    // primary action and it is "Choose your plan".
    assert.equal((FOR_CREATORS.match(/href="\/about"/g) ?? []).length, 1)
    assert.equal(/HeroPrimaryCta[^>]*\/about/.test(FOR_CREATORS), false)
  })

  test('it sits after the closing CTA and the FAQ, so it interrupts nothing', () => {
    const order = ['<PlansSection', '<ClosingInvitation', '<FaqSection', '<AboutStoryLink']
    let cursor = -1
    for (const marker of order) {
      const at = FOR_CREATORS.indexOf(marker)
      assert.ok(at > cursor, `${marker} is out of order`)
      cursor = at
    }
  })
})

describe('what must not have changed', () => {
  test('the Creator plan prices still come from one place, untouched', () => {
    const plans = read('src/lib/plans.ts')
    assert.match(plans, /\$19 \/ month/)
    assert.match(plans, /\$79 \/ month/)
    assert.match(plans, /commissionBasisPoints: 800/)
    assert.match(plans, /commissionBasisPoints: 400/)
    // And no price is written into the About page or its content.
    assert.equal(/\$\d/.test(read('src/app/about/page.tsx')), false)
    assert.equal(/\$\d/.test(read('src/lib/aboutStory.ts')), false)
  })

  test('the Creator FAQ is exactly as published', () => {
    const faq = read('src/lib/creatorFaq.ts')
    // The question set is the contract; a changed count means the FAQ
    // was edited, which this change had no business doing. Counted
    // from the entries themselves rather than from the string
    // ``question:``, which also appears in the item type.
    assert.equal(CREATOR_FAQ.length, 7)
    assert.match(faq, /creatorFaqJsonLd/)
    assert.match(FOR_CREATORS, /creatorFaqJsonLd\(\)/)
  })

  test('the About page does not touch membership, payment or Stripe code', () => {
    const page = read('src/app/about/page.tsx') + read('src/lib/aboutStory.ts')
    assert.equal(/stripe|checkout|subscription|entitlement/i.test(page), false)
  })
})

describe('it looks like the rest of the site', () => {
  test('both statements share one pull-quote treatment', () => {
    // The turning point used to be a deep-navy card borrowed from
    // ``ClosingInvitation`` — gold rule, teal glow, the lot. One
    // component renders both quotes now, so they cannot drift into
    // two treatments: same colour, same width, same family, same
    // centring, and only the slope differs.
    const quote = PAGE.slice(PAGE.indexOf('function PullQuote'), PAGE.indexOf('function Closing'))
    assert.match(quote, /color: TEAL_DEEP/)
    assert.match(quote, /max-w-\[44rem\] text-center/)
    assert.match(quote, /font-serif/)
    assert.match(quote, /italic \? 'italic' : ''/)
    // Called twice: the turning point in italic, the vision upright.
    assert.match(PAGE, /<PullQuote key=\{p\.text\} text=\{p\.text\} italic \/>/)
    assert.match(PAGE, /<PullQuote text=\{ABOUT_VISION\} \/>/)
  })

  test('neither quote has a box, a dark ground, a rule or a border', () => {
    const quote = PAGE.slice(PAGE.indexOf('function PullQuote'), PAGE.indexOf('function Closing'))
    for (const banned of ['background', 'boxShadow', 'rounded-3xl', 'border', 'GOLD_RULE', 'NAVY_DEEP']) {
      assert.equal(quote.includes(banned), false, `the quote grew a ${banned}`)
    }
    // And nothing anywhere on the page still reaches for the card.
    assert.equal(/NAVY_DEEP|TEAL_GLOW|GOLD_RULE|max-w-\[1080px\]/.test(PAGE), false)
  })

  test('every colour on the page is a hue the site already uses', () => {
    // The brief was explicit: no sage, eucalyptus, cream, beige or
    // pale-teal panels. Rather than list what is banned — an endless
    // and unfalsifiable list — every colour in the page is reduced to
    // its RGB triple and checked against the hues the homepage, its
    // components, the shared closing card and /for-creators already
    // use. Opacity is ignored on purpose: the same navy at a new
    // alpha is the same colour, while a new hue is a new colour.
    const triples = (src: string) => {
      const out = new Set<string>()
      for (const m of src.matchAll(/#([0-9A-Fa-f]{6})\b/g)) {
        const h = m[1].toUpperCase()
        out.add([0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).join(','))
      }
      for (const m of src.matchAll(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/g)) {
        out.add(`${+m[1]},${+m[2]},${+m[3]}`)
      }
      return out
    }

    const homeComponents = readdirSync('src/components/home')
      .filter((f) => f.endsWith('.tsx'))
      .map((f) => read(`src/components/home/${f}`))
      .join('\n')
    const established = triples(
      HOMEPAGE + homeComponents + CLOSING_CARD + FOR_CREATORS
      + read('src/app/globals.css'),
    )

    const strays = [...triples(PAGE)].filter((c) => {
      if (established.has(c)) return false
      // The two grounds behind the photo frames, which hold the space
      // while each photograph decodes. Neither is page furniture and
      // neither is visible once the images load.
      return !['19,33,28', '27,42,34'].includes(c)
    })
    assert.deepEqual(strays, [], `hues not used anywhere else on the site: ${strays}`)
  })

  test('body copy is the homepage editorial style, to the value', () => {
    // Measured off the rendered homepage, not chosen: its widest
    // editorial paragraph is Georgia 17px / 1.8 / -0.01em at
    // rgba(12,24,38,0.82) with 24px between paragraphs. Setting the
    // same family at a different size and spacing — which an earlier
    // pass did — still does not look like the same website.
    // 19px rather than the homepage's 17px: this is a long read
    // rather than a paragraph between artwork, and at 17px the
    // section headings dominated the prose they introduce. Family,
    // tracking, colour and the 24px gap are the homepage's exactly.
    assert.match(PAGE, /const BODY_CLASS = 'font-serif text-\[19px\] leading-\[1\.75\] tracking-\[-0\.01em\]'/)
    assert.match(PAGE, /const BODY_INK = 'rgba\(12, 24, 38, 0\.82\)'/)
    assert.match(PAGE, /className=\{`mt-6 \$\{BODY_CLASS\}`\}/)
  })

  test('section headings are the homepage heading treatment', () => {
    // 600 weight sans, 1.06 line height, -0.03em, full navy. The
    // homepage sets these at 44px and 40px; 40px is the top of the
    // range here because five run in sequence down one story.
    assert.match(PAGE, /const HEADING_CLASS = 'font-sans font-semibold'/)
    assert.match(PAGE, /lineHeight: 1\.06/)
    assert.match(PAGE, /letterSpacing: '-0\.03em'/)
    // Tops out at 35.2px. The homepage's own 44px and 40px are for
    // headings that open a whole region; five in sequence above body
    // copy need to signpost rather than announce.
    assert.match(PAGE, /fontSize: 'clamp\(1\.7rem, 3\.4vw, 2\.2rem\)'/)
  })

  test('the closing has no typography of its own', () => {
    const closing = PAGE.slice(PAGE.indexOf('function Closing'), PAGE.indexOf('function PhotoCredit'))
    // The invitation is a heading and uses the heading tokens; the
    // signature is the body face. Neither restates a font size, a
    // letter spacing or a family — those overrides were the reason
    // the ending read as though it came from a different page.
    assert.match(closing, /<h2 className=\{HEADING_CLASS\} style=\{HEADING_STYLE\}>/)
    assert.match(closing, /italic \$\{BODY_CLASS\}/)
    assert.equal(/letterSpacing/.test(closing), false)
    assert.equal(/fontSize: '1\.4rem'/.test(closing), false)
  })

  test('the reading column is the homepage\'s own widest measure', () => {
    // 760px — what the homepage itself sets, and what puts the line
    // length at its 79 characters. Was 544px, then 816px; the latter
    // was inside the range asked for but ran five characters a line
    // longer than anything on the homepage.
    assert.match(PAGE, /const READING_COLUMN = 'mx-auto max-w-\[760px\]'/)
    assert.equal(/max-w-\[34rem\]|max-w-\[51rem\]/.test(PAGE), false)
    // The two pull-quotes are narrower than the prose, not wider —
    // nothing on the page breaks out past the reading column now
    // that the navy card is gone.
    assert.match(PAGE, /max-w-\[44rem\] text-center/)
  })

  test('the hero carries the homepage hero\'s typography', () => {
    // 660 weight, 1.02 line height, -0.04em — read off the rendered
    // homepage h1. The size cannot be copied with them: the homepage
    // image is near-empty on the left, while this one has Linds, a
    // trunk and roots across half the frame.
    assert.match(PAGE, /fontWeight: 660/)
    assert.match(PAGE, /lineHeight: 1\.02/)
    assert.match(PAGE, /letterSpacing: '-0\.04em'/)
    assert.match(PAGE, /xl:text-\[5\.5rem\]/)   // 88px, from 52px
  })

  test('the hero wash darkens the right only, and has no edge', () => {
    // An even wash over the whole frame spent the photograph's
    // natural light to solve a problem that exists on one side.
    // This darkens where the headline is and leaves the left — the
    // tree, the roots, Linds — at the picture's own brightness.
    const hero = PAGE.slice(PAGE.indexOf('function Hero'), PAGE.indexOf('function Story'))
    assert.match(read('src/components/home/HomeHero.tsx'), /rgba\(7,20,24,/)  // the ink
    assert.match(hero, /linear-gradient\(to left, /)
    // Many stops, because a straight two-stop ramp changes slope
    // abruptly at both ends and that kink reads as a vertical band —
    // which is exactly what the first directional attempt did.
    const stops = hero.match(/rgba\(7,20,24,[\d.]+\) \d+%/g) ?? []
    assert.ok(stops.length >= 10, `expected an eased curve, got ${stops.length} stops`)
    // It must reach nothing, and well before the left half.
    assert.match(hero, /rgba\(7,20,24,0\.00\) 62%/)
    // Only where the headline is on the photograph.
    assert.match(hero, /pointer-events-none absolute inset-0 hidden md:block/)
  })

  test('the headline golds one word, with the homepage hero\'s gold', () => {
    // #EDBE5D is the gold HomeHero and HomeWhatThisIs use on dark
    // grounds; #D4B048 is the duller one for light grounds and would
    // be the wrong choice over a photograph.
    // Gold on the photograph, from the homepage hero. Below the
    // breakpoint the word sits on the page instead, where gold of
    // either shade measures about 2:1 — so it takes the page's own
    // teal accent, the one the vision statement already uses.
    assert.match(read('src/components/home/HomeHero.tsx'), /#EDBE5D/)
    assert.match(PAGE, /const TEAL_DEEP = '#246B6A'/)
    // Literal, not interpolated. Tailwind generates rules only for
    // class names it can see in the source, so a template literal
    // here produces no CSS and the word is not gold at any width.
    assert.match(PAGE, /'block \[--about-gold:#246B6A\] md:\[--about-gold:#EDBE5D\]'/)
    assert.equal(/--about-gold:\$\{/.test(PAGE), false)
    const gold = ABOUT_TITLE_LINES.filter((l) => l.gold)
    assert.equal(gold.length, 1)
    assert.equal(gold[0].text, 'Collective')
  })

  test('there is no eyebrow label above the heading', () => {
    // A standing instruction for this platform, and for this page in
    // particular: no small uppercase labels above headings.
    const hero = PAGE.slice(PAGE.indexOf('function Hero'), PAGE.indexOf('function Story'))
    assert.equal(/uppercase/.test(hero), false)
    assert.equal(/ABOUT_EYEBROW/.test(PAGE), false)
    assert.equal(/ABOUT_EYEBROW/.test(read('src/lib/aboutStory.ts')), false)
  })

  })

describe('the closing block', () => {
  test('the video link is the quiet third option, under the buttons', () => {
    const closing = PAGE.slice(PAGE.indexOf('function Closing'), PAGE.indexOf('function PhotoCredit'))
    assert.equal(ABOUT_VIDEO_LABEL, 'Or see inside in a minute →')
    assert.equal(ABOUT_VIDEO_URL, 'https://youtu.be/MTXKOxzcl6I?si=rJWftUtovKTXpJ2Q')
    assert.match(closing, /href=\{ABOUT_VIDEO_URL\}/)
    assert.match(closing, /target="_blank"/)
    assert.match(closing, /rel="noopener noreferrer"/)
    assert.match(closing, /focus-visible:outline-\[#246B6A\]/)
    // A link, not a third button: three buttons on one row would
    // have read as three equal choices.
    assert.equal(/HeroPrimaryCta[^>]*ABOUT_VIDEO|HeroSecondaryCta[^>]*ABOUT_VIDEO/.test(closing), false)
    // And after the two buttons in the source order, which is what
    // a phone reads top to bottom.
    assert.ok(closing.indexOf('Explore Collectives') < closing.indexOf('ABOUT_VIDEO_URL'))
  })

  test('no video player is embedded', () => {
    assert.equal(/<iframe|youtube\.com\/embed|react-player/.test(PAGE), false)
  })

  test('on a phone the words come before the portrait', () => {
    // The portrait used to carry ``order-first``, which pushed the
    // invitation, the buttons and the video link a long way down a
    // phone screen. Ordinary flow now reads invitation, signature,
    // buttons, video link, portrait, credit.
    const closing = PAGE.slice(PAGE.indexOf('function Closing'), PAGE.indexOf('function PhotoCredit'))
    assert.equal(/order-first/.test(closing), false)
    assert.ok(closing.indexOf('ABOUT_INVITATION') < closing.indexOf('data-about-frame="portrait"'))
    // Desktop still puts it beside the text.
    assert.match(closing, /lg:grid-cols-\[1fr_minmax\(0,22rem\)\]/)
  })
})

describe('the photo credit', () => {
  test('it names the photographer', () => {
    assert.equal(ABOUT_PHOTO_CREDIT, 'Photographs by Narelle Kate Photography')
    assert.equal(ABOUT_PHOTOGRAPHER, 'Narelle Kate Photography')
    assert.equal(ABOUT_PHOTO_CREDIT_PREFIX + ABOUT_PHOTOGRAPHER, ABOUT_PHOTO_CREDIT)
  })

  test('the photographer\'s name links to her site, safely', () => {
    const credit = PAGE.slice(PAGE.indexOf('function PhotoCredit'))
    assert.match(credit, /href=\{ABOUT_PHOTOGRAPHER_URL\}/)
    assert.equal(ABOUT_PHOTOGRAPHER_URL, 'https://narellekatephotography.mypixieset.com/')
    assert.match(credit, /target="_blank"/)
    // Without ``noopener`` a new-tab link hands the destination a
    // handle on this window through ``window.opener``.
    assert.match(credit, /rel="noopener noreferrer"/)
    // Only the name is the link — "Photographs by" is not part of
    // what anyone would click.
    assert.match(credit, /\{ABOUT_PHOTO_CREDIT_PREFIX\}/)
    assert.match(credit, />\s*\{ABOUT_PHOTOGRAPHER\}\s*</)
    // An anchor with an href is keyboard reachable; the focus ring is
    // drawn only for keyboard use, in the page's existing accent.
    assert.match(credit, /focus-visible:outline-\[#246B6A\]/)
    assert.match(credit, /hover:text-\[#246B6A\]/)
  })

  test('it is one line at the foot of the page, not a caption each', () => {
    assert.match(PAGE, /<PhotoCredit \/>/)
    assert.equal((PAGE.match(/ABOUT_PHOTO_CREDIT/g) ?? []).length, 2) // import + render
    // After the closing block, so it reads as a credit rather than
    // interrupting the sign-off.
    assert.ok(PAGE.indexOf('<Closing />') < PAGE.indexOf('<PhotoCredit />'))
  })

  test('it is quiet, and not an eyebrow', () => {
    const block = PAGE.slice(PAGE.indexOf('function PhotoCredit'))
      .slice(0, PAGE.slice(PAGE.indexOf('function PhotoCredit')).indexOf('export default'))
    assert.match(block, /text-\[13px\]/)
    assert.match(block, /color: INK_SOFT/)
    assert.equal(/uppercase|tracking-wide/.test(block), false)
  })

  test('the plural is right — both photographs are the same shoot', () => {
    // The EXIF agrees on the camera body, the lens and the morning.
    // If a future photograph came from somewhere else, "Photographs
    // by" would quietly become a false claim, so the wording and the
    // count of images are asserted together.
    assert.match(ABOUT_PHOTO_CREDIT, /^Photographs by /)
    assert.equal(Object.keys(ABOUT_IMAGES).length, 2)
  })
})

describe('the supplied files, on disk', () => {
  /**
   * Width and height from a JPEG or WebP header, without a decoder.
   * Two formats because each photograph arrived in the best form it
   * exists in, not because of a house convention.
   */
  function imageSize(path: string): { w: number; h: number } {
    const b = readFileSync(path)

    if (b.toString('latin1', 0, 4) === 'RIFF') {
      const fourcc = b.toString('latin1', 12, 16)
      if (fourcc === 'VP8X') {
        return { w: b.readUIntLE(24, 3) + 1, h: b.readUIntLE(27, 3) + 1 }
      }
      if (fourcc === 'VP8 ') {
        return { w: b.readUInt16LE(26) & 0x3fff, h: b.readUInt16LE(28) & 0x3fff }
      }
      const bits = b.readUInt32LE(21)
      return { w: (bits & 0x3fff) + 1, h: ((bits >> 14) & 0x3fff) + 1 }
    }

    // JPEG: walk the segments to the start-of-frame, which is the one
    // that carries the dimensions. Everything before it is metadata of
    // some kind and is skipped by its own declared length.
    assert.equal(b.readUInt16BE(0), 0xffd8, `${path} is neither WebP nor JPEG`)
    let i = 2
    while (i < b.length) {
      if (b[i] !== 0xff) { i += 1; continue }
      const marker = b[i + 1]
      // SOF0/1/2/3, 5-7, 9-11, 13-15 — but not DHT (c4), JPG (c8), DAC (cc)
      if (marker >= 0xc0 && marker <= 0xcf
          && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
        return { h: b.readUInt16BE(i + 5), w: b.readUInt16BE(i + 7) }
      }
      i += 2 + b.readUInt16BE(i + 2)
    }
    throw new Error(`no SOF marker in ${path}`)
  }

  const onDisk = (src: string) => `public${src}`

  test('both photographs are present', () => {
    for (const image of [ABOUT_IMAGES.hero, ABOUT_IMAGES.portrait]) {
      assert.ok(existsSync(onDisk(image.src)), `missing: ${onDisk(image.src)}`)
    }
  })

  test('every frame on the page is at least as wide as its photograph', () => {
    // The whole crop argument in one assertion. ``objectFit: cover``
    // trims whichever axis has slack, so a frame NARROWER than its
    // source would cut the sides off — and on the hero the open lawn
    // on the right is exactly what the title needs, while on the
    // portrait the sides are the willow and her shoulders.
    //
    // Reading the ratios off the files rather than hard-coding them
    // means replacing a photograph with a differently-shaped one
    // fails here instead of silently cropping it.
    const hero = imageSize(onDisk(ABOUT_IMAGES.hero.src))
    const portrait = imageSize(onDisk(ABOUT_IMAGES.portrait.src))

    assert.ok(Math.abs(hero.w / hero.h - 4 / 3) < 0.01, `hero is ${hero.w}×${hero.h}`)
    assert.ok(Math.abs(portrait.w / portrait.h - 5 / 4) < 0.02, `portrait is ${portrait.w}×${portrait.h}`)

    // The hero's narrowest frame is the phone one, and it matches the
    // file exactly: on a phone the photograph is shown entire.
    assert.match(PAGE, /const HERO_FRAME = 'aspect-\[4\/3\]/)
    // Nothing wider than 16:9 — 21:9 cannot hold her head and her
    // feet at the same time from a 4:3 original.
    assert.equal(/aspect-\[21\/9\]/.test(PAGE), false)
    // The portrait frame is the file's own shape, so nothing is cut.
    assert.match(PAGE, /aspect-\[5\/4\]/)
  })

  test('the hero anchor keeps her feet in shot as the frame widens', () => {
    // She stands low in the photograph. The wider the frame, the
    // lower the visible band has to sit — a centred anchor at 16:9
    // cuts her feet and the roots off, which is the one thing the
    // crop must never do.
    const anchors = [...PAGE.matchAll(/--about-hero-pos:50%_(\d+)%/g)].map((m) => Number(m[1]))
    assert.deepEqual(anchors, [50, 62, 76])
  })

  test('the files are the ones supplied, not re-encoded copies', () => {
    // A re-encode would show up as a size change. These are the
    // supplied bytes exactly.
    const hero = readFileSync(onDisk(ABOUT_IMAGES.hero.src)).length
    const portrait = readFileSync(onDisk(ABOUT_IMAGES.portrait.src)).length
    assert.equal(hero, 4717819)
    assert.equal(portrait, 63888)
  })

  test('the hero has the resolution a high-density screen asks for', () => {
    // The widest frame is 1072 CSS px. A 2× display wants 2144 real
    // pixels and a 3× display 3216. The camera file carries 5184, so
    // ``next/image`` is downsizing at every breakpoint rather than
    // stretching — which is the whole reason the original was worth
    // chasing after the first copy came back at 2048.
    const { w } = imageSize(onDisk(ABOUT_IMAGES.hero.src))
    assert.ok(w >= 3216, `hero is only ${w}px wide`)
  })

  test('neither photograph carries location data', () => {
    // Both files are fetchable directly at their own public URL, so
    // whatever EXIF they hold is published with them. Camera make and
    // a 2019 date are harmless; GPS coordinates on a page about a
    // real person would not be. Asserted on the bytes rather than
    // trusted, because this is the kind of thing that arrives with a
    // replacement photograph years from now.
    for (const image of [ABOUT_IMAGES.hero, ABOUT_IMAGES.portrait]) {
      const b = readFileSync(onDisk(image.src))
      // The GPS IFD is referenced by tag 0x8825 inside an APP1/Exif
      // block. No Exif block at all means no GPS either.
      const app1 = b.indexOf(Buffer.from('Exif\0\0', 'latin1'))
      if (app1 === -1) continue
      assert.equal(
        b.includes(Buffer.from('GPSLatitude', 'latin1')), false,
        `${image.src} carries GPS tags`,
      )
    }
  })
})
