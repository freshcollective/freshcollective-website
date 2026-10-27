/**
 * "Rather see it with a person?" — the offer of a 15-minute
 * show-around, for people who would rather be walked through Fresh
 * Collective than read about it or watch it.
 *
 * It appears in two places (under the homepage video, and under the
 * For Creators FAQ) and must read identically in both, so the copy
 * and the destination live here rather than in either page. One
 * address, one subject line, one set of words.
 *
 * It is an invitation to send an email and nothing more. No booking
 * tool, no calendar, no scheduling link — the time gets arranged in
 * the reply.
 */

import { CONTACT_INFO_EMAIL } from './contact.ts'

/** The quiet question. Deliberately not a heading. */
export const SHOW_AROUND_QUESTION = 'Rather see it with a person?'

/** The action, rendered as a text link rather than a button: the
 *  video is the feature of its section and the plans are the action
 *  on For Creators, and a second button would compete with both. */
export const SHOW_AROUND_LINK_LABEL =
  'Email Lindsey to arrange a 15-minute show-around →'

/**
 * The subject line, prefilled.
 *
 * A plain hyphen rather than an en dash: this travels through a
 * ``mailto:`` URL into whichever mail client the visitor has, and the
 * hyphen is the character that survives that trip everywhere.
 */
export const SHOW_AROUND_SUBJECT = 'Fresh Collective - 15-minute show-around'

/** Where it goes. The address comes from ``lib/contact`` so this
 *  cannot drift from the one the footer and the FAQ already use. */
export const SHOW_AROUND_MAILTO =
  `mailto:${CONTACT_INFO_EMAIL}`
  + `?subject=${encodeURIComponent(SHOW_AROUND_SUBJECT)}`
