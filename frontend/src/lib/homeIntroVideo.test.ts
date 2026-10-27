import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'

import { getEmbedProvider } from './embedAllowlist.ts'
import { CSP_REPORT_ONLY, SECURITY_HEADERS } from './securityHeaders.ts'
import {
  HOME_INTRO_VIDEO_BODY,
  HOME_INTRO_VIDEO_HEADING,
  HOME_INTRO_VIDEO_ID,
  HOME_INTRO_VIDEO_PLAY_LABEL,
  HOME_INTRO_VIDEO_POSTER_ALT,
  HOME_INTRO_VIDEO_POSTER_SIZE,
  HOME_INTRO_VIDEO_POSTER_SRC,
  HOME_INTRO_VIDEO_TITLE,
  HOME_INTRO_VIDEO_WATCH_URL,
  homeIntroVideoEmbedUrl,
} from './homeIntroVideo.ts'

/**
 * The homepage's one-minute tour.
 *
 * Two obligations, and the second is the one worth the file. The
 * first is ordinary: the approved copy, the right video, the right
 * place in the page. The second is that **nothing of YouTube's is
 * fetched before a visitor asks for it** — a property that is
 * invisible when it breaks, because an eagerly-loaded iframe looks
 * exactly like a lazy one to everybody except the third party
 * receiving the request.
 *
 * Source reads are comment-stripped before matching, so a doc
 * comment that mentions a host or an attribute cannot stand in for
 * the code actually using it.
 */

const read = (p: string) => readFileSync(p, 'utf8')

const codeOnly = (src: string) =>
  src
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const COMPONENT = codeOnly(read('src/components/home/HomeIntroVideo.tsx'))
const HOMEPAGE = codeOnly(read('src/app/page.tsx'))
const MODULE = codeOnly(read('src/lib/homeIntroVideo.ts'))


// ---------------------------------------------------------------------------
// 1. The copy, as approved
// ---------------------------------------------------------------------------

describe('the section says what it was asked to say', () => {
  test('the heading is the approved line', () => {
    assert.equal(HOME_INTRO_VIDEO_HEADING, 'Take a look inside Fresh Collective')
  })

  test('the supporting line is the approved line', () => {
    assert.equal(HOME_INTRO_VIDEO_BODY, 'One minute to see what we’ve been building.')
  })

  test('the apostrophe is typographic, like the rest of the page', () => {
    assert.ok(HOME_INTRO_VIDEO_BODY.includes('’'))
    assert.ok(!HOME_INTRO_VIDEO_BODY.includes("'"))
  })

  test('no eyebrow label is introduced above the heading', () => {
    // Fresh Collective does not use small uppercase accent labels.
    assert.ok(!/uppercase/.test(COMPONENT), 'an uppercase eyebrow crept in')
    assert.ok(!/tracking-\[0\.2/.test(COMPONENT))
  })

  test('the heading is rendered from the module, not retyped', () => {
    assert.ok(COMPONENT.includes('HOME_INTRO_VIDEO_HEADING'))
    assert.ok(COMPONENT.includes('HOME_INTRO_VIDEO_BODY'))
    assert.ok(
      !COMPONENT.includes('Take a look inside Fresh Collective'),
      'the heading is duplicated in the component and can now drift',
    )
  })
})


// ---------------------------------------------------------------------------
// 2. The right video, on the privacy-enhanced host
// ---------------------------------------------------------------------------

describe('the embed URL', () => {
  test('it is the video that was asked for', () => {
    assert.equal(HOME_INTRO_VIDEO_ID, 'MTXKOxzcl6I')
    assert.ok(homeIntroVideoEmbedUrl().includes('/embed/MTXKOxzcl6I'))
    assert.equal(HOME_INTRO_VIDEO_WATCH_URL, 'https://youtu.be/MTXKOxzcl6I')
  })

  test('it uses the privacy-enhanced host, over https', () => {
    const url = new URL(homeIntroVideoEmbedUrl())
    assert.equal(url.protocol, 'https:')
    assert.equal(url.hostname, 'www.youtube-nocookie.com')
  })

  test('the idle URL does not autoplay', () => {
    const url = new URL(homeIntroVideoEmbedUrl())
    assert.equal(url.searchParams.get('autoplay'), null)
  })

  test('autoplay is opt-in, for the click that inserts the player', () => {
    const url = new URL(homeIntroVideoEmbedUrl({ autoplay: true }))
    assert.equal(url.searchParams.get('autoplay'), '1')
  })

  test('playback stays inside the page', () => {
    const url = new URL(homeIntroVideoEmbedUrl())
    // Without playsinline iOS takes the video fullscreen by itself,
    // which throws the visitor out of the page.
    assert.equal(url.searchParams.get('playsinline'), '1')
    // Without rel=0 the end screen offers the whole of YouTube.
    assert.equal(url.searchParams.get('rel'), '0')
  })

  test('the host is on the embed allowlist, so the renderer frames it', () => {
    const provider = getEmbedProvider(homeIntroVideoEmbedUrl())
    assert.ok(provider, 'the URL is not allowlisted — EmbedRenderer would link, not embed')
    assert.equal(provider!.name, 'YouTube')
    assert.equal(provider!.shape, 'video', 'a non-video shape loses the 16:9 box')
  })
})


// ---------------------------------------------------------------------------
// 3. Nothing third-party loads before the visitor clicks
// ---------------------------------------------------------------------------

describe('the facade', () => {
  test('the player is behind state, not rendered on load', () => {
    assert.ok(COMPONENT.includes('useState'))
    assert.ok(
      /playing\s*\?/.test(COMPONENT),
      'EmbedRenderer is not gated on the activation state',
    )
  })

  test('the poster is served from our own origin', () => {
    assert.ok(
      HOME_INTRO_VIDEO_POSTER_SRC.startsWith('/'),
      'the poster is remote — a third party now sees every visitor who scrolls past',
    )
    assert.ok(!/ytimg|googleusercontent|youtube/i.test(HOME_INTRO_VIDEO_POSTER_SRC))
  })

  test('no YouTube host is reachable from the component itself', () => {
    // The only YouTube string in the tree belongs to the module, so
    // the host cannot be hardcoded past the allowlist here.
    assert.ok(!/youtube|ytimg|youtu\.be/i.test(COMPONENT))
  })

  test('no YouTube script or API is loaded', () => {
    for (const src of [COMPONENT, MODULE]) {
      assert.ok(!/iframe_api|youtube\.com\/iframe/i.test(src))
      assert.ok(!/<script/i.test(src))
    }
  })

  test('the component builds no iframe of its own', () => {
    assert.ok(
      !/<iframe/i.test(COMPONENT),
      'a second iframe implementation — reuse EmbedRenderer instead',
    )
    assert.ok(COMPONENT.includes('EmbedRenderer'))
  })
})


// ---------------------------------------------------------------------------
// 4. Accessibility and layout stability
// ---------------------------------------------------------------------------

describe('the play control', () => {
  test('it is a real button, so the keyboard reaches it', () => {
    assert.ok(/<button/.test(COMPONENT))
    assert.ok(/type="button"/.test(COMPONENT))
    assert.ok(
      !/onClick=\{[^}]*\}\s*\n?\s*>/.test(COMPONENT.replace(/<button[\s\S]*?>/g, '')),
      'a clickable non-button element is keyboard-invisible',
    )
  })

  test('it has an accessible name that says what it does', () => {
    assert.ok(COMPONENT.includes('aria-label'))
    assert.match(HOME_INTRO_VIDEO_PLAY_LABEL, /^Play the video/)
    assert.ok(HOME_INTRO_VIDEO_PLAY_LABEL.includes('Fresh Collective'))
  })

  test('focus is visible, and not merely suppressed', () => {
    // `focus:outline-none` is only safe when something replaces it.
    // Here that is a positioned ring layer, because an outline on the
    // button is painted over by the poster.
    assert.ok(/group-focus-visible:opacity-100/.test(COMPONENT))
    assert.ok(/inset 0 0 0 4px #FFFFFF/.test(COMPONENT))
  })

  test('the focus ring carries two colours', () => {
    // One colour cannot clear both the bright sky and the navy band
    // the ring crosses.
    const ring = COMPONENT.match(/boxShadow: `([^`]*inset[^`]*)`/)?.[1] ?? ''
    assert.ok(ring.includes('#FFFFFF'), 'no light half to the ring')
    assert.ok(ring.includes('TEAL_DEEP'), 'no dark half to the ring')
  })

  test('focus moves to the player once it is inserted', () => {
    // Otherwise focus falls to <body> and the player's own space and
    // arrow controls reach nothing.
    assert.ok(/querySelector\('iframe'\)\?\.focus\(\)/.test(COMPONENT))
  })

  test('the frame is a fixed 16:9 box in both states', () => {
    assert.ok(
      /aspect-video/.test(COMPONENT),
      'without a reserved box the page shifts when the poster or player arrives',
    )
  })

  test('the decorative play glyph is hidden from assistive tech', () => {
    assert.ok(/aria-hidden="true"/.test(COMPONENT))
  })

  test('the poster carries descriptive alt text', () => {
    assert.ok(HOME_INTRO_VIDEO_POSTER_ALT.length > 25)
    assert.ok(!/^image of|^picture of/i.test(HOME_INTRO_VIDEO_POSTER_ALT))
  })

  test('the frame is announced as a video', () => {
    assert.ok(/video/i.test(HOME_INTRO_VIDEO_TITLE))
    assert.ok(COMPONENT.includes('HOME_INTRO_VIDEO_TITLE'))
  })
})


// ---------------------------------------------------------------------------
// 5. Where it sits on the homepage
// ---------------------------------------------------------------------------

describe('placement', () => {
  const at = (needle: string) => {
    const i = HOMEPAGE.indexOf(needle)
    assert.ok(i >= 0, `${needle} is not on the homepage any more`)
    return i
  }

  test('it renders between the statement of what this is and the friction story', () => {
    assert.ok(at('<HomeWhatThisIs />') < at('<HomeIntroVideo />'))
    assert.ok(at('<HomeIntroVideo />') < at('<HomeFriction'))
  })

  test('the surrounding running order is untouched', () => {
    const order = [
      '<HomeHero />', '<HomeWhatThisIs />', '<HomeIntroVideo />',
      '<HomeFriction', '<ExploreSection', '<InsideCollectiveSection',
      '<CreatorSection', '<HomeOnboardingWalkthrough', '<HomeWorldBuilders',
      '<HomePricing', '<ClosingInvitation',
    ].map(at)
    assert.deepEqual(order, [...order].sort((a, b) => a - b))
  })

  test('it appears exactly once', () => {
    assert.equal(HOMEPAGE.split('<HomeIntroVideo />').length - 1, 1)
  })

  test('it is a white section, like its neighbours', () => {
    assert.ok(/background:\s*'#FFFFFF'/.test(COMPONENT))
  })
})


// ---------------------------------------------------------------------------
// 6. The poster file, on disk
// ---------------------------------------------------------------------------

describe('the poster', () => {
  const onDisk = 'public' + HOME_INTRO_VIDEO_POSTER_SRC

  test('it is present', () => {
    assert.ok(existsSync(onDisk), `${onDisk} is missing — the frame renders black`)
  })

  test('it is a JPEG, and small enough to be free', () => {
    const bytes = readFileSync(onDisk)
    assert.equal(bytes[0], 0xff)
    assert.equal(bytes[1], 0xd8)
    assert.ok(bytes.length < 400_000, `poster is ${bytes.length} bytes`)
  })

  test('its declared size is the 16:9 the frame expects', () => {
    const { width, height } = HOME_INTRO_VIDEO_POSTER_SIZE
    assert.equal(width / height, 16 / 9)
  })

  test('the declared size is the real one', () => {
    // JPEG SOF0/SOF2 marker: height then width, big-endian.
    const b = readFileSync(onDisk)
    let i = 2
    let found: { w: number; h: number } | null = null
    while (i < b.length - 9) {
      if (b[i] !== 0xff) { i += 1; continue }
      const marker = b[i + 1]!
      if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
        found = { h: b.readUInt16BE(i + 5), w: b.readUInt16BE(i + 7) }
        break
      }
      i += 2 + b.readUInt16BE(i + 2)
    }
    assert.ok(found, 'could not read the JPEG header')
    assert.equal(found!.w, HOME_INTRO_VIDEO_POSTER_SIZE.width)
    assert.equal(found!.h, HOME_INTRO_VIDEO_POSTER_SIZE.height)
  })
})


// ---------------------------------------------------------------------------
// 7. The headers the player needs
// ---------------------------------------------------------------------------

describe('the browser is allowed to run it', () => {
  const frameSrc = CSP_REPORT_ONLY
    .split(';').map((s) => s.trim())
    .find((d) => d.startsWith('frame-src '))!

  const permissions = SECURITY_HEADERS
    .find((h) => h.key === 'Permissions-Policy')!.value

  test('CSP frame-src allows the privacy-enhanced host', () => {
    assert.ok(
      frameSrc.includes('https://www.youtube-nocookie.com'),
      'the player would be blocked outright',
    )
  })

  test('Permissions-Policy grants the nocookie host what youtube.com has', () => {
    // Framing it is not enough: without these the player embeds and
    // then refuses fullscreen, picture-in-picture and playback.
    for (const feature of [
      'autoplay', 'encrypted-media', 'fullscreen', 'picture-in-picture',
    ]) {
      const directive = permissions
        .split(',').map((s) => s.trim())
        .find((d) => d.startsWith(feature + '='))
      assert.ok(directive, `${feature} is no longer declared`)
      assert.ok(
        directive!.includes('"https://www.youtube-nocookie.com"'),
        `${feature} does not reach the nocookie player`,
      )
    }
  })

  test('the grants youtube.com already had are untouched', () => {
    for (const feature of [
      'autoplay', 'encrypted-media', 'fullscreen', 'picture-in-picture',
    ]) {
      const directive = permissions
        .split(',').map((s) => s.trim())
        .find((d) => d.startsWith(feature + '='))!
      assert.ok(directive.includes('"https://www.youtube.com"'))
      assert.ok(directive.startsWith(feature + '=(self '))
    }
  })

  test('the other providers kept their own grants', () => {
    assert.ok(permissions.includes('"https://player.vimeo.com"'))
    assert.ok(permissions.includes('"https://www.loom.com"'))
    assert.ok(permissions.includes('"https://fast.wistia.net"'))
  })

  test('nothing was loosened to a wildcard', () => {
    assert.ok(!permissions.includes('*'))
    assert.ok(!/youtube[^"]*\*/.test(permissions))
  })

  test('the locked-down features stayed locked down', () => {
    for (const denied of ['camera=()', 'microphone=()', 'geolocation=()']) {
      assert.ok(permissions.includes(denied), `${denied} was lost`)
    }
  })

  test('no new origin is granted anything beyond YouTube', () => {
    const origins = new Set(
      [...permissions.matchAll(/"(https:\/\/[^"]+)"/g)].map((m) => m[1]!),
    )
    const expected = new Set([
      'https://youtube.com', 'https://www.youtube.com',
      'https://youtube-nocookie.com', 'https://www.youtube-nocookie.com',
      'https://player.vimeo.com', 'https://fast.wistia.net',
      'https://loom.com', 'https://www.loom.com',
    ])
    assert.deepEqual([...origins].sort(), [...expected].sort())
  })
})
