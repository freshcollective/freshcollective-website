/**
 * An upload that never reached the server must say so.
 *
 * ``fetch`` rejects, rather than resolving with a failed status, when
 * the request never completed — dropped connection, lost network,
 * server gone mid-body. Two handlers wrapped that in ``try``/
 * ``finally`` with no ``catch``:
 *
 *   * ``LibraryClient.doUpload`` — the throw escaped as an unhandled
 *     rejection, reported as Sentry FC-WEB-6, and the creator saw the
 *     button stop spinning with nothing said.
 *   * ``CreateCommentForm.handleImageChange`` — worse than silent. The
 *     preview is set before the request, so a throw left an image on
 *     screen that was never attached; and because the file input is
 *     disabled while a preview exists, the member could neither pick
 *     another file nor post. Stuck.
 *
 * These cover the message itself and the wiring at both call sites.
 * The project has no DOM renderer (node:test only, no testing-library
 * or jsdom), so handler behaviour is pinned by reading the source.
 * Comments are stripped with a quote-aware walker — the naive regex
 * version reads ``accept="image/*"`` as a comment opener and deletes
 * the code under test.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import { UPLOAD_NETWORK_ERROR } from './uploadErrors.ts'

function codeOnly(src: string): string {
  let out = ''
  let i = 0
  let quote: string | null = null
  while (i < src.length) {
    const c = src[i]
    const next = src[i + 1]
    if (quote) {
      out += c
      if (c === '\\') { out += next ?? ''; i += 2; continue }
      if (c === quote) quote = null
      i += 1
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; out += c; i += 1; continue }
    if (c === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2)
      i = end === -1 ? src.length : end + 2
      continue
    }
    if (c === '/' && next === '/') {
      const end = src.indexOf('\n', i)
      i = end === -1 ? src.length : end
      continue
    }
    out += c
    i += 1
  }
  return out
}

const read = (p: string) => codeOnly(readFileSync(p, 'utf8'))

const LIBRARY = read('src/app/creator-studio/library/LibraryClient.tsx')
const COMMENT = read('src/components/community/CreateCommentForm.tsx')

/** The body of a named async function, to its closing brace column. */
function fnBody(src: string, signature: string): string {
  const start = src.indexOf(signature)
  assert.notEqual(start, -1, `no function matching ${signature}`)
  const rest = src.slice(start)
  const end = rest.indexOf('\n  }\n')
  assert.notEqual(end, -1, `${signature} never closes`)
  return rest.slice(0, end)
}

const DO_UPLOAD = fnBody(LIBRARY, 'async function doUpload()')
const ON_IMAGE = fnBody(COMMENT, 'async function handleImageChange(')

// ---------------------------------------------------------------------------
// 1 · Network failures are caught in both
// ---------------------------------------------------------------------------

describe('a thrown request is caught', () => {
  test('the Library upload has a catch', () => {
    assert.match(DO_UPLOAD, /\} catch/, 'doUpload still lets a throw escape (FC-WEB-6)')
  })

  test('the comment image upload has a catch', () => {
    assert.match(ON_IMAGE, /\} catch/, 'handleImageChange still lets a throw escape')
  })

  test('neither is try/finally alone', () => {
    for (const [name, body] of [['doUpload', DO_UPLOAD], ['handleImageChange', ON_IMAGE]] as const) {
      const hasCatch = /\} catch/.test(body)
      const hasFinally = /\} finally/.test(body)
      assert.ok(hasFinally, `${name} lost its finally`)
      assert.ok(hasCatch, `${name} is try/finally with no catch — the original defect`)
    }
  })
})

// ---------------------------------------------------------------------------
// 2 · The indicator resets
// ---------------------------------------------------------------------------

describe('the uploading indicator resets after a failure', () => {
  test('both reset in finally, so every path clears it', () => {
    assert.match(DO_UPLOAD, /\} finally \{[\s\S]*?setUploading\(false\)/)
    assert.match(ON_IMAGE, /\} finally \{[\s\S]*?setUploading\(false\)/)
  })
})

// ---------------------------------------------------------------------------
// 3 · The member is told
// ---------------------------------------------------------------------------

describe('a clear message appears', () => {
  test('both report the shared network message', () => {
    assert.match(DO_UPLOAD, /show\(UPLOAD_NETWORK_ERROR, \{ tone: 'error' \}\)/)
    assert.match(ON_IMAGE, /setError\(UPLOAD_NETWORK_ERROR\)/)
  })

  test('the message says what happened and what to do', () => {
    assert.match(UPLOAD_NETWORK_ERROR, /couldn't complete the upload/i)
    assert.match(UPLOAD_NETWORK_ERROR, /try again/i)
  })

  test('it never claims the upload succeeded', () => {
    // "complete" appears, but negated — so test the negation is there
    // rather than banning the word, which only produced a lookahead
    // pointing the wrong way at "couldn't complete".
    for (const claim of [/\buploaded\b/i, /\bsuccess/i, /\bdone\b/i]) {
      assert.ok(!claim.test(UPLOAD_NETWORK_ERROR), `${claim} reads as success`)
    }
    assert.match(
      UPLOAD_NETWORK_ERROR,
      /couldn't|could not|unable|failed/i,
      'the message does not say the upload did not happen',
    )
  })
})

// ---------------------------------------------------------------------------
// 4 · A failure cannot be mistaken for a success
// ---------------------------------------------------------------------------

describe('a failed upload leaves no sign of success', () => {
  test('the Library does not record an uploaded asset in the catch', () => {
    const katch = DO_UPLOAD.slice(DO_UPLOAD.indexOf('} catch'))
    for (const forbidden of ['setUploaded(', 'onUploaded(', "tone: 'success'"]) {
      assert.ok(!katch.includes(forbidden), `the catch calls ${forbidden}`)
    }
  })

  test('the comment form clears the misleading preview', () => {
    // Set before the request, so a throw leaves an image on screen that
    // was never attached — and the file input is disabled while it is
    // there, which is what left the member unable to retry or post.
    const katch = ON_IMAGE.slice(ON_IMAGE.indexOf('} catch'))
    assert.match(katch, /setImagePreview\(null\)/, 'a phantom preview survives a failure')
  })

  test('the comment form does not invent an attachment URL', () => {
    const katch = ON_IMAGE.slice(ON_IMAGE.indexOf('} catch'))
    assert.ok(!/setImageUrl\([^)]*[^)]\)/.test(katch.replace('setImageUrl(null)', '')),
      'the catch sets an image URL')
  })

  test('the file input is still gated on the preview', () => {
    // Pins why clearing the preview matters: it re-enables selection.
    assert.match(COMMENT, /disabled=\{uploading \|\| !!imagePreview\}/)
  })
})

// ---------------------------------------------------------------------------
// 5 & 6 · Success and HTTP errors are untouched
// ---------------------------------------------------------------------------

describe('the existing paths still work', () => {
  test('the Library still handles a successful upload', () => {
    assert.match(DO_UPLOAD, /setUploaded\(\{ id: asset\.id, title: asset\.title \}\)/)
    assert.match(DO_UPLOAD, /show\('Uploaded\.', \{ tone: 'success' \}\)/)
    assert.match(DO_UPLOAD, /onUploaded\(\)/)
  })

  test('the Library still surfaces the server reason on a failed status', () => {
    assert.match(DO_UPLOAD, /if \(!res\.ok\)/)
    assert.match(DO_UPLOAD, /body\.detail === 'string' \? body\.detail : 'Upload failed\.'/)
  })

  test('the comment form still stores a confirmed URL', () => {
    assert.match(ON_IMAGE, /const \{ url \} = await res\.json\(\)/)
    assert.match(ON_IMAGE, /setImageUrl\(url\)/)
  })

  test('the comment form still surfaces the server reason', () => {
    assert.match(ON_IMAGE, /if \(!res\.ok\)/)
    assert.match(ON_IMAGE, /data\.detail \|\| 'Image upload failed\.'/)
  })

  test('the network message is only used for thrown requests', () => {
    // If it appeared in the !res.ok branch it would replace the
    // server's own, more specific reason.
    for (const [name, body] of [['doUpload', DO_UPLOAD], ['handleImageChange', ON_IMAGE]] as const) {
      const httpBranch = body.slice(body.indexOf('if (!res.ok)'), body.indexOf('} catch'))
      assert.ok(
        !httpBranch.includes('UPLOAD_NETWORK_ERROR'),
        `${name} uses the network message for an HTTP error`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// 7 · No technical detail reaches the member
// ---------------------------------------------------------------------------

describe('nothing technical is exposed', () => {
  test('the message carries no internals', () => {
    for (const leak of [/http/i, /\d{3}/, /fetch/i, /TypeError/, /api\//, /stack/i, /error:/i]) {
      assert.ok(!leak.test(UPLOAD_NETWORK_ERROR), `${leak} leaks into the message`)
    }
  })

  test('neither catch renders the caught value', () => {
    // ``catch {}`` with no binding cannot leak one by construction.
    for (const [name, body] of [['doUpload', DO_UPLOAD], ['handleImageChange', ON_IMAGE]] as const) {
      const katch = body.slice(body.indexOf('} catch'))
      assert.ok(
        !/catch\s*\(\s*\w+\s*\)/.test(katch.slice(0, 40)),
        `${name} binds the error — it must not be shown to the member`,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// 8 · Every other FormData upload site still handles a throw
// ---------------------------------------------------------------------------

describe('no upload site lets a network failure escape', () => {
  const SITES = [
    'src/app/admin/atlas/[key]/LocationDetailClient.tsx',
    'src/app/admin/physical-locations/[slug]/PhysicalLocationClient.tsx',
    'src/app/admin/settings/artwork/brand/BrandAssetsClient.tsx',
    'src/app/admin/settings/artwork/PlatformArtworkClient.tsx',
    'src/app/admin/world-guide/documents/[id]/page.tsx',
    'src/app/creator/spaces/[slug]/community/CommunityManager.tsx',
    'src/app/creator/spaces/[slug]/events/EventForm.tsx',
    'src/app/creator-studio/create-collective/CreateCollectiveFlow.tsx',
    'src/app/creator-studio/library/LibraryClient.tsx',
    'src/app/creator-studio/settings/CollectiveSettingsForm.tsx',
    'src/components/community/CreateCommentForm.tsx',
    'src/components/community/CreatePostForm.tsx',
    'src/components/creator/BlockEditorShared.tsx',
    'src/components/creator/ImagePickerField.tsx',
    'src/components/settings/ProfileForm.tsx',
  ]

  test('every file that builds a FormData also catches', () => {
    // A sweep, not a proof: it cannot tell which function the catch
    // belongs to. It would still have flagged both defects here, and
    // it flags a new upload surface that ships with none.
    const offenders: string[] = []
    for (const path of SITES) {
      const src = read(path)
      if (!src.includes('new FormData()')) continue
      if (!/\} catch/.test(src)) offenders.push(path)
    }
    assert.deepEqual(offenders, [], `upload sites with no catch at all: ${offenders.join(', ')}`)
  })

  test('the two fixed sites are in the swept list', () => {
    assert.ok(SITES.includes('src/app/creator-studio/library/LibraryClient.tsx'))
    assert.ok(SITES.includes('src/components/community/CreateCommentForm.tsx'))
  })
})
