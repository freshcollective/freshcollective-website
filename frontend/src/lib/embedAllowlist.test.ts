import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  EMBED_PROVIDERS,
  checkEmbed,
  extractEmbedSrc,
  getEmbedProvider,
  isEmbedHostAllowed,
  resolveEmbedBox,
  supportedEmbedsList,
} from './embedAllowlist.ts'

/**
 * Embed allowlist — the creator-facing mirror of
 * `backend/app/services/embed_validator.py`.
 *
 * The backend is authoritative; this module exists for inline feedback
 * before save, and for picking display dimensions. Both halves must
 * agree, or a creator is told something the server will contradict.
 *
 * New with the Neutrino Human Design provider, and covering the
 * existing providers too — neither side of this allowlist had tests
 * before, which is a poor position from which to extend one.
 *
 * Neutrino publishes a `<script>` loader, a `<neutrino-widget>` element
 * and a `<style>` block alongside its iframe. None of that is used or
 * stored: the iframe src is extracted, validated, and rendered inside
 * FC's own sandboxed iframe.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
/** The backend validator this module mirrors. Two levels up from
 *  `frontend/src` is the repo root. */
const readBackend = () =>
  read('../../backend/app/services/embed_validator.py')

const NEUTRINO_URL =
  'https://neutrinoplatform.com/widget-v2/iframe' +
  '?type=chart&key=7f3a9c21-4b6e-4d2f-9a81-c5e0b7d41f93&hideBrand=true'

/** The snippet as Neutrino's dashboard hands it over, loader and all. */
const NEUTRINO_SNIPPET = `
<style>
  .neutrino-embed { width: 100%; height: 1500px; }
  @media (min-width: 900px) { .neutrino-embed { height: 850px; } }
</style>
<script src="https://neutrinoplatform.com/widget-v2/loader.js" async></script>
<neutrino-widget type="chart" key="7f3a9c21"></neutrino-widget>
<iframe class="neutrino-embed" src="${NEUTRINO_URL}"
        width="100%" height="850" frameborder="0"></iframe>
`

const neutrino = () => {
  const p = EMBED_PROVIDERS.find((x) => x.name === 'Neutrino Human Design')
  assert.ok(p, 'Neutrino Human Design is not in EMBED_PROVIDERS')
  return p!
}

describe('Neutrino Human Design is recognised', () => {
  test('checkEmbed accepts the direct widget URL', () => {
    const result = checkEmbed(NEUTRINO_URL)
    assert.equal(result.ok, true)
    if (!result.ok) return
    assert.equal(result.url, NEUTRINO_URL)
    assert.equal(result.provider.name, 'Neutrino Human Design')
  })

  test('checkEmbed accepts the full snippet and keeps only the src', () => {
    const result = checkEmbed(NEUTRINO_SNIPPET)
    assert.equal(result.ok, true)
    if (!result.ok) return
    assert.equal(result.url, NEUTRINO_URL)
    for (const fragment of ['<script', '<style', '<neutrino-widget', '<iframe']) {
      assert.ok(!result.url.includes(fragment), `${fragment} survived`)
    }
  })

  test('the query string survives extraction', () => {
    const src = extractEmbedSrc(NEUTRINO_SNIPPET)
    assert.ok(src?.includes('type=chart'))
    assert.ok(src?.includes('key=7f3a9c21-4b6e-4d2f-9a81-c5e0b7d41f93'))
    assert.ok(src?.includes('hideBrand=true'))
  })

  test('http:// is refused', () => {
    const result = checkEmbed(NEUTRINO_URL.replace('https://', 'http://'))
    assert.equal(result.ok, false)
    if (result.ok) return
    assert.match(result.reason, /https/i)
  })

  for (const host of [
    'neutrinoplatform.com.evil.example',
    'notneutrinoplatform.com',
    'neutrinoplatform.co',
    'evil-neutrinoplatform.com',
  ]) {
    test(`the deceptive host ${host} is refused`, () => {
      const result = checkEmbed(`https://${host}/widget-v2/iframe?type=chart`)
      assert.equal(result.ok, false)
      assert.ok(!isEmbedHostAllowed(host))
    })
  }

  test('a subdomain resolves to the provider', () => {
    const p = getEmbedProvider('https://www.neutrinoplatform.com/widget-v2/iframe')
    assert.equal(p?.name, 'Neutrino Human Design')
  })

  test('the helper text offers it to creators', () => {
    assert.match(supportedEmbedsList(), /Neutrino Human Design/)
  })

  test('path restriction is the backend\'s job, and stays there', () => {
    // Stated so the asymmetry is deliberate rather than an oversight:
    // this module gates the host, the backend additionally pins the
    // path, and the backend is what rejects on save. Mirroring the
    // path rule here would be a second place to keep in step for no
    // security gain.
    const backend = readBackend()
    assert.match(backend, /EMBED_ALLOWED_PATHS/)
    assert.match(backend, /widget-v2\/iframe/)
  })
})

describe('the responsive height Neutrino needs', () => {
  test('it declares both of the heights from its style block', () => {
    const p = neutrino()
    assert.deepEqual(p.responsiveHeight, {
      breakpoint: 900,
      narrow: 1500,
      wide: 850,
    })
  })

  test('the narrow height renders inline and the wide one as a variable', () => {
    const box = resolveEmbedBox(neutrino())
    assert.equal(box.className, 'fc-embed-h-900')
    assert.equal(box.style.minHeight, 1500)
    assert.equal(box.style.height, 1500)
    assert.equal(box.style['--fc-embed-h-wide'], '850px')
  })

  test('the stylesheet implements the breakpoint the metadata names', () => {
    // A media query cannot read a custom property, so the breakpoint
    // has to exist as a real rule. If the two ever disagree the embed
    // silently keeps the phone height on desktop.
    const css = read('app/globals.css')
    assert.match(css, /@media \(min-width: 900px\)[\s\S]*?\.fc-embed-h-900/)
    assert.match(css, /--fc-embed-h-wide/)
  })

  test('the renderer applies the class and the style it is given', () => {
    const tsx = read('components/EmbedRenderer.tsx')
    assert.match(tsx, /resolveEmbedBox\(p\)/)
    assert.match(tsx, /box\.className/)
    assert.match(tsx, /box\.style/)
  })

  test('a fallback minHeight is kept for the pre-breakpoint case', () => {
    // Belt and braces: if the stylesheet were ever dropped, the iframe
    // still has a usable height rather than collapsing to zero.
    assert.equal(neutrino().minHeight, 1500)
  })
})

describe('existing providers render exactly as they did', () => {
  test('every single-height provider keeps minHeight/height and no class', () => {
    for (const p of EMBED_PROVIDERS) {
      if (p.responsiveHeight) continue
      const box = resolveEmbedBox(p)
      assert.equal(box.className, '', `${p.name} gained a class`)
      assert.equal(
        Object.keys(box.style).sort().join(','),
        'height,minHeight',
        `${p.name} gained extra style keys`,
      )
    }
  })

  test('the documented per-shape heights are unchanged', () => {
    const heightFor = (name: string) => {
      const p = EMBED_PROVIDERS.find((x) => x.name === name)!
      return resolveEmbedBox(p).style.height
    }
    assert.equal(heightFor('Google Forms'), 600)
    assert.equal(heightFor('Typeform'), 600)
    assert.equal(heightFor('Calendly'), 700)
    assert.equal(heightFor('Spotify'), 232)
    assert.equal(heightFor('SoundCloud'), 166)
  })

  test('the shape defaults still apply when minHeight is absent', () => {
    assert.equal(
      resolveEmbedBox({ name: 'X', hosts: ['x.test'], shape: 'short' }).style.height,
      200,
    )
    assert.equal(
      resolveEmbedBox({ name: 'X', hosts: ['x.test'], shape: 'tall' }).style.height,
      600,
    )
  })

  test('Neutrino is the only provider with two heights', () => {
    const responsive = EMBED_PROVIDERS.filter((p) => p.responsiveHeight)
    assert.deepEqual(responsive.map((p) => p.name), ['Neutrino Human Design'])
  })

  for (const url of [
    'https://www.youtube.com/embed/dQw4w9WgXcQ',
    'https://player.vimeo.com/video/123456',
    'https://fast.wistia.net/embed/iframe/abc',
    'https://www.loom.com/embed/abc',
    'https://docs.google.com/forms/d/e/abc/viewform?embedded=true',
    'https://form.typeform.com/to/abc',
    'https://calendly.com/someone/30min',
    'https://open.spotify.com/embed/episode/abc',
  ]) {
    test(`${new URL(url).hostname} is still accepted`, () => {
      assert.equal(checkEmbed(url).ok, true)
    })
  }

  test('an unknown host is still refused, and says what is supported', () => {
    const result = checkEmbed('https://evil.example/embed')
    assert.equal(result.ok, false)
    if (result.ok) return
    assert.match(result.reason, /not allowed/)
    assert.match(result.reason, /Neutrino Human Design/)
  })
})

describe('the two allowlists agree', () => {
  test('every frontend host appears in the backend tuple', () => {
    const backend = readBackend()
    const block = backend.slice(
      backend.indexOf('EMBED_ALLOWED_HOSTS'),
      backend.indexOf('EMBED_PROVIDER_NAMES'),
    )
    for (const p of EMBED_PROVIDERS) {
      for (const host of p.hosts) {
        assert.ok(
          block.includes(`"${host}"`),
          `${p.name} host ${host} is allowed in the browser but not on the server`,
        )
      }
    }
  })

  test('every frontend provider name appears in the backend refusal list', () => {
    const backend = readBackend()
    const block = backend.slice(
      backend.indexOf('EMBED_PROVIDER_NAMES'),
      backend.indexOf('EMBED_ALLOWED_PATHS'),
    )
    for (const p of EMBED_PROVIDERS) {
      assert.ok(
        block.includes(`"${p.name}"`),
        `${p.name} is offered in the browser but missing from the server's message`,
      )
    }
  })
})

describe('the sandbox is unchanged', () => {
  test('no allow-top-navigation, and no new sandbox permissions', () => {
    const tsx = read('components/EmbedRenderer.tsx')
    const m = tsx.match(/const sandbox =\s*\n?\s*'([^']+)'/)
    assert.ok(m, 'could not find the sandbox attribute')
    const tokens = m![1].split(' ')

    // Checked against the attribute's own tokens, not the file text.
    // The comment above it explains that allow-top-navigation is
    // deliberately absent, so a search of the source finds the phrase
    // in the documentation and fails on the explanation.
    assert.ok(
      !tokens.includes('allow-top-navigation'),
      'a hostile embed could redirect the parent page',
    )
    assert.deepEqual(
      tokens.sort(),
      [
        'allow-forms',
        'allow-popups',
        'allow-popups-to-escape-sandbox',
        'allow-presentation',
        'allow-same-origin',
        'allow-scripts',
      ],
    )
  })

  test('the renderer never injects creator markup', () => {
    const tsx = read('components/EmbedRenderer.tsx')
    assert.ok(!tsx.includes('dangerouslySetInnerHTML'))
  })
})
