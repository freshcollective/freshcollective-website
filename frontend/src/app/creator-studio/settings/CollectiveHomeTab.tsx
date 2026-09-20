'use client'

import { useCallback, useState } from 'react'

import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveHomeForm from './CollectiveHomeForm'
import GuidancePanelForm from './GuidancePanelForm'
import MemberDirectoryForm from './MemberDirectoryForm'

/**
 * The Collective Home settings tab, in the order a member meets it.
 *
 * The member directory comes first because it decides whether a whole
 * doorway exists: with it closed, the Home tile editor below has no
 * Members row to show, and without the switch directly above it there
 * is nothing on screen to explain the absence.
 *
 * Sidebar guidance comes last and says where it actually appears. It
 * does not appear on the Collective Home at all — it is the Important
 * panel beside Conversations, Gatherings and Pathways — which is what
 * made the old "Member Hub" grouping misleading once the Home shipped.
 */

interface Props {
  space: CreatorSpaceDetail
}

export default function CollectiveHomeTab({ space }: Props) {
  // Bumped when the directory setting saves, so the Home editor
  // refetches the tile list the server says is permitted. A creator
  // should not have to reload the page to see the Members tile appear.
  const [directoryVersion, setDirectoryVersion] = useState(0)
  const onDirectorySaved = useCallback(() => {
    setDirectoryVersion((v) => v + 1)
  }, [])

  return (
    <div className="space-y-10">
      <MemberDirectoryForm space={space} onSaved={onDirectorySaved} />
      <CollectiveHomeForm slug={space.slug} reloadKey={directoryVersion} />
      <GuidancePanelForm space={space} />
    </div>
  )
}
