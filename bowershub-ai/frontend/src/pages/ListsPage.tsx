/**
 * ListsPage — generic typed-list handler (lists-v2).
 *
 * One schema-driven surface renders every list type (grocery / chores / gifts /
 * to-do / packing / custom). Lists are ID-addressed and household-shared; the
 * type's effective schema (from the API) drives fields, grouping, sort, and the
 * store filter — no per-type branches, no hardcoded options. The chat `list`
 * skill writes the same lists ("add milk to the list").
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import { Check, Trash2, Plus, Settings2, ChevronDown, Pencil, GripVertical, Archive } from 'lucide-react'
import { api } from '../services/api'
import { toast } from '../stores/toast'
import {
  Button, Input, Spinner,
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '../components/ui'
import ListSettingsDialog from '../components/lists/ListSettingsDialog'
import ItemEditorDialog from '../components/lists/ItemEditorDialog'

export interface Field {
  key: string
  label: string
  col_type: string
  storage: string
  scope: string
  groupable: boolean
  sortable: boolean
  filterable: boolean
  options: { value: string | number; label: string }[] | null
  options_source: string | null
}

export interface Item {
  id: number
  text: string
  quantity: string | null
  checked: boolean
  category: string | null
  attributes: Record<string, unknown>
}

interface Group {
  key: string | null
  label: string | null
  items: Item[]
}

interface ListSummary {
  id: number
  name: string
  type: string | null
  icon: string | null
  pending: number
  done: number
}

export interface ListType {
  id: number
  name: string
  label: string
  icon: string | null
  group_by?: string | null
  category_set?: { key: string; label: string }[] | null
}

interface SortOption { key: string; label: string }

export default function ListsPage() {
  const [lists, setLists] = useState<ListSummary[]>([])
  const [types, setTypes] = useState<ListType[]>([])
  const [sorts, setSorts] = useState<SortOption[]>([])
  const [stores, setStores] = useState<string[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [schema, setSchema] = useState<Field[]>([])
  const [sort, setSort] = useState<string>('')
  const [store, setStore] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Item | null>(null)
  const [dragId, setDragId] = useState<number | null>(null)
  const [archivedOpen, setArchivedOpen] = useState(false)

  const storeField = useMemo(() => schema.find((f) => f.key === 'store'), [schema])
  const activeType = useMemo(
    () => types.find((t) => t.name === (lists.find((l) => l.id === activeId)?.type ?? '')) ?? null,
    [types, lists, activeId])
  const categoryOptions = useMemo(
    () => (activeType?.category_set ?? []).map((c) => c.key), [activeType])
  // Drag-reorder is only meaningful on a flat (ungrouped) list in manual order.
  const grouped = groups.some((g) => g.label != null)
  const canReorder = !grouped && (sort === '' || sort === 'manual')

  const loadLists = useCallback(async () => {
    try {
      const res = await api.get('/api/lists')
      const ls: ListSummary[] = res.data.lists ?? []
      setLists(ls)
      setActiveId((cur) => cur ?? (ls[0]?.id ?? null))
    } catch {
      /* non-fatal */
    }
  }, [])

  const loadMeta = useCallback(async () => {
    try {
      const [t, c, s] = await Promise.all([
        api.get('/api/lists/types'),
        api.get('/api/lists/config'),
        api.get('/api/lists/stores'),
      ])
      setTypes(t.data.types ?? [])
      setSorts(c.data.sorts ?? [])
      setStores((s.data.stores ?? []).map((x: { name: string }) => x.name))
    } catch {
      /* non-fatal */
    }
  }, [])

  const loadView = useCallback(async (id: number) => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (sort) params.set('sort', sort)
      if (store) params.set('store', store)
      const res = await api.get(`/api/lists/${id}/view?${params.toString()}`)
      setGroups(res.data.groups ?? [])
      setSchema(res.data.schema ?? [])
    } catch (err: any) {
      toast.error(`Couldn't load list: ${err.response?.data?.detail || 'error'}`)
    } finally {
      setLoading(false)
    }
  }, [sort, store])

  useEffect(() => { loadLists(); loadMeta() }, [loadLists, loadMeta])
  useEffect(() => { if (activeId != null) loadView(activeId) }, [activeId, loadView])

  const refresh = () => { if (activeId != null) loadView(activeId); loadLists() }

  const addItem = async () => {
    const text = draft.trim()
    if (!text || activeId == null) return
    setBusy(true); setDraft('')
    try {
      await api.post(`/api/lists/${activeId}/items`, { items: [text] })
      refresh()
    } catch (err: any) {
      toast.error(`Couldn't add: ${err.response?.data?.detail || 'error'}`)
      setDraft(text)
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (item: Item) => {
    setGroups((gs) => gs.map((g) => ({ ...g, items: g.items.map((i) => i.id === item.id ? { ...i, checked: !i.checked } : i) })))
    try {
      await api.put(`/api/lists/items/${item.id}`, { checked: !item.checked })
    } catch {
      toast.error("Couldn't update that item.")
      if (activeId != null) loadView(activeId)
    }
  }

  const remove = async (item: Item) => {
    setGroups((gs) => gs.map((g) => ({ ...g, items: g.items.filter((i) => i.id !== item.id) })))
    try {
      await api.delete(`/api/lists/items/${item.id}`)
    } catch {
      toast.error("Couldn't remove that item.")
      refresh()
    }
  }

  const clearChecked = async () => {
    if (activeId == null) return
    setBusy(true)
    try {
      await api.post(`/api/lists/${activeId}/clear`)
      refresh()
    } catch {
      toast.error("Couldn't clear checked items.")
    } finally {
      setBusy(false)
    }
  }

  const onDrop = async (targetId: number) => {
    if (dragId == null || dragId === targetId || activeId == null) { setDragId(null); return }
    const flat = groups.flatMap((g) => g.items).map((i) => i.id)
    const from = flat.indexOf(dragId)
    const to = flat.indexOf(targetId)
    if (from < 0 || to < 0) { setDragId(null); return }
    flat.splice(to, 0, flat.splice(from, 1)[0])
    setDragId(null)
    // Optimistic: reorder the single group locally.
    setGroups((gs) => {
      const byId = new Map(gs.flatMap((g) => g.items).map((i) => [i.id, i]))
      return gs.map((g, idx) => idx === 0 ? { ...g, items: flat.map((id) => byId.get(id)!).filter(Boolean) } : g)
    })
    try {
      await api.post(`/api/lists/${activeId}/items/reorder`, { ordered_item_ids: flat })
    } catch {
      toast.error("Couldn't reorder."); if (activeId != null) loadView(activeId)
    }
  }

  const unarchive = async (id: number) => {
    try { await api.post(`/api/lists/${id}/unarchive`); loadLists() }
    catch { toast.error("Couldn't unarchive.") }
  }

  const createList = async (name: string, list_type_id: number) => {
    try {
      const res = await api.post('/api/lists', { name, list_type_id })
      setCreating(false)
      await loadLists()
      setActiveId(res.data.id)
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Couldn't create the list.")
    }
  }

  const checkedCount = groups.reduce((n, g) => n + g.items.filter((i) => i.checked).length, 0)
  const activeList = lists.find((l) => l.id === activeId) ?? null
  const attrFields = schema.filter((f) => f.storage === 'attribute' && f.key !== 'store')

  return (
    <div className="flex h-full flex-col bg-surface text-text">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <h1 className="text-lg font-medium">Lists</h1>

        <Select value={activeId != null ? String(activeId) : ''} onValueChange={(v) => setActiveId(Number(v))}>
          <SelectTrigger className="w-48" aria-label="Choose list">
            <SelectValue placeholder="Pick a list" />
          </SelectTrigger>
          <SelectContent>
            {lists.map((l) => (
              <SelectItem key={l.id} value={String(l.id)}>{l.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button variant="ghost" size="sm" onClick={() => setCreating(true)}>
          <Plus size={15} aria-hidden /> New
        </Button>

        {sorts.length > 0 && (
          <Select value={sort} onValueChange={setSort}>
            <SelectTrigger className="w-36" aria-label="Sort by">
              <SelectValue placeholder="Sort" />
            </SelectTrigger>
            <SelectContent>
              {sorts.map((s) => <SelectItem key={s.key} value={s.key}>{s.label}</SelectItem>)}
            </SelectContent>
          </Select>
        )}

        {storeField && stores.length > 0 && (
          <Select value={store || '__all__'} onValueChange={(v) => setStore(v === '__all__' ? '' : v)}>
            <SelectTrigger className="w-36" aria-label="Store">
              <SelectValue placeholder="All stores" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All stores</SelectItem>
              {stores.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        )}

        <div className="ml-auto flex items-center gap-2">
          {checkedCount > 0 && (
            <Button variant="ghost" size="sm" onClick={clearChecked} disabled={busy}>
              Clear {checkedCount} checked
            </Button>
          )}
          <Button variant="ghost" size="icon" aria-label="Archived lists" onClick={() => setArchivedOpen(true)}>
            <Archive size={16} aria-hidden />
          </Button>
          {activeId != null && (
            <Button variant="ghost" size="icon" aria-label="List settings" onClick={() => setSettingsOpen(true)}>
              <Settings2 size={17} aria-hidden />
            </Button>
          )}
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 overflow-y-auto p-4">
        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addItem()}
            placeholder={activeList ? `Add to ${activeList.name}…` : 'Pick or create a list'}
            aria-label="Add item"
            disabled={activeId == null}
          />
          <Button onClick={addItem} disabled={busy || !draft.trim() || activeId == null} size="icon" aria-label="Add">
            <Plus size={18} aria-hidden />
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-text-muted"><Spinner /> Loading…</div>
        ) : groups.every((g) => g.items.length === 0) ? (
          <p className="py-8 text-center text-sm text-text-muted">
            Nothing here yet. Add an item above — or tell the assistant “add milk to the list”.
          </p>
        ) : (
          <div className="space-y-4">
            {groups.filter((g) => g.items.length > 0).map((g) => (
              <section key={g.key ?? '__none__'}>
                {g.label && (
                  <h2 className="mb-1 flex items-center gap-1 px-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
                    <ChevronDown size={12} aria-hidden /> {g.label}
                  </h2>
                )}
                <ul className="space-y-1">
                  {g.items.map((i) => (
                    <ItemRow key={i.id} item={i} attrFields={attrFields}
                      onToggle={toggle} onRemove={remove} onEdit={() => setEditing(i)}
                      draggable={canReorder}
                      onDragStart={() => setDragId(i.id)}
                      onDropItem={() => onDrop(i.id)} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      {creating && (
        <CreateListDialog types={types} onClose={() => setCreating(false)} onCreate={createList} />
      )}
      {settingsOpen && activeList && (
        <ListSettingsDialog
          list={activeList}
          types={types}
          onClose={() => setSettingsOpen(false)}
          onChanged={refresh}
          onDeleted={() => { setSettingsOpen(false); setActiveId(null); loadLists() }}
          onStoresChanged={loadMeta}
        />
      )}
      {editing && activeId != null && (
        <ItemEditorDialog
          listId={activeId}
          item={editing}
          fields={schema}
          categoryOptions={categoryOptions}
          onClose={() => setEditing(null)}
          onSaved={refresh}
        />
      )}
      {archivedOpen && (
        <ArchivedDialog onClose={() => setArchivedOpen(false)} onUnarchive={unarchive} />
      )}
    </div>
  )
}

function ArchivedDialog({ onClose, onUnarchive }: { onClose: () => void; onUnarchive: (id: number) => void }) {
  const [rows, setRows] = useState<ListSummary[]>([])
  useEffect(() => {
    api.get('/api/lists?archived=true').then((r) => setRows(r.data.lists ?? [])).catch(() => {})
  }, [])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-3 text-base font-medium">Archived lists</h2>
        {rows.length === 0 ? (
          <p className="py-4 text-center text-sm text-text-muted">No archived lists.</p>
        ) : (
          <ul className="space-y-1">
            {rows.map((l) => (
              <li key={l.id} className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-surface-light/50">
                <span className="flex-1 text-sm">{l.name}</span>
                <Button variant="ghost" size="sm" onClick={() => onUnarchive(l.id)}>Restore</Button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex justify-end"><Button variant="ghost" size="sm" onClick={onClose}>Done</Button></div>
      </div>
    </div>
  )
}

function ItemRow({ item, attrFields, onToggle, onRemove, onEdit, draggable, onDragStart, onDropItem }: {
  item: Item
  attrFields: Field[]
  onToggle: (i: Item) => void
  onRemove: (i: Item) => void
  onEdit: () => void
  draggable: boolean
  onDragStart: () => void
  onDropItem: () => void
}) {
  const chips: string[] = []
  for (const f of attrFields) {
    const v = item.attributes?.[f.key]
    if (v == null || (Array.isArray(v) && v.length === 0)) continue
    chips.push(`${f.label}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
  }
  return (
    <li
      draggable={draggable}
      onDragStart={onDragStart}
      onDragOver={(e) => draggable && e.preventDefault()}
      onDrop={onDropItem}
      className="group flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-surface-light/50"
    >
      {draggable && (
        <span className="shrink-0 cursor-grab text-text-muted opacity-0 group-hover:opacity-100" aria-hidden>
          <GripVertical size={14} />
        </span>
      )}
      <button
        onClick={() => onToggle(item)}
        aria-label={item.checked ? `Uncheck ${item.text}` : `Check ${item.text}`}
        className={'flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ' +
          (item.checked ? 'border-primary bg-primary text-on-primary' : 'border-border hover:border-primary')}
      >
        {item.checked && <Check size={14} aria-hidden />}
      </button>
      <span className={'flex-1 text-sm ' + (item.checked ? 'text-text-muted line-through' : 'text-text')}>
        {item.text}
        {item.quantity && <span className="ml-2 text-xs text-text-muted">({item.quantity})</span>}
        {chips.length > 0 && (
          <span className="ml-2 space-x-1">
            {chips.map((c) => (
              <span key={c} className="rounded bg-surface-light px-1.5 py-0.5 text-[10px] text-text-muted">{c}</span>
            ))}
          </span>
        )}
      </span>
      <button onClick={onEdit} aria-label={`Edit ${item.text}`}
        className="shrink-0 rounded p-1 text-text-muted opacity-0 transition-opacity hover:text-text group-hover:opacity-100">
        <Pencil size={14} aria-hidden />
      </button>
      <button
        onClick={() => onRemove(item)}
        aria-label={`Remove ${item.text}`}
        className="shrink-0 rounded p-1 text-text-muted opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
      >
        <Trash2 size={15} aria-hidden />
      </button>
    </li>
  )
}

function CreateListDialog({ types, onClose, onCreate }: {
  types: ListType[]
  onClose: () => void
  onCreate: (name: string, typeId: number) => void
}) {
  const [name, setName] = useState('')
  const [typeId, setTypeId] = useState<number | null>(types[0]?.id ?? null)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-3 text-base font-medium">New list</h2>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="List name" aria-label="List name" autoFocus />
        <div className="mt-3">
          <Select value={typeId != null ? String(typeId) : ''} onValueChange={(v) => setTypeId(Number(v))}>
            <SelectTrigger aria-label="List type"><SelectValue placeholder="Type" /></SelectTrigger>
            <SelectContent>
              {types.map((t) => <SelectItem key={t.id} value={String(t.id)}>{t.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" disabled={!name.trim() || typeId == null}
            onClick={() => typeId != null && onCreate(name.trim(), typeId)}>Create</Button>
        </div>
      </div>
    </div>
  )
}
