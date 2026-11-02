import { strict as assert } from 'node:assert'
import { describe, it } from 'node:test'

import {
  arrangementOf,
  broadensAccess,
  buildChannelEditPatch,
  storedChannelType,
  type ChannelEditInput,
} from './channelEditing.ts'

function input(over: Partial<ChannelEditInput> = {}): ChannelEditInput {
  return {
    name: 'Women’s Circle',
    description: 'A monthly gathering',
    memberPostingAllowed: true,
    pollsAllowed: true,
    arrangement: 'open',
    currentChannelType: 'open',
    links: [],
    ...over,
  }
}

describe('arrangementOf — how a stored channel reads back', () => {
  it('maps every linked kind to one arrangement', () => {
    for (const t of ['pathway', 'gathering', 'series']) {
      assert.equal(arrangementOf(t), 'linked')
    }
  })

  it('maps private and open to themselves', () => {
    assert.equal(arrangementOf('private'), 'private')
    assert.equal(arrangementOf('open'), 'open')
  })

  it('treats the system types as open, which is their audience', () => {
    assert.equal(arrangementOf('general'), 'open')
    assert.equal(arrangementOf('start_here'), 'open')
  })
})

describe('storedChannelType', () => {
  it('takes the kind of the first selected experience', () => {
    assert.equal(
      storedChannelType('linked', [
        { type: 'series', id: 's1' },
        { type: 'gathering', id: 'g1' },
      ]),
      'series',
    )
  })

  it('falls back to gathering when nothing is selected', () => {
    // The backend refuses a linked channel with no links, so this
    // fails cleanly rather than storing something misleading.
    assert.equal(storedChannelType('linked', []), 'gathering')
  })

  it('passes open and private straight through', () => {
    assert.equal(storedChannelType('open', []), 'open')
    assert.equal(storedChannelType('private', []), 'private')
  })
})

describe('broadensAccess — only widening warrants a warning', () => {
  it('private to open widens', () => {
    assert.equal(broadensAccess('private', 'open'), true)
  })

  it('linked to open widens', () => {
    assert.equal(broadensAccess('linked', 'open'), true)
  })

  it('private to linked widens', () => {
    assert.equal(broadensAccess('private', 'linked'), true)
  })

  it('open to private does not — nobody is newly exposed', () => {
    assert.equal(broadensAccess('open', 'private'), false)
    assert.equal(broadensAccess('open', 'linked'), false)
    assert.equal(broadensAccess('linked', 'private'), false)
  })

  it('no change does not', () => {
    assert.equal(broadensAccess('open', 'open'), false)
    assert.equal(broadensAccess('linked', 'linked'), false)
  })
})

describe('buildChannelEditPatch', () => {
  it('always carries name and description', () => {
    const patch = buildChannelEditPatch(input({ name: '  Spaced  ' }))
    assert.equal(patch.name, 'Spaced')
    assert.equal(patch.description, 'A monthly gathering')
  })

  it('sends an empty description as null, not an empty string', () => {
    const patch = buildChannelEditPatch(input({ description: '   ' }))
    assert.equal(patch.description, null)
  })

  it('carries participation and poll settings', () => {
    const patch = buildChannelEditPatch(input({
      memberPostingAllowed: false, pollsAllowed: false,
    }))
    assert.equal(patch.member_posting_allowed, false)
    assert.equal(patch.polls_allowed, false)
  })

  it('omits channel_type when the arrangement has not changed', () => {
    const patch = buildChannelEditPatch(input({
      arrangement: 'linked', currentChannelType: 'gathering',
      links: [{ type: 'gathering', id: 'g1' }],
    }))
    assert.equal('channel_type' in patch, false)
  })

  it('sends channel_type when the arrangement changes', () => {
    const patch = buildChannelEditPatch(input({
      arrangement: 'private', currentChannelType: 'open',
    }))
    assert.equal(patch.channel_type, 'private')
  })

  it('maps a change to linked onto the first experience kind', () => {
    const patch = buildChannelEditPatch(input({
      arrangement: 'linked', currentChannelType: 'open',
      links: [{ type: 'pathway', id: 'p1' }],
    }))
    assert.equal(patch.channel_type, 'pathway')
  })

  describe('linked_experiences is omitted unless it applies', () => {
    it('omits it for an open channel', () => {
      // The absence means "leave the links alone". Sending [] here
      // would unlink everything the channel had, from a rename.
      const patch = buildChannelEditPatch(input({
        arrangement: 'open', currentChannelType: 'open',
      }))
      assert.equal('linked_experiences' in patch, false)
    })

    it('omits it for a private channel', () => {
      const patch = buildChannelEditPatch(input({
        arrangement: 'private', currentChannelType: 'private',
      }))
      assert.equal('linked_experiences' in patch, false)
    })

    it('omits it when moving a linked channel to open', () => {
      const patch = buildChannelEditPatch(input({
        arrangement: 'open', currentChannelType: 'gathering',
        links: [{ type: 'gathering', id: 'g1' }],
      }))
      assert.equal('linked_experiences' in patch, false)
      assert.equal(patch.channel_type, 'open')
    })

    it('sends the full set when the channel is linked', () => {
      const links = [
        { type: 'gathering' as const, id: 'nov' },
        { type: 'gathering' as const, id: 'dec' },
        { type: 'pathway' as const, id: 'know-yourself' },
      ]
      const patch = buildChannelEditPatch(input({
        arrangement: 'linked', currentChannelType: 'gathering', links,
      }))
      assert.deepEqual(patch.linked_experiences, links)
    })

    it('sends the set when becoming linked', () => {
      const patch = buildChannelEditPatch(input({
        arrangement: 'linked', currentChannelType: 'private',
        links: [{ type: 'series', id: 'term-1' }],
      }))
      assert.equal(patch.channel_type, 'series')
      assert.deepEqual(patch.linked_experiences, [
        { type: 'series', id: 'term-1' },
      ])
    })
  })

  describe('Common Room', () => {
    it('only name and description may change', () => {
      const patch = buildChannelEditPatch(input({
        systemGeneral: true,
        arrangement: 'private',
        currentChannelType: 'general',
        memberPostingAllowed: false,
        links: [{ type: 'pathway', id: 'p1' }],
      }))
      assert.deepEqual(Object.keys(patch).sort(), ['description', 'name'])
    })
  })
})
