import { permanentRedirect } from 'next/navigation'

/**
 * Legacy Resources route. Resources have folded into the unified
 * Library — one creator surface for files (uploads) and links.
 * Permanent redirect preserves bookmarks and any in-editor
 * "Open Resources →" links.
 */
export default function LegacyResourcesRedirect() {
  permanentRedirect('/creator-studio/library')
}
