import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * The optional media heading, rendered the same way in all three places.
 *
 * This block vocabulary is rendered independently by the member Pathway
 * renderer, the member About renderer and the Creator Studio preview.
 * The preview's entire purpose is to show a creator what members will
 * see, so a heading that appears in two of the three is worse than one
 * that appears in none — it makes the preview lie.
 *
 * These tests therefore assert the same thing three times on purpose,
 * and the parametrised shape is what makes a forgotten renderer fail
 * rather than pass quietly.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/** Source with comments stripped: the comments in these files discuss
 *  the heading, the "Audio" label and the fields it deliberately does
 *  not reuse, so a bare substring search would match the prose. */
function code(path: string): string {
  return read(path)
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

const RENDERERS = [
  ['Pathway renderer', 'components/spaces/BlockList.tsx'],
  ['About renderer', 'components/spaces/AboutBlockRenderer.tsx'],
  ['Creator Studio preview', 'components/creator/BlockEditorShared.tsx'],
] as const

describe('every renderer offers the heading', () => {
  for (const [name, path] of RENDERERS) {
    test(`${name} imports the shared component`, () => {
      assert.match(code(path), /import MediaBlockHeading from '@\/components\/spaces\/MediaBlockHeading'/)
    })

    test(`${name} renders it three times — video, audio and file`, () => {
      // One per media block type. Fewer means a type was missed.
      const uses = code(path).match(/<MediaBlockHeading\s+heading=\{block\.heading\}/g) ?? []
      assert.equal(
        uses.length,
        3,
        `expected a heading on video_embed, audio and file_download; found ${uses.length}`,
      )
    })
  }

  test('no renderer builds the heading markup itself', () => {
    // If one inlines its own serif paragraph instead of using the
    // component, the three drift the moment the treatment changes.
    for (const [name, path] of RENDERERS) {
      const source = code(path)
      assert.ok(
        !/font-serif text-\[20px\][^\n]*\{block\.heading\}/.test(source),
        `${name} renders the heading inline instead of via the component`,
      )
    }
  })
})

describe('the shared component', () => {
  const COMPONENT = 'components/spaces/MediaBlockHeading.tsx'

  test('renders nothing when there is no heading', () => {
    // Every block authored before this field existed. This early return
    // is the whole backward-compatibility guarantee on the render side.
    assert.match(code(COMPONENT), /if \(!heading\?\.trim\(\)\) return null/)
  })

  test('uses the Exercise block’s serif title treatment', () => {
    // A title the creator wrote, so it reads as a heading.
    assert.match(code(COMPONENT), /font-serif/)
    assert.match(code(COMPONENT), /text-\[20px\]/)
  })

  test('is not styled as a small uppercase label', () => {
    // The `embed` block's eyebrow treatment is deliberately not reused:
    // this is a title, not a category tag.
    const source = code(COMPONENT)
    assert.ok(!source.includes('uppercase'), 'the heading must not be an eyebrow label')
    assert.ok(!source.includes('tracking-widest'))
  })
})

describe('the audio block’s stock label', () => {
  test('a creator heading replaces "Audio" rather than stacking with it', () => {
    const source = code('components/spaces/BlockList.tsx')
    // The conditional is the contract: heading present → component,
    // heading absent → the long-standing "Audio" label.
    assert.match(
      source,
      /block\.heading\?\.trim\(\)\s*\?\s*\(\s*<MediaBlockHeading/,
    )
    assert.match(source, /uppercase tracking-widest text-black">Audio<\/p>/)
  })

  test('the stock label still exists for blocks without a heading', () => {
    // Removing it entirely would change every existing audio block.
    assert.ok(code('components/spaces/BlockList.tsx').includes('>Audio</p>'))
  })
})

describe('the editor can write a heading', () => {
  const EDITOR = 'components/creator/BlockEditorShared.tsx'

  test('it holds heading state seeded from the block', () => {
    assert.match(code(EDITOR), /useState\(block\.heading \?\? ''\)/)
  })

  test('it offers a Heading field three times', () => {
    const fields = code(EDITOR).match(/Heading \(optional\)/g) ?? []
    assert.equal(fields.length, 3, 'expected a Heading field on video, audio and file')
  })

  test('the field is bounded to the column width', () => {
    assert.match(code(EDITOR), /maxLength=\{300\}/)
  })

  test('the save payload includes it, empty becoming null', () => {
    // '' would be stored and then have to be trimmed by every renderer.
    assert.match(code(EDITOR), /heading: heading\.trim\(\) \|\| null/)
  })

  test('autosave fires when the heading changes', () => {
    // Omitting it from the dependency list is the quiet failure here:
    // the field would appear to work and silently never persist until
    // some other field was touched.
    const deps = code(EDITOR).match(/\}, \[content, label, caption,([^\]]*)\]\)/)
    assert.ok(deps, 'the autosave dependency list has moved')
    assert.match(deps[1], /\bheading\b/)
  })
})

describe('the types carry the field', () => {
  test('both block shapes declare heading', () => {
    const types = read('types/platform.ts')
    for (const shape of ['StepBlock', 'PathwayAboutBlock', 'EditorBlock']) {
      const start = types.indexOf(`export interface ${shape} {`)
      assert.ok(start !== -1, `${shape} not found`)
      const body = types.slice(start, types.indexOf('\n}', start))
      assert.match(body, /heading: string \| null/, `${shape} is missing heading`)
    }
  })
})
