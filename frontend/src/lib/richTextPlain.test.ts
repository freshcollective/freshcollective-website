import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  isFormattedDescription,
  richTextExcerpt,
  richTextFirstLine,
  richTextToPlain,
} from './richTextPlain.ts'

const SRC = join(process.cwd(), 'src')

const FORMATTED = '<h2>What to expect</h2>'
  + '<p>Join us for an <strong>evening</strong> of <em>quiet</em> company.</p>'
  + '<ul><li>Bring a journal</li><li>Tea provided</li></ul>'
  + '<ol><li>Arrive</li><li>Settle</li></ol>'
  + '<p>Details on <a href="https://freshcollective.au/x">our page</a>.</p>'

// What the Gatherings that already exist actually hold.
const LEGACY = "Our monthly Women's Circle.\n"
  + 'Doors open at 6.30pm.\n\n'
  + 'Bring something to share — tea & biscuits provided.'

describe('richTextToPlain', () => {
  it('removes every tag', () => {
    const out = richTextToPlain(FORMATTED)
    assert.ok(!out.includes('<'), out)
    assert.ok(!out.includes('>'), out)
  })

  it('keeps the words', () => {
    const out = richTextToPlain(FORMATTED)
    for (const phrase of [
      'What to expect', 'Join us for an evening of quiet company.',
      'Bring a journal', 'Tea provided', 'Arrive', 'our page',
    ]) {
      assert.ok(out.includes(phrase), `${phrase} missing from ${out}`)
    }
  })

  it('keeps paragraphs apart', () => {
    assert.equal(richTextToPlain('<p>One</p><p>Two</p>'), 'One\n\nTwo')
  })

  it('turns a soft break into a line break', () => {
    const out = richTextToPlain('<p>One<br>Two</p>')
    assert.ok(!out.includes('OneTwo'), out)
  })

  it('resolves entities', () => {
    assert.equal(richTextToPlain('<p>A &amp; B</p>'), 'A & B')
    assert.equal(richTextToPlain('<p>&lt;ok&gt;</p>'), '<ok>')
    assert.equal(richTextToPlain('<p>&#8230;</p>'), '…')
    assert.equal(richTextToPlain('<p>&hellip;</p>'), '…')
    assert.equal(richTextToPlain('<p>&#x2019;</p>'), '’')
  })

  it('does not double-decode', () => {
    // "&amp;lt;" is the text "&lt;", not the character "<".
    assert.equal(richTextToPlain('<p>&amp;lt;</p>'), '&lt;')
  })

  it('leaves an unknown entity alone rather than eating it', () => {
    assert.equal(richTextToPlain('<p>&notareal; thing</p>'), '&notareal; thing')
  })

  it('leaves a legacy plain-text description exactly as it is', () => {
    // The many Gatherings written before formatting existed.
    assert.equal(richTextToPlain(LEGACY), LEGACY)
  })

  it('handles nothing at all', () => {
    assert.equal(richTextToPlain(null), '')
    assert.equal(richTextToPlain(undefined), '')
    assert.equal(richTextToPlain(''), '')
    assert.equal(richTextToPlain('<p></p><p>  </p>'), '')
  })
})

describe('richTextExcerpt', () => {
  it('leaves a short description alone', () => {
    assert.equal(richTextExcerpt('<p>Short.</p>', 100), 'Short.')
  })

  it('cuts on a word boundary and marks the cut', () => {
    const out = richTextExcerpt('<p>' + 'alpha '.repeat(40) + '</p>', 40)
    assert.ok(out.length <= 41, out)
    assert.ok(out.endsWith('…'))
    assert.ok(!out.includes('alph…'), out)
  })

  it('cuts mid-word rather than returning a letter', () => {
    const out = richTextExcerpt('<p>' + 'x'.repeat(100) + ' end</p>', 20)
    assert.equal(out.length, 21)
    assert.ok(out.endsWith('…'))
  })

  it('collapses the line structure — a card is one block', () => {
    assert.ok(!richTextExcerpt(FORMATTED, 200).includes('\n'))
  })
})

describe('richTextFirstLine', () => {
  it('is the first non-empty line', () => {
    assert.equal(richTextFirstLine(FORMATTED), 'What to expect')
    assert.equal(richTextFirstLine(LEGACY), "Our monthly Women's Circle.")
  })

  it('returns null when there is nothing', () => {
    assert.equal(richTextFirstLine(null), null)
    assert.equal(richTextFirstLine('<p>  </p>'), null)
  })

  it('truncates a very long opening line', () => {
    const out = richTextFirstLine('<p>' + 'word '.repeat(50) + '</p>', 30)
    assert.ok(out !== null && out.length <= 31, String(out))
    assert.ok(out!.endsWith('…'))
  })
})

describe('isFormattedDescription', () => {
  it('recognises editor output', () => {
    assert.equal(isFormattedDescription('<p>Hi</p>'), true)
    assert.equal(isFormattedDescription('  <h2>Hi</h2>'), true)
  })

  it('does not mistake prose for markup', () => {
    assert.equal(isFormattedDescription(LEGACY), false)
    assert.equal(isFormattedDescription('<3 you all'), false)
    assert.equal(isFormattedDescription('3 < 5'), false)
    assert.equal(isFormattedDescription(null), false)
  })
})

/**
 * The editors are TipTap React components and this harness is
 * node:test with no DOM, so the wiring is asserted against the source.
 * Shape checks, not behaviour: they fail loudly if a surface goes back
 * to rendering a raw description, which is what a regression here
 * would look like.
 */
describe('the Gathering editor uses the shared rich-text editor', () => {
  const form = () => readFileSync(
    join(SRC, 'app', 'creator', 'spaces', '[slug]', 'events', 'EventForm.tsx'),
    'utf8',
  )

  it('no longer has a plain textarea for the description', () => {
    const source = form()
    assert.ok(
      /<AboutRichTextEditor[\s\S]{0,260}value=\{description\}/.test(source),
      'the description is not bound to the rich-text editor',
    )
    const descBlock = source.slice(
      source.indexOf('gathering-description'),
      source.indexOf('Gathering type'),
    )
    assert.ok(!/<textarea/.test(descBlock), 'the textarea is back')
  })

  it('offers italic and numbered lists', () => {
    assert.ok(/extendedMarks/.test(form()))
  })

  it('still sends the same field', () => {
    // The storage format changed, the API shape did not.
    assert.ok(/description: description \|\| null/.test(form()))
  })
})

describe('the Series editor uses it too', () => {
  it('is wired to the shared editor', () => {
    const source = readFileSync(
      join(SRC, 'app', 'creator-studio', 'gathering-series', '[seriesSlug]',
        'SeriesEditorClient.tsx'),
      'utf8',
    )
    assert.ok(/<AboutRichTextEditor[\s\S]{0,200}value=\{description\}/.test(source))
  })
})

describe('member-facing surfaces', () => {
  it('the Gathering page renders through the shared renderer', () => {
    const page = readFileSync(
      join(SRC, 'app', 'spaces', '[slug]', 'events', '[eventId]', 'page.tsx'),
      'utf8',
    )
    assert.ok(/<MarkdownBody content=\{event\.description\} \/>/.test(page))
    assert.ok(
      !/event\.description\.split\('\\n'\)/.test(page),
      'the page is splitting the raw description into paragraphs again',
    )
  })

  it('the Series page renders through it as well', () => {
    const page = readFileSync(
      join(SRC, 'app', 'spaces', '[slug]', 'gathering-series', '[series-slug]',
        'page.tsx'),
      'utf8',
    )
    assert.ok(/<MarkdownBody content=\{detail\.description\} \/>/.test(page))
  })

  it('calendar links carry plain text', () => {
    const page = readFileSync(
      join(SRC, 'app', 'spaces', '[slug]', 'events', '[eventId]', 'page.tsx'),
      'utf8',
    )
    assert.ok(/details: richTextToPlain\(event\.description\)/.test(page))
    assert.ok(/body: richTextToPlain\(event\.description\)/.test(page))
  })

  it('no card shows a raw description', () => {
    // The thing this whole conversion exists to prevent: a card
    // reading "<strong>Join us for an evening…".
    const cards: [string, string[]][] = [
      [join(SRC, 'components', 'spaces', 'EventCard.tsx'),
        ['richTextFirstLine(event.description)']],
      [join(SRC, 'components', 'spaces', 'MemberGatheringsGrid.tsx'),
        ['richTextToPlain(series.description)',
          'richTextToPlain(event.description)']],
      [join(SRC, 'app', 'creator', 'spaces', '[slug]', 'events', '[eventId]',
        'attendance', 'AttendanceDashboardClient.tsx'),
        ['richTextExcerpt(event.description, 180)']],
    ]
    for (const [path, expected] of cards) {
      const source = readFileSync(path, 'utf8')
      for (const fragment of expected) {
        assert.ok(source.includes(fragment), `${path} is missing ${fragment}`)
      }
      assert.ok(
        !/\{(?:event|series)\.description\}/.test(source),
        `${path} still renders the raw description`,
      )
    }
  })
})

describe('the shared renderer', () => {
  const body = () => readFileSync(
    join(SRC, 'components', 'ui', 'MarkdownBody.tsx'), 'utf8',
  )

  it('never uses dangerouslySetInnerHTML', () => {
    // The property that makes rendering creator HTML safe at all.
    //
    // Matched as the JSX prop, not as the word: the file's own header
    // says "No dangerouslySetInnerHTML", and a bare substring check
    // failed on the sentence promising the thing it was checking for.
    assert.ok(
      !/dangerouslySetInnerHTML\s*=/.test(body()),
      'MarkdownBody now sets raw HTML',
    )
  })

  it('only follows http(s) links', () => {
    assert.ok(/\/\^https\?:\\\/\\\/\/i\.test\(h\)/.test(body()))
  })

  it('renders an ordered list as ordered', () => {
    // It used to collect <ol> as a 'ul' and draw bullets, losing the
    // numbering an author had chosen.
    const source = body()
    assert.ok(/b\.tag === 'ol'/.test(source))
    assert.ok(/<ol key=\{k\}/.test(source))
    assert.ok(/tag: tag as 'ul' \| 'ol'/.test(source))
  })

  it('keeps pasted bold and italic, and line breaks', () => {
    const source = body()
    assert.ok(/strong\|b/.test(source), '<b> is dropped again')
    assert.ok(/em\|i/.test(source), '<i> is dropped again')
    assert.ok(/<br key=\{k\} \/>/.test(source), '<br> is dropped again')
  })
})

describe('the editor keeps the Collective About toolbar unchanged', () => {
  it('italic and numbered lists are opt-in', () => {
    // Adding buttons to the About page toolbar is a separate decision.
    const source = readFileSync(
      join(SRC, 'components', 'ui', 'AboutRichTextEditor.tsx'), 'utf8',
    )
    assert.ok(/extendedMarks = false/.test(source), 'they are on by default')
    assert.ok(/\{extendedMarks && \([\s\S]{0,400}toggleItalic/.test(source))
    assert.ok(/\{extendedMarks && \([\s\S]{0,400}toggleOrderedList/.test(source))
  })

  it('the Collective settings form does not pass them', () => {
    const settings = readFileSync(
      join(SRC, 'app', 'creator-studio', 'settings', 'CollectiveSettingsForm.tsx'),
      'utf8',
    )
    const editor = settings.slice(settings.indexOf('<AboutRichTextEditor'))
    const tag = editor.slice(0, editor.indexOf('/>'))
    assert.ok(!/extendedMarks/.test(tag), tag)
  })
})
