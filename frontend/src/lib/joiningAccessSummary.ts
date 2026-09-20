import type { JoiningOption } from '@/types/platform'

/**
 * What a joining purchase actually brings.
 *
 * The Access card was written for the older shape — free membership,
 * with content inside sold separately — and said so in two labelled
 * halves: INCLUDED and PAID SEPARATELY. On a purchase-required
 * Collective that is not merely stale, it is wrong in a way that
 * costs money: it tells a visitor they must buy their way in and
 * *then* buy the term, when the one purchase does both. EMBODY read
 * "Membership comes with a purchase / PAID SEPARATELY: EMBODY term
 * access and in-person session bookings are paid separately" —
 * describing a second payment that does not exist.
 *
 * So the summary is derived from the nominated options' own
 * ``PaymentOptionGrant`` rows, which are the same rows fulfilment
 * reads. Whatever a purchase grants is what the page claims it
 * grants, with no second description to drift out of step.
 *
 * ``included_access_summary`` still has a job — community content
 * that comes with membership rather than with any grant — but it is
 * supporting copy beneath the derived list, never the authority.
 * ``paid_content_summary`` is not shown at all when everything it
 * describes is already granted by the doors.
 */

/** Oxford-free list: "A, B and C". */
export function listPhrase(items: string[]): string {
  const clean = items.map((s) => s.trim()).filter(Boolean)
  if (clean.length === 0) return ''
  if (clean.length === 1) return clean[0]
  return `${clean.slice(0, -1).join(', ')} and ${clean[clean.length - 1]}`
}

export interface JoiningAccessSummary {
  /** Everything every door grants, de-duplicated, in first-seen order. */
  includedTitles: string[]
  /** The sentence under "Your purchase includes". */
  sentence: string
  /** Present when the doors differ in session allowance, so the page
   *  never implies one flat entitlement across tiers. */
  allowanceNote: string | null
  /** True when the doors grant different things, so the reader knows
   *  to compare them rather than assume they are interchangeable. */
  varies: boolean
}

export function buildJoiningAccessSummary(
  collectiveName: string,
  options: JoiningOption[],
): JoiningAccessSummary | null {
  if (options.length === 0) return null

  const seen = new Set<string>()
  const includedTitles: string[] = []
  for (const option of options) {
    for (const title of option.included_titles ?? []) {
      const t = title.trim()
      if (t && !seen.has(t)) {
        seen.add(t)
        includedTitles.push(t)
      }
    }
  }

  // Do the doors grant the same things? If they differ, the page must
  // not describe one of them as though it were all of them.
  const signatures = new Set(
    options.map((o) => [...(o.included_titles ?? [])].map((t) => t.trim()).sort().join('|')),
  )
  const varies = signatures.size > 1

  const membership = `membership of ${collectiveName.trim()}`
  const sentence = includedTitles.length === 0
    ? `Your purchase brings you into ${collectiveName.trim()}.`
    : varies
      ? `Your purchase brings you ${membership}, plus access to ${listPhrase(includedTitles)} — what each option includes is shown with it below.`
      : `Your purchase brings you ${membership}, plus access to ${listPhrase(includedTitles)}.`

  // Session allowance, where the doors carry one and disagree about
  // it. "1 to 3 sessions a week" is true of the set; claiming any
  // single number would be true of only one option.
  const perWeek = options
    .map((o) => o.sessions_per_week)
    .filter((n): n is number => typeof n === 'number' && n > 0)
  let allowanceNote: string | null = null
  if (perWeek.length > 0) {
    const min = Math.min(...perWeek)
    const max = Math.max(...perWeek)
    allowanceNote = min === max
      ? `Includes ${min} session${min === 1 ? '' : 's'} a week.`
      : `Session bookings range from ${min} to ${max} a week, depending on the option you choose.`
  }

  return { includedTitles, sentence, allowanceNote, varies }
}

/**
 * Paid content that the joining purchase does **not** cover.
 *
 * A "paid separately" line is honest only when something really is
 * sold on top. When every paid Pathway is already granted by the
 * doors — EMBODY's case — showing one invents a second purchase.
 *
 * Compared by title because that is what both sides carry publicly;
 * a Pathway the doors grant appears in ``includedTitles`` verbatim,
 * since both come from the same rows.
 */
export function additionalPaidTitles(
  paidPathwayTitles: string[],
  includedTitles: string[],
): string[] {
  const included = new Set(includedTitles.map((t) => t.trim().toLowerCase()))
  return paidPathwayTitles
    .map((t) => t.trim())
    .filter((t) => t && !included.has(t.toLowerCase()))
}
