import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * The order of the Collective's doorways.
 *
 * ``SpaceNav`` builds one ``tabs`` array and renders it twice — as the
 * desktop tab bar and as the mobile bottom nav. That single array is
 * the whole reason the two cannot drift apart, so these tests assert
 * on the array rather than on either rendering: a change that reorders
 * one and not the other is not expressible.
 *
 * About leads. The Collective root already redirects a signed-out
 * visitor to ``/about``, so any other first tab puts the tab bar and
 * the Collective's own front door in disagreement.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/** The tab labels, in the order the array declares them. */
function tabOrder(): string[] {
  const source = read('components/spaces/SpaceNav.tsx')
  const start = source.indexOf('const tabs: Tab[] = [')
  assert.ok(start !== -1, 'SpaceNav no longer declares a tabs array')
  // Stop at the array's closing bracket — the ``.filter`` chain that
  // follows mentions labels too, and matching those would report an
  // order that is not the declared one.
  const end = source.indexOf('\n  ]', start)
  assert.ok(end > start, 'could not find the end of the tabs array')
  const body = source.slice(start, end)
  return [...body.matchAll(/label:\s*'([^']+)'/g)].map((m) => m[1])
}

describe('the Collective tab bar', () => {
  test('About is the first doorway', () => {
    assert.equal(tabOrder()[0], 'About')
  })

  test('every expected doorway is still present', () => {
    // Guards against a reorder that quietly drops one.
    assert.deepEqual(
      [...tabOrder()].sort(),
      ['About', 'Conversations', 'Gatherings', 'Members', 'Pathways'],
    )
  })

  test('the remaining order is unchanged behind About', () => {
    // Only About moved. Asserting the rest pins that this was a
    // reorder of one tab and not a reshuffle of the whole bar.
    assert.deepEqual(
      tabOrder().slice(1),
      ['Conversations', 'Pathways', 'Gatherings', 'Members'],
    )
  })

  test('there is still exactly one array feeding both navs', () => {
    const source = read('components/spaces/SpaceNav.tsx')
    assert.equal(
      (source.match(/const tabs: Tab\[\] = \[/g) ?? []).length,
      1,
      'a second tabs array would let desktop and mobile disagree',
    )
  })

  test('About keeps its area-policy mapping', () => {
    // Moving the tab must not detach it from the policy that decides
    // whether this viewer may see it at all.
    const source = read('components/spaces/SpaceNav.tsx')
    assert.match(source, /About:\s*'about'/)
  })
})
