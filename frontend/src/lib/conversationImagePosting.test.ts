import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Collective Conversations — publishing a post or reply that carries an
 * image.
 *
 * The reported bug: the picker opened, the file uploaded, the preview
 * appeared, and then nothing happened. Share was disabled because the
 * body was empty, and a disabled button has nothing to say — so the
 * upload looked successful and the post simply never went.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const POST = 'components/community/CreatePostForm.tsx'
const COMMENT = 'components/community/CreateCommentForm.tsx'

/** The `disabled` expression on a composer's submit button. */
function submitDisabled(path: string): string {
  const src = codeOnly(path)
  const i = src.lastIndexOf('disabled={')
  assert.ok(i > 0, `${path}: no submit disabled expression`)
  return src.slice(i, src.indexOf('}\n', i) + 1)
}

describe('an image is enough to publish', () => {
  for (const [label, path] of [['post', POST], ['reply', COMMENT]] as const) {
    describe(label, () => {
      test('submit is not blocked by empty text when an image is attached', () => {
        const d = submitDisabled(path)
        assert.match(d, /!body\.trim\(\) && !imageUrl/)
        assert.ok(
          !/!body\.trim\(\)\s*(\)|\|\|)/.test(d.replace(/!body\.trim\(\) && !imageUrl/g, '')),
          `${label}: text is still required on its own`,
        )
      })

      test('the guard matches the button', () => {
        // A guard stricter than the button turns a working click into a
        // silent no-op; looser, and the button lies about being ready.
        assert.match(codeOnly(path), /!body\.trim\(\) && !imageUrl/)
      })

      test('it is the uploaded url that counts, not the local preview', () => {
        // `imagePreview` is set from createObjectURL the instant a file
        // is chosen — before, and regardless of whether, the upload
        // succeeds. Posting on that would attach nothing.
        const d = submitDisabled(path)
        assert.ok(
          !d.includes('imagePreview'),
          `${label}: submit must not be enabled by a local preview`,
        )
      })

      test('an upload in flight still blocks submit', () => {
        assert.match(submitDisabled(path), /uploading/)
      })

      test('the image url is sent with the post', () => {
        assert.match(codeOnly(path), /image_url: imageUrl \|\| null/)
      })
    })
  }

  test('neither empty is still refused, with a reason', () => {
    // Not a silent return: the reply composer used to just stop.
    for (const path of [POST, COMMENT]) {
      const src = codeOnly(path)
      const i = src.indexOf('!body.trim() && !imageUrl')
      const after = src.slice(i, i + 220)
      assert.match(after, /setError\(/, `${path}: refusal must explain itself`)
    }
    assert.match(read(POST), /write something or attach an image/)
    assert.match(read(COMMENT), /write something or attach an image/)
  })
})

describe('the attachment survives until it is sent or removed', () => {
  for (const [label, path] of [['post', POST], ['reply', COMMENT]] as const) {
    test(`${label}: the composer is only cleared after a successful send`, () => {
      // The two composers express this differently — one returns early
      // on failure, the other wraps the clear in `if (res.ok)`. The
      // invariant is the same either way: the response has to have been
      // examined before anything is thrown away, and the failure path
      // has to say something. Asserted on the shape rather than on one
      // composer's control flow.
      const src = codeOnly(path)
      const submit = src.slice(src.indexOf('async function handleSubmit'))
      const clearAt = submit.search(/reset\(\)|setImageUrl\(null\)/)
      assert.ok(clearAt > 0, `${label}: nothing clears the composer`)

      const okAt = submit.indexOf('res.ok')
      assert.ok(okAt > 0, `${label}: the response is never checked`)
      assert.ok(
        okAt < clearAt,
        `${label}: the composer is cleared before the send is known to have worked`,
      )
      assert.match(submit, /setError\(/, `${label}: a failed send must report`)
    })

    test(`${label}: a failed upload clears the preview and keeps the text`, () => {
      const src = codeOnly(path)
      const handler = src.slice(
        src.indexOf('handleImageChange'),
        src.indexOf('handleSubmit'),
      )
      assert.match(handler, /setError\(/, 'the failure is reported')
      assert.match(handler, /setImagePreview\(null\)/, 'the dead preview goes')
      assert.ok(
        !/setBody\(''\)/.test(handler),
        'a failed upload must not discard what was typed',
      )
    })

    test(`${label}: removing the attachment clears both the url and the preview`, () => {
      // Clearing only the preview would leave an invisible attachment
      // that still posts.
      assert.match(
        codeOnly(path),
        /setImageUrl\(null\);?\s*setImagePreview\(null\)/,
      )
    })
  }
})

describe('upload validation is not widened', () => {
  test('the picker still offers only the three permitted types', () => {
    for (const path of [POST, COMMENT]) {
      assert.match(
        codeOnly(path),
        /accept="image\/jpeg,image\/png,image\/webp"/,
        path,
      )
    }
  })

  test('no svg is offered', () => {
    for (const path of [POST, COMMENT]) {
      assert.ok(!codeOnly(path).includes('svg'), path)
    }
  })
})

describe('posted images render through the shared component', () => {
  const SITES = [
    'components/community/PostCard.tsx',
    'app/spaces/[slug]/community/[postId]/page.tsx',
    'app/spaces/[slug]/community/[postId]/RepliesClient.tsx',
  ]

  test('every surface uses CommunityImage', () => {
    for (const path of SITES) {
      assert.match(codeOnly(path), /<CommunityImage/, path)
    }
  })

  test('no surface hand-rolls an img for a post image', () => {
    // The feed did, so a key that could not be read showed a broken
    // image icon instead of nothing.
    for (const path of SITES) {
      const src = codeOnly(path)
      assert.ok(
        !/<img[^>]*src=\{resolveMediaUrl/.test(src),
        `${path}: bare <img> for a community image`,
      )
    }
  })

  test('the component degrades to nothing when the file cannot be read', () => {
    const src = codeOnly('components/community/CommunityImage.tsx')
    assert.match(src, /onError=\{\(\) => setFailed\(true\)\}/)
    assert.match(src, /if \(failed\) return null/)
  })

  test('images are width-bound so they cannot overflow the thread', () => {
    for (const path of SITES) {
      const src = codeOnly(path)
      const i = src.indexOf('<CommunityImage')
      const el = src.slice(i, src.indexOf('/>', i))
      assert.match(el, /className="[^"]*\b(w-full|w-16|max-w)/, path)
    }
  })

  test('each render site gives the image an alt decision', () => {
    for (const path of SITES) {
      const src = codeOnly(path)
      const i = src.indexOf('<CommunityImage')
      assert.match(src.slice(i, src.indexOf('/>', i)), /alt=/, path)
    }
  })
})
