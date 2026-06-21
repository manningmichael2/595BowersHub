/**
 * RecurringPage — detected recurring charges (relocated from the old Review tab).
 * Read-only list: merchant, occurrences, average amount, cadence.
 */
import { useEffect, useState } from 'react'
import MerchantLogo from '../components/MerchantLogo'
import { toast } from '../stores/toast'
import { financeReview, type RecurringCharge } from '../services/financeReview'

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}

export default function RecurringPage() {
  const [recurring, setRecurring] = useState<RecurringCharge[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    financeReview.getRecurring()
      .then(setRecurring)
      .catch((e) => toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load recurring'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div style={{ padding: 16, maxWidth: 820, margin: '0 auto' }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Recurring charges</h2>
      {loading ? <p>Loading…</p> : recurring.length === 0 ? (
        <p data-testid="empty-recurring">No recurring charges detected.</p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {recurring.map((r) => (
            <li key={r.merchant_key} data-testid="recurring-row" style={{
              display: 'flex', gap: 12, alignItems: 'center', padding: 10,
              border: '1px solid var(--color-border, #333)', borderRadius: 8,
            }}>
              <MerchantLogo merchantKey={r.merchant_key} />
              <span style={{ flex: 1, fontWeight: 600 }}>{r.merchant_key}</span>
              <span style={{ color: 'var(--color-text-muted)' }}>{r.occurrences}×</span>
              <span>{money(r.avg_amount)}</span>
              {r.avg_interval_days != null && <span style={{ color: 'var(--color-text-muted)' }}>~{Math.round(r.avg_interval_days)}d</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
