import { useState } from 'react'
import { api } from '../../services/api'
import { useEndpointData, SectionStateGuard } from './AdminCommon'

export interface AdminModel {
  id: number                            // numeric row id — the PATCH key
  model_id: string
  provider: string
  display_name: string
  input_cost_per_mtok: number | null    // $/MTok (admin-only — not in the public DTO)
  output_cost_per_mtok: number | null
  ref_input_cost: number | null         // canonical reference from bh_model_price_rules (0006)
  ref_output_cost: number | null
  needs_price_confirmation: boolean
  is_active: boolean
  roles: string[]
}

export default function ModelsSection() {
  // Admin catalog view (/api/admin/models, prices + per-row canonical reference) with
  // inline editing — prices save on blur/Enter; flagged rows get a one-click Confirm.
  const { data, isLoading, error, reload } = useEndpointData<AdminModel[]>('/api/admin/models')
  const [refreshing, setRefreshing] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const handleRefresh = async () => {
    setRefreshing(true)
    setResult(null)
    setActionError(null)
    try {
      const res = await api.post('/api/admin/models/refresh')
      const s = res.data
      setResult(
        `Refresh ${s.complete ? 'complete' : 'partial (some sources errored — nothing deactivated)'} — ` +
          `${s.added} added, ${s.reactivated} reactivated, ${s.deactivated} deactivated, ` +
          `${s.price_flagged} price-flagged.`,
      )
      await reload()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Refresh failed')
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-sm font-medium text-gray-300">Model Catalog</h3>
          <p className="text-xs text-gray-500 mt-0.5 max-w-xl">
            DB-driven model list with operator-owned prices ($/MTok). Edit a price (saves on
            Enter or when you click away) or, for a flagged row whose price already matches the
            reference, just hit <span className="text-amber-300">Confirm</span>. The reference
            column is Anthropic's published rate. Refresh discovers models from the Anthropic
            Models API + Ollama, preserving your prices.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-3 py-2 rounded-lg text-sm bg-indigo-500/15 text-indigo-200 hover:bg-indigo-500/25 border border-indigo-500/30 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
        >
          {refreshing ? 'Refreshing…' : '↻ Refresh now'}
        </button>
      </div>

      {result && (
        <div className="bg-green-900/20 border border-green-800 rounded-lg px-4 py-2 text-sm text-green-300 mb-4">
          {result}
        </div>
      )}
      {actionError && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-2 text-sm text-red-300 mb-4">
          {actionError}
        </div>
      )}

      <SectionStateGuard isLoading={isLoading} error={error}>
        <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-4 py-2 text-gray-400">Model ID</th>
                <th className="text-left px-3 py-2 text-gray-400">Provider</th>
                <th className="text-left px-3 py-2 text-gray-400">Roles</th>
                <th className="text-right px-3 py-2 text-gray-400">In $/MTok</th>
                <th className="text-right px-3 py-2 text-gray-400">Out $/MTok</th>
                <th className="text-right px-3 py-2 text-gray-400">Reference</th>
                <th className="text-left px-3 py-2 text-gray-400"></th>
              </tr>
            </thead>
            <tbody>
              {data && data.length > 0 ? (
                data.map(m => <ModelRow key={m.id} model={m} onSaved={reload} />)
              ) : (
                <tr>
                  <td colSpan={7} className="px-4 py-4 text-center text-gray-500">
                    No models
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionStateGuard>
    </div>
  )
}

function fmtRate(v: number | null): string {
  return v == null ? '' : String(Number(v))
}

function ModelRow({ model, onSaved }: { model: AdminModel; onSaved: () => Promise<void> | void }) {
  const [inCost, setInCost] = useState(fmtRate(model.input_cost_per_mtok))
  const [outCost, setOutCost] = useState(fmtRate(model.output_cost_per_mtok))
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const dirty = inCost !== fmtRate(model.input_cost_per_mtok) || outCost !== fmtRate(model.output_cost_per_mtok)
  const valid = inCost.trim() !== '' && outCost.trim() !== '' && !isNaN(Number(inCost)) && !isNaN(Number(outCost))

  const patch = async (body: Record<string, unknown>) => {
    setBusy(true)
    setErr(null)
    try {
      await api.patch(`/api/admin/models/${model.id}`, body)
      await onSaved()
      setFlash(true)
      setTimeout(() => setFlash(false), 1500)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Failed')
    } finally {
      setBusy(false)
    }
  }

  // Commit an edit on blur / Enter — only when changed + valid. Editing a price is an
  // explicit confirmation, so clear the unconfirmed flag at the same time.
  const commitEdit = () => {
    if (!dirty || !valid || busy) return
    patch({ input_cost_per_mtok: Number(inCost), output_cost_per_mtok: Number(outCost), needs_price_confirmation: false })
  }
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
  }

  const refIn = model.ref_input_cost
  const refOut = model.ref_output_cost
  const refStr = refIn == null ? '—' : `$${Number(refIn).toFixed(2)} / $${Number(refOut).toFixed(2)}`
  const matchesRef =
    refIn != null &&
    Number(model.input_cost_per_mtok) === Number(refIn) &&
    Number(model.output_cost_per_mtok) === Number(refOut)

  const cell = 'w-20 bg-[#1a1a2e] border border-gray-700 rounded px-2 py-1 text-right text-gray-200 focus:border-indigo-500 focus:outline-none'
  return (
    <tr className={'border-b border-gray-800/50 ' + (model.is_active ? '' : 'opacity-50')}>
      <td className="px-4 py-2 text-gray-300 font-mono text-xs">
        {model.model_id}
        {model.needs_price_confirmation && (
          <span className="ml-2 text-amber-400" title="Provisional price — Confirm, or edit to set">⚠</span>
        )}
        {!model.is_active && <span className="ml-2 text-gray-600">(inactive)</span>}
      </td>
      <td className="px-3 py-2 text-gray-400">{model.provider}</td>
      <td className="px-3 py-2 text-indigo-300 text-xs">{model.roles?.join(', ')}</td>
      <td className="px-3 py-2 text-right">
        <input className={cell} value={inCost} disabled={busy} inputMode="decimal"
               onChange={e => setInCost(e.target.value)} onBlur={commitEdit} onKeyDown={onKey} />
      </td>
      <td className="px-3 py-2 text-right">
        <input className={cell} value={outCost} disabled={busy} inputMode="decimal"
               onChange={e => setOutCost(e.target.value)} onBlur={commitEdit} onKeyDown={onKey} />
      </td>
      <td className={'px-3 py-2 text-right text-xs whitespace-nowrap ' + (matchesRef ? 'text-gray-500' : 'text-amber-300')}
          title={matchesRef ? 'matches reference' : 'differs from reference'}>
        {refStr}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {model.needs_price_confirmation && !dirty && (
          <button onClick={() => patch({ needs_price_confirmation: false })} disabled={busy}
                  className="px-2.5 py-1 rounded text-xs bg-amber-500/15 text-amber-200 hover:bg-amber-500/25 border border-amber-500/30 disabled:opacity-40">
            {busy ? '…' : 'Confirm'}
          </button>
        )}
        {flash && <span className="text-green-400 text-xs">✓ saved</span>}
        {err && <span className="text-red-400 text-xs">{err}</span>}
      </td>
    </tr>
  )
}
