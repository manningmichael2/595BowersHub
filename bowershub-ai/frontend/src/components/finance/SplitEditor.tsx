/**
 * SplitEditor — shared inline editor to split a transaction across N categories.
 * Decoupled from any page: takes the parent `amount` + category options and emits
 * the allocations once they balance to the total. Used by the Transactions
 * explorer and the Review queue.
 */
import { useState } from 'react'

export interface SplitCategoryOption { id: number; name: string }

const selectStyle: React.CSSProperties = {
  background: 'var(--color-surface)', color: 'var(--color-text)',
  border: '1px solid var(--color-border, #374151)', borderRadius: 6, padding: '4px 8px',
}

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}

export default function SplitEditor({ amount, categories, onSave, onCancel }: {
  amount: number
  categories: SplitCategoryOption[]
  onSave: (allocations: { category_id: number | null; amount: number }[]) => void
  onCancel: () => void
}) {
  const [lines, setLines] = useState<{ category_id: number | ''; amount: string }[]>([
    { category_id: '', amount: '' }, { category_id: '', amount: '' },
  ])
  const sum = lines.reduce((a, l) => a + (Number(l.amount) || 0), 0)
  const balanced = Math.abs(sum - amount) < 0.005 && lines.every((l) => l.amount !== '')
  const set = (i: number, patch: Partial<{ category_id: number | ''; amount: string }>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))

  return (
    <div data-testid="split-editor" style={{ borderTop: '1px dashed var(--color-border,#333)', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
        Split {money(amount)} — remaining {money(amount - sum)}
      </div>
      {lines.map((l, i) => (
        <div key={i} style={{ display: 'flex', gap: 6 }}>
          <select style={selectStyle} aria-label={`Split category ${i + 1}`} value={l.category_id}
            onChange={(e) => set(i, { category_id: e.target.value === '' ? '' : Number(e.target.value) })}>
            <option value="">Category…</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <input aria-label={`Split amount ${i + 1}`} placeholder="amount" value={l.amount} style={{ width: 90 }}
            onChange={(e) => set(i, { amount: e.target.value })} />
        </div>
      ))}
      <div style={{ display: 'flex', gap: 4 }}>
        <button style={{ fontSize: 12 }} onClick={() => setLines((ls) => [...ls, { category_id: '', amount: '' }])}>+ line</button>
        <button style={{ fontSize: 12 }} disabled={!balanced}
          onClick={() => onSave(lines.map((l) => ({ category_id: l.category_id === '' ? null : l.category_id, amount: Number(l.amount) })))}>
          Save split
        </button>
        <button style={{ fontSize: 12 }} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}
