/**
 * ContextCapturePanel — Settings → Context Capture section.
 *
 * Context capture is a background pass that, after each exchange, extracts facts
 * the user explicitly stated and persists them to the workspace knowledge base
 * so the assistant remembers them. This panel exposes the per-user privacy
 * opt-out (`settings_json.context_capture_disabled`), honored in the backend's
 * hook engine before any capture runs.
 */
import { useSettingsStore } from '../stores/settings'
import { Switch } from './ui'

export default function ContextCapturePanel() {
  const settings = useSettingsStore((s) => s.settings)
  const patch = useSettingsStore((s) => s.patch)

  const disabled = !!settings.context_capture_disabled

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-text">Context Capture</h2>
        <p className="mt-1 text-sm text-text-muted">
          After each exchange, BowersHub can quietly save facts you explicitly
          stated — preferences, decisions, people, account details — so it
          remembers them in future conversations.
        </p>
      </div>

      <label className="flex items-start gap-3 rounded-xl border border-border bg-background/40 p-4">
        <Switch
          className="mt-0.5"
          aria-label="Enable context capture"
          checked={!disabled}
          onCheckedChange={(v) => patch({ context_capture_disabled: !v })}
        />
        <div>
          <div className="text-sm font-medium text-text">Capture context from my chats</div>
          <div className="mt-1 text-xs leading-relaxed text-text-muted">
            Only explicit statements are saved — never inferred or assumed. Turn
            off to stop capturing from your exchanges. Existing captured facts are
            not removed.
          </div>
        </div>
      </label>
    </div>
  )
}
