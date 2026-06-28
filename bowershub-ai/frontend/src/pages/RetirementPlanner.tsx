/**
 * RetirementPlanner — reactive retirement projection (R4.4, R4.6, R4.7, R4.8, R5.2).
 *
 * Every field is user-entered and drives a live recompute: editing any input
 * re-projects (debounced) and updates the balance-over-time chart + stats. A
 * prominent disclaimer rides every projection (R4.6); before the minimum inputs
 * exist, a setup state shows instead of a fabricated projection (R4.8).
 * Tokenized Tailwind; the chart is a dependency-free inline SVG.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from '../stores/toast'
import {
  financeRetirement, type Projection, type RetirementFields,
} from '../services/financeRetirement'

const EMPTY: RetirementFields = {
  current_age: null, retirement_age: null, current_balance: null, annual_salary: null,
  annual_contribution: null, annual_expenses: null, expected_return: null,
  inflation: null, withdrawal_rate: null, end_age: null,
}

const money = (n: number) => `$${Math.round(n).toLocaleString()}`

/** Round to cents (2 decimals). */
const round2 = (n: number) => Math.round(n * 100) / 100

/** Dollar fields — kept at 2 decimals (the % and age fields are not). */
const MONEY_KEYS: (keyof RetirementFields)[] = [
  'current_balance', 'annual_salary', 'annual_contribution', 'annual_expenses',
]

export default function RetirementPlanner() {
  const [fields, setFields] = useState<RetirementFields>(EMPTY)
  const [projection, setProjection] = useState<Projection | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    financeRetirement
      .getInputs()
      .then(({ prefill }) => {
        // Account-derived dollar prefills can carry float noise — snap to cents.
        const cleaned = { ...prefill }
        for (const k of MONEY_KEYS) {
          const v = cleaned[k]
          if (typeof v === 'number') cleaned[k] = round2(v)
        }
        setFields({ ...EMPTY, ...cleaned })
      })
      .catch(() => toast.error('Could not load your retirement inputs.'))
      .finally(() => setLoaded(true))
  }, [])

  // Reactive recompute: any field change re-projects (debounced) — R4.7.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!loaded) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        setProjection(await financeRetirement.project(fields))
      } catch {
        toast.error('Projection failed.')
      }
    }, 250)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [fields, loaded])

  const set = useCallback(
    (k: keyof RetirementFields, raw: string, isPct = false) => {
      // Dollar/age fields snap to 2 decimals; percents stay full-precision
      // (they're stored as fractions, e.g. 7.25% → 0.0725).
      const v = raw === '' ? null : isPct ? Number(raw) / 100 : round2(Number(raw))
      setFields((f) => ({ ...f, [k]: Number.isNaN(v as number) ? null : v }))
    },
    [],
  )

  const needsInputs = projection?.needs_inputs === true

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-lg font-semibold text-text mb-1">Retirement Planner</h1>
      <p className="text-sm text-text-muted mb-4">
        Tune any field — the projection updates live. Numbers are estimates, not advice.
      </p>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-md border border-border bg-surface px-4 py-3">
          <div className="text-sm font-medium text-text mb-3">Your numbers</div>
          <div className="grid grid-cols-2 gap-3">
            <NumField label="Current age" v={fields.current_age} onChange={(r) => set('current_age', r)} />
            <NumField label="Retirement age" v={fields.retirement_age} onChange={(r) => set('retirement_age', r)} testid="ret-age" />
            <NumField label="Current balance" v={fields.current_balance} onChange={(r) => set('current_balance', r)} prefix="$" />
            <NumField label="Annual salary" v={fields.annual_salary} onChange={(r) => set('annual_salary', r)} prefix="$" />
            <NumField label="Annual contribution" v={fields.annual_contribution} onChange={(r) => set('annual_contribution', r)} prefix="$" />
            <NumField label="Annual spend (retired)" v={fields.annual_expenses} onChange={(r) => set('annual_expenses', r)} prefix="$" />
            <NumField label="Return %" v={pct(fields.expected_return)} onChange={(r) => set('expected_return', r, true)} suffix="%" />
            <NumField label="Inflation %" v={pct(fields.inflation)} onChange={(r) => set('inflation', r, true)} suffix="%" />
            <NumField label="Withdrawal %" v={pct(fields.withdrawal_rate)} onChange={(r) => set('withdrawal_rate', r, true)} suffix="%" />
            <NumField label="Plan to age" v={fields.end_age} onChange={(r) => set('end_age', r)} />
          </div>
          <button
            type="button"
            onClick={async () => {
              try {
                await financeRetirement.saveInputs(fields)
                toast.success('Inputs saved.')
              } catch {
                toast.error('Could not save inputs.')
              }
            }}
            className="mt-3 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-on-primary"
          >
            Save inputs
          </button>
        </section>

        <section className="rounded-md border border-border bg-surface px-4 py-3">
          {needsInputs ? (
            <div className="text-sm text-text-muted py-8 text-center" data-testid="ret-setup">
              Enter your age, retirement age, balance, contribution, and expected spend to see a
              projection.
            </div>
          ) : projection?.series ? (
            <div data-testid="ret-projection">
              <BalanceChart series={projection.series} retirementAge={projection.retirement_age} />
              <Stats p={projection} />
            </div>
          ) : (
            <div className="text-sm text-text-muted py-8 text-center">Loading projection…</div>
          )}
        </section>
      </div>

      {projection?.disclaimer && (
        <p className="mt-4 rounded-md border border-border bg-surface-dark px-3 py-2 text-xs text-text-muted" data-testid="ret-disclaimer">
          ⚠️ {projection.disclaimer}
        </p>
      )}
    </div>
  )
}

function pct(v: number | null): number | null {
  return v == null ? null : Math.round(v * 1000) / 10
}

function NumField(props: {
  label: string
  v: number | null
  onChange: (raw: string) => void
  prefix?: string
  suffix?: string
  testid?: string
}) {
  return (
    <label className="text-xs text-text-muted">
      {props.label}
      <div className="mt-0.5 flex items-center rounded border border-border bg-surface">
        {props.prefix && <span className="pl-2 text-text-muted">{props.prefix}</span>}
        <input
          type="number"
          value={props.v ?? ''}
          onChange={(e) => props.onChange(e.target.value)}
          data-testid={props.testid}
          className="w-full bg-transparent px-2 py-1 text-sm text-text focus:outline-none"
        />
        {props.suffix && <span className="pr-2 text-text-muted">{props.suffix}</span>}
      </div>
    </label>
  )
}

function Stats({ p }: { p: Projection }) {
  const gap = p.surplus_or_gap ?? 0
  return (
    <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
      <Stat label="Balance at retirement" value={money(p.retirement_balance ?? 0)} />
      <Stat label="FIRE target" value={money(p.fire_target ?? 0)} />
      <Stat
        label={gap >= 0 ? 'Surplus' : 'Gap'}
        value={money(Math.abs(gap))}
        tone={gap >= 0 ? 'ok' : 'bad'}
      />
      <Stat
        label="To close the gap / month"
        value={p.required_monthly_contribution ? money(p.required_monthly_contribution) : '—'}
      />
      {p.depletion_age != null && <Stat label="Money runs out at age" value={String(p.depletion_age)} tone="bad" />}
    </dl>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'bad' }) {
  const color = tone === 'ok' ? 'var(--color-primary)' : tone === 'bad' ? 'var(--color-danger)' : 'var(--color-text)'
  return (
    <div>
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className="font-semibold" style={{ color }}>
        {value}
      </dd>
    </div>
  )
}

function BalanceChart({ series, retirementAge }: { series: { age: number; balance: number }[]; retirementAge?: number }) {
  const { path, retX, w, h } = useMemo(() => {
    const W = 320
    const H = 140
    if (series.length < 2) return { path: '', retX: null as number | null, w: W, h: H }
    const ages = series.map((s) => s.age)
    const bals = series.map((s) => s.balance)
    const minA = Math.min(...ages)
    const maxA = Math.max(...ages)
    const maxB = Math.max(...bals, 1)
    const x = (a: number) => ((a - minA) / (maxA - minA)) * W
    const y = (b: number) => H - (b / maxB) * H
    const d = series.map((s, i) => `${i === 0 ? 'M' : 'L'}${x(s.age).toFixed(1)},${y(s.balance).toFixed(1)}`).join(' ')
    return {
      path: d,
      retX: retirementAge != null ? x(retirementAge) : null,
      w: W,
      h: H,
    }
  }, [series, retirementAge])

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" data-testid="ret-chart" role="img" aria-label="Balance over time">
      <path d={path} fill="none" stroke="var(--color-primary)" strokeWidth={2} />
      {retX != null && (
        <line x1={retX} y1={0} x2={retX} y2={h} stroke="var(--color-text-muted)" strokeDasharray="3 3" strokeWidth={1} />
      )}
    </svg>
  )
}
