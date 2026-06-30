/**
 * ListSettingsDialog — manage a list's columns, options, stores, and details.
 *
 * This is where "see the columns per list and add options to pick lists" lives
 * (lists-v2 R6.5): add/remove custom columns, edit the store option set, and
 * rename / retype / archive / delete the list. All options are API-driven.
 */
import { useEffect, useState, useCallback } from 'react'
import { Trash2, Plus } from 'lucide-react'
import { api } from '../../services/api'
import { toast } from '../../stores/toast'
import {
  Button, Input,
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '../ui'
import type { Field, ListType } from '../../pages/ListsPage'

interface Props {
  list: { id: number; name: string; type: string | null }
  types: ListType[]
  onClose: () => void
  onChanged: () => void
  onDeleted: () => void
  onStoresChanged: () => void
}

interface Store { id: number; name: string }

const COL_TYPES = ['text', 'number', 'date', 'checkbox', 'single_select', 'multi_select', 'url']
type Tab = 'details' | 'columns' | 'stores'

export default function ListSettingsDialog({ list, types, onClose, onChanged, onDeleted, onStoresChanged }: Props) {
  const [tab, setTab] = useState<Tab>('details')
  const [name, setName] = useState(list.name)
  const [fields, setFields] = useState<Field[]>([])
  const [stores, setStores] = useState<Store[]>([])
  const [newCol, setNewCol] = useState({ key: '', label: '', col_type: 'text', options: '' })
  const [newStore, setNewStore] = useState('')
  const [aisleFor, setAisleFor] = useState<number | null>(null)
  const [aisleText, setAisleText] = useState('')

  const parseOptions = (s: string) =>
    s.split(',').map((o) => o.trim()).filter(Boolean).map((o) => ({ value: o, label: o }))

  const loadFields = useCallback(async () => {
    try {
      const res = await api.get(`/api/lists/${list.id}/fields`)
      setFields(res.data.fields ?? [])
    } catch { /* non-fatal */ }
  }, [list.id])

  const loadStores = useCallback(async () => {
    try {
      const res = await api.get('/api/lists/stores')
      setStores(res.data.stores ?? [])
    } catch { /* non-fatal */ }
  }, [])

  useEffect(() => { loadFields(); loadStores() }, [loadFields, loadStores])

  const rename = async () => {
    if (!name.trim() || name === list.name) return
    try {
      await api.patch(`/api/lists/${list.id}`, { name: name.trim() })
      toast.success('Renamed.')
      onChanged()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Couldn't rename.")
    }
  }

  const retype = async (typeId: number) => {
    try {
      await api.patch(`/api/lists/${list.id}`, { list_type_id: typeId })
      onChanged(); loadFields()
    } catch { toast.error("Couldn't change type.") }
  }

  const archive = async () => {
    try { await api.post(`/api/lists/${list.id}/archive`); onDeleted() }
    catch { toast.error("Couldn't archive.") }
  }

  const del = async () => {
    if (!confirm(`Delete "${list.name}" and all its items? This can't be undone.`)) return
    try { await api.delete(`/api/lists/${list.id}?confirm=true`); onDeleted() }
    catch { toast.error("Couldn't delete.") }
  }

  const isSelect = (t: string) => t === 'single_select' || t === 'multi_select'

  const addColumn = async () => {
    const key = newCol.key.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_')
    if (!key || !newCol.label.trim()) return
    if (isSelect(newCol.col_type) && !newCol.options.trim()) {
      toast.error('Add at least one option for a select column.')
      return
    }
    try {
      await api.post(`/api/lists/${list.id}/fields`, {
        key, label: newCol.label.trim(), col_type: newCol.col_type,
        options: isSelect(newCol.col_type) ? parseOptions(newCol.options) : null,
      })
      setNewCol({ key: '', label: '', col_type: 'text', options: '' })
      loadFields(); onChanged()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Couldn't add the column.")
    }
  }

  const saveOptions = async (f: Field, optionsText: string) => {
    try {
      await api.patch(`/api/lists/${list.id}/fields/${encodeURIComponent(f.key)}`,
        { options: parseOptions(optionsText) })
      loadFields(); onChanged()
    } catch { toast.error("Couldn't update options.") }
  }

  const saveAisles = async (storeId: number) => {
    const departments = aisleText.split(',').map((d) => d.trim()).filter(Boolean)
    try {
      await api.put(`/api/lists/stores/${storeId}/aisles`, { departments })
      setAisleFor(null); setAisleText(''); onStoresChanged()
      toast.success('Aisle order saved.')
    } catch { toast.error("Couldn't save aisle order.") }
  }

  const removeColumn = async (f: Field) => {
    try {
      await api.patch(`/api/lists/${list.id}/fields/${encodeURIComponent(f.key)}`, { is_active: false })
      loadFields(); onChanged()
    } catch { toast.error("Couldn't remove the column.") }
  }

  const addStore = async () => {
    if (!newStore.trim()) return
    try {
      await api.post('/api/lists/stores', { name: newStore.trim() })
      setNewStore(''); loadStores(); onStoresChanged()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Couldn't add the store.")
    }
  }

  const removeStore = async (s: Store) => {
    try { await api.delete(`/api/lists/stores/${s.id}`); loadStores(); onStoresChanged() }
    catch { toast.error("Couldn't remove the store.") }
  }

  const typeId = types.find((t) => t.name === list.type)?.id ?? null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="flex max-h-[80vh] w-full max-w-md flex-col rounded-xl border border-border bg-surface shadow-xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <h2 className="text-base font-medium">List settings</h2>
          <div className="ml-auto flex gap-1 text-sm">
            {(['details', 'columns', 'stores'] as Tab[]).map((t) => (
              <button key={t}
                className={'rounded px-2 py-1 capitalize ' + (tab === t ? 'bg-surface-light text-text' : 'text-text-muted')}
                onClick={() => setTab(t)}>{t}</button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {tab === 'details' && (
            <div className="space-y-4">
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="mb-1 block text-xs text-text-muted">Name</label>
                  <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="List name" />
                </div>
                <Button size="sm" onClick={rename} disabled={!name.trim() || name === list.name}>Save</Button>
              </div>
              <div>
                <label className="mb-1 block text-xs text-text-muted">Type</label>
                <Select value={typeId != null ? String(typeId) : ''} onValueChange={(v) => retype(Number(v))}>
                  <SelectTrigger aria-label="List type"><SelectValue placeholder="Type" /></SelectTrigger>
                  <SelectContent>
                    {types.map((t) => <SelectItem key={t.id} value={String(t.id)}>{t.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex gap-2 pt-2">
                <Button variant="ghost" size="sm" onClick={archive}>Archive</Button>
                <Button variant="ghost" size="sm" className="text-danger" onClick={del}>Delete…</Button>
              </div>
            </div>
          )}

          {tab === 'columns' && (
            <div className="space-y-3">
              <ul className="space-y-1">
                {fields.map((f) => (
                  <ColumnRow key={f.key} field={f} onRemove={() => removeColumn(f)}
                    onSaveOptions={(txt) => saveOptions(f, txt)} editableOptions={isSelect(f.col_type) && !f.options_source} />
                ))}
              </ul>
              <div className="space-y-2 border-t border-border pt-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Input className="w-28" placeholder="key" value={newCol.key}
                    onChange={(e) => setNewCol({ ...newCol, key: e.target.value })} aria-label="Column key" />
                  <Input className="w-28" placeholder="Label" value={newCol.label}
                    onChange={(e) => setNewCol({ ...newCol, label: e.target.value })} aria-label="Column label" />
                  <Select value={newCol.col_type} onValueChange={(v) => setNewCol({ ...newCol, col_type: v })}>
                    <SelectTrigger className="w-32" aria-label="Column type"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {COL_TYPES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Button size="icon" aria-label="Add column" onClick={addColumn}
                    disabled={!newCol.key.trim() || !newCol.label.trim()}><Plus size={16} /></Button>
                </div>
                {isSelect(newCol.col_type) && (
                  <Input placeholder="Options, comma-separated (e.g. low, medium, high)" value={newCol.options}
                    onChange={(e) => setNewCol({ ...newCol, options: e.target.value })} aria-label="Options" />
                )}
              </div>
            </div>
          )}

          {tab === 'stores' && (
            <div className="space-y-3">
              <ul className="space-y-1">
                {stores.map((s) => (
                  <li key={s.id} className="rounded px-2 py-1.5 hover:bg-surface-light/50">
                    <div className="flex items-center gap-2">
                      <span className="flex-1 text-sm">{s.name}</span>
                      <button aria-label={`Aisle order for ${s.name}`}
                        onClick={() => { setAisleFor(aisleFor === s.id ? null : s.id); setAisleText('') }}
                        className="rounded px-1.5 py-0.5 text-xs text-text-muted hover:text-text">Aisles</button>
                      <button aria-label={`Remove ${s.name}`} onClick={() => removeStore(s)}
                        className="rounded p-1 text-text-muted hover:text-danger"><Trash2 size={14} /></button>
                    </div>
                    {aisleFor === s.id && (
                      <div className="mt-2 flex items-center gap-2">
                        <Input placeholder="Departments in walk order, comma-separated" value={aisleText}
                          onChange={(e) => setAisleText(e.target.value)} aria-label="Aisle order" />
                        <Button size="sm" onClick={() => saveAisles(s.id)} disabled={!aisleText.trim()}>Save</Button>
                      </div>
                    )}
                  </li>
                ))}
                {stores.length === 0 && <li className="px-2 py-2 text-sm text-text-muted">No stores yet.</li>}
              </ul>
              <div className="flex items-center gap-2 border-t border-border pt-3">
                <Input placeholder="Add a store (e.g. Meijer)" value={newStore}
                  onChange={(e) => setNewStore(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addStore()} aria-label="New store" />
                <Button size="icon" aria-label="Add store" onClick={addStore} disabled={!newStore.trim()}>
                  <Plus size={16} />
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end border-t border-border px-4 py-3">
          <Button variant="ghost" size="sm" onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>
  )
}

function ColumnRow({ field, onRemove, onSaveOptions, editableOptions }: {
  field: Field
  onRemove: () => void
  onSaveOptions: (text: string) => void
  editableOptions: boolean
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState((field.options ?? []).map((o) => o.label).join(', '))
  return (
    <li className="rounded px-2 py-1.5 hover:bg-surface-light/50">
      <div className="flex items-center gap-2">
        <span className="flex-1 text-sm">{field.label}
          <span className="ml-2 text-xs text-text-muted">{field.col_type}</span>
          {field.scope !== 'list' && <span className="ml-2 text-[10px] uppercase text-text-muted">{field.scope}</span>}
        </span>
        {editableOptions && (
          <button className="rounded px-1.5 py-0.5 text-xs text-text-muted hover:text-text"
            onClick={() => setOpen((o) => !o)} aria-label={`Options for ${field.label}`}>Options</button>
        )}
        <button aria-label={`Remove ${field.label}`} onClick={onRemove}
          className="rounded p-1 text-text-muted hover:text-danger"><Trash2 size={14} /></button>
      </div>
      {open && editableOptions && (
        <div className="mt-2 flex items-center gap-2">
          <Input value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Options, comma-separated" aria-label="Edit options" />
          <Button size="sm" onClick={() => { onSaveOptions(text); setOpen(false) }}>Save</Button>
        </div>
      )}
    </li>
  )
}
