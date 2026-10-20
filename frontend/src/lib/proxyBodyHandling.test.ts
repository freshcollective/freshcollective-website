import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, test } from 'node:test'

/**
 * Guards the two changes that made large uploads survivable (B6/B7).
 *
 * Both are easy to undo by accident — one is a regex in a config
 * export, the other is a single line in a request handler — and undoing
 * either reintroduces an out-of-memory crash that takes down the whole
 * frontend for every user, not just the person uploading.
 *
 * Measured on a production build inside a hard 512 MB cgroup, four
 * concurrent 50 MB uploads:
 *
 *   buffered body, middleware on /api   OOM at two concurrent
 *   streamed body, middleware on /api   OOM at two concurrent
 *   streamed body, /api excluded        390 MB for four, no OOM
 *
 * Neither change works without the other, which is why they are tested
 * together in one file.
 */

const SRC = join(import.meta.dirname, '..')

function read(rel: string): string {
  return readFileSync(join(SRC, rel), 'utf8')
}

/** Source with comments stripped.
 *
 *  Without this, a comment *explaining* that the proxy no longer calls
 *  ``request.arrayBuffer()`` would itself fail the assertion that the
 *  proxy no longer calls it — banning the word rather than the use.
 *  Same helper shape as ``offerPagesRetired.test.ts``. */
function codeOnly(rel: string): string {
  // Line comments first, then block comments. The other order breaks on
  // a file whose ``//`` comments mention ``/*`` — the block stripper
  // then pairs that opener with a later ``*/`` and swallows real code
  // in between, which is how this helper first reported that a config
  // value was missing when it was three lines further down.
  return read(rel)
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
    .replace(/\/\*[\s\S]*?\*\//g, '')
}

describe('the middleware does not run on /api', () => {
  const proxy = codeOnly('proxy.ts')

  test('the matcher excludes /api/', () => {
    const match = proxy.match(/matcher:\s*\[\s*'([^']+)'/)
    assert.ok(match, 'no matcher found in proxy.ts')
    assert.ok(
      match![1].includes('api/'),
      'the middleware matcher no longer excludes /api/ — Next will clone '
      + 'every API request body again, and large uploads will OOM fc-web',
    )
  })

  test('the exclusion actually excludes an API path', () => {
    const match = proxy.match(/matcher:\s*\[\s*'([^']+)'/)
    const re = new RegExp(`^${match![1].replace(/\\\\/g, '\\')}$`)
    assert.equal(
      re.test('/api/creator/spaces/x/offerings/y/files'), false,
      'an API upload path still matches the middleware',
    )
    // The positive control: ordinary pages must still run middleware,
    // or authentication redirects and the active-collective sync break.
    assert.equal(re.test('/creator-studio/offerings'), true)
    assert.equal(re.test('/spaces/embody/about'), true)
  })

  test('the middleware never needed the body', () => {
    // The clone was pure cost: this middleware reads headers, cookies
    // and the pathname, and nothing else. If that stops being true the
    // exclusion needs rethinking rather than silently dropping work.
    for (const bodyReader of ['request.json', 'request.text', 'request.formData',
                              'request.arrayBuffer', 'request.body']) {
      assert.ok(
        !proxy.includes(bodyReader),
        `proxy.ts now reads the request body via ${bodyReader}, which the `
        + '/api exclusion would silently skip',
      )
    }
  })
})

describe('the BFF proxy streams request bodies', () => {
  const route = codeOnly('app/api/[...path]/route.ts')

  test('it does not buffer the whole body', () => {
    assert.ok(
      !route.includes('await request.arrayBuffer()'),
      'the proxy buffers the entire upload again — fc-web memory will '
      + 'scale with file size and OOM under concurrent uploads',
    )
  })

  test('it forwards the stream with duplex: half', () => {
    assert.ok(route.includes('init.body = request.body'))
    assert.ok(
      route.includes("duplex: 'half'"),
      'a streamed fetch body requires duplex: half',
    )
  })

  test('an empty body is still not forwarded', () => {
    // Preserved from the buffered implementation: a zero-length body
    // made some servers reject the request outright.
    assert.ok(route.includes("content-length') !== '0'"))
  })
})

describe('the proxy body ceiling is configured', () => {
  const config = codeOnly('../next.config.ts')

  test('proxyClientMaxBodySize is set above the Offering file limit', () => {
    const match = config.match(/proxyClientMaxBodySize:\s*(\d+)\s*\*\s*1024\s*\*\s*1024/)
    assert.ok(
      match,
      'proxyClientMaxBodySize is unset — Next defaults to 10 MiB and '
      + 'SILENTLY TRUNCATES larger bodies while still returning 200',
    )
    const mib = Number(match![1])
    // 50 MB per file on Creator Portfolio, plus multipart framing.
    assert.ok(mib >= 52, `ceiling is ${mib} MiB, below the 50 MB file limit`)
  })
})
