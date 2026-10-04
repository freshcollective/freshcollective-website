import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const COMPONENT = 'components/ui/MemberImage.tsx'

/** Every .ts/.tsx file under src, for the no-second-implementation sweep. */
function allSources(dir = SRC): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...allSources(full))
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full)
  }
  return out
}

describe('the ladder continues in the browser', () => {
  const src = codeOnly(COMPONENT)

  test('a failed image steps down rather than giving up', () => {
    // A boolean `failed` sent a broken photo straight to a bare glyph,
    // skipping the member's own card — worse treatment than a member
    // with no photo at all, who gets a designed card.
    assert.match(src, /const \[stepsDown, setStepsDown\] = useState\(0\)/)
    assert.match(src, /setStepsDown\(\(n\) => n \+ 1\)/)
  })

  test('the rungs are the payload order, photo first', () => {
    assert.match(src, /\[image\.url, image\.fallback_url\]/)
  })

  test('it stops at the plain initial, which is always present', () => {
    assert.match(src, /image\.initial \?\? '·'/)
  })

  test('the element is keyed on its source', () => {
    // Without a key React reuses the <img> and the browser can keep
    // serving the failed resource, so the fallback is never requested.
    assert.match(src, /key=\{url\}/)
  })

  test('the crop steps down with the image', () => {
    // A photo is cropped; a card is drawn for the frame and must not
    // be. Once the photo has failed, what is showing is a card.
    assert.match(src, /image\.kind === 'photo' && stepsDown === 0/)
  })

  test('it re-derives nothing: the server still picks the tier', () => {
    for (const smell of ['avatar_url', 'alphabet_letter', 'toUpperCase', 'charAt']) {
      assert.ok(!src.includes(smell), `the client must not derive ${smell}`)
    }
  })
})

describe('one image implementation, every surface', () => {
  test('nothing else renders a member avatar', () => {
    const offenders: string[] = []
    for (const file of allSources()) {
      const rel = file.slice(SRC.length + 1)
      if (rel === COMPONENT) continue
      const code = codeOnly(rel)
      // An <img> fed from a member image payload anywhere else would be
      // a second ladder, which is the thing the resolver exists to stop.
      if (/<img[^>]*src=\{[^}]*\bimage\./.test(code)) offenders.push(rel)
    }
    assert.deepEqual(offenders, [])
  })

  test('Ways to Connect and Messages render the same component', () => {
    for (const path of [
      'components/connections/PersonCard.tsx',
      'components/messages/PeerThreadList.tsx',
      'app/messages/[threadId]/PeerConversationClient.tsx',
    ]) {
      assert.match(
        codeOnly(path),
        /MemberImage/,
        `${path} should render the shared component`,
      )
    }
  })

  test('both consume the payload without reshaping it', () => {
    // `image={...}` straight through. Rebuilding the object is how one
    // surface would start disagreeing with another.
    assert.match(
      codeOnly('components/connections/PersonCard.tsx'),
      /<MemberImage image=\{person\.image\}/,
    )
    assert.match(
      codeOnly('components/messages/PeerThreadList.tsx'),
      /<MemberImage image=\{thread\.other\.image\}/,
    )
  })

  test('the wire type carries the fallback rung', () => {
    assert.match(codeOnly('types/platform.ts'), /fallback_url\?: string \| null/)
  })
})
