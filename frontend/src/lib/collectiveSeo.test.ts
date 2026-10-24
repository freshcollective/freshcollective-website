import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  DEFAULT_SOCIAL_IMAGE,
  SITE_ORIGIN,
  cleanText,
  collectiveDescription,
  collectiveMetadata,
  collectiveSocialImage,
  collectiveTitle,
  truncate,
} from './collectiveSeo.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const EMBODY = {
  name: 'EMBODY',
  tagline: 'Strength. Somatics. Sisterhood.',
  description: 'An in-person movement experience for women.',
  isPublic: true,
  location: {
    hero_artwork_url:
      '/api/uploads/platform-artwork/atlas-locations/sanctuary-springs/hero.webp',
  },
}

describe('a Collective title', () => {
  test('it is the name and the platform, with the platform separator', () => {
    // The middle dot is what discover-places already uses. A pipe here
    // would make two conventions where one will do.
    assert.equal(collectiveTitle('EMBODY'), 'EMBODY · Fresh Collective')
  })

  test('a nameless Collective does not produce a dangling separator', () => {
    assert.equal(collectiveTitle(''), 'Fresh Collective')
  })

  test('markup in a name never reaches the title', () => {
    assert.equal(collectiveTitle('<b>EMBODY</b>'), 'EMBODY · Fresh Collective')
  })
})

describe('the description ladder', () => {
  test('a tagline leads, and the Collective is named after it', () => {
    assert.equal(
      collectiveDescription(EMBODY),
      'Strength. Somatics. Sisterhood. Discover EMBODY on Fresh Collective.',
    )
  })

  test('a tagline with no full stop gains one', () => {
    // Otherwise two sentences run together: "Sisterhood Discover EMBODY".
    assert.match(
      collectiveDescription({ ...EMBODY, tagline: 'Strength and softness' }),
      /^Strength and softness\. Discover EMBODY/,
    )
  })

  test('a tagline ending in ? or ! keeps its own punctuation', () => {
    assert.match(
      collectiveDescription({ ...EMBODY, tagline: 'Ready to move?' }),
      /^Ready to move\? Discover/,
    )
  })

  test('no tagline falls back to the description, alone', () => {
    // Alone, not with a sentence appended — a description is usually a
    // paragraph, so the appended line would be truncated away anyway.
    assert.equal(
      collectiveDescription({ ...EMBODY, tagline: null }),
      'An in-person movement experience for women.',
    )
  })

  test('neither gives a generic line in the current voice', () => {
    const d = collectiveDescription({
      name: 'Quiet Mornings', tagline: null, description: null,
    })
    assert.equal(
      d,
      'Discover Quiet Mornings on Fresh Collective — a home for creator-led communities.',
    )
    // The retired positioning must not come back through a fallback.
    assert.ok(!/transformation platform|transformative growth/i.test(d))
  })

  test('an empty-string tagline counts as absent, not as a tagline', () => {
    assert.equal(
      collectiveDescription({ ...EMBODY, tagline: '   ' }),
      'An in-person movement experience for women.',
    )
  })

  test('HTML and runaway whitespace are stripped', () => {
    assert.equal(
      collectiveDescription({
        name: 'X', tagline: null,
        description: '<p>Two   lines\n\nof  prose.</p>',
      }),
      'Two lines of prose.',
    )
  })

  test('every rung stays within the meta-description budget', () => {
    const long = 'word '.repeat(80)
    for (const input of [
      { name: 'X', tagline: long, description: null },
      { name: 'X', tagline: null, description: long },
      { name: long, tagline: null, description: null },
    ]) {
      assert.ok(
        collectiveDescription(input).length <= 155,
        `${collectiveDescription(input).length} chars`,
      )
    }
  })
})

describe('truncation', () => {
  test('short text is untouched', () => {
    assert.equal(truncate('Short enough.'), 'Short enough.')
  })

  test('it breaks on a word boundary, not mid-word', () => {
    const out = truncate('alpha beta gamma delta epsilon', 20)
    assert.ok(!out.includes('epsi'), out)
    assert.ok(out.endsWith('…'), out)
    // No orphaned punctuation before the ellipsis.
    assert.ok(!/[,;:—-]…$/.test(out), out)
  })

  test('one very long word is cut hard, because there is no boundary', () => {
    const out = truncate('a'.repeat(40), 20)
    assert.equal(out.length, 20)
    assert.ok(out.endsWith('…'))
  })
})

describe('the social image', () => {
  test('the Location hero artwork is preferred', () => {
    assert.equal(
      collectiveSocialImage(EMBODY),
      EMBODY.location.hero_artwork_url,
    )
  })

  test('no Location falls back to the brand asset', () => {
    assert.equal(
      collectiveSocialImage({ ...EMBODY, location: null }),
      DEFAULT_SOCIAL_IMAGE,
    )
  })

  test('a Location with no artwork falls back too', () => {
    assert.equal(
      collectiveSocialImage({ ...EMBODY, location: { hero_artwork_url: null } }),
      DEFAULT_SOCIAL_IMAGE,
    )
  })

  test('a NON-public upload path is refused, not used', () => {
    // The trap this guards. Covers live under /api/uploads/covers/,
    // which needs a session — an anonymous crawler gets 401 and the
    // card renders imageless, while the creator who shared it sees it
    // working because they are signed in.
    assert.equal(
      collectiveSocialImage({
        ...EMBODY,
        location: { hero_artwork_url: '/api/uploads/covers/secret.jpg' },
      }),
      DEFAULT_SOCIAL_IMAGE,
    )
  })

  test('the fallback asset actually exists', () => {
    const path = join(SRC, '..', 'public', DEFAULT_SOCIAL_IMAGE)
    assert.ok(readFileSync(path).length > 0)
  })
})

describe('canonical and indexing', () => {
  test('the canonical points at /about, where visitors land', () => {
    // /spaces/[slug] redirects non-members to /about, so without this
    // the two URLs compete as duplicates.
    const m = collectiveMetadata(EMBODY, 'embody')
    assert.equal(m.alternates.canonical, '/spaces/embody/about')
    assert.equal(m.openGraph.url, '/spaces/embody/about')
  })

  test('a public Collective is indexable', () => {
    assert.equal(collectiveMetadata(EMBODY, 'embody').robots, undefined)
  })

  test('a NON-public Collective is noindex', () => {
    const m = collectiveMetadata({ ...EMBODY, isPublic: false }, 'embody')
    assert.deepEqual(m.robots, { index: false, follow: false })
  })

  test('an unknown visibility is treated as indexable', () => {
    // Only an explicit false suppresses indexing; the field is optional
    // and a missing value must not silently de-index a public page.
    const m = collectiveMetadata({ name: 'X' }, 'x')
    assert.equal(m.robots, undefined)
  })

  test('metadataBase is set, so relative URLs can resolve', () => {
    assert.equal(SITE_ORIGIN, 'https://freshcollective.au')
    assert.match(codeOnly('app/layout.tsx'), /metadataBase:\s*new URL\(SITE_ORIGIN\)/)
  })
})

describe('the Open Graph and Twitter payloads', () => {
  test('both carry the same title, description and image', () => {
    const m = collectiveMetadata(EMBODY, 'embody')
    assert.equal(m.openGraph.title, m.title)
    assert.equal(m.twitter.title, m.title)
    assert.equal(m.openGraph.description, m.description)
    assert.equal(m.twitter.description, m.description)
    assert.equal(m.openGraph.images[0].url, m.twitter.images[0])
  })

  test('the card is a large summary', () => {
    assert.equal(
      collectiveMetadata(EMBODY, 'embody').twitter.card,
      'summary_large_image',
    )
  })
})

describe('the page wiring', () => {
  const ABOUT = 'app/spaces/[slug]/about/page.tsx'

  /** Just the generateMetadata function, not the whole page. */
  const metadataBlock = (src: string) =>
    src.slice(
      src.indexOf('export async function generateMetadata'),
      src.indexOf('export default'),
    )

  test('generateMetadata lives on the About page', () => {
    // Not the layout: the layout wraps member-only areas whose
    // metadata differs, and /about is where a crawler lands.
    assert.match(codeOnly(ABOUT), /export async function generateMetadata/)
  })

  test('it goes through the shared builder, not its own copy', () => {
    assert.match(codeOnly(ABOUT), /collectiveMetadata\(/)
  })

  test('a Collective it cannot read is unnamed and noindex', () => {
    // getSpace returns null for private (401) and draft (404)
    // Collectives when the caller is anonymous — which every crawler
    // is. The fallback must not name anything.
    const block = metadataBlock(codeOnly(ABOUT))
    assert.match(block, /if \(!space\)/)
    assert.match(block, /index: false/)
    assert.ok(
      !/space\.name/.test(block.slice(0, block.indexOf('collectiveMetadata'))),
      'the not-found branch must not read the Collective name',
    )
  })

  test('the metadata path never uses cover_image_url', () => {
    // Scoped to the metadata, not the page. The About page renders the
    // cover for a human visitor at line ~110, which is fine — a signed
    // -in reader can fetch it. What must not happen is a crawler being
    // handed that URL in an OG tag, where it 401s.
    const src =
      metadataBlock(codeOnly(ABOUT)) + codeOnly('lib/collectiveSeo.ts')
    assert.ok(
      !/cover_image_url/.test(src),
      'covers are session-gated and would 401 for a crawler',
    )
  })
})

describe('existing metadata is untouched', () => {
  test('the homepage keeps its own title, description and openGraph', () => {
    const src = codeOnly('app/page.tsx')
    assert.match(src, /title: 'Fresh Collective — a home for creator-led communities'/)
    assert.match(src, /openGraph: \{/)
  })

  test('For Creators keeps its openGraph', () => {
    assert.match(codeOnly('app/for-creators/page.tsx'), /openGraph/)
  })

  test('the root description is still the current positioning', () => {
    assert.match(
      codeOnly('app/layout.tsx'),
      /A home for creator-led communities where people learn/,
    )
  })
})

describe('cleanText', () => {
  test('it handles null and undefined', () => {
    assert.equal(cleanText(null), '')
    assert.equal(cleanText(undefined), '')
  })

  test('it decodes the entities a creator is most likely to paste', () => {
    assert.equal(cleanText('a&nbsp;b &amp; c'), 'a b & c')
  })
})
