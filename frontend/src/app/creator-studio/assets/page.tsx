import { permanentRedirect } from 'next/navigation'

/**
 * Legacy Media Library route. Everything files-related now lives in the
 * unified Library alongside external links. A permanent redirect keeps
 * bookmarks + in-editor "Open Assets →" links working after the switch.
 */
export default function LegacyAssetsRedirect() {
  permanentRedirect('/creator-studio/library')
}
