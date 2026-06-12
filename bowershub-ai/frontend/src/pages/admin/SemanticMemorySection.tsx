import { useEndpointData, SectionStateGuard } from './AdminCommon'

interface Coverage {
  done: number
  total: number
  pct: number
}

interface DeadLetter {
  source_type: string
  source_id: number | string
  error: string
  timestamp: string
}

interface SemanticStatus {
  active: boolean
  error?: string
  model?: string
  config?: Record<string, any>
  stats?: { total: number; done: number; pending: number; dead: number }
  coverage?: { messages: Coverage; entities: Coverage }
  dead_letters?: DeadLetter[]
}

function Bar({ label, cov }: { label: string; cov: Coverage }) {
  const pct = Math.max(0, Math.min(100, cov.pct))
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-300">{label}</span>
        <span className="text-gray-400">
          {cov.done.toLocaleString()} / {cov.total.toLocaleString()} ({pct}%)
        </span>
      </div>
      <div className="h-2 rounded bg-gray-800 overflow-hidden">
        <div
          className="h-full bg-emerald-500 transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 px-4 py-3">
      <div className={`text-2xl font-semibold ${tone || 'text-gray-100'}`}>
        {value.toLocaleString()}
      </div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  )
}

export default function SemanticMemorySection() {
  const { data, isLoading, error, reload } = useEndpointData<SemanticStatus>(
    '/api/admin/semantic-memory/status',
  )

  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">Semantic Memory</h2>
          <button
            onClick={reload}
            className="text-sm px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-200"
          >
            ↻ Refresh
          </button>
        </div>

        {data && !data.active && (
          <div className="bg-amber-900/30 border border-amber-800 rounded-lg px-4 py-3 text-sm text-amber-200">
            Semantic memory is not active{data.error ? `: ${data.error}` : ''}. The
            embedding pipeline may not be migrated/deployed yet.
          </div>
        )}

        {data && data.active && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm text-gray-400">
              <span>Active model:</span>
              <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-200 font-mono">
                {data.model || 'unknown'}
              </span>
            </div>

            {data.stats && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Stat label="Total chunks" value={data.stats.total} />
                <Stat label="Embedded" value={data.stats.done} tone="text-emerald-400" />
                <Stat label="Pending" value={data.stats.pending} tone="text-amber-400" />
                <Stat
                  label="Dead-lettered"
                  value={data.stats.dead}
                  tone={data.stats.dead > 0 ? 'text-red-400' : 'text-gray-100'}
                />
              </div>
            )}

            {data.coverage && (
              <div className="space-y-3 bg-[#0f0f1a] rounded-lg border border-gray-800 px-4 py-4">
                <Bar label="Messages" cov={data.coverage.messages} />
                <Bar label="Entities" cov={data.coverage.entities} />
              </div>
            )}

            {data.dead_letters && data.dead_letters.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-300 mb-2">
                  Recent failures ({data.dead_letters.length})
                </h3>
                <div className="space-y-2">
                  {data.dead_letters.map((d, i) => (
                    <div
                      key={`${d.source_type}-${d.source_id}-${i}`}
                      className="bg-[#0f0f1a] rounded-lg border border-red-900/50 px-4 py-2 text-xs"
                    >
                      <div className="flex items-center gap-2 text-gray-400">
                        <span className="px-1.5 py-0.5 rounded bg-gray-800">
                          {d.source_type} #{d.source_id}
                        </span>
                        <span className="text-gray-600">
                          {new Date(d.timestamp).toLocaleString()}
                        </span>
                      </div>
                      <div className="text-red-300 mt-1 break-words">{d.error}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <p className="text-xs text-gray-600">
              Pending chunks are embedded by the background worker (every ~2 min);
              coverage climbs over time as history is backfilled.
            </p>
          </>
        )}
      </div>
    </SectionStateGuard>
  )
}
