import assert from 'node:assert/strict'
import { beforeEach, describe, test } from 'node:test'

import {
  IN_FLIGHT_BYTE_BUDGET,
  LARGE_UPLOAD_BYTES,
  MAX_CONCURRENT_LARGE_UPLOADS,
  acquireLargeUploadSlot,
  largeUploadBytesInFlight,
  largeUploadsInFlight,
  needsSlot,
  resetLargeUploadGate,
} from './uploadConcurrency.ts'

beforeEach(() => resetLargeUploadGate())

const MB = 1024 * 1024

describe('which requests take a slot', () => {
  test('a large upload does', () => {
    assert.equal(needsSlot('POST', String(50 * MB)), true)
    assert.equal(needsSlot('POST', String(LARGE_UPLOAD_BYTES)), true)
  })

  test('a small one does not', () => {
    // An avatar or a JSON patch must never wait behind a video.
    assert.equal(needsSlot('POST', String(200 * 1024)), false)
    assert.equal(needsSlot('POST', String(LARGE_UPLOAD_BYTES - 1)), false)
  })

  test('reads never do', () => {
    assert.equal(needsSlot('GET', String(50 * MB)), false)
    assert.equal(needsSlot('HEAD', String(50 * MB)), false)
  })

  test('a missing or junk Content-Length does not', () => {
    // The header is client-supplied, so this gate is not a security
    // control. fc-api's counting check and proxyClientMaxBodySize are
    // the authoritative limits; this only catches honest large uploads.
    assert.equal(needsSlot('POST', null), false)
    assert.equal(needsSlot('POST', 'banana'), false)
    assert.equal(needsSlot('POST', ''), false)
  })
})

describe('the gate bounds concurrency at two', () => {
  test('the agreed launch ceiling is two', () => {
    // Matches fc-api's MAX_CONCURRENT_UPLOADS and the conservative
    // ceiling agreed for launch. Raising it means re-running the
    // 512 MB memory measurement first.
    assert.equal(MAX_CONCURRENT_LARGE_UPLOADS, 2)
  })

  test('the third concurrent upload is refused', () => {
    const a = acquireLargeUploadSlot(10 * MB)
    const b = acquireLargeUploadSlot(10 * MB)
    assert.ok(a, 'first upload refused')
    assert.ok(b, 'second upload refused')
    assert.equal(largeUploadsInFlight(), 2)
    assert.equal(acquireLargeUploadSlot(10 * MB), null, 'a third slot was handed out')
  })

  test('releasing frees a slot', () => {
    const a = acquireLargeUploadSlot(10 * MB)!
    acquireLargeUploadSlot(10 * MB)
    assert.equal(acquireLargeUploadSlot(10 * MB), null)
    a()
    assert.equal(largeUploadsInFlight(), 1)
    assert.ok(acquireLargeUploadSlot(10 * MB), 'the freed slot was not reusable')
  })

  test('releasing twice does not invent a slot', () => {
    // A double release would let occupancy drift below zero and the
    // gate would stop gating — the failure mode is silent.
    const a = acquireLargeUploadSlot(10 * MB)!
    a()
    a()
    assert.equal(largeUploadsInFlight(), 0)
    assert.ok(acquireLargeUploadSlot(10 * MB))
    assert.ok(acquireLargeUploadSlot(10 * MB))
    assert.equal(acquireLargeUploadSlot(10 * MB), null)
  })
})

describe('the byte budget distinguishes big files from many files', () => {
  test('two uploads at the Offerings ceiling both fit', () => {
    // 50 MB each — the Creator Portfolio maximum. Measured peak 286 MB
    // of 512 MB.
    assert.ok(acquireLargeUploadSlot(50 * MB), 'first 50 MB refused')
    assert.ok(acquireLargeUploadSlot(50 * MB), 'second 50 MB refused')
    assert.equal(largeUploadBytesInFlight(), 100 * MB)
  })

  test('a second very large upload is refused', () => {
    // 250 MB is the Media Library video ceiling. One fits (measured
    // 449 MB); two killed the process outright.
    assert.ok(acquireLargeUploadSlot(250 * MB), 'the first video was refused')
    assert.equal(
      acquireLargeUploadSlot(250 * MB), null,
      'a second 250 MB upload was admitted — measured to OOM at 512 MB',
    )
  })

  test('the first upload is always admitted whatever its size', () => {
    // Refusing it would reduce the advertised limit by the back door:
    // a 250 MB video could never be uploaded at all.
    assert.ok(IN_FLIGHT_BYTE_BUDGET < 250 * MB)
    assert.ok(
      acquireLargeUploadSlot(250 * MB),
      'a lone upload over the budget was refused',
    )
  })

  test('a small second upload still fits beside a medium first', () => {
    assert.ok(acquireLargeUploadSlot(60 * MB))
    assert.ok(acquireLargeUploadSlot(50 * MB), 'within budget but refused')
  })

  test('releasing returns the bytes as well as the slot', () => {
    const big = acquireLargeUploadSlot(100 * MB)!
    assert.equal(largeUploadBytesInFlight(), 100 * MB)
    big()
    assert.equal(largeUploadBytesInFlight(), 0)
    assert.ok(acquireLargeUploadSlot(100 * MB), 'bytes were not returned')
  })
})

describe('the proxy applies the gate', () => {
  test('it acquires, refuses with 429, and releases in a finally', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const src = readFileSync(
      join(import.meta.dirname, '..', 'app', 'api', '[...path]', 'route.ts'),
      'utf8',
    )
    assert.ok(
      src.includes('acquireLargeUploadSlot(declaredBytes)'),
      'the proxy must pass the declared size so the byte budget applies',
    )
    assert.ok(src.includes('429'), 'shedding must use 429, never 503')
    assert.ok(
      /finally\s*\{[\s\S]{0,120}releaseSlot\?\.\(\)/.test(src),
      'the slot is not released in a finally — a leak would wedge uploads '
      + 'until the process restarted',
    )
  })
})
