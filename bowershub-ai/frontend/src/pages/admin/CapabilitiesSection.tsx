import { useState } from 'react'
import { api } from '../../services/api'
import { toast } from '../../stores/toast'
import { useEndpointData, SectionStateGuard } from './AdminCommon'

const ROLES = ['viewer', 'member', 'admin']

interface Capability {
  capability: string
  min_role: string
  description: string | null
}
interface Feature {
  feature_key: string
  label: string
  baseline_capability: string | null
  admin_only_floor: boolean
}

/**
 * Retune capability gates (min_role) without a code change or restart — the
 * NO-HARDCODING admin surface. A PATCH reloads the server's authz cache, so the
 * new policy is live immediately.
 */
export default function CapabilitiesSection() {
  const caps = useEndpointData<Capability[]>('/api/admin/capabilities')
  const features = useEndpointData<Feature[]>('/api/admin/features')
  const [savingCap, setSavingCap] = useState<string | null>(null)

  const retune = async (capability: string, min_role: string) => {
    setSavingCap(capability)
    try {
      await api.patch(`/api/admin/capabilities/${capability}`, { min_role })
      toast.success(`${capability} now requires ${min_role}`)
      await caps.reload()
    } catch (err: any) {
      toast.error(`Failed to retune ${capability}: ${err.response?.data?.detail || 'Unknown error'}`)
    } finally {
      setSavingCap(null)
    }
  }

  return (
    <SectionStateGuard isLoading={caps.isLoading} error={caps.error}>
      {caps.data && (
        <div className="space-y-6">
          <div>
            <h2 className="text-lg font-medium mb-1">Capabilities</h2>
            <p className="text-sm text-text-muted mb-3">
              The minimum role required for each gate. Changes take effect immediately.
            </p>
            <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto">
              <table className="w-full text-sm min-w-[560px]">
                <thead>
                  <tr className="border-b border-gray-800">
                    <th className="text-left px-4 py-3 text-gray-400 font-medium">Capability</th>
                    <th className="text-left px-4 py-3 text-gray-400 font-medium">Min role</th>
                    <th className="text-left px-4 py-3 text-gray-400 font-medium">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {caps.data.map(c => (
                    <tr key={c.capability} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-mono text-gray-300">{c.capability}</td>
                      <td className="px-4 py-3">
                        <select
                          aria-label={`Min role for ${c.capability}`}
                          value={c.min_role}
                          disabled={savingCap === c.capability}
                          onChange={e => retune(c.capability, e.target.value)}
                          className="bg-[#1a1a2e] border border-gray-700 rounded px-2 py-1 text-xs disabled:opacity-50"
                        >
                          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                      </td>
                      <td className="px-4 py-3 text-gray-500">{c.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {features.data && (
            <div>
              <h2 className="text-lg font-medium mb-1">Features</h2>
              <p className="text-sm text-text-muted mb-3">
                User-facing areas and their baseline capability. A floored feature can
                never be granted below admin.
              </p>
              <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto">
                <table className="w-full text-sm min-w-[480px]">
                  <thead>
                    <tr className="border-b border-gray-800">
                      <th className="text-left px-4 py-3 text-gray-400 font-medium">Feature</th>
                      <th className="text-left px-4 py-3 text-gray-400 font-medium">Baseline capability</th>
                      <th className="text-left px-4 py-3 text-gray-400 font-medium">Admin-only floor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {features.data.map(f => (
                      <tr key={f.feature_key} className="border-b border-gray-800/50">
                        <td className="px-4 py-3 text-gray-300">{f.label}</td>
                        <td className="px-4 py-3 font-mono text-gray-500">{f.baseline_capability}</td>
                        <td className="px-4 py-3">{f.admin_only_floor ? '🔒 Yes' : 'No'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </SectionStateGuard>
  )
}
