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
import { Check, Trash2, Plus, Settings2, ChevronDown, Pencil, GripVertical, Archive, List, Table2, SlidersHorizontal } from 'lucide-react'
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
  const [viewMode, setViewMode] = useState<'list' | 'table'>('list')
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(new Set())
  const [colMenuOpen, setColMenuOpen] = useState(false)

  const storeField = useMemo(() => schema.find((f) => f.key === 'store'), [schema])
  const activeType = useMemo(
    () => types.find((t) => t.name === (lists.find((l) => l.id === activeId)?.type ?? '')) ?? null,
    [types, lists, activeId])
  const categoryOptions = useMemo(
    () => (activeType?.category_set ?? []).map((c) => c.key), [activeType])
  // Drag-reorder is only meaningful on a flat (ungrouped) list in manual order.
  const grouped = groups.some((g) => g.label != null)
  const canReorder = !grouped && (sort === '' || sort === 'manual')

  // Per-list view preferences (mode + hidden columns), remembered per device.
  useEffect(() => {
    if (activeId == null) return
    try {
      const raw = localStorage.getItem(`lists:view:${activeId}`)
      const v = raw ? JSON.parse(raw) : null
      setViewMode(v?.mode === 'table' ? 'table' : 'list')
      setHiddenCols(new Set<string>(v?.hidden ?? []))
    } catch { setViewMode('list'); setHiddenCols(new Set()) }
  }, [activeId])

  const persistView = useCallback((mode: 'list' | 'table', hidden: Set<string>) => {
    if (activeId == null) return
    try { localStorage.setItem(`lists:view:${activeId}`, JSON.stringify({ mode, hidden: [...hidden] })) } catch { /* */ }
  }, [activeId])

  const setMode = (m: 'list' | 'table') => { setViewMode(m); persistView(m, hiddenCols) }
  const toggleCol = (key: string) => {
    setHiddenCols((cur) => {
      const next = new Set(cur)
      next.has(key) ? next.delete(key) : next.add(key)
      persistView(viewMode, next)
      return next
    })
  }
  // Columns selectable in the view editor (everything except the item label + internal fields).
  const columnFields = schema.filter((f) => !['text', 'checked', 'sort_order'].includes(f.key))
  const visibleColumns = columnFields.filter((f) => !hiddenCols.has(f.key))

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
          {/* View mode: List / Table */}
          <div className="flex overflow-hidden rounded-md border border-border">
            <button aria-label="List view" onClick={() => setMode('list')}
              className={'flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-colors ' +
                (viewMode === 'list' ? 'bg-primary text-on-primary' : 'text-text-muted hover:bg-surface-light hover:text-text')}>
              <List size={17} aria-hidden /><span className="hidden sm:inline">List</span>
            </button>
            <button aria-label="Table view" onClick={() => setMode('table')}
              className={'flex items-center gap-1.5 border-l border-border px-3 py-1.5 text-sm font-medium transition-colors ' +
                (viewMode === 'table' ? 'bg-primary text-on-primary' : 'text-text-muted hover:bg-surface-light hover:text-text')}>
              <Table2 size={17} aria-hidden /><span className="hidden sm:inline">Table</span>
            </button>
          </div>
          {/* Column visibility editor (the "edit the view" control) */}
          {viewMode === 'table' && columnFields.length > 0 && (
            <div className="relative">
              <Button variant="ghost" size="sm" onClick={() => setColMenuOpen((o) => !o)} aria-label="Edit columns">
                <SlidersHorizontal size={15} aria-hidden /> Columns
              </Button>
              {colMenuOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setColMenuOpen(false)} />
                  <div className="absolute right-0 z-50 mt-1 w-48 rounded-lg border border-border bg-surface p-2 shadow-xl">
                    <p className="px-1 pb-1 text-xs text-text-muted">Show columns</p>
                    {columnFields.map((f) => (
                      <label key={f.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-surface-light/50">
                        <input type="checkbox" checked={!hiddenCols.has(f.key)} onChange={() => toggleCol(f.key)} />
                        {f.label}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
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
        ) : viewMode === 'table' ? (
          <TableView groups={groups} columns={visibleColumns} onToggle={toggle}
            onRemove={remove} onEdit={setEditing} />
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

function renderCell(field: Field, item: Item): string {
  const raw = field.storage === 'column'
    ? (item as unknown as Record<string, unknown>)[field.key]
    : item.attributes?.[field.key]
  if (raw == null || (Array.isArray(raw) && raw.length === 0)) return '—'
  if (field.col_type === 'checkbox') return raw ? '✓' : '—'
  const label = (v: unknown) => field.options?.find((o) => String(o.value) === String(v))?.label ?? String(v)
  if (field.col_type === 'single_select') return label(raw)
  if (field.col_type === 'multi_select' && Array.isArray(raw)) return raw.map(label).join(', ')
  if (field.col_type === 'date') return String(raw).slice(0, 10)
  return String(raw)
}

function TableView({ groups, columns, onToggle, onRemove, onEdit }: {
  groups: Group[]
  columns: Field[]
  onToggle: (i: Item) => void
  onRemove: (i: Item) => void
  onEdit: (i: Item) => void
}) {
  const visible = groups.filter((g) => g.items.length > 0)
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-text-muted">
            <th className="w-8 px-2 py-2" />
            <th className="px-2 py-2 font-semibold">Item</th>
            {columns.map((c) => <th key={c.key} className="px-2 py-2 font-semibold">{c.label}</th>)}
            <th className="w-16 px-2 py-2" />
          </tr>
        </thead>
        <tbody>
          {visible.map((g) => (
            <FragmentGroup key={g.key ?? '__none__'} group={g} colSpan={columns.length + 3}
              columns={columns} onToggle={onToggle} onRemove={onRemove} onEdit={onEdit} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FragmentGroup({ group, colSpan, columns, onToggle, onRemove, onEdit }: {
  group: Group
  colSpan: number
  columns: Field[]
  onToggle: (i: Item) => void
  onRemove: (i: Item) => void
  onEdit: (i: Item) => void
}) {
  return (
    <>
      {group.label && (
        <tr><td colSpan={colSpan}
          className="px-2 pb-1 pt-4 text-xs font-semibold uppercase tracking-wider text-text-muted">{group.label}</td></tr>
      )}
      {group.items.map((i) => (
        <tr key={i.id} className="group border-b border-border/50 hover:bg-surface-light/40">
          <td className="px-2 py-2">
            <button onClick={() => onToggle(i)} aria-label={i.checked ? `Uncheck ${i.text}` : `Check ${i.text}`}
              className={'flex h-5 w-5 items-center justify-center rounded border ' +
                (i.checked ? 'border-primary bg-primary text-on-primary' : 'border-border hover:border-primary')}>
              {i.checked && <Check size={14} aria-hidden />}
            </button>
          </td>
          <td className={'px-2 py-2 ' + (i.checked ? 'text-text-muted line-through' : '')}>
            {i.text}{i.quantity && <span className="ml-1 text-xs text-text-muted">({i.quantity})</span>}
          </td>
          {columns.map((c) => <td key={c.key} className="px-2 py-2 text-text-muted">{renderCell(c, i)}</td>)}
          <td className="px-2 py-2">
            <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100">
              <button onClick={() => onEdit(i)} aria-label={`Edit ${i.text}`}
                className="rounded p-1 text-text-muted hover:text-text"><Pencil size={14} /></button>
              <button onClick={() => onRemove(i)} aria-label={`Remove ${i.text}`}
                className="rounded p-1 text-text-muted hover:text-danger"><Trash2 size={14} /></button>
            </div>
          </td>
        </tr>
      ))}
    </>
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
