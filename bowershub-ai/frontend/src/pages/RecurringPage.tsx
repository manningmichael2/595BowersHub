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
    <div className="max-w-[820px] mx-auto p-4">
      <h2 className="text-base font-semibold mb-3 text-text">Recurring charges</h2>
      {loading ? <p className="text-text-muted">Loading…</p> : recurring.length === 0 ? (
        <p data-testid="empty-recurring" className="text-text-muted">No recurring charges detected.</p>
      ) : (
        <ul className="list-none p-0 flex flex-col gap-1.5">
          {recurring.map((r) => (
            <li
              key={r.merchant_key}
              data-testid="recurring-row"
              className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2.5 rounded-lg border border-border"
            >
              <MerchantLogo merchantKey={r.merchant_key} />
              <span className="flex-1 min-w-0 font-semibold text-text break-words">{r.merchant_key}</span>
              <span className="text-text-muted">{r.occurrences}×</span>
              <span className="text-text">{money(r.avg_amount)}</span>
              {r.avg_interval_days != null && <span className="text-text-muted">~{Math.round(r.avg_interval_days)}d</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
