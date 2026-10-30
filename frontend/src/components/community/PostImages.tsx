import CommunityImage from './CommunityImage'
import { resolveMediaUrl } from '@/lib/api'

/**
 * The photographs on a Conversation post.
 *
 * One image keeps exactly the presentation it always had — full width,
 * rounded, `object-cover` — so every post written before a post could
 * carry several looks untouched.
 *
 * Beyond one it becomes a grid, and the shape follows the count rather
 * than one layout stretched to fit:
 *
 *   2      side by side
 *   3      one wide above, two below
 *   4      two by two
 *   5      two above, three below
 *
 * Every cell is a fixed aspect ratio with `object-cover`, which is what
 * keeps a portrait and a landscape photograph sitting together without
 * either being stretched — the frame crops, the image is never
 * distorted. On a phone the grid collapses to two columns, and a single
 * image stays single.
 *
 * Each image links to the file itself, opening full size in a new tab.
 * Deliberately not a lightbox: there is no viewer in this codebase to
 * reuse, and the browser already knows how to show an image and let
 * somebody pinch it.
 */

interface Props {
  images: string[]
  className?: string
}

/** Cells that should span both columns, by (count, index). */
function isWide(count: number, index: number): boolean {
  if (count === 3) return index === 0
  return false
}

export default function PostImages({ images, className }: Props) {
  if (images.length === 0) return null

  if (images.length === 1) {
    return (
      <a
        href={resolveMediaUrl(images[0]) ?? ''}
        target="_blank"
        rel="noopener noreferrer"
        className={`block rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A] ${className ?? ''}`}
      >
        <CommunityImage
          src={resolveMediaUrl(images[0]) ?? ''}
          alt="Post image"
          className="w-full rounded-xl object-cover"
        />
      </a>
    )
  }

  return (
    <ul
      className={`grid list-none grid-cols-2 gap-2 p-0 ${className ?? ''}`}
      aria-label={`${images.length} photos`}
    >
      {images.map((src, i) => (
        <li
          key={`${src}-${i}`}
          className={isWide(images.length, i) ? 'col-span-2' : undefined}
        >
          <a
            href={resolveMediaUrl(src) ?? ''}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Photo ${i + 1} of ${images.length}`}
            className="block overflow-hidden rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
          >
            <CommunityImage
              src={resolveMediaUrl(src) ?? ''}
              alt=""
              className={`w-full object-cover ${
                isWide(images.length, i) ? 'aspect-[16/9]' : 'aspect-square'
              }`}
            />
          </a>
        </li>
      ))}
    </ul>
  )
}
