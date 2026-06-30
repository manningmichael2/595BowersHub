/**
 * ItemEditorDialog — edit one list item's fields (lists-v2 R6.1/R6.5).
 *
 * Renders an input per editable field from the list's effective schema (text,
 * number, date, select, multi-select, url), so custom columns, assignee, due
 * date and store tags are all settable from the UI — not just via chat. Core
 * fields go top-level, attribute fields under `attributes`; the backend
 * validates against the schema.
 */
import { useState } from 'react'
import { api } from '../../services/api'
import { toast } from '../../stores/toast'
import {
  Button, Input,
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '../ui'
import type { Field, Item } from '../../pages/ListsPage'

interface Props {
  listId: number
  item: Item
  fields: Field[]
  categoryOptions: string[]
  onClose: () => void
  onSaved: () => void
}

const CORE_KEYS = new Set(['text', 'quantity', 'category', 'due_date', 'assignee_user_id'])
const SKIP = new Set(['sort_order', 'checked'])

function initialValue(item: Item, f: Field): unknown {
  if (f.key === 'text') return item.text
  if (f.key === 'quantity') return item.quantity ?? ''
  if (f.key === 'category') return item.category ?? ''
  if (CORE_KEYS.has(f.key)) return (item as unknown as Record<string, unknown>)[f.key] ?? ''
  const v = item.attributes?.[f.key]
  return v ?? (f.col_type === 'multi_select' ? [] : '')
}

export default function ItemEditorDialog({ listId, item, fields, categoryOptions, onClose, onSaved }: Props) {
  const editable = fields.filter((f) => !SKIP.has(f.key))
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const v: Record<string, unknown> = {}
    for (const f of editable) v[f.key] = initialValue(item, f)
    return v
  })
  const [saving, setSaving] = useState(false)

  const optionsFor = (f: Field): { value: string | number; label: string }[] => {
    if (f.key === 'category' && (!f.options || f.options.length === 0)) {
      return categoryOptions.map((c) => ({ value: c, label: c }))
    }
    return f.options ?? []
  }

  const save = async () => {
    setSaving(true)
    const patch: Record<string, unknown> = {}
    const attributes: Record<string, unknown> = {}
    for (const f of editable) {
      let val = values[f.key]
      if (val === '') val = null
      if (f.col_type === 'number' && val != null) val = Number(val)
      if (f.key === 'assignee_user_id' && val != null) val = Number(val)
      if (CORE_KEYS.has(f.key)) patch[f.key] = val
      else attributes[f.key] = val
    }
    if (Object.keys(attributes).length) patch.attributes = attributes
    try {
      await api.patch(`/api/lists/items/${item.id}`, patch)
      onSaved()
      onClose()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Couldn't save the item.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="flex max-h-[80vh] w-full max-w-sm flex-col rounded-xl border border-border bg-surface shadow-xl"
           onClick={(e) => e.stopPropagation()}>
        <h2 className="border-b border-border px-4 py-3 text-base font-medium">Edit item</h2>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {editable.map((f) => (
            <div key={f.key}>
              <label className="mb-1 block text-xs text-text-muted">{f.label}</label>
              {f.col_type === 'single_select' ? (
                <Select value={values[f.key] != null && values[f.key] !== '' ? String(values[f.key]) : ''}
                  onValueChange={(v) => setValues((s) => ({ ...s, [f.key]: v }))}>
                  <SelectTrigger aria-label={f.label}><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {optionsFor(f).map((o) => <SelectItem key={String(o.value)} value={String(o.value)}>{o.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : f.col_type === 'multi_select' ? (
                <div className="flex flex-wrap gap-1.5">
                  {optionsFor(f).map((o) => {
                    const arr = Array.isArray(values[f.key]) ? (values[f.key] as (string | number)[]) : []
                    const on = arr.map(String).includes(String(o.value))
                    return (
                      <button key={String(o.value)} type="button"
                        className={'rounded-full border px-2 py-0.5 text-xs ' +
                          (on ? 'border-primary bg-primary text-on-primary' : 'border-border text-text-muted')}
                        onClick={() => setValues((s) => {
                          const cur = Array.isArray(s[f.key]) ? (s[f.key] as (string | number)[]).map(String) : []
                          const next = on ? cur.filter((x) => x !== String(o.value)) : [...cur, String(o.value)]
                          return { ...s, [f.key]: next }
                        })}>{o.label}</button>
                    )
                  })}
                </div>
              ) : f.col_type === 'checkbox' ? (
                <input type="checkbox" checked={Boolean(values[f.key])}
                  onChange={(e) => setValues((s) => ({ ...s, [f.key]: e.target.checked }))} aria-label={f.label} />
              ) : (
                <Input
                  type={f.col_type === 'number' ? 'number' : f.col_type === 'date' ? 'date' : f.col_type === 'url' ? 'url' : 'text'}
                  value={values[f.key] != null ? String(values[f.key]) : ''}
                  onChange={(e) => setValues((s) => ({ ...s, [f.key]: e.target.value }))}
                  aria-label={f.label}
                />
              )}
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={save} disabled={saving}>Save</Button>
        </div>
      </div>
    </div>
  )
}
