import type { PostSummary } from '@/types/platform'

/**
 * Every image on a Conversation post, in order.
 *
 * A post used to carry one image in `image_url`; it now carries a list
 * in `image_urls` and keeps the first of them in the old field. One
 * function applies the fallback so a post written before the change —
 * or a response from an fc-api that has not finished deploying — reads
 * as a one-image post everywhere, rather than in whichever surfaces
 * remembered to check.
 *
 * Mirrors `post_images()` in `app/community/routes.py`.
 */
export function postImages(
  post: Pick<PostSummary, 'image_url' | 'image_urls'>,
): string[] {
  const many = (post.image_urls ?? []).filter(Boolean)
  if (many.length > 0) return many
  return post.image_url ? [post.image_url] : []
}
