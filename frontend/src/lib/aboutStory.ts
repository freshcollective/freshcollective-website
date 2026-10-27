/**
 * "Why Fresh Collective exists" — the approved story, as data.
 *
 * Kept out of the page component for the same reason the FAQ copy is:
 * it is approved, first-person writing with a deliberate rhythm, and a
 * test can assert it survived intact. The page decides how it looks;
 * this decides what it says.
 *
 * Two things here are load-bearing and easy to lose in an edit:
 *
 *   * **The grouping.** Sentences developing one thought sit in one
 *     paragraph; a handful of short lines stand alone because the
 *     pause is the point — "And that was it.", "So I built a place
 *     that could hold it all." Splitting every sentence out again
 *     would make a short story look like a long one, and merging the
 *     standalone beats in would flatten the voice. The wording is
 *     untouched either way: regrouping moved paragraph boundaries and
 *     changed no words.
 *   * **The March 2026 turning point.** It is the hinge of the whole
 *     piece — the walk, the friend, the reminder — and it has to stay
 *     easy to follow.
 *
 * Australian spelling throughout.
 */

export interface AboutParagraph {
  text: string
  /**
   * ``turning-point`` is the one line the page lifts out of the body
   * copy: "A world of many Collectives, rather than just mine." It is
   * where the story turns, and it is emphasised rather than shouted.
   */
  emphasis?: 'turning-point'
}

export interface AboutSection {
  id: string
  heading: string
  paragraphs: readonly AboutParagraph[]
}

/** Sits above the first heading, in a slightly larger body style. */
export const ABOUT_INTRO =
  'Hi, I’m Linds. I built Fresh Collective, and I’m also one of the '
  + 'creators here.'

export const ABOUT_SECTIONS: readonly AboutSection[] = [
  {
    id: 'a-gap-i-kept-falling-into',
    heading: 'It started with a gap I kept falling into',
    paragraphs: [
      { text:
        'For years, I ran communities the way most of us do. A Facebook '
        + 'group, then a community platform. People joined, and eventually '
        + 'the conversation thinned out. You missed things. Engagement '
        + 'became something I had to keep generating.' },
      { text:
        'After live sessions, it was even starker. You’d share something '
        + 'real with a room full of people, then never speak to most of '
        + 'them again, unless you happened to turn up at the same event.' },
      { text:
        'The connection was real. There just wasn’t anywhere for it to '
        + 'continue.' },
    ],
  },
  {
    id: 'doing-it-on-my-own',
    heading: 'And I was doing it all on my own',
    paragraphs: [
      { text:
        'I had websites, course platforms, groups, a bit of everything. '
        + 'But in the end, it was always just me. Building, posting, '
        + 'marketing, trying to keep everything moving. No real connection '
        + 'with other creators. No collaborating. Just a lot of quiet '
        + 'effort.' },
      { text:
        'It was lonely. And I knew I wasn’t the only one feeling it.' },
    ],
  },
  {
    id: 'the-idea-i-kept-coming-back-to',
    heading: 'The idea I kept coming back to',
    paragraphs: [
      { text:
        'For years, I’d talked with a good friend and fellow coach about '
        + 'creating a place where people like us could come together and '
        + 'share our different areas of expertise. Instead of each of us '
        + 'working in our own little silo, we’d have one place filled with '
        + 'all our different kinds of wisdom, experiences and ideas. '
        + 'Somewhere people could discover things they might never have '
        + 'gone looking for.' },
      { text:
        'And someone would be there to bring it all together.' },
      { text:
        'But when I first started Fresh Collective in 2024, I went small '
        + 'instead of following that dream. Just me, my own courses and '
        + 'teachings. Again. It never quite felt right. Everything depended '
        + 'on me, and it couldn’t reach as far as I wanted it to.' },
      { text:
        'Then, in March 2026, that same friend and I were out walking, '
        + 'talking about business, coaching and leadership. I was going on '
        + '(and on!) about how much more we could do if we collaborated '
        + 'with other people. She stopped me and reminded me of the dream '
        + 'I’d been talking about all those years before.' },
      { text:
        'And that was it. Fresh Collective got a makeover and became what '
        + 'I’d imagined in the first place.' },
      {
        text: 'A world of many Collectives, rather than just mine.',
        emphasis: 'turning-point',
      },
    ],
  },
  {
    id: 'why-it-looks-and-feels-this-way',
    heading: 'Why it looks and feels the way it does',
    paragraphs: [
      { text:
        'Making a room feel welcoming is much easier when you’re actually '
        + 'in it. It’s much harder online, especially in the spaces between '
        + 'live sessions.' },
      { text:
        'I wanted Fresh Collective to feel different. Somewhere beautiful '
        + 'and welcoming. Somewhere you feel like you belong when you '
        + 'arrive, rather than feeling like you’ve just logged into another '
        + 'app.' },
      { text:
        'One of the things I’m pretty handy at is systems and design, so '
        + 'Fresh Collective is me putting those skills to good use. '
        + 'Building something beautiful and practical that can help far '
        + 'more people than I ever could on my own.' },
      { text:
        'It’s also the home I needed myself. My own work spans movement, '
        + 'leadership and Human Design. I didn’t want to keep dividing '
        + 'those parts of myself across different platforms and '
        + 'communities. And I know I’m not the only creator whose interests '
        + 'and expertise don’t fit neatly into one box.' },
      { text:
        'So I built a place that could hold it all.' },
    ],
  },
  {
    id: 'what-i-hope-you-find-here',
    heading: 'What I hope you find here',
    paragraphs: [
      { text:
        'Every creator has something to offer that someone else doesn’t. '
        + 'There’s wisdom here I know nothing about, just as there are '
        + 'things I can share that others can’t. That’s what makes the idea '
        + 'of Fresh Collective so exciting to me.' },
      { text:
        'Members can discover all sorts of experiences, ideas and '
        + 'perspectives in one place. They might arrive for one thing and '
        + 'discover something entirely unexpected along the way.' },
      { text:
        'And if you’re a creator, I hope Fresh Collective feels like '
        + 'somewhere you want to grow your community. Somewhere you feel '
        + 'welcome, supported and not quite so alone anymore.' },
      { text:
        'That’s also why I created the World Builders Collective, just '
        + 'for Fresh Collective creators. A place to learn from one '
        + 'another, share ideas, ask questions and, hopefully, find '
        + 'opportunities to collaborate along the way.' },
      { text:
        'Because I don’t think any of us needs to build everything on our '
        + 'own.' },
    ],
  },
]

/**
 * The bigger vision, set between the story and the invitation.
 *
 * A typographic moment, not a banner — the brief was explicit that it
 * should complement the story rather than interrupt it.
 */
export const ABOUT_VISION =
  'A world where people can discover themselves through discovering '
  + 'each other.'

/**
 * The closing invitation and sign-off.
 *
 * These two lines close the final section in the approved draft. They
 * are rendered in the closing block beside the portrait instead,
 * because that is where the brief asked the invitation, the signature
 * and the photograph to come together. The words are unchanged; only
 * where they sit on the page differs.
 */
export const ABOUT_INVITATION = 'Please come in and have a look around.'
export const ABOUT_SIGNATURE = 'Linds'

/**
 * The two photographs, and where they live.
 *
 * Both are static files under ``frontend/public/about/``, served by
 * ``next/image`` — the same arrangement as ``public/home/`` and the
 * homepage hero. Nothing new was added to handle them.
 *
 *   fig-tree-hero.jpg      5184 × 3888 (4:3)  — the camera original
 *   willow-portrait.webp   1135 ×  909 (5:4)
 *
 * Renamed on the way in only so the filenames say what they are.
 * The bytes are the supplied files exactly — copied, not re-encoded,
 * not resized, not cropped on disk, not graded. Both frames on the
 * page are built around these two ratios rather than the other way
 * round, so neither photograph is cut to fit a layout.
 *
 * Two different formats because each is the best source available,
 * not because of a convention. The hero is the untouched 20-megapixel
 * camera file; ``next/image`` downsizes it per breakpoint and serves
 * WebP, so the 4.5 MB on disk never reaches a browser and the extra
 * pixels are there for high-density screens. The willow portrait only
 * exists at 1135 × 909, which is already generous for a 352px frame.
 *
 * Alt text is descriptive rather than decorative, because on this
 * page the photographs are part of what is being said.
 */
/**
 * A minute-long look inside, offered under the two buttons.
 *
 * A link, not an embed: a player in the closing block would be a
 * second photograph-sized object competing with the willow portrait,
 * and would load a third-party frame onto a page that currently
 * loads none.
 */
export const ABOUT_VIDEO_LABEL = 'Or see inside in a minute →'
export const ABOUT_VIDEO_URL =
  'https://youtu.be/MTXKOxzcl6I?si=rJWftUtovKTXpJ2Q'

export const ABOUT_IMAGES = {
  hero: {
    src: '/about/fig-tree-hero.jpg',
    alt:
      'Linds, barefoot, balancing along the broad surface roots of a large '
      + 'fig tree in a park.',
  },
  portrait: {
    src: '/about/willow-portrait.webp',
    alt: 'Linds, smiling, in front of a green willow.',
  },
} as const

/**
 * Photo credit.
 *
 * Both photographs are from the same shoot — the EXIF agrees on the
 * camera body, the lens and the morning, 36 minutes apart — so one
 * credit covers the page rather than a line under each.
 *
 * It has to live in the markup rather than in the files. The portrait
 * arrived with ``Copyright: Narelle Kate Photography`` embedded and
 * the hero, being the unedited camera JPEG, never carried the field
 * at all; but neither matters to a reader, because ``next/image``
 * strips metadata from every derivative it serves. An on-page line is
 * the only acknowledgement anyone actually sees.
 */
export const ABOUT_PHOTOGRAPHER = 'Narelle Kate Photography'
export const ABOUT_PHOTOGRAPHER_URL =
  'https://narellekatephotography.mypixieset.com/'

/** Everything before the photographer's name. The name is a link, so
 *  the line is rendered in two pieces rather than one string. */
export const ABOUT_PHOTO_CREDIT_PREFIX = 'Photographs by '

/** The whole line, for tests and anywhere it is needed unsplit. */
export const ABOUT_PHOTO_CREDIT = ABOUT_PHOTO_CREDIT_PREFIX + ABOUT_PHOTOGRAPHER

export const ABOUT_TITLE = 'Why Fresh Collective exists'

/**
 * The title, broken on purpose.
 *
 * The break lands after "Fresh" rather than before it, and that is
 * what lets the title be big.
 *
 * Keeping "Fresh Collective" whole makes it the longest line, and a
 * line that long only fits the column beside the photograph at about
 * 64px. Breaking after "Fresh" makes "Collective" the longest line —
 * barely half the width — so the same column carries 88px, and the
 * block can sit further right, which in turn gives the gradient room
 * to fall off gently instead of ending in a visible edge.
 *
 * The breaks are data rather than markup so the accessible name stays
 * the one sentence in ``ABOUT_TITLE``: the spans carry no semantics
 * of their own, so a screen reader reads it straight through.
 */
export interface AboutTitleLine {
  text: string
  /** Rendered in the hero gold. At most one line carries this. */
  gold?: boolean
}

export const ABOUT_TITLE_LINES: readonly AboutTitleLine[] = [
  { text: 'Why Fresh' },
  // Gold, the way the homepage hero golds "belonging." — one word
  // lifted out of a white headline, never a whole line.
  { text: 'Collective', gold: true },
  { text: 'exists' },
]
