'use client'

/**
 * DraggableBlockList — a document-shaped wrapper around ``BlockRow``.
 *
 * The pathway editor's job is to read like one continuous document
 * rather than a stack of admin cards. This list:
 *   - Renders every block with HTML5 native drag-and-drop reordering.
 *   - Places a persistent hairline between blocks with a single
 *     ``+ Add content`` control that opens the block-type menu directly
 *     at the insertion point — no intermediate "Add block" panel.
 *   - Places a single ``+ Add content`` control after the final block.
 *
 * Both affordances open the same lightweight ``BlockTypeMenu`` — one
 * click, one menu, no duplicate prompts.
 */

import { useEffect, useRef, useState } from 'react'
import { BlockRow, BlockTypeMenu } from './BlockEditorShared'
import type { StepBlock, StepBlockType, CreatorMediaAsset, CreatorResource } from '@/types/platform'


interface Props {
  blocks: StepBlock[]
  assets: CreatorMediaAsset[]
  resources: CreatorResource[]
  /** ID of the single currently-active editor. Only one block is ever
   *  open at a time; the parent StepBlockEditor lifts this state. */
  activeBlockId: string | null
  onActivateBlock: (id: string | null) => void
  onUpdate: (blockId: string, patch: Record<string, unknown>) => Promise<void>
  onDelete: (blockId: string) => Promise<void> | void
  onReorder: (nextOrderIds: string[]) => Promise<void> | void
  onInsertAt: (position: number, type: StepBlockType) => Promise<void> | void
  spaceSlug?: string
  onAssetUploaded?: (asset: CreatorMediaAsset) => void
}


export default function DraggableBlockList({
  blocks, assets, resources, activeBlockId, onActivateBlock,
  onUpdate, onDelete, onReorder, onInsertAt,
  spaceSlug, onAssetUploaded,
}: Props) {
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)
  /** Position at which the type menu is open, or ``null`` when closed. */
  const [insertOpenAt, setInsertOpenAt] = useState<number | null>(null)

  function handleDragStart(index: number, e: React.DragEvent) {
    setDragIndex(index)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
  }

  function handleDragOver(index: number, e: React.DragEvent) {
    if (dragIndex === null) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDropIndex(index)
  }

  function handleDragEnd() {
    setDragIndex(null)
    setDropIndex(null)
  }

  async function handleDrop(index: number, e: React.DragEvent) {
    e.preventDefault()
    const from = dragIndex
    setDragIndex(null)
    setDropIndex(null)
    if (from === null || from === index) return
    const next = blocks.slice()
    const [moved] = next.splice(from, 1)
    const insertAt = from < index ? index - 1 : index
    next.splice(insertAt, 0, moved)
    await onReorder(next.map((b) => b.id))
  }

  async function handlePickInsert(position: number, type: StepBlockType) {
    setInsertOpenAt(null)
    await onInsertAt(position, type)
  }

  return (
    <div>
      {blocks.map((block, i) => (
        <div key={block.id}>
          {dragIndex !== null && dropIndex === i && dragIndex !== i && (
            <div className="my-1 h-[2px] rounded" style={{ background: 'rgb(56,160,158)' }} />
          )}

          <InsertAffordance
            position={i}
            open={insertOpenAt === i}
            onOpen={() => setInsertOpenAt(i)}
            onClose={() => setInsertOpenAt(null)}
            onPick={(t) => handlePickInsert(i, t)}
          />

          {/*
            Native HTML5 drag lives ONLY on the handle, never on the
            row. When the whole row is ``draggable``, the browser
            interprets mousedown+mousemove inside a contenteditable
            descendant (the TipTap surface) as the start of a drag and
            not as a text selection, breaking caret placement and
            selection completely. Keeping ``draggable`` scoped to the
            handle keeps drag reorder functional while leaving the
            editor body free to receive real mouse input.
          */}
          <div
            onDragOver={(e) => handleDragOver(i, e)}
            onDrop={(e) => handleDrop(i, e)}
            className="group/block"
            style={{ opacity: dragIndex === i ? 0.45 : 1 }}
          >
            <BlockRow
              block={block}
              index={i}
              total={blocks.length}
              assets={assets}
              resources={resources}
              isActive={block.id === activeBlockId}
              onActivate={() => onActivateBlock(block.id)}
              onDeactivate={() => onActivateBlock(null)}
              onMoveUp={() => { /* replaced by drag */ }}
              onMoveDown={() => { /* replaced by drag */ }}
              onDelete={() => onDelete(block.id)}
              onUpdate={(patch) => onUpdate(block.id, patch)}
              spaceSlug={spaceSlug}
              onAssetUploaded={onAssetUploaded}
              hideMoveButtons
              dragHandle={
                <span
                  draggable
                  onDragStart={(e) => handleDragStart(i, e)}
                  onDragEnd={handleDragEnd}
                  className="flex h-7 w-5 cursor-grab select-none items-center justify-center rounded-md text-[14px] leading-none text-slate-300 transition-all hover:bg-slate-100 hover:text-slate-600 active:cursor-grabbing opacity-100 focus-within:opacity-100 sm:opacity-0 sm:group-hover/block:opacity-100 sm:group-hover/row:opacity-100"
                  title="Drag to reorder"
                  aria-label="Drag to reorder this block"
                  role="button"
                >
                  ⋮⋮
                </span>
              }
            />
          </div>
        </div>
      ))}

      <InsertAffordance
        position={blocks.length}
        open={insertOpenAt === blocks.length}
        onOpen={() => setInsertOpenAt(blocks.length)}
        onClose={() => setInsertOpenAt(null)}
        onPick={(t) => handlePickInsert(blocks.length, t)}
        trailing
      />
    </div>
  )
}


/**
 * A single insertion affordance.
 *
 * Between blocks: the row is invisible chrome by default — no
 * hairline, no visible pill — until the writer hovers the gap. A
 * quiet ``+`` fades in centred on the row. Once opened it stays
 * lit while the type menu is visible.
 *
 * Trailing (after the last block): a text-link-style ``+ Add
 * content`` affordance in teal. No dashed border, no admin chrome.
 */
function InsertAffordance({
  position, open, onOpen, onClose, onPick, trailing,
}: {
  position: number
  open: boolean
  onOpen: () => void
  onClose: () => void
  onPick: (type: StepBlockType) => void
  trailing?: boolean
}) {
  const ref = useRef<HTMLDivElement | null>(null)

  // Close the menu on outside click or Escape.
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (!ref.current) return
      if (!ref.current.contains(e.target as Node)) onClose()
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  return (
    <div ref={ref} className={`relative ${trailing ? 'mt-6' : ''}`}>
      {trailing ? (
        <div className="flex justify-start">
          <button
            type="button"
            onClick={onOpen}
            className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-[13.5px] font-medium transition-colors hover:bg-teal-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
            style={{ color: '#0f766e' }}
            title="Add content at the end"
            aria-label="Add content at the end"
          >
            <span aria-hidden="true" className="text-[16px] leading-none">+</span>
            Add content
          </button>
        </div>
      ) : (
        <div className="group/insert relative flex h-5 items-center justify-center">
          <button
            type="button"
            onClick={onOpen}
            className={`flex h-5 w-5 items-center justify-center rounded-full text-[14px] leading-none transition-opacity duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
              open ? 'opacity-100' : 'opacity-0 group-hover/insert:opacity-100'
            }`}
            style={{
              color: open ? '#0f766e' : '#94a3b8',
              background: open ? 'rgba(56,160,158,0.10)' : 'transparent',
            }}
            title={`Add content at position ${position + 1}`}
            aria-label="Add content here"
          >
            <span aria-hidden="true">+</span>
          </button>
        </div>
      )}

      {open && (
        <div
          className={`absolute z-30 mt-1 w-80 ${trailing ? 'left-0' : 'left-1/2 -translate-x-1/2'}`}
        >
          <BlockTypeMenu onSelect={(t) => onPick(t)} />
        </div>
      )}
    </div>
  )
}
