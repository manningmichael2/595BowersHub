/**
 * SplitEditor — shared editor to split a transaction across N categories.
 * Decoupled from any page: takes the parent `amount` + category options and
 * emits the allocations once they balance to the total. Used by the
 * Transactions explorer (desktop modal / mobile inline) and the Review queue.
 */
import { useState } from 'react'
import { Button } from '../ui'
import { Combobox, CurrencyInput } from '../ui/finance'

export interface SplitCategoryOption { id: number; name: string }

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}

interface Line { category_id: number | null; amount: number }

export default function SplitEditor({ amount, categories, onSave, onCancel }: {
  amount: number
  categories: SplitCategoryOption[]
  onSave: (allocations: { category_id: number | null; amount: number }[]) => void
  onCancel: () => void
}) {
  // amount === NaN means the line's amount field is empty.
  const [lines, setLines] = useState<Line[]>([
    { category_id: null, amount: NaN }, { category_id: null, amount: NaN },
  ])
  const sum = lines.reduce((a, l) => a + (Number.isNaN(l.amount) ? 0 : l.amount), 0)
  const balanced = Math.abs(sum - amount) < 0.005 && lines.every((l) => !Number.isNaN(l.amount))
  const set = (i: number, patch: Partial<Line>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))

  const options = categories.map((c) => ({ id: c.id, label: c.name }))

  return (
    <div data-testid="split-editor" className="flex flex-col gap-2 border-t border-dashed border-border pt-2">
      <div className="text-xs text-text-muted">
        Split {money(amount)} — remaining {money(amount - sum)}
      </div>
      {lines.map((l, i) => (
        <div key={i} className="flex items-end gap-2">
          <Combobox
            aria-label={`Split category ${i + 1}`}
            className="min-w-0 flex-1"
            options={options}
            selectedKey={l.category_id}
            onSelectionChange={(k) => set(i, { category_id: k == null ? null : Number(k) })}
            placeholder="Category…"
          />
          <CurrencyInput
            aria-label={`Split amount ${i + 1}`}
            className="w-28 shrink-0"
            value={l.amount}
            onChange={(v) => set(i, { amount: v })}
            placeholder="$0.00"
          />
        </div>
      ))}
      <div className="flex gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setLines((ls) => [...ls, { category_id: null, amount: NaN }])}
        >
          + line
        </Button>
        <Button
          size="sm"
          disabled={!balanced}
          onClick={() => onSave(lines.map((l) => ({ category_id: l.category_id, amount: l.amount })))}
        >
          Save split
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
