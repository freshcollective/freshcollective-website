import type { ReactNode, HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react'
import { cn } from './utils'

/**
 * Table — compositional table primitive per §11.
 *
 * No zebra. No coloured cells. Numbers right-align (use `align="right"`).
 * Empty cells use em dash (call sites render "—" for null values).
 *
 * @see docs/fresh-design-language.md §11
 */

export type TableDensity = 'standard' | 'compact'

interface TableProps extends HTMLAttributes<HTMLTableElement> {
  density?: TableDensity
  children: ReactNode
}

export function Table({
  density = 'standard', className, children, ...rest
}: TableProps) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        data-density={density}
        className={cn(
          'w-full border-collapse text-left',
          className,
        )}
        {...rest}
      >
        {children}
      </table>
    </div>
  )
}

export function TableHeader({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>
}

export function TableBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>
}

interface TableRowProps extends HTMLAttributes<HTMLTableRowElement> {
  interactive?: boolean
  children: ReactNode
}

export function TableRow({
  interactive = false, className, children, ...rest
}: TableRowProps) {
  return (
    <tr
      className={cn(
        'border-b border-[color:var(--fc-border-hairline)]',
        interactive &&
          'cursor-pointer transition-colors duration-[var(--fc-motion-hover)] hover:bg-[color:var(--fc-surface-muted)]',
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  )
}

interface TableHeadCellProps extends ThHTMLAttributes<HTMLTableCellElement> {
  align?: 'left' | 'right' | 'center'
  children: ReactNode
}

export function TableHead({
  align = 'left', className, children, ...rest
}: TableHeadCellProps) {
  return (
    <th
      scope="col"
      className={cn(
        'text-[11px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow-tight)]',
        'text-[color:var(--fc-ink-primary)]',
        'px-4 py-3',
        // Density = compact tightens the leading in the parent selector.
        '[[data-density=compact]_&]:px-3 [[data-density=compact]_&]:py-2',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  )
}

interface TableCellProps extends TdHTMLAttributes<HTMLTableCellElement> {
  align?: 'left' | 'right' | 'center'
  children: ReactNode
}

export function TableCell({
  align = 'left', className, children, ...rest
}: TableCellProps) {
  return (
    <td
      className={cn(
        'text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)] text-[color:var(--fc-ink-primary)]',
        'px-4 py-3',
        '[[data-density=compact]_&]:px-3 [[data-density=compact]_&]:py-1.5',
        align === 'right' && 'text-right tabular-nums',
        align === 'center' && 'text-center',
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  )
}

/**
 * `emDash` — helper for empty cells. `<TableCell>{emDash(value)}</TableCell>`
 * renders an em dash when the value is null/undefined/empty string.
 */
export function emDash<T>(value: T | null | undefined): T | '—' {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' && value.trim() === '') return '—'
  return value
}
