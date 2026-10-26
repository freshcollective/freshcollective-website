import { strict as assert } from 'node:assert'
import { describe, it } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  ARCHIVE_CONFIRM_PARAGRAPHS,
  DELETE_CONFIRM_PARAGRAPHS,
  GENERIC_ARCHIVE_ERROR,
  GENERIC_DELETE_ERROR,
  GENERIC_RESTORE_ERROR,
  NOT_DELETABLE_PARAGRAPHS,
  RESTORED_STATUS,
  actionErrorMessage,
  isArchivableStatus,
  isDeletableStatus,
  isRestorableStatus,
} from './pathwayLifecycle.ts'

const SRC = dirname(dirname(fileURLToPath(import.meta.url)))
const CLIENT = join(
  SRC, 'app', 'creator-studio', 'pathways', 'PathwaysClient.tsx',
)

const ALL_STATUSES = ['draft', 'active', 'coming_soon', 'archived']

describe('actionErrorMessage', () => {
  it('shows the server sentence when there is one', () => {
    assert.equal(
      actionErrorMessage(
        {
          detail:
            'This pathway cannot be permanently deleted because members '
            + 'hold access to it. Those records are kept.',
        },
        GENERIC_DELETE_ERROR,
      ),
      'This pathway cannot be permanently deleted because members hold '
      + 'access to it. Those records are kept.',
    )
  })

  it('uses the fallback it was given, per action', () => {
    assert.equal(actionErrorMessage({}, GENERIC_ARCHIVE_ERROR), GENERIC_ARCHIVE_ERROR)
    assert.equal(actionErrorMessage({}, GENERIC_RESTORE_ERROR), GENERIC_RESTORE_ERROR)
  })

  it('falls back on a non-object body', () => {
    // A proxy error page, or ``res.json()`` having been caught.
    for (const body of [undefined, null, '', 'nope', 404]) {
      assert.equal(
        actionErrorMessage(body, GENERIC_DELETE_ERROR), GENERIC_DELETE_ERROR,
      )
    }
  })

  it('falls back on a non-string or blank detail', () => {
    // FastAPI returns a LIST of objects for a validation error, which
    // must never be rendered as a sentence.
    assert.equal(
      actionErrorMessage({ detail: [{ msg: 'field required' }] }, GENERIC_DELETE_ERROR),
      GENERIC_DELETE_ERROR,
    )
    assert.equal(
      actionErrorMessage({ detail: '   ' }, GENERIC_DELETE_ERROR),
      GENERIC_DELETE_ERROR,
    )
  })
})

describe('which actions a status offers', () => {
  it('offers Delete on a draft only', () => {
    assert.deepEqual(
      ALL_STATUSES.filter(isDeletableStatus), ['draft'],
    )
  })

  it('offers Archive on everything not already archived', () => {
    assert.deepEqual(
      ALL_STATUSES.filter(isArchivableStatus),
      ['draft', 'active', 'coming_soon'],
    )
  })

  it('offers Restore on an archived pathway only', () => {
    assert.deepEqual(
      ALL_STATUSES.filter(isRestorableStatus), ['archived'],
    )
  })

  it('never offers Archive and Restore at the same time', () => {
    for (const s of ALL_STATUSES) {
      assert.equal(
        isArchivableStatus(s) && isRestorableStatus(s), false, s,
      )
    }
  })

  it('restores to Draft, not to Live', () => {
    // A silent re-publish would put a pathway back in front of members
    // without the creator choosing to.
    assert.equal(RESTORED_STATUS, 'draft')
  })
})

describe('the Pathways page uses them', () => {
  // Source contract. Asserted on the affordances the page renders
  // rather than on words — this file's own prose legitimately contains
  // "try again", "archive" and "detail", and a blunt substring check
  // on vocabulary has tripped on comments here before.
  const source = readFileSync(CLIENT, 'utf8')

  it('imports the helpers rather than restating them', () => {
    assert.match(source, /from '@\/lib\/pathwayLifecycle'/)
    for (const fn of [
      'actionErrorMessage',
      'isArchivableStatus',
      'isDeletableStatus',
      'isRestorableStatus',
    ]) {
      assert.match(source, new RegExp(`${fn}\\(`), fn)
    }
  })

  it('reads the response body on a failed action', () => {
    // Without this the 409 sentence never reaches the creator, which
    // is the whole defect being fixed.
    assert.match(source, /res\.json\(\)/)
  })

  it('renders the confirmation copy from the shared constants', () => {
    // Not a copy of the sentences — just that the component uses the
    // ones these tests assert, so the two cannot diverge.
    for (const name of [
      'ARCHIVE_CONFIRM_PARAGRAPHS',
      'DELETE_CONFIRM_PARAGRAPHS',
      'NOT_DELETABLE_PARAGRAPHS',
    ]) {
      assert.match(source, new RegExp(name), name)
    }
    assert.match(source, /copy\.paragraphs\.map\(/)
  })

  it('renders an Archived group in the gallery', () => {
    // An archived pathway used to vanish from this page entirely,
    // reachable only by typing its settings URL.
    assert.match(source, /status === 'archived'/)
  })

  it('no longer filters archived rows out of the gallery', () => {
    assert.doesNotMatch(source, /\.status !== 'archived'/)
  })

  it('sends the status change through PATCH', () => {
    assert.match(source, /method: 'PATCH'/)
  })
})


describe('the archive confirmation copy', () => {
  // Asserted on the strings themselves, which is only possible because
  // the copy is data. Each check is one promise the creator is being
  // made, so a reworded paragraph that drops a promise fails here.
  const all = ARCHIVE_CONFIRM_PARAGRAPHS.join(' ')

  it('says it leaves public discovery', () => {
    assert.match(all, /public listings/)
    assert.match(all, /members browsing your pathways/)
  })

  it('says new individual purchases stop', () => {
    assert.match(all, /nobody new can buy it on its own/)
  })

  it('does not claim it can never be bought again', () => {
    // The correction this copy exists for. A pathway inside a bundle
    // that is still on sale IS still acquirable, so an unqualified
    // promise would be untrue — and the qualifier has to be the
    // "on its own" above, not a vaguer hedge.
    assert.doesNotMatch(all, /can no longer be bought(?! on its own)/)
    assert.doesNotMatch(all, /cannot be purchased/)
    assert.doesNotMatch(all, /no longer be purchased/)
  })

  it('says existing holders keep access and progress', () => {
    assert.match(all, /already has access keeps it/)
    assert.match(all, /progress and reflections/)
    // Named individually, because "purchases" alone would leave a
    // creator unsure about the other two.
    for (const source of ['purchases', 'manual grants', 'passes']) {
      assert.match(all, new RegExp(source), source)
    }
  })

  it('names the bundle exception and what to do about it', () => {
    assert.match(all, /part of a bundle/)
    assert.match(all, /still get access to it/)
    assert.match(all, /editing what the bundle includes/)
  })

  it('says it can be restored', () => {
    assert.match(all, /restore this pathway at any time/)
  })

  it('reads as four short paragraphs', () => {
    assert.equal(ARCHIVE_CONFIRM_PARAGRAPHS.length, 4)
    for (const para of ARCHIVE_CONFIRM_PARAGRAPHS) {
      assert.ok(para.length < 220, `too long: ${para}`)
      assert.ok(para.trim() === para, `untrimmed: ${para}`)
    }
  })

  it('uses typographic punctuation, not ASCII substitutes', () => {
    // House style, and the reason the copy moved out of JSX: a real
    // apostrophe here needs no HTML entity.
    assert.match(all, /\u2019/)
    assert.doesNotMatch(all, /&rsquo;|&amp;|&mdash;/)
  })
})

describe('the delete confirmation copy', () => {
  const all = DELETE_CONFIRM_PARAGRAPHS.join(' ')

  it('warns that deletion is permanent', () => {
    assert.match(all, /permanently remove/)
    assert.match(all, /cannot be undone/)
  })

  it('tells the creator a protected pathway will be declined, not obeyed', () => {
    // The platform refuses rather than cascading, and a creator who
    // does not know that will not risk pressing the button.
    assert.match(all, /declined and nothing will change/)
  })

  it('does not promise to remove member progress', () => {
    // The old copy said deletion "will permanently remove the pathway
    // and any associated member progress", which is the behaviour that
    // was removed. Promising destruction the platform no longer
    // performs is as misleading as the reverse.
    assert.doesNotMatch(all, /remove .{0,40}member progress/)
  })
})

describe('the not-deletable copy', () => {
  it('points at the two things that actually work', () => {
    const all = NOT_DELETABLE_PARAGRAPHS.join(' ')
    assert.match(all, /Only a draft pathway/)
    assert.match(all, /Archive it instead/)
    assert.match(all, /back to Draft in its settings/)
  })
})
