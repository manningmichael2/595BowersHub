/**
 * Map a widget's REST `data_endpoint` to its key in the SSE cache
 * (`backend/services/dashboard_stream.py`). The publisher keys by the endpoint
 * function name (snake_case); the REST routes use slashes/hyphens — e.g.
 * `/api/dashboard/finance/recent-transactions` → `finance_recent_transactions`,
 * `/api/dashboard/system-health` → `system_health`.
 */
export function endpointToStreamKey(endpoint: string): string {
  return endpoint.replace(/^\/api\/dashboard\//, '').replace(/[/-]/g, '_')
}
