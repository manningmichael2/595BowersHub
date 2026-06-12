import { useEndpointData, SectionStateGuard } from './AdminCommon'

export default function AuditSection() {
  const { data, isLoading, error } = useEndpointData<any[]>('/api/admin/audit?limit=50')
  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && (
        <div>
          {data.length === 0 ? (
            <div>
              <h2 className="text-lg font-medium mb-4">Audit Log</h2>
              <div className="text-center text-gray-500 py-12 bg-[#0f0f1a] rounded-lg border border-gray-800">
                No activity logged yet. Admin actions (creating users, modifying
                skills, etc.) will appear here.
              </div>
            </div>
          ) : (
            <div>
              <h2 className="text-lg font-medium mb-4">Recent Activity ({data.length})</h2>
              <div className="space-y-2">
                {data.map((entry: any) => (
                  <div
                    key={entry.id}
                    className="bg-[#0f0f1a] rounded-lg border border-gray-800 px-4 py-3 flex items-center gap-3 flex-wrap"
                  >
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400 shrink-0">
                      {entry.action}
                    </span>
                    <span className="text-sm text-gray-300 flex-1 min-w-0 truncate">
                      {entry.user_email || 'System'}
                    </span>
                    {entry.target_type && (
                      <span className="text-xs text-gray-500 shrink-0">
                        {entry.target_type} #{entry.target_id}
                      </span>
                    )}
                    <span className="text-xs text-gray-600 shrink-0">
                      {new Date(entry.created_at).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </SectionStateGuard>
  )
}
