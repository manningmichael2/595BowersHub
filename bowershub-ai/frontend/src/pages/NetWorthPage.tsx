/**
 * NetWorthPage — the accounting surface (finance-accounting Task 9, R3.7/R2.5/R4.1).
 *
 * Net worth + asset/liability breakdown (account_type-driven), per-account as-of +
 * stale flags, inline set-type for untyped accounts, per-account reconcile, and a
 * net-worth trend sparkline. Typed against financeAccounting — no `any`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from '../stores/toast'
import {
  financeAccounting,
  ACCOUNT_TYPES,
  type AccountBalance,
  type AccountOwner,
  type NetWorth,
  type NetWorthPoint,
} from '../services/financeAccounting'
import { api } from '../services/api'
import { useHasRole } from '../hooks/useHasRole'

interface HouseholdUser { id: number; display_name: string }

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}

function errorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? 'Something went wrong'
}

function Sparkline({ points }: { points: NetWorthPoint[] }) {
  if (points.length < 2) return <span className="text-text-muted text-xs">Not enough history yet</span>
  const vals = points.map((p) => p.net_worth)
  const min = Math.min(...vals), max = Math.max(...vals)
  const range = max - min || 1
  const w = 240, h = 40
  const d = points.map((p, i) => {
    const x = (i / (points.length - 1)) * w
    const y = h - ((p.net_worth - min) / range) * h
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg width={w} height={h} className="block">
      <path d={d} fill="none" stroke="var(--color-primary)" strokeWidth={2} />
    </svg>
  )
}

export default function NetWorthPage() {
  const navigate = useNavigate()
  const isAdmin = useHasRole('admin')
  const [nw, setNw] = useState<NetWorth | null>(null)
  const [history, setHistory] = useState<NetWorthPoint[]>([])
  const [loading, setLoading] = useState(true)
  // Owner assignment is an admin setup task (household): tag whose account it is.
  const [accounts, setAccounts] = useState<AccountOwner[]>([])
  const [users, setUsers] = useState<HouseholdUser[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [n, h] = await Promise.all([financeAccounting.getNetWorth(), financeAccounting.getHistory()])
      setNw(n)
      setHistory(h)
      if (isAdmin) {
        const [accts, usersRes] = await Promise.all([
          financeAccounting.listAccounts(),
          api.get('/api/admin/users'),
        ])
        setAccounts(accts)
        const rows = usersRes.data as HouseholdUser[]
        setUsers(rows.map((u) => ({ id: u.id, display_name: u.display_name })))
      }
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [isAdmin])

  useEffect(() => { void load() }, [load])

  const setType = async (id: string, type: string) => {
    try {
      await financeAccounting.setAccountType(id, type)
      toast.success('Account type set')
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }

  const setOwner = async (id: string, ownerId: number | null) => {
    try {
      await financeAccounting.setAccountOwner(id, ownerId)
      toast.success('Account owner set')
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }

  const reconcile = async (id: string, raw: string) => {
    const bal = Number(raw)
    if (Number.isNaN(bal)) { toast.error('Enter a numeric statement balance'); return }
    try {
      const r = await financeAccounting.reconcile(id, new Date().toISOString().slice(0, 10), bal)
      toast.success(r.in_sync ? 'Reconciled — in sync ✓' : `Recorded — drift ${money(r.delta ?? 0)}`)
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }

  const { assets, liabilities, needsType } = useMemo(() => {
    const a: AccountBalance[] = [], l: AccountBalance[] = [], n: AccountBalance[] = []
    for (const acc of nw?.accounts ?? []) {
      if (acc.classification === 'needs_type') n.push(acc)
      else if (acc.classification === 'liability') l.push(acc)
      else a.push(acc)
    }
    return { assets: a, liabilities: l, needsType: n }
  }, [nw])

  return (
    <div className="max-w-[880px] mx-auto p-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-text">Net Worth</h1>
        <button onClick={() => navigate('/dashboard')} className="text-xs text-text-muted hover:text-text">← Dashboard</button>
      </div>

      {loading || !nw ? <p className="text-text-muted">Loading…</p> : (
        <>
          <div className="flex flex-wrap items-end gap-6 mb-2">
            <div>
              <div className="text-xs text-text-muted">Net Worth</div>
              <div className="text-3xl font-bold text-text">{money(nw.net_worth)}</div>
            </div>
            <div className="text-xs text-text-muted">
              Assets {money(nw.assets)} · Liabilities {money(nw.liabilities)}
            </div>
            <div className="ml-auto"><Sparkline points={history} /></div>
          </div>

          {needsType.length > 0 && (
            <Section title="Needs account type">
              {needsType.map((a) => (
                <Row key={a.id} acc={a}>
                  <select aria-label={`Type for ${a.name}`} defaultValue=""
                          onChange={(e) => e.target.value && setType(a.id, e.target.value)}>
                    <option value="">Set type…</option>
                    {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Row>
              ))}
            </Section>
          )}

          <Section title="Assets">
            {assets.map((a) => <Row key={a.id} acc={a}><ReconcileInline onReconcile={(v) => reconcile(a.id, v)} /></Row>)}
          </Section>
          <Section title="Liabilities">
            {liabilities.map((a) => <Row key={a.id} acc={a}><ReconcileInline onReconcile={(v) => reconcile(a.id, v)} /></Row>)}
          </Section>

          {isAdmin && accounts.length > 0 && (
            <div className="mt-6">
              <h2 className="text-sm font-semibold text-text-muted mb-1">Account owners</h2>
              <p className="text-xs text-text-muted mb-1.5">
                Tag whose account each is (for filtering). Display only — everyone still sees all finances.
              </p>
              <ul className="list-none p-0 flex flex-col gap-1.5">
                {accounts.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2.5 rounded-lg border border-border">
                    <div className="flex-1 min-w-[10rem]">
                      <div className="font-semibold text-text break-words">{a.name}</div>
                      <div className="text-xs text-text-muted">{a.org}</div>
                    </div>
                    <select
                      aria-label={`Owner for ${a.name}`}
                      className="text-xs rounded border border-border bg-surface px-2 py-1 text-text"
                      value={a.owner_id == null ? '' : String(a.owner_id)}
                      onChange={(e) => setOwner(a.id, e.target.value === '' ? null : Number(e.target.value))}
                    >
                      <option value="">Joint / Shared</option>
                      {users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
                    </select>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <h2 className="text-sm font-semibold text-text-muted mb-1.5">{title}</h2>
      <ul className="list-none p-0 flex flex-col gap-1.5">{children}</ul>
    </div>
  )
}

function Row({ acc, children }: { acc: AccountBalance; children?: React.ReactNode }) {
  return (
    <li data-testid="account-row" className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2.5 rounded-lg border border-border">
      <div className="flex-1 min-w-[10rem]">
        <div className="font-semibold text-text break-words">{acc.name}</div>
        <div className="text-xs text-text-muted flex flex-wrap gap-2">
          <span>{acc.org}</span>
          {acc.account_type && <span>· {acc.account_type}</span>}
          {acc.as_of && <span>· as of {acc.as_of}</span>}
          {acc.stale && <span data-testid="stale" className="text-warning">· stale</span>}
        </div>
      </div>
      <div className="text-right min-w-[100px] font-semibold text-text">{money(acc.balance)}</div>
      {children}
    </li>
  )
}

function ReconcileInline({ onReconcile }: { onReconcile: (v: string) => void }) {
  const [val, setVal] = useState('')
  return (
    <div className="flex gap-1">
      <input
        aria-label="Statement balance"
        placeholder="stmt $"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        className="w-20 text-xs rounded border border-border bg-surface px-2 py-1 text-text"
      />
      <button disabled={val === ''} onClick={() => onReconcile(val)} className="text-xs rounded border border-border px-2 py-1 text-text disabled:opacity-50">Reconcile</button>
    </div>
  )
}
