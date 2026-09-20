import { test, describe, afterEach } from 'node:test'
import assert from 'node:assert/strict'

import { isDiscoveryPillarEnabled, isWaysToConnectEnabled } from './featureFlags.ts'

/**
 * Discover Places and Ways to Connect used to share one flag. They
 * were built as one pillar and are not ready at the same time, so
 * launching the first would have published the second as a side
 * effect. These tests pin the separation — above all the combination
 * we are about to ship: Discovery on, Ways to Connect off.
 *
 * ``process.env`` is written directly because the helpers read it at
 * call time. In a real build Next.js inlines ``NEXT_PUBLIC_*`` at
 * compile time, which is why flipping either flag needs a rebuild
 * rather than a restart — the behaviour under test is the mapping
 * from value to boolean, which is identical either way.
 */

const DISCOVERY = 'NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED'
const WAYS = 'NEXT_PUBLIC_WAYS_TO_CONNECT_ENABLED'

function setFlags(discovery?: string, ways?: string) {
  if (discovery === undefined) delete process.env[DISCOVERY]
  else process.env[DISCOVERY] = discovery
  if (ways === undefined) delete process.env[WAYS]
  else process.env[WAYS] = ways
}

afterEach(() => setFlags(undefined, undefined))

describe('the two flags are independent', () => {
  test('the launch combination: Discovery on, Ways to Connect off', () => {
    setFlags('true', 'false')
    assert.equal(isDiscoveryPillarEnabled(), true)
    assert.equal(isWaysToConnectEnabled(), false)
  })

  test('Ways to Connect stays off when its flag is simply absent', () => {
    // The state on the very first deploy after decoupling: the new
    // variable has not been set anywhere yet.
    setFlags('true', undefined)
    assert.equal(isDiscoveryPillarEnabled(), true)
    assert.equal(isWaysToConnectEnabled(), false)
  })

  test('Ways to Connect can be on while Discovery is off', () => {
    setFlags('false', 'true')
    assert.equal(isDiscoveryPillarEnabled(), false)
    assert.equal(isWaysToConnectEnabled(), true)
  })

  test('both off is the default everywhere', () => {
    setFlags(undefined, undefined)
    assert.equal(isDiscoveryPillarEnabled(), false)
    assert.equal(isWaysToConnectEnabled(), false)
  })

  test('both on still works', () => {
    setFlags('true', 'true')
    assert.equal(isDiscoveryPillarEnabled(), true)
    assert.equal(isWaysToConnectEnabled(), true)
  })
})

describe('only the exact string "true" enables a flag', () => {
  for (const value of ['True', 'TRUE', '1', 'yes', 'on', '', ' true']) {
    test(`${JSON.stringify(value)} is off`, () => {
      setFlags(value, value)
      assert.equal(isDiscoveryPillarEnabled(), false)
      assert.equal(isWaysToConnectEnabled(), false)
    })
  }
})
