import {
  type ColumnsPayload,
  setCellImage,
} from './columnsBlock.ts'

/**
 * Adapter between a columns cell's image and ``ImageBlockFields``.
 *
 * ``ImageBlockFields`` is fully controlled and was written for an image
 * *block*, where the picture lives in four separate columns on the row
 * (``media_asset_id``, ``embed_url``, ``label``, ``caption``) plus an
 * ``altUnset`` flag the form keeps beside them. A columns cell keeps
 * all of that in one nested ``image`` object instead, so something has
 * to translate. This is that translation, kept out of the component so
 * it can be tested against the call sequences the real controls make.
 *
 * Those sequences are why this is not a one-line mapping. The controls
 * fire two callbacks per gesture, and in an order that a naive
 * translation gets wrong:
 *
 *   - Picking from the library calls ``onMediaAssetIdChange(id)`` and
 *     then ``onEmbedUrlChange('')``, to stop the two image sources
 *     conflicting. The second call must not undo the first.
 *
 *   - Unticking "decorative" calls ``onAltUnsetChange(true)`` and then
 *     ``onAltTextChange('')``. Writing that empty string through would
 *     put the cell straight back to decorative — the same bug that
 *     once locked the checkbox on for image blocks.
 *
 * Alt text keeps the block's three states, encoded in one nullable
 * field: ``null`` is "no decision recorded, inherit the asset title",
 * ``''`` is "deliberately decorative", and any other string is
 * explicit. ``altUnset`` is therefore not stored — it is exactly
 * ``alt === null``.
 */

/** The subset of a media asset this adapter needs. */
export interface ColumnsImageAsset {
  id: string
  file_url: string
  title?: string | null
}

/** Values to hand ``ImageBlockFields`` for a given cell. */
export interface ColumnsImageFieldProps {
  mediaAssetId: string | null
  embedUrl: string
  caption: string
  altText: string
  altUnset: boolean
}

export function cellImageFieldProps(
  cell: ColumnsPayload['cells'][number] | undefined,
): ColumnsImageFieldProps {
  const image = cell?.image
  const alt = image?.alt ?? null
  return {
    mediaAssetId: image?.assetId ?? null,
    // Only an image that came from outside the library shows in the
    // external URL box; a library pick leaves it blank.
    embedUrl: image && image.assetId === null ? image.url : '',
    caption: image?.caption ?? '',
    altText: alt ?? '',
    altUnset: alt === null,
  }
}


/** The creator chose, or uploaded, a library asset for this column. */
export function applyAssetToCell(
  payload: ColumnsPayload,
  index: number,
  asset: ColumnsImageAsset,
): ColumnsPayload {
  const current = payload.cells[index]?.image
  return setCellImage(payload, index, {
    assetId: asset.id,
    // Raw file_url in, resolved at render — the same contract image
    // blocks have.
    url: asset.file_url,
    // Snapshotted so the "inherit the title" alt state can resolve on
    // pages that never hydrate this JSON.
    assetTitle: asset.title ?? null,
    alt: current?.alt ?? null,
    caption: current?.caption ?? null,
  })
}


/** The creator picked a library asset by id, or cleared the selection. */
export function applyAssetIdToCell(
  payload: ColumnsPayload,
  index: number,
  id: string | null,
  assets: ColumnsImageAsset[],
): ColumnsPayload {
  if (!id) return setCellImage(payload, index, null)
  const asset = assets.find((a) => a.id === id)
  return asset ? applyAssetToCell(payload, index, asset) : payload
}


/** The external image URL box changed. */
export function applyEmbedUrlToCell(
  payload: ColumnsPayload,
  index: number,
  url: string,
): ColumnsPayload {
  const current = payload.cells[index]?.image
  if (!url.trim()) {
    // Emptying the box removes an external image, but the controls also
    // clear this field right after a library pick — which must not
    // throw the pick away.
    if (current && current.assetId === null) return setCellImage(payload, index, null)
    return payload
  }
  return setCellImage(payload, index, {
    assetId: null,
    url: url.trim(),
    assetTitle: null,
    alt: current?.alt ?? null,
    caption: current?.caption ?? null,
  })
}


/** A keystroke in the alt-text field. */
export function applyAltTextToCell(
  payload: ColumnsPayload,
  index: number,
  value: string,
): ColumnsPayload {
  const current = payload.cells[index]?.image
  if (!current) return payload
  // See the module note: this arrives as the second half of unticking
  // "decorative", and must leave the unset state alone.
  if (value === '' && current.alt === null) return payload
  return setCellImage(payload, index, { ...current, alt: value })
}


/** The "no alt text needed" decision was set or withdrawn. */
export function applyAltUnsetToCell(
  payload: ColumnsPayload,
  index: number,
  unset: boolean,
): ColumnsPayload {
  const current = payload.cells[index]?.image
  if (!current) return payload
  if (unset) {
    return current.alt === null
      ? payload
      : setCellImage(payload, index, { ...current, alt: null })
  }
  return current.alt === null
    ? setCellImage(payload, index, { ...current, alt: '' })
    : payload
}


/** The caption field changed. */
export function applyCaptionToCell(
  payload: ColumnsPayload,
  index: number,
  value: string,
): ColumnsPayload {
  const current = payload.cells[index]?.image
  if (!current) return payload
  return setCellImage(payload, index, {
    ...current,
    caption: value.trim() ? value : null,
  })
}
