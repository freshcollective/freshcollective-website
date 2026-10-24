/**
 * Fresh Collective's contact addresses.
 *
 * All three reach the same mailbox; the distinction is what a reader
 * should expect to be read as, not where it lands. Named here so three
 * surfaces cannot drift apart on a typo, and so a test can assert that
 * each surface uses the right one.
 *
 *   info@     general, membership and creator enquiries — the footer,
 *             where a visitor who is not yet a member arrives.
 *   support@  account and purchase problems — the places where someone
 *             is already stuck.
 *   hello@    friendly correspondence. Deliberately not surfaced: the
 *             footer slot is better served by ``info@`` and the stuck
 *             moments by ``support@``, and a third address competing
 *             for the same few touchpoints helps nobody.
 */

/** General, membership and creator enquiries. */
export const CONTACT_INFO_EMAIL = 'info@freshcollective.au'

/** Account issues, purchase assistance, technical problems. */
export const CONTACT_SUPPORT_EMAIL = 'support@freshcollective.au'
