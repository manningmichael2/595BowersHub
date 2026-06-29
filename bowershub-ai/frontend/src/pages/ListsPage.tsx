/**
 * ListsPage — household-shared shopping / to-do / packing lists.
 *
 * The same lists are driven by the chat `list` skill ("add milk to the list");
 * this is the visual surface. Lists are shared household-wide (migration 0049),
 * so what one member adds or checks off, the other sees. Item operations are
 * id-based via /api/lists (the chat path is fuzzy-text).
 */
import { useEffect, useState, useCallback } from 'react'
import { Check, Trash2, Plus } from 'lucide-react'
import { api } from '../services/api'
import { toast } from '../stores/toast'
import { Button, Input, Spinner, Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui'

interface Item {
  id: number
  text: string
  quantity: string | null
  checked: boolean
  added_by: string | null
}

interface ListSummary {
  name: string
  pending: number
  done: number
}

export default function ListsPage() {
  const [lists, setLists] = useState<ListSummary[]>([])
  const [active, setActive] = useState('shopping')
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const loadLists = useCallback(async () => {
    try {
      const res = await api.get('/api/lists')
      setLists(res.data.lists ?? [])
    } catch {
      /* non-fatal — the active list still loads */
    }
  }, [])

  const loadItems = useCallback(async (name: string) => {
    setLoading(true)
    try {
      const res = await api.get(`/api/lists/${encodeURIComponent(name)}`)
      setItems(res.data.items ?? [])
    } catch (err: any) {
      toast.error(`Couldn't load the ${name} list: ${err.response?.data?.detail || 'error'}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadLists()
  }, [loadLists])
  useEffect(() => {
    loadItems(active)
  }, [active, loadItems])

  const addItem = async () => {
    const text = draft.trim()
    if (!text) return
    setBusy(true)
    setDraft('')
    try {
      const res = await api.post(`/api/lists/${encodeURIComponent(active)}/items`, {
        items: [text],
      })
      setItems(res.data.items ?? [])
      loadLists()
    } catch (err: any) {
      toast.error(`Couldn't add: ${err.response?.data?.detail || 'error'}`)
      setDraft(text) // restore so it isn't lost
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (item: Item) => {
    // Optimistic
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, checked: !i.checked } : i)))
    try {
      await api.put(`/api/lists/items/${item.id}`, { checked: !item.checked })
    } catch {
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, checked: item.checked } : i)))
      toast.error("Couldn't update that item.")
    }
  }

  const remove = async (item: Item) => {
    setItems((prev) => prev.filter((i) => i.id !== item.id))
    try {
      await api.delete(`/api/lists/items/${item.id}`)
    } catch {
      toast.error("Couldn't remove that item.")
      loadItems(active)
    }
  }

  const clearChecked = async () => {
    setBusy(true)
    try {
      const res = await api.post(`/api/lists/${encodeURIComponent(active)}/clear`)
      setItems(res.data.items ?? [])
      loadLists()
    } catch {
      toast.error("Couldn't clear checked items.")
    } finally {
      setBusy(false)
    }
  }

  const unchecked = items.filter((i) => !i.checked)
  const checked = items.filter((i) => i.checked)
  // Ensure the active list is selectable even before it's in the summary.
  const listNames = Array.from(new Set([active, ...lists.map((l) => l.name)]))

  return (
    <div className="flex h-full flex-col bg-surface text-text">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <h1 className="text-lg font-medium">Lists</h1>
        <Select value={active} onValueChange={setActive}>
          <SelectTrigger className="w-44" aria-label="Choose list">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {listNames.map((n) => (
              <SelectItem key={n} value={n}>
                {n.charAt(0).toUpperCase() + n.slice(1)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {checked.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clearChecked} disabled={busy} className="ml-auto">
            Clear {checked.length} checked
          </Button>
        )}
      </div>

      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 overflow-y-auto p-4">
        {/* Add row */}
        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addItem()}
            placeholder={`Add to ${active}…`}
            aria-label="Add item"
          />
          <Button onClick={addItem} disabled={busy || !draft.trim()} size="icon" aria-label="Add">
            <Plus size={18} aria-hidden />
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-text-muted">
            <Spinner /> Loading…
          </div>
        ) : items.length === 0 ? (
          <p className="py-8 text-center text-sm text-text-muted">
            Nothing on the {active} list yet. Add an item above — or just tell the assistant
            “add milk to the list”.
          </p>
        ) : (
          <ul className="space-y-1">
            {unchecked.map((i) => (
              <ItemRow key={i.id} item={i} onToggle={toggle} onRemove={remove} />
            ))}
            {checked.length > 0 && (
              <>
                <li className="px-1 pt-3 text-xs uppercase tracking-wider text-text-muted">
                  Checked off
                </li>
                {checked.map((i) => (
                  <ItemRow key={i.id} item={i} onToggle={toggle} onRemove={remove} />
                ))}
              </>
            )}
          </ul>
        )}
      </div>
    </div>
  )
}

function ItemRow({
  item,
  onToggle,
  onRemove,
}: {
  item: Item
  onToggle: (i: Item) => void
  onRemove: (i: Item) => void
}) {
  return (
    <li className="group flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-surface-light/50">
      <button
        onClick={() => onToggle(item)}
        aria-label={item.checked ? `Uncheck ${item.text}` : `Check ${item.text}`}
        className={
          'flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ' +
          (item.checked
            ? 'border-primary bg-primary text-on-primary'
            : 'border-border hover:border-primary')
        }
      >
        {item.checked && <Check size={14} aria-hidden />}
      </button>
      <span className={'flex-1 text-sm ' + (item.checked ? 'text-text-muted line-through' : 'text-text')}>
        {item.text}
        {item.quantity && <span className="ml-2 text-xs text-text-muted">({item.quantity})</span>}
      </span>
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
