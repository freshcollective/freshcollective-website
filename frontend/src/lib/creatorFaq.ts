/**
 * The /for-creators FAQ — content, and the structured data built from it.
 *
 * The copy lives here rather than inside the page component for one
 * reason that matters: the FAQPage JSON-LD has to say the same thing as
 * the visible answers. Google treats a mismatch as cloaking, and the
 * usual way a mismatch happens is somebody editing the visible copy and
 * not the schema beside it. Here the schema is *derived* from the same
 * strings the page renders, so the two cannot drift.
 *
 * Every factual claim in these answers was checked against the
 * implementation before publication, not against documentation. The
 * ones worth recording, because each was wrong in an earlier draft:
 *
 *   * **Payouts.** Weekly, anchored Monday, set on the creator's Stripe
 *     connected account at onboarding (``stripe_connect_accounts.
 *     WEEKLY_PAYOUT_SCHEDULE``). Creators *do* get a Stripe account — a
 *     Connect ``recipient`` account with an Express dashboard — and
 *     Stripe collects their bank details, not Fresh Collective: the
 *     account sets ``requirements_collector='stripe'``, which is why FC
 *     cannot write them.
 *   * **Processing costs.** Genuinely absorbed out of the commission —
 *     the creator receives ``net_creator_amount_cents``, which the
 *     transfer sweeper computes without reference to the processing fee.
 *   * **Downgrades.** Only the active-Collective limit is a
 *     precondition; exceeding it is a 409. Paid offerings are *not* —
 *     they are left in place and simply stop selling, because
 *     ``guard_paid_offers_enabled`` runs on authoring paths and paid
 *     checkout answers 403 once the plan forbids them.
 *   * **Cancellation.** Nothing is deleted and there is no retention
 *     window. ``handle_subscription_deleted`` sets ``cancelled``, leaves
 *     members and content untouched, and deliberately does not reassign
 *     the creator to Community.
 *   * **Leaving a Collective.** A member keeps what they bought
 *     separately — downloads, individual Pathways, paid Gatherings — and
 *     leaving cancels no subscription or payment plan. Both are in the
 *     Membership Terms and both are implemented.
 *
 * Percentages and monthly prices are stated in the copy as approved.
 * ``creatorFaq.test.ts`` asserts they still agree with ``PUBLIC_PLANS``,
 * so a plan change cannot leave this page quoting a stale figure.
 */

export interface FeeRow {
  /** What the creator sells. */
  sale: string
  /** What they receive on the Creator plan. */
  creator: string
  /** What they receive on Creator Portfolio. */
  portfolio: string
}

/**
 * The worked examples. Each figure is the sale less the plan's
 * commission and nothing else, which is what the ledger computes:
 * 49 × 0.92 = 45.08, 49 × 0.96 = 47.04, 300 × 0.92 = 276,
 * 300 × 0.96 = 288.
 */
export const FEE_ROWS: readonly FeeRow[] = [
  { sale: 'A $49 workshop', creator: '$45.08', portfolio: '$47.04' },
  { sale: 'A $300 term', creator: '$276.00', portfolio: '$288.00' },
]

export const FEE_TABLE_HEADINGS = {
  sale: 'You sell',
  creator: 'On Creator (8%) you receive',
  portfolio: 'On Creator Portfolio (4%) you receive',
} as const

export interface CreatorFaqItem {
  /** Stable id, used for the accordion and for anchoring. */
  id: string
  question: string
  /** Rendered in order as paragraphs. */
  paragraphs: readonly string[]
  /** When true, the fee table renders after the first paragraph. */
  feeTable?: boolean
  /**
   * JSON-LD answer, when it cannot simply be the paragraphs joined.
   *
   * Only the fee question needs one: its visible answer ends with
   * "Here's what that looks like:" and a table, and a structured-data
   * answer that trailed off mid-sentence would be worse than useless.
   * The example is stated in prose instead.
   */
  schemaAnswer?: string
}

export const CREATOR_FAQ: readonly CreatorFaqItem[] = [
  {
    id: 'how-do-i-get-paid',
    question: 'How do I get paid?',
    paragraphs: [
      'Payments are processed securely through Stripe, and your earnings '
      + 'are paid out to you weekly, in Australian dollars. You’ll set '
      + 'up payouts once through Stripe, which collects your bank details '
      + 'securely. You can also see your payments and payouts through your '
      + 'own Stripe dashboard.',
    ],
  },
  {
    id: 'platform-fee',
    question: 'What does the platform fee actually cost me?',
    paragraphs: [
      'It’s a percentage of each paid sale, worked out on the full '
      + 'sale price: 8% on the Creator plan and 4% on Creator Portfolio. '
      + 'We cover the standard card processing costs, so nothing else '
      + 'comes out. Here’s what that looks like:',
      'Your monthly plan fee ($19 or $79) is separate.',
    ],
    feeTable: true,
    schemaAnswer:
      'It’s a percentage of each paid sale, worked out on the full '
      + 'sale price: 8% on the Creator plan and 4% on Creator Portfolio. '
      + 'We cover the standard card processing costs, so nothing else '
      + 'comes out. For example, on a $300 sale you receive $276 on '
      + 'Creator or $288 on Creator Portfolio. Your monthly plan fee '
      + '($19 or $79) is separate.',
  },
  {
    id: 'start-for-free',
    question: 'Can I start for free?',
    paragraphs: [
      'Yes. The Community plan is free. You can build a Collective with '
      + 'Pathways, Gatherings and free offerings for up to 100 members. '
      + 'When you’re ready to charge for what you offer, move to the '
      + 'Creator plan.',
    ],
  },
  {
    id: 'change-or-cancel',
    question: 'Can I change or cancel my plan?',
    paragraphs: [
      'Yes. You can upgrade, downgrade or cancel your plan. Upgrades take '
      + 'effect straight away, while downgrades and cancellations take '
      + 'effect at the end of your current billing period.',
      'If you’re moving to a smaller plan, you’ll need to be '
      + 'within its Collective limit first. For example, the Creator plan '
      + 'allows one Collective rather than five, so you’d need to '
      + 'archive any extras before downgrading.',
      'Other features become unavailable when the downgrade takes effect. '
      + 'The free Community plan doesn’t include paid offerings, so '
      + 'your existing paid offerings will no longer be available for '
      + 'purchase.',
      'Cancelling your subscription doesn’t delete your Collective or '
      + 'your content. You can start a new plan whenever you’re ready.',
    ],
  },
  {
    id: 'who-owns-my-content',
    question: 'Who owns my content?',
    paragraphs: [
      'You do. Everything you create, from your Pathways and Resources to '
      + 'your recordings and branding, stays yours. When members buy '
      + 'access, they’re buying access, not ownership of your work.',
    ],
  },
  {
    id: 'bring-existing-people',
    question: 'How do I bring my existing people across?',
    paragraphs: [
      'Right now, you can add members to your Collective one at a time.',
    ],
  },
  {
    id: 'member-leaves',
    question: 'What happens if a member leaves?',
    paragraphs: [
      'If a member leaves your Collective, they lose access to content '
      + 'that’s included with their membership, but they keep anything '
      + 'they’ve purchased separately, including digital downloads, '
      + 'individual Pathways and Gatherings they’ve already paid for. '
      + 'Leaving a Collective doesn’t automatically cancel an existing '
      + 'subscription or payment plan.',
    ],
  },
]

/** The answer as structured data sees it. */
export function faqSchemaAnswer(item: CreatorFaqItem): string {
  return item.schemaAnswer ?? item.paragraphs.join(' ')
}

/**
 * schema.org FAQPage, built from the same copy the page renders.
 *
 * Returned as an object so the page can serialise it once; keeping the
 * shape here means a test can assert every visible question appears in
 * the structured data and that no answer carries markup.
 */
export function creatorFaqJsonLd(): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: CREATOR_FAQ.map((item) => ({
      '@type': 'Question',
      name: item.question,
      acceptedAnswer: {
        '@type': 'Answer',
        text: faqSchemaAnswer(item),
      },
    })),
  }
}
