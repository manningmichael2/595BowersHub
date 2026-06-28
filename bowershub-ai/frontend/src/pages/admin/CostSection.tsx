import { useEndpointData, SectionStateGuard } from './AdminCommon'

export default function CostSection() {
  const { data, isLoading, error } = useEndpointData<any>('/api/admin/cost?days=7')
  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && <CostSectionInner data={data} />}
    </SectionStateGuard>
  )
}

function CostSectionInner({ data }: { data: any }) {
  const weekTotal = data.daily?.reduce((s: number, d: any) => s + d.total, 0) || 0
  const totalCalls = data.daily?.reduce((s: number, d: any) => s + d.calls, 0) || 0

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        <div className="bg-background rounded-lg border border-border p-4">
          <div className="text-sm text-text-muted">Today</div>
          <div className="text-2xl font-bold text-on-primary mt-1">
            ${(data.today_total || 0).toFixed(4)}
          </div>
        </div>
        <div className="bg-background rounded-lg border border-border p-4">
          <div className="text-sm text-text-muted">7-Day Total</div>
          <div className="text-2xl font-bold text-on-primary mt-1">${weekTotal.toFixed(4)}</div>
        </div>
        <div className="bg-background rounded-lg border border-border p-4">
          <div className="text-sm text-text-muted">Total Calls</div>
          <div className="text-2xl font-bold text-on-primary mt-1">{totalCalls}</div>
        </div>
      </div>

      <h3 className="text-sm font-medium text-text-muted mb-3">Daily Breakdown</h3>
      <div className="bg-background rounded-lg border border-border overflow-x-auto mb-6">
        <table className="w-full text-sm min-w-[400px]">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-2 text-text-muted">Date</th>
              <th className="text-right px-4 py-2 text-text-muted">Cost</th>
              <th className="text-right px-4 py-2 text-text-muted">Calls</th>
            </tr>
          </thead>
          <tbody>
            {data.daily?.length > 0 ? (
              data.daily.map((d: any) => (
                <tr key={d.day} className="border-b border-border/50">
                  <td className="px-4 py-2 text-text-muted">{d.day}</td>
                  <td className="px-4 py-2 text-right text-text-muted">
                    ${d.total.toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right text-text-muted">{d.calls}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={3} className="px-4 py-4 text-center text-text-muted">
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h3 className="text-sm font-medium text-text-muted mb-3">By Model</h3>
      <div className="bg-background rounded-lg border border-border overflow-x-auto mb-6">
        <table className="w-full text-sm min-w-[500px]">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-2 text-text-muted">Model</th>
              <th className="text-right px-4 py-2 text-text-muted">Cost</th>
              <th className="text-right px-4 py-2 text-text-muted">Calls</th>
              <th className="text-right px-4 py-2 text-text-muted">Tokens (in/out)</th>
            </tr>
          </thead>
          <tbody>
            {data.by_model?.length > 0 ? (
              data.by_model.map((m: any) => (
                <tr key={m.model} className="border-b border-border/50">
                  <td className="px-4 py-2 text-text-muted font-mono text-xs">{m.model}</td>
                  <td className="px-4 py-2 text-right text-text-muted">
                    ${m.total.toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right text-text-muted">{m.calls}</td>
                  <td className="px-4 py-2 text-right text-text-muted text-xs">
                    {m.input_tokens}/{m.output_tokens}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4} className="px-4 py-4 text-center text-text-muted">
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h3 className="text-sm font-medium text-text-muted mb-3">By Source</h3>
      <div className="bg-background rounded-lg border border-border overflow-x-auto">
        <table className="w-full text-sm min-w-[400px]">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-2 text-text-muted">Source</th>
              <th className="text-right px-4 py-2 text-text-muted">Cost</th>
              <th className="text-right px-4 py-2 text-text-muted">Calls</th>
            </tr>
          </thead>
          <tbody>
            {data.by_source?.length > 0 ? (
              data.by_source.map((s: any) => (
                <tr key={s.source} className="border-b border-border/50">
                  <td className="px-4 py-2 text-text-muted">{s.source}</td>
                  <td className="px-4 py-2 text-right text-text-muted">
                    ${s.total.toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right text-text-muted">{s.calls}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={3} className="px-4 py-4 text-center text-text-muted">
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
