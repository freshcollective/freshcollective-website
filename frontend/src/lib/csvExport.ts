/**
 * Small CSV export helper for the World Management pages.
 *
 * Design decision: exports are computed **client-side** from the already
 * loaded, filtered, sorted array that renders the table.
 *
 * Rationale:
 *   - The admin pages hold their entire visible dataset in memory
 *     already (that's what powers instant search / sort / filter).
 *   - A dedicated backend endpoint would duplicate the filter/sort
 *     logic and add a network round-trip for data the browser already
 *     has, with no correctness benefit at current scale.
 *   - The scale is small (World Management is for a handful of
 *     caretakers overseeing a curated platform, not a data-warehouse
 *     export tool).
 *   - If the dataset ever grows large enough that the page can't
 *     render every row (i.e. we introduce pagination), export moves
 *     to a backend endpoint that accepts the same filter parameters
 *     — the frontend table can no longer be the source of truth.
 *
 * RFC 4180-shaped output:
 *   - UTF-8 with a leading BOM so Excel opens it as UTF-8 rather
 *     than mangling accented characters or em-dashes.
 *   - CRLF line endings.
 *   - Fields containing `,`, `"`, `\n`, or `\r` are wrapped in double
 *     quotes; embedded `"` doubled.
 *   - Header row always present.
 *   - Empty values render as empty cells (no placeholder character).
 */

export type CsvColumn<T> = {
  header: string
  value: (row: T) => string | null | undefined
}

export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const header = columns.map((c) => escapeCsvField(c.header)).join(',')
  const body = rows
    .map((row) => columns.map((c) => escapeCsvField(c.value(row))).join(','))
    .join('\r\n')
  return body ? `${header}\r\n${body}\r\n` : `${header}\r\n`
}

export function downloadCsv<T>(
  rows: T[],
  columns: CsvColumn<T>[],
  filename: string,
): void {
  const csv = '\uFEFF' + toCsv(rows, columns)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function escapeCsvField(value: string | null | undefined): string {
  const s = (value ?? '').toString()
  if (/[",\r\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`
  }
  return s
}

export function todayIsoDate(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Multi-value delimiter used across the World Management exports. */
export const CSV_MULTI_DELIMITER = '; '
