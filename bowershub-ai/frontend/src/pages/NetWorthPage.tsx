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
  type NetWorth,
  type NetWorthPoint,
} from '../services/financeAccounting'

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}

function errorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? 'Something went wrong'
}

function Sparkline({ points }: { points: NetWorthPoint[] }) {
  if (points.length < 2) return <span style={{ color: 'var(--color-text-muted)' }}>Not enough history yet</span>
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
    <svg width={w} height={h} style={{ display: 'block' }}>
      <path d={d} fill="none" stroke="var(--color-primary, #468)" strokeWidth={2} />
    </svg>
  )
}

export default function NetWorthPage() {
  const navigate = useNavigate()
  const [nw, setNw] = useState<NetWorth | null>(null)
  const [history, setHistory] = useState<NetWorthPoint[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [n, h] = await Promise.all([financeAccounting.getNetWorth(), financeAccounting.getHistory()])
      setNw(n)
      setHistory(h)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const setType = async (id: string, type: string) => {
    try {
      await financeAccounting.setAccountType(id, type)
      toast.success('Account type set')
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
    <div style={{ padding: 24, maxWidth: 880, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Net Worth</h1>
        <button onClick={() => navigate('/dashboard')} style={{ fontSize: 13 }}>← Dashboard</button>
      </div>

      {loading || !nw ? <p>Loading…</p> : (
        <>
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', marginBottom: 8, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Net Worth</div>
              <div style={{ fontSize: 28, fontWeight: 700 }}>{money(nw.net_worth)}</div>
            </div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              Assets {money(nw.assets)} · Liabilities {money(nw.liabilities)}
            </div>
            <div style={{ marginLeft: 'auto' }}><Sparkline points={history} /></div>
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
        </>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 6 }}>{title}</h2>
      <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>{children}</ul>
    </div>
  )
}

function Row({ acc, children }: { acc: AccountBalance; children?: React.ReactNode }) {
  return (
    <li data-testid="account-row" style={{
      display: 'flex', gap: 12, alignItems: 'center', padding: 10,
      border: '1px solid var(--color-border, #333)', borderRadius: 8,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>{acc.name}</div>
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', display: 'flex', gap: 8 }}>
          <span>{acc.org}</span>
          {acc.account_type && <span>· {acc.account_type}</span>}
          {acc.as_of && <span>· as of {acc.as_of}</span>}
          {acc.stale && <span data-testid="stale" style={{ color: '#c84' }}>· stale</span>}
        </div>
      </div>
      <div style={{ textAlign: 'right', minWidth: 100, fontWeight: 600 }}>{money(acc.balance)}</div>
      {children}
    </li>
  )
}

function ReconcileInline({ onReconcile }: { onReconcile: (v: string) => void }) {
  const [val, setVal] = useState('')
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      <input aria-label="Statement balance" placeholder="stmt $" value={val}
             onChange={(e) => setVal(e.target.value)} style={{ width: 80, fontSize: 12 }} />
      <button disabled={val === ''} onClick={() => onReconcile(val)} style={{ fontSize: 12 }}>Reconcile</button>
    </div>
  )
}
