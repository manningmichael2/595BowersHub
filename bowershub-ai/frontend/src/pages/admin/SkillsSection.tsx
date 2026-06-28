import { useEndpointData, SectionStateGuard } from './AdminCommon'

export default function SkillsSection() {
  const { data, isLoading, error } = useEndpointData<any[]>('/api/skills')
  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && (
        <div>
          <h2 className="text-lg font-medium mb-4">Skills ({data.length})</h2>
          <div className="grid gap-3">
            {data.map((s: any) => (
              <div
                key={s.id}
                className="bg-background rounded-lg border border-border p-4"
              >
                <div className="flex justify-between items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-medium text-text">{s.name}</h3>
                      {s.restricted_users && s.restricted_users.length > 0 && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-warning/30 text-warning">
                          🔒 restricted
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-text-muted mt-1">{s.description}</p>
                    <div className="mt-2 text-xs text-text-muted font-mono break-all">
                      {s.http_method} {s.webhook_url}
                    </div>
                  </div>
                  <span
                    className={`text-xs px-2 py-0.5 rounded shrink-0 ${
                      s.is_active
                        ? 'bg-success/30 text-success'
                        : 'bg-danger/30 text-danger'
                    }`}
                  >
                    {s.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </SectionStateGuard>
  )
}
