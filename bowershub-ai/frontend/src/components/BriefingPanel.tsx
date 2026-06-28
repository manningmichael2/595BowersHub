/**
 * BriefingPanel — Settings → Briefing section.
 *
 * Wires the two morning-card knobs that already existed in `settings_json` and
 * were honored end-to-end by the backend (routers/briefing.py) and the
 * `MorningCard` component, but had no UI:
 *   - `morning_card_disabled` — hide the morning briefing card entirely.
 *   - `morning_card_workspace_id` — which workspace the briefing summarizes.
 *     Null = automatic (the backend's default-workspace fallback).
 *
 * Both persist through `useSettingsStore.patch()` (optimistic + server-merged).
 */
import { useEffect } from 'react'
import { useSettingsStore } from '../stores/settings'
import { useWorkspaceStore } from '../stores/workspace'
import {
  Switch,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from './ui'

// Sentinel for the "Automatic" option — Radix Select values must be strings,
// and an empty value isn't allowed, so we use a named token and map it to null.
const AUTO = 'auto'

export default function BriefingPanel() {
  const settings = useSettingsStore((s) => s.settings)
  const patch = useSettingsStore((s) => s.patch)
  const workspaces = useWorkspaceStore((s) => s.workspaces)
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces)

  // The settings page can be reached without the workspace list having loaded
  // (e.g. deep-link); make sure the picker has options.
  useEffect(() => {
    if (workspaces.length === 0) fetchWorkspaces()
  }, [workspaces.length, fetchWorkspaces])

  const disabled = !!settings.morning_card_disabled
  const selected =
    settings.morning_card_workspace_id != null
      ? String(settings.morning_card_workspace_id)
      : AUTO

  const onSelectWorkspace = (value: string) => {
    patch({
      morning_card_workspace_id: value === AUTO ? null : Number(value),
    })
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-text">Briefing</h2>
        <p className="mt-1 text-sm text-text-muted">
          Your morning card — a daily summary shown at the top of the chat.
        </p>
      </div>

      <div className="space-y-4">
        <label className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background/40 p-4">
          <div>
            <div className="text-sm font-medium text-text">Show the morning card</div>
            <div className="mt-1 text-xs leading-relaxed text-text-muted">
              A daily briefing card at the top of your conversation. Turn off to hide it.
            </div>
          </div>
          <Switch
            aria-label="Show the morning card"
            checked={!disabled}
            onCheckedChange={(v) => patch({ morning_card_disabled: !v })}
          />
        </label>

        <div
          className={
            'rounded-xl border border-border bg-background/40 p-4 transition-opacity ' +
            (disabled ? 'pointer-events-none opacity-50' : '')
          }
        >
          <div className="mb-2 text-sm font-medium text-text">Briefing workspace</div>
          <div className="mb-3 text-xs leading-relaxed text-text-muted">
            Which workspace the briefing summarizes. Automatic uses your default
            briefing workspace.
          </div>
          <Select value={selected} onValueChange={onSelectWorkspace} disabled={disabled}>
            <SelectTrigger className="w-full sm:w-72" aria-label="Briefing workspace">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTO}>Automatic (default)</SelectItem>
              {workspaces.map((w) => (
                <SelectItem key={w.id} value={String(w.id)}>
                  {w.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  )
}
