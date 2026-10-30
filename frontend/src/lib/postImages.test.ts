import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { postImages } from './postImages.ts'

/**
 * How many photographs a Conversation post has, and how they are laid
 * out.
 *
 * A post used to carry one image in `image_url`. It now carries a list
 * in `image_urls` and keeps the first of them in the old field, so the
 * half worth testing is the fallback: a post written before the change
 * — or a response from an fc-api mid-deploy — must read as a one-image
 * post, not as a post with none.
 */

/**
 * Comments out, code left behind.
 *
 * Deliberately *not* the `{/* … *\/}` pattern used elsewhere in this
 * repo: it matches an opening brace followed by a doc comment —
 * `interface Foo {` on one line and `/** … *\/` on the next — and then
 * runs non-greedily to the first `*\/}` anywhere below, swallowing
 * everything between. Stripping block comments first makes a JSX
 * comment collapse to a harmless `{}` and leaves the code intact.
 */
const codeOnly = (src: string) =>
  src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const GALLERY = codeOnly(readFileSync('src/components/community/PostImages.tsx', 'utf8'))
const FORM = codeOnly(readFileSync('src/components/community/CreatePostForm.tsx', 'utf8'))
const CARD = codeOnly(readFileSync('src/components/community/PostCard.tsx', 'utf8'))


describe('how many images a post has', () => {
  test('a text-only post has none', () => {
    assert.deepEqual(postImages({ image_url: null }), [])
    assert.deepEqual(postImages({ image_url: null, image_urls: [] }), [])
  })

  test('an older post reads as one image', () => {
    // The compatibility case: no `image_urls` at all.
    assert.deepEqual(postImages({ image_url: '/a.jpg' }), ['/a.jpg'])
  })

  test('an empty list falls back rather than hiding the image', () => {
    assert.deepEqual(postImages({ image_url: '/a.jpg', image_urls: [] }), ['/a.jpg'])
  })

  test('the list wins when both are present', () => {
    assert.deepEqual(
      postImages({ image_url: '/a.jpg', image_urls: ['/one.jpg', '/two.jpg'] }),
      ['/one.jpg', '/two.jpg'],
    )
  })

  test('order is preserved', () => {
    const urls = ['/c.jpg', '/a.jpg', '/b.jpg', '/e.jpg', '/d.jpg']
    assert.deepEqual(postImages({ image_url: null, image_urls: urls }), urls)
  })

  test('blank entries are dropped', () => {
    assert.deepEqual(
      postImages({ image_url: null, image_urls: ['', '/a.jpg'] }),
      ['/a.jpg'],
    )
  })
})


describe('the gallery', () => {
  test('one image keeps the presentation it always had', () => {
    assert.match(GALLERY, /images\.length === 1/)
    assert.match(GALLERY, /w-full rounded-xl object-cover/)
  })

  test('more than one becomes a two-column grid', () => {
    assert.match(GALLERY, /grid list-none grid-cols-2 gap-2/)
  })

  test('three images lead with a wide one', () => {
    assert.match(GALLERY, /if \(count === 3\) return index === 0/)
    assert.match(GALLERY, /col-span-2/)
  })

  test('nothing is stretched — every cell crops instead', () => {
    // A fixed ratio plus object-cover is what lets a portrait and a
    // landscape sit together without distorting either.
    assert.match(GALLERY, /aspect-\[16\/9\]/)
    assert.match(GALLERY, /aspect-square/)
    assert.ok(!/object-fill/.test(GALLERY))
  })

  test('nothing renders when there are no images', () => {
    assert.match(GALLERY, /if \(images\.length === 0\) return null/)
  })

  test('each image opens full size, safely', () => {
    assert.match(GALLERY, /target="_blank"/)
    assert.match(GALLERY, /rel="noopener noreferrer"/)
    assert.match(GALLERY, /focus-visible:outline/)
  })

  test('it reuses the shared image component', () => {
    // A bare <img> shows a broken-image icon when a file cannot be
    // read; CommunityImage renders nothing instead.
    assert.match(GALLERY, /import CommunityImage/)
    assert.ok(!/<img /.test(GALLERY), 'a bare <img> crept in')
  })

  test('every photo is numbered for assistive tech', () => {
    assert.match(GALLERY, /aria-label=\{`Photo \$\{i \+ 1\} of \$\{images\.length\}`\}/)
  })
})


describe('the composer', () => {
  test('five is the limit, named once', () => {
    assert.match(FORM, /const MAX_POST_IMAGES = 5/)
    assert.equal((FORM.match(/MAX_POST_IMAGES = /g) ?? []).length, 1)
  })

  test('several files can be chosen at once', () => {
    assert.match(FORM, /multiple/)
    assert.match(FORM, /Array\.from\(e\.target\.files \?\? \[\]\)/)
  })

  test('a selection beyond the limit is trimmed, not refused outright', () => {
    assert.match(FORM, /const room = MAX_POST_IMAGES - images\.length/)
    assert.match(FORM, /picked\.slice\(0, room\)/)
    assert.match(FORM, /could be added/)
  })

  test('the picker is disabled once full, and says why', () => {
    assert.match(FORM, /disabled=\{uploading \|\| images\.length >= MAX_POST_IMAGES\}/)
    assert.match(FORM, /You can attach up to \$\{MAX_POST_IMAGES\} photos/)
  })

  test('each preview can be removed on its own', () => {
    assert.match(FORM, /function removeImage\(id: string\)/)
    assert.match(FORM, /aria-label="Remove this photo"/)
  })

  test('removing a preview deletes no file', () => {
    // The upload may already belong to another post. The composer
    // drops its own reference and nothing else.
    const fn = FORM.slice(FORM.indexOf('function removeImage'))
    const body = fn.slice(0, fn.indexOf('\n  }'))
    assert.ok(!/fetch\(/.test(body), 'removing a preview must not call the server')
    assert.ok(!/DELETE/.test(body))
  })

  test('the post carries only uploads that came back', () => {
    assert.match(FORM, /const uploadedUrls = images\s*\n?\s*\.map\(\(a\) => a\.url\)/)
    assert.match(FORM, /image_urls: uploadedUrls/)
  })

  test('a failed upload drops only its own attachment', () => {
    assert.match(FORM, /prev\.filter\(\(a\) => a\.id !== entry\.id\)/)
  })

  test('the count is shown while composing', () => {
    assert.match(FORM, /\{images\.length\} of \{MAX_POST_IMAGES\} photos/)
  })

  test('the existing formats and the upload endpoint are unchanged', () => {
    assert.match(FORM, /accept="image\/jpeg,image\/png,image\/webp"/)
    assert.match(FORM, /community\/upload-image/)
  })
})


describe('the feed card', () => {
  test('it still shows one thumbnail, with a count when there are more', () => {
    assert.match(CARD, /const images = postImages\(post\)/)
    assert.match(CARD, /images\.length > 1 && \(/)
    assert.match(CARD, /h-16 w-16 rounded-lg object-cover/)
  })

  test('the count is announced, not just drawn', () => {
    assert.match(CARD, /aria-label=\{`\$\{images\.length\} photos`\}/)
  })
})
