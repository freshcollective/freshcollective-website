import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { isOfferingFileUpload } from './uploadRouting.ts'

describe('the Offering upload timeout applies to exactly two endpoints', () => {
  test('a file upload matches', () => {
    assert.equal(
      isOfferingFileUpload('POST', 'creator/spaces/embody/offerings/guide/files'),
      true,
    )
  })

  test('a file replacement matches', () => {
    assert.equal(
      isOfferingFileUpload(
        'POST',
        'creator/spaces/embody/offerings/guide/files/ofl_123/replace',
      ),
      true,
    )
  })

  test('the method is checked case-insensitively', () => {
    assert.equal(
      isOfferingFileUpload('post', 'creator/spaces/embody/offerings/g/files'),
      true,
    )
  })
})

describe('nothing else gets the longer budget', () => {
  // A longer timeout on an endpoint that does not need one means a stuck
  // backend holds a browser connection four times as long, so each of
  // these is a real guard rather than a completeness exercise.
  const notUploads: ReadonlyArray<readonly [string, string]> = [
    ['GET', 'creator/spaces/embody/offerings/guide/files'],
    ['DELETE', 'creator/spaces/embody/offerings/guide/files/ofl_1'],
    ['PATCH', 'creator/spaces/embody/offerings/guide/files/ofl_1'],
    ['POST', 'creator/spaces/embody/offerings/guide/files/reorder'],
    ['POST', 'creator/spaces/embody/offerings'],
    ['POST', 'creator/spaces/embody/offerings/guide/publish'],
    ['POST', 'creator/spaces/embody/pathways/p/steps/s/resources'],
    ['POST', 'uploads/avatars'],
    ['POST', 'checkout'],
    ['POST', 'auth/login'],
  ]

  for (const [method, path] of notUploads) {
    test(`${method} /api/${path}`, () => {
      assert.equal(isOfferingFileUpload(method, path), false)
    })
  }
})

describe('the matcher cannot be widened by a crafted path', () => {
  test('a Collective slug containing "offerings" is not enough', () => {
    assert.equal(
      isOfferingFileUpload('POST', 'creator/spaces/my-offerings/files'),
      false,
    )
  })

  test('a path outside creator/spaces never matches', () => {
    assert.equal(
      isOfferingFileUpload('POST', 'spaces/embody/offerings/guide/files'),
      false,
    )
  })
})
