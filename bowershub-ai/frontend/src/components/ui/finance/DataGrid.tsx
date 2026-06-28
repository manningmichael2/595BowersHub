import type { ReactNode } from 'react'
import {
  Table,
  TableHeader,
  TableBody,
  Column,
  Row,
  Cell,
  type Key,
  type SortDescriptor,
} from 'react-aria-components'
import { cn } from '../cn'

export interface DataGridColumn<T> {
  id: string
  header: string
  /** Marks the column whose cell labels each row (a11y). */
  isRowHeader?: boolean
  allowsSorting?: boolean
  render: (row: T) => ReactNode
}

export interface DataGridProps<T> {
  'aria-label': string
  columns: DataGridColumn<T>[]
  rows: T[]
  getRowId: (row: T) => Key
  sortDescriptor?: SortDescriptor
  onSortChange?: (descriptor: SortDescriptor) => void
  selectionMode?: 'none' | 'single' | 'multiple'
  emptyMessage?: string
  className?: string
}

/**
 * DataGrid — tabular data over React Aria's Table (R2.5): sortable columns,
 * keyboard navigation, selection, ARIA grid semantics. Config-driven (columns +
 * rows) for the finance transaction/holdings views. Exposed through the finance
 * UI boundary; inline-cell editing is layered on at the P4 integration points.
 */
export function DataGrid<T>({
  columns,
  rows,
  getRowId,
  sortDescriptor,
  onSortChange,
  selectionMode = 'none',
  emptyMessage = 'No rows',
  className,
  ...aria
}: DataGridProps<T>) {
  return (
    <Table
      aria-label={aria['aria-label']}
      selectionMode={selectionMode}
      sortDescriptor={sortDescriptor}
      onSortChange={onSortChange}
      className={cn('w-full border-collapse text-sm text-text', className)}
    >
      <TableHeader columns={columns}>
        {(column) => (
          <Column
            id={column.id}
            isRowHeader={column.isRowHeader}
            allowsSorting={column.allowsSorting}
            className="cursor-default border-b border-border px-3 py-2 text-left text-xs font-medium text-text-muted outline-none"
          >
            {column.header}
          </Column>
        )}
      </TableHeader>
      <TableBody
        items={rows}
        renderEmptyState={() => (
          <div className="p-6 text-center text-sm text-text-muted">{emptyMessage}</div>
        )}
      >
        {(item) => (
          <Row
            id={getRowId(item)}
            columns={columns}
            className="border-b border-border outline-none data-[hovered]:bg-surface-light data-[selected]:bg-primary/10"
          >
            {(column) => (
              <Cell className="px-3 py-2 tabular-nums outline-none">
                {(column as DataGridColumn<T>).render(item)}
              </Cell>
            )}
          </Row>
        )}
      </TableBody>
    </Table>
  )
}
