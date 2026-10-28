import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync, statSync } from 'node:fs'

import { CREATOR_FAQ, creatorFaqJsonLd } from './creatorFaq.ts'
import { PUBLIC_PLANS } from './plans.ts'
import {
  SHOWCASE_DEFAULT_ID,
  SHOWCASE_HEADING,
  SHOWCASE_INTRO,
  SHOWCASE_SHOTS,
  showcaseShot,
} from './collectiveShowcase.ts'

/**
 * The Moonlit Circle showcase.
 *
 * Two obligations beyond the ordinary ones. The first is privacy:
 * Moonlit Circle is a private Collective, and this gallery is four
 * approved pictures of it — not a door into it. Nothing here may
 * become a link to ``/spaces/moonlit-circle`` or a call to its API,
 * and a test should fail the day one does.
 *
 * The second is that the rest of /for-creators is untouched. The
 * section was inserted into a page carrying prices, a fee table and
 * FAQPage structured data, and the easiest way to damage it is
 * sideways.
 *
 * Source reads are comment-stripped, so a doc comment mentioning a
 * slug cannot stand in for code using one.
 */

const read = (p: string) => readFileSync(p, 'utf8')

const codeOnly = (src: string) =>
  src
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const COMPONENT = codeOnly(read('src/components/marketing/CollectiveShowcase.tsx'))
const MODULE = codeOnly(read('src/lib/collectiveShowcase.ts'))
const PAGE = codeOnly(read('src/app/for-creators/page.tsx'))


// ---------------------------------------------------------------------------
// 1. The copy, as approved
// ---------------------------------------------------------------------------

describe('the section says what it was asked to say', () => {
  test('the heading', () => {
    assert.equal(SHOWCASE_HEADING, 'See what you can create.')
  })

  test('the introduction', () => {
    assert.equal(
      SHOWCASE_INTRO,
      'Every Collective has its own personality. Here’s a little look '
        + 'inside Moonlit Circle, a demonstration Collective created on '
        + 'Fresh Collective.',
    )
  })

  test('the four labels and descriptions', () => {
    assert.deepEqual(
      SHOWCASE_SHOTS.map((s) => [s.label, s.description]),
      [
        ['Your Collective', 'A beautiful home for your community.'],
        ['Pathways', 'Create guided experiences with videos, exercises and reflections.'],
        ['Gatherings', 'Bring people together with sessions, events and bookable experiences.'],
        ['Offerings', 'Share free and paid digital resources.'],
      ],
    )
  })

  test('the copy is rendered from the module, not retyped', () => {
    assert.ok(COMPONENT.includes('SHOWCASE_HEADING'))
    assert.ok(COMPONENT.includes('SHOWCASE_INTRO'))
    assert.ok(!COMPONENT.includes('See what you can create'))
  })

  test('no eyebrow label is introduced', () => {
    assert.ok(!/uppercase/.test(COMPONENT))
  })
})


// ---------------------------------------------------------------------------
// 2. Privacy — pictures of a private Collective, not a way in
// ---------------------------------------------------------------------------

describe('Moonlit Circle stays private', () => {
  test('every image is a static local file', () => {
    for (const shot of SHOWCASE_SHOTS) {
      assert.ok(
        shot.src.startsWith('/for-creators/'),
        `${shot.id} is not served from our own static assets`,
      )
      assert.ok(!/^https?:/.test(shot.src))
    }
  })

  test('nothing links into the Collective', () => {
    for (const src of [MODULE, COMPONENT]) {
      assert.ok(!/\/spaces\/moonlit/i.test(src))
      assert.ok(!/href=["'`]\/spaces/.test(src))
    }
  })

  test('nothing calls an API', () => {
    for (const src of [MODULE, COMPONENT]) {
      assert.ok(!/\/api\//.test(src))
      assert.ok(!/\bfetch\s*\(/.test(src))
      assert.ok(!/serverApi|resolveMediaUrl/.test(src))
    }
  })

  test('the introduction is what frames the Collective now', () => {
    // The footnote under the previews was removed as redundant. The
    // intro already names Moonlit Circle a demonstration Collective,
    // and it is the only place that framing survives — so it is the
    // line to protect. The privacy guarantees above are structural
    // and unaffected either way: the gallery is four static files
    // with no link and no call into the Collective.
    assert.match(SHOWCASE_INTRO, /demonstration Collective/)
  })

  test('the footnote is gone, not merely unrendered', () => {
    for (const src of [MODULE, COMPONENT]) {
      assert.ok(!/FOOTNOTE/.test(src))
      assert.ok(!/not a way in/i.test(src))
    }
  })
})


// ---------------------------------------------------------------------------
// 3. The assets on disk
// ---------------------------------------------------------------------------

describe('the screenshots', () => {
  /** Width and height from a WebP header (VP8L / VP8X / lossy VP8). */
  function webpSize(path: string): { w: number; h: number } {
    const b = readFileSync(path)
    assert.equal(b.toString('ascii', 0, 4), 'RIFF')
    assert.equal(b.toString('ascii', 8, 12), 'WEBP')
    const fourcc = b.toString('ascii', 12, 16)
    if (fourcc === 'VP8X') return { w: b.readUIntLE(24, 3) + 1, h: b.readUIntLE(27, 3) + 1 }
    if (fourcc === 'VP8L') {
      const bits = b.readUInt32LE(21)
      return { w: (bits & 0x3fff) + 1, h: ((bits >> 14) & 0x3fff) + 1 }
    }
    // Lossy VP8: dimensions follow the 3-byte start code at offset 23.
    return { w: b.readUInt16LE(26) & 0x3fff, h: b.readUInt16LE(28) & 0x3fff }
  }

  for (const shot of SHOWCASE_SHOTS) {
    const file = 'public' + shot.src

    test(`${shot.id} is present`, () => {
      assert.ok(existsSync(file), `${file} is missing — the gallery renders blank`)
    })

    test(`${shot.id} declares its real dimensions`, () => {
      const { w, h } = webpSize(file)
      assert.equal(w, shot.width)
      assert.equal(h, shot.height)
    })

    test(`${shot.id} is small enough to serve`, () => {
      // Optimised from PNG; the point is that text stays readable, so
      // this is a sanity ceiling rather than an aggressive target.
      assert.ok(statSync(file).size < 300_000, `${file} is ${statSync(file).size} bytes`)
    })
  }

  test('the four shapes really are different, which is why the frame scrolls', () => {
    const ratios = SHOWCASE_SHOTS.map((s) => +(s.width / s.height).toFixed(2))
    assert.deepEqual(ratios, [1.2, 0.68, 0.98, 1.47])
    assert.equal(new Set(ratios).size, 4)
  })

  test('every shot has descriptive alt text', () => {
    for (const shot of SHOWCASE_SHOTS) {
      assert.ok(shot.alt.length > 40, `${shot.id} alt text is too thin`)
      assert.ok(!/^image of|^screenshot of a screenshot/i.test(shot.alt))
    }
  })
})


// ---------------------------------------------------------------------------
// 4. The gallery's behaviour
// ---------------------------------------------------------------------------

describe('the gallery', () => {
  test('Your Collective is the default', () => {
    assert.equal(SHOWCASE_DEFAULT_ID, 'collective-home')
    assert.equal(SHOWCASE_SHOTS[0]!.id, SHOWCASE_DEFAULT_ID)
    assert.equal(showcaseShot(SHOWCASE_DEFAULT_ID).label, 'Your Collective')
    assert.ok(COMPONENT.includes('useState(SHOWCASE_DEFAULT_ID)'))
  })

  test('selection happens in the page, with no navigation', () => {
    assert.ok(/onClick=\{\(\) => select\(shot\.id\)\}/.test(COMPONENT))
    assert.ok(
      !/<Link|router\.|window\.location/.test(COMPONENT),
      'choosing a preview must not navigate',
    )
  })

  test('nothing rotates on its own', () => {
    assert.ok(!/setInterval|setTimeout|autoplay/i.test(COMPONENT))
  })

  test('proportions are preserved — nothing is cropped or stretched', () => {
    // The featured image is full width with its height free; only the
    // small previews use object-cover.
    assert.ok(/className="block h-auto w-full"/.test(COMPONENT))
    assert.ok(!/object-contain/.test(COMPONENT))
  })

  test('the window is a fixed height, so the page below cannot jump', () => {
    assert.ok(/const WINDOW_HEIGHT = 'h-\[\d+px\]/.test(COMPONENT))
    assert.ok(/overflow-y-auto/.test(COMPONENT))
  })

  test('a taller screenshot says so, and stops saying so at the end', () => {
    assert.ok(/canScroll && !atEnd/.test(COMPONENT))
    assert.ok(COMPONENT.includes('Scroll to see more'))
  })

  test('switching returns to the top of the new screenshot', () => {
    assert.ok(/scrollTo\(\{ top: 0 \}\)/.test(COMPONENT))
  })

  test('only the default screenshot is given priority', () => {
    assert.ok(/priority=\{selected\.id === SHOWCASE_DEFAULT_ID\}/.test(COMPONENT))
  })

  test('it uses next/image rather than a gallery library', () => {
    assert.ok(COMPONENT.includes("from 'next/image'"))
    assert.ok(!/swiper|slick|lightbox|photoswipe|fancybox/i.test(COMPONENT))
  })
})


// ---------------------------------------------------------------------------
// 5. Keyboard and assistive technology
// ---------------------------------------------------------------------------

describe('it works without a mouse', () => {
  test('the previews are real buttons', () => {
    assert.ok(/<button/.test(COMPONENT))
    assert.ok(/type="button"/.test(COMPONENT))
  })

  test('the selected preview is announced, not just coloured', () => {
    assert.ok(/aria-pressed=\{isSelected\}/.test(COMPONENT))
  })

  test('the group of previews has a name', () => {
    assert.ok(/role="group"[\s\S]{0,80}aria-label="Choose a screenshot to view"/.test(COMPONENT))
  })

  test('the scrolling window takes focus, so the keyboard can scroll it', () => {
    assert.ok(/tabIndex=\{0\}/.test(COMPONENT))
    assert.ok(/aria-label=\{`\$\{selected\.label\}/.test(COMPONENT))
  })

  test('the description change is spoken', () => {
    assert.ok(/aria-live="polite"/.test(COMPONENT))
  })

  test('focus is visible on every control', () => {
    const rings = COMPONENT.match(/focus-visible:outline-2/g) ?? []
    assert.ok(rings.length >= 3, `only ${rings.length} focus rings`)
  })

  test('the decorative hint is hidden from assistive tech', () => {
    assert.ok(/aria-hidden="true"/.test(COMPONENT))
  })

  test('nothing needs hover to work', () => {
    assert.ok(!/onMouseEnter|onMouseOver|group-hover:(?!opacity)/.test(COMPONENT))
  })
})


// ---------------------------------------------------------------------------
// 6. The rest of /for-creators is untouched
// ---------------------------------------------------------------------------

describe('the page it was added to', () => {
  const at = (needle: string) => {
    const i = PAGE.indexOf(needle)
    assert.ok(i >= 0, `${needle} is gone from /for-creators`)
    return i
  }

  test('the showcase sits after the hero and before How to start', () => {
    assert.ok(at('<Hero artUrl=') < at('<CollectiveShowcase />'))
    assert.ok(at('<CollectiveShowcase />') < at('<Journey />'))
  })

  test('the running order is otherwise unchanged', () => {
    const order = [
      '<Hero artUrl=', '<CollectiveShowcase />', '<Journey />',
      '<PlansSection', '<WorldBuildersSection', '<ClosingInvitation',
      '<FaqSection />', '<AboutStoryLink />',
    ].map(at)
    assert.deepEqual(order, [...order].sort((a, b) => a - b))
  })

  test('it appears exactly once', () => {
    assert.equal(PAGE.split('<CollectiveShowcase />').length - 1, 1)
  })

  test('the hero CTA still points at the plans', () => {
    assert.ok(PAGE.includes('href="#plans"'))
    assert.ok(PAGE.includes('Choose your plan'))
    assert.ok(PAGE.includes('id="plans"'))
  })

  test('the plans and their prices survive', () => {
    // Three come from the shared plans module; Ecosystem is declared
    // on the page itself, so it is checked there.
    assert.deepEqual(
      Object.values(PUBLIC_PLANS).map((p) => [p.displayName, p.priceLabel]),
      [
        ['Community Collective', 'Free'],
        ['Creator', '$19 / month'],
        ['Creator Portfolio', '$79 / month'],
      ],
    )
    assert.ok(PAGE.includes('Ecosystem'))
  })

  test('the platform fees survive', () => {
    assert.deepEqual(
      Object.values(PUBLIC_PLANS).map((p) => p.commissionLabel),
      [null, '8%', '4%'],
    )
  })

  test('the FAQ is still seven questions, with seven in the structured data', () => {
    assert.equal(CREATOR_FAQ.length, 7)
    assert.equal((creatorFaqJsonLd() as { mainEntity: unknown[] }).mainEntity.length, 7)
  })

  test('the fee table, show-around invitation and About link are all still there', () => {
    assert.ok(PAGE.includes('<FeeTable />'))
    assert.ok(PAGE.includes('<ShowAroundInvitation'))
    assert.ok(PAGE.includes('<AboutStoryLink />'))
  })

  test('the SEO metadata is unchanged', () => {
    assert.ok(PAGE.includes("title: 'For Creators — Fresh Collective'"))
  })

  test('the section is white, like its neighbours', () => {
    assert.ok(/background: '#FFFFFF'/.test(COMPONENT))
  })

  test('no new colours were introduced', () => {
    const hex = new Set(COMPONENT.match(/#[0-9A-Fa-f]{6}/g) ?? [])
    assert.deepEqual([...hex].sort(), ['#0C1826', '#246B6A', '#FFFFFF'])
  })
})
