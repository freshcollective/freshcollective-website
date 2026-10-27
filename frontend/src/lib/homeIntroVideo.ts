/**
 * The one-minute introduction video on the homepage.
 *
 * Copy, identifiers and the embed URL live here rather than in the
 * component for the same reason the About story and the creator FAQ
 * do: a test can hold them still. The component decides how the
 * section looks; this decides what it plays and what it says.
 *
 * Three decisions are load-bearing and easy to undo by accident:
 *
 *   * **Nothing of YouTube's is fetched until the visitor asks for
 *     it.** The idle state is a self-hosted poster and a button. No
 *     iframe, no script, no thumbnail request — so no third party
 *     learns that this page was opened. ``POSTER_SRC`` must stay a
 *     local path for that to remain true.
 *   * **The privacy-enhanced host.** ``www.youtube-nocookie.com``
 *     rather than ``www.youtube.com``. It is already a first-class
 *     entry in ``EMBED_PROVIDERS``, so CSP ``frame-src`` allows it
 *     with no header change.
 *   * **``autoplay=1`` appears only on the activated URL.** The page
 *     never loads a player that could start by itself; the parameter
 *     exists so that the click which inserts the player is also the
 *     click that starts it, rather than asking for a second one.
 */

/** YouTube's id for the tour. The watch URL is derived from it. */
export const HOME_INTRO_VIDEO_ID = 'MTXKOxzcl6I'

export const HOME_INTRO_VIDEO_HEADING = 'Take a look inside Fresh Collective'

export const HOME_INTRO_VIDEO_BODY =
  'One minute to see what we’ve been building.'

/**
 * The iframe's accessible name, and the button's.
 *
 * "Video" is in it on purpose: a screen-reader user meeting the
 * button needs to know what activating it produces, and a frame
 * announced only by its title should say what kind of thing it is.
 */
export const HOME_INTRO_VIDEO_TITLE =
  'Take a look inside Fresh Collective — a one-minute video tour'

export const HOME_INTRO_VIDEO_PLAY_LABEL =
  'Play the video: Take a look inside Fresh Collective, one minute'

/**
 * The poster frame, served from our own origin.
 *
 * It is YouTube's own title card for this video, saved into
 * ``public/home/`` at its native 1280 × 720 — the same arrangement as
 * ``public/about/``. Fetching it from ``i.ytimg.com`` instead would
 * have meant widening CSP ``img-src`` for every page in the app to
 * show one thumbnail, and would have told YouTube about every visitor
 * who merely scrolled past. A 157 KB file is the cheaper answer.
 */
export const HOME_INTRO_VIDEO_POSTER_SRC = '/home/intro-video-poster.jpg'

export const HOME_INTRO_VIDEO_POSTER_ALT =
  'A cluster of small islands at sunset, titled “Fresh Collective — '
  + 'A Look Inside”.'

/** Native size of the poster file, so the frame can reserve its box. */
export const HOME_INTRO_VIDEO_POSTER_SIZE = { width: 1280, height: 720 }

/** Where the video lives, for anyone who wants it outside the page. */
export const HOME_INTRO_VIDEO_WATCH_URL =
  `https://youtu.be/${HOME_INTRO_VIDEO_ID}`

const EMBED_ORIGIN = 'https://www.youtube-nocookie.com'

/**
 * Build the player URL.
 *
 * ``rel=0`` keeps the end-screen suggestions to this channel rather
 * than opening the whole of YouTube on top of the homepage;
 * ``modestbranding=1`` quiets the chrome; ``playsinline=1`` stops iOS
 * taking the video fullscreen on its own, which would throw a visitor
 * out of the page the section exists to keep them in.
 *
 * @param autoplay pass true only in response to a real click.
 */
export function homeIntroVideoEmbedUrl({ autoplay = false } = {}): string {
  const params = new URLSearchParams({
    rel: '0',
    modestbranding: '1',
    playsinline: '1',
  })
  if (autoplay) params.set('autoplay', '1')
  return `${EMBED_ORIGIN}/embed/${HOME_INTRO_VIDEO_ID}?${params.toString()}`
}
