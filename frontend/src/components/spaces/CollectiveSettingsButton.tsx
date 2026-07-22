'use client'

import { useState } from 'react'
import CollectiveSettingsModal from '@/components/spaces/CollectiveSettingsModal'

interface Props {
  spaceSlug: string
  spaceName: string
}

export default function CollectiveSettingsButton({ spaceSlug, spaceName }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <>
      {open && (
        <CollectiveSettingsModal
          spaceSlug={spaceSlug}
          spaceName={spaceName}
          onClose={() => setOpen(false)}
        />
      )}
      <button
        onClick={() => setOpen(true)}
        className="block w-full rounded-xl border border-slate-200 px-4 py-2 text-center text-[13px] font-medium text-black transition-colors hover:bg-slate-50"
      >
        Settings
      </button>
    </>
  )
}
