import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import ThemeBuilder from '../../components/ThemeBuilder'
import type { ThemeTokens } from '../../stores/settings'

interface ThemeListEntry {
  id: number
  name: string
  slug: string
  is_preset: boolean
  owner_id: number | null
  tokens_json: ThemeTokens
  is_default: boolean
}

export default function ThemeManagementSection() {
  const [themes, setThemes] = useState<ThemeListEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [builderOpen, setBuilderOpen] = useState(false)

  const loadThemes = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.get('/api/themes')
      const list: ThemeListEntry[] = Array.isArray(res.data)
        ? res.data
        : Array.isArray(res.data?.themes)
          ? res.data.themes
          : []
      setThemes(list)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load themes')
      setThemes([])
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadThemes()
  }, [])

  const setPlatformDefault = async (theme: ThemeListEntry) => {
    if (theme.is_default) return
    if (theme.owner_id != null) {
      setError('Only published (admin) themes can be set as the platform default.')
      return
    }
    setError(null)
    setActionMsg(null)
    setBusyId(theme.id)
    try {
      await api.post(`/api/themes/${theme.id}/set-platform-default`)
      setActionMsg(`Set "${theme.name}" as the platform default.`)
      await loadThemes()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to set platform default')
    } finally {
      setBusyId(null)
    }
  }

  const deleteTheme = async (theme: ThemeListEntry) => {
    if (theme.is_preset) {
      setError('Preset themes cannot be deleted.')
      return
    }
    if (
      !window.confirm(
        `Delete "${theme.name}"? Any users currently using this theme will fall back to the platform default.`,
      )
    ) {
      return
    }
    setError(null)
    setActionMsg(null)
    setBusyId(theme.id)
    try {
      const res = await api.delete(`/api/themes/${theme.id}`)
      const affected = res.data?.affected_user_count ?? 0
      setActionMsg(
        affected > 0
          ? `Deleted "${theme.name}". ${affected} user(s) reset to the platform default.`
          : `Deleted "${theme.name}".`,
      )
      await loadThemes()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete theme')
    } finally {
      setBusyId(null)
    }
  }

  const sorted = (themes ?? []).slice().sort((a, b) => {
    const groupA = a.is_preset ? 0 : a.owner_id == null ? 1 : 2
    const groupB = b.is_preset ? 0 : b.owner_id == null ? 1 : 2
    if (groupA !== groupB) return groupA - groupB
    return a.name.localeCompare(b.name)
  })

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-medium text-text">Theme Management</h2>
          <p className="text-sm text-text-muted mt-1">
            Manage published themes and the platform default. Personal themes
            owned by other users are not listed here.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setBuilderOpen(true)}
          className="px-3 py-1.5 rounded-lg bg-primary text-sm text-on-primary hover:bg-primary/90"
        >
          + New theme
        </button>
      </div>

      {actionMsg && (
        <div className="rounded-lg border border-success/40 bg-success/20 px-3 py-2 text-sm text-success">
          {actionMsg}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-danger/40 bg-danger/20 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {isLoading && themes == null ? (
        <div className="text-center text-text-muted py-12">Loading themes...</div>
      ) : sorted.length === 0 ? (
        <div className="text-sm text-text-muted italic">No themes available.</div>
      ) : (
        <div className="bg-background rounded-lg border border-border overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-text-muted font-medium">Theme</th>
                <th className="text-left px-4 py-3 text-text-muted font-medium">Type</th>
                <th className="text-left px-4 py-3 text-text-muted font-medium">Default</th>
                <th className="text-right px-4 py-3 text-text-muted font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(theme => {
                const tokens = theme.tokens_json || ({} as ThemeTokens)
                const isBusy = busyId === theme.id
                const canDelete = !theme.is_preset
                const canSetDefault = theme.owner_id == null && !theme.is_default
                return (
                  <tr key={theme.id} className="border-b border-border/50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div
                          className="h-8 w-12 rounded border flex overflow-hidden shrink-0"
                          style={{ borderColor: tokens.border || '#334155' }}
                        >
                          <div
                            className="flex-1"
                            style={{ background: tokens.background || '#0f172a' }}
                          />
                          <div
                            className="flex-1"
                            style={{ background: tokens.surface || '#1e293b' }}
                          />
                          <div
                            className="w-2"
                            style={{ background: tokens.primary || '#6366f1' }}
                          />
                          <div
                            className="w-2"
                            style={{ background: tokens.accent || '#8b5cf6' }}
                          />
                        </div>
                        <div className="min-w-0">
                          <div className="text-text font-medium truncate">
                            {theme.name}
                          </div>
                          <div className="text-xs text-text-muted font-mono truncate">
                            {theme.slug}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {theme.is_preset ? (
                        <span className="text-[10px] uppercase tracking-wider text-text-muted bg-surface-light/60 px-1.5 py-0.5 rounded">
                          Preset
                        </span>
                      ) : theme.owner_id == null ? (
                        <span className="text-[10px] uppercase tracking-wider text-primary bg-primary/40 px-1.5 py-0.5 rounded">
                          Published
                        </span>
                      ) : (
                        <span className="text-[10px] uppercase tracking-wider text-success bg-success/40 px-1.5 py-0.5 rounded">
                          Personal
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {theme.is_default ? (
                        <span className="text-warning text-xs">★ Platform default</span>
                      ) : (
                        <span className="text-text-muted text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex gap-2">
                        <button
                          type="button"
                          onClick={() => setPlatformDefault(theme)}
                          disabled={isBusy || !canSetDefault}
                          className="px-2.5 py-1 rounded bg-surface text-xs text-text-muted hover:bg-surface-light disabled:opacity-40 disabled:cursor-not-allowed"
                          title={
                            theme.is_default
                              ? 'Already the platform default'
                              : theme.owner_id != null
                                ? 'Only published themes can be set as default'
                                : 'Set as platform default'
                          }
                        >
                          {isBusy ? '…' : 'Set default'}
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteTheme(theme)}
                          disabled={isBusy || !canDelete}
                          className="px-2.5 py-1 rounded bg-danger/40 text-xs text-danger hover:bg-danger/90/60 disabled:opacity-40 disabled:cursor-not-allowed"
                          title={
                            theme.is_preset
                              ? 'Preset themes cannot be deleted'
                              : 'Delete theme'
                          }
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {builderOpen && (
        <ThemeBuilder
          onClose={() => setBuilderOpen(false)}
          onSave={async () => {
            setActionMsg('Theme saved.')
            await loadThemes()
          }}
        />
      )}
    </div>
  )
}
